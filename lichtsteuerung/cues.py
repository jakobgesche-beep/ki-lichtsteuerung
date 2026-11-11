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
        """Alle Namen. Eine kaputte Datei wird übersprungen (steht im Logbuch), statt alles anzuhalten."""
        namen = []
        for pfad in self.ordner.glob("*.json"):
            inhalt = daten.lese_json_sicher(pfad)
            if isinstance(inhalt, dict) and isinstance(inhalt.get("name"), str):
                namen.append(inhalt["name"])
        return sorted(namen)

    def lesen(self, name: str) -> Optional[dict]:
        inhalt = daten.lese_json_sicher(self.ordner / f"{daten.dateiname(name)}.json")
        return inhalt if isinstance(inhalt, dict) and isinstance(inhalt.get("cues", []), list) else None

    def schreiben(self, inhalt: dict) -> None:
        daten.schreibe_json(self.ordner / f"{daten.dateiname(inhalt['name'])}.json", inhalt)

    def loeschen(self, name: str) -> None:
        (self.ordner / f"{daten.dateiname(name)}.json").unlink(missing_ok=True)
