"""Positionen einmessen und Follow-Spot: Damit die Köpfe wirklich treffen, und einem Sänger folgen.

Einmessen (Setup → Positionen)
    Das Programm rechnet aus, wohin ein Kopf zeigen muss, aus seinem Ort in stage.json (wo er hängt, wie er
    gedreht ist). Schon ein paar Grad falsch montiert, und der Spot verfehlt den Sänger um einen Meter.
    Darum: Kopf wählen, eine benannte Position wählen (dort steht jemand oder liegt ein Klebeband), "Hinfahren".
    Dann den Kopf mit den Pfeilen genau auf die Stelle schieben und "Punkt merken". Nach 2 bis 3 Punkten
    rechnet das Programm aus, um wie viel Grad Pan und Tilt verschoben sind (und ob Pan oder Tilt am Gerät
    umgekehrt ist). Danach treffen alle Positionen, auch die, die nicht eingemessen wurden.

Follow-Spot (Show-Seite und Handy)
    In der Draufsicht der Bühne einen Punkt ziehen: Die gewählten Köpfe (sonst alle Moving Heads) zeigen auf
    Kopfhöhe dorthin, hell und weiß, und folgen dem Finger. Nur auf der Bühne, nie ins Publikum.
"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional

from .pantilt import Montage, ZielAusserhalb
from .render import Eigenschaften
from .szenen import bereiche_von, zeige_auf

KOPFHOEHE_M = 1.6              # über dem Bühnenboden (wie beim Tippen auf den Grundriss im Pult)
WEISS = (1.0, 1.0, 1.0)


def _punkt(punkt) -> tuple:
    """Benannte Positionen sind {"x", "y", "z"}, gerechnet wird mit (x, y, z)."""
    return (punkt["x"], punkt["y"], punkt["z"]) if isinstance(punkt, dict) else tuple(punkt)


def _normal(winkel: float) -> float:
    """Winkel nach -180 bis 180."""
    return (winkel + 180.0) % 360.0 - 180.0


def geometrische_winkel(montage: Montage, ziel: tuple) -> tuple:
    """Pan und Tilt ohne Versatz und Umkehren (wie die Rechnung sie vor dem Gerät sieht)."""
    d = [ziel[i] - (montage.x, montage.y, montage.z)[i] for i in range(3)]
    laenge = math.sqrt(sum(w * w for w in d)) or 1e-9
    d = [w / laenge for w in d]
    seite, vorne, achse = montage.achsen()
    punkt = lambda u, v: sum(a * b for a, b in zip(u, v))
    a, b, c = punkt(d, seite), punkt(d, vorne), punkt(d, achse)
    return math.degrees(math.atan2(a, b)), math.degrees(math.acos(max(-1.0, min(1.0, c))))


def versatz_berechnen(montage: Montage, messungen: list) -> dict:
    """messungen: [(Ziel (x, y, z), Pan, Tilt am Gerät)]. Sucht Pan- und Tilt-Versatz, mit denen die Rechnung
    genau die eingestellten Winkel ergibt. Ab 2 Punkten auch, ob Pan oder Tilt umgekehrt ist.

    Gibt pan_versatz_grad, tilt_versatz_grad, pan_umkehren, tilt_umkehren und die mittlere Abweichung (Grad) zurück."""
    if not messungen:
        raise ValueError("Erst mindestens einen Punkt merken.")
    basis = replace(montage, pan_versatz_grad=0.0, tilt_versatz_grad=0.0, pan_umkehren=False, tilt_umkehren=False)
    if len(messungen) < 2:
        arten = [(montage.pan_umkehren, montage.tilt_umkehren)]
    else:
        arten = [(p, t) for p in (False, True) for t in (False, True)]
    beste = None
    for pan_um, tilt_um in arten:
        sp, st = (-1.0 if pan_um else 1.0), (-1.0 if tilt_um else 1.0)
        kandidaten = []
        for ziel, pan_ist, tilt_ist in messungen:
            pan_g, tilt_g = geometrische_winkel(basis, ziel)
            kandidaten.append([(_normal(p - sp * pan_ist), t - st * tilt_ist)
                               for p, t in ((pan_g, tilt_g), (pan_g + 180.0, -tilt_g))])
        for erster in kandidaten[0]:
            abstand = lambda k: math.hypot(_normal(k[0] - erster[0]), k[1] - erster[1])
            gewaehlt = [erster] + [min(liste, key=abstand) for liste in kandidaten[1:]]
            pan_v = _normal(erster[0] + sum(_normal(k[0] - erster[0]) for k in gewaehlt) / len(gewaehlt))
            tilt_v = sum(k[1] for k in gewaehlt) / len(gewaehlt)
            rest = math.sqrt(sum(math.hypot(_normal(k[0] - pan_v), k[1] - tilt_v) ** 2 for k in gewaehlt) / len(gewaehlt))
            bewertung = (round(rest, 3), abs(pan_v) + abs(tilt_v), pan_um or tilt_um)
            if beste is None or bewertung < beste[0]:
                beste = (bewertung, {"pan_versatz_grad": round(pan_v, 2), "tilt_versatz_grad": round(tilt_v, 2),
                                     "pan_umkehren": pan_um, "tilt_umkehren": tilt_um, "abweichung_grad": round(rest, 2)})
    return beste[1]


class Einmessen:
    """Ein Kopf wird eingemessen: Er leuchtet weiß, Pan und Tilt kommen von hier (über allem anderen)."""

    def __init__(self, show):
        self.show = show
        self.geraet: Optional[dict] = None
        self.pan = self.tilt = 0.0
        self.ziel: Optional[str] = None
        self.punkte: list = []                # [(Name, (x, y, z), Pan, Tilt)]
        self.ergebnis: Optional[dict] = None

    def _bereiche(self):
        bereiche = bereiche_von(self.show.patch, self.geraet) if self.geraet else None
        if not bereiche:
            raise ValueError("Erst einen Moving Head zum Einmessen wählen.")
        return bereiche

    def starten(self, geraet_id: str) -> None:
        geraet = self.show.patch.geraet(geraet_id)
        if not bereiche_von(self.show.patch, geraet) or self.show.buehne.geraet(geraet_id) is None:
            raise ValueError(f"{geraet['name']} kann sich nicht bewegen (kein Pan/Tilt oder kein Ort auf der Bühne).")
        self.geraet, self.pan, self.tilt, self.ziel, self.punkte, self.ergebnis = geraet, 0.0, 0.0, None, [], None

    def beenden(self) -> None:
        self.geraet, self.ziel, self.punkte, self.ergebnis = None, None, [], None

    def hinfahren(self, position: str) -> None:
        """Fährt die gerechnete Stelle einer benannten Position an (mit dem jetzigen Versatz)."""
        self._bereiche()
        if position not in self.show.positionen:
            raise ValueError(f"Die Position „{position}“ gibt es nicht.")
        try:
            self.pan, self.tilt = zeige_auf(self.geraet, _punkt(self.show.positionen[position]), self.show.patch,
                                            self.show.buehne, (self.pan, self.tilt))
        except ZielAusserhalb as fehler:
            raise ValueError(str(fehler)) from fehler
        self.ziel, self.ergebnis = position, None

    def schubsen(self, pan: float, tilt: float) -> None:
        pan_bereich, tilt_bereich = self._bereiche()
        self.pan = max(-pan_bereich / 2, min(pan_bereich / 2, self.pan + float(pan)))
        self.tilt = max(-tilt_bereich / 2, min(tilt_bereich / 2, self.tilt + float(tilt)))

    def merken(self) -> None:
        if self.geraet is None or self.ziel is None:
            raise ValueError("Erst eine Position anfahren und den Kopf genau auf die Stelle schieben.")
        punkt = _punkt(self.show.positionen[self.ziel])
        self.punkte = [p for p in self.punkte if p[0] != self.ziel] + [(self.ziel, punkt, self.pan, self.tilt)]
        self.ergebnis = None

    def ausrechnen(self) -> dict:
        if self.geraet is None:
            raise ValueError("Erst einen Moving Head zum Einmessen wählen.")
        montage = Montage.aus_buehne(self.show.buehne.geraet(self.geraet["id"]))
        self.ergebnis = versatz_berechnen(montage, [(p[1], p[2], p[3]) for p in self.punkte])
        return self.ergebnis

    def uebernehmen(self) -> dict:
        """Schreibt den Versatz in stage.json. Ab dann rechnet jede Position damit."""
        ergebnis = self.ergebnis or self.ausrechnen()
        self.show.buehne.setze_geraet(self.geraet["id"], {k: v for k, v in ergebnis.items() if k != "abweichung_grad"})
        self.show.buehne.speichern()
        return ergebnis

    def anwenden(self, zustand: dict) -> dict:
        if self.geraet is None:
            return zustand
        zustand = dict(zustand)
        zustand[self.geraet["id"]] = Eigenschaften(helligkeit=1.0, farbe=WEISS, pan=self.pan, tilt=self.tilt, gobo="Offen")
        return zustand

    def zustand(self) -> dict:
        return {"geraet": self.geraet["id"] if self.geraet else None, "pan": round(self.pan, 1), "tilt": round(self.tilt, 1),
                "ziel": self.ziel, "punkte": [{"name": p[0], "pan": round(p[2], 1), "tilt": round(p[3], 1)} for p in self.punkte],
                "ergebnis": self.ergebnis,
                "jetzt": {k: (self.show.buehne.geraet(self.geraet["id"]) or {}).get(k)
                          for k in ("pan_versatz_grad", "tilt_versatz_grad", "pan_umkehren", "tilt_umkehren")}
                if self.geraet else None}


class FollowSpot:
    """Köpfe folgen einem Punkt auf der Bühne (Finger in der Draufsicht)."""

    def __init__(self, show):
        self.show = show
        self.punkt: Optional[tuple] = None
        self.geraete: list = []
        self.hell = 1.0
        self._winkel: dict = {}

    @property
    def an(self) -> bool:
        return self.punkt is not None

    def moegliche(self) -> list:
        """Alle Moving Heads mit Ort auf der Bühne."""
        return [g for g in self.show.patch.geraete
                if bereiche_von(self.show.patch, g) and self.show.buehne.geraet(g["id"]) is not None]

    def setzen(self, x: float, y: float, geraete: Optional[list] = None, hell: Optional[float] = None) -> None:
        buehne = self.show.buehne.daten.get("buehne", {"breite_m": 8.0, "tiefe_m": 5.0, "hoehe_kante_m": 0.8})
        x = max(-buehne["breite_m"] / 2, min(buehne["breite_m"] / 2, float(x)))
        y = max(0.0, min(buehne["tiefe_m"], float(y)))                 # nur auf der Bühne, nie ins Publikum
        moegliche = {g["id"] for g in self.moegliche()}
        if geraete is not None:
            self.geraete = [g for g in geraete if g in moegliche]
        if not self.geraete:
            self.geraete = sorted(moegliche, key=[g["id"] for g in self.show.patch.geraete].index)
        if not self.geraete:
            raise ValueError("Es gibt keinen Moving Head mit Ort auf der Bühne (Setup → Patch).")
        if hell is not None:
            self.hell = max(0.1, min(1.0, float(hell)))
        self.punkt = (round(x, 2), round(y, 2), buehne["hoehe_kante_m"] + KOPFHOEHE_M)

    def aus(self) -> None:
        self.punkt, self._winkel = None, {}

    def anwenden(self, zustand: dict) -> dict:
        if self.punkt is None:
            return zustand
        zustand = dict(zustand)
        for geraet_id in self.geraete:
            try:
                geraet = self.show.patch.geraet(geraet_id)
                pan, tilt = zeige_auf(geraet, self.punkt, self.show.patch, self.show.buehne, self._winkel.get(geraet_id))
            except Exception:
                continue                                           # dieser Kopf kommt nicht hin: er bleibt, wie er ist
            self._winkel[geraet_id] = (pan, tilt)
            alt = zustand.get(geraet_id) or Eigenschaften()
            zustand[geraet_id] = alt.kopie(helligkeit=self.hell, farbe=WEISS, pan=pan, tilt=tilt, gobo="Offen",
                                           strobo_hz=0.0, gobo_drehung=None)
        return zustand

    def zustand(self) -> dict:
        return {"an": self.an, "punkt": list(self.punkt) if self.punkt else None, "geraete": self.geraete,
                "hell": self.hell}
