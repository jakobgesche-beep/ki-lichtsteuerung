"""Die Befehlszeile, angelehnt an grandMA. Auch die KI soll später so das Pult bedienen.

Beispiele (Groß- und Kleinschreibung egal, deutsch oder englisch):
    Gerät 1 bis 3            Fixture 1 Thru 3        Geräte nach Nummer im Patch wählen
    Gerät 1 + 5                                      mehrere einzeln
    Gruppe Spots             Group Spots             eine Gruppe wählen
    auf 80                   At 80                   Helligkeit 80 % für die Auswahl
    auf voll / auf aus       At Full / At 0
    Gruppe Spots auf 50                              wählen und gleich setzen
    Farbe Rot                Color Red
    Position Mitte           Gobo 3                  Effekt Kreis
    Leeren                   Clear                   erst Auswahl, dann Programmer leeren
    Speichern                Store                   Programmer als neuen Cue (Sequenz wie im Pult gewählt)
    Speichern Cue 3          Store Cue 3             Cue 3 überschreiben
    Go / Go- / Blind / Aus   Go / Go- / Blind / Off
"""
from __future__ import annotations

import re
import time
from typing import Optional

from .farben import FARBNAMEN

WOERTER = {
    "fixture": "geraet", "geraet": "geraet", "geräte": "geraet", "geraete": "geraet", "gerät": "geraet",
    "group": "gruppe", "gruppe": "gruppe", "at": "auf", "auf": "auf", "thru": "bis", "bis": "bis",
    "color": "farbe", "colour": "farbe", "farbe": "farbe", "position": "position", "gobo": "gobo",
    "effect": "effekt", "effekt": "effekt", "clear": "leeren", "leeren": "leeren", "store": "speichern",
    "speichern": "speichern", "cue": "cue", "go": "go", "go+": "go", "go-": "zurueck", "blind": "blind",
    "off": "aus", "aus": "aus", "full": "voll", "voll": "voll", "+": "plus", "und": "plus",
}
DEUTSCHE_FARBEN = {"red": "rot", "green": "gruen", "grün": "gruen", "blue": "blau", "white": "weiss",
                   "weiß": "weiss", "yellow": "gelb", "warm": "warmweiss", "warmweiß": "warmweiss"}


class BefehlsFehler(ValueError):
    pass


def woerter(text: str) -> list:
    return [w for w in re.split(r"\s+", text.strip().replace("+", " + ")) if w]


