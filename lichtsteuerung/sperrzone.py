"""Sperrzone Publikum: Kein Moving Head darf auf Kopfhöhe ins Publikum zielen.

Wir verfolgen den Lichtstrahl als Gerade und schauen, ob er den Kasten
"Publikum bis Kopfhöhe" trifft. Außer der Strahlmitte prüfen wir vier Punkte
auf dem Rand des Lichtkegels, denn auch der Rand blendet.
"""
from __future__ import annotations

import math

from .pantilt import Vektor


def trifft_kasten(start: Vektor, richtung: Vektor, unten: Vektor, oben: Vektor) -> bool:
    """Trifft der Strahl den Kasten? Für jede Achse berechnen wir, wann er
    drinnen ist. Überlappen sich diese Zeiten, hat er den Kasten getroffen."""
    eintritt, austritt = 0.0, math.inf
    for achse in range(3):
        if abs(richtung[achse]) < 1e-9:
            if not unten[achse] <= start[achse] <= oben[achse]:
                return False
            continue
        a = (unten[achse] - start[achse]) / richtung[achse]
        b = (oben[achse] - start[achse]) / richtung[achse]
        eintritt = max(eintritt, min(a, b))
        austritt = min(austritt, max(a, b))
    return eintritt <= austritt


def kegel_rand(richtung: Vektor, halber_winkel_grad: float) -> list:
    """Vier Richtungen auf dem Rand des Lichtkegels."""
    rx, ry, rz = richtung
    hilfe = (0.0, 0.0, 1.0) if abs(rz) < 0.9 else (1.0, 0.0, 0.0)
    # Zwei Richtungen, die senkrecht auf dem Strahl stehen:
    ax, ay, az = (ry * hilfe[2] - rz * hilfe[1], rz * hilfe[0] - rx * hilfe[2],
                  rx * hilfe[1] - ry * hilfe[0])
    laenge = math.sqrt(ax * ax + ay * ay + az * az)
    ax, ay, az = ax / laenge, ay / laenge, az / laenge
    bx, by, bz = ry * az - rz * ay, rz * ax - rx * az, rx * ay - ry * ax
    weite = math.tan(math.radians(halber_winkel_grad))
    rand = []
    for u, v in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        rand.append((rx + weite * (u * ax + v * bx), ry + weite * (u * ay + v * by),
                      rz + weite * (u * az + v * bz)))
    return rand


def zielt_ins_publikum(start: Vektor, richtung: Vektor, publikum: dict,
                       abstrahlwinkel_grad: float = 0.0) -> bool:
    """True, wenn Strahl oder Kegelrand das Publikum auf Kopfhöhe erreichen."""
    abstand = publikum.get("sicherheitsabstand_m", 0.0)
    unten = (publikum["x_von_m"] - abstand, publikum["y_von_m"] - abstand, 0.0)
    oben = (publikum["x_bis_m"] + abstand, publikum["y_bis_m"] + abstand, publikum["kopfhoehe_m"])
    strahlen = [richtung]
    if abstrahlwinkel_grad > 0:
        strahlen += kegel_rand(richtung, abstrahlwinkel_grad / 2)
    return any(trifft_kasten(start, strahl, unten, oben) for strahl in strahlen)
