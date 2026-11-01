"""Die Rechnung für Moving Heads: von Winkeln zur Richtung und zurück.

So denken wir uns den Kopf (die Mitte des DMX-Bereichs ist Pan 0°, Tilt 0°):
  * Bei Tilt 0° zeigt er geradeaus von der Montage weg: stehend nach oben,
    hängend nach unten.
  * Tilt kippt ihn zur "Vorderseite" des Geräts.
  * Pan dreht das Ganze um die Achse der Montage.

Die Vorderseite ergibt sich aus `drehung_grad`: 0° zeigt in die Bühne (+y),
180° zum Publikum (-y). Positive Werte drehen von oben gesehen gegen den Uhrzeiger.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

Vektor = Tuple[float, float, float]


class ZielAusserhalb(Exception):
    """Der Kopf kommt nicht an dieses Ziel. Dann lieber Meldung als falsche Bewegung."""


@dataclass
class Montage:
    x: float
    y: float
    z: float
    haengend: bool = False
    drehung_grad: float = 0.0
    pan_versatz_grad: float = 0.0     # kommt später aus der Kalibrierung
    tilt_versatz_grad: float = 0.0
    pan_umkehren: bool = False        # falls Pan/Tilt am Gerät umgedreht wurden
    tilt_umkehren: bool = False

    @classmethod
    def aus_buehne(cls, ort: dict) -> "Montage":
        return cls(
            x=ort["x"], y=ort["y"], z=ort["z"], haengend=ort.get("montage") == "haengend",
            drehung_grad=ort.get("drehung_grad", 0.0),
            pan_versatz_grad=ort.get("pan_versatz_grad", 0.0),
            tilt_versatz_grad=ort.get("tilt_versatz_grad", 0.0),
            pan_umkehren=ort.get("pan_umkehren", False),
            tilt_umkehren=ort.get("tilt_umkehren", False))

    def achsen(self) -> Tuple[Vektor, Vektor, Vektor]:
        """Die drei Achsen des Geräts (seitlich, vorne, Montageachse) in Bühnen-Koordinaten."""
        winkel = math.radians(self.drehung_grad)
        cos, sin = math.cos(winkel), math.sin(winkel)
        vorne = (-sin, cos, 0.0)
        if self.haengend:
            return (-cos, -sin, 0.0), vorne, (0.0, 0.0, -1.0)
        return (cos, sin, 0.0), vorne, (0.0, 0.0, 1.0)


def richtung(montage: Montage, pan_grad: float, tilt_grad: float) -> Vektor:
    """In welche Richtung zeigt der Kopf bei diesen Winkeln? Ergebnis hat Länge 1."""
    pan = math.radians((-pan_grad if montage.pan_umkehren else pan_grad) + montage.pan_versatz_grad)
    tilt = math.radians((-tilt_grad if montage.tilt_umkehren else tilt_grad) + montage.tilt_versatz_grad)
    seite, vorne, achse = montage.achsen()
    anteile = (math.sin(tilt) * math.sin(pan), math.sin(tilt) * math.cos(pan), math.cos(tilt))
    return tuple(anteile[0] * seite[i] + anteile[1] * vorne[i] + anteile[2] * achse[i]
                 for i in range(3))


def _in_geraet_winkel(montage: Montage, pan: float, tilt: float) -> Tuple[float, float]:
    """Macht Versatz und Umkehren rückgängig, ergibt die Winkel fürs Gerät."""
    pan -= montage.pan_versatz_grad
    tilt -= montage.tilt_versatz_grad
    return (-pan if montage.pan_umkehren else pan, -tilt if montage.tilt_umkehren else tilt)


def winkel_fuer_ziel(montage: Montage, ziel: Vektor, pan_bereich: float, tilt_bereich: float,
                     aktuell: Optional[Tuple[float, float]] = None) -> Tuple[float, float]:
    """Berechnet Pan und Tilt, damit der Kopf auf `ziel` zeigt.

    Meist gibt es mehrere Lösungen, weil ein Kopf mehr als 360° schafft. Wir
    nehmen die mit dem kürzesten Weg von `aktuell`. Passt keine in den
    Bereich des Geräts, kommt ZielAusserhalb.
    """
    d = (ziel[0] - montage.x, ziel[1] - montage.y, ziel[2] - montage.z)
    laenge = math.sqrt(sum(wert * wert for wert in d))
    if laenge < 1e-6:
        raise ZielAusserhalb("Das Ziel liegt genau im Gerät.")
    d = tuple(wert / laenge for wert in d)
    seite, vorne, achse = montage.achsen()
    punkt = lambda u, v: sum(a * b for a, b in zip(u, v))
    a, b, c = punkt(d, seite), punkt(d, vorne), punkt(d, achse)

    tilt = math.degrees(math.acos(max(-1.0, min(1.0, c))))
    # Zeigt das Ziel genau auf der Achse, ist Pan egal: Es bleibt, wo es ist.
    pan = math.degrees(math.atan2(a, b)) if tilt > 1e-6 else None
    start_pan, start_tilt = aktuell or (0.0, 0.0)

    loesungen = []
    if pan is None:
        loesungen.append(_in_geraet_winkel(montage, start_pan, 0.0))
    else:
        for umdrehung in (-720, -360, 0, 360, 720):
            loesungen.append(_in_geraet_winkel(montage, pan + umdrehung, tilt))
            loesungen.append(_in_geraet_winkel(montage, pan + 180 + umdrehung, -tilt))

    moeglich = [(p, t) for p, t in loesungen
                if abs(p) <= pan_bereich / 2 + 1e-6 and abs(t) <= tilt_bereich / 2 + 1e-6]
    if not moeglich:
        raise ZielAusserhalb(f"Ziel liegt außerhalb des Bereichs (nötig wäre Tilt {tilt:.0f}°, "
                             f"das Gerät schafft ±{tilt_bereich / 2:.0f}°).")
    return min(moeglich, key=lambda w: abs(w[0] - start_pan) + abs(w[1] - start_tilt))


def winkel_zu_anteil(winkel: float, bereich: float) -> float:
    """Winkel in einen Anteil 0..1 des DMX-Bereichs: -270°..+270° wird 0..1."""
    return max(0.0, min(1.0, winkel / bereich + 0.5))


def anteil_zu_winkel(anteil: float, bereich: float) -> float:
    return (anteil - 0.5) * bereich
