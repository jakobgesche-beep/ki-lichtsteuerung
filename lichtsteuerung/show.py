"""Die Show: hält alle Daten und baut daraus jedes einzelne DMX-Bild."""
from __future__ import annotations

from . import daten
from .buehne import Buehne
from .katalog import Katalog
from .patch import Patch


class Show:
    def __init__(self, pfade: daten.Pfade = None):
        self.pfade = pfade or daten.Pfade()
        self.katalog = Katalog(self.pfade.katalog)
        self.patch = Patch(self.pfade.fixtures, self.katalog)
        self.buehne = Buehne(self.pfade.stage)
        self.positionen = daten.lese_json(self.pfade.positions, {"positionen": {}})["positionen"]
