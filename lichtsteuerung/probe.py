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
    """Spielt den Song einmal durch die Live-Analyse: Tempo, Beats, Drops und Aufbau."""
    analyse = Analyse(beat_erkennung())
    beats, drops, aufbau = [], [], []
    for start in range(0, len(ton) - BLOCK, BLOCK):
        werte = analyse.verarbeite(ton[start:start + BLOCK])
        zeit = start / ABTASTRATE
        if werte.beat:
            beats.append(zeit)
        if werte.drop:
            drops.append(round(zeit, 2))
        if werte.spannung >= 0.3:
            aufbau.append(zeit)
    tempo = analyse.tempo if 40 <= analyse.tempo <= 240 else 120.0
    return round(float(tempo), 1), beats, drops, aufbau


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
    tempo, beats, drops, aufbau = tempo_und_beats(ton)
    zeiten = [0.0] + [auf_takt(i * SCHRITT_S, beats, tempo) for i in grenzen_finden(werte)] + [dauer]
    # Ein Drop ist immer ein Wechsel, genau an seiner Stelle. Ein Wechsel kurz davor fällt weg.
    zeiten = [z for z in zeiten if not any(0 < abs(z - d) < 2.0 for d in drops)] + drops
    zeiten += [a for a in _aufbau_beginn(aufbau)]
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
    for teil in teile:
        if any(abs(teil["start"] - d) < 0.3 for d in drops):
            teil.update(name="Drop", klasse="hoehepunkt")
        elif any(teil["start"] - 0.3 <= a < teil["ende"] for a in aufbau) and any(
                abs(teil["ende"] - d) < 0.3 for d in drops):
            teil["name"] = "Aufbau"
    return {"name": name, "dauer_s": round(dauer, 2), "tempo_bpm": tempo, "teile": teile, "drops_s": drops}


def _aufbau_beginn(zeiten: list) -> list:
    """Erster Zeitpunkt jedes zusammenhängenden Aufbaus."""
    beginn, letzte = [], None
    for zeit in zeiten:
        if letzte is None or zeit - letzte > 1.0:
            beginn.append(round(zeit, 2))
        letzte = zeit
    return beginn


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

# So sieht jede Stärke aus. Der Song bekommt nur zwei Farben (A und B) und Weiß für Akzente,
# damit es zusammenpasst und nicht wie eine bunte Lichterkette wirkt.
LOOKS = {
    #              Bewegung, Größe, Beats/Runde, Helligkeit, Gobo-Drehung, Puls-Tiefe, Farben
    "ruhig":      (None,      0.0, 16, 0.5, 0.0, 0.3, "B"),
    "mittel":     (None,      0.0, 16, 0.7, 0.0, 0.3, "A"),
    "stark":      ("schwenk", 0.5, 16, 1.0, 0.3, 0.35, "A"),
    "hoehepunkt": ("kreis",   0.7, 8,  1.0, 0.6, 0.35, "AB"),
}
ZEITEN_S = {"ruhig": 3.0, "mittel": 2.0, "stark": 1.0, "hoehepunkt": 0.0}
AKZENT_S = 0.4            # so lange dauert ein Akzent, dann geht es von selbst weiter


def show_bauen(analyse: dict, patch, palette: list, gobos_von, positionen: Optional[dict] = None) -> dict:
    """Baut die Sequenz: ein Cue pro Songteil, dazu Akzente an markierten Stellen.

    Gleiche Buchstaben sehen gleich aus. Strophen sind ruhiger, Refrain und Höhepunkt
    bewegen sich und tauschen die zwei Song-Farben. Der Strobo blitzt nur bei
    Höhepunkt, Drop und Akzenten, und nur so weit die Prüfung es erlaubt.
    """
    gruppen = patch.gruppen()
    farbe_a = palette[0]
    farbe_b = palette[1 % len(palette)]
    gobos = gobos_von("Spots") if "Spots" in gruppen else []
    band = "Band" if positionen and "Band" in positionen else None
    cues, zeitcode = [], []
    buchstaben = {}
    for teil in analyse["teile"]:
        nummer = buchstaben.setdefault(teil["gruppe"], len(buchstaben))
        if teil["name"] == "Aufbau":
            cues.append(aufbau_cue(teil, gruppen, farbe_b))
            zeitcode.append(teil["start"])
            continue
        klasse = "hoehepunkt" if teil["name"] == "Drop" else teil["klasse"]
        if teil["name"] == "Schluss":
            klasse = "ruhig"
        bewegung, groesse, beats, hell, drehung, tiefe, farben = LOOKS[klasse]
        if teil["name"] == "Drop":
            bewegung, groesse, beats, drehung = "acht", 1.0, 4, 0.8
        # Gleich starke, aber verschiedene Teile tauschen A und B, damit man den Wechsel sieht.
        a, b = (farbe_a, farbe_b) if nummer % 2 == 0 else (farbe_b, farbe_a)
        haupt = b if farben == "B" else a
        werte, effekte = [], []
        if "Spots" in gruppen:
            wert = {"gruppe": "Spots", "helligkeit": hell, "farbe": haupt,
                    "gobo": gobos[nummer % len(gobos)] if gobos and klasse != "ruhig" else "Offen"}
            if gobos and drehung:
                wert["gobo_drehung"] = drehung
            if band and not bewegung:
                wert["position"] = band            # stehendes Licht zeigt auf die Band
            werte.append(wert)
            if bewegung:
                effekte.append({"art": bewegung, "ziel": {"gruppe": "Spots"}, "groesse": groesse,
                                "tempo": "musik", "beats": beats, "verteilung": 0.5})
            if farben == "AB":
                effekte.append({"art": "farbwechsel", "ziel": {"gruppe": "Spots"}, "tempo": "musik",
                                "beats": 8, "verteilung": 0.5, "farben": [a, b]})
        if "Farb-PARs" in gruppen:
            werte.append({"gruppe": "Farb-PARs", "helligkeit": hell, "farbe": b if farben != "B" else a})
            if farben == "AB":
                effekte.append({"art": "farbwechsel", "ziel": {"gruppe": "Farb-PARs"}, "tempo": "musik",
                                "beats": 8, "verteilung": 0.5, "farben": [b, a]})
        puls = "dimmer_welle" if klasse == "ruhig" else "dimmer_puls"
        for ziel in ("Spots", "Farb-PARs"):
            if ziel in gruppen:
                effekte.append({"art": puls, "ziel": {"gruppe": ziel}, "tempo": "musik", "tiefe": tiefe,
                                "beats": 16 if puls == "dimmer_welle" else 2, "verteilung": 0.5})
        if "Strobo" in gruppen:
            # Im Höhepunkt blitzt er. Wie lange, begrenzt die Prüfung (Dauer, dann Pause).
            werte.append({"gruppe": "Strobo", "helligkeit": 1.0 if klasse == "hoehepunkt" else 0.0,
                          "strobo_hz": 3.0 if klasse == "hoehepunkt" else 0.0})
        takte = round((teil["ende"] - teil["start"]) * analyse["tempo_bpm"] / 60 / 4)
        cue = {"name": f"{teil['name']} {teil['gruppe']} ({takte} Takte)",
               "zeit_s": 4.0 if teil["name"] == "Schluss" else ZEITEN_S[klasse],
               "folgen_s": None, "werte": werte, "effekte": effekte}
        cues.append(cue)
        zeitcode.append(teil["start"])
        for stelle in akzente_im_teil(analyse, teil):
            cues += [akzent_cue(gruppen), {**cue, "name": cue["name"] + " weiter", "zeit_s": 0.5}]
            zeitcode += [stelle, round(stelle + AKZENT_S, 2)]
    return {"name": analyse["name"], "cues": cues, "zeitcode": zeitcode,
            "farben": [farbe_a, farbe_b],
            "_hinweis": "Automatisch aus der Probe gebaut. Im Pult frei änderbar."}


