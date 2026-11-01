"""Szenen, Cues, Cuelisten und Fader.

    Szene     Datei in cues/szenen/, Werte siehe szenen.py
    Cue       eine Szene plus Einblendzeit, Ausblendzeit und Wartezeit
              Wartezeit 0 heißt: Der nächste Cue kommt erst mit "Weiter".
              Sonst geht es nach Einblenden plus Wartezeit von allein weiter.
    Cueliste  Datei in cues/listen/, Cues in fester Reihenfolge
    Fader     steuert eine Gerätegruppe (Helligkeit) oder eine Szene stufenlos
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import daten
from .render import Eigenschaften, mischen
from .szenen import loese_auf, pruefe_werte

ANZAHL_FADER = 8


class Sammlung:
    """Ein Ordner voller JSON-Dateien mit je einem Namen."""

    def __init__(self, ordner: Path):
        self.ordner = Path(ordner)

    def namen(self) -> list:
        return sorted(daten.lese_json(p)["name"] for p in self.ordner.glob("*.json"))

    def lesen(self, name: str) -> Optional[dict]:
        return daten.lese_json(self.ordner / f"{daten.dateiname(name)}.json")

    def schreiben(self, inhalt: dict) -> None:
        daten.schreibe_json(self.ordner / f"{daten.dateiname(inhalt['name'])}.json", inhalt)

    def loeschen(self, name: str) -> None:
        (self.ordner / f"{daten.dateiname(name)}.json").unlink(missing_ok=True)


def pruefe_szene(szene: dict, patch, positionen: dict) -> list:
    fehler = []
    if not str(szene.get("name", "")).strip():
        fehler.append("Die Szene braucht einen Namen.")
    if not szene.get("werte"):
        fehler.append("Die Szene ist leer.")
    else:
        fehler += pruefe_werte(szene["werte"], patch.gruppen(), [g["id"] for g in patch.geraete], positionen)
    return fehler


def pruefe_cueliste(liste: dict, szenen: Sammlung) -> list:
    fehler = []
    if not str(liste.get("name", "")).strip():
        fehler.append("Die Cueliste braucht einen Namen.")
    for nummer, cue in enumerate(liste.get("cues", []), start=1):
        if szenen.lesen(str(cue.get("szene", "?"))) is None:
            fehler.append(f"Cue {nummer}: Szene {cue.get('szene')!r} gibt es nicht.")
        for feld in ("einblenden_s", "ausblenden_s", "warten_s"):
            wert = cue.get(feld, 0)
            if not isinstance(wert, (int, float)) or isinstance(wert, bool) or wert < 0:
                fehler.append(f"Cue {nummer}: {feld} darf nicht negativ sein.")
    return fehler


class CueSpieler:
    """Spielt eine Cueliste ab und blendet dabei über."""

    def __init__(self, patch, buehne, positionen: dict, szenen: Sammlung):
        self.patch, self.buehne, self.positionen, self.szenen = patch, buehne, positionen, szenen
        self.liste: Optional[dict] = None
        self.index = -1
        self.cue: Optional[dict] = None
        self.ziel = {}              # was der aktuelle Cue setzt
        self.vorher = {}            # was davor zu sehen war
        self.start = 0.0
        self.aus_zeit = 0.0         # Ausblendzeit des vorigen Cues
        self.loslassen = None       # Zeitpunkt, ab dem die Cues ausgeblendet werden
        self.meldungen = []

    def laden(self, liste: dict) -> None:
        self.liste = liste
        self.index = -1
        self.cue = None
        self.ziel = {}
        self.vorher = {}
        self.loslassen = None

    def naechster_name(self) -> Optional[str]:
        if self.liste and self.index + 1 < len(self.liste["cues"]):
            return self.liste["cues"][self.index + 1]["name"]
        return None

    def weiter(self, jetzt: float) -> bool:
        """Startet den nächsten Cue. False, wenn die Liste zu Ende ist."""
        if not self.liste or self.index + 1 >= len(self.liste["cues"]):
            return False
        return self.gehe_zu(self.index + 1, jetzt)

    def gehe_zu(self, index: int, jetzt: float) -> bool:
        cue = self.liste["cues"][index]
        szene = self.szenen.lesen(cue["szene"])
        if szene is None:
            self.meldungen = [f"Szene {cue['szene']!r} gibt es nicht mehr."]
            return False
        self.vorher = self._momentan(jetzt)
        self.aus_zeit = self.cue.get("ausblenden_s", 0) if self.cue else cue.get("einblenden_s", 0)
        self.ziel, self.meldungen = loese_auf(szene["werte"], self.patch, self.buehne, self.positionen)
        self.index, self.cue, self.start, self.loslassen = index, cue, jetzt, None
        return True

    def stopp(self, jetzt: float) -> None:
        """Cue loslassen: Es blendet zurück zur Automatik."""
        if self.cue is not None and self.loslassen is None:
            self.vorher = self._momentan(jetzt)
            self.ziel = {}
            self.aus_zeit = self.cue.get("ausblenden_s", 0)
            self.loslassen = jetzt
            self.cue = None

    def _momentan(self, jetzt: float) -> dict:
        """Was die Cue-Ebene gerade zeigt: {id: (Eigenschaften, Deckkraft)}."""
        return {i: wert for i, wert in self._ebene(jetzt).items()}

    def _ebene(self, jetzt: float) -> dict:
        ein = max(self.cue.get("einblenden_s", 0), 0) if self.cue else 0
        anteil_ein = 1.0 if ein <= 0 else min(1.0, (jetzt - self.start) / ein)
        beginn = self.loslassen if self.loslassen is not None else self.start
        anteil_aus = 1.0 if self.aus_zeit <= 0 else min(1.0, (jetzt - beginn) / self.aus_zeit)
        ergebnis = {}
        for geraet_id in set(self.vorher) | set(self.ziel):
            alt = self.vorher.get(geraet_id)
            neu = self.ziel.get(geraet_id)
            if alt and neu:
                ergebnis[geraet_id] = (mischen(alt[0], neu, anteil_ein),
                                       alt[1] + (1.0 - alt[1]) * anteil_ein)
            elif neu:
                ergebnis[geraet_id] = (neu, anteil_ein)
            else:
                ergebnis[geraet_id] = (alt[0], alt[1] * (1.0 - anteil_aus))
        return {i: w for i, w in ergebnis.items() if w[1] > 0.0}

    def ueberlagern(self, zustand: dict, jetzt: float) -> dict:
        """Legt die Cue-Ebene über die Automatik."""
        if self.cue and self.cue.get("warten_s", 0) > 0:
            frist = self.cue.get("einblenden_s", 0) + self.cue["warten_s"]
            if jetzt - self.start >= frist:
                self.weiter(jetzt)
        ergebnis = dict(zustand)
        for geraet_id, (eigenschaften, deckung) in self._ebene(jetzt).items():
            unten = ergebnis.get(geraet_id, Eigenschaften(farbe=eigenschaften.farbe, pan=eigenschaften.pan,
                                                          tilt=eigenschaften.tilt))
            gemischt = mischen(unten, eigenschaften, deckung)
            # Strobo und Gobo werden nicht überblendet, sondern gelten ab dem Cue.
            ergebnis[geraet_id] = gemischt.kopie(strobo_hz=eigenschaften.strobo_hz if deckung >= 1 else 0.0)
        return ergebnis

    def status(self) -> dict:
        return {"liste": self.liste["name"] if self.liste else None,
                "cues": [c["name"] for c in self.liste["cues"]] if self.liste else [],
                "index": self.index, "aktiv": self.cue["name"] if self.cue else None,
                "naechster": self.naechster_name(), "meldungen": self.meldungen}


class FaderBank:
    """Acht Fader. Die Belegung steht in cues/fader.json, die Stellung nur im Speicher."""

    def __init__(self, pfad: Path):
        self.pfad = Path(pfad)
        self.belegung = daten.lese_json(self.pfad, {"fader": []})["fader"][:ANZAHL_FADER]
        self.belegung += [{"art": "frei"}] * (ANZAHL_FADER - len(self.belegung))
        self.werte = [1.0 if f["art"] == "gruppe" else 0.0 for f in self.belegung]

    def belegen(self, nummer: int, belegung: dict, szenen: Sammlung, gruppen: list) -> None:
        if not 0 <= nummer < ANZAHL_FADER:
            raise ValueError(f"Fader {nummer + 1} gibt es nicht.")
        art = belegung.get("art")
        if art == "gruppe" and belegung.get("ziel") not in gruppen:
            raise ValueError(f"Gruppe {belegung.get('ziel')!r} gibt es nicht.")
        if art == "szene" and szenen.lesen(str(belegung.get("ziel"))) is None:
            raise ValueError(f"Szene {belegung.get('ziel')!r} gibt es nicht.")
        if art not in ("gruppe", "szene", "frei"):
            raise ValueError("Ein Fader steuert eine Gruppe oder eine Szene.")
        self.belegung[nummer] = {"art": art, "ziel": belegung.get("ziel")} if art != "frei" else {"art": "frei"}
        self.werte[nummer] = 1.0 if art == "gruppe" else 0.0
        daten.schreibe_json(self.pfad, {"fader": self.belegung})

    def setze(self, nummer: int, wert: float) -> None:
        if not 0 <= nummer < ANZAHL_FADER:
            raise ValueError(f"Fader {nummer + 1} gibt es nicht.")
        self.werte[nummer] = max(0.0, min(1.0, float(wert)))

    def anwenden(self, zustand: dict, patch, buehne, positionen: dict, szenen: Sammlung) -> dict:
        ergebnis = dict(zustand)
        # Zuerst Szenen dazumischen, danach begrenzen die Gruppen-Fader alles.
        for fader, wert in zip(self.belegung, self.werte):
            if fader["art"] != "szene" or wert <= 0:
                continue
            szene = szenen.lesen(fader["ziel"])
            if szene is None:
                continue
            ziel, _ = loese_auf(szene["werte"], patch, buehne, positionen)
            for geraet_id, e in ziel.items():
                unten = ergebnis.get(geraet_id, Eigenschaften(farbe=e.farbe, pan=e.pan, tilt=e.tilt))
                ergebnis[geraet_id] = mischen(unten, e, wert).kopie(strobo_hz=unten.strobo_hz)
        for fader, wert in zip(self.belegung, self.werte):
            if fader["art"] != "gruppe":
                continue
            for geraet in patch.in_gruppe(fader["ziel"]):
                if geraet["id"] in ergebnis:
                    e = ergebnis[geraet["id"]]
                    ergebnis[geraet["id"]] = e.kopie(helligkeit=e.helligkeit * wert)
        return ergebnis

    def status(self) -> list:
        return [{**f, "wert": w} for f, w in zip(self.belegung, self.werte)]
