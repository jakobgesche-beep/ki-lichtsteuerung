"""Übersetzt Eigenschaften ("Rot, 80 %, Gobo 2") in DMX-Werte für das gepatchte Gerät.

Das ist die einzige Stelle, an der aus Eigenschaften Zahlen werden. Alles
davor (Cues, Profile, Engine) kennt keine Kanäle. Deshalb reicht beim
Gerätetausch ein neuer Eintrag im Patch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional

from .farben import Farbe, farbe as lies_farbe
from .katalog import FARB_TYPEN
from .pantilt import winkel_zu_anteil

KANAELE = 512


@dataclass
class Eigenschaften:
    """Was ein Licht gerade tun soll. None heißt: nicht festgelegt."""

    helligkeit: float = 0.0
    farbe: Optional[Farbe] = None
    pan: Optional[float] = None         # Grad, 0 = Mitte
    tilt: Optional[float] = None
    tempo: Optional[float] = None       # Bewegungstempo: 0 langsam, 1 schnell
    gobo: Optional[str] = None
    strobo_hz: float = 0.0
    nebel: float = 0.0

    def kopie(self, **aenderungen) -> "Eigenschaften":
        return replace(self, **aenderungen)


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


def _kanal_wert(bereich: dict, hz: float) -> int:
    """DMX-Wert innerhalb eines Strobo-Bereichs für die gewünschten Hertz."""
    von, bis = bereich["hz_von"], bereich["hz_bis"]
    anteil = 0.0 if bis == von else (hz - von) / (bis - von)
    anteil = max(0.0, min(1.0, anteil))
    wert = bereich["von"] + anteil * (bereich["bis"] - bereich["von"])
    # Immer zur langsameren Seite runden, damit keine Grenze überschritten wird.
    return math.floor(wert) if bis >= von else math.ceil(wert)


def strobo_bereich(kanal: dict, hz: float) -> Optional[dict]:
    """Sucht einen Bereich, der dieses Tempo nachweislich kann."""
    for bereich in kanal.get("bereiche", []):
        if bereich["typ"] == "strobo" and bereich.get("hz_von") is not None:
            if min(bereich["hz_von"], bereich["hz_bis"]) <= hz <= max(bereich["hz_von"], bereich["hz_bis"]):
                return bereich
    return None


def offen_wert(kanal: dict) -> int:
    """Wert, bei dem ein Shutter-Kanal ruhig offen steht."""
    for bereich in kanal.get("bereiche", []):
        if bereich["typ"] == "offen":
            return bereich["von"]
    return kanal.get("standard", 0)


def zu_wert(kanal: dict) -> Optional[int]:
    for bereich in kanal.get("bereiche", []):
        if bereich["typ"] == "zu":
            return bereich["von"]
    return None


def naechster_platz(kanal: dict, ziel: Farbe) -> int:
    """Sucht auf einem Farbrad den Platz, der der Wunschfarbe am nächsten kommt."""
    beste, abstand = kanal.get("standard", 0), 99.0
    for bereich in kanal.get("bereiche", []):
        if bereich["typ"] != "platz" or "farbe" not in bereich:
            continue
        platz = lies_farbe(bereich["farbe"])
        d = sum((a - b) ** 2 for a, b in zip(platz, ziel))
        if d < abstand:
            beste, abstand = bereich["von"], d
    return beste


def gobo_wert(kanal: dict, name: Optional[str]) -> int:
    for bereich in kanal.get("bereiche", []):
        if bereich["typ"] == "platz" and bereich.get("name") == (name or "Offen"):
            return bereich["von"]
    return kanal.get("standard", 0)


def farb_anteile(ziel: Farbe, typen: set) -> dict:
    """Verteilt eine Farbe auf die LED-Farben des Geräts (RGB oder RGBW)."""
    rot, gruen, blau = ziel
    anteile = {}
    if "weiss" in typen:
        weiss = min(rot, gruen, blau)
        anteile["weiss"] = weiss
        rot, gruen, blau = rot - weiss, gruen - weiss, blau - weiss
    anteile.update(rot=rot, gruen=gruen, blau=blau)
    return anteile


def geraet_kanaele(patch, geraet: dict) -> list:
    """(DMX-Index ab 0, Kanal) für alle Kanäle eines Geräts."""
    typ = patch.typ(geraet)
    start = geraet["adresse"] - 1
    return [(start + versatz, kanal) for versatz, kanal in typ.kanaele_im_modus(geraet["modus"])
            if start + versatz < KANAELE]


class Renderer:
    def __init__(self, patch):
        self.patch = patch
        self.standard = bytearray(KANAELE)
        self.geraete = []
        for geraet in patch.geraete:
            kanaele = geraet_kanaele(patch, geraet)
            for index, kanal in kanaele:
                self.standard[index] = kanal.get("standard", 0)
            typen = {k["typ"] for _, k in kanaele}
            self.geraete.append((geraet, kanaele, typen))

    def bild(self, zustand: dict) -> bytearray:
        """Baut aus {Geräte-id: Eigenschaften} ein DMX-Bild mit 512 Werten."""
        bild = bytearray(self.standard)
        for geraet, kanaele, typen in self.geraete:
            eigenschaften = zustand.get(geraet["id"])
            if eigenschaften is not None:
                self._schreibe(bild, kanaele, typen, eigenschaften)
        return bild

    def _schreibe(self, bild, kanaele, typen, e: Eigenschaften) -> None:
        hell = max(0.0, min(1.0, e.helligkeit))
        ziel = e.farbe if e.farbe is not None else (1.0, 1.0, 1.0)
        anteile = farb_anteile(ziel, typen)
        hat_dimmer = "dimmer" in typen
        # Ohne Dimmer steckt die Helligkeit in den Farben selbst.
        farb_faktor = 1.0 if hat_dimmer else hell
        for index, kanal in kanaele:
            typ = kanal["typ"]
            if typ == "dimmer":
                bild[index] = round(hell * 255)
            elif typ in FARB_TYPEN:
                bild[index] = round(anteile.get(typ, 0.0) * farb_faktor * 255)
            elif typ == "farbrad":
                bild[index] = naechster_platz(kanal, ziel)
            elif typ == "gobo":
                bild[index] = gobo_wert(kanal, e.gobo)
            elif typ == "strobo":
                bild[index] = self._shutter(kanal, hell, e.strobo_hz, hat_dimmer)
            elif typ == "pan" and e.pan is not None:
                self._winkel(bild, index, kanal, kanaele, "pan_fein", e.pan)
            elif typ == "tilt" and e.tilt is not None:
                self._winkel(bild, index, kanal, kanaele, "tilt_fein", e.tilt)
            elif typ == "tempo" and e.tempo is not None and "schnell_bei" in kanal:
                anteil = e.tempo if kanal["schnell_bei"] == 255 else 1.0 - e.tempo
                bild[index] = round(max(0.0, min(1.0, anteil)) * 255)
            elif typ == "nebel":
                bild[index] = round(max(0.0, min(1.0, e.nebel)) * 255)

    @staticmethod
    def _shutter(kanal: dict, hell: float, hz: float, hat_dimmer: bool) -> int:
        if hell <= 0.0:
            geschlossen = zu_wert(kanal)
            if geschlossen is not None:
                return geschlossen
        if hz > 0.0:
            bereich = strobo_bereich(kanal, hz)
            if bereich is not None:
                return _kanal_wert(bereich, hz)
        return offen_wert(kanal)

    @staticmethod
    def _winkel(bild, index, kanal, kanaele, fein_typ, winkel) -> None:
        grad = kanal.get("grad")
        if not grad:
            return
        anteil = winkel_zu_anteil(winkel, grad)
        fein = next((i for i, k in kanaele if k["typ"] == fein_typ), None)
        if fein is None:
            bild[index] = round(anteil * 255)
        else:
            wert = round(anteil * 65535)
            bild[index], bild[fein] = wert >> 8, wert & 255
