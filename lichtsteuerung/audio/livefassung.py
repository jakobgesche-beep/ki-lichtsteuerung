"""Live-Fassungen einer Probe-Aufnahme: für die Generalprobe (und für Tests).

Aus der Aufnahme wird ein Ton gebaut, der so klingen könnte wie beim Konzert:

    Tempo      etwas schneller oder langsamer gespielt (die Tonhöhe bleibt gleich)
    Saal       anderer Klang: mehr Bass, weniger Höhen, Hall
    Publikum   Gemurmel und Klatschen, vor dem Song und während des Songs

Für jede Stelle im Live-Ton ist bekannt, welche Stelle der Probe gerade läuft. So lässt sich messen,
wie genau Song-Erkennung und Song-Folger treffen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .quellen import ABTASTRATE as RATE


def dehnen(ton: np.ndarray, faktor: float, n: int = 2048, toleranz: int = 512) -> np.ndarray:
    """Schneller (faktor > 1) oder langsamer spielen, ohne dass sich die Tonhöhe ändert (WSOLA).

    Kurze Stücke werden überlappend aneinandergelegt. Jedes Stück wird in der Nähe so gewählt,
    dass es möglichst nahtlos an das vorige passt."""
    ton = np.asarray(ton, np.float32)
    halb = n // 2
    schritt = halb * faktor
    fenster = np.hanning(n).astype(np.float32)
    anzahl = int((len(ton) - n - toleranz) / schritt)
    if anzahl <= 1:
        return ton.copy()
    aus = np.zeros(anzahl * halb + n, np.float32)
    norm = np.zeros_like(aus)
    groesse = 1 << int(np.ceil(np.log2(2 * toleranz + 2 * n)))
    vorher = 0
    for k in range(anzahl):
        soll = int(k * schritt)
        pos = soll
        if k:
            ziel = ton[vorher + halb: vorher + halb + n]
            von, bis = max(0, soll - toleranz), min(len(ton) - n, soll + toleranz)
            if len(ziel) == n and bis > von:
                bereich = ton[von: bis + n]
                korrelation = np.fft.irfft(np.fft.rfft(bereich, groesse) * np.conj(np.fft.rfft(ziel, groesse)), groesse)
                pos = von + int(np.argmax(korrelation[: bis - von + 1]))
        aus[k * halb: k * halb + n] += ton[pos: pos + n] * fenster
        norm[k * halb: k * halb + n] += fenster
        vorher = pos
    norm[norm < 1e-3] = 1.0
    return aus / norm


def falten(ton: np.ndarray, kern: np.ndarray) -> np.ndarray:
    """Schnelle Faltung in Blöcken (für Klangfilter und Hall)."""
    block = 1 << 16
    groesse = 1 << int(np.ceil(np.log2(block + len(kern))))
    spektrum = np.fft.rfft(kern, groesse)
    aus = np.zeros(len(ton) + len(kern), np.float32)
    for a in range(0, len(ton), block):
        stueck = np.fft.irfft(np.fft.rfft(ton[a:a + block], groesse) * spektrum, groesse)[: block + len(kern)]
        aus[a: a + len(stueck)] += stueck[: len(aus) - a].astype(np.float32)
    return aus[: len(ton)]


def klangfilter(punkte: list, laenge: int = 2049) -> np.ndarray:
    """Filter aus Frequenzpunkten [(Hz, dB), ...], dazwischen gleichmäßig verbunden."""
    frequenz = np.fft.rfftfreq(laenge * 2, 1 / RATE)
    hz = np.array([p[0] for p in punkte], float)
    db = np.array([p[1] for p in punkte], float)
    verstaerkung = 10 ** (np.interp(np.log10(np.maximum(frequenz, 1)), np.log10(hz), db) / 20)
    kern = np.fft.irfft(verstaerkung)
    kern = np.roll(kern, laenge)[: 2 * laenge - 1] * np.hanning(2 * laenge - 1)
    return kern.astype(np.float32)


def hall(nachhall_s: float = 1.2, anteil: float = 0.35, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(nachhall_s * RATE)
    zeit = np.arange(n) / RATE
    antwort = rng.standard_normal(n) * np.exp(-6.9 * zeit / nachhall_s)
    antwort = antwort / np.sqrt(np.sum(antwort ** 2)) * anteil
    antwort[0] += 1.0
    return antwort.astype(np.float32)


def publikum(laenge: int, seed: int = 5) -> np.ndarray:
    """Gemurmel, Klatschen und Rufe, ungefähr wie ein Schulpublikum."""
    rng = np.random.default_rng(seed)
    rauschen = rng.standard_normal(laenge, dtype=np.float32)
    murmeln = falten(rauschen, klangfilter([(20, -30), (200, 0), (1000, 0), (3000, -12), (20000, -40)]))
    zeit = np.arange(laenge, dtype=np.float32) / RATE
    murmeln *= 0.6 + 0.4 * np.sin(2 * np.pi * 3.7 * zeit + rng.uniform(0, 6)) * np.sin(2 * np.pi * 0.31 * zeit)
    klatschen = np.zeros(laenge, np.float32)
    huelle = np.exp(-np.arange(800) / 150).astype(np.float32)
    for start in rng.integers(0, max(1, laenge - 4000), size=max(1, laenge // RATE * 3)):
        klatschen[start:start + 800] += rng.standard_normal(800, dtype=np.float32) * huelle * rng.uniform(0.5, 2)
    return murmeln / (np.std(murmeln) + 1e-9) + 0.3 * klatschen


def mischen(ton: np.ndarray, stoerung: np.ndarray, abstand_db: float) -> np.ndarray:
    """Störung dazu: abstand_db = wie viel lauter die Musik ist (10 dB: gut zu hören, 3 dB: sehr laut im Saal)."""
    p_ton = float(np.mean(ton ** 2)) + 1e-12
    p_stoerung = float(np.mean(stoerung ** 2)) + 1e-12
    return (ton + stoerung * np.sqrt(p_ton / p_stoerung / 10 ** (abstand_db / 10))).astype(np.float32)


@dataclass
class LiveFassung:
    ton: np.ndarray
    musik_ab_s: float          # ab hier spielt die Band im Live-Ton
    musik_bis_s: float
    probe_von_s: float         # diese Stelle der Probe läuft bei musik_ab_s
    tempo: float               # 1.03 = 3 % schneller als in der Probe

    def probe_zeit(self, live_s: float) -> Optional[float]:
        """Welche Stelle der Probe läuft im Live-Ton bei live_s? (None: dort spielt die Band nicht)"""
        if not self.musik_ab_s <= live_s < self.musik_bis_s:
            return None
        return self.probe_von_s + (live_s - self.musik_ab_s) * self.tempo

    def live_zeit(self, probe_s: float) -> Optional[float]:
        """Wann kommt die Stelle probe_s der Probe im Live-Ton? (None: gar nicht)"""
        live = self.musik_ab_s + (probe_s - self.probe_von_s) / self.tempo
        return live if self.musik_ab_s <= live < self.musik_bis_s else None


def bauen(ton: np.ndarray, von_s: float, bis_s: float, tempo: float = 1.0, anderer_mix: bool = False,
          nachhall_s: float = 0.0, publikum_db: Optional[float] = None, vorlauf_s: float = 4.0,
          nachlauf_s: float = 3.0, seed: int = 0) -> LiveFassung:
    """Baut die Live-Fassung: vorher etwas Saal (Publikum), dann die Band ab von_s der Probe, danach Saal.

    anderer_mix: mehr Bass, weniger Höhen (anderes Mischpult, andere Boxen).
    nachhall_s: Hall wie in einer Aula (0 = keiner). publikum_db: wie viel lauter die Band als das Publikum ist."""
    stueck = np.asarray(ton[int(von_s * RATE): int(bis_s * RATE)], np.float32)
    if abs(tempo - 1.0) > 1e-3:
        stueck = dehnen(stueck, tempo)
    vorne = int(vorlauf_s * RATE)
    live = np.concatenate([np.zeros(vorne, np.float32), stueck, np.zeros(int(nachlauf_s * RATE), np.float32)])
    if anderer_mix:
        live = falten(live, klangfilter([(20, 0), (80, 6), (300, 2), (2000, -3), (6000, -10), (20000, -20)]))
    if nachhall_s > 0:
        live = falten(live, hall(nachhall_s, 0.4, seed=seed + 3))
    if publikum_db is not None:
        live = mischen(live, publikum(len(live), seed=seed + 5), publikum_db)
    return LiveFassung(live.astype(np.float32), vorne / RATE, (vorne + len(stueck)) / RATE, von_s, tempo)
