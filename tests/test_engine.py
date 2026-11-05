"""Die Regeln der Engine: Ton rein, Eigenschaften raus."""
import pytest

from lichtsteuerung.audio.analyse import Messwerte
from lichtsteuerung.buehne import Buehne
from lichtsteuerung.engine import LOOKS, Engine
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


def test_max_helligkeit_gilt_auch_fuer_das_grundlicht(engine):
    dunkel = {**PARTY, "max_helligkeit": 0.2}
    assert engine.bewerte(None, dunkel, 0.0)["par-1"].helligkeit == pytest.approx(0.2)
    zustand, _ = einschwingen(engine, dunkel, Messwerte(**{**MUSIK, "bass": 1.0}))
    assert max(e.helligkeit for e in zustand.values()) <= 0.2 + 1e-9


def test_viel_energie_bewegt_groesser_als_wenig(engine):
    engine.beats, engine.phase = 16, 2.0       # Muster "Kreuz", Bewegung ganz außen
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
    erzwinge(nur_spots, "Stehen")
    a = nur_spots.bewerte(Messwerte(beat=True, **{**MUSIK, "energie": 0.1}), PARTY, zeit)
    b = nur_spots.bewerte(Messwerte(beat=True, **{**MUSIK, "energie": 0.1}), PARTY, zeit + 0.5)
    assert (a["front-1"].helligkeit > a["front-2"].helligkeit) != (b["front-1"].helligkeit > b["front-2"].helligkeit)


def test_bewegung_springt_nicht(nur_spots):
    werte = Messwerte(**{**MUSIK, "energie": 0.9})
    letzte, groesster = None, 0.0
    for i in range(40 * 40):           # 40 Sekunden, also mehrere Musterwechsel
        m = Messwerte(beat=i % 20 == 0, **{**MUSIK, "energie": 0.9})
        pan = nur_spots.bewerte(m, PARTY, i / 40).get("front-1").pan
        if letzte is not None and i > 80:
            groesster = max(groesster, abs(pan - letzte))
        letzte = pan
    assert groesster <= 4.51    # 180 Grad pro Sekunde bei 40 Bildern


def test_muster_bleiben_auf_der_buehne(nur_spots):
    masse = nur_spots.buehne.daten["buehne"]
    for beats in range(0, 64, 16):
        nur_spots.beats = beats
        for i in range(200):
            nur_spots.phase = i / 10
            for nummer in (0, 1, 2):
                x, y = nur_spots._muster(nummer, 8, 1.0)
                assert abs(x) <= masse["breite_m"] / 2 and 0 <= y <= masse["tiefe_m"]


def test_profil_mit_wenig_reaktion_bleibt_ruhig(nur_spots):
    ruhig = {**PARTY, "beat_reaktion": 0.15, "bewegung": "langsam"}
    z, _ = einschwingen(nur_spots, ruhig, Messwerte(beat=True, **MUSIK))
    assert z["front-1"].gobo is None



# --- Looks: Ruhe statt Dauerwechsel ------------------------------------------------

def look(name):
    return next(l for l in LOOKS if l.name == name)


def erzwinge(engine, name):
    """Setzt einen Look von Hand, als hätte die Engine ihn gerade gewählt."""
    engine.look, engine.look_seit = look(name), engine.beats
    engine.look_nummer = max(engine.look_nummer, 1)


def beats_spielen(engine, profil, anzahl, energie, von=0.0, bpm=120, **werte):
    """Spielt Beats im Takt. Gibt (Zeit, Liste der Looks pro Beat) zurück."""
    abstand = 60 / bpm
    looks = []
    zeit = von
    for _ in range(anzahl):
        for schritt in range(int(abstand * 40)):
            m = Messwerte(beat=schritt == 0, tempo_bpm=bpm, energie=energie, leise=False, bass=werte.get("bass", 0.5))
            engine.bewerte(m, profil, zeit)
            zeit += 1 / 40
        looks.append(engine.look.name)
    return zeit, looks


def test_startet_gleich_mit_passendem_look(engine):
    beats_spielen(engine, PARTY, 2, 0.9)
    assert engine.look.stufe == 3


def test_look_bleibt_mindestens_eine_phrase_stehen(engine):
    zeit, looks = beats_spielen(engine, PARTY, 4, 0.5)
    erster = engine.look
    # Energie springt mitten in der Phrase hin und her: Der Look bleibt.
    for energie in (0.7, 0.45, 0.7, 0.45):
        zeit, neu = beats_spielen(engine, PARTY, 2, energie, von=zeit)
        looks += neu
    assert set(looks[2:12]) == {erster.name}


def test_mehr_energie_wechselt_am_ende_der_phrase(engine):
    zeit, _ = beats_spielen(engine, PARTY, 4, 0.5)
    alt = engine.look
    zeit, looks = beats_spielen(engine, PARTY, 30, 0.7, von=zeit)
    assert engine.look.stufe == 2 and engine.look != alt
    wechsel = next(i for i, name in enumerate(looks) if name != alt.name) + 4
    assert wechsel >= 16                     # nicht vor dem Ende der Phrase


