"""Stärke aus dem Pegel in dB (2.5.2): laut/leise richtig, erster Song, gemerkter Bezug vom Soundcheck."""
import numpy as np

from lichtsteuerung import daten
from lichtsteuerung.audio.lautheit import Lautheit
from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK
from lichtsteuerung.show import Show

DAUER = BLOCK / ABTASTRATE


def rauschen(db: float, sekunden: float, seed: int = 1) -> list:
    """Blöcke mit gleichmäßigem Pegel (dB, mittlere Leistung)."""
    zufall = np.random.default_rng(seed)
    ton = zufall.standard_normal(int(sekunden * ABTASTRATE)).astype(np.float32) * (10 ** (db / 20))
    return [ton[i:i + BLOCK] for i in range(0, len(ton) - BLOCK, BLOCK)]


def spielen(laut: Lautheit, db: float, sekunden: float, musik: bool = True) -> list:
    return [laut.verarbeite(b, DAUER, musik) for b in rauschen(db, sekunden)]


def test_leises_intro_ist_kein_hoehepunkt_der_refrain_schon():
    laut = Lautheit()
    intro = spielen(laut, -35, 10)
    strophe = spielen(laut, -25, 20)
    refrain = spielen(laut, -21, 20)
    strophe_2 = spielen(laut, -25, 20)
    assert max(intro[int(2 / DAUER):]) < 0.8                   # leises Intro am Anfang: höchstens stark
    assert np.mean(refrain[-int(5 / DAUER):]) >= 0.8           # Refrain: Höhepunkt
    assert 0.5 <= np.mean(strophe_2[-int(5 / DAUER):]) <= 0.75  # die zweite Strophe 4 dB leiser: mittel bis stark
    assert np.mean(strophe[-int(5 / DAUER):]) > np.mean(strophe_2[-int(5 / DAUER):])   # beim ersten Mal kannte es den Refrain noch nicht


def test_laut_bleibt_laut():
    """Eine Band, die minutenlang gleich laut spielt (oder ein Schlagzeug-Solo), ist Höhepunkt, nicht „normal“."""
    laut = Lautheit()
    werte = spielen(laut, -18, 120)
    assert np.mean(werte[-int(30 / DAUER):]) >= 0.95


def test_rede_und_applaus_zaehlen_nicht_zur_musik():
    laut = Lautheit()
    spielen(laut, -20, 70)
    bezug = laut.bezug_db
    spielen(laut, -10, 30, musik=False)                        # sehr lauter Applaus
    assert laut.bezug_db == bezug and laut.musik_s < 71


def test_gemerkter_bezug_macht_schon_den_ersten_song_richtig():
    ohne = Lautheit()
    mit = Lautheit(gemerkt_db=-20.0)                          # Soundcheck: laute Stellen bei −20 dB
    ballade_ohne = spielen(ohne, -30, 20)
    ballade_mit = spielen(mit, -30, 20)
    assert np.mean(ballade_mit[-int(10 / DAUER):]) < 0.35      # 10 dB leiser als die Band: ruhig
    assert np.mean(ballade_ohne[-int(10 / DAUER):]) > 0.6      # ohne Bezug weiß das niemand


def test_gemerkter_bezug_gibt_nach_wenn_heute_leiser_gespielt_wird():
    laut = Lautheit(gemerkt_db=-14.0)                          # gestern 6 dB lauter
    werte = spielen(laut, -20, 180)
    assert np.mean(werte[-int(20 / DAUER):]) >= 0.9            # nach drei Minuten passt es wieder


def test_gemerkt_wird_erst_nach_einer_minute_musik():
    laut = Lautheit()
    spielen(laut, -22, 30)
    assert laut.gelernt() is None
    spielen(laut, -22, 40)
    assert abs(laut.gelernt() - (-22.0)) < 1.0


def test_bezug_wird_pro_eingang_gemerkt_und_nach_dem_neustart_genutzt(tmp_path):
    daten.einrichten(tmp_path / "d")
    pfade = daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog")
    show = Show(pfade)

    class Quelle:
        kanaele = (15, 16)

    class Gelernt:
        class lautheit:
            @staticmethod
            def gelernt():
                return -17.3

    show.audio.name = "Eingang: X-USB"
    show.audio._bezug_merken(Quelle(), Gelernt())
    assert show.audio.bezuege == {"Eingang: X-USB | 15,16": -17.3}
    show.audio.name = "Testsignal"                             # Testsignal und Dateien: nichts merken
    show.audio._bezug_merken(Quelle(), Gelernt())
    assert len(show.audio.bezuege) == 1
    neu = Show(pfade)
    assert neu.audio.bezuege == {"Eingang: X-USB | 15,16": -17.3}
    neu.audio.name = "Eingang: X-USB"
    assert neu.audio._bezug_name(Quelle()) == "Eingang: X-USB | 15,16"


def test_stopp_nach_dichter_musik_nicht_bei_leisen_teilen():
    laut = Lautheit()
    spielen(laut, -20, 70)
    stopp = [laut.verarbeite(b, DAUER, True) is not None and laut.stopp for b in rauschen(-90, 1.0, seed=2)]
    assert stopp[int(0.1 / DAUER)] and all(stopp[int(0.1 / DAUER):])           # nach höchstens 0,1 s
    nach = [laut.verarbeite(b, DAUER, True) is not None and laut.stopp for b in rauschen(-20, 2.0, seed=3)]
    assert not any(nach[int(0.05 / DAUER):])                                      # Einsatz: sofort vorbei
    leiser = [laut.verarbeite(b, DAUER, True) is not None and laut.stopp for b in rauschen(-38, 8.0, seed=4)]
    assert not any(leiser)                                                        # leiser Teil: kein Stopp


def test_kein_stopp_in_luecken_zwischen_toenen_nur_am_schlusspunkt():
    from werkzeuge import testmusik
    for ton, schluss_erlaubt in ((testmusik.song("ballade", 76, 32, seed=3), True),
                                 (testmusik.song("rock", 140, 64, seed=3), True),
                                 (testmusik.song_mit_form(120.0, seed=2)[0], True)):
        ton = ton[0] if isinstance(ton, tuple) else ton
        laut, stopps = Lautheit(), []
        for i in range(0, len(ton) - BLOCK, BLOCK):
            vorher = laut.stopp
            laut.verarbeite(ton[i:i + BLOCK], DAUER, True)
            if laut.stopp and not vorher:
                stopps.append(i / len(ton))
        assert all(s > 0.95 for s in stopps), stopps                              # nur der Schlusspunkt
