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

import copy
import math
from pathlib import Path
from typing import Optional

from . import daten, showtasten
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
    for feld, unten, oben in (("groesse", 0, 1), ("verteilung", 0, 1), ("beats", 0.25, 64), ("tiefe", 0, 1)):
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
        # Tempo-Fader: alle Effekte schneller oder langsamer (0,25- bis 4-mal).
        # "versatz" sorgt dafür, dass beim Schieben nichts springt.
        self.faktor = 1.0
        self.versatz = 0.0
        self.zeit_skaliert = 0.0

    def faktor_setzen(self, faktor: float) -> None:
        if faktor != self.faktor:
            self.versatz += self.musik_beats * (self.faktor - faktor)
            self.faktor = faktor

    def effekt_beats(self, tempo) -> float:
        """Wie viele Beats ein Effekt schon gelaufen ist (mit Tempo-Fader)."""
        if tempo == "musik":
            return self.musik_beats * self.faktor + self.versatz
        return self.zeit_skaliert * tempo / 60.0

    def takt(self, dauer: float, musik_bpm: float, beat: bool = False) -> None:
        self.zeit += dauer
        self.zeit_skaliert += dauer * self.faktor
        self.musik_beats += dauer * musik_bpm / 60.0
        if beat:
            # Einrasten: Die Effekt-Uhr wird sanft auf den gehörten Schlag gezogen,
            # so landet der Puls auf dem Beat statt irgendwo dazwischen.
            rest = self.musik_beats % 1.0
            fehler = rest if rest < 0.5 else rest - 1.0
            self.musik_beats -= 0.25 * fehler

    def auf_schlag(self) -> None:
        """Tap: Genau jetzt ist ein Schlag."""
        self.musik_beats = float(round(self.musik_beats))

    def geraete(self, effekt: dict) -> list:
        ziel = effekt.get("ziel", {})
        if "geraete" in ziel:
            return [g for g in self.patch.geraete if g["id"] in ziel["geraete"]]
        return self.patch.in_gruppe(ziel.get("gruppe", ""))

    def anwenden(self, effekt: dict, zustand: dict) -> dict:
        """Legt einen Effekt über den Zustand. Gibt den neuen Zustand zurück."""
        ergebnis = dict(zustand)
        geraete = self.geraete(effekt)
        runden = self.effekt_beats(effekt.get("tempo", "musik")) / effekt.get("beats", 4)
        for nummer, geraet in enumerate(geraete):
            versatz = effekt.get("verteilung", 0.0) * nummer / max(len(geraete), 1)
            phase = (runden + versatz) % 1.0
            e = ergebnis.get(geraet["id"], Eigenschaften(helligkeit=1.0))
            ergebnis[geraet["id"]] = self._wirkung(effekt, geraet, phase, e)
        return ergebnis

    def _wirkung(self, effekt: dict, geraet: dict, phase: float, e: Eigenschaften) -> Eigenschaften:
        art = effekt["art"]
        # "tiefe": wie weit das Licht zwischendurch heruntergeht. 1 = ganz aus, 0.5 = halb.
        if art == "dimmer_welle":
            tiefe = effekt.get("tiefe", 0.6)
            return e.kopie(helligkeit=e.helligkeit * (1.0 - tiefe * (0.5 - 0.5 * math.sin(2 * math.pi * phase))))
        if art == "dimmer_puls":
            tiefe = effekt.get("tiefe", 0.5)
            return e.kopie(helligkeit=e.helligkeit * (1.0 - tiefe * (1.0 - math.exp(-phase * 5.0))))
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

SEITEN = 4                      # Fader-Seiten, wie die Pages am Pult
PRO_SEITE = 10                  # Fader pro Seite
ANZAHL_EXECUTOREN = SEITEN * PRO_SEITE
SONG_NUMMER = 99                # eigener Platz für Song-Start: nimmt keinem Fader etwas weg
FLASH_MAX_S = 20.0              # eine hängende Flash-Taste geht von selbst aus
EXECUTOR_ARTEN = {"sequenz": "Sequenz", "gruppe": "Gruppen-Master", "tempo": "Tempo"}


def tempo_faktor(fader: float) -> float:
    """Tempo-Fader: ganz unten 0,25-mal, in der Mitte normal, ganz oben 4-mal so schnell."""
    if abs(fader - 0.5) < 0.03:
        return 1.0
    return 2.0 ** ((max(0.0, min(1.0, fader)) - 0.5) * 4.0)


