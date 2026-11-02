"""Der Simulator: Liest ein fertiges DMX-Bild und sagt, was die Lichter tun würden.

Er arbeitet mit denselben 512 Zahlen, die auch an das Enttec gehen. Was die
3D-Vorschau zeigt, ist also genau das, was die Prüfung durchgelassen hat.
"""
from __future__ import annotations

from .farben import farbe as lies_farbe
from .katalog import FARB_TYPEN
from .pantilt import Montage, anteil_zu_winkel, richtung
from .pruefung import STANDARD_KEGEL_GRAD, bereich_von, hz_von
from .render import geraet_kanaele


class Simulator:
    def __init__(self, patch, buehne):
        self.geraete = []
        for geraet in patch.geraete:
            typ = patch.typ(geraet)
            kanaele = geraet_kanaele(patch, geraet)
            nach_typ = {}
            for index, kanal in kanaele:
                nach_typ.setdefault(kanal["typ"], (index, kanal))
            ort = buehne.geraet(geraet["id"])
            self.geraete.append({
                "geraet": geraet, "typen": nach_typ, "ort": ort, "kanaele": kanaele,
                "montage": Montage.aus_buehne(ort) if ort else None,
                "kegel": typ.daten.get("physik", {}).get("abstrahlwinkel_grad") or STANDARD_KEGEL_GRAD,
            })

    def aufbau(self) -> list:
        """Was sich nicht ändert: Name, Ort und Kegel. Für die 3D-Bühne beim Start."""
        ergebnis = []
        for eintrag in self.geraete:
            if eintrag["ort"] is None:
                continue
            ergebnis.append({
                "id": eintrag["geraet"]["id"], "name": eintrag["geraet"]["name"],
                "ort": eintrag["ort"], "kegel": eintrag["kegel"],
                "beweglich": "pan" in eintrag["typen"] or "tilt" in eintrag["typen"],
                "leuchtet": "nebel" not in eintrag["typen"],
            })
        return ergebnis

    def lies(self, bild: bytes) -> list:
        """Für jedes Gerät: Farbe, Helligkeit, Richtung und Strobo-Tempo."""
        return [self._geraet(eintrag, bild) for eintrag in self.geraete if eintrag["ort"]]

    def _geraet(self, eintrag: dict, bild: bytes) -> dict:
        typen = eintrag["typen"]
        rot, gruen, blau = self._farbe(typen, eintrag["kanaele"], bild)
        hell = bild[typen["dimmer"][0]] / 255 if "dimmer" in typen else 1.0
        hz = drehung = 0.0
        for index, kanal in eintrag["kanaele"]:
            bereich = bereich_von(kanal, bild[index])
            if bereich is None:
                continue
            if bereich["typ"] == "zu":
                hell = 0.0
            elif bereich["typ"] == "strobo":
                hz = hz_von(bereich, bild[index]) or 0.0
            elif bereich["typ"] == "drehung":
                drehung = float(bereich["richtung"])
        return {
            "id": eintrag["geraet"]["id"], "hell": round(hell, 3),
            "farbe": [round(rot, 3), round(gruen, 3), round(blau, 3)],
            "richtung": [round(w, 4) for w in self._richtung(eintrag, bild)], "strobo_hz": round(hz, 2),
            "gobo": self._gobo(typen, bild), "gobo_drehung": drehung,
        }

    @staticmethod
    def _farbe(typen, kanaele, bild):
        if "farbrad" in typen:
            index, kanal = typen["farbrad"]
            bereich = bereich_von(kanal, bild[index])
            if bereich and "farbe" in bereich:
                return lies_farbe(bereich["farbe"])
            return (1.0, 1.0, 1.0)
        summe, led_gefunden = [0.0, 0.0, 0.0], False
        for index, kanal in kanaele:
            if kanal["typ"] in FARB_TYPEN:
                led_gefunden = True
                led = lies_farbe(FARB_TYPEN[kanal["typ"]])
                for i in range(3):
                    summe[i] += led[i] * bild[index] / 255
        if not led_gefunden:
            return (1.0, 1.0, 1.0)      # weißes Gerät wie ein Stufenlinsen-Spot
        return tuple(min(1.0, wert) for wert in summe)

    @staticmethod
    def _gobo(typen, bild):
        if "gobo" not in typen:
            return None
        index, kanal = typen["gobo"]
        bereich = bereich_von(kanal, bild[index])
        return bereich.get("name") if bereich else None

    @staticmethod
    def _anteil(typen, name, bild) -> float:
        index = typen[name][0]
        fein = typen.get(f"{name}_fein")
        return bild[index] / 255 if fein is None else (bild[index] * 256 + bild[fein[0]]) / 65535

    def _richtung(self, eintrag: dict, bild: bytes):
        typen = eintrag["typen"]
        ort, montage = eintrag["ort"], eintrag["montage"]
        if "pan" in typen or "tilt" in typen:
            winkel = {"pan": 0.0, "tilt": 0.0}
            for name in winkel:
                grad = typen[name][1].get("grad") if name in typen else None
                if grad:
                    winkel[name] = anteil_zu_winkel(self._anteil(typen, name, bild), grad)
            return richtung(montage, winkel["pan"], winkel["tilt"])
        # Feste Geräte zeigen dorthin, wohin sie laut stage.json geneigt sind.
        return richtung(montage, 0.0, ort.get("neigung_grad", 0.0))