def akzente_im_teil(analyse: dict, teil: dict) -> list:
    """Markierte Stellen (Taste D) und erkannte Drops, die mitten in diesem Teil liegen."""
    stellen = sorted(set(analyse.get("markiert_s", [])) | set(analyse.get("drops_s", [])))
    ergebnis = []
    for stelle in stellen:
        if teil["start"] + 0.5 < stelle < teil["ende"] - AKZENT_S and (not ergebnis or stelle - ergebnis[-1] > 1.0):
            ergebnis.append(stelle)
    return ergebnis


def akzent_cue(gruppen: list) -> dict:
    """Ein heller Schlag: alles weiß und voll, der Strobo blitzt. Danach geht es von selbst weiter."""
    werte = [{"gruppe": g, "helligkeit": 1.0, "farbe": "weiss"} for g in ("Spots", "Farb-PARs") if g in gruppen]
    if "Strobo" in gruppen:
        werte.append({"gruppe": "Strobo", "helligkeit": 1.0, "strobo_hz": 3.0})
    return {"name": "Akzent", "zeit_s": 0.0, "folgen_s": AKZENT_S, "werte": werte, "effekte": []}


def aufbau_cue(teil: dict, gruppen: list, farbe: str) -> dict:
    """Aufbau: Strahlen in die Mitte, Licht weiß, sanft pulsierend. Der Drop kommt im nächsten Cue."""
    werte, effekte = [], []
    if "Spots" in gruppen:
        werte.append({"gruppe": "Spots", "helligkeit": 0.8, "farbe": "weiss", "gobo": "Offen", "position": "Mitte"})
        effekte.append({"art": "dimmer_puls", "ziel": {"gruppe": "Spots"}, "tempo": "musik", "beats": 1, "verteilung": 0.0})
    if "Farb-PARs" in gruppen:
        werte.append({"gruppe": "Farb-PARs", "helligkeit": 0.7, "farbe": farbe})
        effekte.append({"art": "dimmer_puls", "ziel": {"gruppe": "Farb-PARs"}, "tempo": "musik", "beats": 1, "verteilung": 0.0})
    return {"name": f"Aufbau {teil['gruppe']}", "zeit_s": 2.0, "folgen_s": None, "werte": werte, "effekte": effekte}


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

    def speichern(self, name: str, ton: np.ndarray, markierungen: Optional[list] = None) -> dict:
        import soundfile
        if len(ton) < ABTASTRATE * 10:
            raise ValueError("Die Aufnahme ist kürzer als 10 Sekunden. Läuft der Ton?")
        self.ordner.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(self.ton_pfad(name)), ton, ABTASTRATE, subtype="PCM_16")
        analyse = analysieren(ton, name)
        if markierungen:
            # Wo du "Drop!" gedrückt hast. Damit lässt sich die Erkennung auf echte Songs abstimmen.
            analyse["markiert_s"] = [round(m, 2) for m in markierungen]
        daten.schreibe_json(self.ordner / f"{daten.dateiname(name)}.json", analyse)
        return analyse

    def aus_datei(self, name: str, pfad: Path) -> dict:
        return self.speichern(name, lade_datei(pfad))

    def loeschen(self, name: str) -> None:
        for endung in (".json", ".wav"):
            (self.ordner / f"{daten.dateiname(name)}{endung}").unlink(missing_ok=True)


__all__ = ["Proben", "analysieren", "show_bauen", "EigeneBeatErkennung"]
