"""Musik-Analyse: Macht aus Ton-Blöcken ein paar einfache Zahlen.

    beat        gerade ist ein Schlag
    tempo_bpm   Schläge pro Minute
    bass, mitte, hoehe     wie stark diese Bereiche sind, je 0 bis 1
    energie     geglättete Gesamtenergie, 0 bis 1
    leise, rede sind die Regeln für das ruhige Grundlicht

Bass, Mitten und Höhen kommen aus einer eigenen FFT mit numpy. Den Beat liefert
aubio. Lässt sich aubio nicht installieren, springt EigeneBeatErkennung ein.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .quellen import ABTASTRATE, BLOCK

FFT_LAENGE = 1024         # kurz, damit Bass und Höhen kaum Verzögerung haben
BEAT_FFT = 512
BAENDER = {"bass": (20, 150), "mitte": (150, 2000), "hoehe": (2000, 16000)}
LEISE_PEGEL = 10 ** (-45 / 20)     # unter -45 dB gilt es als Stille
RUHE_S = 0.8                       # so lange muss es still sein
KEIN_BEAT_S = 3.0                  # so lange ohne Beat, bevor es Rede sein kann


@dataclass
class Messwerte:
    beat: bool = False
    tempo_bpm: float = 0.0
    bass: float = 0.0
    mitte: float = 0.0
    hoehe: float = 0.0
    energie: float = 0.0
    pegel: float = 0.0
    leise: bool = True
    rede: bool = False
    spannung: float = 0.0      # 0 bis 1: wie stark sich gerade ein Drop aufbaut
    vor_drop: bool = False     # die kurze Pause direkt vor dem Drop
    drop: bool = False         # genau jetzt schlägt der Drop ein (nur in einem Block wahr)
    intensitaet: float = 0.0   # 0 bis 1: wie stark diese Stelle im Vergleich zum Rest des Songs ist


class AubioBeatErkennung:
    name = "aubio"

    def __init__(self):
        import aubio
        self.tempo = aubio.tempo("default", 1024, BLOCK, ABTASTRATE)

    def verarbeite(self, block: np.ndarray):
        beat = bool(self.tempo(block.astype(np.float32))[0])
        return beat, float(self.tempo.get_bpm())


class EigeneBeatErkennung:
    """Einfacher Ersatz für aubio: Ein Beat ist ein plötzlicher Sprung im Spektrum."""

    name = "eigene"

    def __init__(self):
        self.letztes = np.zeros(BEAT_FFT // 2 + 1)
        self.verlauf = deque(maxlen=int(1.5 * ABTASTRATE / BLOCK))
        self.puffer = np.zeros(BEAT_FFT)
        self.fenster = np.hanning(len(self.puffer))
        self.seit_beat = 0
        self.sprungverlauf = deque(maxlen=int(8 * ABTASTRATE / BLOCK))
        self.tempo = 0.0
        self.bis_rechnung = 0

    def schaetze_tempo(self) -> float:
        """Sucht im Verlauf der Sprünge den Abstand, der sich am stärksten wiederholt.

        Das ist viel stabiler als einzelne Schläge zu zählen. Tempi um 120 BPM
        werden leicht bevorzugt, sonst landet man gern beim halben oder doppelten.
        """
        verlauf = np.array(self.sprungverlauf)
        verlauf = verlauf - verlauf.mean()
        spektrum = np.fft.rfft(verlauf, 2 * len(verlauf))
        wiederholung = np.fft.irfft(np.abs(spektrum) ** 2)
        rate = ABTASTRATE / BLOCK
        lags = np.arange(int(60 * rate / 180), int(60 * rate / 70) + 1)
        bpm = 60 * rate / lags
        vorliebe = np.exp(-0.5 * (np.log2(bpm / 120) / 0.8) ** 2)
        return float(bpm[np.argmax(wiederholung[lags] * vorliebe)])

    def verarbeite(self, block: np.ndarray):
        self.puffer = np.concatenate([self.puffer[len(block):], block])
        betrag = np.abs(np.fft.rfft(self.puffer * self.fenster))
        betrag = np.log1p(betrag * 10)
        sprung = float(np.maximum(betrag - self.letztes, 0).sum())
        self.letztes = betrag
        self.seit_beat += 1
        schwelle = np.mean(self.verlauf) + 1.8 * np.std(self.verlauf) if len(self.verlauf) > 20 else np.inf
        self.verlauf.append(sprung)
        kleinster_abstand = int(0.28 * ABTASTRATE / BLOCK)      # höchstens gut 210 BPM
        beat = sprung > schwelle and sprung > 1.0 and self.seit_beat >= kleinster_abstand
        if beat:
            self.seit_beat = 0
        self.sprungverlauf.append(sprung)
        self.bis_rechnung -= 1
        if self.bis_rechnung <= 0 and len(self.sprungverlauf) >= 2 * ABTASTRATE / BLOCK:
            self.tempo = self.schaetze_tempo()
            self.bis_rechnung = int(ABTASTRATE / BLOCK)     # einmal pro Sekunde reicht
        return beat, self.tempo


def beat_erkennung():
    try:
        return AubioBeatErkennung()
    except Exception:
        return EigeneBeatErkennung()


class BeatUhr:
    """Überbrückt Lücken: Auch aubio lässt mal einen Schlag aus, das Tempo stimmt aber.

    Jeder erkannte Schlag stellt die Uhr. Dazwischen tickt sie im Tempo weiter,
    aber nur kurz. Hört die Musik auf, hört auch die Uhr auf.
    """

    MAX_OHNE_ECHTEN_BEAT_S = 6.0

    def __init__(self):
        self.bis_naechstem = 0.0
        self.seit_ausgabe = 99.0
        self.seit_echtem = 99.0

    def takt(self, echter_beat: bool, tempo: float, dauer: float) -> bool:
        periode = 60.0 / tempo if 40.0 <= tempo <= 240.0 else 0.0
        self.bis_naechstem -= dauer
        self.seit_ausgabe += dauer
        self.seit_echtem = 0.0 if echter_beat else self.seit_echtem + dauer
        faellig = (periode > 0 and self.bis_naechstem <= 0
                   and self.seit_echtem < self.MAX_OHNE_ECHTEN_BEAT_S)
        if echter_beat:
            self.bis_naechstem = periode
            faellig = self.seit_ausgabe >= 0.5 * periode
        elif faellig:
            self.bis_naechstem += periode
        if faellig:
            self.seit_ausgabe = 0.0
        return faellig


class DropErkennung:
    """Erkennt einen echten Drop, nicht nur "es wird lauter".

    Zwei Wege führen zu einem Drop:
      Aufbau   Die Höhen werden 4 Sekunden lang stetig lauter (Riser, Snare-Wirbel),
               und der Wumms (Kick und Bass) ist deutlich leiser als sonst.
      Break    Mindestens 2 Sekunden ist der ganze Song deutlich leiser als sonst.
    Danach muss der Wumms schlagartig zurückkommen: viel lauter als eben und fast
    so laut wie die lautesten Stellen. Oft gibt es davor eine kurze Pause.

    "Wumms" heißt hier 40 bis 300 Hz. So geht es auch über kleine Lautsprecher
    und das Laptop-Mikrofon, die den ganz tiefen Bass gar nicht übertragen.
    Gerechnet wird mit echten Lautstärken in dB, 20-mal pro Sekunde.
    """

    RATE = 20                  # Messpunkte pro Sekunde (alle 50 ms)
    WUMMS_HZ = (40, 300)
    SPRUNG_DB = 4.0            # so viel lauter muss der Wumms schlagartig werden
    NAH_AN_MAX_DB = 8.0        # und dabei fast so laut wie die lautesten Stellen
    KIPP_DB = 8.0              # oder so viel bass-lastiger als eine halbe Sekunde vorher
    ANTEIL_DB = 3.0            # und sein Anteil am Klang fast so hoch wie an den bass-lastigsten Stellen
    AUFBAU_DB_PRO_S = 1.2      # so schnell steigen die Höhen in einem Aufbau mindestens
    WUMMS_WEG_DB = 6.0         # so viel leiser ist der Wumms im Aufbau
    AUFBAU_S = 4               # so viele Sekunden müssen die Höhen stetig steigen
    AUFBAU_MIN_DB = 6.0        # und dabei mindestens so viel lauter werden
    HOEHEN_ANTEIL_DB = 15.0    # höchstens so viel leiser als der Gesamtklang dürfen die Höhen sein
    BREAK_DB = 13.0            # so viel leiser ist ein Break (eine ruhige Strophe ist weniger leise)
    BREAK_S = 2.0              # mindestens so lang
    PAUSE_DB = 12.0            # so viel leiser ist die Pause vor dem Drop
    SPERRE_S = 15.0            # nach einem Drop kommt so schnell kein zweiter

    def __init__(self, frequenzen: np.ndarray):
        laenge = 30 * self.RATE
        self.wumms_maske = (frequenzen >= self.WUMMS_HZ[0]) & (frequenzen < self.WUMMS_HZ[1])
        self.wumms = deque(maxlen=laenge)
        self.hoch = deque(maxlen=laenge)
        self.gesamt = deque(maxlen=laenge)
        self.sammeln = []
        self.spannung = 0.0
        self.spannung_verlauf = deque(maxlen=6 * self.RATE)
        self.break_seit: Optional[float] = None
        self.break_zuletzt = -99.0
        self.letzter_drop = -99.0
        self.zeit = 0.0
        self.vor_drop = False
        self.im_break = False

    @staticmethod
    def _db(wert: float) -> float:
        return 20 * np.log10(wert + 1e-9)

    def verarbeite(self, spektrum: np.ndarray, masken: dict, dauer: float) -> bool:
        """Bekommt pro Block das Spektrum. Gibt True zurück, wenn genau jetzt der Drop kommt."""
        self.zeit += dauer
        self.sammeln.append((float(np.sqrt(np.mean(spektrum[self.wumms_maske] ** 2))),
                             float(np.sqrt(np.mean(spektrum[masken["hoehe"]] ** 2))),
                             float(np.sqrt(np.mean(spektrum ** 2)))))
        if len(self.sammeln) * dauer < 1 / self.RATE:
            return False
        wumms, hoch, gesamt = (self._db(float(np.mean(w))) for w in zip(*self.sammeln))
        self.sammeln = []
        self.wumms.append(wumms)
        self.hoch.append(hoch)
        self.gesamt.append(gesamt)
        return self._auswerten()

    def _sekundenmittel(self, werte: np.ndarray) -> np.ndarray:
        """Mittel über eine Sekunde: Zwischen zwei Kicks ist der Wumms sonst immer "weg"."""
        leistung = 10 ** (werte / 10)
        return 10 * np.log10(np.convolve(leistung, np.ones(self.RATE) / self.RATE, mode="valid") + 1e-12)

    def _auswerten(self) -> bool:
        if len(self.wumms) < 8 * self.RATE:
            return False                # erst nach 8 Sekunden genug Verlauf
        wumms = np.array(self.wumms)
        hoch = np.array(self.hoch)
        gesamt = np.array(self.gesamt)
        wumms_s = self._sekundenmittel(wumms)
        gesamt_s = self._sekundenmittel(gesamt)
        wumms_typisch = np.percentile(wumms_s, 80)
        gesamt_typisch = np.percentile(gesamt_s, 80)

        # Weg 1, Aufbau: Die Höhen steigen GLEICHMÄSSIG (nicht ein Sprung wie beim Refrain),
        # und der Wumms ist weg.
        fenster = self.AUFBAU_S * self.RATE
        steigung = np.polyfit(np.arange(fenster) / self.RATE, hoch[-fenster:], 1)[0]
        stufen = hoch[-fenster:].reshape(self.AUFBAU_S, self.RATE).mean(axis=1)
        schritte = np.diff(stufen)
        anstieg = stufen[-1] - stufen[0]
        gleichmaessig = ((schritte > 0).all() and anstieg >= self.AUFBAU_MIN_DB
                         and schritte.max() < 0.45 * anstieg
                         and stufen[-1] > gesamt[-self.RATE:].mean() - self.HOEHEN_ANTEIL_DB)
        # Im Aufbau sinkt der Anteil des Wumms am Gesamtklang, auch über kleine Lautsprecher,
        # wo das Rauschen vom Riser selbst etwas Wumms-Energie mitbringt.
        anteil = wumms_s - gesamt_s
        wumms_weg = (wumms_s[-self.RATE:].max() < wumms_typisch - self.WUMMS_WEG_DB
                     or anteil[-self.RATE:].max() < np.percentile(anteil, 80) - self.WUMMS_WEG_DB)
        ziel = min(1.0, max(0.0, steigung / self.AUFBAU_DB_PRO_S)) if (gleichmaessig and wumms_weg) else 0.0
        self.spannung = float(self.spannung + (ziel - self.spannung) * (0.3 if ziel > self.spannung else 0.05))
        self.spannung_verlauf.append(self.spannung)
        aufgebaut = max(self.spannung_verlauf) > 0.5

        # Weg 2, Break: eine Weile deutlich leiser als sonst.
        self.im_break = bool(gesamt_s[-1] < gesamt_typisch - self.BREAK_DB)
        if self.im_break:
            self.break_seit = self.break_seit if self.break_seit is not None else self.zeit
            if self.zeit - self.break_seit >= self.BREAK_S:
                self.break_zuletzt = self.zeit
        else:
            self.break_seit = None
        nach_break = self.zeit - self.break_zuletzt < 1.5

        # Pause: mitten im Aufbau plötzlich viel leiser.
        # bool() und float(): numpy-Werte lassen sich nicht an die Oberfläche schicken.
        self.vor_drop = bool(self.spannung > 0.4 and gesamt[-1] < gesamt[-3 * self.RATE:-self.RATE // 2].mean() - self.PAUSE_DB)

        # Drop: Der Wumms schlägt ein, viel lauter als eben, fast so laut wie die lautesten Stellen,
        # und der ganze Song schlägt mit ein.
        jetzt, eben = wumms[-1], wumms[-2 * self.RATE:-self.RATE // 5].mean()
        # Eine Snare ist Rauschen über alle Frequenzen. Im Moment des Drops dagegen ist der
        # Wumms-Anteil am Klang so hoch wie an den bass-lastigsten Stellen des ganzen Songs.
        # Das gilt über eine gute Anlage genauso wie über einen Handy-Lautsprecher.
        anteil = wumms - gesamt
        bass_lastig = anteil[-1] > np.percentile(anteil, 90) - self.ANTEIL_DB
        laut = jetzt > np.percentile(wumms, 90) - self.NAH_AN_MAX_DB
        # Lauter als eben, oder (über kleine Lautsprecher) plötzlich viel bass-lastiger als eben.
        sprung = jetzt > eben + self.SPRUNG_DB or anteil[-1] > anteil[-self.RATE // 2:-1].mean() + self.KIPP_DB
        einschlag = bass_lastig and laut and sprung
        if (aufgebaut or nach_break) and einschlag and self.zeit - self.letzter_drop > self.SPERRE_S:
            self.letzter_drop = self.zeit
            self.spannung = 0.0
            self.spannung_verlauf.clear()
            self.break_zuletzt = -99.0
            self.vor_drop = False
            return True
        return False

    def diagnose(self) -> dict:
        """Für den Mitschnitt: was die Erkennung gerade sieht."""
        if not self.wumms:
            return {}
        return {"wumms_db": round(float(self.wumms[-1]), 1), "hoehen_db": round(float(self.hoch[-1]), 1),
                "gesamt_db": round(float(self.gesamt[-1]), 1), "spannung": round(self.spannung, 2),
                "break": self.im_break, "vor_drop": self.vor_drop}


class Analyse:
    def __init__(self, beat=None):
        self.beat = beat or beat_erkennung()
        self.uhr = BeatUhr()
        self.puffer = np.zeros(FFT_LAENGE, dtype=np.float32)
        self.fenster = np.hanning(FFT_LAENGE)
        frequenzen = np.fft.rfftfreq(FFT_LAENGE, 1 / ABTASTRATE)
        self.masken = {n: (frequenzen >= von) & (frequenzen < bis) for n, (von, bis) in BAENDER.items()}
        self.spitzen = {name: 1e-4 for name in BAENDER}
        self.werte = {name: 0.0 for name in BAENDER}
        self.pegel_spitze = 1e-3
        self.energie = 0.0
        self.pegel_glatt = 0.0
        self.zeit_still = 0.0
        self.zeit_ohne_beat = KEIN_BEAT_S
        self.tempo = 0.0
        self.anteil_mitte = 0.0
        self.drops = DropErkennung(frequenzen)
        self.energie_verlauf = deque(maxlen=60 * 10)    # eine Minute, zehnmal pro Sekunde
        self.bis_energie_merken = 0

    def verarbeite(self, block: np.ndarray) -> Messwerte:
        dauer = len(block) / ABTASTRATE
        beat, tempo = self.beat.verarbeite(block)
        if tempo > 0:
            self.tempo = tempo
        self.puffer = np.concatenate([self.puffer[len(block):], block])
        spektrum = np.abs(np.fft.rfft(self.puffer * self.fenster))

        for name, maske in self.masken.items():
            staerke = float(np.sqrt(np.mean(spektrum[maske] ** 2)))
            # Automatische Anpassung: Die Spitze der letzten Zeit gilt als 1.
            self.spitzen[name] = max(staerke, self.spitzen[name] * 0.9995, 1e-4)
            ziel = staerke / self.spitzen[name]
            # Schnell nach oben, langsam nach unten: So pumpt das Licht mit dem Bass.
            alt = self.werte[name]
            self.werte[name] = ziel if ziel > alt else alt + (ziel - alt) * 0.15

        drop = self.drops.verarbeite(spektrum, self.masken, dauer)

        pegel = float(np.sqrt(np.mean(block ** 2)))
        self.pegel_glatt += (pegel - self.pegel_glatt) * 0.1
        self.pegel_spitze = max(self.pegel_glatt, self.pegel_spitze * 0.99995, 1e-3)
        roh = self.pegel_glatt / self.pegel_spitze
        self.energie += (roh - self.energie) * 0.02

        # Intensität: Energie im Vergleich zur letzten Minute. So ist die lauteste Stelle
        # auch wirklich "Höhepunkt", egal wie laut das Mikrofon insgesamt ist.
        self.bis_energie_merken -= 1
        if self.bis_energie_merken <= 0:
            self.energie_verlauf.append(self.energie)
            self.bis_energie_merken = int(ABTASTRATE / BLOCK / 10)
        if len(self.energie_verlauf) > 50:
            unten, oben = np.percentile(self.energie_verlauf, (10, 95))
            intensitaet = float(min(1.0, max(0.0, (self.energie - unten) / max(oben - unten, 0.08))))
        else:
            intensitaet = float(min(1.0, self.energie))

        leise_jetzt = self.pegel_glatt < LEISE_PEGEL
        self.zeit_still = self.zeit_still + dauer if leise_jetzt else 0.0
        self.zeit_ohne_beat = 0.0 if beat else self.zeit_ohne_beat + dauer
        gesamt = sum(self.werte.values()) or 1.0
        self.anteil_mitte += (self.werte["mitte"] / gesamt - self.anteil_mitte) * 0.02
        leise = self.zeit_still >= RUHE_S
        # Grobe Schätzung. Sicher erkennt es später das X32 (offenes Rednerpult).
        rede = not leise and self.zeit_ohne_beat >= KEIN_BEAT_S and self.anteil_mitte > 0.45
        return Messwerte(beat=self.uhr.takt(beat, self.tempo, dauer), tempo_bpm=round(self.tempo, 1), bass=self.werte["bass"],
                         mitte=self.werte["mitte"], hoehe=self.werte["hoehe"],
                         energie=min(1.0, self.energie), pegel=pegel, leise=leise and not self.drops.vor_drop,
                         rede=rede and self.drops.spannung < 0.3, spannung=round(self.drops.spannung, 2),
                         vor_drop=self.drops.vor_drop, drop=drop, intensitaet=round(intensitaet, 3))
