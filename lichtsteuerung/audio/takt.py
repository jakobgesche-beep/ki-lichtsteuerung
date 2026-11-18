"""Takt live: Wann kommt der nächste Beat? Gerechnet wie die Probe-Analyse, nur laufend über die letzten 8 Sekunden.

    Merkmale   alle 10 ms 40 Frequenzbänder (wie songanalyse), daraus die Einsatz-Kurve
    Tempo      alle 0,25 s: Welcher Abstand wiederholt sich, auch doppelt und vierfach (songanalyse.tempo_schaetzen)?
               Ein neues Tempo gilt erst, wenn es 1 s lang immer wieder herauskommt. Das halbe oder doppelte
               Tempo ist kein neues Tempo (dasselbe Raster), so springt der Puls nicht zwischen schnell und langsam.
    Raster     Beats im Fenster per dynamischer Programmierung (songanalyse.beats_finden). Die sicheren Beats
               (nicht ganz am Ende des Fensters) ergeben Abstand und Lage, daraus der nächste Beat.
    Ausgabe    Ein Beat kommt zur vorhergesagten Zeit, nicht erst, wenn der Schlag gehört ist. Neue Vorhersagen
               ziehen die Uhr nur sanft nach, wie ein Musiker, der mitzählt.
    Eins       Welcher Schlag ist die Eins im Takt? Wie bei der Probe: Dort wechseln die Akkorde, und dort schlägt
               die Bassdrum (songanalyse.takt_eins_finden über die letzten 16 s, alle 2 s, mit Mehrheit).
    Stille     Ist es 2 s lang viel leiser als vorher, hört die Uhr auf und fängt mit der Musik neu an.

Vorher (bis 2.2) kam ein Beat bei jedem lauten Einsatz, und das Tempo sprang: Bei "Hh" (167 BPM) zwischen 84,
114, 130 und 171 BPM, nur gut die Hälfte der Beats lag richtig (siehe ANNAHMEN.md).
"""
from __future__ import annotations

import logging
import math
from collections import deque
from typing import Optional

import numpy as np

from . import songanalyse
from .quellen import ABTASTRATE

HOP = songanalyse.HOP                        # 10 ms
N_FFT = songanalyse.N_FFT
FENSTER_S = 8.0                              # Tempo und Schläge: die letzten 8 s
LANG_S = 16.0                                # halbes oder doppeltes Tempo: die letzten 16 s (Snare auf 2 und 4)
OKTAVE_ALLE = 8                              # so oft (2 s) wird die Oktave geprüft ...
OKTAVE_MAL = 3                               # ... und so oft hintereinander muss sie dasselbe sagen
RECHNEN_ALLE = 25                            # Messpunkte (0,25 s)
PRUEFEN_ALLE = 4                             # jede vierte Rechnung (1 s) das Tempo auf 2/3 und 12/8 prüfen
MIN_S = 3.0                                  # so viel Musik braucht die erste Schätzung
SICHER_ABSTAND_S = 0.35                      # Beats so kurz vor "jetzt" sind noch unsicher
GLEICH = 0.04                                # 4 % Unterschied gelten als dasselbe Tempo
START_MAL = 6                                # so oft dasselbe Tempo, dann geht der Takt los (1,5 s)
KLAR_START = 0.1                             # so klar muss der Takt dafür sein
WECHSEL_MAL = 12                             # so oft hintereinander (3 s) ein ganz anderes Tempo: Es gilt
VERWANDT = (1.5, 2 / 3, 4 / 3, 0.75, 3.0, 1 / 3)   # dasselbe Raster, nur anders gezählt (halb/doppelt: Oktave)
EBENE_MAL = 32                               # so oft hintereinander ein verwandtes Tempo (8 s), dann gilt es
EBENE_MAL_ANFANG = 12                        # in den ersten 30 s nach dem Start reichen 3 s (der Start kann irren)
ANFANG = 120                                 # Rechnungen (30 s)
SAMMELN = 0.03                               # Anteil jeder neuen Rechnung an der gesammelten Autokorrelation (~8 s)
NACHZIEHEN = 0.5                             # wie stark eine neue Vorhersage die Uhr verschiebt
SPRUNG_AB = 0.25                             # ab so viel einer Periode daneben gilt es als Sprung ...
SPRUNG_MAL = 3                               # ... und wird erst nach so vielen gleichen Rechnungen übernommen
STILLE_DB = 25.0                             # so viel leiser als die Musik vorher: Stille
CHROMA_HOP = HOP * 5                         # Tonklassen alle 50 ms (wie bei der Probe)
EINS_MAL = 3                                 # so viele Rechnungen merkt sich die Eins
EINS_VERGESSEN = 0.9                         # pro Rechnung (2 s) bleibt so viel von den alten Punkten (~20 s)
EINS_ABSTAND = 0.05                          # so viel mehr Punkte als die zweitbeste Stelle braucht die Eins


