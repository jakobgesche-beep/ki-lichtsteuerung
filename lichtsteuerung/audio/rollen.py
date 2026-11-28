"""Einzelne Kanäle vom X32 (über USB): Bassdrum, Snare, Gesang/Rednerpult und weitere Band-Kanäle.

Die Summe allein hört alles gemischt (und im Saal mit Hall und Publikum). Die Mikrofone am Schlagzeug und am
Rednerpult sagen viel genauer, was gerade passiert:

    Takt      Bassdrum und Snare kommen sauber und ohne Hall. Sie werden der Summe für den Takt-Folger
              beigemischt (Rhythmus-Mischung): Die Schläge stechen heraus, der Takt sitzt fester.
    Rede      Ein Mikro (Gesang oder Rednerpult) ist laut, und die Band (Schlagzeug, Band-Kanäle) ist still:
              Dann redet jemand. Viel sicherer als aus der Summe zu raten.
    Solo      Schlagzeug spielt dicht (mindestens 2,5 Schläge pro Sekunde), Gesang ist still: Schlagzeug-Solo.

Die Kanäle kommen vor dem Fader (wie an den Eingängen des Pults). Darum misst jede Rolle ihren eigenen
Grundpegel (Rauschen) und ihre eigene Spitze und urteilt relativ dazu, nicht nach festen Zahlen.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .quellen import ABTASTRATE, BLOCK

ROLLEN = {"summe": "Summe (Main L/R)", "bassdrum": "Bassdrum", "snare": "Snare", "gesang": "Gesang",
          "rednerpult": "Rednerpult", "band": "Band (weitere)"}
TROMMELN = ("bassdrum", "snare")
STIMMEN = ("gesang", "rednerpult")

AKTIV_UEBER_DB = 15.0         # so viel über dem eigenen Grundpegel heißt „spielt“ / „spricht“
GRUND_STEIGT_DB_S = 1.5       # der Grundpegel folgt nach oben nur langsam (sonst wird Musik zum Rauschen)
FENSTER_S = 1.5               # Rede: so lange Mikro aktiv und Band still
SOLO_SCHLAEGE_PRO_S = 2.5
SOLO_S = 2.0
MISCH_ANTEIL = 0.8            # wie stark Bassdrum/Snare der Summe für den Takt beigemischt werden
# Rhythmus-Mischung für den Takt-Folger: gemessen (6 Stile, viel Hall, sehr lautes Publikum) Beats 94,6 → 95,8 %,
# aber bei EDM (Bassdrum auf jedem Schlag) rutschte die Eins um einen Schlag. Kommt die Summe sauber vom X32
# (ohne Saal), sitzt der Takt ohnehin bei 97–99 %. Darum aus; die Einzelkanäle helfen bei Rede, Solo und Applaus.
RHYTHMUS_MISCHEN = False


@dataclass
class RollenWerte:
    rede_sicher: bool = False
    schlagzeug_solo: bool = False
    band_aktiv: bool = False
    stimme_aktiv: bool = False
    schlaege_pro_s: float = 0.0


class _Kanal:
    """Pegel, Grundpegel und Einsätze eines Kanals (pro Block)."""

    def __init__(self):
        self.grund_db = -60.0
        self.spitze_db = -60.0
        self.db = -90.0
        self.huelle = 0.0
        self.huelle_vorher = 0.0
        self.seit_schlag = 1.0
        self.verlauf = deque(maxlen=int(FENSTER_S * ABTASTRATE / BLOCK))   # aktiv ja/nein pro Block
        self.pegel_verlauf = deque(maxlen=int(FENSTER_S * ABTASTRATE / BLOCK))   # dB pro Block
        self.rms_glatt = 1e-4

    def verarbeite(self, block: np.ndarray) -> bool:
        """Gibt zurück, ob in diesem Block ein Schlag (Einsatz) beginnt."""
        dauer = len(block) / ABTASTRATE
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64)))) + 1e-9
        self.rms_glatt += (rms - self.rms_glatt) * min(1.0, dauer / 3.0)
        self.db = 20 * np.log10(rms)
        # Grundpegel: fällt schnell (Pausen), steigt nur langsam
        if self.db < self.grund_db:
            self.grund_db += (self.db - self.grund_db) * min(1.0, dauer / 0.3)
        else:
            self.grund_db = min(self.db, self.grund_db + GRUND_STEIGT_DB_S * dauer)
        self.spitze_db = max(self.db, self.spitze_db - 3.0 * dauer)
        aktiv = self.db > self.grund_db + AKTIV_UEBER_DB
        self.verlauf.append(aktiv)
        self.pegel_verlauf.append(self.db)
        # Einsatz: Hüllkurve springt deutlich (Schlagzeug: sehr kurz, sehr steil)
        self.huelle_vorher, self.huelle = self.huelle, rms
        self.seit_schlag += dauer
        schlag = aktiv and self.huelle > 2.0 * self.huelle_vorher and self.seit_schlag >= 0.09
        if schlag:
            self.seit_schlag = 0.0
        return schlag

    def anteil_aktiv(self) -> float:
        return sum(self.verlauf) / len(self.verlauf) if self.verlauf else 0.0


class RollenAnalyse:
    def __init__(self):
        self.kanaele: dict = {}
        self.schlaege = deque()           # Zeiten der Schlag-Einsätze (Bassdrum/Snare), für Schläge pro Sekunde
        self.zeit = 0.0
        self.band_still_seit: Optional[float] = None
        self.solo_seit: Optional[float] = None

    def rhythmus(self, summe: np.ndarray, rollen: dict) -> np.ndarray:
        """Summe mit beigemischter Bassdrum und Snare (gleich laut gemacht): für den Takt-Folger."""
        mix = summe.astype(np.float32).copy()
        ziel = self.kanaele["summe"].rms_glatt if "summe" in self.kanaele else float(np.sqrt(np.mean(summe ** 2))) + 1e-6
        for name in TROMMELN:
            block = rollen.get(name)
            kanal = self.kanaele.get(name)
            if block is None or kanal is None:
                continue
            verstaerkung = min(20.0, ziel / max(kanal.rms_glatt, 1e-5))
            mix += MISCH_ANTEIL * verstaerkung * block.astype(np.float32)
        return mix

    def verarbeite(self, summe: np.ndarray, rollen: dict) -> RollenWerte:
        dauer = len(summe) / ABTASTRATE
        self.zeit += dauer
        for name, block in [("summe", summe)] + [(n, b) for n, b in rollen.items() if n != "summe"]:
            kanal = self.kanaele.setdefault(name, _Kanal())
            schlag = kanal.verarbeite(block)
            if schlag and name in TROMMELN:
                self.schlaege.append(self.zeit)
        while self.schlaege and self.zeit - self.schlaege[0] > SOLO_S:
            self.schlaege.popleft()
        pro_s = len(self.schlaege) / SOLO_S
        trommeln = [self.kanaele[n] for n in TROMMELN if n in rollen]
        weitere = [self.kanaele[n] for n in ("band",) if n in rollen]
        stimmen = [self.kanaele[n] for n in STIMMEN if n in rollen]
        band_aktiv = any(k.anteil_aktiv() > 0.05 for k in trommeln) or any(k.anteil_aktiv() > 0.3 for k in weitere) \
            or pro_s >= 1.0
        # Ein Gesangsmikro hört das Schlagzeug mit (Übersprechen). Springt sein Pegel genau mit den Schlägen,
        # ist es nur das Schlagzeug und keine Stimme.
        trommel_pegel = None
        if trommeln:
            laenge = min(len(k.pegel_verlauf) for k in trommeln)
            if laenge >= 8:
                trommel_pegel = np.max([list(k.pegel_verlauf)[-laenge:] for k in trommeln], axis=0)

        def echte_stimme(k) -> bool:
            if k.anteil_aktiv() < 0.4:
                return False
            if trommel_pegel is None or not any(t.anteil_aktiv() > 0.05 for t in trommeln):
                return True
            eigen = np.array(list(k.pegel_verlauf)[-len(trommel_pegel):])
            if len(eigen) < 8 or np.std(eigen) < 1e-3 or np.std(trommel_pegel) < 1e-3:
                return True
            return float(np.corrcoef(eigen, trommel_pegel)[0, 1]) < 0.5

        stimme_aktiv = any(echte_stimme(k) for k in stimmen)
        if band_aktiv:
            self.band_still_seit = None
        elif self.band_still_seit is None:
            self.band_still_seit = self.zeit
        rede = bool(stimmen) and stimme_aktiv and self.band_still_seit is not None \
            and self.zeit - self.band_still_seit >= FENSTER_S
        solo_jetzt = bool(trommeln) and pro_s >= SOLO_SCHLAEGE_PRO_S and not stimme_aktiv \
            and not any(k.anteil_aktiv() > 0.3 for k in weitere)
        if solo_jetzt:
            self.solo_seit = self.solo_seit if self.solo_seit is not None else self.zeit
        else:
            self.solo_seit = None
        solo = self.solo_seit is not None and self.zeit - self.solo_seit >= SOLO_S
        return RollenWerte(rede_sicher=rede, schlagzeug_solo=solo, band_aktiv=band_aktiv,
                           stimme_aktiv=stimme_aktiv, schlaege_pro_s=round(pro_s, 2))

    def pegel(self) -> dict:
        return {name: {"db": round(k.db, 1), "grund_db": round(k.grund_db, 1), "aktiv": k.anteil_aktiv() > 0.3}
                for name, k in self.kanaele.items()}
