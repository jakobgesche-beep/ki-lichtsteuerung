"""Farben: Namen, die in Profilen und Cues benutzt werden dürfen, und Umrechnung."""
from __future__ import annotations

from typing import Tuple

Farbe = Tuple[float, float, float]   # Rot, Grün, Blau, je 0 bis 1

FARBNAMEN = {
    "rot": "#ff0000", "gruen": "#00ff00", "blau": "#0000ff", "weiss": "#ffffff",
    "warmweiss": "#ffd9a0", "gold": "#ffb030", "orange": "#ff8000", "gelb": "#ffff00",
    "pink": "#ff00a0", "lila": "#8000ff", "cyan": "#00ffff", "hellblau": "#80c0ff",
}


def farbe(wert: str) -> Farbe:
    """Macht aus "rot" oder "#ff0000" eine Farbe. Unbekanntes ergibt einen Fehler."""
    text = FARBNAMEN.get(wert.lower().replace("ß", "ss").replace("ü", "ue"), wert)
    if len(text) != 7 or not text.startswith("#"):
        raise ValueError(f"Unbekannte Farbe: {wert!r}")
    return tuple(int(text[i:i + 2], 16) / 255 for i in (1, 3, 5))


def ist_farbe(wert: str) -> bool:
    try:
        farbe(wert)
        return True
    except ValueError:
        return False
