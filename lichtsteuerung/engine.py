"""Die Musik-Engine: Regeln, die aus Messwerten Licht machen.

    Beat          -> Farbschritt der PARs
    Bass          -> Helligkeit
    hohe Energie  -> Bewegung der Moving Heads
    leise / Rede  -> ruhiges Grundlicht

Wie stark jede Regel wirkt, sagt das Profil. Die Engine spricht nur die Gruppen
"Farb-PARs" und "Spots" an. Ein anderes Modell in der Gruppe ändert hier nichts.
Sie läuft komplett lokal und braucht kein Internet.
"""
from __future__ import annotations

import math
from typing import Optional

from .farben import farbe as lies_farbe
from .audio.analyse import Messwerte
from .pantilt import ZielAusserhalb
from .render import Eigenschaften
from .szenen import bereiche_von, loese_auf, zeige_auf

GRUPPE_FARBE = "Farb-PARs"
GRUPPE_BEWEGUNG = "Spots"
HOHE_ENERGIE = 0.5
STROBO_ENERGIE = 0.92
STROBO_NACH_S = 2.0
UEBERGANG_S = 1.5        # so lange dauert der Wechsel zwischen Musik und Grundlicht
ZIEL_HOEHE_M = 0.8       # die Spots wandern über den Bühnenboden


def mischen(a: Eigenschaften, b: Eigenschaften, anteil: float) -> Eigenschaften:
    """Überblendung von a nach b. anteil=1 ergibt b."""
    def zahl(x, y):
        if x is None or y is None:
            return y if y is not None else x
        return x + (y - x) * anteil

    farbe = None
    if a.farbe is not None and b.farbe is not None:
        farbe = tuple(zahl(x, y) for x, y in zip(a.farbe, b.farbe))
    else:
        farbe = b.farbe or a.farbe
    return b.kopie(helligkeit=zahl(a.helligkeit, b.helligkeit), farbe=farbe,
                   pan=zahl(a.pan, b.pan), tilt=zahl(a.tilt, b.tilt))


