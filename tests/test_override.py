"""Override-Tasten und Rückfall: im echten Bild-Ablauf der Show."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung.audio.analyse import Messwerte
from lichtsteuerung.buehne import Buehne
from lichtsteuerung.daten import schreibe_json
from lichtsteuerung.dmx_ausgabe import DmxAusgabe
from lichtsteuerung.patch import Patch
from lichtsteuerung.profile import pruefe_profil, strobo_grenzen
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show
from lichtsteuerung.sicherheit import Grenzen

GRUND = {"werte": [{"gruppe": "Farb-PARs", "farbe": "gold", "helligkeit": 0.4}]}
PARTY = {"name": "Party", "palette": ["rot", "blau"], "max_helligkeit": 1.0, "bewegung": "voll",
         "beat_reaktion": 1.0, "strobo": {"max_blitze_pro_sekunde": 3, "max_dauer_s": 4},
         "hazer": True, "grundlicht": GRUND}
MUSIK = Messwerte(tempo_bpm=120, bass=0.9, energie=0.8, leise=False)
DIMMER, ROT, BLAU, STROBO = 0, 1, 3, 4


class FesterTon:
    """Tut so, als käme laufend Musik."""
    name = "fest"
    beat_erkennung = "test"
    beat_zaehler = 0
    fehler = None
    werte = MUSIK

    def aktuell(self, jetzt=None):
        return self.werte

    def stoppen(self):
        pass


@pytest.fixture
def show(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/par", "6", 2, "PAR 1-2", gruppen=["Farb-PARs"])
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf", gruppen=["Spots"])
    patch.speichern()
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("kopf", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend",
                                 "drehung_grad": 180})
    buehne.speichern()
    pfade.profile.mkdir()
    schreibe_json(pfade.profile / "party.json", PARTY)
    s = Show(pfade)
    s.profil_laden("Party")
    s.audio = FesterTon()
    return s


def einschwingen(show):
    bild = None
    for i in range(120):
        bild = show.baue_bild(i / 40)
    return bild, 3.0


def test_musik_macht_licht(show):
    bild, _ = einschwingen(show)
    assert bild[DIMMER] > 150


def test_blackout_schlaegt_alles(show):
    einschwingen(show)
    show.overrides.blackout = True
    show.test_kanaele = {1: 255, 2: 255}      # auch rohe Testwerte
    bild = show.baue_bild(4.0)
    for start in (0, 6):
        assert bild[start + DIMMER] == 0 and bild[start + ROT] == 0
    assert bild[16] == 0                      # Dimmer vom Kopf


def test_warmweiss_schlaegt_die_automatik(show):
    einschwingen(show)
    show.overrides.warmweiss = True
    bild = show.baue_bild(4.0)
    assert bild[DIMMER] == round(0.7 * 255)
    assert bild[ROT] == 255 and bild[BLAU] == pytest.approx(160, abs=2)


def test_blackout_schlaegt_warmweiss(show):
    show.overrides.warmweiss = show.overrides.blackout = True
    assert show.baue_bild(0.0)[DIMMER] == 0


def test_pause_blendet_aufs_grundlicht(show):
    _, zeit = einschwingen(show)
    show.overrides.pause = True
    for i in range(120):
        bild = show.baue_bild(zeit + i / 40)
    assert bild[DIMMER] == round(0.4 * 255)


def test_strobo_aus_sperrt_auch_ein_erlaubtes_profil(show):
    show.test_kanaele = {5: 30}              # 2,5 Hz: im Profil erlaubt
    show.baue_bild(0.0)
    assert show.blitzt
    show.overrides.strobo_aus = True
    assert show.baue_bild(0.1)[STROBO] == 0 and not show.blitzt


def test_max_helligkeit_des_profils_begrenzt_den_ausgang(show):
    show.profil = {**PARTY, "max_helligkeit": 0.3}
    bild, _ = einschwingen(show)
    assert bild[DIMMER] <= round(0.3 * 255)


def test_analyse_faellt_aus_grundlicht_statt_blackout(show):
    einschwingen(show)
    show.audio.werte = None
    bild = show.baue_bild(4.0)
    assert bild[DIMMER] == round(0.4 * 255)


def test_fehler_in_der_engine_fuehrt_zum_grundlicht(show):
    einschwingen(show)
    original = show.engine.bewerte

    def kaputt(messwerte, *argumente):
        if messwerte is not None:
            raise RuntimeError("Bug")
        return original(messwerte, *argumente)

    show.engine.bewerte = kaputt
    assert show.baue_bild(4.0)[DIMMER] == round(0.4 * 255)


def test_notbild_haelt_und_blackout_bleibt(show):
    bild, _ = einschwingen(show)
    assert show.notbild() == bild
    show.overrides.blackout = True
    assert show.notbild() == bytes(512)


def test_hazer_folgt_dem_profil(show, katalog):
    assert show.profil["hazer"] is True
    assert show._vorgaben().hazer_erlaubt
    show.overrides.blackout = True
    assert not show._vorgaben().hazer_erlaubt


def test_neustart_laedt_letztes_profil_und_dmx_bleibt_aus(show, pfade):
    neu = Show(pfade, DmxAusgabe())
    assert neu.profil["name"] == "Party"
    assert not neu.ausgabe.eingeschaltet


def test_fehlendes_letztes_profil_stoert_den_start_nicht(show, pfade):
    (pfade.profile / "party.json").unlink()
    assert Show(pfade).profil["name"].startswith("Ruhe")


def test_ohne_sicherheitsdatei_startet_nichts(pfade):
    pfade.sicherheit.unlink()
    with pytest.raises(FileNotFoundError):
        Show(pfade)


@pytest.mark.parametrize("aenderung, teil", [
    ({"palette": []}, "Palette"),
    ({"palette": ["blubb"]}, "Farbe"),
    ({"max_helligkeit": 2}, "max_helligkeit"),
    ({"beat_reaktion": -1}, "beat_reaktion"),
    ({"bewegung": "wild"}, "bewegung"),
    ({"strobo": "an"}, "strobo"),
    ({"strobo": {"max_blitze_pro_sekunde": 0, "max_dauer_s": 2}}, "max_blitze"),
    ({"grundlicht": {"werte": []}}, "Grundlicht"),
    ({"hazer": "ja"}, "hazer"),
])
def test_kaputte_profile_werden_abgelehnt(aenderung, teil):
    assert any(teil in f for f in pruefe_profil({**PARTY, **aenderung}))


def test_profil_mit_unbekannter_gruppe_wird_abgelehnt():
    assert pruefe_profil(PARTY, ["Spots"])


def test_profil_kommt_nicht_ueber_die_feste_grenze():
    wild = {**PARTY, "strobo": {"max_blitze_pro_sekunde": 100, "max_dauer_s": 999}}
    assert strobo_grenzen(wild, Grenzen(3, 5, 30)) == (3, 5)


def test_alle_mitgelieferten_profile_sind_gueltig():
    from lichtsteuerung.daten import PROJEKT
    from lichtsteuerung.profile import Profile
    profile = Profile(PROJEKT / "profile")
    assert len(profile.namen()) == 4
    for name in profile.namen():
        profile.laden(name)


def test_tasten_ueber_den_server(pfade):
    with TestClient(erstelle_app(Show(pfade))) as client:
        assert client.post("/api/override/blackout").json()["blackout"] is True
        assert client.post("/api/override/blackout").json()["blackout"] is False
        assert client.post("/api/override/unsinn").status_code == 400


def test_warmweiss_richtet_spots_auf_die_mitte(show):
    show.overrides.warmweiss = True
    bild = show.baue_bild(0.0)
    kopf = next(g for g in show.simulator.lies(bild) if g["id"] == "kopf")
    assert kopf["hell"] == pytest.approx(0.7, abs=0.01) and kopf["richtung"][2] < -0.3


def test_patch_aenderung_setzt_die_strobo_dauer_nicht_zurueck(show):
    show.pruefer.strobo.start = 1.0
    show.pruefer.strobo.gesperrt_bis = 99.0
    show.aufbauen()
    assert show.pruefer.strobo.gesperrt_bis == 99.0


def test_vergessener_dmx_test_endet_von_selbst(show):
    import time
    show.test_setzen("par-1", {})
    show.test_seit = time.monotonic() - 1000
    show.baue_bild(0.0)
    assert show.test_geraet is None and not show._test_laeuft()


def test_blitzwaechter_gilt_auch_im_bild(show):
    """Eine Cue-Ebene, die Hell und Dunkel im 20-Hz-Takt wechselt, wird gebremst."""
    show.audio.werte = None
    spruenge, vorher = 0, 0
    for i in range(80):
        show.zustand_test = None
        show._automatik = lambda _j, h=(255 if i % 2 else 0): {
            "par-1": __import__("lichtsteuerung.render", fromlist=["x"]).Eigenschaften(helligkeit=h / 255)}
        wert = show.baue_bild(i * 0.025)[DIMMER]
        if wert - vorher > 100:
            spruenge += 1
        vorher = wert
    assert spruenge <= 7       # 2 Sekunden lang höchstens 3 pro Sekunde
