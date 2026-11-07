"""Show-Tasten: Looks zum Drücken, wie die Playback-Tasten an einem Profi-Pult.

Sie funktionieren immer, auch ohne Musik-Erkennung:

    Look-Tasten   Ein Druck, und der Look steht (weich überblendet). Er bleibt,
                  bis eine andere Taste kommt. "Aus" gibt das Licht an Song und Automatik zurück.
    Farben        Farbe 1 und Farbe 2 für alle Looks. Ein Druck ändert den laufenden Look mit.
    Halten        Weiß voll, Strobo und Dunkel gelten nur, solange man drückt
                  (wie die Flash-Tasten am Pult). Nach 20 Sekunden ist von selbst Schluss.
    Tap           Viermal im Takt tippen: Alle Effekte laufen in diesem Tempo.
                  Ohne Ton läuft das Licht im getippten oder zuletzt gehörten Tempo weiter.

Die Not-Tasten (Blackout, Warmweiß, Strobo aus) haben weiter immer Vorrang,
und jeder Wert geht durch die Prüfung (Strobo-Grenze, Publikum).
"""
from __future__ import annotations

from typing import Optional

from .farben import FARBNAMEN
from .probe import akzent_cue, aufbau_cue, look_cue
from .render import Eigenschaften

LOOKS = [
    {"id": "ruhig", "name": "Ruhig", "text": "Farbe 2 steht auf der Band und atmet langsam", "taste": "1"},
    {"id": "strophe", "name": "Strophe", "text": "Farbe 1 steht, pulsiert im Beat", "taste": "2"},
    {"id": "aufbau", "name": "Aufbau", "text": "Weiß in die Mitte, Puls auf jedem Schlag", "taste": "3"},
    {"id": "refrain", "name": "Refrain", "text": "Beide Farben, langsamer Schwenk, Gobos", "taste": "4"},
    {"id": "hoehepunkt", "name": "Höhepunkt", "text": "Kreis, Farben tauschen, Strobo blitzt", "taste": "5"},
    {"id": "drop", "name": "Drop!", "text": "Weißer Schlag, dann schnelle Acht, alles voll", "taste": "6"},
    {"id": "solo", "name": "Solo", "text": "Weißer Spot auf die Band, Farbe 2 leise dahinter", "taste": "7"},
    {"id": "ballade", "name": "Ballade", "text": "Warmweiß, steht, kaum Bewegung", "taste": "8"},
    {"id": "schluss", "name": "Schluss", "text": "4 Sekunden ausblenden", "taste": "9"},
]
HALTEN = {"flash": "Weiß voll", "strobo": "Strobo", "dunkel": "Dunkel"}
HALTEN_MAX_S = 20.0           # eine vergessene oder hängende Halte-Taste geht von selbst aus
FARBEN = ["rot", "orange", "gelb", "gruen", "cyan", "blau", "lila", "pink", "weiss", "warmweiss"]


