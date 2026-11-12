"""Applaus- und Pausenlicht: Was das Licht zwischen den Songs macht, ohne dass jemand drücken muss.

    Song zu Ende   (der Song-Folger ist am Ende, die Band hört nach dem letzten Teil auf,
                   oder das Publikum klatscht im Schluss des Songs 3 s lang)
                   -> Applaus-Licht: die Bühne hell und warm, die Band gut zu sehen.
                   Es bleibt mindestens 6 s, solange geklatscht wird länger (höchstens 25 s).
    Danach         -> Pausenlicht: ruhig und warm, bis der nächste Song startet
                   (von Hand, durch die Song-Erkennung) oder wieder Musik kommt.
    Eingreifen     Jede Look-Taste und jeder Song-Start beendet das Zwischenlicht sofort.

Läuft auf einem eigenen Platz (wie die Show-Tasten), über dem Song, aber unter allem, was man drückt.
Die Not-Tasten haben wie immer Vorrang.
"""
from __future__ import annotations

from typing import Optional

from .pult import Executor

APPLAUS_MIN_S = 6.0
APPLAUS_MAX_S = 25.0
MUSIK_WIEDER_S = 3.0           # so lange Musik, dann geht das Pausenlicht weg (ohne Song)
ZWISCHEN_NUMMER = -2


def applaus_cue(gruppen: list) -> dict:
    werte = []
    for gruppe, hell in (("Farb-PARs", 1.0), ("Spots", 0.9), ("Frontlicht", 1.0), ("Publikum", 0.8), ("Saal", 0.8)):
        if gruppe in gruppen:
            wert = {"gruppe": gruppe, "helligkeit": hell, "farbe": "warmweiss"}
            if gruppe in ("Spots", "Frontlicht"):
                wert["gobo"] = "Offen"
            werte.append(wert)
    if "Strobo" in gruppen:
        werte.append({"gruppe": "Strobo", "helligkeit": 0.0, "strobo_hz": 0.0})
    return {"name": "Applaus", "zeit_s": 1.0, "folgen_s": None, "werte": werte, "effekte": []}


def pause_cue(gruppen: list, farbe: str) -> dict:
    werte = []
    if "Farb-PARs" in gruppen:
        werte.append({"gruppe": "Farb-PARs", "helligkeit": 0.35, "farbe": farbe})
    for gruppe in ("Spots", "Frontlicht"):
        if gruppe in gruppen:
            werte.append({"gruppe": gruppe, "helligkeit": 0.3, "farbe": "warmweiss", "gobo": "Offen"})
    for gruppe in ("Publikum", "Saal"):
        if gruppe in gruppen:
            werte.append({"gruppe": gruppe, "helligkeit": 0.4, "farbe": "warmweiss"})
    if "Strobo" in gruppen:
        werte.append({"gruppe": "Strobo", "helligkeit": 0.0, "strobo_hz": 0.0})
    effekte = [{"art": "dimmer_welle", "ziel": {"gruppe": "Farb-PARs"}, "tempo": 60, "beats": 8, "tiefe": 0.25,
                "verteilung": 0.5}] if "Farb-PARs" in gruppen else []
    return {"name": "Pause", "zeit_s": 3.0, "folgen_s": None, "werte": werte, "effekte": effekte}


class Zwischenlicht:
    def __init__(self, show):
        self.show = show
        self.platz = Executor(ZWISCHEN_NUMMER)
        self.zustand = "aus"            # aus, applaus, pause
        self.seit = 0.0
        self.musik_seit: Optional[float] = None
        self.song_lief = False          # lief seit dem letzten Zwischenlicht ein Song?

    def _zeigen(self, art: str, jetzt: float) -> None:
        gruppen = self.show.patch.gruppen()
        farbe = self.show.pult.farbe_2 or "blau"
        cue = applaus_cue(gruppen) if art == "applaus" else pause_cue(gruppen, farbe)
        if not cue["werte"]:
            return
        self.platz.sequenz = {"name": "Zwischenlicht", "cues": [cue]}
        self.platz.art = "sequenz"
        self.platz.gehe_zu(0, jetzt)
        self.show.pult.nach_oben(self.platz, jetzt, umschalten=False)
        self.zustand, self.seit = art, jetzt

    @property
    def an(self) -> bool:
        return self.show.song.zwischenlicht_an

    def beenden(self, jetzt: float) -> None:
        if self.zustand != "aus":
            self.platz.aus(jetzt)
            self.zustand = "aus"

    def takt(self, jetzt: float, messwerte) -> None:
        """Jedes Bild (unter der Sperre der Show)."""
        song = self.show.song
        song.klatschen(messwerte is not None and messwerte.applaus, jetzt)
        if not self.an:
            self.beenden(jetzt)
            return
        laeuft = song.folger is not None and not song._am_ende()
        if laeuft:
            self.song_lief = True
            self.beenden(jetzt)                      # ein Song läuft: kein Zwischenlicht
            return
        if self.show.pult.tasten.index >= 0 and self.zustand != "aus":
            self.beenden(jetzt)                      # jemand hat eine Look-Taste gedrückt
            return
        musik = messwerte is not None and not messwerte.leise and not messwerte.applaus and messwerte.energie > 0.15
        if self.zustand == "aus":
            if self.show.pult.tasten.index >= 0:
                return                               # eine Look-Taste ist an: Der Mensch fährt das Licht
            if self.song_lief and song.folger is not None and song._am_ende():
                self.song_lief = False
                self._zeigen("applaus", jetzt)
            return
        if self.zustand == "applaus":
            klatscht = messwerte is not None and messwerte.applaus
            if jetzt - self.seit >= APPLAUS_MAX_S or (jetzt - self.seit >= APPLAUS_MIN_S and not klatscht):
                self._zeigen("pause", jetzt)
            return
        # Pausenlicht: endet, wenn wieder Musik kommt (ohne Song: nach 3 s Musik)
        if musik:
            self.musik_seit = self.musik_seit or jetzt
            if jetzt - self.musik_seit >= MUSIK_WIEDER_S:
                self.beenden(jetzt)
        else:
            self.musik_seit = None

    def status(self) -> dict:
        return {"an": self.an, "zustand": self.zustand}