class Befehlszeile:
    def __init__(self, show):
        self.show = show
        self.sequenz: Optional[str] = None      # setzt die Oberfläche: dahin speichert "Speichern"

    def ausfuehren(self, text: str) -> str:
        """Führt einen Befehl aus und gibt eine kurze Antwort zurück."""
        teile = woerter(text)
        if not teile:
            raise BefehlsFehler("Kein Befehl.")
        with self.show.sperre:
            return self._ausfuehren(teile)

    def _wort(self, wort: str) -> str:
        return WOERTER.get(wort.lower(), wort)

    def _ausfuehren(self, teile: list) -> str:
        pult = self.show.pult
        antworten = []
        i = 0
        while i < len(teile):
            wort = self._wort(teile[i])
            if wort == "geraet":
                nummern, i = self._nummern(teile, i + 1)
                pult.waehlen(self._ids(nummern), "setzen")
                antworten.append(f"{len(pult.auswahl)} Geräte gewählt")
                continue
            if wort == "gruppe":
                name, i = self._name_bis_befehl(teile, i + 1)
                gruppe = self._finde(name, self.show.patch.gruppen(), "Gruppe")
                pult.waehlen([g["id"] for g in self.show.patch.in_gruppe(gruppe)], "setzen")
                antworten.append(f"Gruppe {gruppe} gewählt")
                continue
            if wort == "auf":
                wert, i = self._wert(teile, i + 1)
                self._setzen({"helligkeit": wert})
                antworten.append(f"Helligkeit {round(wert * 100)} %")
                continue
            if wort in ("farbe", "position", "gobo", "effekt"):
                name, i = self._name_bis_befehl(teile, i + 1)
                antworten.append(getattr(self, "_" + wort)(name))
                continue
            if wort == "leeren":
                if pult.auswahl:
                    pult.auswahl = []
                    antworten.append("Auswahl geleert")
                else:
                    pult.programmer.leeren()
                    antworten.append("Programmer geleert")
                i += 1
                continue
            if wort == "speichern":
                nummer = None
                if i + 2 < len(teile) + 1 and i + 1 < len(teile) and self._wort(teile[i + 1]) == "cue":
                    nummer = self._zahl(teile[i + 2] if i + 2 < len(teile) else "")
                    i += 3
                else:
                    i += 1
                antworten.append(self._speichern(nummer))
                continue
            if wort in ("go", "zurueck"):
                pult.go(pult.haupt + 1, time.monotonic(), 1 if wort == "go" else -1)
                executor = pult.executor(pult.haupt + 1)
                antworten.append(f"Executor {executor.nummer}: Cue {executor.index + 1}")
                i += 1
                continue
            if wort == "blind":
                pult.programmer.blind = not pult.programmer.blind
                antworten.append("Blind an" if pult.programmer.blind else "Blind aus")
                i += 1
                continue
            if wort == "aus":
                pult.executor(pult.haupt + 1).aus(time.monotonic())
                antworten.append(f"Executor {pult.haupt + 1} aus")
                i += 1
                continue
            raise BefehlsFehler(f"Unbekannt: „{teile[i]}“. Beispiele: Gerät 1 bis 3, Gruppe Spots, auf 80, Farbe Rot.")
        return " · ".join(antworten)

    # --- Hilfen -------------------------------------------------------------

    def _ist_befehl(self, wort: str) -> bool:
        return self._wort(wort) in set(WOERTER.values()) - {"plus", "bis", "voll", "cue"}

    def _name_bis_befehl(self, teile: list, i: int) -> tuple:
        name = []
        while i < len(teile) and not self._ist_befehl(teile[i]):
            name.append(teile[i])
            i += 1
        if not name:
            raise BefehlsFehler("Da fehlt ein Name.")
        return " ".join(name), i

    @staticmethod
    def _zahl(text: str) -> int:
        if not text.isdigit():
            raise BefehlsFehler(f"„{text}“ ist keine Nummer.")
        return int(text)

    def _nummern(self, teile: list, i: int) -> tuple:
        nummern = []
        while i < len(teile):
            wort = self._wort(teile[i])
            if teile[i].isdigit():
                nummern.append(int(teile[i]))
            elif wort == "bis" and nummern and i + 1 < len(teile):
                ende = self._zahl(teile[i + 1])
                nummern += list(range(nummern[-1] + 1, ende + 1))
                i += 1
            elif wort != "plus":
                break
            i += 1
        if not nummern:
            raise BefehlsFehler("Welche Geräte? Zum Beispiel: Gerät 1 bis 3")
        return nummern, i

    def _ids(self, nummern: list) -> list:
        geraete = self.show.patch.geraete
        falsch = [n for n in nummern if not 1 <= n <= len(geraete)]
        if falsch:
            raise BefehlsFehler(f"Gerät {falsch[0]} gibt es nicht. Es gibt 1 bis {len(geraete)}.")
        return [geraete[n - 1]["id"] for n in nummern]

    def _wert(self, teile: list, i: int) -> tuple:
        if i >= len(teile):
            raise BefehlsFehler("Auf wie viel? Zum Beispiel: auf 80")
        wort = self._wort(teile[i])
        if wort == "voll":
            return 1.0, i + 1
        if wort == "aus":
            return 0.0, i + 1
        text = teile[i].rstrip("%")
        if not re.fullmatch(r"\d+(\.\d+)?", text) or float(text) > 100:
            raise BefehlsFehler("Helligkeit von 0 bis 100.")
        return float(text) / 100, i + 1

    @staticmethod
    def _finde(name: str, moeglich: list, art: str) -> str:
        for kandidat in moeglich:
            if kandidat.lower() == name.lower():
                return kandidat
        passend = [k for k in moeglich if k.lower().startswith(name.lower())]
        if len(passend) == 1:
            return passend[0]
        raise BefehlsFehler(f"{art} „{name}“ gibt es nicht. Möglich: {', '.join(moeglich)}.")

    def _setzen(self, werte: dict) -> None:
        pult = self.show.pult
        if not pult.auswahl:
            raise BefehlsFehler("Zuerst Geräte wählen, zum Beispiel: Gruppe Spots")
        pult.programmer.setzen(pult.auswahl, werte)

    def _farbe(self, name: str) -> str:
        farbe = DEUTSCHE_FARBEN.get(name.lower(), name.lower().replace("ß", "ss").replace("ü", "ue"))
        farbe = self._finde(farbe, list(FARBNAMEN), "Farbe")
        self._setzen({"farbe": farbe})
        return f"Farbe {farbe}"

    def _position(self, name: str) -> str:
        position = self._finde(name, list(self.show.positionen), "Position")
        self._setzen({"position": position})
        return f"Position {position}"

    def _gobo(self, name: str) -> str:
        gobos = {"Offen"}
        for geraet in self.show.patch.geraete:
            if geraet["id"] in self.show.pult.auswahl:
                for _, kanal in self.show.patch.typ(geraet).kanaele_im_modus(geraet["modus"]):
                    if kanal["typ"] == "gobo":
                        gobos |= {b["name"] for b in kanal.get("bereiche", []) if b["typ"] == "platz"}
        gobos = sorted(gobos)
        if name.isdigit():
            name = f"Gobo {name}"
        gobo = self._finde(name, gobos, "Gobo")
        self._setzen({"gobo": gobo})
        return gobo

    def _effekt(self, name: str) -> str:
        from .pult import EFFEKT_ARTEN
        namen = {text.lower(): art for art, text in EFFEKT_ARTEN.items()} | {art: art for art in EFFEKT_ARTEN}
        art = namen.get(name.lower()) or namen.get(self._finde(name, list(namen), "Effekt"))
        pult = self.show.pult
        if not pult.auswahl:
            raise BefehlsFehler("Zuerst Geräte wählen, zum Beispiel: Gruppe Spots")
        pult.programmer.effekt_dazu({"art": art, "ziel": {"geraete": list(pult.auswahl)}, "groesse": 0.5,
                                     "tempo": "musik", "beats": 4, "verteilung": 0.5})
        return f"Effekt {EFFEKT_ARTEN[art]}"

    def _speichern(self, nummer: Optional[int]) -> str:
        name = self.sequenz or "Show"
        sequenz = self.show.pult.cue_speichern(name, f"Cue {nummer or len((self.show.pult.sequenzen.lesen(name) or {'cues': []})['cues']) + 1}",
                                               2.0, None, nummer)
        return f"Gespeichert in {name}, Cue {nummer or len(sequenz['cues'])}"
