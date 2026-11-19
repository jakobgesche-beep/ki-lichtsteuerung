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
    """Live muss es nebenher laufen (auf diesem Mac gut 3 % der Zeit; Grenze großzügig für langsame Rechner)."""
    ton, _ = testmusik.song("rock", 140, takte=16, seed=4)
    start = time.perf_counter()
    abspielen(ton)
    assert time.perf_counter() - start < 0.3 * len(ton) / ABTASTRATE


# --- Die Effekt-Uhr zählt im Takt ----------------------------------------------------

def effekt_uhr():
    from lichtsteuerung.pult import Effekte
    return Effekte(None, None, {})


def test_effekt_uhr_legt_vielfache_von_4_auf_die_eins():
    uhr = effekt_uhr()
    for _ in range(5):                              # fünf Schläge ohne Eins: die Uhr steht bei etwa 5
        uhr.takt(0.5, 120.0, beat=True)
    assert round(uhr.musik_beats) % 4 != 0
    uhr.takt(0.5, 120.0, beat=True, eins=True)
    assert round(uhr.musik_beats) % 4 == 0


def test_effekt_uhr_zaehlt_wie_die_probe():
    uhr = effekt_uhr()
    uhr.takt(0.5, 120.0, beat=True)
    uhr.takt(0.5, 120.0, beat=True, takt_stelle=13.08)    # laut Song-Folger der 14. Schlag nach der ersten Eins
    assert round(uhr.musik_beats) == 13
    rest = uhr.musik_beats - 13
    uhr.takt(0.5, 120.0, beat=True, takt_stelle=14.02)
    assert round(uhr.musik_beats) == 14 and abs(uhr.musik_beats - 14) <= abs(rest) + 1e-9


def test_song_spieler_kennt_die_stelle_im_takt():
    from types import SimpleNamespace
    from lichtsteuerung.songspieler import SongSpieler
    spieler = SongSpieler.__new__(SongSpieler)
    beats = [1.0 + 0.5 * i for i in range(40)]
    spieler._takt_merken({"beats_s": beats, "einsen_s": beats[2::4]})
    spieler.folger = SimpleNamespace(stelle=beats[2], wartet=False, bereit=False)
    assert spieler.takt_stelle() == pytest.approx(0.0)
    spieler.folger.stelle = beats[11] + 0.25                 # halb zwischen dem 10. und 11. Schlag nach der Eins
    assert spieler.takt_stelle() == pytest.approx(9.5)
    spieler.folger.wartet = True                             # Band hat aufgehört: keine Stelle
    assert spieler.takt_stelle() is None