def look_bauen(look_id: str, patch, farbe_1: str, farbe_2: str, gobos: list, positionen: dict) -> dict:
    """Macht aus einer Look-Taste einen Cue (Eigenschaften, keine DMX-Zahlen)."""
    gruppen = patch.gruppen()
    band = "Band" if "Band" in positionen else None
    gobo = gobos[0] if gobos else None
    name = next((l["name"] for l in LOOKS if l["id"] == look_id), look_id)
    if look_id == "ruhig":
        cue = look_cue(name, "ruhig", gruppen, farbe_1, farbe_2, gobo, band)
    elif look_id == "strophe":
        cue = look_cue(name, "mittel", gruppen, farbe_1, farbe_2, gobo, band)
    elif look_id == "aufbau":
        cue = aufbau_cue({"gruppe": ""}, gruppen, farbe_2)
    elif look_id == "refrain":
        cue = look_cue(name, "stark", gruppen, farbe_1, farbe_2, gobos[1 % len(gobos)] if gobos else None, band)
    elif look_id == "hoehepunkt":
        cue = look_cue(name, "hoehepunkt", gruppen, farbe_1, farbe_2, gobos[2 % len(gobos)] if gobos else None, band)
    elif look_id == "drop":
        cue = look_cue(name, "hoehepunkt", gruppen, farbe_1, farbe_2, gobos[-1] if gobos else None, band, drop=True)
    elif look_id == "solo":
        werte = []
        if "Spots" in gruppen:
            werte.append({"gruppe": "Spots", "helligkeit": 1.0, "farbe": "weiss", "gobo": "Offen",
                          **({"position": band} if band else {})})
        if "Farb-PARs" in gruppen:
            werte.append({"gruppe": "Farb-PARs", "helligkeit": 0.3, "farbe": farbe_2})
        if "Strobo" in gruppen:
            werte.append({"gruppe": "Strobo", "helligkeit": 0.0, "strobo_hz": 0.0})
        cue = {"name": name, "zeit_s": 1.5, "folgen_s": None, "werte": werte, "effekte": []}
    elif look_id == "ballade":
        werte, effekte = [], []
        for gruppe, hell in (("Spots", 0.7), ("Farb-PARs", 0.6)):
            if gruppe in gruppen:
                wert = {"gruppe": gruppe, "helligkeit": hell, "farbe": "warmweiss"}
                if gruppe == "Spots":
                    wert.update(gobo="Offen", **({"position": band} if band else {}))
                werte.append(wert)
                effekte.append({"art": "dimmer_welle", "ziel": {"gruppe": gruppe}, "tempo": "musik", "beats": 16,
                                "tiefe": 0.2, "verteilung": 0.5})
        if "Strobo" in gruppen:
            werte.append({"gruppe": "Strobo", "helligkeit": 0.0, "strobo_hz": 0.0})
        cue = {"name": name, "zeit_s": 3.0, "folgen_s": None, "werte": werte, "effekte": effekte}
    elif look_id == "schluss":
        werte = [{"gruppe": g, "helligkeit": 0.0} for g in ("Spots", "Farb-PARs", "Strobo") if g in gruppen]
        cue = {"name": name, "zeit_s": 4.0, "folgen_s": None, "werte": werte, "effekte": []}
    else:
        raise ValueError(f"Unbekannte Look-Taste {look_id!r}.")
    cue["name"] = name
    return cue


def drop_folge(patch, farbe_1: str, farbe_2: str, gobos: list, positionen: dict) -> list:
    """Drop: erst ein weißer Schlag, dann geht es von selbst in den Drop-Look."""
    return [akzent_cue(patch.gruppen()), look_bauen("drop", patch, farbe_1, farbe_2, gobos, positionen)]


def halten_anwenden(zustand: dict, halten: dict, patch, strobo_hz: float) -> dict:
    """Legt die gedrückten Halte-Tasten über alles (außer die Not-Tasten danach)."""
    if not any(halten.values()):
        return zustand
    ergebnis = dict(zustand)
    for geraet in patch.geraete:
        gruppen = patch.gruppen_von(geraet) if hasattr(patch, "gruppen_von") else []
        alt = ergebnis.get(geraet["id"], Eigenschaften())
        if halten.get("dunkel"):
            ergebnis[geraet["id"]] = alt.kopie(helligkeit=0.0, strobo_hz=0.0)
            continue
        if halten.get("flash") and ("Spots" in gruppen or "Farb-PARs" in gruppen):
            ergebnis[geraet["id"]] = alt.kopie(helligkeit=1.0, farbe=(1.0, 1.0, 1.0), gobo="Offen", gobo_drehung=0.0)
        if halten.get("strobo") and "Strobo" in gruppen:
            ergebnis[geraet["id"]] = alt.kopie(helligkeit=1.0, strobo_hz=strobo_hz, farbe=(1.0, 1.0, 1.0))
    return ergebnis


def ist_farbe(name: str) -> bool:
    return name in FARBNAMEN


def tap_tempo(tipps: list) -> Optional[float]:
    """Aus den letzten Tipp-Zeitpunkten ein Tempo (Median der Abstände)."""
    if len(tipps) < 3:
        return None
    abstaende = sorted(b - a for a, b in zip(tipps, tipps[1:]))
    mitte = abstaende[len(abstaende) // 2]
    if mitte <= 0:
        return None
    return max(40.0, min(240.0, 60.0 / mitte))
