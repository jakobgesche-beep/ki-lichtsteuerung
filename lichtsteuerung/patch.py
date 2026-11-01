"""Der Patch: Welche Geräte sind da, und auf welcher DMX-Adresse liegen sie?

Daten stehen in fixtures.json. Jedes Gerät hat eine feste `id` und `gruppen`
nach Funktion ("Farb-PARs", "Frontlicht", ...). Cues und Engine sprechen nur
Gruppen und ids an. Deshalb laufen sie weiter, wenn ein Gerät getauscht wird.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import daten
from .buehne import Buehne
from .katalog import Katalog

DMX_KANAELE = 512
FUNKTIONS_GRUPPEN = ["Farb-PARs", "Frontlicht", "Effektlicht", "Spots", "Dunst"]


class PatchFehler(Exception):
    """Der Patch kann so nicht gespeichert werden."""


def namen_erzeugen(name: str, anzahl: int) -> list:
    """Aus "PAR 1-6" oder "PAR" und der Anzahl werden "PAR 1", "PAR 2", ..."""
    treffer = re.fullmatch(r"(.*?)\s*(\d+)\s*[-–]\s*\d+\s*", name)
    if treffer:
        basis, start = treffer.group(1), int(treffer.group(2))
    else:
        basis, start = name.strip(), 1
    if anzahl == 1 and not treffer:
        return [basis]
    return [f"{basis} {start + i}" for i in range(anzahl)]


class Patch:
    def __init__(self, pfad: Path, katalog: Katalog):
        self.pfad = Path(pfad)
        self.katalog = katalog
        inhalt = daten.lese_json(self.pfad, {"geraete": []})
        self.hinweis = inhalt.get("_hinweis")
        self.geraete = inhalt["geraete"]

    def speichern(self) -> None:
        inhalt = {"geraete": self.geraete}
        if self.hinweis:
            inhalt = {"_hinweis": self.hinweis, **inhalt}
        daten.schreibe_json(self.pfad, inhalt)

    def geraet(self, geraet_id: str) -> dict:
        for geraet in self.geraete:
            if geraet["id"] == geraet_id:
                return geraet
        raise PatchFehler(f"Gerät {geraet_id!r} ist nicht gepatcht.")

    def typ(self, geraet: dict):
        return self.katalog.typ(geraet["typ"])

    def kanalzahl(self, geraet: dict) -> int:
        return self.typ(geraet).kanalzahl(geraet["modus"])

    def in_gruppe(self, gruppe: str) -> list:
        return [g for g in self.geraete if gruppe in g.get("gruppen", [])]

    def gruppen(self) -> list:
        vorhanden = []
        for geraet in self.geraete:
            for gruppe in geraet.get("gruppen", []):
                if gruppe not in vorhanden:
                    vorhanden.append(gruppe)
        return vorhanden

    def belegung(self, ohne: Optional[str] = None) -> dict:
        """Kanal -> Liste der Geräte, die ihn benutzen."""
        kanaele = {}
        for geraet in self.geraete:
            if geraet["id"] == ohne:
                continue
            for kanal in range(geraet["adresse"], geraet["adresse"] + self.kanalzahl(geraet)):
                kanaele.setdefault(kanal, []).append(geraet["id"])
        return kanaele

    def probleme(self) -> list:
        """Findet Überschneidungen und alles, was über Kanal 512 hinausragt."""
        ergebnis = []
        paare = set()
        for kanal, geraete in sorted(self.belegung().items()):
            if len(geraete) > 1:
                paare.add(tuple(sorted(geraete)))
            if kanal > DMX_KANAELE:
                for geraet in geraete:
                    eintrag = {"art": "ueber_512", "geraete": [geraet],
                               "text": f"{geraet} ragt über Kanal {DMX_KANAELE} hinaus."}
                    if eintrag not in ergebnis:
                        ergebnis.append(eintrag)
        for paar in sorted(paare):
            ergebnis.append({"art": "ueberschneidung", "geraete": list(paar),
                             "text": f"Adressen überschneiden sich: {', '.join(paar)}."})
        return ergebnis

    def naechste_freie(self, kanalzahl: int, ab: int = 1) -> int:
        """Erste Adresse ab `ab`, an der `kanalzahl` Kanäle am Stück frei sind."""
        belegt = self.belegung()
        adresse = ab
        while adresse + kanalzahl - 1 <= DMX_KANAELE:
            frei = all(k not in belegt for k in range(adresse, adresse + kanalzahl))
            if frei:
                return adresse
            adresse += 1
        raise PatchFehler(f"Im Universum sind keine {kanalzahl} Kanäle am Stück mehr frei.")

    def _neue_id(self, name: str) -> str:
        basis = daten.dateiname(name)
        vorhanden = {g["id"] for g in self.geraete}
        kandidat, nummer = basis, 2
        while kandidat in vorhanden:
            kandidat, nummer = f"{basis}-{nummer}", nummer + 1
        return kandidat

    def hinzufuegen(self, typ_id: str, modus: str, anzahl: int, name: str,
                    start: Optional[int] = None, gruppen: Optional[list] = None) -> list:
        """Der Patch-Assistent. `start=None` heißt: nächste freie Adresse.

        Über 512 ist gesperrt. Eine Überschneidung wird nur gemeldet (probleme),
        denn zwei Geräte auf gleicher Adresse können auch gewollt sein.
        """
        if anzahl < 1:
            raise PatchFehler("Die Anzahl muss mindestens 1 sein.")
        typ = self.katalog.typ(typ_id)
        kanalzahl = typ.kanalzahl(modus)
        neue = []
        adresse = start
        for geraet_name in namen_erzeugen(name, anzahl):
            if start is None:
                adresse = self.naechste_freie(kanalzahl)
            if adresse < 1 or adresse + kanalzahl - 1 > DMX_KANAELE:
                self.geraete = [g for g in self.geraete if g not in neue]
                raise PatchFehler(f"{geraet_name}: Adresse {adresse} mit {kanalzahl} Kanälen "
                                  f"passt nicht in 1 bis {DMX_KANAELE}.")
            geraet = {"id": self._neue_id(geraet_name), "name": geraet_name, "typ": typ_id,
                      "modus": modus, "adresse": adresse, "gruppen": list(gruppen or [])}
            self.geraete.append(geraet)
            neue.append(geraet)
            adresse += kanalzahl
        return neue

    def aendern(self, geraet_id: str, **aenderungen) -> dict:
        """Ändert Name, Adresse, Modus oder Gruppen eines Geräts."""
        geraet = self.geraet(geraet_id)
        neu = {**geraet, **{k: v for k, v in aenderungen.items() if v is not None}}
        kanalzahl = self.katalog.typ(neu["typ"]).kanalzahl(neu["modus"])
        if neu["adresse"] < 1 or neu["adresse"] + kanalzahl - 1 > DMX_KANAELE:
            raise PatchFehler(f"Adresse {neu['adresse']} mit {kanalzahl} Kanälen "
                              f"passt nicht in 1 bis {DMX_KANAELE}.")
        geraet.update(neu)
        return geraet

    def tauschen(self, geraet_id: str, typ_id: str, modus: str) -> dict:
        """Tauscht das Modell. id, Gruppen und Ort bleiben, also laufen die Cues weiter."""
        return self.aendern(geraet_id, typ=typ_id, modus=modus)

    def entfernen(self, geraet_id: str) -> None:
        self.geraete.remove(self.geraet(geraet_id))

    def traverse_warnungen(self, buehne: Buehne) -> list:
        """Warnt, wenn die Traverse zu voll oder zu schwer wird."""
        am_traversen = [g for g in self.geraete
                        if (buehne.geraet(g["id"]) or {}).get("ort") == "traverse"]
        grenze = buehne.traverse
        warnungen = []
        if len(am_traversen) > grenze["max_geraete"]:
            warnungen.append(f"Die Traverse trägt höchstens {grenze['max_geraete']} Geräte, "
                             f"geplant sind {len(am_traversen)}.")
        gewicht, unbekannt = 0.0, []
        for geraet in am_traversen:
            kilo = self.typ(geraet).daten.get("physik", {}).get("gewicht_kg")
            if kilo is None:
                unbekannt.append(geraet["name"])
            else:
                gewicht += kilo
        if gewicht > grenze["max_gewicht_kg"]:
            warnungen.append(f"Die Traverse trägt höchstens {grenze['max_gewicht_kg']} kg, "
                             f"geplant sind {gewicht:.1f} kg.")
        if unbekannt:
            warnungen.append("Gewicht unbekannt, also nicht mitgezählt: " + ", ".join(unbekannt) + ".")
        return warnungen
