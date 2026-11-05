"""Ablage für Show-Daten, die aus vielen einzelnen JSON-Dateien bestehen (zum Beispiel Sequenzen)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import daten


class Sammlung:
    """Ein Ordner voller JSON-Dateien mit je einem Namen."""

    def __init__(self, ordner: Path):
        self.ordner = Path(ordner)

    def namen(self) -> list:
        return sorted(daten.lese_json(p)["name"] for p in self.ordner.glob("*.json"))

    def lesen(self, name: str) -> Optional[dict]:
        return daten.lese_json(self.ordner / f"{daten.dateiname(name)}.json")

    def schreiben(self, inhalt: dict) -> None:
        daten.schreibe_json(self.ordner / f"{daten.dateiname(inhalt['name'])}.json", inhalt)

    def loeschen(self, name: str) -> None:
        (self.ordner / f"{daten.dateiname(name)}.json").unlink(missing_ok=True)
