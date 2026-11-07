"""Song-Folger: Weiß live, an welcher Stelle im Song die Band gerade ist.

Man drückt einmal Start, wenn die Band anfängt. Dann vergleicht das Programm
alle 50 ms, was es hört, mit der Probe-Aufnahme: Harmonie (welche Töne klingen)
und Rhythmus (wo setzen Instrumente ein). Das Verfahren heißt "online DTW"
(Dixon 2005): Es findet den Weg durch die Probe, der am besten zum Gehörten
passt, auch wenn die Band schneller oder langsamer spielt.

Die Stelle, die das Licht benutzt, läuft wie eine Uhr weiter und wird nur sanft
nachgezogen. So springt das Licht nie hin und her:

    hört gut mit     Die Uhr folgt der Band (bis 25 % schneller oder langsamer).
    unsicher         Die Uhr läuft im zuletzt gemessenen Tempo weiter.
    kein Ton         Die Uhr läuft im Tempo der Probe weiter (sicherer Rückfall).
    Band hört auf    Nach 3 Sekunden Stille wartet die Uhr, bis wieder Musik kommt.

Von Hand korrigieren geht immer: "Nächster Teil jetzt" setzt die Stelle an den
Anfang des nächsten Teils, das Mithören sucht dann von dort aus weiter.
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from .quellen import ABTASTRATE

HOP = 2205                 # alle 50 ms ein Messpunkt
FENSTER = 4096
RATE = ABTASTRATE / HOP    # 20 Messpunkte pro Sekunde
SUCHE_S = 6.0              # so weit vor und zurück sucht das Mithören
START_SUCHE_S = (1.0, 4.0) # beim Start: etwas vor bis 4 s nach dem Musikanfang der Probe
MAX_ABWEICHUNG = 0.25      # die Uhr läuft höchstens 25 % schneller oder langsamer
NACHZIEHEN = 0.6           # wie kräftig die Uhr pro Sekunde zum Gehörten gezogen wird
SPRUNG_S = 4.0             # so weit daneben, sicher und lange genug: dann springt die Uhr
SPRUNG_NACH_S = 2.5
STILLE_WARTEN_S = 3.0      # so lange Stille, dann wartet die Uhr auf die Band


def _chroma_filter() -> np.ndarray:
    freq = np.fft.rfftfreq(FENSTER, 1 / ABTASTRATE)
    gueltig = (freq >= 80) & (freq <= 4000)
    halbton = 69 + 12 * np.log2(np.maximum(freq, 1) / 440.0)
    filter_ = np.zeros((12, len(freq)), np.float32)
    for klasse in range(12):
        abstand = (halbton - klasse + 6) % 12 - 6
        filter_[klasse] = np.exp(-0.5 * (abstand / 0.4) ** 2) * gueltig
    return filter_


def _band_filter() -> np.ndarray:
    freq = np.fft.rfftfreq(FENSTER, 1 / ABTASTRATE)
    grenzen = (30, 150, 400, 1200, 3500, 11000)
    filter_ = np.zeros((len(grenzen) - 1, len(freq)), np.float32)
    for i, (von, bis) in enumerate(zip(grenzen, grenzen[1:])):
        filter_[i] = (freq >= von) & (freq < bis)
    return filter_ / np.maximum(filter_.sum(axis=1, keepdims=True), 1)


CHROMA = _chroma_filter()
BAENDER = _band_filter()
HANNING = np.hanning(FENSTER).astype(np.float32)


class Merkmale:
    """Macht aus Ton-Blöcken alle 50 ms einen Merkmal-Vektor. Gleich für Probe und live."""

    def __init__(self):
        self.puffer = np.zeros(0, np.float32)
        self.vorher = None

    def dazu(self, ton: np.ndarray) -> list:
        """Gibt die neuen Messpunkte zurück: Liste von (Vektor, Pegel in dB)."""
        self.puffer = np.concatenate([self.puffer, ton.astype(np.float32)])
        ergebnis = []
        while len(self.puffer) >= FENSTER:
            stueck = self.puffer[:FENSTER]
            self.puffer = self.puffer[HOP:]
            ergebnis.append(self._rahmen(stueck))
        return ergebnis

    def _rahmen(self, stueck: np.ndarray) -> tuple:
        betrag = np.abs(np.fft.rfft(stueck * HANNING))
        with np.errstate(all="ignore"):         # numpy 2.0 auf dem Mac meldet hier Fehlalarme
            chroma = np.log1p(100 * betrag) @ CHROMA.T
            baender = np.log10(((betrag ** 2) @ BAENDER.T) + 1e-10)
        chroma = np.maximum(chroma - chroma.mean(), 0)
        chroma = chroma / (np.linalg.norm(chroma) + 1e-9)
        # Rhythmus: wo die Bänder plötzlich lauter werden
        einsatz = np.zeros_like(baender) if self.vorher is None else np.maximum(baender - self.vorher, 0)
        self.vorher = baender
        einsatz = np.minimum(einsatz, 2.0) / 2.0
        pegel = float(10 * np.log10(np.mean(stueck ** 2) + 1e-12))
        return np.concatenate([chroma, 0.5 * einsatz]).astype(np.float32), pegel


def merkmale_der_aufnahme(ton: np.ndarray) -> tuple:
    """Alle Messpunkte einer ganzen Aufnahme: (Matrix, Pegel)."""
    m = Merkmale()
    punkte = m.dazu(ton)
    if not punkte:
        return np.zeros((0, 17), np.float32), np.zeros(0)
    return np.array([p[0] for p in punkte]), np.array([p[1] for p in punkte])


def musik_anfang(pegel: np.ndarray, rate: float = RATE) -> int:
    """Erster Messpunkt, an dem Musik beginnt.

    Verglichen wird mit dem Rauschen ganz am Anfang der Aufnahme (man drückt ja
    vor der Band auf Aufnahme), nicht mit dem lauten Refrain. So zählt auch ein
    leises Gitarren-Intro schon als Musik.
    """
    if len(pegel) == 0:
        return 0
    vorlauf = np.sort(pegel[: max(3, int(1.5 * rate))])
    grund = float(np.mean(vorlauf[: max(1, len(vorlauf) // 3)]))
    if grund > np.percentile(pegel, 50) - 6.0:
        return 0                                  # die Aufnahme beginnt schon mit Musik
    schwelle = grund + 8.0
    laut = pegel > schwelle
    halten = max(1, int(0.3 * rate))
    for i in range(len(laut) - halten):
        if laut[i:i + halten].all():
            return i
    return 0


class SongFolger:
    """Folgt der Band durch einen Song. Alle Zeiten in Sekunden der Probe-Aufnahme."""

    def __init__(self, referenz: np.ndarray, pegel: np.ndarray):
        self.ref = referenz.astype(np.float32)
        self.ref_pegel = pegel
        self.n = len(referenz)
        self.anfang = musik_anfang(pegel) / RATE
        unten, oben = (np.percentile(pegel, 2), np.percentile(pegel, 95)) if len(pegel) else (-90, -20)
        self.stille_db = min(unten + 0.4 * (oben - unten), oben - 12.0)
        self.sperre = threading.Lock()
        self.merkmale = Merkmale()
        self.stelle = self.anfang             # die Stelle, die das Licht benutzt
        self.gehoert: Optional[float] = None  # wo das Mithören die Band gerade vermutet
        self.sicher = 0.0
        self.rate = 1.0
        self.rate_lang = 1.0                  # wie schnell die Band im Vergleich zur Probe spielt
        self.laeuft = False
        self.wartet = False
        self.zuletzt_ton: Optional[float] = None
        self.stille_seit = 0.0
        self.daneben_seit = 0.0
        self.live_pegel_oben = None
        self.verlauf = []                     # die letzten Schätzungen, für die Sicherheit
        self._dtw_zuruecksetzen(self.anfang, START_SUCHE_S)

    # --- Steuerung ------------------------------------------------------

    def starten(self, stelle: Optional[float] = None) -> None:
        with self.sperre:
            self.stelle = self.anfang if stelle is None else stelle
            self.rate, self.rate_lang, self.sicher, self.gehoert = 1.0, 1.0, 0.0, None
            self.laeuft, self.wartet = True, False
            self.stille_seit = self.daneben_seit = 0.0
            self.merkmale = Merkmale()
            self.verlauf = []
            self._dtw_zuruecksetzen(self.stelle, START_SUCHE_S if stelle is None else (1.0, 1.0))

    def setzen(self, stelle: float) -> None:
        """Von Hand: hier sind wir jetzt. Das Mithören sucht ab hier weiter."""
        with self.sperre:
            self.stelle = max(0.0, min(stelle, self.n / RATE))
            self.gehoert, self.sicher, self.daneben_seit = None, 0.0, 0.0
            self.wartet = False
            self.verlauf = []
            self._dtw_zuruecksetzen(self.stelle, (1.0, 1.0))

    def stoppen(self) -> None:
        with self.sperre:
            self.laeuft = False

    # --- Ton von der Band (Audio-Thread) -------------------------------------

    def hoeren(self, block: np.ndarray, jetzt: float) -> None:
        if not self.laeuft:
            return
        for vektor, pegel in self.merkmale.dazu(block):
            with self.sperre:
                self._schritt(vektor, pegel, jetzt)

    def _schritt(self, vektor: np.ndarray, pegel: float, jetzt: float) -> None:
        self.zuletzt_ton = jetzt
        if pegel < self._live_stille(pegel):
            self.stille_seit += 1 / RATE
            return
        self.stille_seit = 0.0
        if self.wartet:
            # Die Band spielt wieder: von der wartenden Stelle aus neu suchen
            self.wartet = False
            self.verlauf = []
            self._dtw_zuruecksetzen(self.stelle, (1.0, 4.0))
        self._dtw(vektor)

    def _live_stille(self, pegel: float) -> float:
        """Still ist es, wenn es viel leiser ist als die Band zuletzt war (oder fast nichts kommt)."""
        if self.live_pegel_oben is None:
            self.live_pegel_oben = pegel
        self.live_pegel_oben = max(pegel, self.live_pegel_oben - 0.05)     # fällt langsam, steigt sofort
        return max(self.live_pegel_oben - 30.0, -75.0)

    # --- Online DTW -------------------------------------------------------

    def _dtw_zuruecksetzen(self, mitte_s: float, suche: tuple) -> None:
        self.d1 = np.full(self.n, np.inf, np.float32)     # Kosten bis zur letzten Spalte
        self.d2 = np.full(self.n, np.inf, np.float32)     # ... und der davor
        self.l1 = np.ones(self.n, np.float32)
        self.l2 = np.ones(self.n, np.float32)
        self.k1 = np.zeros(self.n, np.float32)            # Einzelkosten der letzten Spalte
        self.mitte = int(mitte_s * RATE)
        self.erwartet = float(self.mitte)
        self.start_von = max(0, int((mitte_s - suche[0]) * RATE))
        self.start_bis = min(self.n, int((mitte_s + suche[1]) * RATE) + 1)
        self.erste_spalte = True

    def _dtw(self, vektor: np.ndarray) -> None:
        if self.n < 3:
            return
        if self.erste_spalte:
            von, bis = self.start_von, self.start_bis
        else:
            breite = int(SUCHE_S * RATE)
            von, bis = max(0, self.mitte - breite), min(self.n, self.mitte + breite + 1)
        if bis - von < 2:
            return
        idx = np.arange(von, bis)
        with np.errstate(all="ignore"):
            harmonie = self.ref[von:bis, :12] @ vektor[:12]
        kosten = (1.0 - harmonie + 0.3 * np.abs(self.ref[von:bis, 12:] - vektor[12:]).sum(axis=1)).astype(np.float32)
        neu_d = np.full(self.n, np.inf, np.float32)
        neu_l = np.ones(self.n, np.float32)
        if self.erste_spalte:
            # Start im Suchbereich, eine Strafe für weit weg von der erwarteten Stelle
            neu_d[von:bis] = kosten + 0.1 * np.abs(idx - self.mitte) / RATE
            self.erste_spalte = False
        else:
            # Schritte: (1,1) normal, (2,1) Band schneller, (1,2) Band langsamer. Tempo-Wechsel kosten etwas.
            k_vorher = np.concatenate([[np.inf], kosten[:-1]])          # Kosten bei i-1 in dieser Spalte
            a = self._verschoben(self.d1, von, bis, 1) + kosten
            la = self._verschoben(self.l1, von, bis, 1) + 1
            b = self._verschoben(self.d1, von, bis, 2) + k_vorher + kosten + 0.15
            lb = self._verschoben(self.l1, von, bis, 2) + 2
            c = self._verschoben(self.d2, von, bis, 1) + self.k1[von:bis] + kosten + 0.15
            lc = self._verschoben(self.l2, von, bis, 1) + 2
            with np.errstate(invalid="ignore"):
                werte = np.vstack([a / la, b / lb, c / lc])
            werte = np.where(np.isfinite(werte), werte, np.inf)
            wahl = np.argmin(werte, axis=0)
            neu_d[von:bis] = np.choose(wahl, [a, b, c])
            neu_l[von:bis] = np.choose(wahl, [la, lb, lc])
        self.d2, self.l2 = self.d1, self.l1
        self.d1, self.l1 = neu_d, neu_l
        self.k1 = np.zeros(self.n, np.float32)
        self.k1[von:bis] = kosten
        with np.errstate(invalid="ignore"):
            normiert = neu_d[von:bis] / neu_l[von:bis]
        normiert = np.where(np.isfinite(normiert), normiert, np.inf)
        if not np.isfinite(normiert).any():
            return
        # Weiter wie bisher ist wahrscheinlicher als ein Sprung: In Songs wiederholt sich vieles.
        self.erwartet += self.rate_lang
        bewertung = normiert + 0.02 * np.abs(idx - self.erwartet) / RATE
        beste = int(np.argmin(bewertung))
        self.mitte = von + beste
        self.gehoert = self.mitte / RATE
        # Sicherheit: Rückt die Schätzung gleichmäßig vor (wie eine Band), oder springt sie?
        self.verlauf.append(self.mitte)
        self.verlauf = self.verlauf[-int(3 * RATE):]
        if len(self.verlauf) >= int(1.5 * RATE):
            schritte = np.diff(self.verlauf)
            ruhig = float(np.mean(np.abs(schritte - self.rate_lang) <= 1.01))
            weit = abs(self.mitte - self.erwartet) / RATE
            self.sicher = ruhig * float(np.clip(1.0 - weit / SUCHE_S, 0, 1))
            if self.sicher > 0.6:
                # Tempo der Band aus den letzten 3 Sekunden
                rate = (self.verlauf[-1] - self.verlauf[0]) / (len(self.verlauf) - 1)
                self.rate_lang += (min(1.2, max(0.8, rate)) - self.rate_lang) * 0.02
                self.erwartet += (self.mitte - self.erwartet) * 0.3
        if abs(self.mitte - self.erwartet) > 2 * RATE:
            self.erwartet += (self.mitte - self.erwartet) * 0.02

    @staticmethod
    def _verschoben(werte: np.ndarray, von: int, bis: int, schritt: int) -> np.ndarray:
        a, b = von - schritt, bis - schritt
        if a >= 0:
            return werte[a:b]
        return np.concatenate([np.full(-a, np.inf, werte.dtype), werte[0:b]])

    # --- Die Uhr fürs Licht (Show-Thread) --------------------------------------

    def takt(self, dauer: float, jetzt: float) -> float:
        """Rückt die Stelle weiter. Gibt die Stelle in Sekunden der Probe zurück."""
        with self.sperre:
            if not self.laeuft:
                return self.stelle
            ton_da = self.zuletzt_ton is not None and jetzt - self.zuletzt_ton < 0.5
            if ton_da and self.stille_seit >= STILLE_WARTEN_S and not self._probe_still(self.stelle):
                self.wartet = True               # Band hat aufgehört: warten, bis sie weiterspielt
            if self.wartet:
                return self.stelle
            ziel_rate = self.rate_lang if ton_da else 1.0
            if ton_da and self.gehoert is not None and self.sicher > 0.5:
                abstand = self.gehoert - self.stelle
                if abs(abstand) > SPRUNG_S and self.sicher > 0.8:
                    self.daneben_seit += dauer
                    if self.daneben_seit >= SPRUNG_NACH_S:
                        self.stelle, self.daneben_seit = self.gehoert, 0.0
                        return self.stelle
                else:
                    self.daneben_seit = 0.0
                ziel_rate = self.rate_lang + NACHZIEHEN * abstand
            ziel_rate = min(1 + MAX_ABWEICHUNG, max(1 - MAX_ABWEICHUNG, ziel_rate))
            self.rate += (ziel_rate - self.rate) * min(1.0, dauer * 3.0)
            self.stelle = min(self.n / RATE, self.stelle + dauer * self.rate)
            return self.stelle

    def _probe_still(self, stelle: float) -> bool:
        i = int(stelle * RATE)
        if not 0 <= i < len(self.ref_pegel):
            return True
        return bool(self.ref_pegel[max(0, i - 10):i + 10].mean() < self.stille_db)

    def zustand(self, jetzt: float) -> dict:
        ton_da = self.zuletzt_ton is not None and jetzt - self.zuletzt_ton < 0.5
        if not ton_da:
            art = "uhr"
        elif self.wartet:
            art = "wartet"
        elif self.sicher > 0.5:
            art = "hoert"
        else:
            art = "unsicher"
        return {"stelle": round(self.stelle, 2), "rate": round(self.rate, 3), "sicher": round(self.sicher, 2),
                "tempo_faktor": round(self.rate_lang, 3), "art": art,
                "gehoert": None if self.gehoert is None else round(self.gehoert, 2)}
