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


# Farbpaare, die auf der Bühne gut aussehen (A: Strophe und Grundfarbe, B: Spots im Refrain). Vorne die, die auch
# Köpfe mit Farbrad sauber zeigen (Rot, Blau, Grün, Pink und Hellblau hat fast jedes Rad, Gold und Orange nicht).
# Schnelle Songs nehmen eher die kräftigen vorne, langsame eher die kühlen.
FARBPAARE_KRAEFTIG = [("blau", "rot"), ("gruen", "pink"), ("blau", "pink"), ("rot", "cyan"), ("lila", "cyan"),
                      ("rot", "gold"), ("blau", "gold"), ("cyan", "orange")]
FARBPAARE_RUHIG = [("blau", "gold"), ("blau", "pink"), ("lila", "cyan"), ("rot", "cyan"), ("blau", "rot"),
                   ("gold", "lila"), ("gruen", "pink"), ("cyan", "orange")]


def farbpaar(palette: list, tempo_bpm: float = 120.0, vergeben: tuple = (), nummer: int = 0) -> tuple:
    """Die zwei Farben eines Songs. Nur Farben aus dem Profil; andere Songs haben möglichst andere Paare.
    nummer: der wievielte Song (die Automatik nimmt für jeden neuen Song das nächste Paar)."""
    erlaubt = [f for f in palette if f not in ("weiss", "warmweiss")] or list(palette) or ["blau", "gold"]
    paare = [p for p in (FARBPAARE_KRAEFTIG if tempo_bpm >= 110 else FARBPAARE_RUHIG)
             if p[0] in erlaubt and p[1] in erlaubt]
    vergeben = {tuple(v) for v in vergeben}
    frei = [p for p in paare if p not in vergeben and (p[1], p[0]) not in vergeben]
    auswahl = frei or paare
    if auswahl:
        return auswahl[nummer % len(auswahl)]
    return erlaubt[nummer % len(erlaubt)], erlaubt[(nummer + 1) % len(erlaubt)]
