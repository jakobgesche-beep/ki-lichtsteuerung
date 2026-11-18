"""Prüfstand: Eine Aufnahme läuft durch das ganze Programm, als würde die Band spielen. Was macht das Licht?

Aufruf aus dem Projektordner:

    .venv/bin/python -m werkzeuge.pruefstand AUFNAHME.wav [--song] [--daten ORDNER] [--profil NAME]
                                             [--bild licht.png] [--marken 45.5,69.4,...] [--von S] [--bis S]

    ohne --song   Musik-Automatik (so, als gäbe es keine Probe)
    --song        Die Aufnahme wird als Probe gespeichert, die Show gebaut und Song-Start gedrückt.
                  Dann läuft dieselbe Aufnahme als Band.
    --daten       Ordner mit Patch und Bühne (Kopie!). Sonst die Beispiel-Show des Projekts.
    --marken      Echte Teilwechsel (zum Beispiel die D-Marken), werden im Bild rot eingezeichnet und gemessen.

Ergebnis: ein Bild (pro Gerät ein Streifen mit Farbe und Helligkeit über die Zeit, darunter die Kopfrichtung)
und Zahlen: wie oft das Licht wechselt, ob Wechsel auf Takt-Einsen und Teilwechseln liegen, wie gut der Puls zum
Beat passt, wie viel dunkel ist. Die Aufnahme bleibt auf diesem Rechner; nichts davon kommt ins Programm.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import sys
import tempfile
import zlib
from dataclasses import replace
from pathlib import Path

import numpy as np

PROJEKT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT))

from lichtsteuerung import daten                                   # noqa: E402
from lichtsteuerung.audio import songanalyse                       # noqa: E402
from lichtsteuerung.audio.analyse import Analyse                   # noqa: E402
from lichtsteuerung.audio.quellen import ABTASTRATE as RATE, BLOCK, lade_datei   # noqa: E402
from lichtsteuerung.show import Show                               # noqa: E402

BILDER = 40                   # so oft rechnet die Show ein Bild (wie live)


# --- Durchlauf -------------------------------------------------------------------

def show_bauen(ordner: Path, quelle: Path = None) -> Show:
    ordner.mkdir(parents=True, exist_ok=True)
    if quelle:
        for name in daten.STANDARD_DATEIEN:
            if (Path(quelle) / name).exists():
                shutil.copy(Path(quelle) / name, ordner / name)
        for name in ("catalog/eigene", "profile", "cues"):
            if (Path(quelle) / name).is_dir():
                shutil.copytree(Path(quelle) / name, ordner / name, dirs_exist_ok=True)
    daten.einrichten(ordner)
    show = Show(daten.Pfade(ordner, daten.PROJEKT / "catalog"))
    return show


def durchlauf(show: Show, ton: np.ndarray, von_s: float = 0.0, bis_s: float = None, song: str = None,
              song_start_s: float = None) -> dict:
    """Spielt den Ton blockweise ein (wie der Audio-Thread) und rechnet 40 Bilder pro Sekunde (wie die Show)."""
    audio = show.audio
    analyse = Analyse()
    zaehler = {"beat": 0, "drop": 0, "schlag": 0, "eins": 0}
    abgeholt = dict(zaehler)
    stand = {"werte": None, "zeit": -1.0}

    def aktuell(jetzt=None):
        return stand["werte"]

    def abholen(jetzt=None):
        werte = stand["werte"]
        if werte is None:
            return None
        neu = {k: zaehler[k] != abgeholt[k] for k in zaehler}
        abgeholt.update(zaehler)
        return replace(werte, beat=neu["beat"], drop=neu["drop"], schlag=neu["schlag"], eins=neu["eins"])

    audio.aktuell, audio.abholen = aktuell, abholen
    audio.name = "Eingang: Prüfstand"
    von = int(von_s * RATE)
    bis = len(ton) if bis_s is None else min(len(ton), int(bis_s * RATE))
    aufzeichnung = {"zeit": [], "geraete": {}, "look": [], "beats": [], "schlaege": [], "drops": [], "einsen": [],
                    "cue": []}
    naechstes = von / RATE
    gestartet = song is None
    for a in range(von, bis - BLOCK, BLOCK):
        jetzt = a / RATE
        if not gestartet and jetzt >= (song_start_s or 0.0):
            show.song.starten(song, jetzt=jetzt)
            gestartet = True
        block = ton[a:a + BLOCK]
        werte = analyse.verarbeite(block)
        for zuhoerer in [audio.zuhoerer] + list(audio.mithoerer):
            if zuhoerer is not None:
                zuhoerer(block, jetzt)
        for art in zaehler:
            if getattr(werte, art):
                zaehler[art] += 1
                aufzeichnung[{"beat": "beats", "schlag": "schlaege", "drop": "drops", "eins": "einsen"}[art]].append(
                    round(jetzt, 3))
        stand["werte"] = werte
        while naechstes <= jetzt:
            show.baue_bild(naechstes)
            aufzeichnung["zeit"].append(round(naechstes, 3))
            for g in show.simulator.lies(show.letztes_bild):
                aufzeichnung["geraete"].setdefault(g["id"], []).append(
                    (g["hell"], tuple(g["farbe"]), tuple(g["richtung"]), g["strobo_hz"], g["gobo"]))
            aufzeichnung["look"].append((show.engine.look.name, show.engine.look_nummer))
            platz = show.pult.song_platz
            aufzeichnung["cue"].append(platz.index if show.song.folger is not None else -1)
            naechstes += 1.0 / BILDER
    return aufzeichnung


# --- Auswerten -------------------------------------------------------------------

def wechsel_zeiten(aufzeichnung: dict, schluessel: str) -> list:
    zeiten, vorher = [], None
    for t, wert in zip(aufzeichnung["zeit"], aufzeichnung[schluessel]):
        kennung = wert[1] if isinstance(wert, tuple) else wert
        if vorher is not None and kennung != vorher:
            zeiten.append(t)
        vorher = kennung
    return zeiten


def farbwechsel_zaehlen(farbe: np.ndarray, sichtbar: np.ndarray, bleiben_s: float = 0.3) -> int:
    """Wie oft wechselt die Farbe wirklich? Helligkeit zählt nicht (ein RGB-PAR ohne Dimmer pulst über die Farbe),
    weiche Überblendungen zählen einmal: Gezählt wird, wenn eine neue Farbe mindestens 0,3 s bleibt."""
    if len(farbe) < 2:
        return 0
    norm = farbe / np.maximum(farbe.max(axis=1, keepdims=True), 1e-6)
    stufen = [tuple(z) if h > 0.1 else None for z, h in zip(np.round(norm * 4).astype(int), sichtbar)]
    bleiben = int(bleiben_s * BILDER)
    wechsel, jetzt, i = 0, None, 0
    while i < len(stufen):
        stufe = stufen[i]
        if stufe is None or stufe == jetzt:
            i += 1
            continue
        lauf = i
        while lauf < len(stufen) and stufen[lauf] == stufe:
            lauf += 1
        if lauf - i >= bleiben:
            wechsel += jetzt is not None
            jetzt = stufe
        i = lauf
    return wechsel


def naechster_abstand(zeiten: list, ziele: list) -> list:
    ziele = np.asarray(sorted(ziele))
    if not len(ziele):
        return []
    return [float(np.min(np.abs(ziele - t))) for t in zeiten]


def auswerten(aufzeichnung: dict, offline: dict, marken: list) -> dict:
    zeiten = np.asarray(aufzeichnung["zeit"])
    dauer_min = (zeiten[-1] - zeiten[0]) / 60 if len(zeiten) > 1 else 1
    ergebnis = {"dauer_s": round(float(zeiten[-1] - zeiten[0]), 1)}
    beats = np.asarray(offline.get("beats_s", []))
    einsen = np.asarray(offline.get("einsen_s", []))
    # Live-Beats gegen die offline gefundenen (die stimmen sehr gut): Treffer, wenn höchstens 70 ms daneben
    live = np.asarray(aufzeichnung["beats"])
    if len(beats) and len(live):
        im = (beats >= zeiten[0]) & (beats <= zeiten[-1])
        ref = beats[im]
        treffer = sum(1 for b in live if np.min(np.abs(ref - b)) <= 0.07) if len(ref) else 0
        praezision = treffer / len(live)
        erinnerung = sum(1 for b in ref if np.min(np.abs(live - b)) <= 0.07) / max(1, len(ref))
        versatz = [float(b - ref[np.argmin(np.abs(ref - b))]) for b in live if np.min(np.abs(ref - b)) <= 0.15]
        ergebnis["beat"] = {"live": len(live), "offline": int(len(ref)),
                            "f_mass": round(2 * praezision * erinnerung / max(1e-9, praezision + erinnerung), 3),
                            "versatz_ms_median": round(1000 * float(np.median(versatz)), 1) if versatz else None}
    for art in ("look", "cue"):
        wechsel = wechsel_zeiten(aufzeichnung, art)
        if art == "cue" and all(c < 0 for c in aufzeichnung["cue"]):
            continue
        eintrag = {"anzahl": len(wechsel), "pro_minute": round(len(wechsel) / dauer_min, 2)}
        if len(einsen):
            abstand = naechster_abstand(wechsel, einsen)
            eintrag["auf_takt_eins_150ms"] = round(float(np.mean(np.asarray(abstand) <= 0.15)), 2) if abstand else None
        if marken:
            nah = naechster_abstand(marken, wechsel)
            eintrag["marken_mit_wechsel_1s"] = round(float(np.mean(np.asarray(nah) <= 1.0)), 2) if nah else None
            eintrag["marken_abstand_s"] = [round(x, 2) for x in nah]
        ergebnis[art] = eintrag
    geraete = {}
    for gid, werte in aufzeichnung["geraete"].items():
        hell = np.asarray([w[0] for w in werte])
        farbe = np.asarray([w[1] for w in werte])
        richtung = np.asarray([w[2] for w in werte])
        sichtbar = hell * np.max(farbe, axis=1) if farbe.size else hell
        winkel = []
        if richtung.size and np.any(richtung):
            skalar = np.clip(np.sum(richtung[1:] * richtung[:-1], axis=1), -1, 1)
            winkel = np.degrees(np.arccos(skalar)) * BILDER        # Grad pro Sekunde
        farbwechsel = farbwechsel_zaehlen(farbe, sichtbar)
        geraete[gid] = {"dunkel_anteil": round(float(np.mean(sichtbar < 0.05)), 2),
                        "mittel_hell": round(float(np.mean(sichtbar)), 2),
                        "farbwechsel_pro_minute": round(farbwechsel / dauer_min, 1),
                        "bewegung_grad_s_median": round(float(np.median(winkel)), 1) if len(winkel) else None,
                        "bewegung_grad_s_95": round(float(np.percentile(winkel, 95)), 1) if len(winkel) else None,
                        "strobo_anteil": round(float(np.mean([w[3] > 0 for w in werte])), 3)}
        # Puls im Beat: Ist es kurz nach einem Beat heller als kurz davor?
        if len(beats):
            vor, nach = [], []
            for b in beats:
                i = int(np.searchsorted(zeiten, b))
                if 3 <= i < len(zeiten) - 3:
                    vor.append(sichtbar[i - 2])
                    nach.append(sichtbar[i + 1])
            if vor:
                geraete[gid]["puls_im_beat"] = round(float(np.mean(nach) - np.mean(vor)), 3)
    ergebnis["geraete"] = geraete
    return ergebnis


# --- Bild ------------------------------------------------------------------------

def png(pfad: Path, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    roh = b"".join(b"\x00" + zeile.tobytes() for zeile in rgb.astype(np.uint8))

    def stueck(art: bytes, inhalt: bytes) -> bytes:
        return struct.pack(">I", len(inhalt)) + art + inhalt + struct.pack(">I", zlib.crc32(art + inhalt) & 0xFFFFFFFF)

    Path(pfad).write_bytes(b"\x89PNG\r\n\x1a\n" + stueck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + stueck(b"IDAT", zlib.compress(roh, 6)) + stueck(b"IEND", b""))


def bild(aufzeichnung: dict, offline: dict, marken: list, pfad: Path, px_pro_s: float = 10.0) -> None:
    """Pro Gerät: oben ein Streifen Farbe × Helligkeit, darunter Pan (gelb) und Tilt (blau) als Linien."""
    zeiten = np.asarray(aufzeichnung["zeit"])
    t0, t1 = zeiten[0], zeiten[-1]
    breite = int((t1 - t0) * px_pro_s) + 1
    spalte = np.clip(((zeiten - t0) * px_pro_s).astype(int), 0, breite - 1)
    reihen = []
    kopf = np.full((16, breite, 3), 18, np.uint8)
    for b in offline.get("einsen_s", []):
        x = int((b - t0) * px_pro_s)
        if 0 <= x < breite:
            kopf[10:16, x] = (90, 90, 90)
    for m in marken:
        x = int((m - t0) * px_pro_s)
        if 0 <= x < breite:
            kopf[:, x] = (230, 40, 40)
    for t in wechsel_zeiten(aufzeichnung, "look"):
        x = int((t - t0) * px_pro_s)
        if 0 <= x < breite:
            kopf[0:6, x] = (240, 200, 0)
    for t in aufzeichnung["schlaege"]:
        x = int((t - t0) * px_pro_s)
        if 0 <= x < breite:
            kopf[6:10, x] = (255, 255, 255)
    reihen.append(kopf)
    for gid, werte in aufzeichnung["geraete"].items():
        streifen = np.zeros((26, breite, 3), np.float32)
        linien = np.full((30, breite, 3), 10, np.float32)
        hell = np.asarray([w[0] for w in werte])
        farbe = np.asarray([w[1] for w in werte])
        richtung = np.asarray([w[2] for w in werte])
        farbe_px = np.zeros((breite, 3), np.float32)
        anzahl = np.zeros(breite)
        np.add.at(farbe_px, spalte, farbe * hell[:, None])
        np.add.at(anzahl, spalte, 1)
        farbe_px /= np.maximum(anzahl, 1)[:, None]
        streifen[:] = farbe_px[None, :, :] * 255
        if richtung.size and np.any(richtung):
            pan = np.degrees(np.arctan2(richtung[:, 0], richtung[:, 1]))
            tilt = np.degrees(np.arccos(np.clip(-richtung[:, 2], -1, 1)))
            for kurve, farbe_linie, bereich in ((pan, (230, 200, 40), 180.0), (tilt, (80, 140, 255), 180.0)):
                y = np.clip((29 - (kurve + bereich) / (2 * bereich) * 29).astype(int), 0, 29) if farbe_linie[0] > 200 \
                    else np.clip((29 - kurve / bereich * 29).astype(int), 0, 29)
                linien[y, spalte] = farbe_linie
        trenner = np.full((3, breite, 3), 40, np.float32)
        reihen += [streifen, linien, trenner]
    png(pfad, np.clip(np.vstack(reihen), 0, 255).astype(np.uint8))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("aufnahme")
    parser.add_argument("--song", action="store_true")
    parser.add_argument("--daten")
    parser.add_argument("--profil")
    parser.add_argument("--bild", default="licht.png")
    parser.add_argument("--marken", default="")
    parser.add_argument("--von", type=float, default=0.0)
    parser.add_argument("--bis", type=float)
    parser.add_argument("--json")
    args = parser.parse_args()
    ton = lade_datei(Path(args.aufnahme))
    with tempfile.TemporaryDirectory() as tmp:
        show = show_bauen(Path(tmp) / "show", args.daten)
        show.automatik_an = True
        show.song.mitschnitt_an = False          # der Mitschnitt schriebe noch, wenn der Ordner schon weg ist
        if args.profil:
            show.profil_laden(args.profil)
        offline = songanalyse.analysieren(ton)
        song = None
        if args.song:
            show.proben.speichern("Prüfstand", ton)
            show.show_aus_probe("Prüfstand")
            song = "Prüfstand"
        marken = [float(m) for m in args.marken.split(",") if m.strip()]
        aufzeichnung = durchlauf(show, ton, args.von, args.bis, song, song_start_s=max(args.von, offline["musik_von_s"] - 0.5))
    ergebnis = auswerten(aufzeichnung, offline, marken)
    bild(aufzeichnung, offline, marken, Path(args.bild))
    text = json.dumps(ergebnis, ensure_ascii=False, indent=1)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
