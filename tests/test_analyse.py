"""Die Musik-Analyse, gefüttert mit künstlichen Signalen schneller als Echtzeit."""
import numpy as np
import pytest

from lichtsteuerung.audio.analyse import Analyse, AubioBeatErkennung, EigeneBeatErkennung
from lichtsteuerung.audio.betrieb import AudioBetrieb
from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK, AudioFehler, erzeuge_takt


def bloecke(ton):
    for start in range(0, len(ton) - BLOCK, BLOCK):
        yield ton[start:start + BLOCK]


def abspielen(analyse, ton):
    return [analyse.verarbeite(block) for block in bloecke(ton)]


ERKENNUNGEN = [EigeneBeatErkennung]
try:
    import aubio  # noqa: F401
    ERKENNUNGEN.append(AubioBeatErkennung)
except ImportError:
    pass


@pytest.mark.parametrize("erkennung", ERKENNUNGEN)
@pytest.mark.parametrize("bpm", [100, 128])
def test_erkennt_den_takt(erkennung, bpm):
    werte = abspielen(Analyse(erkennung()), erzeuge_takt(bpm, 20))
    ende = werte[len(werte) // 2:]
    assert ende[-1].tempo_bpm == pytest.approx(bpm, rel=0.05) or \
        ende[-1].tempo_bpm == pytest.approx(bpm * 2, rel=0.05)
    assert sum(w.beat for w in ende) >= 10 * bpm / 60 * 0.7


def test_bass_hoch_beim_tiefen_ton():
    zeit = np.arange(ABTASTRATE * 2) / ABTASTRATE
    tief = (0.5 * np.sin(2 * np.pi * 60 * zeit)).astype(np.float32)
    werte = abspielen(Analyse(EigeneBeatErkennung()), tief)[-1]
    assert werte.bass > 0.8


def test_stille_gilt_als_leise_nach_kurzer_zeit():
    analyse = Analyse(EigeneBeatErkennung())
    abspielen(analyse, erzeuge_takt(120, 3))
    werte = abspielen(analyse, np.zeros(ABTASTRATE * 2, dtype=np.float32))
    assert not werte[0].leise
    assert werte[-1].leise


def test_laute_stelle_hat_mehr_energie_als_leise():
    laut = erzeuge_takt(120, 10)
    analyse = Analyse(EigeneBeatErkennung())
    energie_laut = abspielen(analyse, laut)[-1].energie
    energie_leise = abspielen(analyse, laut * 0.1)[-1].energie
    assert energie_laut > energie_leise * 2


def test_energie_bleibt_zwischen_0_und_1():
    werte = abspielen(Analyse(EigeneBeatErkennung()), erzeuge_takt(140, 5) * 3)
    assert all(0 <= w.energie <= 1 and 0 <= w.bass <= 1 for w in werte)


class KaputteQuelle:
    def lies(self):
        raise AudioFehler("Kabel raus")

    def schliessen(self):
        pass


def test_ausfall_der_quelle_ergibt_keine_messwerte():
    betrieb = AudioBetrieb()
    betrieb.starten(KaputteQuelle(), "kaputt")
    betrieb._thread.join(1)
    assert betrieb.aktuell() is None
    assert "Kabel" in betrieb.fehler
    betrieb.stoppen()


def test_alte_messwerte_gelten_als_ausfall():
    betrieb = AudioBetrieb()
    betrieb.messwerte, betrieb.zeitpunkt = object(), 100.0
    assert betrieb.aktuell(100.2) is not None
    assert betrieb.aktuell(100.6) is None        # Analyse hängt


def test_beatuhr_ueberbrueckt_luecken_und_hoert_wieder_auf():
    from lichtsteuerung.audio.analyse import BeatUhr
    uhr = BeatUhr()
    schritt = 0.01
    beats = 0
    for i in range(int(4 / schritt)):      # 4 s bei 120 BPM, nur ein echter Beat am Anfang
        beats += uhr.takt(i == 0, 120.0, schritt)
    assert 7 <= beats <= 9
    for _ in range(int(10 / schritt)):     # danach Stille
        beats += uhr.takt(False, 120.0, schritt)
    assert beats <= 13                     # nach 6 s ist Schluss
