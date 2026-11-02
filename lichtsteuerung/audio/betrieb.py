"""Lässt die Analyse in einem eigenen Thread laufen und bewacht sie.

Hängt die Analyse oder fällt die Quelle aus, ist `aktuell()` einfach None.
Die Engine geht dann aufs Grundlicht (Grundregel „Sicherer Rückfall").
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Optional

from .analyse import Analyse, Messwerte

MAX_ALTER_S = 0.5     # Ältere Messwerte gelten als ausgefallen


class AudioBetrieb:
    def __init__(self):
        self.quelle = None
        self.name = "aus"
        self.fehler: Optional[str] = None
        self.messwerte: Optional[Messwerte] = None
        self.zeitpunkt = 0.0
        self.beat_zaehler = 0
        self.abgeholt = 0
        self.beat_erkennung = None
        self._thread: Optional[threading.Thread] = None
        self._stopp = threading.Event()

    def starten(self, quelle, name: str) -> None:
        self.stoppen()
        self.quelle, self.name, self.fehler = quelle, name, None
        self._stopp = threading.Event()
        self._thread = threading.Thread(target=self._schleife, args=(quelle, self._stopp),
                                        name="Audio", daemon=True)
        self._thread.start()

    def stoppen(self) -> None:
        self._stopp.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self.quelle is not None:
            self.quelle.schliessen()
            self.quelle = None
        self.name = "aus"
        self.messwerte = None

    def _schleife(self, quelle, stopp: threading.Event) -> None:
        try:
            analyse = Analyse()
            self.beat_erkennung = analyse.beat.name
            while not stopp.is_set():
                werte = analyse.verarbeite(quelle.lies())
                if werte.beat:
                    self.beat_zaehler += 1
                self.messwerte, self.zeitpunkt = werte, time.monotonic()
        except Exception as fehler:
            self.fehler = str(fehler)

    def abholen(self, jetzt: Optional[float] = None) -> Optional[Messwerte]:
        """Für die Show: Die Analyse läuft schneller als das Licht.

        Ein Beat steht nur in einem einzigen kurzen Block. Darum merken wir uns,
        welche Beats die Show schon gesehen hat. So geht keiner verloren.
        """
        werte = self.aktuell(jetzt)
        if werte is None:
            return None
        neuer_beat = self.beat_zaehler != self.abgeholt
        self.abgeholt = self.beat_zaehler
        return replace(werte, beat=neuer_beat)

    def aktuell(self, jetzt: Optional[float] = None) -> Optional[Messwerte]:
        """Die neuesten Messwerte, oder None, wenn nichts Frisches da ist."""
        jetzt = time.monotonic() if jetzt is None else jetzt
        if self.messwerte is None or jetzt - self.zeitpunkt > MAX_ALTER_S:
            return None
        return self.messwerte