class Executor:
    """Ein Platz mit Fader und Tasten. Darauf liegt eine Sequenz, ein Gruppen-Master oder der Tempo-Fader.

        Sequenz          Go+, Go-, Flash, Aus. Fader hoch startet sie, Fader ganz runter schaltet sie aus.
        Gruppen-Master   Der Fader regelt die Helligkeit einer Gruppe. Flash: Gruppe voll. Aus: Gruppe dunkel.
        Tempo            Der Fader macht alle Effekte langsamer oder schneller. Learn: im Takt tippen.
    """

    def __init__(self, nummer: int):
        self.nummer = nummer
        self.art: Optional[str] = None      # "sequenz", "gruppe", "tempo" oder None (frei)
        self.sequenz: Optional[dict] = None
        self.gruppe: Optional[str] = None
        self.label: Optional[str] = None
        self.index = -1               # -1: noch kein Cue, also aus
        self.fader = 1.0
        self.start = 0.0
        self.vorher = {}              # Bild des Executors beim letzten Go, für die Überblendung
        self.zuletzt = {}             # das zuletzt ausgegebene Bild
        self.aus_seit: Optional[float] = None
        self.reihenfolge = 0          # wer zuletzt Go hatte, liegt oben
        self.zeitcode = False         # beim Nachspielen der Probe: Cues folgen der Aufnahme
        self.flash_seit: Optional[float] = None
        self.flash_startete = False   # Flash hat die Sequenz eingeschaltet: Loslassen schaltet sie wieder aus
        self.sofort = False           # diese Überblendung ohne Zeit (Flash)
        self.stumm = False            # Gruppen-Master: Gruppe aus

    @property
    def aktiv(self) -> bool:
        return self.sequenz is not None and (self.index >= 0 or self.aus_seit is not None)

    def belegen(self, sequenz: Optional[dict]) -> None:
        self.sequenz, self.index, self.vorher, self.zuletzt, self.aus_seit = sequenz, -1, {}, {}, None
        self.art = "sequenz" if sequenz else None
        self.gruppe, self.label, self.zeitcode, self.stumm = None, None, False, False
        self.flash_seit, self.flash_startete, self.sofort = None, False, False

    def belegen_gruppe(self, gruppe: str) -> None:
        self.belegen(None)
        self.art, self.gruppe, self.fader = "gruppe", gruppe, 1.0

    def belegen_tempo(self) -> None:
        self.belegen(None)
        self.art, self.fader = "tempo", 0.5

    def eintrag(self) -> Optional[dict]:
        """So steht die Belegung in der Datei."""
        if self.art is None:
            return None
        eintrag = {"art": self.art, "fader": round(self.fader, 3)}
        if self.sequenz:
            eintrag["sequenz"] = self.sequenz["name"]
        if self.gruppe:
            eintrag["gruppe"] = self.gruppe
        if self.label:
            eintrag["label"] = self.label
        return eintrag

    def wirksam(self) -> float:
        """Der Fader, wie er gerade wirkt: Flash zählt als ganz oben."""
        return 1.0 if self.flash_seit is not None else self.fader

    def go(self, jetzt: float, schritt: int = 1) -> bool:
        if not self.sequenz or not self.sequenz["cues"]:
            return False
        neu = self.index + schritt
        if neu >= len(self.sequenz["cues"]):
            neu = 0                   # nach dem letzten Cue geht es wieder von vorn los
        if neu < 0:
            return False
        self.vorher = dict(self.zuletzt)
        self.index, self.start, self.aus_seit, self.sofort = neu, jetzt, None, False
        return True

    def gehe_zu(self, index: int, jetzt: float) -> None:
        self.vorher = dict(self.zuletzt)
        self.index, self.start, self.aus_seit, self.sofort = index, jetzt, None, False

    def aus(self, jetzt: float) -> None:
        if self.index >= 0:
            self.vorher = dict(self.zuletzt)
            self.index, self.start, self.aus_seit, self.sofort = -1, jetzt, jetzt, False

    def sofort_aus(self) -> None:
        """Ohne Ausblenden aus, zum Beispiel beim Loslassen von Flash."""
        self.index, self.aus_seit, self.vorher, self.zuletzt, self.sofort = -1, None, {}, {}, False

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
        self.song_platz = Executor(SONG_NUMMER)
        self.haupt = 0                 # dieser Executor hört auf die Leertaste
        self.seite = 1                 # welche Fader-Seite die Oberfläche zeigt
        self.grand = 1.0               # Grand Master: Helligkeit von allem
        self.highlight = False         # gewählte Geräte hell und weiß, zum Finden auf der Bühne
        self.oops = []                 # Rückgängig: Schritte mit dem Stand von vorher
        self._speichern_ab: Optional[float] = None
        self.zaehler = 0
        self.meldungen = []
        self.effekte = None
        self.letzte_zeit: Optional[float] = None
        # Show-Tasten: ein eigener Executor (nicht unter den acht), dazu Halten und Tap
        self.tasten = Executor(0)
        self.look: Optional[str] = None
        self.farbe_1, self.farbe_2 = "rot", "blau"
        self.halten = {art: None for art in showtasten.HALTEN}     # seit wann gedrückt
        self.tipps = []
        self.tempo_getippt: Optional[float] = None
        self.tempo_quelle = "ton"         # "ton": vom Mikrofon, "tap": getippt
        roh = daten.lese_json(self.belegung_pfad, {"executoren": []})
        self.grand = max(0.0, min(1.0, float(roh.get("grand", 1.0))))
        self._eintraege_anwenden(roh.get("executoren", []))

    def _eintraege_anwenden(self, eintraege: list) -> None:
        """Belegung aus der Datei (oder aus dem Rückgängig-Stapel) auf die Fader legen."""
        for executor, eintrag in zip(self.executoren, list(eintraege) + [None] * len(self.executoren)):
            if isinstance(eintrag, str):          # ältere Versionen speicherten nur den Namen
                eintrag = {"art": "sequenz", "sequenz": eintrag}
            if not isinstance(eintrag, dict):
                executor.belegen(None)
                continue
            art = eintrag.get("art")
            sequenz = self.sequenzen.lesen(eintrag.get("sequenz") or "") if art == "sequenz" else None
            if art == "sequenz" and sequenz is not None:
                if not (executor.sequenz and executor.sequenz["name"] == sequenz["name"]):
                    executor.belegen(sequenz)
            elif art == "gruppe" and eintrag.get("gruppe"):
                if executor.art != "gruppe" or executor.gruppe != eintrag["gruppe"]:
                    executor.belegen_gruppe(eintrag["gruppe"])
            elif art == "tempo":
                if executor.art != "tempo":
                    executor.belegen_tempo()
            else:
                executor.belegen(None)
                continue
            executor.label = eintrag.get("label")
            if isinstance(eintrag.get("fader"), (int, float)):
                executor.fader = max(0.0, min(1.0, float(eintrag["fader"])))
        self._tempo_anwenden()

    def aufbauen(self) -> None:
        self.effekte = Effekte(self.show.patch, self.show.buehne, self.show.positionen)
        self._tempo_anwenden()

    def belegung_speichern(self) -> None:
        self._speichern_ab = None
        daten.schreibe_json(self.belegung_pfad, {"executoren": [e.eintrag() for e in self.executoren],
                                                 "grand": round(self.grand, 3)})

    def executor(self, nummer: int) -> Executor:
        if nummer == SONG_NUMMER:
            return self.song_platz
        if not 1 <= nummer <= ANZAHL_EXECUTOREN:
            raise ValueError(f"Fader {nummer} gibt es nicht (1 bis {ANZAHL_EXECUTOREN}).")
        return self.executoren[nummer - 1]

    # --- Fader und ihre Tasten ----------------------------------------------

    def go(self, nummer: int, jetzt: float, schritt: int = 1) -> None:
        executor = self.executor(nummer)
        if executor.art == "gruppe":
            executor.stumm = False if schritt > 0 else executor.stumm
            return
        if executor.art == "tempo":
            if schritt > 0:
                self.tap(jetzt)
            return
        if executor.sequenz is None:
            raise ValueError(f"Auf Fader {nummer} liegt nichts. Erst eine Sequenz zuweisen (Assign) oder speichern (Store).")
        self.haupt = nummer - 1
        song = getattr(self.show, "song", None)
        if executor.zeitcode == "song" and song is not None and song.laeuft_auf(nummer):
            # Im Song-Modus heißt Go+: nächster Teil jetzt. Go-: Teil zurück.
            song.teil_vor() if schritt > 0 else song.teil_zurueck()
            self.nach_oben(executor, jetzt, umschalten=False)
            return
        if executor.go(jetzt, schritt):
            self.nach_oben(executor, jetzt, umschalten=False)

    def nach_oben(self, executor: Executor, jetzt: float, umschalten: bool = True) -> None:
        """Dieser Executor liegt jetzt oben (wie "zuletzt gedrückt" am Pult)."""
        if umschalten and executor.index < 0:
            executor.go(jetzt)
        self.zaehler += 1
        executor.reihenfolge = self.zaehler

    def aus(self, nummer: int, jetzt: float) -> None:
        executor = self.executor(nummer)
        if executor.art == "gruppe":
            executor.stumm = not executor.stumm          # Aus-Taste beim Gruppen-Master: dunkel und wieder an
        elif executor.art == "tempo":
            self.fader_setzen(nummer, 0.5, jetzt)        # Tempo wieder normal
        else:
            executor.aus(jetzt)

    def fader_setzen(self, nummer: int, wert: float, jetzt: float) -> None:
        """Fader schieben. Bei Sequenzen wie am Pult: hoch startet, ganz runter schaltet aus."""
        executor = self.executor(nummer)
        alt, executor.fader = executor.fader, max(0.0, min(1.0, float(wert)))
        if executor.art == "sequenz" and executor.zeitcode is False:
            if alt <= 0.0 < executor.fader and executor.index < 0:
                if executor.go(jetzt):
                    self.haupt = nummer - 1
                    self.nach_oben(executor, jetzt, umschalten=False)
            elif executor.fader <= 0.0 < alt and executor.index >= 0:
                executor.aus(jetzt)
        if executor.art == "tempo":
            self._tempo_anwenden()
        self._speichern_ab = jetzt + 1.5      # nicht bei jeder Bewegung auf die Platte schreiben

    def flash(self, nummer: int, an: bool, jetzt: float) -> None:
        """Flash: solange gedrückt, steht der Fader ganz oben (bei Gruppen: Gruppe voll)."""
        executor = self.executor(nummer)
        if executor.art == "tempo":
            if an:
                self.tap(jetzt)
            return
        if executor.art is None:
            raise ValueError(f"Auf Fader {nummer} liegt nichts.")
        if not an:
            self._flash_loslassen(executor)
            return
        if executor.flash_seit is not None:
            return
        executor.flash_seit = jetzt
        if executor.art == "sequenz":
            if executor.index < 0 and executor.go(jetzt):
                executor.flash_startete, executor.sofort = True, True
            self.nach_oben(executor, jetzt, umschalten=False)

    def _flash_loslassen(self, executor: Executor) -> None:
        executor.flash_seit = None
        if executor.flash_startete:
            executor.flash_startete = False
            executor.sofort_aus()

    def grand_setzen(self, wert: float, jetzt: float) -> None:
        self.grand = max(0.0, min(1.0, float(wert)))
        self._speichern_ab = jetzt + 1.5

    def seite_setzen(self, seite: int) -> None:
        self.seite = max(1, min(SEITEN, int(seite)))

    def _tempo_anwenden(self) -> None:
        if self.effekte is None:
            return
        tempo = next((e for e in self.executoren if e.art == "tempo"), None)
        self.effekte.faktor_setzen(tempo_faktor(tempo.fader) if tempo else 1.0)

    # --- Zuweisen, Speichern, Update, Label, Löschen (wie Assign/Store/Update am Pult) ---

    def zuweisen(self, nummer: int, art: Optional[str], ziel: Optional[str] = None, zusammen: bool = False) -> None:
        """Legt etwas auf einen Fader. art None macht ihn frei. zusammen: ein Oops-Schritt mit dem vorigen."""
        executor = self.executor(nummer)
        if executor is self.song_platz:
            raise ValueError("Der Song-Platz wird nur über Song-Start belegt.")
        sequenz = None
        if art == "sequenz":
            sequenz = self.sequenzen.lesen(str(ziel or ""))
            if sequenz is None:
                raise ValueError(f"Sequenz „{ziel}“ gibt es nicht.")
        elif art == "gruppe":
            if ziel not in self.show.patch.gruppen():
                raise ValueError(f"Gruppe „{ziel}“ gibt es nicht. Es gibt: {', '.join(self.show.patch.gruppen())}.")
        elif art not in ("tempo", None):
            raise ValueError(f"Unbekannte Fader-Art {art!r}.")
        self.merke_belegung(zusammen=zusammen)
        if art == "sequenz":
            executor.belegen(sequenz)
        elif art == "gruppe":
            executor.belegen_gruppe(ziel)
        elif art == "tempo":
            for andere in self.executoren:          # es gibt nur einen Tempo-Fader
                if andere.art == "tempo":
                    andere.belegen(None)
            executor.belegen_tempo()
        else:
            executor.belegen(None)
        self._tempo_anwenden()
        self.belegung_speichern()

    def label_setzen(self, nummer: int, text: str) -> None:
        executor = self.executor(nummer)
        if executor.art is None:
            raise ValueError(f"Auf Fader {nummer} liegt nichts.")
        self.merke_belegung()
        executor.label = str(text).strip()[:24] or None
        self.belegung_speichern()

    def neuer_sequenzname(self, basis: str = "Sequenz") -> str:
        namen = set(self.sequenzen.namen())
        nummer = 1
        while f"{basis} {nummer}" in namen:
            nummer += 1
        return f"{basis} {nummer}"

    def speichern_auf(self, nummer: int, cue_name: Optional[str] = None, zeit_s: float = 2.0) -> dict:
        """Store auf einen Fader: Programmer als neuer Cue. Leerer Fader bekommt eine neue Sequenz."""
        executor = self.executor(nummer)
        if executor.art in ("gruppe", "tempo"):
            raise ValueError(f"Auf Fader {nummer} liegt ein {EXECUTOR_ARTEN[executor.art]}. Erst löschen (Delete).")
        if self.programmer.ist_leer():
            raise ValueError("Der Programmer ist leer: erst Geräte wählen und Werte setzen.")
        name = executor.sequenz["name"] if executor.sequenz else self.neuer_sequenzname()
        anzahl = len(executor.sequenz["cues"]) if executor.sequenz else 0
        sequenz = self.cue_speichern(name, cue_name or f"Cue {anzahl + 1}", zeit_s, None)
        if executor.sequenz is None:
            self.merke_belegung(zusammen=True)
            executor.belegen(sequenz)
            self.belegung_speichern()
        return sequenz

    def aktualisieren(self, nummer: int) -> dict:
        """Update: Programmer in den gerade laufenden Cue dieses Faders einarbeiten."""
        executor = self.executor(nummer)
        if executor.sequenz is None or executor.index < 0:
            raise ValueError("Update geht nur auf einen laufenden Cue: erst Go drücken.")
        if self.programmer.ist_leer():
            raise ValueError("Der Programmer ist leer: erst Werte setzen, dann Update.")
        sequenz = copy.deepcopy(self.sequenzen.lesen(executor.sequenz["name"]) or executor.sequenz)
        cue = sequenz["cues"][executor.index]
        neu = self.programmer.als_cue(cue["name"])
        werte = [dict(w) for w in cue.get("werte", [])]
        for wert in neu["werte"]:
            vorhanden = next((w for w in werte if w.get("geraet") == wert["geraet"]), None)
            if vorhanden is None:
                werte.append(dict(wert))
                continue
            if any(k in wert for k in ("position", "punkt", "pan", "tilt")):
                for alt in ("position", "punkt", "pan", "tilt"):
                    vorhanden.pop(alt, None)
            vorhanden.update(wert)
        cue["werte"] = werte
        if neu["effekte"]:
            effekte = [dict(e) for e in cue.get("effekte", [])]
            for effekt in neu["effekte"]:
                sorte = effekt_sorte(effekt["art"])
                effekte = [e for e in effekte if not (effekt_sorte(e["art"]) == sorte and e.get("ziel") == effekt.get("ziel"))]
                effekte.append(effekt)
            cue["effekte"] = effekte
        self.sequenz_speichern(sequenz)
        return sequenz

    def _sequenz_mit_cue(self, name: str, nummer: int) -> dict:
        sequenz = self.sequenzen.lesen(name)
        if sequenz is None:
            raise ValueError(f"Sequenz „{name}“ gibt es nicht.")
        if not 1 <= nummer <= len(sequenz["cues"]):
            raise ValueError(f"Cue {nummer} gibt es in „{name}“ nicht.")
        return copy.deepcopy(sequenz)

    def cue_aendern(self, name: str, nummer: int, felder: dict) -> dict:
        """Name, Überblendzeit und Folgen-Zeit eines Cues ändern (wie im Sequence Sheet)."""
        sequenz = self._sequenz_mit_cue(name, nummer)
        cue = sequenz["cues"][nummer - 1]
        if "name" in felder:
            cue["name"] = str(felder["name"]).strip()[:60] or cue["name"]
        if "zeit_s" in felder:
            cue["zeit_s"] = max(0.0, min(600.0, float(felder["zeit_s"])))
        if "folgen_s" in felder:
            wert = felder["folgen_s"]
            cue["folgen_s"] = None if wert in (None, "") else max(0.0, min(600.0, float(wert)))
        self.sequenz_speichern(sequenz)
        return sequenz

    def cue_loeschen(self, name: str, nummer: int) -> dict:
        sequenz = self._sequenz_mit_cue(name, nummer)
        if sequenz.get("zeitcode"):
            raise ValueError("Diese Sequenz gehört zu einem Song. Cues dort nicht löschen, sondern in der Probe „Show neu bauen“.")
        del sequenz["cues"][nummer - 1]
        if not sequenz["cues"]:
            raise ValueError("Der letzte Cue bleibt. Ganze Sequenz löschen geht im Sequenzen-Pool.")
        self.sequenz_speichern(sequenz)
        return sequenz

    def cue_verschieben(self, name: str, nummer: int, richtung: int) -> dict:
        sequenz = self._sequenz_mit_cue(name, nummer)
        ziel = nummer - 1 + (1 if richtung > 0 else -1)
        if not 0 <= ziel < len(sequenz["cues"]):
            return sequenz
        cues = sequenz["cues"]
        cues[nummer - 1], cues[ziel] = cues[ziel], cues[nummer - 1]
        self.sequenz_speichern(sequenz)
        return sequenz

    def sequenz_loeschen(self, name: str) -> None:
        if self.sequenzen.lesen(name) is None:
            raise ValueError(f"Sequenz „{name}“ gibt es nicht.")
        self.merke_sequenz(name)
        self.merke_belegung(zusammen=True)
        for executor in self.executoren:
            if executor.sequenz and executor.sequenz["name"] == name:
                executor.belegen(None)
        self.sequenzen.loeschen(name)
        self.belegung_speichern()

    # --- Oops: Rückgängig -------------------------------------------------------

    def _merken(self, eintrag: tuple, zusammen: bool) -> None:
        if zusammen and self.oops:
            self.oops[-1].append(eintrag)
        else:
            self.oops.append([eintrag])
        del self.oops[:-50]

    def merke_sequenz(self, name: str, zusammen: bool = False) -> None:
        self._merken(("sequenz", name, copy.deepcopy(self.sequenzen.lesen(name))), zusammen)

    def merke_belegung(self, zusammen: bool = False) -> None:
        self._merken(("belegung", [e.eintrag() for e in self.executoren], self.grand), zusammen)

    def merke_programmer(self, zusammen: bool = False) -> None:
        self._merken(("programmer", copy.deepcopy(self.programmer.werte), copy.deepcopy(self.programmer.effekte),
                      list(self.auswahl)), zusammen)

    def rueckgaengig(self) -> str:
        """Oops: Macht den letzten Schritt rückgängig (Speichern, Löschen, Zuweisen, Programmer)."""
        if not self.oops:
            raise ValueError("Es gibt nichts zum Rückgängigmachen.")
        texte = []
        for eintrag in reversed(self.oops.pop()):
            if eintrag[0] == "sequenz":
                _, name, alt = eintrag
                if alt is None:
                    self.sequenzen.loeschen(name)
                    for executor in self.executoren:
                        if executor.sequenz and executor.sequenz["name"] == name:
                            executor.belegen(None)
                    self.belegung_speichern()
                else:
                    self.sequenzen.schreiben(alt)
                    self._sequenz_auffrischen(alt)
                texte.append(f"Sequenz {name}")
            elif eintrag[0] == "belegung":
                _, eintraege, grand = eintrag
                self._eintraege_anwenden(eintraege)
                self.grand = grand
                self.belegung_speichern()
                texte.append("Fader-Belegung")
            elif eintrag[0] == "programmer":
                _, werte, effekte, auswahl = eintrag
                self.programmer.werte, self.programmer.effekte, self.auswahl = werte, effekte, auswahl
                texte.append("Programmer")
        return "Rückgängig: " + ", ".join(dict.fromkeys(texte))

    # --- Show-Tasten ------------------------------------------------------

    def look_druecken(self, look_id: str, jetzt: float) -> None:
        gobos = self.show.gobos_der_gruppe("Spots") if "Spots" in self.show.patch.gruppen() else []
        welt = (self.show.patch, self.farbe_1, self.farbe_2, gobos, self.show.positionen)
        cues = showtasten.drop_folge(*welt) if look_id == "drop" else [showtasten.look_bauen(look_id, *welt)]
        self.tasten.sequenz = {"name": "Show-Tasten", "cues": cues}
        self.tasten.gehe_zu(0, jetzt)
        self.look = look_id
        self.nach_oben(self.tasten, jetzt, umschalten=False)

    def look_aus(self, jetzt: float) -> None:
        self.tasten.aus(jetzt)
        self.look = None

    def farben_setzen(self, farbe_1: Optional[str], farbe_2: Optional[str], jetzt: float) -> None:
        for farbe in (farbe_1, farbe_2):
            if farbe is not None and not showtasten.ist_farbe(farbe):
                raise ValueError(f"Unbekannte Farbe {farbe!r}.")
        self.farbe_1 = farbe_1 or self.farbe_1
        self.farbe_2 = farbe_2 or self.farbe_2
        if self.look and self.look != "drop" and self.tasten.index >= 0:
            # Der laufende Look nimmt die neue Farbe gleich mit (weich überblendet)
            reihenfolge = self.tasten.reihenfolge
            self.look_druecken(self.look, jetzt)
            self.tasten.reihenfolge = reihenfolge

    def halten_setzen(self, art: str, an: bool, jetzt: float) -> None:
        if art not in self.halten:
            raise ValueError(f"Unbekannte Halte-Taste {art!r}.")
        self.halten[art] = jetzt if an else None

    def tap(self, jetzt: float) -> Optional[float]:
        if self.tipps and jetzt - self.tipps[-1] > 2.0:
            self.tipps = []                  # nach einer Pause beginnt das Tippen neu
        self.tipps = (self.tipps + [jetzt])[-8:]
        tempo = showtasten.tap_tempo(self.tipps)
        if tempo:
            self.tempo_getippt, self.tempo_quelle = tempo, "tap"
        if self.effekte is not None:
            self.effekte.auf_schlag()
        return tempo

    def _halten_jetzt(self, jetzt: float) -> dict:
        for art, seit in self.halten.items():
            if seit is not None and jetzt - seit > showtasten.HALTEN_MAX_S:
                self.halten[art] = None
        return {art: seit is not None for art, seit in self.halten.items()}

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
        song = getattr(self.show, "song", None)
        if executor.zeitcode == "song" and song is not None and song.laeuft_auf(nummer):
            song.zu_cue(index)               # der Song läuft von dort aus weiter
            return
        executor.zeitcode = False
        executor.gehe_zu(index, jetzt)
        self.haupt = nummer - 1
        self.zaehler += 1
        executor.reihenfolge = self.zaehler

    def sequenz_speichern(self, sequenz: dict, merken: bool = True) -> None:
        fehler = pruefe_sequenz(sequenz, self.show.patch, self.show.positionen)
        if fehler:
            raise ValueError(" ".join(fehler))
        if merken:
            self.merke_sequenz(sequenz["name"])
        self.sequenzen.schreiben(sequenz)
        self._sequenz_auffrischen(sequenz)

    def _sequenz_auffrischen(self, sequenz: dict) -> None:
        """Fader mit dieser Sequenz bekommen den neuen Stand."""
        for executor in self.executoren + [self.song_platz]:
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

    def anwenden(self, zustand: dict, jetzt: float, musik_bpm: float, beat: bool = False) -> dict:
        """Legt Executoren, Show-Tasten, Programmer, Gruppen-Master, Halte-Tasten und Grand Master
        über die Automatik."""
        dauer = 0.0 if self.letzte_zeit is None else max(0.0, jetzt - self.letzte_zeit)
        self.letzte_zeit = jetzt
        self.effekte.takt(dauer, musik_bpm, beat)
        self.meldungen = []
        for executor in self.executoren:
            if executor.flash_seit is not None and jetzt - executor.flash_seit > FLASH_MAX_S:
                self._flash_loslassen(executor)        # hängende Flash-Taste
        aktive = sorted((e for e in self.executoren + [self.song_platz, self.tasten] if e.aktiv),
                        key=lambda e: e.reihenfolge)
        for executor in aktive:
            zustand = self._executor(executor, zustand, jetzt)
        if not self.programmer.blind:
            if not self.programmer.ist_leer():
                zustand, meldungen = self.programmer.ausgabe(zustand, *self._welt(), self.effekte)
                self.meldungen += meldungen
            zustand = self._hervorheben(zustand)
        zustand = self._gruppen_master(zustand)
        grenzen = getattr(self.show, "grenzen", None)
        strobo_hz = min(3.0, grenzen.strobo_max_hz) if grenzen is not None else 3.0
        zustand = showtasten.halten_anwenden(zustand, self._halten_jetzt(jetzt), self.show.patch, strobo_hz)
        if self.grand < 1.0:
            zustand = {i: e.kopie(helligkeit=e.helligkeit * self.grand) for i, e in zustand.items()}
        if self._speichern_ab is not None and jetzt >= self._speichern_ab:
            try:
                self.belegung_speichern()
            except OSError:
                self._speichern_ab = jetzt + 5.0
        return zustand

    def _hervorheben(self, zustand: dict) -> dict:
        """Highlight: Die gewählten Geräte leuchten hell und weiß."""
        if not self.highlight or not self.auswahl:
            return zustand
        ergebnis = dict(zustand)
        for geraet_id in self.auswahl:
            alt = ergebnis.get(geraet_id, Eigenschaften())
            ergebnis[geraet_id] = alt.kopie(helligkeit=1.0, farbe=(1.0, 1.0, 1.0), gobo="Offen",
                                            gobo_drehung=0.0, strobo_hz=0.0)
        return ergebnis

    def _gruppen_master(self, zustand: dict) -> dict:
        master = [e for e in self.executoren if e.art == "gruppe" and e.gruppe]
        if not master:
            return zustand
        ergebnis = dict(zustand)
        for executor in master:
            for geraet in self.show.patch.in_gruppe(executor.gruppe):
                alt = ergebnis.get(geraet["id"])
                if executor.flash_seit is not None:
                    alt = alt or Eigenschaften(farbe=(1.0, 1.0, 1.0))
                    ergebnis[geraet["id"]] = alt.kopie(helligkeit=1.0)
                elif alt is not None:
                    stufe = 0.0 if executor.stumm else executor.fader
                    ergebnis[geraet["id"]] = alt.kopie(helligkeit=alt.helligkeit * stufe)
        return ergebnis

    def vorschau(self, zustand: dict) -> dict:
        """Was der Programmer zeigen würde. Für Blind und später für die KI."""
        ergebnis, _ = self.programmer.ausgabe(zustand, *self._welt(), self.effekte)
        return self._hervorheben(ergebnis)

    def _welt(self) -> tuple:
        return self.show.patch, self.show.buehne, self.show.positionen

    def _zeitcode(self, executor: Executor, jetzt: float, stelle: Optional[float] = None) -> None:
        """Probe ansehen und Song-Start: Der Cue richtet sich nach der Stelle im Song."""
        stelle = self.show.audio.position_s() if stelle is None else stelle
        zeiten = executor.sequenz.get("zeitcode") if executor.sequenz else None
        if stelle is None or not zeiten:
            return
        ziel = max((i for i, z in enumerate(zeiten) if z <= stelle + 0.05), default=0)
        ziel = min(ziel, len(executor.sequenz["cues"]) - 1)     # falls im Pult Cues gelöscht wurden
        if ziel != executor.index:
            executor.gehe_zu(ziel, jetzt)

    def _executor(self, executor: Executor, zustand: dict, jetzt: float) -> dict:
        if executor.zeitcode == "song":
            song = getattr(self.show, "song", None)
            stelle = song.stelle(jetzt) if song is not None and song.laeuft_auf(executor.nummer) else None
            if stelle is not None:
                self._zeitcode(executor, jetzt, stelle)
        elif executor.zeitcode:
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
                if executor is self.tasten:
                    executor.go(jetzt)          # Show-Tasten: zum Beispiel vom weißen Schlag in den Drop
                else:
                    self.go(executor.nummer, jetzt)
        else:
            ziel, zeit = {}, 0.0
            if executor.aus_seit is not None and jetzt - executor.aus_seit >= 1.0:
                executor.aus_seit, executor.vorher = None, {}
                return zustand
        anteil = 1.0 if zeit <= 0 or executor.sofort else min(1.0, (jetzt - executor.start) / zeit)
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
        fader = executor.wirksam()
        ergebnis = dict(zustand)
        for geraet_id, e in bild.items():
            unten = ergebnis.get(geraet_id, Eigenschaften(farbe=e.farbe, pan=e.pan, tilt=e.tilt))
            gemischt = mischen(unten, e, fader)
            ergebnis[geraet_id] = gemischt.kopie(gobo=e.gobo if fader > 0.5 else unten.gobo,
                                                 gobo_drehung=e.gobo_drehung if fader > 0.5 else unten.gobo_drehung,
                                                 strobo_hz=e.strobo_hz if fader >= 1 else 0.0)
        return ergebnis

    def _weg_gesperrt(self, geraet_id: str, alt: Eigenschaften, neu: Eigenschaften) -> bool:
        if None in (alt.pan, alt.tilt, neu.pan, neu.tilt) or (alt.pan, alt.tilt) == (neu.pan, neu.tilt):
            return False
        pruefer = getattr(self.show, "pruefer", None)
        return pruefer is not None and not pruefer.weg_frei(geraet_id, (alt.pan, alt.tilt), (neu.pan, neu.tilt))

    def anzeigename(self, executor: Executor) -> str:
        if executor.label:
            return executor.label
        if executor.sequenz:
            return executor.sequenz["name"]
        if executor.art == "gruppe":
            return executor.gruppe or ""
        return "Tempo" if executor.art == "tempo" else ""

    def executor_info(self, executor: Executor) -> dict:
        """Was die Fader-Leiste über einen Fader wissen muss (ohne die ganze Cue-Liste)."""
        cues = executor.sequenz["cues"] if executor.sequenz else []
        info = {"nummer": executor.nummer, "art": executor.art, "name": self.anzeigename(executor),
                "label": executor.label, "sequenz": executor.sequenz["name"] if executor.sequenz else None,
                "gruppe": executor.gruppe, "index": executor.index, "anzahl": len(cues),
                "fader": round(executor.fader, 3), "flash": executor.flash_seit is not None,
                "stumm": executor.stumm, "song": executor.zeitcode == "song"}
        if 0 <= executor.index < len(cues):
            info["cue"] = cues[executor.index]["name"]
        if cues:
            info["naechster"] = cues[executor.index + 1 if executor.index + 1 < len(cues) else 0]["name"]
        if executor.art == "tempo":
            info["faktor"] = round(tempo_faktor(executor.fader), 2)
        return info

    def status(self) -> dict:
        try:
            haupt = self.executor(self.haupt + 1)
        except ValueError:
            haupt = self.executoren[0]
        return {
            "haupt": self.haupt + 1, "blind": self.programmer.blind, "auswahl": self.auswahl,
            "programmer": {"werte": self.programmer.werte, "effekte": self.programmer.effekte},
            "executoren": [self.executor_info(e) for e in self.executoren],
            "song_platz": self.executor_info(self.song_platz),
            "haupt_info": self.executor_info(haupt),
            "haupt_cues": [c["name"] for c in haupt.sequenz["cues"]] if haupt.sequenz else [],
            "seite": self.seite, "seiten": SEITEN, "pro_seite": PRO_SEITE,
            "grand": round(self.grand, 3), "highlight": self.highlight, "oops": len(self.oops),
            "effekt_tempo": round(self.effekte.faktor, 2) if self.effekte else 1.0,
            "tasten": {"look": self.look if self.tasten.index >= 0 else None, "farbe_1": self.farbe_1,
                       "farbe_2": self.farbe_2, "halten": {a: s is not None for a, s in self.halten.items()},
                       "tempo_quelle": self.tempo_quelle,
                       "tempo_getippt": round(self.tempo_getippt, 1) if self.tempo_getippt else None},
        }
