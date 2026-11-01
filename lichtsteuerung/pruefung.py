"""Die Prüfung: Jedes DMX-Bild läuft hier durch, bevor es irgendwo hingeht.

Geprüft wird gegen die Gerätedatei aus dem Katalog:
  * gültiger Bereich: Programm- und Reset-Kanäle bleiben auf ihrem Standard,
    Werte außerhalb der bekannten Bereiche werden zurückgesetzt
  * Strobo: Obergrenze für Blitze pro Sekunde und maximale Dauer
  * Hazer: nur, wenn das Profil ihn erlaubt
  * Sperrzone Publikum

Die Prüfung arbeitet mit den fertigen DMX-Zahlen und nicht mit Eigenschaften.
Dann ist egal, woher ein Wert kam: Engine, Cue, DMX-Test oder später die KI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .katalog import FARB_TYPEN, GESPERRTE_TYPEN
from .pantilt import Montage, anteil_zu_winkel, richtung
from .render import _kanal_wert, geraet_kanaele, offen_wert, strobo_bereich, zu_wert
from .sicherheit import Grenzen, StroboWaechter
from .sperrzone import zielt_ins_publikum

STANDARD_KEGEL_GRAD = 15.0


@dataclass
class Vorgaben:
    """Was gerade erlaubt ist. Kommt vom aktiven Profil und den Override-Tasten."""

    strobo_max_hz: float = 0.0        # 0 = aus
    strobo_max_dauer_s: float = 0.0
    hazer_erlaubt: bool = False
    blackout: bool = False            # Die Taste gilt auch für rohe Werte.


def bereich_von(kanal: dict, wert: int) -> Optional[dict]:
    for bereich in kanal.get("bereiche", []):
        if bereich["von"] <= wert <= bereich["bis"]:
            return bereich
    return None


def hz_von(bereich: dict, wert: int) -> Optional[float]:
    """Wie viele Blitze pro Sekunde bedeutet dieser Wert? None = unbekannt."""
    von, bis = bereich.get("hz_von"), bereich.get("hz_bis")
    if von is None or bis is None:
        return None
    if bereich["bis"] == bereich["von"]:
        return float(bis)
    return von + (bis - von) * (wert - bereich["von"]) / (bereich["bis"] - bereich["von"])


def sicherer_wert(kanal: dict) -> int:
    """Ein Wert, bei dem dieser Kanal bestimmt nicht blitzt."""
    if kanal["typ"] == "strobo":
        return offen_wert(kanal)
    return kanal.get("standard", 0)


class Pruefer:
    def __init__(self, patch, buehne, grenzen: Grenzen):
        self.buehne = buehne
        self.grenzen = grenzen
        self.strobo = StroboWaechter()
        self.geraete = []
        for geraet in patch.geraete:
            typ = patch.typ(geraet)
            kanaele = geraet_kanaele(patch, geraet)
            nach_typ = {}
            for index, kanal in kanaele:
                nach_typ.setdefault(kanal["typ"], (index, kanal))
            self.geraete.append({
                "id": geraet["id"], "name": geraet["name"], "kanaele": kanaele, "typen": nach_typ,
                "kegel": typ.daten.get("physik", {}).get("abstrahlwinkel_grad") or STANDARD_KEGEL_GRAD,
            })
        self.letzte_sichere_stellung = {}

    def pruefe(self, bild: bytearray, vorgaben: Vorgaben, jetzt: Optional[float] = None):
        """Gibt (geprüftes Bild, Meldungen, blitzt gerade) zurück. Das Original bleibt."""
        jetzt = time.monotonic() if jetzt is None else jetzt
        bild = bytearray(bild)
        meldungen = []
        blitzt = False
        for geraet in self.geraete:
            for index, kanal in geraet["kanaele"]:
                self._pruefe_bereich(bild, index, kanal)
            if self._pruefe_strobo(bild, geraet, vorgaben, jetzt, meldungen):
                blitzt = True
            if not vorgaben.hazer_erlaubt and "nebel" in geraet["typen"]:
                bild[geraet["typen"]["nebel"][0]] = 0
            self._pruefe_sperrzone(bild, geraet, meldungen)
            if vorgaben.blackout:
                self._verdunkeln(bild, geraet)
        self.strobo.melde(blitzt, jetzt, self._max_dauer(vorgaben), self.grenzen.strobo_pause_s)
        return bild, meldungen, blitzt

    def _max_dauer(self, vorgaben: Vorgaben) -> float:
        return min(vorgaben.strobo_max_dauer_s, self.grenzen.strobo_max_dauer_s)

    @staticmethod
    def _pruefe_bereich(bild, index, kanal) -> None:
        if kanal["typ"] in GESPERRTE_TYPEN:
            bild[index] = kanal.get("standard", 0)
        elif kanal.get("bereiche") and bereich_von(kanal, bild[index]) is None:
            bild[index] = kanal.get("standard", 0)

    def _pruefe_strobo(self, bild, geraet, vorgaben, jetzt, meldungen) -> bool:
        """Setzt jeden Strobo-Wert über der Grenze zurück. True, wenn es erlaubt blitzt."""
        grenze = min(vorgaben.strobo_max_hz, self.grenzen.strobo_max_hz)
        blitzt = False
        for index, kanal in geraet["kanaele"]:
            bereich = bereich_von(kanal, bild[index])
            if bereich is None or bereich["typ"] != "strobo":
                continue
            hz = hz_von(bereich, bild[index])
            if hz is None:
                bild[index] = sicherer_wert(kanal)
                meldungen.append(f"{geraet['name']}: Strobo-Tempo unbekannt, Strobo gesperrt.")
            elif grenze <= 0 or not self.strobo.erlaubt(jetzt):
                bild[index] = sicherer_wert(kanal)
            elif hz > grenze:
                passend = strobo_bereich(kanal, grenze)
                bild[index] = _kanal_wert(passend, grenze) if passend else sicherer_wert(kanal)
                blitzt = passend is not None
                meldungen.append(f"{geraet['name']}: Strobo auf {grenze:g} Blitze/s begrenzt.")
            else:
                blitzt = True
        return blitzt

    def _pruefe_sperrzone(self, bild, geraet, meldungen) -> None:
        typen = geraet["typen"]
        if "pan" not in typen and "tilt" not in typen:
            return
        ort = self.buehne.geraet(geraet["id"])
        pan_grad = typen["pan"][1].get("grad") if "pan" in typen else 0.0
        tilt_grad = typen["tilt"][1].get("grad") if "tilt" in typen else 0.0
        if ort is None or pan_grad is None or tilt_grad is None:
            self._verdunkeln(bild, geraet)
            meldungen.append(f"{geraet['name']}: Ort oder Winkelbereich fehlt, Gerät bleibt dunkel.")
            return
        montage = Montage.aus_buehne(ort)
        winkel = {}
        for name, grad in (("pan", pan_grad), ("tilt", tilt_grad)):
            winkel[name] = anteil_zu_winkel(self._anteil(bild, typen, name), grad) if name in typen else 0.0
        strahl = richtung(montage, winkel["pan"], winkel["tilt"])
        stellung_kanaele = [typen[t][0] for t in ("pan", "pan_fein", "tilt", "tilt_fein") if t in typen]
        if not zielt_ins_publikum((montage.x, montage.y, montage.z), strahl,
                                  self.buehne.publikum, geraet["kegel"]):
            self.letzte_sichere_stellung[geraet["id"]] = [bild[i] for i in stellung_kanaele]
            return
        meldungen.append(f"{geraet['name']}: Ziel liegt in der Sperrzone Publikum.")
        sicher = self.letzte_sichere_stellung.get(geraet["id"])
        if sicher is None:
            self._verdunkeln(bild, geraet)
        else:
            for index, wert in zip(stellung_kanaele, sicher):
                bild[index] = wert

    @staticmethod
    def _anteil(bild, typen, name) -> float:
        index = typen[name][0]
        fein = typen.get(f"{name}_fein")
        if fein is None:
            return bild[index] / 255
        return (bild[index] * 256 + bild[fein[0]]) / 65535

    @staticmethod
    def _verdunkeln(bild, geraet) -> None:
        for index, kanal in geraet["kanaele"]:
            if kanal["typ"] == "dimmer" or kanal["typ"] in FARB_TYPEN:
                bild[index] = 0
            elif kanal["typ"] == "strobo":
                geschlossen = zu_wert(kanal)
                if geschlossen is not None:
                    bild[index] = geschlossen
