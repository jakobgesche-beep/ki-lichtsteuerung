"""Die Show: hält alle Daten und baut daraus 40-mal pro Sekunde ein DMX-Bild.

Hier läuft alles zusammen. Ein Bild entsteht immer in dieser Reihenfolge:

    DMX-Test (falls aktiv)
    Prüfung        -> jeder Wert gegen die Gerätedatei
    Ausgabe        -> Simulator, und wenn eingeschaltet das Enttec
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from . import daten
from .buehne import Buehne
from .dmx_ausgabe import BILDER_PRO_SEKUNDE, DmxAusgabe
from .katalog import Katalog
from .patch import Patch
from .pruefung import Pruefer, Vorgaben
from .render import Eigenschaften, Renderer
from .sicherheit import Grenzen


class Show:
    def __init__(self, pfade: Optional[daten.Pfade] = None, ausgabe: Optional[DmxAusgabe] = None):
        self.pfade = pfade or daten.Pfade()
        self.katalog = Katalog(self.pfade.katalog)
        self.patch = Patch(self.pfade.fixtures, self.katalog)
        self.buehne = Buehne(self.pfade.stage)
        self.positionen = daten.lese_json(self.pfade.positions, {"positionen": {}})["positionen"]
        self.grenzen = Grenzen.laden(self.pfade.sicherheit)
        self.ausgabe = ausgabe or DmxAusgabe()

        self.sperre = threading.RLock()     # Oberfläche und Show-Schleife wechseln sich ab
        self.test_geraet: Optional[str] = None
        self.test_kanaele = {}              # DMX-Kanal (ab 1) -> Wert
        self.meldungen = []
        self.letztes_bild = bytes(512)
        self._stopp = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.aufbauen()

    def aufbauen(self) -> None:
        """Muss nach jeder Änderung am Patch oder an der Bühne laufen."""
        with self.sperre:
            self.renderer = Renderer(self.patch)
            self.pruefer = Pruefer(self.patch, self.buehne, self.grenzen)

    # --- Ein Bild bauen ---------------------------------------------------

    def baue_bild(self, jetzt: Optional[float] = None) -> bytes:
        jetzt = time.monotonic() if jetzt is None else jetzt
        with self.sperre:
            zustand = {}
            if self.test_geraet is not None:
                zustand[self.test_geraet] = Eigenschaften(helligkeit=1.0, farbe=(1.0, 1.0, 1.0))
            bild = self.renderer.bild(zustand)
            for kanal, wert in self.test_kanaele.items():
                bild[kanal - 1] = wert
            bild, meldungen, _blitzt = self.pruefer.pruefe(bild, Vorgaben(), jetzt)
            self.meldungen = meldungen
            self.letztes_bild = bytes(bild)
            return self.letztes_bild

    # --- Die Schleife -----------------------------------------------------

    def start(self) -> None:
        self._stopp.clear()
        self._thread = threading.Thread(target=self._schleife, name="Show", daemon=True)
        self._thread.start()

    def stopp(self) -> None:
        self._stopp.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.ausgabe.ausschalten()

    def _schleife(self) -> None:
        abstand = 1.0 / BILDER_PRO_SEKUNDE
        while not self._stopp.is_set():
            beginn = time.monotonic()
            self.ausgabe.setze_bild(self.baue_bild(beginn))
            rest = abstand - (time.monotonic() - beginn)
            if rest > 0:
                time.sleep(rest)
