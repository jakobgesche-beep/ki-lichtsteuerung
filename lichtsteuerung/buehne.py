"""Die Bühne aus stage.json: Maße, Publikum und wo jedes Gerät hängt.

Koordinaten in Metern. Nullpunkt: Bühnenmitte vorne auf dem Boden.
    x  nach rechts (vom Publikum aus gesehen)
    y  nach hinten in die Bühne, das Publikum hat also negatives y
    z  nach oben
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import daten


class Buehne:
    def __init__(self, pfad: Path):
        self.pfad = Path(pfad)
        self.daten = daten.lese_json(self.pfad, {})

    @property
    def publikum(self) -> dict:
        return self.daten["publikum"]

    @property
    def traverse(self) -> dict:
        return self.daten["traverse"]

    def geraet(self, geraet_id: str) -> Optional[dict]:
        return self.daten.get("geraete", {}).get(geraet_id)

    def setze_geraet(self, geraet_id: str, ort: dict) -> None:
        eintrag = self.daten.setdefault("geraete", {}).setdefault(geraet_id, {})
        eintrag.update(ort)

    def entferne_geraet(self, geraet_id: str) -> None:
        self.daten.get("geraete", {}).pop(geraet_id, None)

    def speichern(self) -> None:
        daten.schreibe_json(self.pfad, self.daten)

    def ort_vorschlag(self, ort: str, nummer: int, anzahl: int) -> dict:
        """Startposition für neue Geräte. Die genaue Stelle misst man später ein."""
        if ort == "traverse":
            grenze = self.traverse
            breite = grenze["x_bis_m"] - grenze["x_von_m"]
            x = grenze["x_von_m"] + breite * (nummer + 0.5) / anzahl
            return {"ort": ort, "x": round(x, 2), "y": grenze["y_m"], "z": grenze["hoehe_m"],
                    "montage": "haengend", "drehung_grad": 180}
        if ort == "stativ":
            x = -3.5 + 7.0 * nummer / max(anzahl - 1, 1)
            return {"ort": ort, "x": round(x, 2), "y": -1.0, "z": 2.5,
                    "montage": "stehend", "drehung_grad": 0}
        x = -2.0 + 4.0 * nummer / max(anzahl - 1, 1)
        return {"ort": "boden", "x": round(x, 2), "y": 3.0,
                "z": self.daten["buehne"]["hoehe_kante_m"],
                "montage": "stehend", "drehung_grad": 0}
