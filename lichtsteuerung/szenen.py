"""Szenen: Werte für Geräte oder Gruppen, gespeichert als Eigenschaften.

So sieht ein Wert aus:
    {"gruppe": "Farb-PARs", "farbe": "rot", "helligkeit": 0.8}
    {"gruppe": "Spots", "position": "Rednerpult", "gobo": "Gobo 2", "helligkeit": 1}
    {"geraet": "par-3", "farbe": "#ff8000"}

Gespeichert werden nie DMX-Zahlen. Darum überstehen Szenen einen Gerätetausch.
"""
from __future__ import annotations

from typing import Optional

from .farben import farbe as lies_farbe, ist_farbe
from .pantilt import Montage, ZielAusserhalb, winkel_fuer_ziel
from .render import Eigenschaften


def pruefe_werte(werte: list, gruppen: Optional[list] = None, geraete: Optional[list] = None,
                 positionen: Optional[dict] = None) -> list:
    """Prüft Szenen-Werte. Gruppen, Geräte und Positionen nur, wenn sie angegeben sind."""
    fehler = []
    for wert in werte:
        if "gruppe" not in wert and "geraet" not in wert:
            fehler.append("Jeder Wert braucht eine Gruppe oder ein Gerät.")
        if gruppen is not None and "gruppe" in wert and wert["gruppe"] not in gruppen:
            fehler.append(f"Gruppe {wert['gruppe']!r} gibt es nicht.")
        if geraete is not None and "geraet" in wert and wert["geraet"] not in geraete:
            fehler.append(f"Gerät {wert['geraet']!r} gibt es nicht.")
        if positionen is not None and "position" in wert and wert["position"] not in positionen:
            fehler.append(f"Position {wert['position']!r} gibt es nicht.")
        if "farbe" in wert and not ist_farbe(str(wert["farbe"])):
            fehler.append(f"Unbekannte Farbe: {wert['farbe']}.")
        for feld, grenze in (("helligkeit", 1.0), ("nebel", 1.0), ("strobo_hz", 1000.0)):
            if feld in wert:
                zahl = wert[feld]
                if not isinstance(zahl, (int, float)) or isinstance(zahl, bool) or not 0 <= zahl <= grenze:
                    fehler.append(f"{feld} muss zwischen 0 und {grenze:g} liegen.")
    return fehler


def zielgeraete(wert: dict, patch) -> list:
    if "geraet" in wert:
        return [g for g in patch.geraete if g["id"] == wert["geraet"]]
    return patch.in_gruppe(wert["gruppe"])


def bereiche_von(patch, geraet: dict) -> tuple:
    """(Pan-Bereich, Tilt-Bereich) in Grad, oder None, wenn sich das Gerät nicht bewegt."""
    typ = patch.typ(geraet)
    grad = {}
    for _, kanal in typ.kanaele_im_modus(geraet["modus"]):
        if kanal["typ"] in ("pan", "tilt"):
            grad[kanal["typ"]] = kanal.get("grad")
    if grad.get("pan") and grad.get("tilt"):
        return grad["pan"], grad["tilt"]
    return None


def zeige_auf(geraet: dict, ziel, patch, buehne, aktuell=None) -> tuple:
    """Pan und Tilt fürs Ziel. Kann ein Gerät das nicht, kommt ZielAusserhalb."""
    bereiche = bereiche_von(patch, geraet)
    ort = buehne.geraet(geraet["id"])
    if bereiche is None or ort is None:
        raise ZielAusserhalb(f"{geraet['name']} kann nicht auf eine Position zielen.")
    return winkel_fuer_ziel(Montage.aus_buehne(ort), ziel, bereiche[0], bereiche[1], aktuell)


def loese_auf(werte: list, patch, buehne, positionen: dict, basis: Optional[dict] = None) -> tuple:
    """Macht aus Szenen-Werten {Geräte-id: Eigenschaften}. Gibt auch Meldungen zurück."""
    zustand = dict(basis or {})
    meldungen = []
    for wert in werte:
        for geraet in zielgeraete(wert, patch):
            e = zustand.get(geraet["id"], Eigenschaften())
            aenderung = {}
            if "helligkeit" in wert:
                aenderung["helligkeit"] = float(wert["helligkeit"])
            if "farbe" in wert:
                aenderung["farbe"] = lies_farbe(wert["farbe"])
            for feld in ("gobo", "strobo_hz", "nebel"):
                if feld in wert:
                    aenderung[feld] = wert[feld]
            if "position" in wert:
                punkt = positionen.get(wert["position"])
                if punkt is None:
                    meldungen.append(f"Position {wert['position']!r} gibt es nicht.")
                elif bereiche_von(patch, geraet) is not None:
                    try:
                        ziel = (punkt["x"], punkt["y"], punkt["z"])
                        aenderung["pan"], aenderung["tilt"] = zeige_auf(geraet, ziel, patch, buehne)
                    except ZielAusserhalb as grund:
                        meldungen.append(f"{geraet['name']}: {grund}")
            zustand[geraet["id"]] = e.kopie(**aenderung)
    return zustand, meldungen
