"""Das Lichtpult: Programmer, Effekte, Sequenzen und Executoren, angelehnt an grandMA.

    Programmer  Hier stellt man gerade etwas ein: Geräte wählen, Werte setzen,
                Effekte starten. Er liegt über allem außer den Not-Tasten.
                Im Blind-Modus sieht man ihn nur in der 3D-Vorschau.
    Cue         Ein gespeicherter Stand: Werte und Effekte, dazu eine Überblendzeit.
    Sequenz     Cues in fester Reihenfolge. Werte, die ein Cue nicht ändert,
                bleiben aus dem vorigen Cue stehen ("Tracking" wie bei grandMA).
    Executor    Ein Platz mit Fader und Tasten (Go+, Go-, Aus), auf dem eine
                Sequenz liegt. Der Fader blendet sie über die Automatik.

So sieht ein Cue in der Datei aus:
    {"name": "Rot dreht", "zeit_s": 2, "folgen_s": null,
     "werte": [{"gruppe": "Spots", "farbe": "rot", "helligkeit": 1, "gobo": "Gobo 3"}],
     "effekte": [{"art": "kreis", "ziel": {"gruppe": "Spots"}, "groesse": 0.6,
                  "tempo": "musik", "beats": 4, "verteilung": 0.5}]}

Gespeichert werden immer Eigenschaften, nie DMX-Zahlen.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from . import daten
from .cues import Sammlung
from .farben import farbe as lies_farbe, ist_farbe
from .pantilt import ZielAusserhalb
from .render import Eigenschaften, mischen
from .szenen import bereiche_von, loese_auf, pruefe_werte, zeige_auf

ANZAHL_EXECUTOREN = 8
EFFEKT_ARTEN = {
    "kreis": "Kreis", "acht": "Acht", "schwenk": "Schwenk links-rechts", "nicken": "Nicken vor-zurück",
    "publikum": "Über das Publikum", "dimmer_welle": "Dimmer-Welle", "dimmer_puls": "Puls auf dem Beat",
    "farbwechsel": "Farbwechsel",
}
BEWEGUNGS_ARTEN = {"kreis", "acht", "schwenk", "nicken", "publikum"}
RADIUS_M = 2.0           # Größe 1 heißt: 2 m um die Mitte
BODEN_HOEHE_M = 0.8      # die Effekte zielen auf den Bühnenboden


def effekt_sorte(art: str) -> str:
    if art in BEWEGUNGS_ARTEN:
        return "bewegung"
    return "farbe" if art == "farbwechsel" else "helligkeit"


# --- Prüfen ------------------------------------------------------------------

def pruefe_effekt(effekt: dict, gruppen: list, geraete: list) -> list:
    fehler = []
    if effekt.get("art") not in EFFEKT_ARTEN:
        fehler.append(f"Unbekannte Effekt-Art {effekt.get('art')!r}.")
    ziel = effekt.get("ziel", {})
    if "gruppe" in ziel and ziel["gruppe"] not in gruppen:
        fehler.append(f"Gruppe {ziel['gruppe']!r} gibt es nicht.")
    if "geraete" in ziel and not set(ziel["geraete"]) <= set(geraete):
        fehler.append("Ein Gerät im Effekt ist nicht gepatcht.")
    if "gruppe" not in ziel and not ziel.get("geraete"):
        fehler.append("Der Effekt braucht Geräte oder eine Gruppe.")
    for feld, unten, oben in (("groesse", 0, 1), ("verteilung", 0, 1), ("beats", 0.25, 64)):
        if feld in effekt and not (isinstance(effekt[feld], (int, float)) and unten <= effekt[feld] <= oben):
            fehler.append(f"{feld} muss zwischen {unten:g} und {oben:g} liegen.")
    tempo = effekt.get("tempo", "musik")
    if tempo != "musik" and not (isinstance(tempo, (int, float)) and 10 <= tempo <= 300):
        fehler.append('tempo ist "musik" oder 10 bis 300 BPM.')
    fehler += [f"Unbekannte Farbe: {f}." for f in effekt.get("farben", []) if not ist_farbe(str(f))]
    return fehler


def pruefe_cue(cue: dict, patch, positionen: dict) -> list:
    fehler = []
    if not str(cue.get("name", "")).strip():
        fehler.append("Der Cue braucht einen Namen.")
    if not cue.get("werte") and "effekte" not in cue:
        fehler.append("Der Cue ist leer.")
    gruppen, geraete = patch.gruppen(), [g["id"] for g in patch.geraete]
    fehler += pruefe_werte(cue.get("werte", []), gruppen, geraete, positionen)
    for effekt in cue.get("effekte", []):
        fehler += pruefe_effekt(effekt, gruppen, geraete)
    for feld in ("zeit_s", "folgen_s"):
        wert = cue.get(feld)
        if wert is not None and not (isinstance(wert, (int, float)) and wert >= 0):
            fehler.append(f"{feld} darf nicht negativ sein.")
    return fehler


def pruefe_sequenz(sequenz: dict, patch, positionen: dict) -> list:
    fehler = [] if str(sequenz.get("name", "")).strip() else ["Die Sequenz braucht einen Namen."]
    for nummer, cue in enumerate(sequenz.get("cues", []), start=1):
        fehler += [f"Cue {nummer}: {f}" for f in pruefe_cue(cue, patch, positionen)]
    return fehler


# --- Effekte -----------------------------------------------------------------

class Effekte:
    """Rechnet Effekte aus. Die Uhr läuft im Tempo der Musik oder in festen BPM."""

    def __init__(self, patch, buehne, positionen: dict):
        self.patch, self.buehne, self.positionen = patch, buehne, positionen
        self.musik_beats = 0.0          # gezählte Beats seit Start, läuft mit dem Musiktempo
        self.zeit = 0.0
        self.winkel = {}                # letzte Stellung pro Gerät, für kurze Wege

    def takt(self, dauer: float, musik_bpm: float) -> None:
        self.zeit += dauer
        self.musik_beats += dauer * musik_bpm / 60.0

    def geraete(self, effekt: dict) -> list:
        ziel = effekt.get("ziel", {})
        if "geraete" in ziel:
            return [g for g in self.patch.geraete if g["id"] in ziel["geraete"]]
        return self.patch.in_gruppe(ziel.get("gruppe", ""))

    def anwenden(self, effekt: dict, zustand: dict) -> dict:
        """Legt einen Effekt über den Zustand. Gibt den neuen Zustand zurück."""
        ergebnis = dict(zustand)
        geraete = self.geraete(effekt)
        tempo = effekt.get("tempo", "musik")
        beats = self.musik_beats if tempo == "musik" else self.zeit * tempo / 60.0
        runden = beats / effekt.get("beats", 4)
        for nummer, geraet in enumerate(geraete):
            versatz = effekt.get("verteilung", 0.0) * nummer / max(len(geraete), 1)
            phase = (runden + versatz) % 1.0
            e = ergebnis.get(geraet["id"], Eigenschaften(helligkeit=1.0))
            ergebnis[geraet["id"]] = self._wirkung(effekt, geraet, phase, e)
        return ergebnis

    def _wirkung(self, effekt: dict, geraet: dict, phase: float, e: Eigenschaften) -> Eigenschaften:
        art = effekt["art"]
        if art == "dimmer_welle":
            return e.kopie(helligkeit=e.helligkeit * (0.1 + 0.9 * (0.5 + 0.5 * math.sin(2 * math.pi * phase))))
        if art == "dimmer_puls":
            return e.kopie(helligkeit=e.helligkeit * math.exp(-phase * 5.0))
        if art == "farbwechsel":
            farben = effekt.get("farben") or ["rot", "blau"]
            return e.kopie(farbe=lies_farbe(farben[int(phase * len(farben)) % len(farben)]))
        if bereiche_von(self.patch, geraet) is None:
            return e
        try:
            pan, tilt = zeige_auf(geraet, self._punkt(effekt, phase), self.patch, self.buehne,
                                  self.winkel.get(geraet["id"]))
        except ZielAusserhalb:
            return e
        self.winkel[geraet["id"]] = (pan, tilt)
        return e.kopie(pan=pan, tilt=tilt)

    def _punkt(self, effekt: dict, phase: float) -> tuple:
        masse = self.buehne.daten["buehne"]
        mitte = effekt.get("mitte")
        if isinstance(mitte, dict):
            mx, my = mitte["x"], mitte["y"]
        elif mitte in self.positionen:
            mx, my = self.positionen[mitte]["x"], self.positionen[mitte]["y"]
        else:
            mx, my = 0.0, masse["tiefe_m"] / 2
        r = RADIUS_M * effekt.get("groesse", 0.5)
        w = 2 * math.pi * phase
        art = effekt["art"]
        if art == "kreis":
            return (mx + r * math.cos(w), my + r * math.sin(w) * 0.7, BODEN_HOEHE_M)
        if art == "acht":
            return (mx + r * math.sin(w), my + r * 0.5 * math.sin(2 * w), BODEN_HOEHE_M)
        if art == "schwenk":
            return (mx + 1.5 * r * math.sin(w), my, BODEN_HOEHE_M)
        if art == "nicken":
            return (mx, my + r * math.sin(w), BODEN_HOEHE_M)
        # Über das Publikum: deutlich über den Köpfen. Die Sperrzone prüft trotzdem jeden Wert.
        publikum = self.buehne.publikum
        hoehe = self.buehne.traverse["hoehe_m"] + 1.0
        return (2.0 * r * math.sin(w), (publikum["y_von_m"] + publikum["y_bis_m"]) / 2, hoehe)


# --- Programmer ----------------------------------------------------------------

class Programmer:
    def __init__(self):
        self.werte = {}        # Geräte-id -> {"helligkeit": 0.8, "farbe": "rot", ...}
        self.effekte = []
        self.blind = False

    def setzen(self, geraete: list, werte: dict) -> None:
        for geraet_id in geraete:
            eintrag = self.werte.setdefault(geraet_id, {})
            if "position" in werte or "punkt" in werte:
                # Eine neue Position ersetzt die alte und auch direkte Winkel.
                for alt in ("position", "punkt", "pan", "tilt"):
                    eintrag.pop(alt, None)
            if "pan" in werte or "tilt" in werte:
                eintrag.pop("position", None)
                eintrag.pop("punkt", None)
            eintrag.update(werte)

    def effekt_dazu(self, effekt: dict) -> None:
        """Ein neuer Effekt ersetzt den alten derselben Sorte auf denselben Geräten.

        Sorten: Bewegung, Helligkeit, Farbe. Ein Kopf kann nicht gleichzeitig
        einen Kreis und eine Acht fahren.
        """
        sorte = effekt_sorte(effekt["art"])
        self.effekte = [e for e in self.effekte
                        if not (effekt_sorte(e["art"]) == sorte and e.get("ziel") == effekt.get("ziel"))]
        self.effekte.append(effekt)

    def leeren(self) -> None:
        self.werte, self.effekte = {}, []

    def ist_leer(self) -> bool:
        return not self.werte and not self.effekte

    def als_cue(self, name: str, zeit_s: float = 2.0, folgen_s: Optional[float] = None) -> dict:
        werte = [{"geraet": geraet_id, **eintrag} for geraet_id, eintrag in self.werte.items() if eintrag]
        return {"name": name, "zeit_s": zeit_s, "folgen_s": folgen_s, "werte": werte,
                "effekte": [dict(e) for e in self.effekte]}

    def aus_cue(self, cue: dict, patch) -> None:
        """Holt einen Cue zum Ändern in den Programmer. Gruppen werden zu Geräten."""
        self.leeren()
        for wert in cue.get("werte", []):
            werte = {k: v for k, v in wert.items() if k not in ("gruppe", "geraet")}
            ids = [wert["geraet"]] if "geraet" in wert else [g["id"] for g in patch.in_gruppe(wert["gruppe"])]
            self.setzen(ids, werte)
        self.effekte = [dict(e) for e in cue.get("effekte", [])]

    def ausgabe(self, zustand: dict, patch, buehne, positionen: dict, effekte: Effekte) -> tuple:
        werte = [{"geraet": geraet_id, **eintrag} for geraet_id, eintrag in self.werte.items()]
        ergebnis, meldungen = loese_auf(werte, patch, buehne, positionen, zustand)
        for effekt in self.effekte:
            ergebnis = effekte.anwenden(effekt, ergebnis)
        return ergebnis, meldungen


# --- Sequenzen und Executoren ------------------------------------------------------

class Executor:
    """Spielt eine Sequenz. Go+ und Go- wie am echten Pult."""

    def __init__(self, nummer: int):
        self.nummer = nummer
        self.sequenz: Optional[dict] = None
        self.index = -1               # -1: noch kein Cue, also aus
        self.fader = 1.0
        self.start = 0.0
        self.vorher = {}              # Bild des Executors beim letzten Go, für die Überblendung
        self.zuletzt = {}             # das zuletzt ausgegebene Bild
        self.aus_seit: Optional[float] = None
        self.reihenfolge = 0          # wer zuletzt Go hatte, liegt oben
        self.zeitcode = False         # beim Nachspielen der Probe: Cues folgen der Aufnahme

    @property
    def aktiv(self) -> bool:
        return self.index >= 0 or self.aus_seit is not None

    def belegen(self, sequenz: Optional[dict]) -> None:
        self.sequenz, self.index, self.vorher, self.zuletzt, self.aus_seit = sequenz, -1, {}, {}, None
        self.zeitcode = False

    def go(self, jetzt: float, schritt: int = 1) -> bool:
        if not self.sequenz or not self.sequenz["cues"]:
            return False
        neu = self.index + schritt
        if neu >= len(self.sequenz["cues"]):
            neu = 0                   # nach dem letzten Cue geht es wieder von vorn los
        if neu < 0:
            return False
        self.vorher = dict(self.zuletzt)
        self.index, self.start, self.aus_seit = neu, jetzt, None
        return True

    def gehe_zu(self, index: int, jetzt: float) -> None:
        self.vorher = dict(self.zuletzt)
        self.index, self.start, self.aus_seit = index, jetzt, None

    def aus(self, jetzt: float) -> None:
        if self.index >= 0:
            self.vorher = dict(self.zuletzt)
            self.index, self.start, self.aus_seit = -1, jetzt, jetzt

    def cue(self) -> Optional[dict]:
        return self.sequenz["cues"][self.index] if self.sequenz and self.index >= 0 else None

    def tracking(self, patch, buehne, positionen: dict) -> tuple:
        """Alle Cues bis zum aktuellen übereinandergelegt: Was nicht neu ist, bleibt."""
        zustand, effekte, meldungen = {}, [], []
        for cue in self.sequenz["cues"][: self.index + 1]:
            zustand, neu = loese_auf(cue.get("werte", []), patch, buehne, positionen, zustand)
            meldungen = neu
            if "effekte" in cue:
                effekte = cue["effekte"]
        return zustand, effekte, meldungen


class Pult:
    def __init__(self, show, ordner: Path, belegung_pfad: Path):
        self.show = show
        self.sequenzen = Sammlung(ordner)
        self.belegung_pfad = Path(belegung_pfad)
        self.programmer = Programmer()
        self.auswahl = []              # gewählte Geräte, wie die gelbe Auswahl bei grandMA
        self.executoren = [Executor(n) for n in range(1, ANZAHL_EXECUTOREN + 1)]
        self.haupt = 0                 # dieser Executor hört auf die Leertaste
        self.zaehler = 0
        self.meldungen = []
        self.effekte = None
        self.letzte_zeit: Optional[float] = None
        belegung = daten.lese_json(self.belegung_pfad, {"executoren": []})["executoren"]
        for executor, name in zip(self.executoren, belegung):
            if name:
                executor.belegen(self.sequenzen.lesen(name))

    def aufbauen(self) -> None:
        self.effekte = Effekte(self.show.patch, self.show.buehne, self.show.positionen)

    def belegung_speichern(self) -> None:
        daten.schreibe_json(self.belegung_pfad, {"executoren": [
            e.sequenz["name"] if e.sequenz else None for e in self.executoren]})

    def executor(self, nummer: int) -> Executor:
        if not 1 <= nummer <= ANZAHL_EXECUTOREN:
            raise ValueError(f"Executor {nummer} gibt es nicht.")
        return self.executoren[nummer - 1]

    def go(self, nummer: int, jetzt: float, schritt: int = 1) -> None:
        executor = self.executor(nummer)
        self.haupt = nummer - 1
        if executor.go(jetzt, schritt):
            self.zaehler += 1
            executor.reihenfolge = self.zaehler

    def waehlen(self, geraete: list, art: str = "setzen") -> None:
        """art: setzen (nur diese), dazu, umschalten (an/aus) oder weg."""
        bekannt = [g["id"] for g in self.show.patch.geraete]
        geraete = [g for g in geraete if g in bekannt]
        if art == "setzen":
            self.auswahl = list(dict.fromkeys(geraete))
        elif art == "dazu":
            self.auswahl += [g for g in geraete if g not in self.auswahl]
        elif art == "weg":
            self.auswahl = [g for g in self.auswahl if g not in geraete]
        elif art == "umschalten":
            if geraete and all(g in self.auswahl for g in geraete):
                self.auswahl = [g for g in self.auswahl if g not in geraete]
            else:
                self.auswahl += [g for g in geraete if g not in self.auswahl]
        else:
            raise ValueError(f"Unbekannte Auswahl-Art {art!r}.")

    def goto(self, nummer: int, index: int, jetzt: float) -> None:
        """Direkt zu einem Cue springen, wie Goto am Pult."""
        executor = self.executor(nummer)
        if not executor.sequenz or not 0 <= index < len(executor.sequenz["cues"]):
            raise ValueError("Diesen Cue gibt es nicht.")
        executor.zeitcode = False
        executor.gehe_zu(index, jetzt)
        self.haupt = nummer - 1
        self.zaehler += 1
        executor.reihenfolge = self.zaehler

    def sequenz_speichern(self, sequenz: dict) -> None:
        fehler = pruefe_sequenz(sequenz, self.show.patch, self.show.positionen)
        if fehler:
            raise ValueError(" ".join(fehler))
        self.sequenzen.schreiben(sequenz)
        for executor in self.executoren:
            if executor.sequenz and executor.sequenz["name"] == sequenz["name"]:
                executor.sequenz = sequenz
                executor.index = min(executor.index, len(sequenz["cues"]) - 1)

    def cue_speichern(self, sequenz_name: str, name: str, zeit_s: float, folgen_s: Optional[float],
                      nummer: Optional[int] = None) -> dict:
        """Speichert den Programmer als Cue. Ohne Nummer kommt er ans Ende."""
        if self.programmer.ist_leer():
            raise ValueError("Der Programmer ist leer: erst Geräte wählen und Werte setzen.")
        sequenz = self.sequenzen.lesen(sequenz_name) or {"name": sequenz_name, "cues": []}
        cue = self.programmer.als_cue(name, zeit_s, folgen_s)
        if nummer is None:
            sequenz["cues"].append(cue)
        else:
            sequenz["cues"][nummer - 1] = cue
        self.sequenz_speichern(sequenz)
        return sequenz

    # --- Ein Bild ---------------------------------------------------------

    def anwenden(self, zustand: dict, jetzt: float, musik_bpm: float) -> dict:
        """Legt Executoren und Programmer über die Automatik."""
        dauer = 0.0 if self.letzte_zeit is None else max(0.0, jetzt - self.letzte_zeit)
        self.letzte_zeit = jetzt
        self.effekte.takt(dauer, musik_bpm)
        self.meldungen = []
        aktive = sorted((e for e in self.executoren if e.aktiv), key=lambda e: e.reihenfolge)
        for executor in aktive:
            zustand = self._executor(executor, zustand, jetzt)
        if not self.programmer.blind and not self.programmer.ist_leer():
            zustand, meldungen = self.programmer.ausgabe(zustand, *self._welt(), self.effekte)
            self.meldungen += meldungen
        return zustand

    def vorschau(self, zustand: dict) -> dict:
        """Was der Programmer zeigen würde. Für Blind und später für die KI."""
        ergebnis, _ = self.programmer.ausgabe(zustand, *self._welt(), self.effekte)
        return ergebnis

    def _welt(self) -> tuple:
        return self.show.patch, self.show.buehne, self.show.positionen

    def _zeitcode(self, executor: Executor, jetzt: float) -> None:
        """Probe ansehen: Der Cue richtet sich nach der Stelle in der Aufnahme."""
        stelle = self.show.audio.position_s()
        zeiten = executor.sequenz.get("zeitcode") if executor.sequenz else None
        if stelle is None or not zeiten:
            return
        ziel = max(i for i, z in enumerate(zeiten) if z <= stelle + 0.05)
        ziel = min(ziel, len(executor.sequenz["cues"]) - 1)     # falls im Pult Cues gelöscht wurden
        if ziel != executor.index:
            executor.gehe_zu(ziel, jetzt)

    def _executor(self, executor: Executor, zustand: dict, jetzt: float) -> dict:
        if executor.zeitcode:
            self._zeitcode(executor, jetzt)
        cue = executor.cue()
        if cue is not None:
            ziel, effekte, meldungen = executor.tracking(*self._welt())
            self.meldungen += meldungen
            for effekt in effekte:
                ziel = self.effekte.anwenden(effekt, ziel)
            zeit = cue.get("zeit_s") or 0.0
            folgen = cue.get("folgen_s")
            if folgen is not None and jetzt - executor.start >= zeit + folgen:
                self.go(executor.nummer, jetzt)
        else:
            ziel, zeit = {}, 0.0
            if executor.aus_seit is not None and jetzt - executor.aus_seit >= 1.0:
                executor.aus_seit, executor.vorher = None, {}
                return zustand
        anteil = 1.0 if zeit <= 0 else min(1.0, (jetzt - executor.start) / zeit)
        if cue is None:
            anteil = min(1.0, (jetzt - executor.aus_seit) / 1.0)
        bild = {}
        for geraet_id in set(ziel) | set(executor.vorher):
            alt = executor.vorher.get(geraet_id)
            neu = ziel.get(geraet_id)
            if neu is None:
                neu = alt.kopie(helligkeit=0.0)
            if alt is None:
                bild[geraet_id] = neu.kopie(helligkeit=neu.helligkeit * anteil)
            elif self._weg_gesperrt(geraet_id, alt, neu):
                # Kein weicher Schwenk durchs Publikum: direkt hinfahren und dort aufblenden.
                bild[geraet_id] = mischen(alt, neu, anteil).kopie(
                    pan=neu.pan, tilt=neu.tilt, helligkeit=neu.helligkeit * anteil)
            else:
                bild[geraet_id] = mischen(alt, neu, anteil)
        executor.zuletzt = bild
        ergebnis = dict(zustand)
        for geraet_id, e in bild.items():
            unten = ergebnis.get(geraet_id, Eigenschaften(farbe=e.farbe, pan=e.pan, tilt=e.tilt))
            gemischt = mischen(unten, e, executor.fader)
            ergebnis[geraet_id] = gemischt.kopie(gobo=e.gobo if executor.fader > 0.5 else unten.gobo,
                                                 gobo_drehung=e.gobo_drehung if executor.fader > 0.5 else unten.gobo_drehung,
                                                 strobo_hz=e.strobo_hz if executor.fader >= 1 else 0.0)
        return ergebnis

    def _weg_gesperrt(self, geraet_id: str, alt: Eigenschaften, neu: Eigenschaften) -> bool:
        if None in (alt.pan, alt.tilt, neu.pan, neu.tilt) or (alt.pan, alt.tilt) == (neu.pan, neu.tilt):
            return False
        pruefer = getattr(self.show, "pruefer", None)
        return pruefer is not None and not pruefer.weg_frei(geraet_id, (alt.pan, alt.tilt), (neu.pan, neu.tilt))

    def status(self) -> dict:
        return {
            "haupt": self.haupt + 1, "blind": self.programmer.blind, "auswahl": self.auswahl,
            "programmer": {"werte": self.programmer.werte, "effekte": self.programmer.effekte},
            "executoren": [{
                "nummer": e.nummer, "sequenz": e.sequenz["name"] if e.sequenz else None,
                "cues": [c["name"] for c in e.sequenz["cues"]] if e.sequenz else [],
                "index": e.index, "fader": e.fader} for e in self.executoren],
        }
