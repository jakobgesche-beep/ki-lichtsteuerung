"""Die Regeln der Engine: Ton rein, Eigenschaften raus."""
import pytest

from lichtsteuerung.audio.analyse import Messwerte
from lichtsteuerung.buehne import Buehne
from lichtsteuerung.engine import Engine
from lichtsteuerung.farben import farbe
from lichtsteuerung.patch import Patch
from lichtsteuerung.sicherheit import Grenzen

GRUND = {"werte": [{"gruppe": "Farb-PARs", "farbe": "warmweiss", "helligkeit": 0.4}]}
PARTY = {"name": "Party", "palette": ["rot", "blau", "gruen"], "max_helligkeit": 1.0, "bewegung": "voll",
         "beat_reaktion": 1.0, "strobo": {"max_blitze_pro_sekunde": 2, "max_dauer_s": 3},
         "hazer": False, "grundlicht": GRUND}
MUSIK = dict(tempo_bpm=120, bass=0.8, energie=0.7, leise=False)


@pytest.fixture
def engine(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/par", "6", 2, "PAR 1-2", gruppen=["Farb-PARs"])
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf", gruppen=["Spots", "Effektlicht"])
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("kopf", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend",
                                 "drehung_grad": 180})
    return Engine(patch, buehne, {"Mitte": {"x": 0, "y": 2, "z": 2.4}}, Grenzen(3, 5, 30))


def einschwingen(engine, profil, werte, von=0.0, dauer=3.0):
    """Lässt die Engine laufen, bis der Übergang zum Musik-Licht fertig ist."""
    schritte = int(dauer * 40)
    ergebnis = None
    for i in range(schritte):
        ergebnis = engine.bewerte(werte, profil, von + i / 40)
    return ergebnis, von + dauer


def test_ohne_analyse_grundlicht_und_kein_blackout(engine):
    zustand = engine.bewerte(None, PARTY, 0.0)
    assert zustand["par-1"].helligkeit == pytest.approx(0.4)
    assert zustand["par-1"].farbe == farbe("warmweiss")


def test_ausfall_mitten_in_der_musik_geht_sofort_aufs_grundlicht(engine):
    einschwingen(engine, PARTY, Messwerte(**MUSIK))
    zustand = engine.bewerte(None, PARTY, 10.0)
    assert zustand["par-1"].helligkeit == pytest.approx(0.4)
    assert zustand["kopf"].strobo_hz == 0 if "kopf" in zustand else True


def test_beat_gibt_farbschritt(engine):
    _, zeit = einschwingen(engine, PARTY, Messwerte(**MUSIK))
    vorher = engine.bewerte(Messwerte(**MUSIK), PARTY, zeit)["par-1"].farbe
    nachher = engine.bewerte(Messwerte(beat=True, **MUSIK), PARTY, zeit + 1)["par-1"].farbe
    assert vorher != nachher and nachher in [farbe(f) for f in PARTY["palette"]]


def test_farbschritte_nie_schneller_als_die_grenze(engine):
    _, zeit = einschwingen(engine, PARTY, Messwerte(**MUSIK))
    start = engine.farb_schritt
    for i in range(40):       # 20 Beats pro Sekunde, 2 Sekunden lang
        engine.bewerte(Messwerte(beat=True, **MUSIK), PARTY, zeit + i * 0.05)
    assert engine.farb_schritt - start <= 7


def test_bass_steuert_helligkeit(engine):
    _, zeit = einschwingen(engine, PARTY, Messwerte(**MUSIK))
    tief = engine.bewerte(Messwerte(**{**MUSIK, "bass": 0.0}), PARTY, zeit)["par-1"].helligkeit
    hoch = engine.bewerte(Messwerte(**{**MUSIK, "bass": 1.0}), PARTY, zeit + 0.01)["par-1"].helligkeit
    assert hoch > tief * 2


def test_max_helligkeit_gilt_auch_fuer_das_grundlicht(engine):
    dunkel = {**PARTY, "max_helligkeit": 0.2}
    assert engine.bewerte(None, dunkel, 0.0)["par-1"].helligkeit == pytest.approx(0.2)
    zustand, _ = einschwingen(engine, dunkel, Messwerte(**{**MUSIK, "bass": 1.0}))
    assert max(e.helligkeit for e in zustand.values()) <= 0.2 + 1e-9


