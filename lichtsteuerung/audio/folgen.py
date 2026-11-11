"""Song-Folger: Weiß live, an welcher Stelle im Song die Band gerade ist.

Man drückt einmal Start, wenn die Band anfängt (etwas zu früh oder zu spät ist egal: Die Uhr
beginnt erst, wenn die Band wirklich spielt). Dann vergleicht das Programm alle 50 ms die letzten
4 Sekunden der Band mit der Probe-Aufnahme: Harmonie (welche Töne klingen) und Rhythmus (wo
Instrumente einsetzen), an allen Stellen in der Nähe und in sieben Tempi. So folgt es der Band,
auch wenn sie schneller oder langsamer spielt, anders klingt oder das Publikum laut ist.
Alle halbe Sekunde sucht es zusätzlich im ganzen Song: Lässt die Band einen Teil aus oder
wiederholt einen, springt es nach etwa 2 Sekunden an die richtige Stelle.

Die Stelle, die das Licht benutzt, läuft wie eine Uhr weiter und wird nur sanft
nachgezogen. So springt das Licht nie hin und her:

    hört gut mit     Die Uhr folgt der Band (bis 25 % schneller oder langsamer).
    unsicher         Die Uhr läuft im zuletzt gemessenen Tempo weiter.
    kein Ton         Die Uhr läuft im Tempo der Probe weiter (sicherer Rückfall).
    Band hört auf    Nach 3 Sekunden Stille wartet die Uhr, bis wieder Musik kommt.

Von Hand korrigieren geht immer: "Nächster Teil jetzt" setzt die Stelle an den
Anfang des nächsten Teils, das Mithören sucht dann von dort aus weiter.

Gemessen mit der echten Probe-Aufnahme "Hh" und daraus gebauten Live-Fassungen (schneller,
langsamer, anderer Klang mit Hall und Publikum, Teil ausgelassen, Refrain doppelt):
siehe ANNAHMEN.md, Abschnitt Song-Folger 2.0.
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
FENSTER_S = 4.0            # so viele Sekunden der Band werden auf einmal mit der Probe verglichen
TEMPO_SCHRITTE = np.array([-0.06, -0.04, -0.02, 0.0, 0.02, 0.04, 0.06])
UEBERALL_ALLE = 10         # alle 10 Messpunkte (0,5 s) im ganzen Song suchen: hat die Band einen Teil ausgelassen?
UEBERALL_BESSER = 0.08     # so viel besser muss eine andere Stelle passen ...
UEBERALL_MAL = 4           # ... und so oft hintereinander (2 s), dann springt das Mithören dorthin
START_SUCHE_S = (1.0, 4.0) # beim Start: etwas vor bis 4 s nach dem Musikanfang der Probe
MAX_ABWEICHUNG = 0.25      # die Uhr läuft höchstens 25 % schneller oder langsamer
NACHZIEHEN = 0.6           # wie kräftig die Uhr pro Sekunde zum Gehörten gezogen wird
SPRUNG_S = 4.0             # so weit daneben, sicher und lange genug: dann springt die Uhr
STRAFE = 0.15
VERGESSEN = 0.95           # wie schnell alte Messpunkte an Gewicht verlieren (0,95: Gedächtnis rund 1 Sekunde)
VERZOEGERUNG_S = FENSTER / ABTASTRATE   # ein Messpunkt beschreibt den Ton bis jetzt: Ende des Fensters zählt
SPRUNG_NACH_S = 2.5
STILLE_WARTEN_S = 3.0      # so lange Stille, dann wartet die Uhr auf die Band
REAKTION_S = 0.7           # spielt die Band schon beim Drücken: so viel früher hat sie wohl angefangen


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


def _dicht(laut: np.ndarray, rate: float = RATE) -> np.ndarray:
    """Wo ist es fast durchgehend laut (mindestens 70 % von 0,4 s)? Einzähl-Klicks sind das nicht."""
    breite = max(2, int(0.4 * rate))
    anteil = np.convolve(laut.astype(float), np.ones(breite) / breite, mode="full")[breite - 1:breite - 1 + len(laut)]
    return anteil >= 0.7


def musik_anfang(pegel: np.ndarray, rate: float = RATE) -> int:
    """Erster Messpunkt, an dem Musik beginnt.

    Verglichen wird mit dem Rauschen ganz am Anfang der Aufnahme (man drückt ja
    vor der Band auf Aufnahme), nicht mit dem lauten Refrain. So zählt auch ein
    leises Gitarren-Intro schon als Musik. Einzelne Klicks (Einzählen mit den
    Sticks) zählen nicht: Musik ist fast durchgehend über der Schwelle.
    """
    if len(pegel) == 0:
        return 0
    pegel = np.asarray(pegel, float)
    breite = max(1, int(0.5 * rate))
    leistung = 10 ** (pegel / 10)
    glatt = 10 * np.log10(np.convolve(leistung, np.ones(breite) / breite, mode="full")[:len(leistung)] + 1e-12)
    vorlauf = np.sort(glatt[: max(3, int(1.5 * rate))])
    grund = float(np.mean(vorlauf[: max(1, len(vorlauf) // 3)]))
    if grund > np.percentile(glatt, 50) - 6.0:
        return 0                                  # die Aufnahme beginnt schon mit Musik
    dicht = _dicht(pegel > grund + 8.0, rate)
    treffer = np.flatnonzero(dicht)
    return int(treffer[0]) if len(treffer) else 0


W = int(FENSTER_S * RATE)
GEWICHT = (0.96 ** np.arange(W)[::-1]).astype(np.float32)     # neueste Messpunkte zählen am meisten


class SongFolger:
    """Folgt der Band durch einen Song. Alle Zeiten in Sekunden der Probe-Aufnahme.

    Mithören: Die letzten 4 Sekunden der Band werden mit der Probe verglichen, an allen Stellen in der Nähe
    und in sieben Tempi (bis 6 % schneller oder langsamer als zuletzt). So verliert ein kurzer lauter Moment
    (Publikum, Rückkopplung) nichts. Alle halbe Sekunde wird zusätzlich im ganzen Song gesucht: Lässt die
    Band einen Teil aus oder wiederholt einen, findet das Mithören die neue Stelle.
    """

    def __init__(self, referenz: np.ndarray, pegel: np.ndarray):
        self.ref = referenz.astype(np.float32)
        self.ref_pegel = pegel
        self.n = len(referenz)
        self.anfang = musik_anfang(pegel) / RATE
        unten, oben = (np.percentile(pegel, 2), np.percentile(pegel, 95)) if len(pegel) else (-90, -20)
        self.stille_db = min(unten + 0.4 * (oben - unten), oben - 12.0)
        self.ref_laut = float(np.percentile(pegel, 50)) if len(pegel) else -30.0
        self.sperre = threading.Lock()
        self.laeuft = False
        self._zuruecksetzen(self.anfang)

    def _zuruecksetzen(self, stelle: float) -> None:
        self.merkmale = Merkmale()
        self.stelle = stelle                  # die Stelle, die das Licht benutzt
        self.gehoert: Optional[float] = None  # wo das Mithören die Band gerade vermutet
        self.pos = stelle * RATE - 1          # Messpunkt der Probe zum neuesten Messpunkt der Band
        self.fenster = []
        self.sicher = 0.0
        self.eindeutig = 0.0
        self.rate = 1.0
        self.rate_lang = 1.0                  # wie schnell die Band im Vergleich zur Probe spielt
        self.wartet = False
        self.zuletzt_ton: Optional[float] = None
        self.stille_seit = 0.0
        self.daneben_seit = 0.0
        self.live_pegel_oben = None
        self.bereit = False                   # Start gedrückt, aber die Band spielt noch nicht
        self.gedrueckt = 0.0
        self.start_pegel = []
        self.zaehler = 0
        self.sprung_ziel: Optional[float] = None
        self.sprung_mal = 0
        self.sofort_springen = False
        self.erwartet = self.pos              # wo die Band ungefähr sein müsste (läuft gleichmäßig weiter)
        self.typisch: Optional[float] = None  # wie gut die Band zur Probe passt, wenn alles stimmt

    # --- Steuerung ------------------------------------------------------

    def starten(self, stelle: Optional[float] = None, jetzt: Optional[float] = None) -> None:
        """Ohne Stelle: Der Song beginnt, sobald die Band spielt (Start darf etwas zu früh oder zu spät kommen)."""
        with self.sperre:
            self._zuruecksetzen(self.anfang if stelle is None else stelle)
            self.laeuft = True
            self.bereit = stelle is None
            self.gedrueckt = jetzt if jetzt is not None else 0.0

    def jetzt_los(self, jetzt: float) -> None:
        """Von Hand: Die Band spielt jetzt (zum Beispiel, wenn sie sehr leise anfängt)."""
        with self.sperre:
            if self.bereit:
                self._losgehen(jetzt, jetzt)

    def setzen(self, stelle: float) -> None:
        """Von Hand: hier sind wir jetzt. Das Mithören sucht ab hier weiter."""
        with self.sperre:
            self.stelle = max(0.0, min(stelle, self.n / RATE))
            self.pos = self.erwartet = self.stelle * RATE - 1
            self.gehoert, self.sicher, self.daneben_seit = None, 0.0, 0.0
            self.wartet = self.bereit = False
            self.fenster = []
            self.sprung_mal = 0

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
        if self.bereit and not self._band_spielt(pegel, jetzt):
            return
        if pegel < self._live_stille(pegel):
            self.stille_seit += 1 / RATE
            return
        self.stille_seit = 0.0
        if self.wartet:
            # Die Band spielt wieder: von der wartenden Stelle aus neu hören
            self.wartet = False
            self.fenster = []
            self.pos = self.erwartet = self.stelle * RATE - 1
        self.fenster.append(vektor)
        self.fenster = self.fenster[-W:]
        self.pos += self.rate_lang
        self.erwartet += self.rate_lang
        self._abgleichen()
        self.zaehler += 1
        if self.zaehler % UEBERALL_ALLE == 0 and len(self.fenster) >= W // 2:
            self._ueberall_suchen()

    def _band_spielt(self, pegel: float, jetzt: float) -> bool:
        """Nach Start: Spielt die Band schon? Fast durchgehend deutlich lauter als vorher, oder so laut wie Musik."""
        if not self.gedrueckt:
            self.gedrueckt = jetzt
        self.start_pegel.append((jetzt, pegel))
        werte = np.array([p for _, p in self.start_pegel])
        breite = max(2, int(0.4 * RATE))
        if len(werte) < breite:
            return False
        leistung = 10 ** (werte / 10)
        glatt = 10 * np.log10(np.convolve(leistung, np.ones(breite) / breite, mode="valid") + 1e-12)
        schwelle = min(float(glatt.min()) + 10.0, max(-55.0, self.ref_laut - 18.0))
        laut = werte > schwelle
        if laut[-breite:].mean() < 0.7:
            return False
        i = len(laut) - breite
        while i > 0 and laut[max(0, i - breite):i].mean() >= 0.5:
            i -= 1
        beginn = self.start_pegel[i][0] if i > 0 else self.start_pegel[0][0] - REAKTION_S
        self._losgehen(beginn, jetzt)
        return True

    def _losgehen(self, beginn: float, jetzt: float) -> None:
        self.bereit = False
        self.stelle = self.anfang + max(0.0, jetzt - beginn)
        self.pos = self.erwartet = self.stelle * RATE - 1
        self.fenster = []

    def _live_stille(self, pegel: float) -> float:
        """Still ist es, wenn es viel leiser ist als die Band zuletzt war (oder fast nichts kommt)."""
        if self.live_pegel_oben is None:
            self.live_pegel_oben = pegel
        self.live_pegel_oben = max(pegel, self.live_pegel_oben - 0.05)     # fällt langsam, steigt sofort
        return max(self.live_pegel_oben - 30.0, -75.0)

    # --- Vergleichen ---------------------------------------------------------

    def _kosten(self, band: np.ndarray, von: int, bis: int) -> np.ndarray:
        """Wie schlecht passt jeder Messpunkt der Band zu jedem Messpunkt der Probe (0 = genau gleich)."""
        probe = self.ref[von:bis]
        with np.errstate(all="ignore"):
            harmonie = band[:, :12] @ probe[:, :12].T
        rhythmus = np.abs(band[:, None, 12:] - probe[None, :, 12:]).sum(axis=2)
        return (1.0 - harmonie + 0.3 * rhythmus).astype(np.float32)

    def _entlang(self, kosten: np.ndarray, von: int, enden: np.ndarray, rate: float) -> np.ndarray:
        """Mittlere Kosten, wenn die Band bei `enden` steht und mit `rate` gespielt hat (gewichtet: neu zählt mehr)."""
        anzahl = len(self.fenster)
        alter = np.arange(anzahl)[::-1]
        stellen = np.rint(enden[:, None] - alter[None, :] * rate).astype(int) - von
        gueltig = (stellen >= 0) & (stellen < kosten.shape[1])
        stellen = np.clip(stellen, 0, kosten.shape[1] - 1)
        werte = kosten[np.arange(anzahl)[None, :], stellen]
        werte = np.where(gueltig, werte, 1.5)
        gewicht = GEWICHT[-anzahl:]
        return (werte * gewicht).sum(axis=1) / gewicht.sum()

    def _abgleichen(self) -> None:
        if self.n < 3 or len(self.fenster) < 3:
            return
        band = np.asarray(self.fenster, np.float32)
        anzahl = len(band)
        breite = int(SUCHE_S * RATE)
        mitte = self.erwartet
        e_von, e_bis = max(0, int(mitte) - breite), min(self.n - 1, int(mitte) + breite)
        if e_bis <= e_von:
            return
        raten = np.clip(self.rate_lang * (1 + TEMPO_SCHRITTE), 0.75, 1.3)
        von = max(0, int(e_von - (anzahl - 1) * raten.max()) - 1)
        kosten = self._kosten(band, von, e_bis + 1)
        enden = np.arange(e_von, e_bis + 1)
        tabelle = np.vstack([self._entlang(kosten, von, enden, r) for r in raten])
        # Weiter wie bisher ist wahrscheinlicher als ein Sprung: In Songs wiederholt sich vieles.
        abweichung = (enden - mitte) / RATE
        bewertung = tabelle + 0.01 * abweichung ** 2
        t, e = np.unravel_index(int(np.argmin(bewertung)), bewertung.shape)
        beste = float(tabelle[t, e])
        # Feiner als ein Messpunkt: Parabel durch die Nachbarn
        fein = 0.0
        if 0 < e < len(enden) - 1:
            a, b, c = bewertung[t, e - 1], bewertung[t, e], bewertung[t, e + 1]
            nenner = a - 2 * b + c
            if nenner > 1e-9:
                fein = float(np.clip(0.5 * (a - c) / nenner, -0.5, 0.5))
        neu = enden[e] + fein
        # Eindeutig? Wie viel schlechter passt die beste Stelle, die mehr als 1 s daneben liegt?
        weg = np.abs(enden - enden[e]) > RATE
        anderswo = tabelle[:, weg]
        abstand = float(anderswo.min() - beste) if anderswo.size else 1.0
        eindeutig = float(np.clip((abstand - 0.01) * 10.0, 0.0, 1.0))
        nah = abs(neu - self.pos) < 0.5 * RATE        # rückt die Schätzung gleichmäßig vor?
        self.eindeutig += (eindeutig - self.eindeutig) * 0.1
        voll = min(1.0, anzahl / (2 * RATE))          # erst nach 2 s Band ganz sicher
        gut = 1.0 if self.typisch is None else float(np.clip(1.0 - (beste - self.typisch - 0.03) * 8, 0.2, 1.0))
        ziel = voll * (0.4 + 0.6 * self.eindeutig) * (1.0 if nah else 0.3) * gut
        self.sicher += (ziel - self.sicher) * 0.15
        self.pos = neu
        self.gehoert = self.pos / RATE + VERZOEGERUNG_S
        # Die Erwartung folgt dem Gehörten, umso schneller, je sicherer es ist. Hängt das Mithören fest,
        # läuft sie weiter und zieht es mit: Ein Hängenbleiben wird so immer teurer.
        self.erwartet += (self.pos - self.erwartet) * (0.02 + 0.2 * self.sicher * self.eindeutig)
        if self.sicher > 0.6 and anzahl >= W // 2:
            self.rate_lang += (float(raten[t]) - self.rate_lang) * 0.05
            self.typisch = beste if self.typisch is None else self.typisch + (beste - self.typisch) * 0.02

    def _ueberall_suchen(self) -> None:
        """Passt eine ganz andere Stelle im Song deutlich besser? (Teil ausgelassen oder wiederholt)"""
        band = np.asarray(self.fenster, np.float32)
        kosten = self._kosten(band, 0, self.n)
        enden = np.arange(len(band), self.n, 2)
        if len(enden) == 0:
            return
        werte = self._entlang(kosten, 0, enden, self.rate_lang)
        hier = (int(np.clip(round(self.pos), enden[0], enden[-1])) - enden[0]) // 2
        nahe = slice(max(0, hier - int(0.25 * RATE)), hier + int(0.25 * RATE) + 1)
        jetzt_kosten = float(werte[nahe].min())
        # Unter fast gleich guten Stellen die nächste nehmen (Refrain 3 statt Refrain 1)
        abstand = np.abs(enden - self.pos) / RATE
        kandidat = int(np.argmin(werte + 0.002 * abstand))
        ziel = float(enden[kandidat])
        typisch = self.typisch if self.typisch is not None else float(np.percentile(werte, 5))
        verloren = jetzt_kosten > typisch + UEBERALL_BESSER          # hier passt es gerade schlecht ...
        dort_gut = werte[kandidat] < typisch + 0.03                  # ... dort so gut wie beim normalen Mithören
        if (abs(ziel - self.pos) > 2.5 * RATE and verloren and dort_gut
                and werte[kandidat] < jetzt_kosten - UEBERALL_BESSER):
            if self.sprung_ziel is not None and abs(ziel - (self.sprung_ziel + UEBERALL_ALLE * self.rate_lang)) < RATE:
                self.sprung_mal += 1
            else:
                self.sprung_mal = 1
            self.sprung_ziel = ziel
            if self.sprung_mal >= UEBERALL_MAL:
                self.pos = self.erwartet = ziel
                self.gehoert = self.pos / RATE + VERZOEGERUNG_S
                self.sicher = max(self.sicher, 0.7)
                self.sofort_springen = True
                self.sprung_mal, self.sprung_ziel = 0, None
        else:
            self.sprung_mal, self.sprung_ziel = 0, None

    # --- Die Uhr fürs Licht (Show-Thread) --------------------------------------

    def takt(self, dauer: float, jetzt: float) -> float:
        """Rückt die Stelle weiter. Gibt die Stelle in Sekunden der Probe zurück."""
        with self.sperre:
            if not self.laeuft:
                return self.stelle
            if self.bereit:
                # Kommt gar kein Ton an (Eingang weg), wartet die Uhr nicht: Sie läuft ab dem Drücken.
                if not self.gedrueckt:
                    self.gedrueckt = jetzt
                if self.zuletzt_ton is None and jetzt - self.gedrueckt > 0.5:
                    self.bereit = False
                    self.stelle = self.anfang + (jetzt - self.gedrueckt)
                    self.pos = self.erwartet = self.stelle * RATE - 1
                else:
                    return self.stelle
            ton_da = self.zuletzt_ton is not None and jetzt - self.zuletzt_ton < 0.5
            if ton_da and self.stille_seit >= STILLE_WARTEN_S and not self._probe_still(self.stelle):
                self.wartet = True               # Band hat aufgehört: warten, bis sie weiterspielt
            if self.wartet:
                return self.stelle
            if self.sofort_springen and self.gehoert is not None:
                self.sofort_springen = False
                self.stelle, self.daneben_seit = self.gehoert, 0.0
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
        if self.bereit:
            art = "bereit"
        elif not ton_da:
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
