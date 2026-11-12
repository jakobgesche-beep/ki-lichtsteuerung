"""Applaus- und Pausenlicht: nach dem Song hell und warm, dann ruhig, bis der nächste Song kommt."""
import numpy as np
import pytest

from lichtsteuerung import daten
from lichtsteuerung.audio.analyse import Analyse, Messwerte
from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK, erzeuge_takt
from lichtsteuerung.show import Show


def bandsong():
    teile = [erzeuge_takt(120, 16) * laut for laut in (0.1, 0.8, 0.15, 0.8)]
    return np.concatenate([np.zeros(ABTASTRATE, np.float32)] + teile).astype(np.float32)


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.automatik_an = False
    s.proben.speichern("Band", bandsong())
    s.show_aus_probe("Band")
    return s


def laufen(show, von, bis, messwerte=None):
    show.audio.abholen = lambda jetzt=None: messwerte          # so "hört" die Show genau das
    for t in np.arange(von, bis, 0.05):
        show.baue_bild(float(t))


def test_nach_dem_song_applaus_dann_pause_dann_der_naechste_song(show):
    dauer = show.song.songs()[0]["dauer_s"]
    show.song.starten("Band", jetzt=0.0, stelle=dauer - 4.0)
    laufen(show, 0.0, 2.0)
    assert show.zwischenlicht.zustand == "aus"                 # der Song läuft noch
    laufen(show, 2.0, 5.0)
    assert show.zwischenlicht.zustand == "applaus"
    bild = show.simulator.lies(show.letztes_bild)
    assert any(g["hell"] > 0.8 for g in bild)                   # hell für den Applaus
    laufen(show, 5.0, 12.0)
    assert show.zwischenlicht.zustand == "pause"
    show.song.starten("Band", jetzt=12.5, stelle=1.0)
    laufen(show, 12.5, 13.0)
    assert show.zwischenlicht.zustand == "aus"


def test_solange_geklatscht_wird_bleibt_das_applaus_licht(show):
    dauer = show.song.songs()[0]["dauer_s"]
    show.song.starten("Band", jetzt=0.0, stelle=dauer - 3.0)
    klatschen = Messwerte(leise=False, applaus=True, energie=0.3)
    laufen(show, 0.0, 15.0, klatschen)
    assert show.zwischenlicht.zustand == "applaus"
    laufen(show, 15.0, 30.0, klatschen)
    assert show.zwischenlicht.zustand == "pause"                # höchstens 25 s


def test_ausgeschaltet_und_look_taste(show):
    show.song.setlist_setzen(zwischenlicht=False)
    dauer = show.song.songs()[0]["dauer_s"]
    show.song.starten("Band", jetzt=0.0, stelle=dauer - 3.0)
    laufen(show, 0.0, 6.0)
    assert show.zwischenlicht.zustand == "aus"
    show.song.setlist_setzen(zwischenlicht=True)
    show.song.starten("Band", jetzt=6.0, stelle=dauer - 3.0)
    laufen(show, 6.0, 12.0)
    assert show.zwischenlicht.zustand == "applaus"
    show.pult.look_druecken("ballade", 12.0)
    laufen(show, 12.0, 12.5)
    assert show.zwischenlicht.zustand == "aus"


def test_analyse_erkennt_klatschen_aber_nicht_musik():
    rng = np.random.default_rng(1)
    klatschen = np.zeros(8 * ABTASTRATE, np.float32)
    for start in rng.integers(0, len(klatschen) - 2000, size=8 * 25):
        klatschen[start:start + 1500] += (rng.standard_normal(1500) * np.exp(-np.arange(1500) / 200) * 0.2).astype(np.float32)
    musik = erzeuge_takt(120, 8) * 0.5

    def applaus_am_ende(ton):
        analyse = Analyse()
        werte = None
        for a in range(0, len(ton) - BLOCK, BLOCK):
            werte = analyse.verarbeite(ton[a:a + BLOCK])
        return werte.applaus

    assert applaus_am_ende(klatschen) and not applaus_am_ende(musik)


def test_klatschen_im_schluss_beendet_den_song(show):
    """Die Probe-Aufnahme geht nach dem Song noch weiter: Das Klatschen sagt, dass der Song vorbei ist."""
    teile = show.song.songs()[0]["teile"]
    show.song.starten("Band", jetzt=0.0, stelle=teile[-1]["start"] + 1.0)
    laufen(show, 0.0, 2.0)
    assert show.zwischenlicht.zustand == "aus"
    klatschen = Messwerte(leise=False, applaus=True, energie=0.3)
    laufen(show, 2.0, 4.0, klatschen)
    assert show.zwischenlicht.zustand == "aus"                 # kurzes Klatschen: der Song läuft weiter
    laufen(show, 4.0, 7.5, klatschen)
    assert show.zwischenlicht.zustand == "applaus" and show.song._am_ende()


def test_klatschen_mitten_im_song_beendet_ihn_nicht(show):
    show.song.starten("Band", jetzt=0.0, stelle=5.0)
    laufen(show, 0.0, 6.0, Messwerte(leise=False, applaus=True, energie=0.3))
    assert show.zwischenlicht.zustand == "aus" and not show.song._am_ende()