def test_hohe_energie_bewegt_die_spots(engine):
    werte = Messwerte(**{**MUSIK, "energie": 0.9})
    a, zeit = einschwingen(engine, PARTY, werte)
    b, _ = einschwingen(engine, PARTY, werte, von=zeit, dauer=0.5)
    assert a["kopf"].pan is not None and a["kopf"].pan != b["kopf"].pan


def test_viel_energie_bewegt_groesser_als_wenig(engine):
    engine.beats, engine.phase = 32, 2.0       # Muster "Kreuz", Bewegung ganz außen
    klein = abs(engine._muster(0, 8, 0.45)[0])
    assert abs(engine._muster(0, 8, 1.0)[0]) > 2 * klein * 0.99 > 0


def test_profil_ohne_bewegung(engine):
    profil = {**PARTY, "bewegung": "aus"}
    werte = Messwerte(**{**MUSIK, "energie": 0.9})
    a, zeit = einschwingen(engine, profil, werte)
    b, _ = einschwingen(engine, profil, werte, von=zeit, dauer=0.5)
    assert a["kopf"].pan == b["kopf"].pan


def test_ruhende_spots_zeigen_auf_die_buehne_und_nicht_nach_oben(engine):
    from lichtsteuerung.pantilt import Montage, richtung
    zustand, _ = einschwingen(engine, {**PARTY, "bewegung": "aus"}, Messwerte(**{**MUSIK, "energie": 0.2}))
    e = zustand["kopf"]
    strahl = richtung(Montage.aus_buehne(engine.buehne.geraet("kopf")), e.pan, e.tilt)
    assert strahl[2] < 0


def test_leise_stelle_blendet_zum_grundlicht(engine):
    _, zeit = einschwingen(engine, PARTY, Messwerte(**MUSIK))
    zustand, _ = einschwingen(engine, PARTY, Messwerte(leise=True), von=zeit)
    assert zustand["par-1"].helligkeit == pytest.approx(0.4)


def test_rede_gibt_grundlicht(engine):
    _, zeit = einschwingen(engine, PARTY, Messwerte(**MUSIK))
    zustand, _ = einschwingen(engine, PARTY, Messwerte(leise=False, rede=True), von=zeit)
    assert zustand["par-1"].farbe == farbe("warmweiss")


def test_automatik_aus_im_theaterprofil(engine):
    theater = {**PARTY, "beat_reaktion": 0.0, "bewegung": "aus"}
    zustand, _ = einschwingen(engine, theater, Messwerte(beat=True, **MUSIK))
    assert zustand["par-1"].farbe == farbe("warmweiss")


def test_strobo_erst_nach_langer_hoher_energie_und_nur_wenn_erlaubt(engine):
    werte = Messwerte(**{**MUSIK, "energie": 0.95})
    zustand, zeit = einschwingen(engine, PARTY, werte, dauer=1.0)
    assert zustand["kopf"].strobo_hz == 0
    zustand, _ = einschwingen(engine, PARTY, werte, von=zeit, dauer=2.0)
    assert zustand["kopf"].strobo_hz == 2
    zustand, _ = einschwingen(engine, {**PARTY, "strobo": "aus"}, werte, von=zeit + 2, dauer=4.0)
    assert zustand["kopf"].strobo_hz == 0


# Nachgestellt: Nur Moving Heads im Patch, das Grundlicht kennt aber nur Farb-PARs.

