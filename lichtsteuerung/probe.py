"""Probe: Songs aufnehmen, analysieren und daraus eine Lichtshow bauen.

Ablauf:
  1. In der Probe nimmt das Programm die Summe vom Pult auf (oder man nimmt eine Audiodatei).
  2. Die Analyse (audio/songanalyse.py) findet Tempo, Beats, Takt-Einsen und Songteile.
     Teile mit derselben Akkordfolge bekommen denselben Buchstaben (A, B, C ...),
     daraus folgen die Namen: Der lauteste wiederholte Teil ist der Refrain.
  3. Daraus entsteht eine Sequenz mit einem Cue pro Songteil. Gleiche Teile sehen
     gleich aus, der letzte Refrain bekommt das meiste Licht.
  4. Live drückt man einmal Start, wenn die Band anfängt. Der Song-Folger
     (audio/folgen.py) hört mit und schaltet die Teile von selbst weiter.

Alles läuft ohne Internet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from . import daten
from .audio import songanalyse
from .audio.analyse import Analyse, EigeneBeatErkennung, beat_erkennung
from .audio.quellen import ABTASTRATE, BLOCK, lade_datei

ANALYSE_VERSION = 2
KLASSEN = ("ruhig", "mittel", "stark", "hoehepunkt")


def drops_und_aufbau(ton: np.ndarray) -> tuple:
    """Spielt den Song einmal durch die Live-Analyse: Wo sind Drops und Aufbauten?"""
    analyse = Analyse(beat_erkennung())
    drops, aufbau = [], []
    for start in range(0, len(ton) - BLOCK, BLOCK):
        werte = analyse.verarbeite(ton[start:start + BLOCK])
        zeit = start / ABTASTRATE
        if werte.drop:
            drops.append(round(zeit, 2))
        if werte.spannung >= 0.3:
            aufbau.append(zeit)
    return drops, aufbau


def tempo_und_beats(ton: np.ndarray) -> tuple:
    """Tempo und Beats aus der neuen Songanalyse, Drops und Aufbau aus der Live-Analyse."""
    ergebnis = songanalyse.analysieren(ton)
    drops, aufbau = drops_und_aufbau(ton)
    return ergebnis["tempo_bpm"], ergebnis["beats_s"], drops, aufbau


def _aufbau_beginn(zeiten: list) -> list:
    """Erster Zeitpunkt jedes zusammenhängenden Aufbaus."""
    beginn, letzte = [], None
    for zeit in zeiten:
        if letzte is None or zeit - letzte > 1.0:
            beginn.append(round(zeit, 2))
        letzte = zeit
    return beginn


def _drops_einbauen(teile: list, drops: list, einsen: list) -> list:
    """Ein Drop beginnt immer einen neuen Teil, genau dort."""
    for drop in drops:
        for nummer, teil in enumerate(teile):
            if teil["start"] - 0.3 <= drop < teil["ende"]:
                if abs(drop - teil["start"]) < 1.0:
                    teil["drop"] = True
                elif teil["ende"] - drop > 2.0:
                    neu = dict(teil, start=round(drop, 2), drop=True)
                    teil["ende"] = round(drop, 2)
                    teile.insert(nummer + 1, neu)
                break
    for teil in teile:
        teil["takte"] = max(1, sum(1 for e in einsen if teil["start"] - 0.05 <= e < teil["ende"] - 0.05)) if einsen else teil.get("takte", 0)
    return teile


def analysieren(ton: np.ndarray, name: str) -> dict:
    erg = songanalyse.analysieren(ton)
    drops, aufbau = drops_und_aufbau(ton)
    teile = _drops_einbauen([dict(t) for t in erg["teile"]], drops, erg["einsen_s"])
    einordnen(teile)
    aufbau_starts = _aufbau_beginn(aufbau)
    for nummer, teil in enumerate(teile):
        naechster = teile[nummer + 1] if nummer + 1 < len(teile) else None
        if teil.pop("drop", False):
            teil.update(name="Drop", klasse="hoehepunkt")
        elif naechster is not None and naechster.get("drop") and any(teil["start"] - 0.3 <= a < teil["ende"] for a in aufbau_starts):
            teil["name"] = "Aufbau"
    return {"name": name, "dauer_s": erg["dauer_s"], "tempo_bpm": erg["tempo_bpm"], "teile": teile, "drops_s": drops,
            "musik_von_s": erg["musik_von_s"], "beats_s": erg["beats_s"], "einsen_s": erg["einsen_s"],
            "version": ANALYSE_VERSION}


def einordnen(teile: list) -> None:
    """Gibt jedem Teil Stärke, Buchstaben, Namen und Klasse.

    Buchstaben: gleiche Akkordfolge, gleicher Buchstabe (in der Reihenfolge des Songs).
    Namen: Der wiederholte Teil mit dem meisten Druck ist der Refrain, der früheste
    andere wiederholte Teil die Strophe. Ein kurzer Teil direkt vor dem Refrain ist die
    Überleitung, ein einzelner Teil nach dem zweiten Refrain die Bridge.
    Klasse (wie viel Licht): aus der Lautstärke, aber der Refrain ist mindestens "stark"
    und der letzte Refrain ist der Höhepunkt.
    """
    if not teile:
        return
    laut = np.array([t.get("laut_db", 0.0) for t in teile])
    unten, oben = float(laut.min()), float(laut.max())
    spanne = max(oben - unten, 6.0)           # weniger als 6 dB Unterschied zählt kaum
    buchstaben = {}
    for teil, wert in zip(teile, laut):
        teil["staerke"] = round(float((wert - unten) / spanne), 2)
        roh = teil["gruppe"]
        teil["gruppe"] = buchstaben.setdefault(roh, chr(ord("A") + len(buchstaben))) if not isinstance(roh, str) else roh
    anzahl, mitte = {}, {}
    for nummer, teil in enumerate(teile):
        anzahl[teil["gruppe"]] = anzahl.get(teil["gruppe"], 0) + 1
        if 0 < nummer < len(teile) - 1:
            mitte[teil["gruppe"]] = mitte.get(teil["gruppe"], 0) + 1
    # Ein Teil, der nur ganz am Anfang und ganz am Ende vorkommt, ist Intro und Schluss.
    wiederholt = [g for g, n in anzahl.items() if n > 1 and mitte.get(g, 0) > 0]

    def druck(gruppe):
        return float(np.mean([t["staerke"] for t in teile if t["gruppe"] == gruppe]))

    refrain = max(wiederholt, key=druck, default=None)
    andere = [g for g in wiederholt if g != refrain]
    strophe = min(andere, key=lambda g: min(i for i, t in enumerate(teile) if t["gruppe"] == g), default=None)
    refrain_stellen = [i for i, t in enumerate(teile) if t["gruppe"] == refrain]
    for nummer, teil in enumerate(teile):
        g = teil["gruppe"]
        naechster = teile[nummer + 1]["gruppe"] if nummer + 1 < len(teile) else None
        if g == refrain:
            teil["name"] = "Refrain"
        elif nummer == 0 and mitte.get(g, 0) == 0 and len(teile) > 2:
            teil["name"] = "Intro"
        elif nummer == len(teile) - 1 and mitte.get(g, 0) == 0 and len(teile) > 2:
            teil["name"] = "Schluss" if teil["staerke"] < 0.6 else "Finale"
        elif g == strophe:
            teil["name"] = "Strophe"
        elif naechster == refrain and teil.get("takte", 99) <= 8:
            teil["name"] = "Überleitung"
        elif anzahl[g] == 1 and len(refrain_stellen) >= 2 and nummer > refrain_stellen[1]:
            teil["name"] = "Bridge"
        else:
            teil["name"] = "Zwischenteil"
        s = teil["staerke"]
        klasse = "ruhig" if s < 0.3 else "mittel" if s < 0.6 else "stark" if s < 0.85 else "hoehepunkt"
        if teil["name"] == "Refrain":
            klasse = "stark" if klasse in ("ruhig", "mittel") else klasse
        elif teil["name"] in ("Strophe", "Intro") and klasse == "hoehepunkt":
            klasse = "stark"
        teil["klasse"] = klasse
        teil.pop("laut_db", None)
    # Der letzte Refrain (und ein direkt folgender) ist der Höhepunkt des Songs.
    if refrain_stellen:
        letzte = refrain_stellen[-1]
        teile[letzte]["klasse"] = "hoehepunkt"
        if letzte - 1 in refrain_stellen:
            teile[letzte - 1]["klasse"] = "hoehepunkt"


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


def look_cue(name: str, klasse: str, gruppen: list, farbe_a: str, farbe_b: str, gobo: Optional[str] = None,
             band: Optional[str] = None, drop: bool = False, zeit_s: Optional[float] = None) -> dict:
    """Ein Look als Cue: Farbe, Gobo, stehen oder bewegen, Puls im Beat. Für Songs und Show-Tasten."""
    bewegung, groesse, beats, hell, drehung, tiefe, farben = LOOKS[klasse]
    if drop:
        bewegung, groesse, beats, drehung = "acht", 1.0, 4, 0.8
    haupt = farbe_b if farben == "B" else farbe_a
    werte, effekte = [], []
    if "Spots" in gruppen:
        wert = {"gruppe": "Spots", "helligkeit": hell, "farbe": haupt,
                "gobo": gobo if gobo and klasse != "ruhig" else "Offen"}
        if gobo and drehung and klasse != "ruhig":
            wert["gobo_drehung"] = drehung
        if band and not bewegung:
            wert["position"] = band            # stehendes Licht zeigt auf die Band
        werte.append(wert)
        if bewegung:
            effekte.append({"art": bewegung, "ziel": {"gruppe": "Spots"}, "groesse": groesse,
                            "tempo": "musik", "beats": beats, "verteilung": 0.5})
        if farben == "AB":
            effekte.append({"art": "farbwechsel", "ziel": {"gruppe": "Spots"}, "tempo": "musik",
                            "beats": 8, "verteilung": 0.5, "farben": [farbe_a, farbe_b]})
    if "Farb-PARs" in gruppen:
        werte.append({"gruppe": "Farb-PARs", "helligkeit": hell, "farbe": farbe_b if farben != "B" else farbe_a})
        if farben == "AB":
            effekte.append({"art": "farbwechsel", "ziel": {"gruppe": "Farb-PARs"}, "tempo": "musik",
                            "beats": 8, "verteilung": 0.5, "farben": [farbe_b, farbe_a]})
    puls = "dimmer_welle" if klasse == "ruhig" else "dimmer_puls"
    for ziel in ("Spots", "Farb-PARs"):
        if ziel in gruppen:
            effekte.append({"art": puls, "ziel": {"gruppe": ziel}, "tempo": "musik", "tiefe": tiefe,
                            "beats": 16 if puls == "dimmer_welle" else (1 if drop else 2), "verteilung": 0.5})
    if "Strobo" in gruppen:
        # Im Höhepunkt blitzt er. Wie lange, begrenzt die Prüfung (Dauer, dann Pause).
        werte.append({"gruppe": "Strobo", "helligkeit": 1.0 if klasse == "hoehepunkt" else 0.0,
                      "strobo_hz": 3.0 if klasse == "hoehepunkt" else 0.0})
    return {"name": name, "zeit_s": ZEITEN_S[klasse] if zeit_s is None else zeit_s,
            "folgen_s": None, "werte": werte, "effekte": effekte}


def show_bauen(analyse: dict, patch, palette: list, gobos_von, positionen: Optional[dict] = None) -> dict:
    """Baut die Sequenz: ein Cue pro Songteil, dazu Akzente an markierten Stellen.

    Gleiche Buchstaben sehen gleich aus. Strophen sind ruhiger, Refrain und Höhepunkt
    bewegen sich und tauschen die zwei Song-Farben. Eine Überleitung vor dem Refrain
    baut Spannung auf (weiß in die Mitte). Der Strobo blitzt nur bei Höhepunkt, Drop
    und Akzenten, und nur so weit die Prüfung es erlaubt.
    In "song" steht die Song-Karte für den Song-Start: Teile, Zeiten, Tempo.
    """
    gruppen = patch.gruppen()
    farbe_a = palette[0]
    farbe_b = palette[1 % len(palette)]
    gobos = gobos_von("Spots") if "Spots" in gruppen else []
    band = "Band" if positionen and "Band" in positionen else None
    cues, zeitcode, karte = [], [], []
    buchstaben = {}
    teile = analyse["teile"]
    for index, teil in enumerate(teile):
        nummer = buchstaben.setdefault(teil["gruppe"], len(buchstaben))
        naechster = teile[index + 1] if index + 1 < len(teile) else None
        takte = teil.get("takte") or round((teil["ende"] - teil["start"]) * analyse["tempo_bpm"] / 60 / 4)
        titel = f"{teil['name']} {teil['gruppe']} ({takte} Takte)"
        klasse = "hoehepunkt" if teil["name"] == "Drop" else teil["klasse"]
        karte.append({"name": teil["name"], "gruppe": teil["gruppe"], "klasse": klasse, "start": teil["start"],
                      "ende": teil["ende"], "takte": takte, "cue": len(cues)})
        if teil["name"] == "Aufbau" or (teil["name"] == "Überleitung" and naechster and naechster["name"] in ("Refrain", "Drop")):
            cue = aufbau_cue(teil, gruppen, farbe_b)
            cue["name"] = titel
            cues.append(cue)
            zeitcode.append(teil["start"])
            continue
        if teil["name"] == "Schluss":
            klasse = "ruhig"
        # Gleich starke, aber verschiedene Teile tauschen A und B, damit man den Wechsel sieht.
        a, b = (farbe_a, farbe_b) if nummer % 2 == 0 else (farbe_b, farbe_a)
        gobo = gobos[nummer % len(gobos)] if gobos else None
        cue = look_cue(titel, klasse, gruppen, a, b, gobo, band, drop=teil["name"] == "Drop",
                       zeit_s=4.0 if teil["name"] == "Schluss" else None)
        cues.append(cue)
        zeitcode.append(teil["start"])
        for stelle in akzente_im_teil(analyse, teil):
            cues += [akzent_cue(gruppen), {**cue, "name": cue["name"] + " weiter", "zeit_s": 0.5}]
            zeitcode += [stelle, round(stelle + AKZENT_S, 2)]
    return {"name": analyse["name"], "cues": cues, "zeitcode": zeitcode,
            "farben": [farbe_a, farbe_b],
            "song": {"probe": analyse["name"], "tempo_bpm": analyse["tempo_bpm"], "dauer_s": analyse["dauer_s"],
                     "musik_von_s": analyse.get("musik_von_s", 0.0), "teile": karte},
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
