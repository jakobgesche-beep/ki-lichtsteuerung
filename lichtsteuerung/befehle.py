"""Die Befehlszeile, angelehnt an grandMA. Auch die Tasten im Pult-Tab schreiben hier hinein.

Beispiele (Groß- und Kleinschreibung egal, deutsch oder englisch):
    Gerät 1 bis 3            Fixture 1 Thru 3        Geräte nach Nummer im Patch wählen
    Gerät 1 + 5                                      mehrere einzeln
    Gruppe Spots / Gruppe 2  Group 2                 eine Gruppe wählen (Name oder Nummer im Pool)
    auf 80                   At 80                   Helligkeit 80 % für die Auswahl
    auf voll / auf aus       At Full / At 0
    Farbe Rot / Farbe 3      Color 3                 Position Mitte, Gobo 3, Effekt Kreis
    Leeren                   Clear                   erst Auswahl, dann Programmer leeren
    Speichern                Store                   Programmer als neuen Cue in die gewählte Sequenz
    Speichern Cue 3          Store Cue 3             Cue 3 überschreiben
    Speichern Fader 5        Store Exec 5            auf Fader 5 (leer: neue Sequenz)
    Update                   Update Exec 5           Programmer in den laufenden Cue einarbeiten
    Zuweisen Sequenz Show auf Fader 3                Assign Sequence Show At Exec 3
    Zuweisen Gruppe Spots auf Fader 4                Gruppen-Master
    Zuweisen Tempo auf Fader 10                      Tempo-Fader für alle Effekte
    Fader 3 auf 50           Exec 3 At 50            Fader schieben
    Go Fader 3 / Go- / Aus   Go Exec 3 / Off Exec 3  ohne Nummer: zuletzt benutzter Fader
    Löschen Fader 3          Delete Exec 3           Fader frei machen (die Sequenz bleibt)
    Löschen Cue 2            Delete Sequence Show    Cue im laufenden Fader / ganze Sequenz
    Label Fader 3 Intro                              Fader beschriften
    Seite 2                  Page 2                  Fader-Seite wechseln
    Grandmaster auf 80       Highlight   Blind       Oops (Rückgängig)
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
    "exec": "fader", "executor": "fader", "exekutor": "fader", "fader": "fader",
    "sequence": "sequenz", "sequenz": "sequenz", "seq": "sequenz",
    "assign": "zuweisen", "zuweisen": "zuweisen", "update": "update", "aktualisieren": "update",
    "delete": "loeschen", "löschen": "loeschen", "loeschen": "loeschen",
    "label": "label", "beschriften": "label", "oops": "oops", "undo": "oops", "rückgängig": "oops",
    "rueckgaengig": "oops", "page": "seite", "seite": "seite", "highlight": "highlight",
    "hervorheben": "highlight", "grandmaster": "grand", "grand": "grand", "gm": "grand", "tempo": "tempo",
}
DEUTSCHE_FARBEN = {"red": "rot", "green": "gruen", "grün": "gruen", "blue": "blau", "white": "weiss",
                   "weiß": "weiss", "yellow": "gelb", "warm": "warmweiss", "warmweiß": "warmweiss"}
# Wörter, die einen Namen beenden ("Zuweisen Sequenz Rote Show auf Fader 3")
ENDE_DES_NAMENS = set(WOERTER.values()) - {"plus", "bis", "voll", "cue", "tempo"}


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
                    if not pult.programmer.ist_leer():
                        pult.merke_programmer()
                    pult.programmer.leeren()
                    antworten.append("Programmer geleert")
                i += 1
                continue
            if wort == "speichern":
                i, antwort = self._speichern(teile, i + 1)
                antworten.append(antwort)
                continue
            if wort == "fader":
                nummer, i = self._fader_nummer(teile, i + 1)
                if i < len(teile) and self._wort(teile[i]) == "auf":
                    wert, i = self._wert(teile, i + 1)
                    pult.fader_setzen(nummer, wert, time.monotonic())
                    antworten.append(f"Fader {nummer} auf {round(wert * 100)} %")
                else:
                    pult.haupt = nummer - 1
                    antworten.append(f"Fader {nummer} gewählt")
                continue
            if wort in ("go", "zurueck", "aus"):
                nummer, i = self._optionaler_fader(teile, i + 1)
                jetzt = time.monotonic()
                if wort == "aus":
                    if self.show.song.laeuft_auf(nummer):
                        self.show.song.stoppen(jetzt)
                    pult.aus(nummer, jetzt)
                    antworten.append(f"Fader {nummer} aus")
                else:
                    pult.go(nummer, jetzt, 1 if wort == "go" else -1)
                    executor = pult.executor(nummer)
                    antworten.append(f"Fader {nummer}: Cue {executor.index + 1}" if executor.sequenz
                                     else f"Fader {nummer}")
                continue
            if wort == "update":
                nummer, i = self._optionaler_fader(teile, i + 1)
                sequenz = pult.aktualisieren(nummer)
                antworten.append(f"Update: {sequenz['name']}, Cue {pult.executor(nummer).index + 1}")
                continue
            if wort == "zuweisen":
                i, antwort = self._zuweisen(teile, i + 1)
                antworten.append(antwort)
                continue
            if wort == "loeschen":
                i, antwort = self._loeschen(teile, i + 1)
                antworten.append(antwort)
                continue
            if wort == "label":
                if i + 1 >= len(teile) or self._wort(teile[i + 1]) != "fader":
                    raise BefehlsFehler("So geht Label: Label Fader 3 Intro")
                nummer, i = self._fader_nummer(teile, i + 2)
                text = " ".join(teile[i:])
                if not text:
                    raise BefehlsFehler("Welcher Name? Zum Beispiel: Label Fader 3 Intro")
                pult.label_setzen(nummer, text)
                antworten.append(f"Fader {nummer} heißt jetzt {text}")
                i = len(teile)
                continue
            if wort == "oops":
                antworten.append(pult.rueckgaengig())
                i += 1
                continue
            if wort == "seite":
                if i + 1 >= len(teile):
                    raise BefehlsFehler("Welche Seite? Zum Beispiel: Seite 2")
                pult.seite_setzen(self._zahl(teile[i + 1]))
                antworten.append(f"Seite {pult.seite}")
                i += 2
                continue
            if wort == "highlight":
                pult.highlight = not pult.highlight
                antworten.append("Highlight an" if pult.highlight else "Highlight aus")
                i += 1
                continue
            if wort == "grand":
                if i + 1 >= len(teile) or self._wort(teile[i + 1]) != "auf":
                    raise BefehlsFehler("So geht es: Grandmaster auf 80")
                wert, i = self._wert(teile, i + 2)
                pult.grand_setzen(wert, time.monotonic())
                antworten.append(f"Grand Master {round(wert * 100)} %")
                continue
            if wort == "sequenz":
                name, i = self._name_bis_befehl(teile, i + 1)
                self.sequenz = self._sequenz(name)
                antworten.append(f"Sequenz {self.sequenz} gewählt")
                continue
            if wort == "blind":
                pult.programmer.blind = not pult.programmer.blind
                antworten.append("Blind an" if pult.programmer.blind else "Blind aus")
                i += 1
                continue
            raise BefehlsFehler(f"Unbekannt: „{teile[i]}“. Beispiele: Gerät 1 bis 3, Gruppe Spots, auf 80, Farbe Rot.")
        return " · ".join(antworten)

    # --- Hilfen -------------------------------------------------------------

    def _ist_befehl(self, wort: str) -> bool:
        return self._wort(wort) in ENDE_DES_NAMENS

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

    def _fader_nummer(self, teile: list, i: int) -> tuple:
        if i >= len(teile):
            raise BefehlsFehler("Welcher Fader? Zum Beispiel: Fader 3")
        nummer = self._zahl(teile[i])
        self.show.pult.executor(nummer)          # gibt es ihn?
        return nummer, i + 1

    def _optionaler_fader(self, teile: list, i: int) -> tuple:
        """Go Fader 3 oder nur Go (dann der zuletzt benutzte Fader)."""
        if i < len(teile) and self._wort(teile[i]) == "fader":
            return self._fader_nummer(teile, i + 1)
        return self.show.pult.haupt + 1, i

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
        text = teile[i].rstrip("%").replace(",", ".")
        if not re.fullmatch(r"\d+(\.\d+)?", text) or float(text) > 100:
            raise BefehlsFehler("Werte von 0 bis 100.")
        return float(text) / 100, i + 1

    @staticmethod
    def _finde(name: str, moeglich: list, art: str) -> str:
        """Name (auch nur der Anfang) oder Nummer im Pool."""
        for kandidat in moeglich:
            if kandidat.lower() == name.lower():
                return kandidat
        if name.isdigit() and 1 <= int(name) <= len(moeglich):
            return moeglich[int(name) - 1]
        passend = [k for k in moeglich if k.lower().startswith(name.lower())]
        if len(passend) == 1:
            return passend[0]
        raise BefehlsFehler(f"{art} „{name}“ gibt es nicht. Möglich: {', '.join(moeglich)}.")

    def _sequenz(self, name: str) -> str:
        namen = self.show.pult.sequenzen.namen()
        if f"Sequenz {name}" in namen and name not in namen:
            return f"Sequenz {name}"
        return self._finde(name, namen, "Sequenz")

    def _setzen(self, werte: dict) -> None:
        pult = self.show.pult
        if not pult.auswahl:
            raise BefehlsFehler("Zuerst Geräte wählen, zum Beispiel: Gruppe Spots")
        pult.merke_programmer()
        pult.programmer.setzen(pult.auswahl, werte)

    def _farbe(self, name: str) -> str:
        if name.isdigit():
            farbe = self._finde(name, list(FARBNAMEN), "Farbe")
        else:
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
        if name.isdigit() and f"Gobo {name}" in gobos:
            name = f"Gobo {name}"
        gobo = self._finde(name, gobos, "Gobo")
        self._setzen({"gobo": gobo})
        return gobo

    def _effekt(self, name: str) -> str:
        from .pult import EFFEKT_ARTEN
        namen = {text.lower(): art for art, text in EFFEKT_ARTEN.items()} | {art: art for art in EFFEKT_ARTEN}
        if name.isdigit():
            art = self._finde(name, list(EFFEKT_ARTEN), "Effekt")
        else:
            art = namen.get(name.lower()) or namen.get(self._finde(name, list(namen), "Effekt"))
        pult = self.show.pult
        if not pult.auswahl:
            raise BefehlsFehler("Zuerst Geräte wählen, zum Beispiel: Gruppe Spots")
        pult.merke_programmer()
        pult.programmer.effekt_dazu({"art": art, "ziel": {"geraete": list(pult.auswahl)}, "groesse": 0.5,
                                     "tempo": "musik", "beats": 4, "verteilung": 0.5})
        return f"Effekt {EFFEKT_ARTEN[art]}"

    def _speichern(self, teile: list, i: int) -> tuple:
        pult = self.show.pult
        ziel = self._wort(teile[i]) if i < len(teile) else None
        if ziel == "fader":
            nummer, i = self._fader_nummer(teile, i + 1)
            sequenz = pult.speichern_auf(nummer)
            return i, f"Gespeichert auf Fader {nummer}: {sequenz['name']}, Cue {len(sequenz['cues'])}"
        if ziel == "sequenz":
            name, i = self._name_bis_befehl(teile, i + 1)
            namen = pult.sequenzen.namen()
            try:
                self.sequenz = self._sequenz(name)
            except BefehlsFehler:
                if name.isdigit() and int(name) <= len(namen):
                    raise
                self.sequenz = name if not name.isdigit() else f"Sequenz {name}"
        nummer = None
        if i < len(teile) and self._wort(teile[i]) == "cue":
            nummer = self._zahl(teile[i + 1] if i + 1 < len(teile) else "")
            i += 2
        name = self.sequenz or "Show"
        vorhanden = (pult.sequenzen.lesen(name) or {"cues": []})["cues"]
        if nummer is not None and nummer > len(vorhanden):
            nummer = None                       # Cue gibt es noch nicht: hinten anhängen
        sequenz = pult.cue_speichern(name, vorhanden[nummer - 1]["name"] if nummer else f"Cue {len(vorhanden) + 1}",
                                     2.0, None, nummer)
        return i, f"Gespeichert in {name}, Cue {nummer or len(sequenz['cues'])}"

    def _zuweisen(self, teile: list, i: int) -> tuple:
        """Zuweisen Sequenz X auf Fader 3 / Zuweisen Gruppe Spots auf Fader 4 / Zuweisen Tempo auf Fader 10."""
        if i >= len(teile):
            raise BefehlsFehler("So geht es: Zuweisen Sequenz Show auf Fader 3")
        art = self._wort(teile[i])
        if art == "tempo":
            ziel, i = None, i + 1
        elif art in ("sequenz", "gruppe"):
            name, i = self._name_bis_befehl(teile, i + 1)
            ziel = self._sequenz(name) if art == "sequenz" else self._finde(name, self.show.patch.gruppen(), "Gruppe")
        else:
            raise BefehlsFehler("Zuweisen geht mit Sequenz, Gruppe oder Tempo.")
        if i < len(teile) and self._wort(teile[i]) == "auf":
            i += 1
        if i >= len(teile) or self._wort(teile[i]) != "fader":
            raise BefehlsFehler("Auf welchen Fader? Zum Beispiel: … auf Fader 3")
        nummer, i = self._fader_nummer(teile, i + 1)
        self.show.pult.zuweisen(nummer, art, ziel)
        return i, f"Fader {nummer}: {ziel or 'Tempo'}"

    def _loeschen(self, teile: list, i: int) -> tuple:
        pult = self.show.pult
        ziel = self._wort(teile[i]) if i < len(teile) else None
        if ziel == "fader":
            nummer, i = self._fader_nummer(teile, i + 1)
            pult.zuweisen(nummer, None)
            return i, f"Fader {nummer} ist frei"
        if ziel == "cue":
            nummer = self._zahl(teile[i + 1] if i + 1 < len(teile) else "")
            executor = pult.executor(pult.haupt + 1)
            if executor.sequenz is None:
                raise BefehlsFehler("Auf dem gewählten Fader liegt keine Sequenz.")
            pult.cue_loeschen(executor.sequenz["name"], nummer)
            return i + 2, f"Cue {nummer} gelöscht"
        if ziel == "sequenz":
            name, i = self._name_bis_befehl(teile, i + 1)
            name = self._sequenz(name)
            pult.sequenz_loeschen(name)
            return i, f"Sequenz {name} gelöscht"
        raise BefehlsFehler("Was löschen? Löschen Fader 3, Löschen Cue 2 oder Löschen Sequenz Name")
