"""Stärke der Musik: Wie laut ist es gerade, verglichen mit den lauten Stellen der Musik?

Gemessen wird in Dezibel über etwa eine Sekunde, wie ein Pegelmesser (nicht wie eine Spitzenanzeige). So ist ein
Refrain mit vollem Schlagzeug lauter als die Strophe, und ein Intro nur mit Akkorden gilt nicht als Höhepunkt.
(Vorher wurde der Pegel durch seine eigene Spitze geteilt. Das maß eher „gleichmäßig oder nicht“ als „laut oder
leise“: Ein Intro ohne Schlagzeug kam lauter heraus als die Strophe mit Schlagzeug.)

    Bezug       die lauten Stellen der letzten 5 Minuten Musik (90. Perzentil)
    Stärke      so viel leiser als der Bezug:  0 dB → 1,0   1,5 dB → 0,8   4 dB → 0,6   9 dB → 0,35   15 dB → 0
                (die Engine macht daraus Höhepunkt ab 0,8, stark ab 0,6, mittel ab 0,35, sonst ruhig).
                Gemessen an den Test-Songs: Refrain 0 dB, Überleitung −1, Strophe −4, Bridge −6, Intro −13 dB.

Am Anfang weiß niemand, wie laut es noch wird:
    - Gibt es einen gemerkten Bezug vom letzten Mal mit derselben Ton-Quelle (zum Beispiel vom Soundcheck am
      Vortag), gilt er. Er verliert 0,05 dB pro Sekunde Musik, falls heute leiser gespielt wird.
    - Sonst gilt: Es wird vermutlich noch 4 dB lauter als bisher gehört. Dieser Abstand schrumpft in den ersten
      45 Sekunden Musik auf null. So wird beim ersten Song nicht schon das Intro zum Höhepunkt, und ein lautes
      Solo am Anfang knallt nach wenigen Sekunden trotzdem (laut muss knallen).
Nach unten folgt der Bezug langsam (0,01 dB/s): Eine Ballade nach lauten Songs wird nicht zum Höhepunkt.
Rede, Applaus und Stille zählen nicht zur Musik.

Stopp: Die Band hört schlagartig auf (gemeinsamer Schlusspunkt, Break). Erkannt, wenn
    - die Musik davor mindestens 1 s dicht durchklang (schneller Pegel, 15 ms, nie mehr als 15 dB unter dem Bezug)
      und kräftig war (Stärke ab 0,6), und
    - der Pegel dann innerhalb von 0,2 s fast auf Stille fällt (mindestens 25 dB unter dem Bezug).
Nicht als Stopp zählen: ein leiser Teil (nur Gesang, Bridge: 6 bis 20 dB darunter), Lücken zwischen einzelnen Tönen
(Ballade, Schlagzeug-Solo: nicht dicht) und ein Ausklingen (fällt langsamer). Der Stopp endet, sobald wieder Ton
kommt, spätestens nach 3 s (dann ist es eine Pause oder das Ende des Songs).
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional

import numpy as np

TAU_S = 1.0                  # so lange mittelt der Pegel (Bassdrum-Spitzen zählen nicht einzeln)
ABSTAND_DB = (0.0, 1.5, 4.0, 9.0, 15.0)      # so viel leiser als der Bezug …
STAERKE = (1.0, 0.8, 0.6, 0.35, 0.0)         # … gibt diese Stärke (dazwischen gerade Linien)
KOPFRAUM_DB = 4.0            # ohne gemerkten Bezug: so viel lauter wird es am Anfang vermutlich noch
KOPFRAUM_S = 45.0            # … und nach so viel Musik ist dieser Abstand null
GEMERKT_SINKT_DB_S = 0.05    # ein gemerkter Bezug gibt nach, falls heute leiser gespielt wird
SINKT_DB_S = 0.01
EINSCHWINGEN_S = 1.0         # so viel Musik, bis der Pegel stimmt (vorher: Stärke 0,5)
SCHNELL_S = 0.015            # schneller Pegel für den Stopp (erkennt ihn nach etwa 0,1 s)
STOPP_UNTER_DB = 25.0        # so weit unter dem Bezug ist es „fast still“
STOPP_ENDE_DB = 20.0         # so nah am Bezug ist der Ton wieder da
STOPP_KRAEFTIG_S = 0.35      # so kurz vorher muss es noch kräftig gewesen sein
STOPP_MAX_S = 3.0
DICHT_DB = 15.0              # so nah am Bezug bleibt dichte Musik (zwischen den Schlägen)
DICHT_S = 1.0                # so lange muss sie vor dem Stopp dicht gewesen sein
STURZ_S = 0.2                # so schnell muss sie auf fast still fallen
VERLAUF_S = 300              # Bezug aus den letzten 5 Minuten Musik
STILLE_DB = -70.0            # darunter ist es keine Musik (digitale Stille, abgeschalteter Kanal)
MERKEN_AB_S = 60.0           # erst nach so viel Musik wird ein Bezug gemerkt


class Lautheit:
    def __init__(self, gemerkt_db: Optional[float] = None):
        self.leistung = 0.0
        self.db = -120.0
        self.verlauf: deque = deque(maxlen=VERLAUF_S * 10)     # zehnmal pro Sekunde, nur Musik
        self.bis_merken = 0.0
        self.gemerkt_db = gemerkt_db
        self.musik_s = 0.0
        self.oben: Optional[float] = None                     # 90. Perzentil des Verlaufs
        self.oben_langsam: Optional[float] = None             # folgt nach unten nur langsam
        self.bezug_db: Optional[float] = None
        self.staerke = 0.0
        self.schnell = 0.0
        self.zeit = 0.0
        self.kraeftig_zeit = -99.0        # wann die Musik zuletzt kräftig war (Stärke ab 0,6)
        self.stopp = False
        self.stopp_seit = 0.0
        self.ueber_seit: Optional[float] = None    # seit wann der schnelle Pegel dicht am Bezug ist
        self.unter_seit: Optional[float] = None    # seit wann er darunter ist (die Lücke)
        self.luecke_nach_dichtem = False

    def verarbeite(self, block: np.ndarray, dauer: float, musik: bool) -> float:
        """Ein Block. `musik`: keine Stille, keine Rede, kein Applaus. Gibt die Stärke (0 bis 1) zurück."""
        leistung = float(np.mean(np.square(block, dtype=np.float64)))
        self.leistung += (leistung - self.leistung) * min(1.0, dauer / TAU_S)
        self.db = 10.0 * math.log10(self.leistung + 1e-12)
        self.zeit += dauer
        self.schnell += (leistung - self.schnell) * min(1.0, dauer / SCHNELL_S)
        self._stopp_pruefen(10.0 * math.log10(self.schnell + 1e-12))
        if musik and self.db > STILLE_DB:
            self.musik_s += dauer
            self.bis_merken -= dauer
            if self.bis_merken <= 0:
                self.bis_merken += 0.1
                self.verlauf.append(self.db)
                if len(self.verlauf) >= 10:
                    self.oben = float(np.percentile(self.verlauf, 90))
            if self.oben is not None:
                if self.oben_langsam is None or self.oben > self.oben_langsam:
                    self.oben_langsam = self.oben
                else:
                    self.oben_langsam = max(self.oben, self.oben_langsam - SINKT_DB_S * dauer)
        if self.musik_s < EINSCHWINGEN_S or self.oben_langsam is None:
            self.staerke = 0.5 if self.musik_s > 0 else 0.0      # noch keine Ahnung: mittel
            return self.staerke
        if self.gemerkt_db is not None:
            self.bezug_db = max(self.oben_langsam, self.gemerkt_db - GEMERKT_SINKT_DB_S * self.musik_s)
        else:
            self.bezug_db = self.oben_langsam + KOPFRAUM_DB * max(0.0, 1.0 - self.musik_s / KOPFRAUM_S)
        self.staerke = float(np.interp(self.bezug_db - self.db, ABSTAND_DB, STAERKE))
        if self.staerke >= 0.6 and musik:
            self.kraeftig_zeit = self.zeit
        return self.staerke

    def _stopp_pruefen(self, schnell_db: float) -> None:
        if self.bezug_db is None:
            return
        if schnell_db >= self.bezug_db - DICHT_DB:
            if self.ueber_seit is None:
                self.ueber_seit = self.zeit
            self.unter_seit = None
        else:
            if self.unter_seit is None:                 # eine Lücke beginnt: war die Musik davor dicht?
                self.unter_seit = self.zeit
                self.luecke_nach_dichtem = self.ueber_seit is not None and self.zeit - self.ueber_seit >= DICHT_S
            self.ueber_seit = None
        if self.stopp:
            if schnell_db > self.bezug_db - STOPP_ENDE_DB or self.zeit - self.stopp_seit > STOPP_MAX_S:
                self.stopp = False
        elif (schnell_db < self.bezug_db - STOPP_UNTER_DB and self.unter_seit is not None and self.luecke_nach_dichtem
              and self.zeit - self.unter_seit <= STURZ_S and self.zeit - self.kraeftig_zeit <= STOPP_KRAEFTIG_S):
            self.stopp, self.stopp_seit = True, self.zeit

    def gelernt(self) -> Optional[float]:
        """Der Bezug zum Merken: nur aus echter Musik und erst nach einer Minute davon."""
        if self.oben_langsam is None or self.musik_s < MERKEN_AB_S:
            return None
        return round(self.oben_langsam, 1)
