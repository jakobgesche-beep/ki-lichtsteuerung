"""Wie genau trifft der Live-Takt? Misst die Beat-Erkennungen auf Testmusik und echten Aufnahmen.

Aufruf aus dem Projektordner:

    .venv/bin/python -m werkzeuge.taktmessung [--erkennung eigene,aubio,takt] [--kurz] [AUFNAHME.wav ...]

Testmusik (werkzeuge/testmusik.py) kennt ihre Beats genau. Bei echten Aufnahmen gilt die Probe-Analyse
(songanalyse, 97 % genau) als richtig. Jede Musik läuft einmal sauber und einmal "live" (anderer Mix, Hall,
Publikum), so wie es im Saal am Mikrofon ankommt.

    F          wie viele Beats richtig sind (auf 70 ms genau), 1 = alle, nach den ersten 6 s Musik
    F Ebene    dasselbe, wenn auch halbes oder doppeltes Tempo als richtig zählt (fürs Licht fast so gut)
    Tempo      Anteil der Zeit, in der das angezeigte Tempo stimmt (4 %), in Klammern: oder halb/doppelt
    Einrasten  wie lange nach Musikbeginn, bis 8 Beats hintereinander stimmen
    Rechenzeit Anteil einer Sekunde, den die Erkennung pro Sekunde Musik braucht
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

PROJEKT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT))

from lichtsteuerung.audio import livefassung, songanalyse          # noqa: E402
from lichtsteuerung.audio.analyse import Analyse, EigeneBeatErkennung   # noqa: E402
from lichtsteuerung.audio.quellen import ABTASTRATE as RATE, BLOCK, lade_datei   # noqa: E402
from werkzeuge import testmusik                                     # noqa: E402

TOLERANZ = 0.07
AUFWAERMEN_S = 6.0

TESTSONGS = [("rock", 120), ("pop", 100), ("punk", 176), ("shuffle", 92), ("ballade", 72), ("edm", 128),
             ("akustik", 96), ("rock", 165), ("pop", 84), ("edm", 140), ("rock", 140), ("shuffle", 120),
             ("sechsachtel", 60), ("sechsachtel", 76), ("punk", 190), ("punk", 160)]


def erkennung(name: str):
    if name == "eigene":
        return EigeneBeatErkennung()
    if name == "aubio":
        from lichtsteuerung.audio.analyse import AubioBeatErkennung
        return AubioBeatErkennung()
    from lichtsteuerung.audio.takt import TaktFolger
    return TaktFolger()


def abspielen(ton: np.ndarray, name: str):
    analyse = Analyse(erkennung(name))
    beats, einsen, tempi, rechenzeit = [], [], [], 0.0
    for i in range(0, len(ton) - BLOCK, BLOCK):
        start = time.perf_counter()
        w = analyse.verarbeite(ton[i:i + BLOCK])
        rechenzeit += time.perf_counter() - start
        t = i / RATE
        if w.beat:
            beats.append(t)
        if w.eins:
            einsen.append(t)
        tempi.append((t, w.tempo_bpm))
    return np.asarray(beats), np.asarray(einsen), tempi, rechenzeit / (len(ton) / RATE)


def f_wert(live: np.ndarray, wahr: np.ndarray) -> float:
    if not len(live) or not len(wahr):
        return 0.0
    treffer_live = np.mean([np.min(np.abs(wahr - b)) <= TOLERANZ for b in live])
    treffer_wahr = np.mean([np.min(np.abs(live - b)) <= TOLERANZ for b in wahr])
    return 0.0 if treffer_live + treffer_wahr == 0 else 2 * treffer_live * treffer_wahr / (treffer_live + treffer_wahr)


def auswerten(beats: np.ndarray, tempi: list, wahr: np.ndarray, von: float, bis: float, einsen=None,
              wahre_einsen=None) -> dict:
    wahr = np.asarray(wahr)
    ab = von + AUFWAERMEN_S
    eins_f = None
    if einsen is not None and wahre_einsen is not None and len(wahre_einsen):
        we = np.asarray(wahre_einsen)
        eins_f = round(f_wert(einsen[(einsen >= ab + 6) & (einsen < bis)], we[(we >= ab + 6) & (we < bis)]), 3)
    live = beats[(beats >= ab) & (beats < bis)]
    soll = wahr[(wahr >= ab) & (wahr < bis)]
    f = f_wert(live, soll)
    mitten = (wahr[:-1] + wahr[1:]) / 2
    doppelt = np.sort(np.concatenate([wahr, mitten]))
    doppelt = doppelt[(doppelt >= ab) & (doppelt < bis)]
    ebenen = [f, f_wert(live, doppelt), f_wert(live, soll[0::2]), f_wert(live, soll[1::2])]
    # Tempo: wahres Tempo an jeder Stelle aus den Beat-Abständen
    abstand = np.diff(wahr)
    richtig = oktave = gezaehlt = 0
    for t, bpm in tempi:
        if not ab <= t < bis or len(abstand) == 0:
            continue
        k = int(np.clip(np.searchsorted(wahr, t) - 1, 0, len(abstand) - 1))
        wahres = 60.0 / abstand[k]
        gezaehlt += 1
        if bpm > 0 and abs(bpm / wahres - 1) <= 0.04:
            richtig += 1
        if bpm > 0 and min(abs(bpm / wahres / f_ - 1) for f_ in (1, 2, 0.5)) <= 0.04:
            oktave += 1
    # Einrasten: ab wann stimmen 8 Beats hintereinander?
    alle = beats[(beats >= von) & (beats < bis)]
    soll_alle = wahr[(wahr >= von) & (wahr < bis)]
    einrasten = None
    if len(soll_alle):
        ok = [np.min(np.abs(soll_alle - b)) <= TOLERANZ for b in alle]
        for k in range(len(ok) - 7):
            if all(ok[k:k + 8]):
                einrasten = round(float(alle[k] - von), 1)
                break
    return {"f": round(f, 3), "f_ebene": round(max(ebenen), 3),
            "tempo": round(richtig / max(1, gezaehlt), 3), "tempo_ebene": round(oktave / max(1, gezaehlt), 3),
            "einrasten_s": einrasten, "eins": eins_f}


def faelle(kurz: bool, aufnahmen: list):
    """(Name, Ton, wahre Beats, Musik von, Musik bis)"""
    songs = TESTSONGS[:6] if kurz else TESTSONGS
    for nummer, (stil, tempo) in enumerate(songs):
        ton, wahr = testmusik.song(stil, tempo, takte=32, seed=nummer + 1, drift=0.02 if nummer % 2 else 0.0)
        beats = np.asarray(wahr["beats"])
        einsen = np.asarray(wahr["einsen"])
        yield f"{stil} {tempo}", ton, beats, float(beats[0]), float(beats[-1]), einsen
        live = livefassung.bauen(ton, 0.0, len(ton) / RATE, anderer_mix=True, nachhall_s=1.2,
                                 publikum_db=8.0, vorlauf_s=3.0, seed=nummer)
        yield f"{stil} {tempo} live", live.ton, beats + live.musik_ab_s, float(beats[0] + live.musik_ab_s), \
            float(beats[-1] + live.musik_ab_s), einsen + live.musik_ab_s
    for pfad in aufnahmen:
        ton = lade_datei(pfad)
        analyse = songanalyse.analysieren(ton)
        beats = np.asarray(analyse["beats_s"])
        name = Path(pfad).stem
        einsen = np.asarray(analyse["einsen_s"])
        yield f"{name} ({analyse['tempo_bpm']:.0f})", ton, beats, float(beats[0]), float(beats[-1]), einsen
        live = livefassung.bauen(ton, 0.0, len(ton) / RATE, tempo=1.03, anderer_mix=True, nachhall_s=1.2,
                                 publikum_db=6.0, vorlauf_s=3.0)
        live_beats = np.asarray([z for z in (live.live_zeit(b) for b in beats) if z is not None])
        live_einsen = np.asarray([z for z in (live.live_zeit(b) for b in einsen) if z is not None])
        yield f"{name} live +3 %", live.ton, live_beats, float(live_beats[0]), float(live_beats[-1]), live_einsen


def main(argv=None):
    teile = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    teile.add_argument("aufnahmen", nargs="*")
    teile.add_argument("--erkennung", default="eigene,takt")
    teile.add_argument("--kurz", action="store_true")
    teile.add_argument("--nur", default="", help="nur Fälle, deren Name das enthält")
    a = teile.parse_args(argv)
    namen = a.erkennung.split(",")
    summe = {n: [] for n in namen}
    print(f"{'Fall':24s} " + " ".join(f"{n:>46s}" for n in namen))
    print(f"{'':24s} " + " ".join(f"{'F   F-Eb  Tempo (Ebene) Einr. Zeit  Eins':>46s}" for _ in namen))
    for name, ton, wahr, von, bis, wahre_einsen in faelle(a.kurz, a.aufnahmen):
        if a.nur and a.nur not in name:
            continue
        zeile = f"{name:24s} "
        for n in namen:
            beats, einsen, tempi, zeit = abspielen(ton, n)
            e = auswerten(beats, tempi, wahr, von, bis, einsen, wahre_einsen)
            e["zeit"] = zeit
            summe[n].append(e)
            einr = "  -  " if e["einrasten_s"] is None else f"{e['einrasten_s']:5.1f}"
            eins = "  -  " if e["eins"] is None else f"{e['eins']:5.2f}"
            zeile += (f"{e['f']:>12.2f} {e['f_ebene']:5.2f} {e['tempo']:5.2f} ({e['tempo_ebene']:4.2f}) {einr} "
                      f"{zeit * 100:4.1f}% {eins}")
        print(zeile, flush=True)
    zeile = f"{'Mittel':24s} "
    for n in namen:
        werte = summe[n]
        einr = [e["einrasten_s"] for e in werte if e["einrasten_s"] is not None]
        zeile += (f"{np.mean([e['f'] for e in werte]):>12.2f} {np.mean([e['f_ebene'] for e in werte]):5.2f} "
                  f"{np.mean([e['tempo'] for e in werte]):5.2f} ({np.mean([e['tempo_ebene'] for e in werte]):4.2f}) "
                  f"{np.median(einr) if einr else 0:5.1f} {np.mean([e['zeit'] for e in werte]) * 100:4.1f}% "
                  f"{np.mean([e['eins'] for e in werte if e['eins'] is not None] or [0]):5.2f}")
    print(zeile)


if __name__ == "__main__":
    main()