def test_rechenfehler_haelt_den_ton_nicht_an(monkeypatch):
    """Sicherer Rückfall: Geht im Takt-Folger etwas schief, zählt er neu ein, die Analyse läuft weiter."""
    from lichtsteuerung.audio import songanalyse
    ton, _ = testmusik.song("rock", 120, takte=6, seed=2)
    analyse = Analyse(TaktFolger())
    abspielen(ton[: len(ton) // 2], analyse)

    def kaputt(*_, **__):
        raise ValueError("Testfehler")
    monkeypatch.setattr(songanalyse, "beats_finden", kaputt)
    _, _, werte = abspielen(ton[len(ton) // 2:], analyse)
    assert werte and analyse.beat.tempo == 0          # neu eingezählt, aber kein Absturz


# --- Rede zwischen den Songs ---------------------------------------------------------

def test_rede_wird_erkannt():
    ton = testmusik.rede(25, seed=2)
    _, _, werte = abspielen(ton)
    nach_5_s = werte[int(5 * ABTASTRATE / BLOCK):]
    assert sum(w.rede for w in nach_5_s) / len(nach_5_s) >= 0.8


@pytest.mark.parametrize("stil,tempo", [("rock", 120), ("ballade", 72), ("akustik", 96), ("sechsachtel", 60)])
def test_musik_ist_keine_rede(stil, tempo):
    ton, _ = testmusik.song(stil, tempo, takte=16, seed=3)
    _, _, werte = abspielen(ton)
    assert not any(w.rede for w in werte)


def test_ansage_nach_song_und_applaus():
    song, _ = testmusik.song("rock", 120, takte=12, seed=1)
    applaus = livefassung.publikum(4 * ABTASTRATE, seed=3) * 0.2
    ansage = testmusik.rede(20, seed=3)
    _, _, werte = abspielen(np.concatenate([song, applaus, ansage]).astype(np.float32))
    ende_song = int(len(song) / BLOCK)
    beginn_ansage = int((len(song) + len(applaus)) / BLOCK)
    assert not any(w.rede for w in werte[:ende_song])
    spaeter = werte[beginn_ansage + int(6 * ABTASTRATE / BLOCK):]
    assert sum(w.rede for w in spaeter) / len(spaeter) >= 0.8


# --- Schlagzeug-Solo: nie Applaus, nie Rede, immer kräftiges Licht -----------------------

@pytest.mark.parametrize("raum", [False, True])
def test_schlagzeug_solo_ist_kein_applaus_und_keine_rede(raum):
    """Becken und Snare rauschen wie Klatschen, zwischen den Schlägen ist es kurz still wie zwischen Silben.
    Trotzdem ist ein Solo Musik (bis 2.3.2 schaltete das Licht dabei auf ruhig)."""
    solo = testmusik.schlagzeug_solo(150, 40, seed=2)
    if raum:
        solo = livefassung.falten(solo, livefassung.hall(0.6, 0.3)).astype(np.float32)
    _, _, werte = abspielen(solo)
    assert not any(w.applaus for w in werte)
    assert not any(w.rede for w in werte)
    assert sum(w.treffer for w in werte) >= 2 * 40          # mindestens 2 Treffer pro Sekunde


@pytest.mark.parametrize("raum", [False, True])
def test_klatschen_bleibt_applaus(raum):
    rng = np.random.default_rng(1)
    klatschen = np.zeros(12 * ABTASTRATE, np.float32)
    for start in rng.integers(0, len(klatschen) - 2000, size=12 * 25):     # viele Hände, 25 Klatscher pro Sekunde
        klatschen[start:start + 1500] += (rng.standard_normal(1500) * np.exp(-np.arange(1500) / 200) * 0.2).astype(np.float32)
    if raum:
        klatschen = livefassung.falten(klatschen, livefassung.hall(1.0, 0.3)).astype(np.float32)[:len(klatschen)]
    _, _, werte = abspielen(klatschen)
    spaeter = werte[int(3 * ABTASTRATE / BLOCK):]
    assert sum(w.applaus for w in spaeter) / len(spaeter) >= 0.8


def test_schlagzeug_solo_gibt_kraeftiges_licht(pfade, katalog):
    """Das ganze Solo durch Analyse und Automatik: meistens die starken Looks, Licht springt auf den Treffern."""
    from lichtsteuerung.buehne import Buehne
    from lichtsteuerung.engine import Engine
    from lichtsteuerung.patch import Patch
    from lichtsteuerung.sicherheit import Grenzen
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/kopf", "7", 2, "Front 1-2", gruppen=["Spots"])
    buehne = Buehne(pfade.stage)
    for geraet, x in (("front-1", -3.5), ("front-2", 3.5)):
        buehne.setze_geraet(geraet, {"ort": "stativ", "x": x, "y": -1, "z": 2.5, "montage": "stehend"})
    engine = Engine(patch, buehne, {}, Grenzen(3, 5, 30))
    profil = {"name": "Party", "palette": ["rot", "blau", "gruen"], "max_helligkeit": 1.0, "bewegung": "voll",
              "beat_reaktion": 0.9, "strobo": "aus", "hazer": False,
              "grundlicht": {"werte": [{"gruppe": "Spots", "farbe": "warmweiss", "helligkeit": 0.4}]}}
    solo = livefassung.falten(testmusik.schlagzeug_solo(150, 40, seed=2), livefassung.hall(0.6, 0.3)).astype(np.float32)
    analyse = Analyse(TaktFolger())
    stufen, hell, texte, bild_zeit = [], [], [], 0.0
    offen = {"beat": False, "treffer": False, "eins": False, "schlag": False}
    for start in range(0, len(solo) - BLOCK, BLOCK):
        w = analyse.verarbeite(solo[start:start + BLOCK])
        for k in offen:
            offen[k] |= getattr(w, k)
        zeit = start / ABTASTRATE
        if zeit >= bild_zeit:                                # 40 Bilder pro Sekunde, wie die Show
            from dataclasses import replace
            z = engine.bewerte(replace(w, **offen), profil, zeit)
            offen = {k: False for k in offen}
            bild_zeit += 1 / 40
            if 5 < zeit < 40:
                stufen.append(engine.look.stufe)
                hell.append(z["front-1"].helligkeit)
                texte.append(engine.zustand_text)
    assert sum(s >= 2 for s in stufen) / len(stufen) >= 0.6
    assert not any("Rede" in t or "Leise" in t for t in texte)
    spruenge = sum(1 for a, b in zip(hell, hell[1:]) if b - a > 0.15)
    assert spruenge / (len(hell) / 40) >= 1.0               # sichtbare Sprünge, mindestens einer pro Sekunde
