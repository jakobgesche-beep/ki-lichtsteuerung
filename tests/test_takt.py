"""Der Takt-Folger: Beats, Tempo und die Eins live, gemessen an Testmusik mit bekannten Beats."""
import time

import numpy as np
import pytest

from lichtsteuerung.audio import livefassung
from lichtsteuerung.audio.analyse import Analyse, beat_erkennung
from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK
from lichtsteuerung.audio.takt import TaktFolger
from werkzeuge import testmusik
from werkzeuge.taktmessung import f_wert


def abspielen(ton, analyse=None):
    analyse = analyse or Analyse(TaktFolger())
    beats, einsen, werte = [], [], []
    for start in range(0, len(ton) - BLOCK, BLOCK):
        w = analyse.verarbeite(ton[start:start + BLOCK])
        if w.beat:
            beats.append(start / ABTASTRATE)
        if w.eins:
            einsen.append(start / ABTASTRATE)
        werte.append(w)
    return np.asarray(beats), np.asarray(einsen), werte


def ab(zeiten, sekunde, bis=1e9):
    zeiten = np.asarray(zeiten)
    return zeiten[(zeiten >= sekunde) & (zeiten <= bis)]


def test_ist_die_normale_beat_erkennung():
    assert beat_erkennung().name == "takt"


@pytest.mark.parametrize("stil,tempo", [("rock", 120), ("shuffle", 92), ("punk", 176), ("ballade", 72),
                                        ("sechsachtel", 60)])
def test_trifft_die_beats(stil, tempo):
    ton, wahr = testmusik.song(stil, tempo, takte=20, seed=3)
    beats, _, werte = abspielen(ton)
    ende = wahr["beats"][-1] + 0.2          # danach klingt der Song nur noch aus
    assert f_wert(ab(beats, 9, ende), ab(wahr["beats"], 9)) >= 0.95
    assert werte[-1].tempo_bpm == pytest.approx(tempo, rel=0.04)


def test_trifft_auch_im_saal():
    """Anderer Mix, Hall und Publikum, die Band 3 % schneller als in der Probe."""
    ton, wahr = testmusik.song("pop", 100, takte=24, seed=5)
    live = livefassung.bauen(ton, 0.0, len(ton) / ABTASTRATE, tempo=1.03, anderer_mix=True, nachhall_s=1.2,
                             publikum_db=8.0, vorlauf_s=3.0)
    wahre = [live.live_zeit(b) for b in wahr["beats"]]
    beats, _, _ = abspielen(live.ton)
    assert f_wert(ab(beats, 12), ab([b for b in wahre if b is not None], 12)) >= 0.9


def test_punk_ist_nicht_zwei_drittel_so_schnell():
    """Durchgehende Achtel: Auch jeder anderthalbte Schlag passt in ein Raster (117 statt 176 BPM)."""
    ton, _ = testmusik.song("punk", 176, takte=24, seed=3)
    _, _, werte = abspielen(ton)
    assert werte[-1].tempo_bpm == pytest.approx(176, rel=0.04)


def test_findet_die_eins():
    ton, wahr = testmusik.song("rock", 120, takte=24, seed=1)
    _, einsen, _ = abspielen(ton)
    assert f_wert(ab(einsen, 16), ab(wahr["einsen"], 16)) >= 0.9


def test_stille_haelt_den_takt_an():
    ton, _ = testmusik.song("rock", 120, takte=8, seed=2)
    beats, _, _ = abspielen(np.concatenate([ton, np.zeros(6 * ABTASTRATE, np.float32)]))
    ende = len(ton) / ABTASTRATE
    assert len(beats[beats > ende + 3]) == 0


def test_neuer_song_nach_applaus_neu_gezaehlt():
    erster, _ = testmusik.song("rock", 120, takte=12, seed=1)
    zweiter, wahr = testmusik.song("pop", 92, takte=16, seed=2, vorlauf_s=0.0)
    applaus = livefassung.publikum(4 * ABTASTRATE, seed=3) * 0.2
    ton = np.concatenate([erster, applaus, zweiter]).astype(np.float32)
    beats, _, werte = abspielen(ton)
    beginn = (len(erster) + len(applaus)) / ABTASTRATE
    assert werte[-1].tempo_bpm == pytest.approx(92, rel=0.04)
    assert f_wert(ab(beats, beginn + 10), ab(np.asarray(wahr["beats"]) + beginn, beginn + 10)) >= 0.9


def test_neu_anfangen_vergisst_alles():
    ton, _ = testmusik.song("rock", 120, takte=8, seed=2)
    folger = TaktFolger()
    for start in range(0, len(ton) - BLOCK, BLOCK):
        folger.verarbeite(ton[start:start + BLOCK])
    assert folger.tempo > 0
    folger.neu_anfangen()
    assert folger.tempo == 0 and folger.naechster is None and folger.eins_phase is None


def test_rechnet_schnell_genug():
    """Live muss es nebenher laufen: weit unter einem Zehntel der Zeit."""
    ton, _ = testmusik.song("rock", 140, takte=16, seed=4)
    start = time.perf_counter()
    abspielen(ton)
    assert time.perf_counter() - start < 0.1 * len(ton) / ABTASTRATE