class Engine:
    def __init__(self, patch, buehne, positionen: dict, grenzen):
        self.patch = patch
        self.buehne = buehne
        self.positionen = positionen
        self.grenzen = grenzen
        self.farb_schritt = 0
        self.beats = 0
        self.letzter_schritt = -99.0
        self.musik_anteil = 0.0     # 0 = Grundlicht, 1 = volle Musik-Regeln
        self.letzte_zeit: Optional[float] = None
        self.laut_seit: Optional[float] = None
        self.winkel = {}
        self.grund_kopie = {}
        self.zustand_text = "Grundlicht"

    def bewerte(self, messwerte: Optional[Messwerte], profil: dict, jetzt: float,
                pause: bool = False) -> dict:
        """Das Ergebnis pro Bild: {Geräte-id: Eigenschaften}."""
        dauer = 0.0 if self.letzte_zeit is None else jetzt - self.letzte_zeit
        self.letzte_zeit = jetzt

        grund, _ = loese_auf(profil["grundlicht"]["werte"], self.patch, self.buehne, self.positionen)
        grund = {i: e.kopie(helligkeit=min(e.helligkeit, profil["max_helligkeit"])) for i, e in grund.items()}

        ruhig = (messwerte is None or pause or profil["beat_reaktion"] <= 0
                 or messwerte.leise or messwerte.rede)
        self._text_setzen(messwerte, pause, profil)
        schritt = dauer / UEBERGANG_S
        self.musik_anteil = max(0.0, min(1.0, self.musik_anteil + (-schritt if ruhig else schritt)))
        # Fällt die Analyse aus, soll das nicht mitten im Blitz stehen bleiben.
        if self.musik_anteil <= 0.0 or messwerte is None:
            self.musik_anteil = 0.0 if messwerte is None else self.musik_anteil
            return grund

        musik = self._musik(messwerte, profil, jetzt)
        ergebnis = dict(grund)
        for geraet_id, eigenschaften in musik.items():
            ausgang = grund.get(geraet_id, Eigenschaften(farbe=eigenschaften.farbe,
                                                         pan=eigenschaften.pan, tilt=eigenschaften.tilt))
            ergebnis[geraet_id] = mischen(ausgang, eigenschaften, self.musik_anteil)
        return ergebnis

    def _text_setzen(self, messwerte, pause, profil) -> None:
        if pause:
            self.zustand_text = "Automatik pausiert: Grundlicht"
        elif messwerte is None:
            self.zustand_text = "Kein Ton: Grundlicht"
        elif profil["beat_reaktion"] <= 0:
            self.zustand_text = "Profil ohne Automatik: Grundlicht"
        elif messwerte.leise:
            self.zustand_text = "Leise Stelle: Grundlicht"
        elif messwerte.rede:
            self.zustand_text = "Rede erkannt: Grundlicht"
        else:
            self.zustand_text = "Musik"

    def _beat_schritt(self, messwerte: Messwerte, reaktion: float, jetzt: float) -> None:
        """Ein Farbschritt pro Beat, aber nicht schneller, als es die Grenze erlaubt."""
        if not messwerte.beat:
            return
        self.beats += 1
        if reaktion < 0.3:
            return           # Bei wenig Reaktion bleiben die Farben fest.
        alle = 1 if reaktion >= 0.7 else 2
        kleinster_abstand = 1.0 / max(self.grenzen.strobo_max_hz, 0.5)
        if self.beats % alle == 0 and jetzt - self.letzter_schritt >= kleinster_abstand:
            self.farb_schritt += 1
            self.letzter_schritt = jetzt

    def _musik(self, m: Messwerte, profil: dict, jetzt: float) -> dict:
        reaktion = profil["beat_reaktion"]
        palette = [lies_farbe(f) for f in profil["palette"]]
        grenze = profil["max_helligkeit"]
        self._beat_schritt(m, reaktion, jetzt)
        ergebnis = {}

        # Bass -> Helligkeit. Bei wenig Reaktion bleibt nur ein sanftes Atmen.
        tiefe = 0.7 * reaktion
        hell = grenze * ((1.0 - tiefe) + tiefe * m.bass)
        for nummer, geraet in enumerate(self.patch.in_gruppe(GRUPPE_FARBE)):
            ergebnis[geraet["id"]] = Eigenschaften(
                helligkeit=hell, farbe=palette[(self.farb_schritt + nummer) % len(palette)])

        strobo = self._strobo_hz(m, profil, jetzt)
        for nummer, geraet in enumerate(self.patch.in_gruppe(GRUPPE_BEWEGUNG)):
            e = Eigenschaften(helligkeit=grenze * (0.4 + 0.6 * m.energie),
                              farbe=palette[(self.farb_schritt // 2 + nummer) % len(palette)],
                              strobo_hz=strobo if "Effektlicht" in geraet.get("gruppen", []) else 0.0)
            if profil["bewegung"] != "aus" and m.energie >= HOHE_ENERGIE:
                self._bewegen(geraet, nummer, profil["bewegung"], jetzt, e)
            elif geraet["id"] in self.winkel:
                e.pan, e.tilt = self.winkel[geraet["id"]]
            ergebnis[geraet["id"]] = e
        return ergebnis

    def _bewegen(self, geraet: dict, nummer: int, bewegung: str, jetzt: float, e: Eigenschaften) -> None:
        """Die Spots wandern in einer ruhigen Acht über die Bühne, nie ins Publikum."""
        if bereiche_von(self.patch, geraet) is None:
            return
        tempo = 0.04 if bewegung == "langsam" else 0.2
        winkel = 2 * math.pi * (tempo * jetzt + nummer / 3)
        masse = self.buehne.daten["buehne"]
        ziel = (0.4 * masse["breite_m"] * math.sin(winkel),
                masse["tiefe_m"] * (0.5 + 0.3 * math.sin(2 * winkel)), ZIEL_HOEHE_M)
        try:
            e.pan, e.tilt = zeige_auf(geraet, ziel, self.patch, self.buehne, self.winkel.get(geraet["id"]))
            self.winkel[geraet["id"]] = (e.pan, e.tilt)
        except ZielAusserhalb:
            if geraet["id"] in self.winkel:
                e.pan, e.tilt = self.winkel[geraet["id"]]

    def _strobo_hz(self, m: Messwerte, profil: dict, jetzt: float) -> float:
        """Strobo nur, wenn das Profil es erlaubt und die Energie lange sehr hoch ist."""
        if profil["strobo"] == "aus" or m.energie < STROBO_ENERGIE:
            self.laut_seit = None
            return 0.0
        if self.laut_seit is None:
            self.laut_seit = jetzt
        if jetzt - self.laut_seit < STROBO_NACH_S:
            return 0.0
        return min(profil["strobo"]["max_blitze_pro_sekunde"], self.grenzen.strobo_max_hz)
