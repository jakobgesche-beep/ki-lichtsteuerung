"""Song-Erkennung: Welcher der geprobten Songs wird gerade gespielt, und an welcher Stelle?

Das Programm hört ständig mit, auch wenn noch kein Song läuft. Die letzten 10 Sekunden werden mit allen
Probe-Aufnahmen verglichen (Harmonie und Rhythmus wie beim Song-Folger, in drei Tempi). Als erkannt
gilt ein Song erst, wenn

    er deutlich besser passt als jeder andere geprobte Song,
    die Stelle in ihm eindeutig ist (viel besser als der Rest desselben Songs),
    und das 3 Sekunden lang so bleibt und dabei gleichmäßig weiterläuft wie eine Band
    (die Stelle rückt mit der Zeit vor, höchstens 0,5 s plus 8 % daneben).

Außerdem muss es im Mittel gut genug passen (Kosten höchstens 0,33; richtige Songs lagen bis 0,28).

Gemessen an 10 Kunstsongs und "Hh" (Live-Fassungen: gleich, 4 % schneller, anderer Klang mit Hall und Publikum;
Start nach 1 s, nach 30 s und mitten im Song): 98 von 99 richtig erkannt, im Mittel nach 9 Sekunden Musik, nie ein
falscher Song. 4 fremde Kunstsongs und Publikum allein: 1 Fehlalarm von 17, bei einem fremden Song in derselben
Tonart, im selben Tempo und mit fast denselben Akkorden wie ein geprobter. (Bis 2.1: 60 von 99, weil Rauschen wie
bestimmte Töne aussah, siehe folgen.Merkmale.) Mit 6 statt 10 Sekunden und 2 statt 3 Sekunden Bestätigung gab es
3 Fehlalarme in 8 Versuchen.

Lieber kein Song als der falsche: Spielt die Band etwas, das nicht geprobt wurde, wird nichts erkannt.
Bei Stille, Reden oder Klatschen wird gar nicht erst verglichen.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Optional

import numpy as np

from . import folgen

RATE = folgen.RATE                 # 20 Messpunkte pro Sekunde
SCHRITT = 2                        # verglichen wird jeder zweite Messpunkt (100 ms): reicht und ist schnell
FENSTER_S = 10.0
MIN_MUSIK_S = 6.0                  # so viel Musik muss im Fenster sein
TEMPI = (0.94, 1.0, 1.06)
SICHER_MAL = 6                     # so oft hintereinander gleich (alle 0,5 s geprüft): 3 Sekunden
ABSTAND_SONGS = 0.04               # so viel besser als der zweitbeste Song
SCHAERFE = 0.12                    # so viel besser als der Durchschnitt der anderen Stellen im selben Song
MAX_KOSTEN = 0.33                  # so schlecht darf es im Mittel höchstens passen (richtige Songs: bis 0,28)
GEWICHT = (0.97 ** np.arange(int(FENSTER_S * RATE / SCHRITT))[::-1]).astype(np.float32)


class SongErkenner:
    def __init__(self):
        self.referenzen: dict = {}          # Name -> Merkmale der Probe (jeder zweite Messpunkt)
        self.sperre = threading.Lock()
        self.merkmale = folgen.Merkmale()
        self.fenster: deque = deque(maxlen=int(FENSTER_S * RATE))     # (Vektor, Pegel)
        self.oben: Optional[float] = None   # lautester Pegel zuletzt (fällt langsam)
        self.kandidat: Optional[tuple] = None   # (Name, Ende in Messpunkten der Probe, Zeit)
        self.mal = 0
        self.kosten_summe = 0.0
        self.letztes: Optional[dict] = None     # letzte Prüfung, für die Anzeige
        self.zuletzt_ton: Optional[float] = None

    # --- Probe-Aufnahmen -------------------------------------------------------

    def referenz(self, name: str, merkmale: np.ndarray) -> None:
        with self.sperre:
            self.referenzen[name] = np.ascontiguousarray(merkmale[::SCHRITT], np.float32)

    def entfernen(self, name: str) -> None:
        with self.sperre:
            self.referenzen.pop(name, None)

    def zuruecksetzen(self) -> None:
        with self.sperre:
            self.fenster.clear()
            self.merkmale = folgen.Merkmale()
            self.kandidat, self.mal, self.letztes = None, 0, None

    # --- Ton (Audio-Thread, muss schnell sein) --------------------------------------

    def hoeren(self, block: np.ndarray, jetzt: float) -> None:
        punkte = self.merkmale.dazu(block)
        with self.sperre:
            self.zuletzt_ton = jetzt
            for vektor, pegel in punkte:
                self.fenster.append((vektor, pegel))
                self.oben = pegel if self.oben is None else max(pegel, self.oben - 0.02)

    # --- Vergleichen (eigener Thread, alle 0,5 s) -------------------------------------

    def _musik_im_fenster(self) -> Optional[np.ndarray]:
        """Die Messpunkte, wenn genug Musik darin ist (nicht Stille, nicht nur ein kurzes Klatschen)."""
        if len(self.fenster) < MIN_MUSIK_S * RATE or self.oben is None:
            return None
        pegel = np.array([p for _, p in self.fenster])
        schwelle = max(self.oben - 25.0, -60.0)
        if np.mean(pegel > schwelle) < 0.75:
            return None
        return np.array([v for v, _ in self.fenster], np.float32)[::-1][::SCHRITT][::-1]

    @staticmethod
    def _kosten(band: np.ndarray, probe: np.ndarray) -> np.ndarray:
        with np.errstate(all="ignore"):
            harmonie = band[:, :12] @ probe[:, :12].T
        rhythmus = np.abs(band[:, None, 12:] - probe[None, :, 12:]).sum(axis=2)
        return (1.0 - harmonie + 0.3 * rhythmus).astype(np.float32)

    def _song_vergleichen(self, band: np.ndarray, probe: np.ndarray) -> Optional[tuple]:
        """Beste Stelle in einem Song: (Kosten, Ende in Messpunkten der Probe, Schärfe)."""
        anzahl = len(band)
        if len(probe) <= anzahl:
            return None
        kosten = self._kosten(band, probe)
        enden = np.arange(anzahl, len(probe))
        alter = np.arange(anzahl)[::-1]
        gewicht = GEWICHT[-anzahl:]
        beste = None
        alle = np.full(len(enden), np.inf, np.float32)
        for tempo in TEMPI:
            stellen = np.rint(enden[:, None] - alter[None, :] * tempo).astype(int)
            gueltig = stellen >= 0
            werte = kosten[np.arange(anzahl)[None, :], np.clip(stellen, 0, len(probe) - 1)]
            werte = (np.where(gueltig, werte, 1.5) * gewicht).sum(axis=1) / gewicht.sum()
            alle = np.minimum(alle, werte)
        i = int(np.argmin(alle))
        weg = np.abs(enden - enden[i]) > 2.0 * RATE / SCHRITT        # mehr als 2 s daneben
        schaerfe = float(np.median(alle[weg]) - alle[i]) if weg.any() else 0.0
        beste = (float(alle[i]), int(enden[i]), schaerfe)
        return beste

    def pruefen(self, jetzt: float, ohne: Optional[str] = None) -> Optional[dict]:
        """Vergleicht und gibt einen Song zurück, sobald er sicher erkannt ist (sonst None).

        ohne: dieser Song läuft gerade und zählt nicht (gesucht wird nur ein anderer)."""
        with self.sperre:
            band = self._musik_im_fenster()
            referenzen = {n: r for n, r in self.referenzen.items() if n != ohne}
        if band is None or not referenzen:
            self.kandidat, self.mal = None, 0
            self.letztes = {"art": "hoert" if band is None else "keine_songs"}
            return None
        ergebnisse = []
        for name, probe in referenzen.items():
            treffer = self._song_vergleichen(band, probe)
            if treffer is not None:
                ergebnisse.append((treffer[0], name, treffer[1], treffer[2]))
        if not ergebnisse:
            return None
        ergebnisse.sort()
        kosten, name, ende, schaerfe = ergebnisse[0]
        abstand = ergebnisse[1][0] - kosten if len(ergebnisse) > 1 else 1.0
        eindeutig = schaerfe >= SCHAERFE and abstand >= ABSTAND_SONGS
        self.letztes = {"art": "vergleicht", "name": name, "kosten": round(kosten, 3), "schaerfe": round(schaerfe, 3),
                        "abstand": round(abstand, 3), "eindeutig": eindeutig}
        if not eindeutig:
            self.kandidat, self.mal = None, 0
            return None
        # Läuft die Stelle gleichmäßig weiter wie eine Band? Gemessen ab der ersten Prüfung: Das Ende rückt um
        # die vergangene Zeit vor, höchstens 0,5 s plus 8 % daneben (eine Band spielt nie viel schneller als geprobt).
        if self.kandidat is not None and self.kandidat[0] == name:
            vergangen = jetzt - self.kandidat[2]
            erwartet = self.kandidat[1] + vergangen * RATE / SCHRITT
            if abs(ende - erwartet) <= (0.5 + 0.08 * vergangen) * RATE / SCHRITT:
                self.mal += 1
                self.kosten_summe += kosten
            else:
                self.mal, self.kandidat, self.kosten_summe = 1, (name, ende, jetzt), kosten
        else:
            self.mal, self.kandidat, self.kosten_summe = 1, (name, ende, jetzt), kosten
        if self.mal < SICHER_MAL:
            return None
        mittel = self.kosten_summe / self.mal
        self.mal, self.kosten_summe = 0, 0.0
        if mittel > MAX_KOSTEN:
            self.kandidat = None
            return None
        stelle = ende * SCHRITT / RATE + folgen.VERZOEGERUNG_S
        return {"name": name, "stelle": stelle, "schaerfe": round(schaerfe, 3), "abstand": round(abstand, 3),
                "kosten": round(mittel, 3)}
