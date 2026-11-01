"""Feste Sicherheitsgrenzen und die Wächter, die sie im Betrieb durchsetzen.

Die Grenzen stehen in sicherheit.json. Das Programm liest die Datei nur.
Kein Profil, keine Cue und keine KI kann sie überschreiten.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import daten


@dataclass(frozen=True)
class Grenzen:
    strobo_max_hz: float
    strobo_max_dauer_s: float
    strobo_pause_s: float

    @classmethod
    def laden(cls, pfad: Path) -> "Grenzen":
        inhalt = daten.lese_json(pfad)
        if inhalt is None:
            raise FileNotFoundError(f"{pfad} fehlt. Ohne Sicherheitsgrenzen startet die Show nicht.")
        return cls(float(inhalt["strobo_max_blitze_pro_sekunde"]),
                   float(inhalt["strobo_max_dauer_s"]), float(inhalt["strobo_pause_s"]))


class StroboWaechter:
    """Stoppt Strobo nach der maximalen Dauer und erzwingt danach eine Pause."""

    def __init__(self):
        self.start: Optional[float] = None
        self.gesperrt_bis = 0.0

    def erlaubt(self, jetzt: float) -> bool:
        return jetzt >= self.gesperrt_bis

    def melde(self, blitzt: bool, jetzt: float, max_dauer: float, pause: float) -> None:
        """Wird pro Bild einmal aufgerufen."""
        if not blitzt:
            self.start = None
            return
        if self.start is None:
            self.start = jetzt
        if jetzt - self.start >= max_dauer:
            self.start = None
            self.gesperrt_bis = jetzt + pause


class BlitzWaechter:
    """Auch schnelles Hell-Dunkel ohne Strobo-Kanal ist Blitzen.

    Springt ein Gerät mehr als `max_pro_sekunde` Mal im Takt nach oben, etwa
    durch sehr schnelle Musik, bleibt es für den Rest der Sekunde auf der
    niedrigen Helligkeit. So gilt die Strobo-Grenze für jede Quelle.
    """

    SPRUNG = 0.4          # ab diesem Helligkeits-Sprung zählt es als Blitz
    FENSTER_S = 1.0

    def __init__(self):
        self.tief = {}
        self.blitze = {}

    def begrenze(self, geraet: str, helligkeit: float, jetzt: float, max_pro_sekunde: float) -> float:
        tief = self.tief.get(geraet, 0.0)
        blitze = self.blitze.setdefault(geraet, deque())
        while blitze and jetzt - blitze[0] > self.FENSTER_S:
            blitze.popleft()
        if helligkeit - tief >= self.SPRUNG:
            if len(blitze) >= max_pro_sekunde:
                return tief
            blitze.append(jetzt)
            self.tief[geraet] = helligkeit
        elif helligkeit < tief:
            self.tief[geraet] = helligkeit
        return helligkeit
