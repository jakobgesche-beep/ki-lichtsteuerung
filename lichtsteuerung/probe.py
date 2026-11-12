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
from .weitere import WeitereAufnahmen

ANALYSE_VERSION = 3          # 3: mit den großen Schlägen der Band (schlaege_s)
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
            "musik_von_s": erg["musik_von_s"], "musik_bis_s": erg.get("musik_bis_s"),
            "beats_s": erg["beats_s"], "einsen_s": erg["einsen_s"],
            "schlaege_s": erg.get("schlaege_s", []), "version": ANALYSE_VERSION}


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
SCHLAG_S = 0.25           # ein Schlag-Akzent (großer Schlag der Band): kurz weiß, kein Strobo


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
        schlaege = schlaege_im_teil(analyse, teil, klasse)
        if schlaege and abs(schlaege[0] - teil["start"]) <= 0.3:
            # Der Teil beginnt mit einem großen Schlag: erst kurz weiß, dann der neue Look
            karte[-1]["cue"] = len(cues)
            cues.append(schlag_cue(gruppen))
            zeitcode.append(teil["start"])
            schlaege = schlaege[1:]
            zeit_look = round(teil["start"] + SCHLAG_S, 2)
        else:
            zeit_look = teil["start"]
        cues.append(cue)
        zeitcode.append(zeit_look)
        akzente = [(stelle, "akzent") for stelle in akzente_im_teil(analyse, teil)]
        akzente += [(stelle, "schlag") for stelle in schlaege
                    if all(abs(stelle - a) > 1.5 for a, _ in akzente) and stelle > zeit_look + 0.5]
        for stelle, art in sorted(akzente):
            dauer = AKZENT_S if art == "akzent" else SCHLAG_S
            cues += [akzent_cue(gruppen) if art == "akzent" else schlag_cue(gruppen),
                     {**cue, "name": cue["name"] + " weiter", "zeit_s": 0.5}]
            zeitcode += [stelle, round(stelle + dauer, 2)]
    return {"name": analyse["name"], "cues": cues, "zeitcode": zeitcode,
            "farben": [farbe_a, farbe_b],
            "song": {"probe": analyse["name"], "tempo_bpm": analyse["tempo_bpm"], "dauer_s": analyse["dauer_s"],
                     "musik_von_s": analyse.get("musik_von_s", 0.0), "musik_bis_s": analyse.get("musik_bis_s"),
                     "teile": karte},
            "_hinweis": "Automatisch aus der Probe gebaut. Im Pult frei änderbar."}


def akzente_im_teil(analyse: dict, teil: dict) -> list:
    """Markierte Stellen (Taste D) und erkannte Drops, die mitten in diesem Teil liegen."""
    stellen = sorted(set(analyse.get("markiert_s", [])) | set(analyse.get("drops_s", [])))
    ergebnis = []
    for stelle in stellen:
        if teil["start"] + 0.5 < stelle < teil["ende"] - AKZENT_S and (not ergebnis or stelle - ergebnis[-1] > 1.0):
            ergebnis.append(stelle)
    return ergebnis


def schlaege_im_teil(analyse: dict, teil: dict, klasse: str) -> list:
    """Große Schläge der Band in diesem Teil (auch genau am Anfang). In ruhigen Teilen keine: Da passt kein Blitz."""
    if klasse == "ruhig" or teil.get("name") in ("Intro", "Schluss", "Aufbau", "Überleitung", "Drop"):
        return []
    return [s for s in analyse.get("schlaege_s", []) if teil["start"] - 0.3 <= s < teil["ende"] - 0.5]


def schlag_cue(gruppen: list) -> dict:
    """Ein großer Schlag der Band: Spots und PARs kurz weiß und voll (ohne Strobo), dann weiter im Look."""
    werte = [{"gruppe": g, "helligkeit": 1.0, "farbe": "weiss"} for g in ("Spots", "Farb-PARs") if g in gruppen]
    return {"name": "Schlag", "zeit_s": 0.0, "folgen_s": SCHLAG_S, "werte": werte, "effekte": []}


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


