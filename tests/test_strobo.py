"""Strobo-Grenze und übrige Wertprüfung."""
import pytest

from lichtsteuerung.buehne import Buehne
from lichtsteuerung.patch import Patch
from lichtsteuerung.pruefung import Pruefer, Vorgaben, hz_von
from lichtsteuerung.render import Eigenschaften, Renderer
from lichtsteuerung.sicherheit import BlitzWaechter, Grenzen, StroboWaechter

PAR_STROBO = 4     # Index des Strobo-Kanals beim Test-PAR


@pytest.fixture
def aufbau(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/par", "6", 1, "PAR")
    return patch, Pruefer(patch, Buehne(pfade.stage), Grenzen(3, 5, 30)), Renderer(patch)


def hz_im_bild(patch, bild):
    kanal = patch.katalog.typ("test/par").daten["kanaele"]["Strobo"]
    wert = bild[PAR_STROBO]
    bereich = next(b for b in kanal["bereiche"] if b["von"] <= wert <= b["bis"])
    return hz_von(bereich, wert) if bereich["typ"] == "strobo" else 0


ERLAUBT = Vorgaben(strobo_max_hz=2.0, strobo_max_dauer_s=5.0)


def test_erlaubtes_strobo_geht_durch(aufbau):
    patch, pruefer, renderer = aufbau
    bild = renderer.bild({"par": Eigenschaften(helligkeit=1, strobo_hz=2.0)})
    geprueft, meldungen, blitzt = pruefer.pruefe(bild, ERLAUBT, jetzt=0)
    assert blitzt and meldungen == []
    assert hz_im_bild(patch, geprueft) == pytest.approx(2.0, abs=0.1)


def test_strobo_ueber_profilgrenze_wird_gedeckelt(aufbau):
    patch, pruefer, renderer = aufbau
    bild = renderer.bild({"par": Eigenschaften(helligkeit=1, strobo_hz=15.0)})
    geprueft, meldungen, _ = pruefer.pruefe(bild, ERLAUBT, jetzt=0)
    assert hz_im_bild(patch, geprueft) <= 2.0 + 0.1
    assert "begrenzt" in meldungen[0]


def test_kein_profil_kann_die_feste_grenze_ueberschreiten(aufbau):
    patch, pruefer, renderer = aufbau
    wild = Vorgaben(strobo_max_hz=50.0, strobo_max_dauer_s=9999.0)
    bild = renderer.bild({"par": Eigenschaften(helligkeit=1, strobo_hz=20.0)})
    geprueft, _, _ = pruefer.pruefe(bild, wild, jetzt=0)
    assert hz_im_bild(patch, geprueft) <= 3.0 + 0.1      # Grenzen(3, ...) aus sicherheit.json


def test_rohwert_wird_auch_gedeckelt(aufbau):
    patch, pruefer, _ = aufbau
    bild = bytearray(512)
    bild[PAR_STROBO] = 255       # 20 Hz direkt ins Bild geschrieben
    geprueft, _, _ = pruefer.pruefe(bild, ERLAUBT, jetzt=0)
    assert hz_im_bild(patch, geprueft) <= 2.1


def test_profil_ohne_strobo_sperrt_jedes_blitzen(aufbau):
    patch, pruefer, renderer = aufbau
    bild = renderer.bild({"par": Eigenschaften(helligkeit=1, strobo_hz=2.0)})
    geprueft, _, blitzt = pruefer.pruefe(bild, Vorgaben(), jetzt=0)
    assert hz_im_bild(patch, geprueft) == 0 and not blitzt


def test_maximale_dauer_dann_pause(aufbau):
    patch, pruefer, renderer = aufbau
    bild = renderer.bild({"par": Eigenschaften(helligkeit=1, strobo_hz=2.0)})
    assert pruefer.pruefe(bild, ERLAUBT, jetzt=0.0)[2]
    assert pruefer.pruefe(bild, ERLAUBT, jetzt=4.9)[2]
    pruefer.pruefe(bild, ERLAUBT, jetzt=5.0)         # Dauer erreicht
    geprueft, _, blitzt = pruefer.pruefe(bild, ERLAUBT, jetzt=5.1)
    assert not blitzt and hz_im_bild(patch, geprueft) == 0
    assert not pruefer.pruefe(bild, ERLAUBT, jetzt=34.9)[2]   # noch in der Pause
    assert pruefer.pruefe(bild, ERLAUBT, jetzt=35.1)[2]       # 30 s Pause vorbei


def test_profil_kann_die_dauer_nur_verkuerzen(aufbau):
    _, pruefer, renderer = aufbau
    bild = renderer.bild({"par": Eigenschaften(helligkeit=1, strobo_hz=2.0)})
    lang = Vorgaben(strobo_max_hz=2.0, strobo_max_dauer_s=600.0)
    pruefer.pruefe(bild, lang, jetzt=0.0)
    pruefer.pruefe(bild, lang, jetzt=5.0)
    assert not pruefer.pruefe(bild, lang, jetzt=5.1)[2]


def test_unbekanntes_tempo_wird_gesperrt(pfade, katalog):
    # Der Testkopf hat wie der MH-X25 nur "slow bis fast" statt Hertz.
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf")
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("kopf", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend"})
    pruefer = Pruefer(patch, buehne, Grenzen(3, 5, 30))
    bild = bytearray(Renderer(patch).standard)
    bild[5] = 200
    geprueft, meldungen, blitzt = pruefer.pruefe(bild, ERLAUBT, jetzt=0)
    assert 4 <= geprueft[5] <= 7 and not blitzt      # Shutter offen
    assert "unbekannt" in meldungen[0]


def test_programm_kanal_bleibt_gesperrt(aufbau):
    _, pruefer, _ = aufbau
    bild = bytearray(512)
    bild[5] = 200
    assert pruefer.pruefe(bild, Vorgaben(), jetzt=0)[0][5] == 0


def test_wert_ohne_bereich_faellt_auf_standard(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf")
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("kopf", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend"})
    pruefer = Pruefer(patch, buehne, Grenzen(3, 5, 30))
    bild = bytearray(Renderer(patch).standard)
    bild[6] = 200       # Farbrad kennt nur 0-29
    assert pruefer.pruefe(bild, Vorgaben(), jetzt=0)[0][6] == 0


def test_hazer_nur_wenn_erlaubt(pfade, katalog):
    eintrag = {"id": "test/dunst", "hersteller": "T", "name": "Dunst",
               "kanaele": {"Nebel": {"typ": "nebel", "standard": 0}},
               "modi": [{"name": "1", "kanaele": ["Nebel"]}], "quelle": {"art": "test"}}
    katalog.speichere_eigenen(eintrag)
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/dunst", "1", 1, "D")
    pruefer = Pruefer(patch, Buehne(pfade.stage), Grenzen(3, 5, 30))
    bild = Renderer(patch).bild({"d": Eigenschaften(nebel=0.5)})
    assert pruefer.pruefe(bild, Vorgaben(), jetzt=0)[0][0] == 0
    assert pruefer.pruefe(bild, Vorgaben(hazer_erlaubt=True), jetzt=0)[0][0] > 100


def test_strobo_waechter_ruht_ohne_blitzen():
    w = StroboWaechter()
    w.melde(True, 0, 5, 30)
    w.melde(False, 1, 5, 30)
    w.melde(True, 2, 5, 30)
    w.melde(True, 6.9, 5, 30)
    assert w.erlaubt(6.9)


def test_blitzwaechter_bremst_schnelles_helldunkel():
    w = BlitzWaechter()
    gesehen = []
    # 10 Wechsel pro Sekunde zwischen dunkel und hell, 2 Sekunden lang
    for schritt in range(40):
        zeit = schritt * 0.05
        gesehen.append(w.begrenze("par", 1.0 if schritt % 2 else 0.0, zeit, 3))
    spruenge = sum(1 for a, b in zip(gesehen, gesehen[1:]) if b - a > 0.4)
    assert spruenge <= 3 * 2 + 1


def test_blitzwaechter_laesst_langsames_atmen_durch():
    w = BlitzWaechter()
    werte = [0.5 + 0.2 * ((i % 40) / 40) for i in range(200)]
    assert [w.begrenze("par", h, i * 0.025, 3) for i, h in enumerate(werte)] == werte