@pytest.fixture
def nur_spots(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/kopf", "7", 2, "Front 1-2", gruppen=["Frontlicht", "Spots"])
    buehne = Buehne(pfade.stage)
    for geraet, x in (("front-1", -3.5), ("front-2", 3.5)):
        buehne.setze_geraet(geraet, {"ort": "stativ", "x": x, "y": -1, "z": 2.5, "montage": "stehend"})
    return Engine(patch, buehne, {}, Grenzen(3, 5, 30))


def test_nur_moving_heads_bleiben_ohne_ton_nicht_dunkel(nur_spots):
    zustand = nur_spots.bewerte(None, PARTY, 0.0)
    assert all(e.helligkeit == 0.5 and e.pan is not None for e in zustand.values())


def test_nur_moving_heads_reagieren_auf_musik(nur_spots):
    zustand, _ = einschwingen(nur_spots, PARTY, Messwerte(**{**MUSIK, "energie": 0.9}))
    assert all(e.helligkeit > 0.5 and e.farbe in [farbe(f) for f in PARTY["palette"]] for e in zustand.values())


def test_geraet_ohne_gruppe_zaehlt_nach_seinen_faehigkeiten(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf")
    patch.hinzufuegen("test/par", "6", 1, "Par")
    assert [g["id"] for g in patch.in_gruppe("Spots")] == ["kopf"]
    assert [g["id"] for g in patch.in_gruppe("Farb-PARs")] == ["par"]


def test_spots_wechseln_sich_auf_dem_beat_ab(nur_spots):
    _, zeit = einschwingen(nur_spots, PARTY, Messwerte(**{**MUSIK, "energie": 0.1}))
    a = nur_spots.bewerte(Messwerte(beat=True, **{**MUSIK, "energie": 0.1}), PARTY, zeit)
    b = nur_spots.bewerte(Messwerte(beat=True, **{**MUSIK, "energie": 0.1}), PARTY, zeit + 0.5)
    assert (a["front-1"].helligkeit > a["front-2"].helligkeit) != (b["front-1"].helligkeit > b["front-2"].helligkeit)


def test_farbe_blendet_weich_ueber(engine):
    _, zeit = einschwingen(engine, PARTY, Messwerte(**MUSIK))
    vorher = engine.bewerte(Messwerte(**MUSIK), PARTY, zeit)["par-1"].farbe
    gleich_danach = engine.bewerte(Messwerte(beat=True, **MUSIK), PARTY, zeit + 0.025)["par-1"].farbe
    assert gleich_danach != vorher and gleich_danach not in [farbe(f) for f in PARTY["palette"]]


def test_bewegung_springt_nicht(nur_spots):
    werte = Messwerte(**{**MUSIK, "energie": 0.9})
    letzte, groesster = None, 0.0
    for i in range(40 * 40):           # 40 Sekunden, also mehrere Musterwechsel
        m = Messwerte(beat=i % 20 == 0, **{**MUSIK, "energie": 0.9})
        pan = nur_spots.bewerte(m, PARTY, i / 40).get("front-1").pan
        if letzte is not None and i > 80:
            groesster = max(groesster, abs(pan - letzte))
        letzte = pan
    assert groesster <= 5.01    # 200 Grad pro Sekunde bei 40 Bildern


def test_muster_bleiben_auf_der_buehne(nur_spots):
    masse = nur_spots.buehne.daten["buehne"]
    for beats in range(0, 64, 16):
        nur_spots.beats = beats
        for i in range(200):
            nur_spots.phase = i / 10
            for nummer in (0, 1, 2):
                x, y = nur_spots._muster(nummer, 8, 1.0)
                assert abs(x) <= masse["breite_m"] / 2 and 0 <= y <= masse["tiefe_m"]


def test_gobos_wechseln_alle_8_beats_und_drehen(pfade, katalog):
    from lichtsteuerung.importe.gemeinsam import speichere_import
    from lichtsteuerung.importe import qxf
    from pathlib import Path
    speichere_import(qxf.wandle((Path(__file__).parent / "beispiele/Varytec-Hero-Spot-60.qxf").read_bytes()), pfade.katalog)
    katalog.neu_laden()
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("varytec/hero-spot-60", "14 Channel", 1, "Spot", gruppen=["Spots"])
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("spot", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend", "drehung_grad": 180})
    e = Engine(patch, buehne, {}, Grenzen(3, 5, 30))
    z, _ = einschwingen(e, PARTY, Messwerte(**MUSIK))
    assert z["spot"].gobo == "Gobo 1" and z["spot"].gobo_drehung
    e.beats = 8
    z = e.bewerte(Messwerte(**MUSIK), PARTY, 4.0)
    assert z["spot"].gobo == "Gobo 2"
    from lichtsteuerung.render import Renderer
    bild = Renderer(patch).bild(z)
    assert 27 <= bild[8] <= 43 and bild[9] >= 10     # Gobo 2, Drehung läuft


def test_profil_mit_wenig_reaktion_bleibt_ruhig(nur_spots):
    ruhig = {**PARTY, "beat_reaktion": 0.15, "bewegung": "langsam"}
    z, _ = einschwingen(nur_spots, ruhig, Messwerte(beat=True, **MUSIK))
    assert z["front-1"].gobo is None