def test_drop_wechselt_sofort_mit_akzent(engine):
    start, _ = beats_spielen(engine, PARTY, 20, 0.3)
    zeit, looks = beats_spielen(engine, PARTY, 6, 0.95, von=start)
    assert engine.look.stufe == 3 and looks.index(engine.look.name) <= 1     # sofort, nicht erst nach der Phrase
    assert start <= engine.letzter_akzent < start + 1.5                       # mit einem hellen Akzent


def test_farben_wechseln_hoechstens_alle_4_beats(engine):
    zeit, _ = beats_spielen(engine, PARTY, 1, 0.65)
    erzwinge(engine, "Stehen mit Akzent")
    farben = []
    for beat in range(16):
        zeit, _ = beats_spielen(engine, PARTY, 1, 0.65, von=zeit)
        farben.append(engine.bewerte(Messwerte(tempo_bpm=120, energie=0.65, leise=False), PARTY, zeit)["kopf"].farbe)
    wechsel = sum(1 for a, b in zip(farben, farben[1:]) if a != b)
    assert 2 <= wechsel <= 4


def test_stehender_look_bewegt_sich_nicht(engine):
    zeit, _ = beats_spielen(engine, PARTY, 2, 0.5)
    erzwinge(engine, "Stehen")
    zeit, _ = beats_spielen(engine, PARTY, 4, 0.5, von=zeit)
    a = engine.bewerte(Messwerte(tempo_bpm=120, energie=0.5, leise=False), PARTY, zeit)["kopf"]
    _, _ = beats_spielen(engine, PARTY, 4, 0.5, von=zeit + 0.025)
    b = engine.bewerte(Messwerte(tempo_bpm=120, energie=0.5, leise=False), PARTY, zeit + 2.1)["kopf"]
    assert a.pan == pytest.approx(b.pan, abs=0.01) and a.tilt == pytest.approx(b.tilt, abs=0.01)


def test_bewegter_look_bewegt_sich_weich(engine):
    einschwingen(engine, PARTY, Messwerte(**{**MUSIK, "energie": 0.9}))
    erzwinge(engine, "Kreis")
    pans = []
    for i in range(160):
        pans.append(engine.bewerte(Messwerte(beat=i % 20 == 0, tempo_bpm=120, energie=0.9, leise=False), PARTY, 3 + i / 40)["kopf"].pan)
    assert max(pans) - min(pans) > 10
    assert max(abs(a - b) for a, b in zip(pans[20:], pans[21:])) <= 4.6


def test_puls_auf_dem_beat_und_akzent_auf_der_eins(engine):
    zeit, _ = beats_spielen(engine, PARTY, 4, 0.65, bass=0.0)
    erzwinge(engine, "Stehen mit Akzent")
    engine.letzter_akzent = -99
    zeit, _ = beats_spielen(engine, PARTY, 3 - engine.beats % 4 if engine.beats % 4 != 3 else 4, 0.65, von=zeit, bass=0.0)
    erzwinge(engine, "Stehen mit Akzent")
    engine.letzter_akzent = -99
    zwischen = engine.bewerte(Messwerte(tempo_bpm=120, energie=0.65, leise=False, bass=0.0), PARTY, zeit + 0.2)["kopf"].helligkeit
    engine.bewerte(Messwerte(beat=True, tempo_bpm=120, energie=0.65, leise=False, bass=0.0), PARTY, zeit + 0.25)
    auf_eins = engine.bewerte(Messwerte(tempo_bpm=120, energie=0.65, leise=False, bass=0.0), PARTY, zeit + 0.3)
    assert engine.beats % 4 == 0
    assert auf_eins["kopf"].helligkeit > 0.9 > zwischen


def test_gobo_bleibt_im_look_und_wechselt_mit_dem_look(pfade, katalog):
    from pathlib import Path
    from lichtsteuerung.importe import qxf
    from lichtsteuerung.importe.gemeinsam import speichere_import
    speichere_import(qxf.wandle((Path(__file__).parent / "beispiele/Varytec-Hero-Spot-60.qxf").read_bytes()), pfade.katalog)
    katalog.neu_laden()
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("varytec/hero-spot-60", "14 Channel", 1, "Spot", gruppen=["Spots"])
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("spot", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend", "drehung_grad": 180})
    e = Engine(patch, buehne, {}, Grenzen(3, 5, 30))
    zeit, _ = beats_spielen(e, PARTY, 2, 0.65)
    erzwinge(e, "Kreuz")
    gobos = set()
    for _ in range(8):
        zeit, _ = beats_spielen(e, PARTY, 1, 0.65, von=zeit)
        gobos.add(e.bewerte(Messwerte(tempo_bpm=120, energie=0.65, leise=False), PARTY, zeit)["spot"].gobo)
    assert len(gobos) == 1 and gobos != {"Offen"}
    e.look_nummer += 1
    z = e.bewerte(Messwerte(tempo_bpm=120, energie=0.65, leise=False), PARTY, zeit + 0.1)
    assert z["spot"].gobo not in gobos and z["spot"].gobo_drehung


def test_ohne_bewegung_im_profil_nur_stehende_looks(engine):
    beats_spielen(engine, {**PARTY, "bewegung": "aus"}, 40, 0.95)
    assert engine.look.bewegung is None
