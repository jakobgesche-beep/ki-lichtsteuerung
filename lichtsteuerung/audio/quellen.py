"""Audio-Quellen. Jede liefert mit lies() den nächsten Block Ton als Zahlen.

    Testsignal   ein künstlicher Takt, braucht nichts außer numpy
    Datei        WAV, FLAC, MP3 und so weiter, läuft in Echtzeit und in Schleife
    Eingang      Mikrofon des Laptops oder später das X32 per USB

Wer eine neue Quelle bauen will, braucht nur lies() und schliessen().
"""
from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import Optional

import numpy as np

ABTASTRATE = 44100
BLOCK = 512           # 512 Werte sind rund 12 Millisekunden


class AudioFehler(Exception):
    """Die Quelle liefert nichts mehr. Die Engine geht dann aufs Grundlicht."""


class _Echtzeit:
    """Bremst Quellen, die sofort liefern könnten, auf echte Geschwindigkeit."""

    def __init__(self):
        self.naechster = time.monotonic()

    def warte(self) -> None:
        self.naechster += BLOCK / ABTASTRATE
        rest = self.naechster - time.monotonic()
        if rest > 0:
            time.sleep(rest)


def erzeuge_takt(bpm: float, sekunden: float, abtastrate: int = ABTASTRATE) -> np.ndarray:
    """Baut einen einfachen Takt: tiefer Schlag plus Rauschen auf jedem halben Beat."""
    laenge = int(sekunden * abtastrate)
    ton = np.zeros(laenge, dtype=np.float32)
    zeit = np.arange(int(0.15 * abtastrate)) / abtastrate
    schlag = (np.sin(2 * np.pi * 60 * zeit) * np.exp(-zeit * 25)).astype(np.float32)
    rauschen = (np.random.default_rng(1).uniform(-1, 1, len(zeit)) * np.exp(-zeit * 80)).astype(np.float32)
    abstand = 60.0 / bpm
    for nummer in range(int(sekunden / abstand)):
        start = int(nummer * abstand * abtastrate)
        ende = min(start + len(schlag), laenge)
        ton[start:ende] += 0.8 * schlag[: ende - start]
        mitte = int((nummer + 0.5) * abstand * abtastrate)
        ende = min(mitte + len(rauschen), laenge)
        if mitte < laenge:
            ton[mitte:ende] += 0.2 * rauschen[: ende - mitte]
    return ton


class _Schleife:
    """Spielt fertige Zahlen immer wieder ab."""

    def __init__(self, ton: np.ndarray):
        self.ton = ton
        self.stelle = 0
        self.uhr = _Echtzeit()

    def lies(self) -> np.ndarray:
        self.uhr.warte()
        ende = self.stelle + BLOCK
        block = self.ton[self.stelle:ende]
        if len(block) < BLOCK:
            ende = BLOCK - len(block)
            block = np.concatenate([block, self.ton[:ende]])
        self.stelle = ende
        return block

    def schliessen(self) -> None:
        pass


class Testsignal(_Schleife):
    def __init__(self, bpm: float = 120.0):
        super().__init__(erzeuge_takt(bpm, 16 * 60.0 / bpm))


def lade_datei(pfad: Path) -> np.ndarray:
    """Liest eine Audiodatei als Mono mit unserer Abtastrate."""
    import soundfile

    try:
        ton, rate = soundfile.read(str(pfad), dtype="float32", always_2d=True)
    except Exception as fehler:
        raise AudioFehler(f"Datei lässt sich nicht lesen: {fehler}") from fehler
    ton = ton.mean(axis=1)
    if rate != ABTASTRATE:
        stellen = np.arange(0, len(ton), rate / ABTASTRATE)
        ton = np.interp(stellen, np.arange(len(ton)), ton).astype(np.float32)
    if len(ton) < BLOCK:
        raise AudioFehler("Die Datei ist zu kurz.")
    return ton


class Datei(_Schleife):
    def __init__(self, pfad: Path):
        super().__init__(lade_datei(pfad))


def eingaenge() -> list:
    """Alle Audio-Eingänge des Rechners für die Auswahl in der Oberfläche."""
    try:
        import sounddevice
        return [{"nummer": i, "name": g["name"], "kanaele": g["max_input_channels"]}
                for i, g in enumerate(sounddevice.query_devices()) if g["max_input_channels"] > 0]
    except Exception:
        return []


class Eingang:
    """Mikrofon oder X32. Beim X32 wählt `kanaele` das Paar aus (zum Beispiel 31 und 32)."""

    def __init__(self, geraet: Optional[int] = None, kanaele: tuple = (1,)):
        try:
            import sounddevice
        except Exception as fehler:
            raise AudioFehler(f"Audio-Eingang nicht verfügbar: {fehler}") from fehler
        self.warteschlange = queue.Queue(maxsize=32)
        self.auswahl = [k - 1 for k in kanaele]

        def angekommen(daten, _anzahl, _zeit, _status):
            try:
                self.warteschlange.put_nowait(daten[:, self.auswahl].mean(axis=1).copy())
            except queue.Full:
                pass     # Lieber einen Block verlieren als hinterherhinken.

        try:
            self.strom = sounddevice.InputStream(
                device=geraet, channels=max(kanaele), samplerate=ABTASTRATE, blocksize=BLOCK,
                dtype="float32", callback=angekommen)
            self.strom.start()
        except Exception as fehler:
            raise AudioFehler(f"Audio-Eingang lässt sich nicht öffnen: {fehler}") from fehler

    def lies(self) -> np.ndarray:
        try:
            return self.warteschlange.get(timeout=1.0)
        except queue.Empty:
            raise AudioFehler("Vom Audio-Eingang kommt nichts mehr.") from None

    def schliessen(self) -> None:
        self.strom.stop()
        self.strom.close()
