"""Die Override-Tasten. Grundregel: Der Mensch hat immer Vorrang.

Sie wirken als Letztes auf die Eigenschaften, kurz vor der Umrechnung in DMX.
Blackout schlägt alles, danach kommt Warmweiß.
"""
from __future__ import annotations

from dataclasses import dataclass

from .farben import farbe
from .render import Eigenschaften

WARMWEISS_HELLIGKEIT = 0.7
TASTEN = ("blackout", "warmweiss", "pause", "strobo_aus")


@dataclass
class Overrides:
    blackout: bool = False
    warmweiss: bool = False
    pause: bool = False
    strobo_aus: bool = False

    def umschalten(self, taste: str) -> None:
        if taste not in TASTEN:
            raise ValueError(f"Unbekannte Taste: {taste}")
        setattr(self, taste, not getattr(self, taste))

    def anwenden(self, zustand: dict, alle_geraete: list) -> dict:
        ergebnis = {}
        warm = farbe("warmweiss")
        for geraet in alle_geraete:
            e = zustand.get(geraet["id"], Eigenschaften())
            if self.strobo_aus:
                e = e.kopie(strobo_hz=0.0)
            if self.warmweiss:
                e = e.kopie(helligkeit=WARMWEISS_HELLIGKEIT, farbe=warm, strobo_hz=0.0, gobo=None)
            if self.blackout:
                e = e.kopie(helligkeit=0.0, strobo_hz=0.0, nebel=0.0)
            ergebnis[geraet["id"]] = e
        return ergebnis