TEIL_NAMEN = ["Intro", "Strophe", "Überleitung", "Refrain", "Bridge", "Solo", "Zwischenteil", "Aufbau", "Drop",
              "Finale", "Schluss"]
KLASSEN = ["ruhig", "mittel", "stark", "hoehepunkt"]


def _takte_zaehlen(einsen: list, start: float, ende: float) -> int:
    return max(1, sum(1 for e in einsen if start - 0.05 <= e < ende - 0.05))


def _auf_takt(einsen: list, zeit: float) -> float:
    """Zur nächsten Takt-Eins (wenn es welche gibt)."""
    if not einsen:
        return round(zeit, 2)
    return float(min(einsen, key=lambda e: abs(e - zeit)))


def teile_aendern(analyse: dict, aktion: str, index: int, wert=None) -> dict:
    """Songteile von Hand richtigstellen. Grenzen liegen immer auf einer Takt-Eins.

        name / klasse   Teil umbenennen (Refrain, Strophe ...) oder Stärke ändern (wie viel Licht)
        verschieben     Anfang des Teils um wert Takte (-1 oder +1) verschieben
        teilen          Teil in der Mitte teilen (wert: Zeit in Sekunden, sonst die Mitte)
        verbinden       Teil mit dem nächsten zusammenlegen
        marken          Deine D-Marken aus der Aufnahme werden die Grenzen
    """
    analyse = {**analyse, "teile": [dict(t) for t in analyse["teile"]]}
    teile = analyse["teile"]
    einsen = list(analyse.get("einsen_s") or [])
    if aktion != "marken" and not 0 <= index < len(teile):
        raise ValueError("Diesen Teil gibt es nicht.")
    if aktion == "name":
        name = str(wert or "").strip()
        if not name or len(name) > 24:
            raise ValueError("Der Name ist leer oder zu lang.")
        teile[index]["name"] = name
    elif aktion == "klasse":
        if wert not in KLASSEN:
            raise ValueError(f"Stärke muss eine von {', '.join(KLASSEN)} sein.")
        teile[index]["klasse"] = wert
    elif aktion == "verschieben":
        if index == 0:
            raise ValueError("Der Anfang des ersten Teils ist der Song-Anfang.")
        schritt = 1 if (wert or 1) > 0 else -1
        start = teile[index]["start"]
        if einsen:
            nummer = min(range(len(einsen)), key=lambda i: abs(einsen[i] - start))
            neu = einsen[max(0, min(len(einsen) - 1, nummer + schritt))]
        else:
            neu = start + schritt * 240.0 / max(analyse.get("tempo_bpm", 120), 40)
        if not teile[index - 1]["start"] + 0.5 < neu < teile[index]["ende"] - 0.5:
            raise ValueError("Weiter geht es nicht: Der Teil wäre sonst leer.")
        teile[index]["start"] = teile[index - 1]["ende"] = round(float(neu), 3)
    elif aktion == "teilen":
        teil = teile[index]
        zeit = _auf_takt(einsen, float(wert) if wert is not None else (teil["start"] + teil["ende"]) / 2)
        if not teil["start"] + 0.5 < zeit < teil["ende"] - 0.5:
            raise ValueError("Der Teil ist zu kurz zum Teilen.")
        neu = {**teil, "start": round(zeit, 3)}
        teil["ende"] = round(zeit, 3)
        teile.insert(index + 1, neu)
    elif aktion == "verbinden":
        if index + 1 >= len(teile):
            raise ValueError("Nach dem letzten Teil kommt keiner mehr.")
        teile[index]["ende"] = teile[index + 1]["ende"]
        del teile[index + 1]
    elif aktion == "marken":
        marken = sorted(_auf_takt(einsen, m) for m in analyse.get("markiert_s") or [])
        anfang, ende = teile[0]["start"], teile[-1]["ende"]
        grenzen = [anfang] + [m for m in dict.fromkeys(marken) if anfang + 1.0 < m < ende - 1.0] + [ende]
        if len(grenzen) < 3:
            raise ValueError("In dieser Aufnahme gibt es keine D-Marken. Taste D während der Aufnahme setzt welche.")
        alt = teile
        teile = []
        for von, bis in zip(grenzen, grenzen[1:]):
            # Name und Stärke vom alten Teil, der hier am meisten Zeit hat
            vorbild = max(alt, key=lambda t: min(t["ende"], bis) - max(t["start"], von))
            teile.append({**vorbild, "start": round(von, 3), "ende": round(bis, 3)})
        analyse["teile"] = teile
    else:
        raise ValueError(f"Unbekannte Änderung {aktion!r}.")
    for teil in analyse["teile"]:
        teil["takte"] = _takte_zaehlen(einsen, teil["start"], teil["ende"]) if einsen else teil.get("takte")
    analyse["von_hand"] = True
    return analyse


