"""Lässt die Analyse in einem eigenen Thread laufen und bewacht sie.

Hängt die Analyse oder fällt die Quelle aus, ist `aktuell()` einfach None.
Die Engine geht dann aufs Grundlicht (Grundregel „Sicherer Rückfall").
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from typing import Optional

from .analyse import Analyse, Messwerte

MAX_AUFNAHME_BLOECKE = 20 * 60 * 44100 // 512   # höchstens 20 Minuten
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
        self.drop_zaehler = 0
        self.drop_abgeholt = 0
        self.schlag_zaehler = 0
        self.schlag_abgeholt = 0
        self.aufnahme = None      # Liste von Blöcken, solange in der Probe aufgenommen wird
        self.beat_erkennung = None
        self.zuhoerer = None      # zum Beispiel der Song-Folger: bekommt jeden Block mit
        self.mithoerer = []       # weitere, zum Beispiel die Song-Erkennung
        self.wieder_verbunden = 0
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
                try:
                    block = quelle.lies()
                except Exception as fehler:
                    quelle = self._neu_verbinden(quelle, stopp, fehler)
                    if quelle is None:
                        return
                    continue
                if self.aufnahme is not None and len(self.aufnahme) < MAX_AUFNAHME_BLOECKE:
                    self.aufnahme.append(block.copy())
                werte = analyse.verarbeite(block)
                jetzt = time.monotonic()
                for zuhoerer in [self.zuhoerer] + list(self.mithoerer):
                    if zuhoerer is None:
                        continue
                    try:
                        zuhoerer(block, jetzt)
                    except Exception:
                        logging.exception("Zuhörer der Audio-Analyse")
                if werte.beat:
                    self.beat_zaehler += 1
                if werte.drop:
                    self.drop_zaehler += 1
                if werte.schlag:
                    self.schlag_zaehler += 1
                self.messwerte, self.zeitpunkt = werte, time.monotonic()
        except Exception as fehler:
            self.fehler = str(fehler)

    def _neu_verbinden(self, quelle, stopp: threading.Event, fehler: Exception):
        """Eingang weg (USB-Kabel, Treiber): alle 2 Sekunden neu öffnen. Bis dahin Grundlicht (Rückfall)."""
        neu_oeffnen = getattr(quelle, "neu_oeffnen", None)
        if neu_oeffnen is None:
            raise fehler
        self.fehler = f"Ton weg ({fehler}). Das Programm öffnet den Eingang von selbst neu."
        self.messwerte = None
        logging.warning("Audio-Eingang weg: %s", fehler)
        while not stopp.wait(2.0):
            try:
                quelle = neu_oeffnen()
            except Exception:
                continue
            self.quelle, self.fehler = quelle, None
            self.wieder_verbunden += 1
            logging.info("Audio-Eingang wieder da")
            return quelle
        return None

    def aufnahme_starten(self) -> None:
        if self.quelle is None:
            raise ValueError("Zuerst auf der Live-Seite eine Tonquelle wählen, zum Beispiel den Eingang vom X32.")
        self.aufnahme = []

    def aufnahme_beenden(self):
        """Gibt den aufgenommenen Ton als eine lange Zahlenreihe zurück."""
        import numpy as np
        bloecke, self.aufnahme = self.aufnahme or [], None
        return np.concatenate(bloecke) if bloecke else np.zeros(0, dtype="float32")

    def position_s(self) -> Optional[float]:
        """Wo eine Audiodatei gerade steht. Für das Nachspielen der Probe."""
        stelle = getattr(self.quelle, "stelle", None)
        return None if stelle is None else stelle / 44100

    def abholen(self, jetzt: Optional[float] = None) -> Optional[Messwerte]:
        """Für die Show: Die Analyse läuft schneller als das Licht.

        Ein Beat steht nur in einem einzigen kurzen Block. Darum merken wir uns,
        welche Beats die Show schon gesehen hat. So geht keiner verloren.
        """
        werte = self.aktuell(jetzt)
        if werte is None:
            return None
        neuer_beat = self.beat_zaehler != self.abgeholt
        neuer_drop = self.drop_zaehler != self.drop_abgeholt
        neuer_schlag = self.schlag_zaehler != self.schlag_abgeholt
        self.abgeholt, self.drop_abgeholt, self.schlag_abgeholt = self.beat_zaehler, self.drop_zaehler, self.schlag_zaehler
        return replace(werte, beat=neuer_beat, drop=neuer_drop, schlag=neuer_schlag)

    def aktuell(self, jetzt: Optional[float] = None) -> Optional[Messwerte]:
        """Die neuesten Messwerte, oder None, wenn nichts Frisches da ist."""
        jetzt = time.monotonic() if jetzt is None else jetzt
        if self.messwerte is None or jetzt - self.zeitpunkt > MAX_ALTER_S:
            return None
        return self.messwerte
