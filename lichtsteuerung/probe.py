"""Probe: Songs aufnehmen, analysieren und daraus eine Lichtshow bauen.

Ablauf:
  1. In der Probe nimmt das Programm die Summe vom Pult auf (oder man nimmt eine Audiodatei).
  2. Die Analyse findet Tempo und Songteile: wo es ruhig wird, wo der Refrain kommt.
     Teile, die gleich klingen, bekommen denselben Buchstaben (A, B, C ...).
  3. Daraus entsteht eine Sequenz mit einem Cue pro Songteil. Gleiche Teile sehen
     gleich aus, der Höhepunkt bekommt das meiste Licht.
  4. Live drückt man Go+, wenn der nächste Teil kommt. Die Effekte laufen im Tempo
     der Band mit, denn eine Band spielt nie genau wie in der Probe.

Alles läuft ohne Internet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from . import daten
from .audio.analyse import Analyse, EigeneBeatErkennung, beat_erkennung
from .audio.quellen import ABTASTRATE, BLOCK, lade_datei

SCHRITT_S = 0.5          # alle halbe Sekunde ein Messpunkt
FENSTER_S = 8.0          # so weit schaut die Suche nach Wechseln vor und zurück
KUERZESTER_TEIL_S = 8.0

KLASSEN = ("ruhig", "mittel", "stark", "hoehepunkt")


def merkmale(ton: np.ndarray) -> np.ndarray:
    """Pro halbe Sekunde: Lautstärke, Bass-Anteil, Höhen-Anteil, Unruhe."""
    schritt = int(SCHRITT_S * ABTASTRATE)
    fenster = np.hanning(schritt * 2)
    freq = np.fft.rfftfreq(schritt * 2, 1 / ABTASTRATE)
    bass, hoch = freq < 150, freq > 2500
    zeilen, vorher = [], None
    for start in range(0, max(len(ton) - 2 * schritt, 1), schritt):
        stueck = ton[start:start + 2 * schritt]
        if len(stueck) < 2 * schritt:
            break
        spektrum = np.abs(np.fft.rfft(stueck * fenster)) + 1e-9
        gesamt = spektrum.sum()
        laut = 20 * np.log10(np.sqrt(np.mean(stueck ** 2)) + 1e-6)
        unruhe = 0.0 if vorher is None else float(np.mean(np.abs(np.log(spektrum) - np.log(vorher))))
        vorher = spektrum
        zeilen.append([laut, spektrum[bass].sum() / gesamt, spektrum[hoch].sum() / gesamt, unruhe])
    return np.array(zeilen) if zeilen else np.zeros((0, 4))


def tempo_und_beats(ton: np.ndarray) -> tuple:
    analyse = Analyse(beat_erkennung())
    beats = []
    for start in range(0, len(ton) - BLOCK, BLOCK):
        if analyse.verarbeite(ton[start:start + BLOCK]).beat:
            beats.append(start / ABTASTRATE)
    tempo = analyse.tempo if 40 <= analyse.tempo <= 240 else 120.0
    return round(float(tempo), 1), beats


def grenzen_finden(werte: np.ndarray) -> list:
    """Wo sich der Klang deutlich ändert. Gibt Stellen in Messpunkten zurück."""
    if len(werte) < 4:
        return []
    norm = (werte - werte.mean(axis=0)) / (werte.std(axis=0) + 1e-9)
    norm[:, 0] *= 2.0       # Lautstärke zählt doppelt
    k = int(FENSTER_S / SCHRITT_S)
    neuheit = np.zeros(len(norm))
    for i in range(k, len(norm) - k):
        neuheit[i] = np.linalg.norm(norm[i:i + k].mean(axis=0) - norm[i - k:i].mean(axis=0))
    schwelle = neuheit[neuheit > 0].mean() + 0.5 * neuheit[neuheit > 0].std() if neuheit.any() else np.inf
    abstand = int(KUERZESTER_TEIL_S / SCHRITT_S)
    stellen = []
    for i in np.argsort(-neuheit):
        if neuheit[i] < schwelle:
            break
        if all(abs(i - j) >= abstand for j in stellen):
            stellen.append(int(i))
    return sorted(stellen)


def auf_takt(sekunde: float, beats: list, tempo: float) -> float:
    """Ein Wechsel kommt fast immer auf dem ersten Schlag eines Takts."""
    if not beats:
        return sekunde
    takt = 4 * 60.0 / tempo
    erster = beats[0]
    return round(erster + round((sekunde - erster) / takt) * takt, 2)


def analysieren(ton: np.ndarray, name: str) -> dict:
    dauer = len(ton) / ABTASTRATE
    werte = merkmale(ton)
    tempo, beats = tempo_und_beats(ton)
    zeiten = [0.0] + [auf_takt(i * SCHRITT_S, beats, tempo) for i in grenzen_finden(werte)] + [dauer]
    zeiten = sorted({max(0.0, min(dauer, z)) for z in zeiten})
    teile = []
    for start, ende in zip(zeiten, zeiten[1:]):
        if ende - start < 2.0:
            continue
        stueck = werte[int(start / SCHRITT_S):max(int(ende / SCHRITT_S), int(start / SCHRITT_S) + 1)]
        teile.append({"start": round(start, 2), "ende": round(ende, 2), "merkmal": stueck.mean(axis=0).tolist()})
    if not teile:
        teile = [{"start": 0.0, "ende": round(dauer, 2), "merkmal": werte.mean(axis=0).tolist() if len(werte) else [0, 0, 0, 0]}]
    einordnen(teile)
    return {"name": name, "dauer_s": round(dauer, 2), "tempo_bpm": tempo, "teile": teile}


def einordnen(teile: list) -> None:
    """Gibt jedem Teil Stärke, Buchstaben und einen Namen wie "Refrain"."""
    lautheit = np.array([t["merkmal"][0] for t in teile])
    unten, oben = lautheit.min(), lautheit.max()
    spanne = max(oben - unten, 6.0)          # weniger als 6 dB Unterschied zählt kaum
    for teil, laut in zip(teile, lautheit):
        anteil = (laut - unten) / spanne
        teil["staerke"] = round(float(anteil), 2)
        teil["klasse"] = "ruhig" if anteil < 0.3 else "mittel" if anteil < 0.6 else "stark" if anteil < 0.9 else "hoehepunkt"
    # Gleich klingende Teile bekommen denselben Buchstaben.
    merkmale_ = np.array([t["merkmal"] for t in teile])
    skala = merkmale_.std(axis=0) + 1e-9
    buchstaben = []
    for nummer, teil in enumerate(teile):
        gefunden = None
        for frueher in range(nummer):
            if np.linalg.norm((merkmale_[nummer] - merkmale_[frueher]) / skala) < 1.2:
                gefunden = buchstaben[frueher]
                break
        buchstaben.append(gefunden or chr(ord("A") + len(set(buchstaben))))
        teil["gruppe"] = buchstaben[-1]
    lauteste_wiederholung = max((t for t in teile if buchstaben.count(t["gruppe"]) > 1),
                                key=lambda t: t["staerke"], default=None)
    for nummer, teil in enumerate(teile):
        if nummer == 0 and teil["klasse"] in ("ruhig", "mittel") and len(teile) > 2:
            teil["name"] = "Intro"
        elif nummer == len(teile) - 1 and len(teile) > 2 and teil["staerke"] < 0.6:
            teil["name"] = "Schluss"
        elif lauteste_wiederholung and teil["gruppe"] == lauteste_wiederholung["gruppe"]:
            teil["name"] = "Refrain"
        elif teil["klasse"] == "hoehepunkt":
            teil["name"] = "Höhepunkt"
        elif buchstaben.count(teil["gruppe"]) > 1:
            teil["name"] = "Strophe"
        else:
            teil["name"] = "Zwischenteil"
        teil.pop("merkmal")


# --- Aus der Analyse eine Show bauen --------------------------------------------

LOOKS = {
    # Bewegung (None = steht), Größe, Beats pro Runde, Helligkeit, Gobo-Drehung, Licht-Effekt
    "ruhig":      (None, 0.0, 16, 0.6, 0.0, "dimmer_welle"),
    "mittel":     (None, 0.0, 16, 0.85, 0.0, "dimmer_puls"),
    "stark":      ("schwenk", 0.5, 16, 1.0, 0.25, "dimmer_puls"),
    "hoehepunkt": ("kreis", 0.7, 8, 1.0, 0.4, "dimmer_puls"),
}
ZEITEN_S = {"ruhig": 3.0, "mittel": 2.0, "stark": 1.0, "hoehepunkt": 0.0}


def show_bauen(analyse: dict, patch, palette: list, gobos_von) -> dict:
    """Baut die Sequenz. Gleiche Buchstaben bekommen dasselbe Aussehen."""
    gruppen = patch.gruppen()
    cues, zeitcode = [], []
    looks_je_buchstabe = {}
    for nummer, teil in enumerate(analyse["teile"]):
        buchstabe = teil["gruppe"]
        if buchstabe not in looks_je_buchstabe:
            looks_je_buchstabe[buchstabe] = len(looks_je_buchstabe)
        look = looks_je_buchstabe[buchstabe]
        bewegung, groesse, beats, hell, drehung, licht = LOOKS[teil["klasse"]]
        if teil["name"] == "Schluss":
            bewegung, licht = None, "dimmer_welle"
        farbe = palette[look % len(palette)]
        werte, effekte = [], []
        if "Spots" in gruppen:
            wert = {"gruppe": "Spots", "helligkeit": hell, "farbe": farbe}
            gobos = gobos_von("Spots")
            if gobos and teil["klasse"] != "ruhig":
                wert["gobo"] = gobos[look % len(gobos)]
                wert["gobo_drehung"] = drehung
            else:
                wert["gobo"] = "Offen"
            werte.append(wert)
            if bewegung:
                effekte.append({"art": bewegung, "ziel": {"gruppe": "Spots"}, "groesse": groesse,
                                "tempo": "musik", "beats": beats, "verteilung": 0.5})
            if teil["klasse"] == "hoehepunkt":
                # Im Höhepunkt wechseln zwei Farben hin und her, nicht die ganze Palette.
                effekte.append({"art": "farbwechsel", "ziel": {"gruppe": "Spots"}, "tempo": "musik",
                                "beats": 8, "verteilung": 0.5, "farben": [farbe, palette[(look + 1) % len(palette)]]})
        if "Farb-PARs" in gruppen:
            werte.append({"gruppe": "Farb-PARs", "helligkeit": hell,
                          "farbe": palette[(look + 1) % len(palette)]})
            if teil["klasse"] == "hoehepunkt":
                effekte.append({"art": "farbwechsel", "ziel": {"gruppe": "Farb-PARs"}, "tempo": "musik",
                                "beats": 8, "verteilung": 0.5,
                                "farben": [palette[(look + 1) % len(palette)], farbe]})
        # Der Puls im Beat: auf allen Lichtern, die Spots versetzt, damit sie sich abwechseln.
        for ziel in ("Spots", "Farb-PARs"):
            if licht and ziel in gruppen:
                effekte.append({"art": licht, "ziel": {"gruppe": ziel}, "tempo": "musik",
                                "beats": 2 if licht == "dimmer_puls" else 16, "verteilung": 0.5})
        dauer = teil["ende"] - teil["start"]
        takte = round(dauer * analyse["tempo_bpm"] / 60 / 4)
        cues.append({"name": f"{teil['name']} {buchstabe} ({takte} Takte)",
                     "zeit_s": 4.0 if teil["name"] == "Schluss" else ZEITEN_S[teil["klasse"]],
                     "folgen_s": None, "werte": werte, "effekte": effekte})
        zeitcode.append(teil["start"])
    return {"name": analyse["name"], "cues": cues, "zeitcode": zeitcode,
            "_hinweis": "Automatisch aus der Probe gebaut. Im Pult frei änderbar."}


class Proben:
    """Ablage der Aufnahmen und Analysen in daten/proben/."""

    def __init__(self, ordner: Path):
        self.ordner = Path(ordner)

    def namen(self) -> list:
        return sorted(daten.lese_json(p)["name"] for p in self.ordner.glob("*.json"))

    def lesen(self, name: str) -> Optional[dict]:
        return daten.lese_json(self.ordner / f"{daten.dateiname(name)}.json")

    def ton_pfad(self, name: str) -> Path:
        return self.ordner / f"{daten.dateiname(name)}.wav"

    def speichern(self, name: str, ton: np.ndarray) -> dict:
        import soundfile
        if len(ton) < ABTASTRATE * 10:
            raise ValueError("Die Aufnahme ist kürzer als 10 Sekunden. Läuft der Ton?")
        self.ordner.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(self.ton_pfad(name)), ton, ABTASTRATE, subtype="PCM_16")
        analyse = analysieren(ton, name)
        daten.schreibe_json(self.ordner / f"{daten.dateiname(name)}.json", analyse)
        return analyse

    def aus_datei(self, name: str, pfad: Path) -> dict:
        return self.speichern(name, lade_datei(pfad))

    def loeschen(self, name: str) -> None:
        for endung in (".json", ".wav"):
            (self.ordner / f"{daten.dateiname(name)}{endung}").unlink(missing_ok=True)


__all__ = ["Proben", "analysieren", "show_bauen", "EigeneBeatErkennung"]