class Proben:
    """Ablage der Aufnahmen und Analysen in daten/proben/."""

    def __init__(self, ordner: Path):
        self.ordner = Path(ordner)
        self.weitere = WeitereAufnahmen(self.ordner)      # Mitschnitte und weitere Proben

    def namen(self) -> list:
        namen = []
        for pfad in self.ordner.glob("*.json"):
            inhalt = daten.lese_json_sicher(pfad)
            if isinstance(inhalt, dict) and isinstance(inhalt.get("name"), str):
                namen.append(inhalt["name"])
        return sorted(namen)

    def lesen(self, name: str) -> Optional[dict]:
        inhalt = daten.lese_json_sicher(self.ordner / f"{daten.dateiname(name)}.json")
        return inhalt if isinstance(inhalt, dict) else None

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

    def neu_analysieren(self, name: str) -> Optional[dict]:
        """Ältere Analysen (vor der neuen Erkennung) noch einmal machen. Markierungen bleiben."""
        alt = self.lesen(name)
        pfad = self.ton_pfad(name)
        if alt is None or not pfad.exists():
            return alt
        if alt.get("version", 1) >= ANALYSE_VERSION:
            if alt.get("musik_bis_s") is None:
                # Fehlte in Version 2.1: Wo die Musik aufhört (fürs Applaus-Licht). Schnell nachgerechnet.
                ton = lade_datei(pfad)
                alt["musik_bis_s"] = round(songanalyse.musik_ende(songanalyse.spektral_merkmale(ton)["baender"]), 2)
                daten.schreibe_json(self.ordner / f"{daten.dateiname(name)}.json", alt)
            return alt
        analyse = analysieren(lade_datei(pfad), alt.get("name", name))
        if alt.get("markiert_s"):
            analyse["markiert_s"] = alt["markiert_s"]
        if alt.get("von_hand"):
            # Von Hand Richtiggestelltes bleibt immer: nur Neues (zum Beispiel die Schläge) kommt dazu.
            analyse.update(teile=alt["teile"], von_hand=True)
        daten.schreibe_json(self.ordner / f"{daten.dateiname(name)}.json", analyse)
        return analyse

    def teile_aendern(self, name: str, aktion: str, index: int, wert=None) -> dict:
        alt = self.lesen(name)
        if alt is None:
            raise ValueError(f"Probe {name!r} gibt es nicht.")
        if alt.get("version", 1) < ANALYSE_VERSION:
            alt = self.neu_analysieren(name) or alt
        neu = teile_aendern(alt, aktion, int(index), wert)
        daten.schreibe_json(self.ordner / f"{daten.dateiname(name)}.json", neu)
        return neu

    def aus_datei(self, name: str, pfad: Path) -> dict:
        return self.speichern(name, lade_datei(pfad))

    def loeschen(self, name: str) -> None:
        for endung in (".json", ".wav"):
            (self.ordner / f"{daten.dateiname(name)}{endung}").unlink(missing_ok=True)
        self.weitere.alle_loeschen(name)


__all__ = ["Proben", "analysieren", "show_bauen", "EigeneBeatErkennung"]
