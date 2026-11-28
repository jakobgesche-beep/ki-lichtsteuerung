"""Die Musik-Engine: macht aus der Musik ein Licht, wie es ein Operator fahren würde.

Sie arbeitet mit Looks. Ein Look ist ein festes Bild: Farbe, Gobo, Stand oder
Bewegung und eine Art, im Beat zu pulsieren. So entsteht Ruhe statt Dauerwechsel:

    Ein Look bleibt mindestens eine Phrase stehen (16 Beats).
    Er wechselt, wenn die Musik stärker oder ruhiger wird, oder nach 32 Beats.
    Ein Drop (plötzlich viel mehr Energie) wechselt sofort, mit einem Akzent.
    Ein großer Schlag der Band (Crash, gemeinsamer Schlag) gibt einen Akzent, ohne den Look zu wechseln.
    Leise Stellen und Rede gehen auf das ruhige Grundlicht.

Was im Look passiert:
    Puls       Dimmer geht im Beat auf und zu (bei schnellen Songs auf 1 und 3). Akzent auf der Eins.
    Farbe      Jeder Song bekommt zwei Farben (A und B) und behält sie bis zur nächsten Pause. Ein Look zeigt
               eine davon oder beide (Spots B über PARs A); manche tauschen sie zu Beginn jeder 8-Takt-Phrase.
    Bewegung   nur in manchen Looks, dann langsam und weich (eine Runde dauert mindestens 4 Sekunden).
               Sonst steht das Licht.

Wechsel kommen auf der Eins: Kennt der Takt-Folger die Eins, wechselt ein Look nur zu Beginn einer
8-Takt-Phrase (gezählt ab dem ersten Takt des Songs), sonst nach Beats gezählt.

Drops sind ein eigenes Ereignis (die Analyse prüft: erst Aufbau, dann Bass-Einschlag):
    Aufbau     Strahlen sammeln sich in der Mitte, das Licht wird heller und weißer,
               der Puls wird stärker.
    Pause      kurz vor dem Drop fast dunkel.
    Drop       ein weißer Schlag, dann kräftige Farben, jeder Bass-Schlag ein harter
               Lichtschlag, große schnelle Bewegung, drehende Gobos, 32 Beats lang.

Wie stark alles wirkt, sagt das Profil. Die Engine spricht nur die Gruppen
"Farb-PARs" und "Spots" an. Sie läuft komplett lokal und braucht kein Internet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .farben import farbe as lies_farbe, farbpaar
from .audio.analyse import Messwerte
from .pantilt import ZielAusserhalb
from .render import Eigenschaften, mischen
from .szenen import bereiche_von, loese_auf, zeige_auf

GRUPPE_FARBE = "Farb-PARs"
GRUPPE_BEWEGUNG = "Spots"
GRUPPE_STROBO = "Strobo"
STANDARD_TEMPO = 120.0
PULS_ABKLANG = 0.45      # wie schnell der Lichtpuls ausklingt, in Beats
AKZENT_ABKLANG = 1.2     # der Akzent ("doppelt hell") klingt langsamer aus
FARB_BLENDE_S = 0.25     # Überblendung der LED-Farben
WINKEL_GLAETTUNG_S = 0.25 # so weich laufen Pan und Tilt, auch beim Look-Wechsel
MAX_GRAD_PRO_S = 220     # schneller folgt auch ein echter Kopf nicht sauber
PHRASE = 16              # so viele Beats bleibt ein Look mindestens stehen
ABWECHSLUNG = 32         # spätestens dann kommt ein neuer Look derselben Stärke (ruhige Teile)
ABWECHSLUNG_STARK = 16   # in starken Teilen schneller
BEATS_BEWEGUNG = 16      # ein Bewegungs-Durchlauf, bei "langsam" doppelt so lang
STUFEN = (0.35, 0.6, 0.8) # Energie-Grenzen zwischen ruhig, mittel, stark, Höhepunkt
HYSTERESE = 0.08         # damit es an einer Grenze nicht hin und her springt
DROP = 0.25              # so viel Energie mehr als zuletzt gilt als Drop
DROP_BEATS = 32         # so lange hält das Drop-Bild
DROP_WEISS_S = 0.25      # erst ein kurzer weißer Schlag
DROP_BEWEGUNG_BEATS = 4  # eine Runde der Drop-Bewegung, schnell
AUFBAU_AB = 0.3          # ab dieser Spannung zeigt das Licht den Aufbau
STROBO_ENERGIE = 0.92
STROBO_NACH_S = 2.0
ERSATZ_HELLIGKEIT = 0.5
UEBERGANG_S = 1.5        # so lange dauert der Wechsel zwischen Musik und Grundlicht
ZIEL_HOEHE_M = 0.8       # die Spots zielen auf den Bühnenboden
PHRASE_TAKTE = 8         # eine Phrase: 8 Takte (mit bekannter Eins)
ABWECHSLUNG_TAKTE = 16   # ruhige Teile: frühestens nach 2 Phrasen ein neuer Look derselben Stärke
ABWECHSLUNG_TAKTE_STARK = 8
NEUER_SONG_S = 3.0       # so lange Pause (leise, Rede, Applaus), dann gilt die nächste Musik als neuer Song
MIN_RUNDE_S = 4.0        # eine Bewegungs-Runde dauert mindestens so lange (schnelle Songs: doppelt so viele Beats)
SCHNELL_BPM = 140        # ab hier pulst das Licht nur auf 1 und 3
MIN_RUNDE_HOEHEPUNKT_S = 2.0   # im Höhepunkt darf es schneller gehen
TREFFER_BODEN = 0.62     # starke Looks: von hier aus springt das Licht auf jedem Treffer hoch. Unter 0,4 Sprung
                         # zählt es nicht als Blitz, so hält der Blitz-Wächter das Licht bei einem Wirbel nicht dunkel.
TREFFER_ABKLANG_S = 0.12
WEISS_ABKLANG_S = 0.15   # großer Schlag (Becken): kurz weiß
STAERKE_HALTEN_S = 6.0   # so lange hält die Stärke nach (ein kurzer Break macht das Licht nicht gleich ruhig;
                         # 2.5.2: vorher 3 s, da sprang die Stärke zwischen zwei Schlägen über die Höhepunkt-Grenze)
SPRUNG = 0.2             # so viel stärker als einen Takt vorher: Ein neuer Songteil hat begonnen (Refrain)
RHYTHMUS_TREFFER = 2.0   # so viele Treffer pro Sekunde (mit Takt): Das ist nie "Ruhe", mindestens Stufe 1
ERSTER_LOOK_S = 0.5      # so lange nach dem ersten Schlag eines Songs wird der erste Look gewählt
ERSTER_LOOK_SPAETESTENS_S = 1.5   # Musik ganz ohne Schläge (Fläche, Orgel): spätestens dann
# KI-Regie (regie.py): Claude sagt, was los ist und welcher Look passt; die Engine wechselt im Takt.
REGIE_GUELTIG_S = 20.0   # so lange gilt eine Entscheidung, dann macht die Engine wieder allein weiter
REGIE_SPAETESTENS_S = 8.0   # kommt keine Phrase (Eins unbekannt), wechselt der Look spätestens dann auf einem Beat
REGIE_RUHIG = ("ansage", "applaus", "stille")
REGIE_LEISE = ("ruhige_musik", "ansage", "applaus", "stille")   # dabei endet ein (vermutlich falscher) Drop
REGIE_KRAEFTIG = ("refrain", "hoehepunkt", "solo", "schlagzeug_solo", "drop", "aufbau")
REGIE_RUHIG_GUELTIG_S = 8.0   # "Ansage/Applaus/Stille" gilt kürzer: Fängt die Musik an, fragt die Regie sofort neu
LAGE_NAMEN = {"ruhige_musik": "ruhige Musik", "strophe": "Strophe", "refrain": "Refrain", "hoehepunkt": "Höhepunkt",
              "solo": "Solo", "schlagzeug_solo": "Schlagzeug-Solo", "break": "Break", "aufbau": "Aufbau",
              "drop": "Drop", "ansage": "Ansage", "applaus": "Applaus", "stille": "Stille", "unklar": "unklar"}


@dataclass(frozen=True)
class Look:
    name: str
    stufe: int                       # 0 ruhig, 1 mittel, 2 stark, 3 Höhepunkt
    bewegung: Optional[str] = None   # None: das Licht steht
    beats: int = 16                  # Beats für eine Runde der Bewegung
    farben: str = "eine"             # eine, zwei (fest verteilt), wechsel (pro Phrase), lauf (3 Farben wandern)
    gobo: bool = False
    drehung: float = 0.0
    puls: str = "beat"               # atmen, beat, akzent (Takt-Eins doppelt hell)
    schub: bool = False              # kleiner Ruck auf jedem Beat


# 2.5.2: In mittleren Teilen standen die Köpfe meist still (gemessen: Pop-Song, Bewegung im Median 0 °/s). Jetzt
# bewegen sich auch ruhige und mittlere Looks, nur langsam; „Stehen“ bleibt als Ruhepunkt. Starke Teile bekommen
# Acht und Gegenlauf, der Höhepunkt Ballyhoo und Farb-Lauf.
LOOKS = (
    Look("Ruhe", 0, puls="atmen"),
    Look("Ruhe schwenkt", 0, bewegung="schwenk", beats=32, puls="atmen", gobo=True),
    Look("Ruhe kreist", 0, bewegung="kreis", beats=32, puls="atmen", farben="zwei"),
    Look("Stehen", 1, gobo=True),
    Look("Sanfter Schwenk", 1, bewegung="schwenk", beats=16, farben="zwei"),
    Look("Farbwechsel", 1, bewegung="kreis", beats=32, farben="wechsel", gobo=True),
    Look("Langsame Acht", 1, bewegung="acht", beats=32, farben="zwei", gobo=True),
    Look("Wippen", 1, bewegung="nicken", beats=16),
    Look("Schwenk", 2, bewegung="schwenk", beats=8, gobo=True, drehung=0.3, schub=True),
    Look("Kreuz", 2, bewegung="kreuz", beats=8, farben="zwei", gobo=True, drehung=0.3),
    Look("Nicken", 2, bewegung="nicken", beats=4, farben="wechsel", schub=True),
    Look("Stehen mit Akzent", 2, farben="wechsel", gobo=True, puls="akzent"),
    Look("Acht", 2, bewegung="acht", beats=8, farben="zwei", gobo=True, drehung=0.4),
    Look("Gegenlauf", 2, bewegung="gegenkreis", beats=8, farben="wechsel", gobo=True, drehung=0.3, puls="akzent"),
    Look("Kreis", 3, bewegung="kreis", beats=8, farben="wechsel", gobo=True, drehung=0.5, puls="akzent"),
    Look("Fächer", 3, bewegung="faecher", beats=4, farben="zwei", gobo=True, drehung=0.6, puls="akzent", schub=True),
    Look("Höhepunkt", 3, bewegung="kreuz", beats=4, farben="wechsel", gobo=True, drehung=0.8, puls="akzent", schub=True),
    Look("Ballyhoo", 3, bewegung="ballyhoo", beats=4, farben="lauf", gobo=True, drehung=0.8, puls="akzent", schub=True),
    Look("Farb-Lauf", 3, bewegung="acht", beats=8, farben="lauf", gobo=True, drehung=0.5, puls="akzent"),
)
ABSCHNITT_FENSTER_BEATS = 8  # so lange nach dem Becken am Anfang eines Teils darf der Look noch auf der Eins wechseln


class Engine:
    def __init__(self, patch, buehne, positionen: dict, grenzen):
        self.patch = patch
        self.buehne = buehne
        self.positionen = positionen
        self.grenzen = grenzen
        self.beats = 0
        self.letzter_beat = -99.0
        self.letzter_akzent = -99.0
        self.phase = 0.0                # zählt Beats weich mit, für die Bewegung
        self.stufe = 0
        self.energie_langsam = 0.0
        self.look = LOOKS[0]
        self.look_seit = 0              # bei welchem Beat der Look begann
        self.look_nummer = 0            # zählt Looks, daraus kommen Farben und Gobos
        self.drop_zeit = -99.0
        self.schub = 0.0
        self.drop_beat = -999
        self.dauer = 0.0
        self.led_farbe = {}
        self.gobo_listen = {}
        self.musik_anteil = 0.0     # 0 = Grundlicht, 1 = volle Musik-Regeln
        self.letzte_zeit: Optional[float] = None
        self.laut_seit: Optional[float] = None
        self.winkel = {}
        self.grund_kopie = {}
        self.zustand_text = "Grundlicht"
        # Song und Takt
        self.song_nummer = -1
        self.farben_paar: Optional[tuple] = None   # (A, B) des laufenden Songs
        self.farbe_drei = "weiss"                  # dritte Farbe für den Farb-Lauf
        self.abschnitt_beat = -999                 # Beat, an dem ein neuer Songteil erkannt wurde (Becken, Sprung)
        self.abschnitt_takt = 0
        self.staerke_vor_takt = 0.0                # Stärke auf der letzten Eins (für den Sprung)
        self.hoeher_beats = 0                      # so viele Beats ist die Musik schon stärker als der Look
        self.im_stopp = False                      # die Band hat eben schlagartig aufgehört (Licht aus)
        self.pause_seit: Optional[float] = None
        self.takte = 0                  # gezählte Takt-Einsen im Song
        self.eins_bekannt = False       # hat der Takt-Folger schon eine Eins gemeldet?
        self.letzte_eins_beat = 0       # bei welchem Beat die letzte Eins war
        self.phrase_nummer = 0          # 8-Takt-Phrasen im Song
        self.pulse = 0                  # gezählte Lichtpulse (die Lampen wechseln sich ab)
        self.phrase_basis = 0           # ab diesem Takt werden die 8-Takt-Phrasen gezählt
        self.schlag_beat = -99          # bei welchem Beat der letzte große Schlag (Becken) kam
        self.tempo = STANDARD_TEMPO
        self.letzter_puls = -99.0
        self.letzter_treffer = -99.0
        self.treffer_zahl = 0
        self.staerke_gehalten = 0.0
        self.treffer_rate = 0.0         # Treffer pro Sekunde, über etwa 3 s gemittelt
        self.look_offen = True          # der erste Look des Songs ist noch nicht gewählt
        self.erste_regung: Optional[float] = None   # erster Schlag oder Treffer des Songs
        self.musik_seit: Optional[float] = None     # seit wann Musik kommt (für den ersten Look ohne Schläge)
        self.regie: Optional[dict] = None           # letzte Entscheidung der KI-Regie (siehe regie.py)

    # --- KI-Regie -------------------------------------------------------------

    def regie_setzen(self, entscheidung: dict, jetzt: float) -> None:
        """Claude hat entschieden. Angewendet wird es im Takt (in _look_waehlen), nicht sofort."""
        look = next((l for l in LOOKS if l.name == entscheidung.get("look")), None)
        self.regie = {**entscheidung, "look_obj": look, "zeit": jetzt, "angewendet": False}

    def _regie(self, jetzt: float) -> Optional[dict]:
        if self.regie is not None and jetzt - self.regie["zeit"] > REGIE_GUELTIG_S:
            self.regie = None                       # zu alt: Die Engine macht wieder allein weiter
        return self.regie

    def _regie_anwenden(self, regie: dict, m: Messwerte, profil: dict, jetzt: float, eigene: int) -> None:
        """Claudes Look kommt auf der Eins (Anfang einer Phrase), bei "jetzt" auf dem nächsten Beat.
        Solange die Entscheidung gilt, wechselt die Engine nicht von selbst (außer beim Drop).

        Grenzen (eigene = Stufe, die die Engine selbst aus der Stärke der Musik hört):
            Ist die Musik kräftig (Stufe 2 oder 3), wird das Licht nie schwächer als die Engine es fahren würde.
            Höchstens eine Stufe kräftiger als die Engine (eine Rede, die Claude für Musik hält, bleibt ruhig).
            Wird die Musik deutlich lauter als Claudes Look, übernimmt die Engine bis zur nächsten Antwort."""
        if regie["angewendet"]:
            if eigene >= 2 and self.look.stufe < eigene:
                regie["look_obj"] = None            # lauter geworden: Die Engine wechselt selbst
            return
        look = regie["look_obj"] or self.look
        ziel = min(max(look.stufe, eigene if eigene >= 2 else 0), eigene + 1)
        if ziel != look.stufe:
            kandidaten = [l for l in self._passende_looks(ziel, profil) if l != self.look] or \
                self._passende_looks(ziel, profil)
            gleich = [l for l in kandidaten if (l.bewegung is None) == (look.bewegung is None)]
            look = (gleich or kandidaten or [self.look])[0]
        erlaubt = self._passende_looks(look.stufe, profil)
        if look not in erlaubt:                     # das Profil verbietet ihn (zum Beispiel Bewegung aus)
            look = erlaubt[0] if erlaubt else self.look
        if regie["wechsel"] == "bleiben" or look == self.look:
            regie["angewendet"] = True
            if regie.get("farben") and self.look_offen:
                self.farben_paar = tuple(regie["farben"])
            return
        seit = self.beats - self.look_seit
        if regie["wechsel"] == "jetzt" or self.look_offen:
            jetzt_wechseln = m.beat
        elif self.eins_bekannt:
            jetzt_wechseln = self._phrase_beginnt(m) or (m.beat and m.eins and jetzt - regie["zeit"] >= REGIE_SPAETESTENS_S)
        else:
            jetzt_wechseln = m.beat and (seit % 8 == 0 or jetzt - regie["zeit"] >= REGIE_SPAETESTENS_S)
        if not jetzt_wechseln:
            return
        self.look = look
        self.look_nummer += 1
        self.look_seit = self.beats
        self.stufe = look.stufe
        self.look_offen = False
        if regie.get("farben"):
            self.farben_paar = tuple(regie["farben"])
        if look.stufe >= 2:
            self.letzter_akzent = jetzt             # der neue starke Look kommt mit einem hellen Akzent
        regie["angewendet"] = True

    def bewerte(self, messwerte: Optional[Messwerte], profil: dict, jetzt: float,
                pause: bool = False) -> dict:
        """Das Ergebnis pro Bild: {Geräte-id: Eigenschaften}."""
        dauer = 0.0 if self.letzte_zeit is None else jetzt - self.letzte_zeit
        self.letzte_zeit = jetzt
        self.dauer = dauer

        grund, _ = loese_auf(profil["grundlicht"]["werte"], self.patch, self.buehne, self.positionen)
        if not any(e.helligkeit > 0 for e in grund.values()):
            grund = self._ersatz_grundlicht()
        grund = {i: e.kopie(helligkeit=min(e.helligkeit, profil["max_helligkeit"])) for i, e in grund.items()}

        if messwerte is not None:
            tempo = messwerte.tempo_bpm if 40.0 <= messwerte.tempo_bpm <= 240.0 else STANDARD_TEMPO
            self.phase += dauer * tempo / 60.0
            self._song_pruefen(messwerte, profil, jetzt)
            if messwerte.beat:
                self.beats += 1
                self.letzter_beat = jetzt
                if messwerte.eins:
                    self._eins_zaehlen()
                im_takt = (self.beats - self.letzte_eins_beat) % 4 if self.eins_bekannt else self.beats % 4
                if tempo <= SCHNELL_BPM or im_takt % 2 == 0:
                    self.pulse += 1
                    self.letzter_puls = jetzt
            if messwerte.drop and profil["beat_reaktion"] >= 0.5 and not pause:
                self.drop_zeit, self.drop_beat = jetzt, self.beats
                self.musik_anteil = 1.0          # der Drop kommt sofort voll, ohne Überblenden
            elif messwerte.schlag and profil["beat_reaktion"] >= 0.5 and not pause and self.stufe >= 1:
                self.letzter_akzent = jetzt      # großer Schlag der Band: kurz doppelt hell, dann klingt es ab
            if messwerte.schlag:
                self.schlag_beat = self.beats
            if messwerte.treffer:
                self.letzter_treffer = jetzt
                self.treffer_zahl += 1
            if (messwerte.beat or messwerte.treffer) and self.erste_regung is None and not (
                    messwerte.leise or messwerte.rede or messwerte.applaus):
                self.erste_regung = jetzt
            if dauer > 0:
                self.treffer_rate += ((1.0 / dauer if messwerte.treffer else 0.0) - self.treffer_rate) * min(1.0, dauer / 3.0)
        ruhig = (messwerte is None or pause or profil["beat_reaktion"] <= 0
                 or messwerte.leise or messwerte.rede)
        regie = None if pause else self._regie(jetzt)
        if (regie is not None and messwerte is not None and profil["beat_reaktion"] > 0
                and regie["lage"] in REGIE_RUHIG and jetzt - regie["zeit"] <= REGIE_RUHIG_GUELTIG_S
                and (messwerte.intensitaet if messwerte.intensitaet > 0 else messwerte.energie) < STUFEN[1]):
            # Claude hört eine Ansage, Applaus oder Stille: ruhiges Grundlicht, aber nur, wenn es nicht gerade
            # kräftig ist. Kräftiger als die eigene Erkennung (zum Beispiel trotz erkannter Rede) macht die Regie nie.
            # Getestet (2.4.0): Claude hielt eine Ansage für ein Solo und ein Schlagzeug-Solo für eine Strophe,
            # weil er nur Zahlen sieht.
            ruhig = True
        self._text_setzen(messwerte, pause, profil, regie, ruhig)   # Aufbau, Pause und Drop setzen ihn danach neu
        schritt = dauer / UEBERGANG_S
        self.musik_anteil = max(0.0, min(1.0, self.musik_anteil + (-schritt if ruhig else schritt)))
        # Fällt die Analyse aus, soll das nicht mitten im Blitz stehen bleiben.
        if self.musik_anteil <= 0.0 or messwerte is None:
            self.musik_anteil = 0.0 if messwerte is None else self.musik_anteil
            return grund

        musik = self._musik(messwerte, profil, jetzt)
        ergebnis = dict(grund)
        for geraet_id, eigenschaften in musik.items():
            ausgang = grund.get(geraet_id, Eigenschaften(farbe=eigenschaften.farbe,
                                                         pan=eigenschaften.pan, tilt=eigenschaften.tilt))
            ergebnis[geraet_id] = mischen(ausgang, eigenschaften, self.musik_anteil)
        return ergebnis

    def _song_pruefen(self, m: Messwerte, profil: dict, jetzt: float) -> None:
        """Nach einer Pause beginnt ein neuer Song: nächstes Farbpaar, Takte neu zählen."""
        pause = m.leise or m.rede or m.applaus
        if pause:
            self.pause_seit = jetzt if self.pause_seit is None else self.pause_seit
            return
        neu = self.farben_paar is None or (self.pause_seit is not None and jetzt - self.pause_seit >= NEUER_SONG_S)
        self.pause_seit = None
        palette = profil.get("palette") or ["blau", "rot"]
        if neu:
            self.song_nummer += 1
            self.eins_bekannt, self.takte, self.phrase_nummer, self.phrase_basis = False, 0, 0, 0
            if self.song_nummer > 0:
                self.look_offen, self.erste_regung = True, None
            self.musik_seit = jetzt
        if neu or not all(f in palette for f in self.farben_paar):
            tempo = m.tempo_bpm if 40.0 <= m.tempo_bpm <= 240.0 else STANDARD_TEMPO
            self.farben_paar = farbpaar(palette, tempo, nummer=max(0, self.song_nummer))
            rest = [f for f in palette if f not in self.farben_paar]
            self.farbe_drei = rest[max(0, self.song_nummer) % len(rest)] if rest else self.farben_paar[0]

    def _eins_zaehlen(self) -> None:
        self.eins_bekannt = True
        self.takte += 1
        self.letzte_eins_beat = self.beats
        if self.takte - 1 > self.phrase_basis and (self.takte - 1 - self.phrase_basis) % PHRASE_TAKTE == 0:
            self.phrase_nummer += 1

    def _phrase_beginnt(self, m: Messwerte) -> bool:
        """Beginnt mit diesem Beat eine neue 8-Takt-Phrase?"""
        return bool(m.beat and m.eins and self.eins_bekannt
                    and (self.takte - 1 - self.phrase_basis) % PHRASE_TAKTE == 0)

    def _abschnitt_beginnt(self, m: Messwerte) -> bool:
        """Ein großer Schlag (Becken) auf der Eins: Hier beginnt oft ein neuer Songteil, zum Beispiel der Refrain."""
        return bool(self.eins_bekannt and m.beat and self.beats - self.letzte_eins_beat <= 1
                    and self.beats - self.schlag_beat <= 1)

    def _ersatz_grundlicht(self) -> dict:
        """Passt das Grundlicht zu keinem gepatchten Gerät, darf die Bühne nicht dunkel bleiben."""
        warm = lies_farbe("warmweiss")
        ergebnis = {}
        for geraet in self.patch.geraete:
            e = Eigenschaften(helligkeit=ERSATZ_HELLIGKEIT, farbe=warm)
            self._ruhelage(geraet, e)
            ergebnis[geraet["id"]] = e
        return ergebnis

    def _text_setzen(self, messwerte, pause, profil, regie: Optional[dict] = None, ruhig: bool = False) -> None:
        lage = LAGE_NAMEN.get(regie["lage"], regie["lage"]) if regie else None
        if pause:
            self.zustand_text = "Automatik pausiert: Grundlicht"
        elif messwerte is None:
            self.zustand_text = "Kein Ton: Grundlicht"
        elif profil["beat_reaktion"] <= 0:
            self.zustand_text = "Profil ohne Automatik: Grundlicht"
        elif ruhig and regie is not None and regie["lage"] in REGIE_RUHIG:
            self.zustand_text = f"KI-Regie hört {lage}: Grundlicht"
        elif ruhig and messwerte.leise:
            self.zustand_text = "Leise Stelle: Grundlicht"
        elif ruhig and messwerte.rede:
            self.zustand_text = "Rede erkannt: Grundlicht"
        else:
            self.zustand_text = f"Musik: {self.look.name}" + (f" · KI-Regie: {lage}" if lage else "")

    # --- Looks wählen --------------------------------------------------------

    def _stufe(self, energie: float) -> int:
        """Energie in vier Stufen, mit etwas Abstand, damit es nicht flattert."""
        stufe = self.stufe
        while stufe < 3 and energie > STUFEN[stufe] + HYSTERESE / 2:
            stufe += 1
        while stufe > 0 and energie < STUFEN[stufe - 1] - HYSTERESE / 2:
            stufe -= 1
        return stufe

    def _passende_looks(self, stufe: int, profil: dict) -> list:
        reaktion = profil["beat_reaktion"]
        if reaktion < 0.3:
            stufe = min(stufe, 1)       # ruhige Profile bleiben ruhig
        looks = [l for l in LOOKS if l.stufe == stufe]
        if profil["bewegung"] == "aus":
            looks = [l for l in looks if l.bewegung is None] or [l for l in LOOKS if l.bewegung is None and l.stufe <= stufe]
        if reaktion < 0.3:
            looks = [l for l in looks if l.farben == "eine"] or [LOOKS[0]]
        return looks

    def _look_waehlen(self, m: Messwerte, profil: dict, jetzt: float) -> None:
        """Nur am Ende einer Phrase wechseln, außer bei einem Drop."""
        # Intensität: wie stark diese Stelle im Vergleich zum Rest des Songs ist.
        staerke = m.intensitaet if m.intensitaet > 0 else m.energie
        # Spitze halten: Ein Break (ein Takt nur Becken) oder eine kurze leise Stelle zieht die Stärke nur langsam
        # herunter. Erst wenn es mehrere Sekunden ruhiger bleibt, wird das Licht ruhiger.
        self.staerke_gehalten = max(staerke, self.staerke_gehalten - self.dauer / STAERKE_HALTEN_S)
        staerke = self.staerke_gehalten
        stufe = self._stufe(staerke)
        if stufe == 0 and m.tempo_bpm > 0 and self.treffer_rate >= RHYTHMUS_TREFFER:
            stufe = 1                   # klarer Rhythmus mit vielen Schlägen ist nie "Ruhe"
        if getattr(m, "schlagzeug_solo", False):
            stufe = max(stufe, 2)       # Einzelkanäle: Schlagzeug spielt dicht, keine Stimme – das muss knallen
        if self.look_offen:
            self.energie_langsam = staerke
        # Ein Sprung: von ruhig oder mittel plötzlich auf Höhepunkt, deutlich über dem Schnitt.
        drop = (stufe == 3 and self.stufe <= 1 and staerke - self.energie_langsam > DROP)
        self.energie_langsam += (staerke - self.energie_langsam) * min(1.0, self.dauer / 8.0)
        regie = self._regie(jetzt)
        if regie is not None and regie.get("look_obj") is not None:
            if not drop:
                self._regie_anwenden(regie, m, profil, jetzt, stufe)
                if regie.get("look_obj") is not None:
                    return
            else:
                regie["angewendet"] = True  # ein plötzlicher Sprung geht vor; Claude sieht ihn bei der nächsten Frage
        seit = self.beats - self.look_seit
        if m.beat:
            self.hoeher_beats = self.hoeher_beats + 1 if stufe > self.look.stufe else 0
        if self._abschnitt_beginnt(m):
            self.abschnitt_beat, self.abschnitt_takt = self.beats, self.takte - 1
        if m.beat and m.eins and self.eins_bekannt:
            if staerke - self.staerke_vor_takt >= SPRUNG and self.beats - self.abschnitt_beat > 4:
                # Deutlich lauter als einen Takt vorher, auch ohne erkanntes Becken: Der neue Teil begann
                # vermutlich auf der letzten Eins (der Pegel braucht etwa eine Sekunde).
                self.abschnitt_beat, self.abschnitt_takt = self.beats, max(0, self.takte - 2)
            self.staerke_vor_takt = staerke
        if self.eins_bekannt:
            # Mit bekannter Eins: Wechsel nur zu Beginn einer 8-Takt-Phrase (auf der Eins)
            abwechslung = 4 * (ABWECHSLUNG_TAKTE_STARK if self.look.stufe >= 2 else ABWECHSLUNG_TAKTE)
            phrase_um = self._phrase_beginnt(m) and seit >= PHRASE
            # Ruhiger werden: einen Takt nach dem Phrasen-Anfang entscheiden. Auf der Eins selbst kennt der Pegel den
            # neuen Teil noch nicht (er braucht etwa eine Sekunde); sonst ging das Licht genau beim Refrain-Einsatz
            # kurz auf ruhig.
            ruhiger_jetzt = bool(m.beat and m.eins and (self.takte - 1 - self.phrase_basis) % PHRASE_TAKTE == 1
                                 and seit >= PHRASE + 4 and stufe < self.stufe)
            if phrase_um and stufe < self.stufe:
                phrase_um = False                         # siehe oben: erst einen Takt später
            weit_daneben = abs(stufe - self.look.stufe) >= 2 and m.beat and m.eins and seit >= 8
            if self._abschnitt_beginnt(m) and stufe != self.look.stufe and seit >= 8:
                # Neuer Songteil mit Becken und anderer Stärke: jetzt wechseln und die Phrasen ab hier zählen
                weit_daneben = True
                self.phrase_basis = self.takte - 1
            elif self._abschnitt_beginnt(m) and seit < 8:
                self.phrase_basis = self.takte - 1      # Look kam eben erst (Sprung): Das Becken zeigt den Teil-Anfang sicherer
            elif m.beat and m.eins and stufe > self.look.stufe and self.hoeher_beats >= 8 and seit >= 16:
                # Lauter werden (Überleitung in den Refrain) wartet nicht auf das Ende der Phrase: Ist die Musik
                # seit zwei Takten stärker als der Look, kommt der stärkere Look auf der nächsten Eins.
                # Ruhiger werden wartet weiter auf die Phrase (Ruhe statt Dauerwechsel).
                weit_daneben = True
                self.phrase_basis = self.takte - 1
            elif (m.beat and m.eins and 0 <= self.beats - self.abschnitt_beat <= ABSCHNITT_FENSTER_BEATS
                  and stufe != self.look.stufe and seit >= 8):
                # Ein, zwei Takte nach dem Becken hört man, ob der neue Teil stärker ist (der Pegel braucht etwa
                # eine Sekunde): jetzt wechseln, wie ein Operator beim Refrain, und die Phrasen ab dem Becken zählen.
                weit_daneben = True
                self.phrase_basis = self.abschnitt_takt
        else:
            abwechslung = ABWECHSLUNG_STARK if self.look.stufe >= 2 else ABWECHSLUNG
            phrase_um = m.beat and seit >= PHRASE and seit % 8 == 0
            ruhiger_jetzt = False
            # Passt der Look gar nicht (zwei Stufen daneben), wartet er nur bis zum nächsten Takt.
            weit_daneben = abs(stufe - self.look.stufe) >= 2 and m.beat and seit >= 8 and seit % 4 == 0
        # Der erste Look eines Songs: eine halbe Sekunde nach dem ersten Schlag (nicht schon beim Rauschen davor).
        erster = self.look_offen and (
            (self.erste_regung is not None and jetzt - self.erste_regung >= ERSTER_LOOK_S)
            or (self.musik_seit is not None and jetzt - self.musik_seit >= ERSTER_LOOK_SPAETESTENS_S))
        wechseln = erster or (drop and seit >= 4) or weit_daneben or ruhiger_jetzt or (
            phrase_um and (stufe != self.stufe or seit >= abwechslung - 2))   # -2: Look begann vielleicht kurz nach der Eins
        self.stufe = stufe if (wechseln or seit < 1) else self.stufe
        if not wechseln and self.look in self._passende_looks(self.look.stufe, profil):
            return
        looks = self._passende_looks(stufe, profil)
        andere = [l for l in looks if l != self.look] or looks
        self.look = andere[self.look_nummer % len(andere)]
        self.look_nummer += 1
        self.look_seit = self.beats
        self.stufe = stufe
        self.look_offen = False
        if drop or stufe >= 2:
            self.letzter_akzent = jetzt     # der neue Look kommt mit einem hellen Akzent

    # --- Ein Bild ------------------------------------------------------------

    def _weiche_farbe(self, geraet_id: str, ziel) -> tuple:
        """LED-Farben wechseln nicht hart, sondern blenden kurz über."""
        alt = self.led_farbe.get(geraet_id, ziel)
        anteil = min(1.0, self.dauer / FARB_BLENDE_S)
        farbe = tuple(a + (z - a) * anteil for a, z in zip(alt, ziel))
        self.led_farbe[geraet_id] = farbe
        return farbe

    def _gobos(self, geraet: dict) -> list:
        """Welche Gobos hat dieses Gerät? Steht im Katalog, nicht im Programm."""
        if geraet["id"] not in self.gobo_listen:
            namen = []
            for _, kanal in self.patch.typ(geraet).kanaele_im_modus(geraet["modus"]):
                if kanal["typ"] == "gobo":
                    namen += [b["name"] for b in kanal.get("bereiche", [])
                              if b["typ"] == "platz" and b.get("name") != "Offen"]
            self.gobo_listen[geraet["id"]] = namen
        return self.gobo_listen[geraet["id"]]

    def _song_farben(self) -> tuple:
        a, b = self.farben_paar or ("blau", "rot")
        return lies_farbe(a), lies_farbe(b)

    def _farbe(self, art: str, nummer: int = 0) -> tuple:
        """Die Farbe eines Geräts im aktuellen Look: eine Song-Farbe (A) oder Spots B über PARs A.
        "wechsel": zu Beginn jeder 8-Takt-Phrase tauschen Spots und PARs die Farben (nicht mehr alle 4 Beats).
        "lauf": drei Farben wandern alle 4 Takte ein Gerät weiter (auf der Eins; alle 2 Takte waren bei schnellen
        Songs über 15 Farbwechsel pro Minute)."""
        a, b = self._song_farben()
        if self.look.farben == "eine":
            return a
        if self.look.farben == "lauf":
            farben = (a, b, lies_farbe(self.farbe_drei))
            schritt = (self.takte - 1 - self.phrase_basis) // 4 if self.eins_bekannt else self.beats // 16
            return farben[(schritt + nummer + (1 if art == "par" else 0)) % len(farben)]
        if self.look.farben == "wechsel" and self.phrase_nummer % 2 == 1:
            a, b = b, a
        return b if art == "spot" else a

    def _helligkeit(self, m: Messwerte, grenze: float, reaktion: float, nummer: int, anzahl: int,
                    jetzt: float, periode: float) -> float:
        """Grundhelligkeit, darauf der Puls im Beat und ab und zu ein Akzent."""
        look = self.look
        if look.puls == "atmen":
            return grenze * (0.6 + 0.2 * math.sin(2 * math.pi * self.phase / 8))
        puls = math.exp(-(jetzt - self.letzter_puls) / (PULS_ABKLANG * periode))
        # Die Lampen wechseln sich auf dem Puls ab, das wirkt auch mit nur zweien lebendig.
        if anzahl > 1 and self.pulse % anzahl != nummer % anzahl:
            puls *= 0.35
        grund = 1.0 - (0.35 + 0.45 * reaktion)      # so tief geht der Dimmer zwischen den Beats
        if look.stufe >= 2 and reaktion >= 0.5:
            # Starke Musik: Das Licht springt auf jedem Treffer (Schlagzeug!) hoch, die Lampen abwechselnd.
            grund = max(grund, TREFFER_BODEN)
            treffer = math.exp(-(jetzt - self.letzter_treffer) / TREFFER_ABKLANG_S)
            if anzahl > 1 and self.treffer_zahl % anzahl != nummer % anzahl:
                treffer *= 0.5
            puls = max(puls, treffer)
        hell = grund + (1.0 - grund) * max(puls, 0.5 * m.bass)
        auf_der_eins = self.beats == self.letzte_eins_beat if self.eins_bekannt else self.beats % 4 == 0
        if look.puls == "akzent" and auf_der_eins:
            # Auf der Eins im Takt: alle zusammen voll, und langsamer wieder runter.
            hell = max(hell, math.exp(-(jetzt - self.letzter_beat) / (AKZENT_ABKLANG * periode)))
        # Beim Wechsel in einen starken Look: kurz doppelt hell.
        hell = max(hell, math.exp(-(jetzt - self.letzter_akzent) / (AKZENT_ABKLANG * periode)))
        return grenze * min(1.0, hell)

    def drop_laeuft(self) -> bool:
        return self.beats - self.drop_beat < DROP_BEATS

    def _musik(self, m: Messwerte, profil: dict, jetzt: float) -> dict:
        reaktion = profil["beat_reaktion"]
        palette = list(self._song_farben())
        grenze = profil["max_helligkeit"]
        tempo = m.tempo_bpm if 40.0 <= m.tempo_bpm <= 240.0 else STANDARD_TEMPO
        periode = 60.0 / tempo
        self.tempo = tempo
        self.schub = math.exp(-(jetzt - self.letzter_beat) / (PULS_ABKLANG * periode))
        if reaktion >= 0.5:
            if getattr(m, "stopp", False) and (self.look.stufe >= 2 or self.drop_laeuft()):
                # Gemeinsamer Schlusspunkt oder Break in kräftiger Musik: Licht aus, wie ein Operator auf dem Stopp.
                # (Dauert es länger, kommt nach 0,8 s „leise“ und das Grundlicht blendet ein.)
                self.im_stopp = True
                return self._stopp_bild()
            if self.im_stopp:
                self.im_stopp = False
                self.letzter_akzent = jetzt           # die Band setzt wieder ein: voll hell, kurz weiß
            regie = self._regie(jetzt)
            leise_gehoert = regie is not None and (regie["lage"] in REGIE_LEISE or (
                regie["lage"] not in REGIE_KRAEFTIG and regie.get("look_obj") is not None and regie["look_obj"].stufe <= 1))
            if self.drop_laeuft() and leise_gehoert and regie["zeit"] > self.drop_zeit + 1.0:
                # Claude hört nach dem "Drop" ruhige Musik: Das war ein Songanfang nach einer Pause, kein Drop.
                self.drop_beat = -999
                self.musik_anteil = min(self.musik_anteil, 0.5)
            if self.drop_laeuft():
                return self._drop(m, profil, palette, grenze, jetzt, periode)
            if self.drop_beat >= 0 and self.beats - self.drop_beat == DROP_BEATS:
                self._nach_dem_drop(m, profil)
            if m.vor_drop:
                return self._pause(grenze)
            if m.spannung >= AUFBAU_AB:
                return self._aufbau(m, palette, grenze, jetzt, periode)
        self._look_waehlen(m, profil, jetzt)
        ergebnis = {}

        # Großer Schlag (Becken) oder neuer starker Look: kurz weiß, dann zurück in die Farbe
        weiss = 0.0
        if self.look.stufe >= 2 and reaktion >= 0.5 and jetzt - self.letzter_akzent < 4 * WEISS_ABKLANG_S:
            weiss = math.exp(-(jetzt - self.letzter_akzent) / WEISS_ABKLANG_S)

        def mit_weiss(farbe):
            return tuple(f + (1.0 - f) * weiss for f in farbe) if weiss > 0.01 else farbe

        pars = self.patch.in_gruppe(GRUPPE_FARBE)
        for nummer, geraet in enumerate(pars):
            hell = self._helligkeit(m, grenze, reaktion, nummer, len(pars), jetzt, periode)
            ziel = self._farbe("par", nummer)
            ergebnis[geraet["id"]] = Eigenschaften(helligkeit=hell,
                                                   farbe=mit_weiss(self._weiche_farbe(geraet["id"], ziel)))

        strobo = self._strobo_hz(m, profil, jetzt)
        spots = self.patch.in_gruppe(GRUPPE_BEWEGUNG)
        for nummer, geraet in enumerate(spots):
            e = Eigenschaften(helligkeit=self._helligkeit(m, grenze, reaktion, nummer, len(spots), jetzt, periode),
                              farbe=mit_weiss(self._farbe("spot", nummer)),
                              strobo_hz=strobo if "Effektlicht" in self.patch.gruppen_von(geraet) else 0.0)
            gobos = self._gobos(geraet)
            if gobos and self.look.gobo and reaktion >= 0.3:
                e.gobo = gobos[self.look_nummer % len(gobos)]
                seite = 1 if nummer % 2 == 0 else -1
                e.gobo_drehung = seite * self.look.drehung if reaktion >= 0.5 and self.look.drehung else None
            elif gobos:
                e.gobo = "Offen"
            if self.look.bewegung and profil["bewegung"] != "aus":
                self._bewegen(geraet, nummer, profil["bewegung"], m.energie, e)
            else:
                self._stehen(geraet, nummer, len(spots), e)
            ergebnis[geraet["id"]] = e
        return ergebnis

    # --- Aufbau, Pause, Drop ----------------------------------------------------

    def _alle_lichter(self):
        for nummer, geraet in enumerate(self.patch.in_gruppe(GRUPPE_BEWEGUNG)):
            yield "spot", nummer, geraet
        for nummer, geraet in enumerate(self.patch.in_gruppe(GRUPPE_FARBE)):
            yield "par", nummer, geraet

    def _aufbau(self, m: Messwerte, palette: list, grenze: float, jetzt: float, periode: float) -> dict:
        """Spannung: Strahlen sammeln sich, Licht wird heller und weißer, der Puls stärker."""
        s = min(1.0, (m.spannung - AUFBAU_AB) / (1.0 - AUFBAU_AB))
        weiss = (1.0, 1.0, 1.0)
        farbe = tuple(a + (b - a) * s for a, b in zip(palette[self.look_nummer % len(palette)], weiss))
        puls = math.exp(-(jetzt - self.letzter_beat) / (PULS_ABKLANG * periode))
        # Der Puls wird mit der Spannung tiefer. Er bleibt im Beat, also unter der Blitz-Grenze.
        hell = grenze * min(1.0, (0.35 + 0.5 * s) + (0.15 + 0.35 * s) * puls)
        masse = self.buehne.daten["buehne"]
        ergebnis = {}
        for art, nummer, geraet in self._alle_lichter():
            e = Eigenschaften(helligkeit=hell, farbe=self._weiche_farbe(geraet["id"], farbe) if art == "par" else farbe)
            if art == "spot":
                e.gobo = "Offen" if self._gobos(geraet) else None
                anzahl = len(self.patch.in_gruppe(GRUPPE_BEWEGUNG))
                breit = 0.3 * masse["breite_m"] * (1.0 - s)
                x = 0.0 if anzahl < 2 else -breit + 2 * breit * nummer / (anzahl - 1)
                self._zielen(geraet, (x, masse["tiefe_m"] * (0.5 - 0.3 * s), ZIEL_HOEHE_M), e)
            ergebnis[geraet["id"]] = e
        self.zustand_text = f"Aufbau {round(m.spannung * 100)} %"
        return ergebnis

    def _stopp_bild(self) -> dict:
        """Licht aus auf dem Stopp. Die Köpfe bleiben stehen (kein Fahren im Dunkeln, das sähe man im Saal)."""
        ergebnis = {}
        for art, _, geraet in self._alle_lichter():
            e = Eigenschaften(helligkeit=0.0, farbe=self.led_farbe.get(geraet["id"], (1.0, 1.0, 1.0)))
            if art == "spot" and geraet["id"] in self.winkel:
                e.pan, e.tilt = self.winkel[geraet["id"]]
            ergebnis[geraet["id"]] = e
        self.zustand_text = "Stopp"
        return ergebnis

    def _pause(self, grenze: float) -> dict:
        """Der Moment vor dem Drop: fast dunkel, die Spots bleiben in der Mitte."""
        ergebnis = {}
        for art, _, geraet in self._alle_lichter():
            e = Eigenschaften(helligkeit=0.03 * grenze, farbe=(1.0, 1.0, 1.0))
            if art == "spot" and geraet["id"] in self.winkel:
                e.pan, e.tilt = self.winkel[geraet["id"]]
            ergebnis[geraet["id"]] = e
        self.zustand_text = "Pause vor dem Drop"
        return ergebnis

    def _drop(self, m: Messwerte, profil: dict, palette: list, grenze: float, jetzt: float, periode: float) -> dict:
        """Der Drop: weißer Schlag, dann jeder Bass-Schlag ein harter Lichtschlag."""
        seit = jetzt - self.drop_zeit
        a = palette[(self.look_nummer + 1) % len(palette)]
        b = palette[(self.look_nummer + 2) % len(palette)]
        wechsel = ((self.beats - self.drop_beat) // 8) % 2
        schlag = math.exp(-(jetzt - max(self.letzter_beat, self.drop_zeit)) / (0.35 * periode))
        hell = grenze * (1.0 if seit < DROP_WEISS_S else 0.15 + 0.85 * schlag)
        masse = self.buehne.daten["buehne"]
        ergebnis = {}
        for art, nummer, geraet in self._alle_lichter():
            farbe = (1.0, 1.0, 1.0) if seit < DROP_WEISS_S else (a if (nummer + wechsel) % 2 == 0 else b)
            e = Eigenschaften(helligkeit=hell, farbe=farbe)
            if art == "spot":
                gobos = self._gobos(geraet)
                if gobos:
                    e.gobo = gobos[(self.look_nummer + 1) % len(gobos)]
                    e.gobo_drehung = 0.8 if nummer % 2 == 0 else -0.8
                if profil["bewegung"] != "aus":
                    # Große, schnelle Bewegung im Takt: die Strahlen kreuzen sich auf der Eins.
                    winkel = 2 * math.pi * (self.beats - self.drop_beat + min(1.0, (jetzt - self.letzter_beat) / periode)) / DROP_BEWEGUNG_BEATS
                    seite = 1 if nummer % 2 == 0 else -1
                    ziel = (seite * 0.42 * masse["breite_m"] * math.sin(winkel),
                            masse["tiefe_m"] * (0.45 + 0.3 * math.cos(winkel)), ZIEL_HOEHE_M)
                    self._zielen(geraet, ziel, e)
                elif geraet["id"] in self.winkel:
                    e.pan, e.tilt = self.winkel[geraet["id"]]
            ergebnis[geraet["id"]] = e
        # Strobos blitzen beim Drop, aber nur wenn das Profil es erlaubt. Tempo und Dauer begrenzt
        # die Prüfung, ein nicht eingemessener Strobo bleibt dort gesperrt.
        if profil["strobo"] != "aus":
            hz = min(profil["strobo"]["max_blitze_pro_sekunde"], self.grenzen.strobo_max_hz)
            for geraet in self.patch.in_gruppe(GRUPPE_STROBO):
                blitzen = seit < 4.0
                ergebnis[geraet["id"]] = Eigenschaften(helligkeit=grenze if blitzen else 0.0,
                                                       strobo_hz=hz if blitzen else 0.0, farbe=(1.0, 1.0, 1.0))
        self.zustand_text = "DROP"
        return ergebnis

    def _nach_dem_drop(self, m: Messwerte, profil: dict) -> None:
        """Nach dem Drop geht es mit einem starken Look weiter, nicht zurück auf ruhig."""
        looks = self._passende_looks(max(2, self._stufe(m.energie)), profil)
        self.look = looks[self.look_nummer % len(looks)]
        self.look_nummer += 1
        self.look_seit = self.beats

    def _ruhelage(self, geraet: dict, e: Eigenschaften) -> None:
        """Ohne Bewegung zeigen Spots auf die Bühnenmitte, nicht einfach nach oben."""
        if bereiche_von(self.patch, geraet) is None:
            return
        masse = self.buehne.daten["buehne"]
        try:
            e.pan, e.tilt = zeige_auf(geraet, (0.0, masse["tiefe_m"] / 2, ZIEL_HOEHE_M),
                                      self.patch, self.buehne)
        except ZielAusserhalb:
            pass

    def _stehen(self, geraet: dict, nummer: int, anzahl: int, e: Eigenschaften) -> None:
        """Licht steht: Die Spots zeigen ruhig auf feste Punkte und gleiten nur dorthin."""
        masse = self.buehne.daten["buehne"]
        if anzahl > 1:
            # Zwei Spots: gespiegelt, je nach Look enger oder weiter
            weite = (0.15, 0.25, 0.1)[self.look_nummer % 3] * masse["breite_m"]
            x = -weite + 2 * weite * nummer / (anzahl - 1)
        else:
            x = 0.0
        self._zielen(geraet, (x, masse["tiefe_m"] / 2, ZIEL_HOEHE_M), e)

    def _muster(self, nummer: int, zyklus: float, weite: float, muster: Optional[str] = None) -> tuple:
        """Ein Punkt der Bewegung auf dem Bühnenboden. Nie im Publikum."""
        masse = self.buehne.daten["buehne"]
        breite, tiefe = masse["breite_m"], masse["tiefe_m"]
        winkel = 2 * math.pi * self.phase / zyklus
        seite = 1 if nummer % 2 == 0 else -1
        versatz = nummer * math.pi
        muster = muster or self.look.bewegung or "schwenk"
        if muster == "faecher":      # gespiegelt auf und zu
            return (seite * breite * weite * (0.1 + 0.15 * (1 + math.sin(winkel))), tiefe * 0.5)
        if muster == "kreis":        # Kreise, die sich gegenüberliegen
            return (0.3 * breite * weite * math.cos(winkel + versatz),
                    tiefe * (0.5 + 0.3 * weite * math.sin(winkel + versatz)))
        if muster == "kreuz":        # die Strahlen tauschen die Seiten
            return (seite * 0.38 * breite * weite * math.sin(winkel), tiefe * 0.5)
        if muster == "nicken":       # vor und zurück, gegeneinander
            return (seite * 0.2 * breite, tiefe * (0.5 + 0.3 * weite * math.sin(winkel + versatz)))
        if muster == "acht":         # liegende Acht, die Köpfe gegeneinander
            return (0.32 * breite * weite * math.sin(winkel + versatz / 2),
                    tiefe * (0.5 + 0.18 * weite * math.sin(2 * winkel + versatz)))
        if muster == "gegenkreis":   # gespiegelte Kreise: ein Kopf rechts herum, der andere links herum
            return (seite * breite * weite * (0.12 + 0.16 * math.cos(winkel)),
                    tiefe * (0.5 + 0.25 * weite * math.sin(winkel)))
        if muster == "ballyhoo":     # groß und wild (zwei Takte, die nie ganz gleich aussehen), aber auf der Bühne
            return (0.4 * breite * weite * math.sin(winkel + versatz / 2) * (0.7 + 0.3 * math.cos(1.5 * winkel)),
                    tiefe * (0.5 + 0.32 * weite * math.sin(1.5 * winkel + versatz)))
        return (0.35 * breite * weite * math.sin(winkel + versatz / 2), tiefe * 0.5)   # Schwenk

    def _runde_beats(self, bewegung: str) -> float:
        """So viele Beats dauert eine Runde der Bewegung: wie im Look, bei "langsam" doppelt so viele,
        und bei schnellen Songs so viele, dass eine Runde mindestens 4 Sekunden dauert."""
        zyklus = self.look.beats * (2 if bewegung == "langsam" else 1)
        mindestens = MIN_RUNDE_HOEHEPUNKT_S if self.look.stufe >= 3 and bewegung != "langsam" else MIN_RUNDE_S
        while zyklus * 60.0 / max(getattr(self, "tempo", STANDARD_TEMPO), 1.0) < mindestens:
            zyklus *= 2
        return zyklus

    def _bewegen(self, geraet: dict, nummer: int, bewegung: str, energie: float, e: Eigenschaften) -> None:
        """Die Spots folgen dem Muster des Looks, im Takt und geglättet."""
        x, y = self._muster(nummer, self._runde_beats(bewegung), 0.6 + 0.4 * energie)
        if self.look.schub:
            y += self.schub * self.buehne.daten["buehne"]["tiefe_m"] * 0.06     # kleiner Ruck auf dem Beat
        self._zielen(geraet, (x, y, ZIEL_HOEHE_M), e)

    def _zielen(self, geraet: dict, ziel: tuple, e: Eigenschaften) -> None:
        """Gleitet weich zum Ziel. Gleiche Rechnung für Stehen und Bewegung."""
        if bereiche_von(self.patch, geraet) is None:
            return
        alt = self.winkel.get(geraet["id"])
        try:
            pan, tilt = zeige_auf(geraet, ziel, self.patch, self.buehne, alt)
        except ZielAusserhalb:
            if alt:
                e.pan, e.tilt = alt
            return
        if alt:
            anteil = min(1.0, self.dauer / WINKEL_GLAETTUNG_S)
            schritt = MAX_GRAD_PRO_S * self.dauer
            begrenze = lambda d: max(-schritt, min(schritt, d * anteil))
            pan, tilt = alt[0] + begrenze(pan - alt[0]), alt[1] + begrenze(tilt - alt[1])
        e.pan, e.tilt = pan, tilt
        self.winkel[geraet["id"]] = (pan, tilt)

    def _strobo_hz(self, m: Messwerte, profil: dict, jetzt: float) -> float:
        """Strobo nur, wenn das Profil es erlaubt und die Energie lange sehr hoch ist."""
        if profil["strobo"] == "aus" or m.energie < STROBO_ENERGIE:
            self.laut_seit = None
            return 0.0
        if self.laut_seit is None:
            self.laut_seit = jetzt
        if jetzt - self.laut_seit < STROBO_NACH_S:
            return 0.0
        return min(profil["strobo"]["max_blitze_pro_sekunde"], self.grenzen.strobo_max_hz)