class TaktFolger:
    name = "takt"
    ist_uhr = True                           # liefert selbst einen gleichmäßigen Takt (keine Beat-Uhr nötig)

    def __init__(self):
        self.filter = songanalyse._baender(N_FFT, 40, 30.0, 11000.0)
        self.fenster = np.hanning(N_FFT).astype(np.float32)
        self.puffer = np.zeros(N_FFT // 2, np.float32)       # wie offline: der erste Messpunkt liegt bei 0 s
        self.baender: deque = deque(maxlen=int(LANG_S * songanalyse.RATE))
        self.pegel: deque = deque(maxlen=int(FENSTER_S * songanalyse.RATE))
        self.oktaven: deque = deque(maxlen=OKTAVE_MAL)          # letzte Ergebnisse der Oktav-Prüfung
        self.messpunkte = 0
        self.proben = 0
        self.seit_rechnung = 0
        self.rechnungen = 0
        self.fehler_gemeldet = -999.0
        self.klarheit_jetzt = 1.0                             # wie klar der Takt in den letzten 8 s ist (0 bis 1)
        self.pruef_roh: Optional[float] = None               # letzte Prüfung: so viel BPM kam roh heraus
        self.pruefungen: deque = deque(maxlen=4)              # Ergebnisse der letzten Prüfungen (Faktor)
        self.pruef_faktor = 1.0                               # so viel schneller ist es wirklich
        self.max_lag = int(60 * songanalyse.RATE / 60.0 * 4) + 2
        self.ak_summe: Optional[np.ndarray] = None
        self.ak_anzahl = 0
        self.seit_start = 0                                   # Rechnungen, seit das Tempo feststeht
        self.tempo = 0.0
        self.kandidat: Optional[float] = None
        self.kandidat_mal = 0
        self.andere_ebene = 0                                 # so oft hintereinander halbes/doppeltes Tempo gemessen
        self.naechster: Optional[float] = None               # Zeit des nächsten Beats (Sekunden seit Beginn)
        self.spruenge = 0                                     # so oft hintereinander lag die Vorhersage weit daneben
        self.sprung = 0.0
        self.periode: Optional[float] = None
        # Takt-Eins
        self.chroma_filter = songanalyse._chroma_filter(songanalyse.N_FFT_CHROMA)
        self.chroma_fenster = np.hanning(songanalyse.N_FFT_CHROMA).astype(np.float32)
        self.ton = np.zeros(songanalyse.N_FFT_CHROMA, np.float32)   # die letzten Proben (für die Tonklassen)
        self.chroma: deque = deque(maxlen=int(LANG_S * songanalyse.RATE / 5))
        self.chroma_naechste = 0                              # Nummer des nächsten Tonklassen-Messpunkts
        self.ausgegeben: deque = deque(maxlen=64)             # (Zeit, Nummer) der ausgegebenen Beats
        self.beat_nummer = 0
        self.eins_phase: Optional[int] = None                 # Beat-Nummer modulo 4 der Eins
        self.eins_stimmen: deque = deque(maxlen=EINS_MAL)
        self.eins_punkte = np.zeros(4)                        # gesammelte Punkte je Beat-Nummer modulo 4
        self.takt_eins = False                                # der Beat in diesem Block ist eine Eins

    # --- Ton rein ----------------------------------------------------------------

    def verarbeite(self, block: np.ndarray):
        """Gibt (Beat in diesem Block?, Tempo in BPM) zurück."""
        self.puffer = np.concatenate([self.puffer, block.astype(np.float32)])
        while len(self.puffer) >= N_FFT:
            betrag = np.abs(np.fft.rfft(self.puffer[:N_FFT] * self.fenster))
            self.puffer = self.puffer[HOP:]
            with np.errstate(all="ignore"):
                band = np.log1p(1e4 * ((betrag ** 2) @ self.filter.T))
            self.baender.append(np.nan_to_num(band))
            self.pegel.append(float(10 * np.log10(np.mean(np.expm1(band) / 1e4) + 1e-12)))
            self.messpunkte += 1
            self.seit_rechnung += 1
        self.proben += len(block)
        self._tonklassen(block)
        jetzt = self.proben / ABTASTRATE
        if self.seit_rechnung >= RECHNEN_ALLE and len(self.baender) >= MIN_S * songanalyse.RATE:
            self.seit_rechnung = 0
            try:
                self._rechnen(jetzt)
            except Exception:
                # Sicherer Rückfall: Ein Rechenfehler darf nie den Ton anhalten. Neu einzählen und weiter.
                if jetzt - self.fehler_gemeldet >= 60.0:      # ins Logbuch höchstens einmal pro Minute
                    logging.exception("Takt-Folger")
                    self.fehler_gemeldet = jetzt
                self.neu_anfangen()
        beat, self.takt_eins = False, False
        if self.naechster is not None and self.periode:
            if jetzt >= self.naechster:
                beat = True
                self.beat_nummer += 1
                self.ausgegeben.append((self.naechster, self.beat_nummer))
                self.takt_eins = self.eins_phase is not None and self.beat_nummer % 4 == self.eins_phase
                self.naechster += self.periode
                while self.naechster <= jetzt:               # weit zurück (Rechner hing): aufholen, nicht nachfeuern
                    self.naechster += self.periode
        tempo = 60.0 / self.periode if self.periode else self.tempo
        return beat, tempo

    def neu_anfangen(self) -> None:
        """Ein neuer Song beginnt (nach Applaus oder Stille): alles vergessen, neu einzählen."""
        self.naechster, self.periode, self.ak_summe = None, None, None
        self.tempo, self.kandidat, self.kandidat_mal, self.andere_ebene = 0.0, None, 0, 0
        self.pruefungen.clear()
        self.pruef_faktor, self.pruef_roh = 1.0, None
        self.oktaven.clear()
        self.eins_phase = None
        self.eins_stimmen.clear()
        self.eins_punkte[:] = 0

    def _tonklassen(self, block: np.ndarray) -> None:
        """Tonklassen (Chroma) alle 50 ms, wie bei der Probe: Messpunkt j liegt bei j * 50 ms."""
        n = songanalyse.N_FFT_CHROMA
        self.ton = np.concatenate([self.ton, block.astype(np.float32)])[-2 * n:]
        while self.chroma_naechste * CHROMA_HOP + n // 2 <= self.proben:
            ende = self.chroma_naechste * CHROMA_HOP + n // 2          # Probe-Nummer hinter dem Fenster
            von = len(self.ton) - (self.proben - ende) - n
            stueck = self.ton[max(0, von):von + n] if von + n > 0 else np.zeros(0, np.float32)
            if len(stueck) < n:
                stueck = np.concatenate([np.zeros(n - len(stueck), np.float32), stueck])
            betrag = np.abs(np.fft.rfft(stueck * self.chroma_fenster))
            with np.errstate(all="ignore"):
                self.chroma.append(np.nan_to_num(np.log1p(100 * betrag) @ self.chroma_filter.T))
            self.chroma_naechste += 1

    def _eins(self, lang: np.ndarray, jetzt: float) -> None:
        """Welcher der ausgegebenen Beats ist die Eins? Über die letzten 16 s, Mehrheit aus drei Rechnungen."""
        start = (self.messpunkte - len(lang)) / songanalyse.RATE
        chroma = np.asarray(self.chroma)
        chroma_start = (self.chroma_naechste - len(chroma)) * CHROMA_HOP / ABTASTRATE
        beginn = max(start, chroma_start)
        beats = [(t, n) for t, n in self.ausgegeben if beginn + 0.1 <= t <= jetzt - 0.6]
        if len(beats) < 12 or len(chroma) < 20:
            return
        baender = lang[int(round((beginn - start) * songanalyse.RATE)):]
        chroma = chroma[int(round((beginn - chroma_start) * songanalyse.RATE / 5)):]
        zeiten = np.array([t for t, _ in beats]) - beginn
        punkte = songanalyse.takt_eins_punkte(baender, chroma, zeiten)
        # Die Punkte sammeln sich über den Song (16 s sind für sich allein oft zweideutig).
        self.eins_punkte *= EINS_VERGESSEN
        for v in range(4):
            self.eins_punkte[beats[v][1] % 4] += punkte[v]
        self.eins_stimmen.append(1)
        reihe = np.sort(self.eins_punkte)
        if len(self.eins_stimmen) >= 2 and reihe[-1] - reihe[-2] >= EINS_ABSTAND * reihe[-1]:
            self.eins_phase = int(np.argmax(self.eins_punkte))

    # --- Rechnen (alle 0,25 s) ---------------------------------------------------------

    def _still(self) -> bool:
        pegel = np.asarray(self.pegel)
        letzte = pegel[-int(2 * songanalyse.RATE):]
        return float(np.max(letzte)) < float(np.percentile(pegel, 90)) - STILLE_DB

    def _tempo_waehlen(self, neu: float, klarheit: float) -> None:
        if self.tempo <= 0:
            if klarheit < KLAR_START:
                return
            if self.kandidat and abs(neu / self.kandidat - 1) < GLEICH:
                self.kandidat_mal += 1
            else:
                self.kandidat, self.kandidat_mal = neu, 1
            if self.kandidat_mal >= START_MAL:
                self.tempo, self.kandidat, self.kandidat_mal, self.seit_start = neu, None, 0, 0
            return
        self.seit_start += 1
        verhaeltnis = neu / self.tempo
        if abs(verhaeltnis - 1) < GLEICH:
            self.tempo += (neu - self.tempo) * 0.3              # die Band wird schneller oder langsamer
            self.kandidat, self.kandidat_mal, self.andere_ebene = None, 0, 0
            return
        if abs(verhaeltnis / 2 - 1) < GLEICH or abs(verhaeltnis * 2 - 1) < GLEICH:
            return                      # halb oder doppelt: entscheidet die Oktav-Prüfung (Snare), nicht die Schätzung
        if any(abs(verhaeltnis / f - 1) < GLEICH for f in VERWANDT):
            # Halb, doppelt, zwei Drittel ...: dasselbe Raster, anders gezählt. Umschalten nur, wenn es
            # lange gleich so bleibt (dann war schon der Anfang falsch, zum Beispiel ein ruhiges Intro).
            if self.kandidat and abs(neu / self.kandidat - 1) < GLEICH:
                self.andere_ebene += 1
            else:
                self.kandidat, self.andere_ebene = neu, 1
            self.kandidat_mal = 0
            if self.andere_ebene >= (EBENE_MAL_ANFANG if self.seit_start < ANFANG else EBENE_MAL):
                self.tempo, self.kandidat, self.andere_ebene = neu, None, 0
                self.naechster = None
            return
        self.andere_ebene = 0
        if self.kandidat and abs(neu / self.kandidat - 1) < GLEICH:
            self.kandidat_mal += 1
        else:
            self.kandidat, self.kandidat_mal = neu, 1
        if self.kandidat_mal >= WECHSEL_MAL:
            self.tempo, self.kandidat, self.kandidat_mal = self.kandidat, None, 0
            self.naechster = None                               # neues Tempo: neu einrasten

    def _oktave(self, lang: np.ndarray) -> None:
        """Halbes oder doppeltes Tempo? Wie bei der Probe entscheidet die Snare (2 und 4), über 16 s.
        Umgestellt wird erst, wenn drei Prüfungen hintereinander dasselbe sagen."""
        ergebnis = songanalyse.oktave_pruefen(lang, songanalyse.tempo_kurve(lang), self.tempo)
        self.oktaven.append(round(ergebnis / self.tempo, 2))
        if len(self.oktaven) == OKTAVE_MAL and len(set(self.oktaven)) == 1 and self.oktaven[0] != 1.0:
            self.tempo *= self.oktaven[0]
            self.oktaven.clear()
            self.naechster = None

    def _korrektur(self, einsatz: np.ndarray, roh: float) -> float:
        """Zwei Drittel (Punk) oder Achtel (12/8) erwischt? Geprüft wird bei neuem Tempo und sonst jede Sekunde.
        Eine Korrektur gilt erst, wenn drei der letzten vier Prüfungen sie ergeben (ein einzelnes
        Fenster kann sich irren), und sie bleibt, bis drei von vier etwas anderes sagen."""
        faellig = (self.tempo <= 0 or self.pruef_roh is None or abs(roh / self.pruef_roh - 1) >= GLEICH
                   or self.rechnungen % PRUEFEN_ALLE == 0)
        if faellig:
            geprueft = songanalyse.gruppen_pruefen(einsatz, songanalyse.dreier_pruefen(einsatz, roh))
            self.pruef_roh = roh
            self.pruefungen.append(round(geprueft / roh, 2))
            werte = list(self.pruefungen)
            haeufig = max(set(werte), key=werte.count)
            if werte.count(haeufig) >= 3:
                self.pruef_faktor = haeufig
        return self.pruef_faktor

    def _rechnen(self, jetzt: float) -> None:
        if self._still():
            self.klarheit_jetzt = 0.0
            self.naechster, self.periode, self.ak_summe = None, None, None
            self.oktaven.clear()
            self.eins_phase = None
            self.eins_stimmen.clear()
            self.eins_punkte[:] = 0
            return
        lang = np.asarray(self.baender, np.float32)
        baender = lang[-int(FENSTER_S * songanalyse.RATE):]
        start = (self.messpunkte - len(baender)) / songanalyse.RATE
        einsatz = songanalyse.einsatz_kurve(baender)
        # Tempo: Die Autokorrelation sammelt sich über den Song an (wie bei der Probe über den ganzen Song),
        # so sagen einzelne wirre Stellen nicht gleich ein anderes Tempo.
        kurve_t = songanalyse.tempo_kurve(baender)
        ak = songanalyse._autokorrelation(kurve_t, self.max_lag) if len(kurve_t) > self.max_lag else None
        # Wie klar ist der Takt gerade jetzt (nur dieses Fenster)? Für die Rede-Erkennung.
        self.klarheit_jetzt = songanalyse.tempo_aus_autokorrelation(ak)[1] if ak is not None else 0.0
        if ak is not None:
            # Am Anfang zählt jede Rechnung gleich viel (das Intro soll nicht allein bestimmen), später die
            # letzten Sekunden mehr.
            self.ak_anzahl = 1 if self.ak_summe is None else self.ak_anzahl + 1
            anteil = max(SAMMELN, 1.0 / self.ak_anzahl)
            self.ak_summe = ak if self.ak_summe is None else self.ak_summe * (1 - anteil) + ak * anteil
        roh, klarheit = songanalyse.tempo_aus_autokorrelation(self.ak_summe if self.ak_summe is not None
                                                              else np.zeros(1))
        self.rechnungen += 1
        self._tempo_waehlen(roh * self._korrektur(einsatz, roh), klarheit)
        if self.tempo <= 0:
            return
        if self.rechnungen % OKTAVE_ALLE == 0 and len(lang) >= 0.75 * LANG_S * songanalyse.RATE:
            self._oktave(lang)
        if self.rechnungen % OKTAVE_ALLE == OKTAVE_ALLE // 2 and self.periode:
            self._eins(lang, jetzt)
        beats = songanalyse.beats_finden(einsatz, self.tempo) + start
        sicher = beats[beats <= jetzt - SICHER_ABSTAND_S][-8:]
        if len(sicher) < 4:
            return
        nummer = np.arange(len(sicher))
        periode, null = np.polyfit(nummer, sicher, 1)
        soll = 60.0 / self.tempo
        if not 0.85 * soll <= periode <= 1.15 * soll:
            periode = soll
        letzter = null + periode * nummer[-1]
        schritte = max(1, math.ceil((jetzt - letzter) / periode))
        vorhersage = letzter + schritte * periode
        if self.naechster is None or self.periode is None:
            self.naechster, self.periode = vorhersage, periode
            return
        # Abweichung zum geplanten Beat (höchstens eine halbe Periode). Kleine Abweichungen sanft nachziehen.
        # Eine große (der andere Schlag des Takts, ein Achtel daneben) erst nach dreimaliger Bestätigung,
        # dann ganz: halb nachziehen landete genau zwischen zwei Schlägen.
        abweichung = (vorhersage - self.naechster + periode / 2) % periode - periode / 2
        if abs(abweichung) <= SPRUNG_AB * periode:
            self.naechster += NACHZIEHEN * abweichung
            self.spruenge = 0
        else:
            gleich = self.spruenge and abs(abweichung - self.sprung) <= SPRUNG_AB * periode
            self.spruenge, self.sprung = (self.spruenge + 1 if gleich else 1), abweichung
            if self.spruenge >= SPRUNG_MAL:
                self.naechster += abweichung
                self.spruenge = 0
        self.periode += (periode - self.periode) * 0.3
