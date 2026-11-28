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
WARTESCHLANGE = 128   # so viele Blöcke dürfen warten (rund 1,5 s), bevor einer verloren geht
NICHTS_KOMMT_S = 2.0  # so lange kein Block vom Gerät: Eingang gilt als weg
LUECKE_S = 0.1        # längere Pausen zwischen zwei Lieferungen des Geräts werden gezählt


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


def erzeuge_edm(bpm: float = 128, abtastrate: int = ABTASTRATE, mit_pause: bool = True) -> tuple:
    """Ein künstlicher EDM-Song: Groove, Aufbau ohne Bass, kurze Pause, Drop mit fettem Bass.

    Gibt (Ton, Zeitpunkt des Drops in Sekunden) zurück. Für Tests und zum Ausprobieren.
    """
    rng = np.random.default_rng(7)
    beat = 60.0 / bpm
    stuecke = []

    def kick(laenge, laut):
        t = np.arange(int(laenge * abtastrate)) / abtastrate
        frequenz = 50 + 80 * np.exp(-t * 30)
        return laut * np.sin(2 * np.pi * np.cumsum(frequenz) / abtastrate) * np.exp(-t * 6)

    def groove(takte, laut, sub):
        ton = np.zeros(int(takte * 4 * beat * abtastrate))
        for n in range(takte * 4):
            start = int(n * beat * abtastrate)
            schlag = kick(beat, laut)
            ton[start:start + len(schlag)] += schlag[: len(ton) - start]
        t = np.arange(len(ton)) / abtastrate
        ton += sub * np.sin(2 * np.pi * 55 * t)
        ton += 0.04 * rng.standard_normal(len(ton)) * (np.sin(2 * np.pi * t / beat * 2) > 0.6)
        return ton

    stuecke.append(groove(8, 0.5, 0.15))                    # 16 Takte Groove
    aufbau = np.zeros(int(16 * beat * abtastrate))           # 4 Takte Aufbau ohne Bass
    t = np.arange(len(aufbau)) / abtastrate
    anteil = t / t[-1]
    aufbau += (0.02 + 0.35 * anteil ** 2) * rng.standard_normal(len(aufbau))
    for teil, unterteilung in enumerate((1, 2, 4, 8)):       # Snare-Wirbel wird immer schneller
        for n in range(4 * unterteilung):
            start = int((teil * 4 + n / unterteilung) * beat * abtastrate)
            laenge = int(0.05 * abtastrate)
            aufbau[start:start + laenge] += (0.1 + 0.3 * teil / 3) * rng.standard_normal(min(laenge, len(aufbau) - start))
    stuecke.append(aufbau)
    if mit_pause:
        stuecke.append(np.zeros(int(beat * abtastrate)))     # ein Beat Stille
    drop_zeit = sum(len(s) for s in stuecke) / abtastrate
    stuecke.append(groove(8, 1.0, 0.5))                      # Drop: alles voll
    ton = np.concatenate(stuecke)
    return (ton / np.max(np.abs(ton)) * 0.9).astype(np.float32), drop_zeit


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
    def __init__(self, bpm: float = 120.0, art: str = "takt"):
        if art == "drop":
            super().__init__(erzeuge_edm(bpm)[0])
        else:
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
    def __init__(self, pfad: Path, ab_s: float = 0.0):
        super().__init__(lade_datei(pfad))
        self.stelle = int(max(0.0, ab_s) * ABTASTRATE) % max(1, len(self.ton))


# Unter Windows steht jedes Gerät mehrmals in der Liste (einmal pro Schnittstelle). Wir zeigen jedes nur
# einmal, in der besten Schnittstelle: WASAPI (wenig Verzögerung, rechnet die Abtastrate selbst um), sonst MME.
API_VORRANG = ("Windows WASAPI", "MME", "Windows DirectSound", "Core Audio", "ALSA")
API_NIE = ("Windows WDM-KS",)


def _sounddevice():
    import sounddevice
    return sounddevice


def eingaenge() -> list:
    """Alle Audio-Eingänge des Rechners für die Auswahl in der Oberfläche (jedes Gerät nur einmal)."""
    try:
        sd = _sounddevice()
        apis = [h["name"] for h in sd.query_hostapis()]
        alle = [{"nummer": i, "name": g["name"], "kanaele": g["max_input_channels"], "api": apis[g["hostapi"]]}
                for i, g in enumerate(sd.query_devices()) if g["max_input_channels"] > 0]
    except Exception:
        return []
    alle = [e for e in alle if e["api"] not in API_NIE]
    rang = {api: i for i, api in enumerate(API_VORRANG)}
    beste = {}
    for eintrag in sorted(alle, key=lambda e: rang.get(e["api"], 99)):
        schluessel = eintrag["name"][:31].strip().lower()      # MME kürzt Namen auf 31 Zeichen
        if not any(schluessel.startswith(k) or k.startswith(schluessel) for k in beste):
            beste[schluessel] = eintrag
    return sorted(beste.values(), key=lambda e: e["nummer"])


def geraet_suchen(name: str, api: Optional[str] = None) -> Optional[int]:
    """Findet ein Gerät nach Namen wieder (die Nummern ändern sich, wenn USB-Geräte dazukommen)."""
    for eintrag in eingaenge():
        if eintrag["name"] == name and (api is None or eintrag["api"] == api):
            return eintrag["nummer"]
    for eintrag in eingaenge():
        if eintrag["name"][:31] == name[:31]:
            return eintrag["nummer"]
    return None


class Umrechner:
    """Rechnet Ton von einer anderen Abtastrate auf unsere um (lineare Zwischenwerte, Block für Block)."""

    def __init__(self, von: float, nach: float = ABTASTRATE):
        self.schritt = von / nach           # so viele Eingangs-Werte pro neuem Wert
        self.stelle = 0.0                   # wo der nächste neue Wert im kommenden Block liegt
        self.letzter = 0.0

    def __call__(self, block: np.ndarray) -> np.ndarray:
        laenge = len(block)
        if laenge == 0:
            return np.zeros(0, np.float32)
        anzahl = int(np.floor((laenge - 1 - self.stelle) / self.schritt)) + 1 if self.stelle <= laenge - 1 else 0
        stellen = self.stelle + np.arange(max(anzahl, 0)) * self.schritt
        mit_vorigem = np.concatenate([[self.letzter], block])
        neu = np.interp(stellen + 1.0, np.arange(laenge + 1), mit_vorigem)
        self.stelle = (stellen[-1] + self.schritt if anzahl > 0 else self.stelle) - laenge
        self.letzter = float(block[-1])
        return neu.astype(np.float32)


class Eingang:
    """Mikrofon oder X32. Beim X32 wählt `kanaele` die Summe aus (zum Beispiel 31 und 32).

    `rollen` (nur X32-USB): weitere Kanäle mit Rolle, zum Beispiel {"bassdrum": [1], "rednerpult": [12]}.
    Ihre Blöcke liegen nach jedem lies() in `letzte_rollen` (gleich lang wie der Summen-Block).
    Gemessen wird der Pegel aller Kanäle des Geräts (bis 32): für den Kanal-Finder (`pegel_liste`).

    Öffnet mit 44,1 kHz. Kann das Gerät das nicht, nimmt es seine eigene Abtastrate und rechnet um.
    """

    def __init__(self, geraet: Optional[int] = None, kanaele: tuple = (1,), name: Optional[str] = None,
                 api: Optional[str] = None, rollen: Optional[dict] = None):
        try:
            sd = _sounddevice()
        except Exception as fehler:
            raise AudioFehler(f"Audio-Eingang nicht verfügbar: {fehler}") from fehler
        if name is not None:
            gefunden = geraet_suchen(name, api)
            if gefunden is None:
                raise AudioFehler(f"Der Eingang „{name}“ ist nicht da. Ist das Gerät angesteckt?")
            geraet = gefunden
        try:
            info = sd.query_devices(geraet, "input")
            self.geraet_name = info["name"]
            self.api_name = sd.query_hostapis(info["hostapi"])["name"]
        except Exception as fehler:
            raise AudioFehler(f"Audio-Eingang nicht gefunden: {fehler}") from fehler
        self.kanaele = tuple(kanaele)
        self.rollen = {r: tuple(int(k) for k in ks) for r, ks in (rollen or {}).items() if ks}
        self.warteschlange = queue.Queue(maxsize=WARTESCHLANGE)
        self.auswahl = [k - 1 for k in self.kanaele]
        self.rollen_index = {r: [k - 1 for k in ks] for r, ks in self.rollen.items()}
        gebraucht = max([max(self.kanaele)] + [max(ks) for ks in self.rollen.values()])
        geraet_kanaele = int(info.get("max_input_channels") or gebraucht)
        self.offene_kanaele = max(gebraucht, min(geraet_kanaele, 32))
        self.pegel = np.zeros(self.offene_kanaele, np.float32)      # Spitzenpegel je Kanal (fällt langsam)
        self.rollen_puffer = {r: np.zeros(0, np.float32) for r in self.rollen}
        self.rollen_umrechner: dict = {}
        self.letzte_rollen: Optional[dict] = None
        # Zum Nachsehen, wenn der Ton wegbleibt (steht im Logbuch und im Konzert-Check)
        self.verloren = 0                    # Blöcke, die wegen Rückstau verworfen wurden
        self.luecken = 0                     # Pausen > 0,1 s zwischen zwei Lieferungen des Geräts
        self.status_meldungen = 0            # Meldungen des Treibers (zum Beispiel Überlauf)
        self.letzter_status = ""
        self.letzte_lieferung: Optional[float] = None
        self.puffer = np.zeros(0, np.float32)
        self.umrechner: Optional[Umrechner] = None
        zusatz = sd.WasapiSettings(auto_convert=True) if self.api_name == "Windows WASAPI" else None

        def angekommen(daten, _anzahl, _zeit, status):
            jetzt = time.monotonic()
            if self.letzte_lieferung is not None and jetzt - self.letzte_lieferung > LUECKE_S:
                self.luecken += 1
            self.letzte_lieferung = jetzt
            if status:
                self.status_meldungen += 1
                self.letzter_status = str(status)
            effektiv = np.sqrt(np.mean(np.square(daten), axis=0))
            self.pegel = np.maximum(effektiv, self.pegel * 0.85)
            mono = daten[:, self.auswahl].mean(axis=1)
            rollen_neu = {r: daten[:, idx].mean(axis=1) for r, idx in self.rollen_index.items()}
            if self.umrechner is not None:
                mono = self.umrechner(mono)
                rollen_neu = {r: self.rollen_umrechner[r](x) for r, x in rollen_neu.items()}
            self.puffer = np.concatenate([self.puffer, mono.astype(np.float32)])
            for r, x in rollen_neu.items():
                self.rollen_puffer[r] = np.concatenate([self.rollen_puffer[r], x.astype(np.float32)])
            while len(self.puffer) >= BLOCK:
                block, self.puffer = self.puffer[:BLOCK].copy(), self.puffer[BLOCK:]
                teile = None
                if self.rollen_puffer:
                    teile = {}
                    for r in self.rollen_puffer:
                        stueck = self.rollen_puffer[r][:BLOCK]
                        if len(stueck) < BLOCK:
                            stueck = np.pad(stueck, (0, BLOCK - len(stueck)))
                        teile[r], self.rollen_puffer[r] = stueck.copy(), self.rollen_puffer[r][BLOCK:]
                try:
                    self.warteschlange.put_nowait((block, teile))
                except queue.Full:
                    self.verloren += 1     # Lieber einen Block verlieren als hinterherhinken (die Uhr erfährt es).

        def oeffnen(rate):
            return sd.InputStream(device=geraet, channels=self.offene_kanaele, samplerate=rate, blocksize=0,
                                  dtype="float32", callback=angekommen, latency="low", extra_settings=zusatz)

        try:
            try:
                self.strom = oeffnen(ABTASTRATE)
            except Exception:
                eigene = float(info.get("default_samplerate") or 48000)
                if abs(eigene - ABTASTRATE) < 1:
                    raise
                self.umrechner = Umrechner(eigene)
                self.rollen_umrechner = {r: Umrechner(eigene) for r in self.rollen}    # gleich lange Blöcke wie die Summe
                self.strom = oeffnen(eigene)
            self.strom.start()
        except Exception as fehler:
            raise AudioFehler(f"Audio-Eingang lässt sich nicht öffnen: {fehler}") from fehler

    def lies(self) -> np.ndarray:
        try:
            block, self.letzte_rollen = self.warteschlange.get(timeout=NICHTS_KOMMT_S)
            return block
        except queue.Empty:
            raise AudioFehler(f"Vom Audio-Eingang kommt nichts mehr ({self.diagnose()}).") from None

    def pegel_liste(self) -> list:
        """Für den Kanal-Finder: Pegel jedes Kanals in dB (Spitze der letzten Zeit)."""
        return [round(float(20 * np.log10(max(w, 1e-6))), 1) for w in self.pegel]

    def diagnose(self) -> str:
        """Kurz, warum der Ton fehlen könnte: fürs Logbuch."""
        if self.letzte_lieferung is None:
            seit = "Gerät hat noch nie geliefert"
        else:
            seit = f"letzte Lieferung vor {time.monotonic() - self.letzte_lieferung:.1f} s"
        teile = [seit, f"{self.geraet_name}, {self.api_name}"]
        if self.umrechner is not None:
            teile.append("mit Umrechnung")
        if self.status_meldungen:
            teile.append(f"Treiber meldete {self.status_meldungen}× ({self.letzter_status})")
        if self.verloren:
            teile.append(f"{self.verloren} Blöcke wegen Rückstau verworfen")
        return ", ".join(teile)

    def schliessen(self) -> None:
        try:
            self.strom.stop()
            self.strom.close()
        except Exception:
            pass

    def neu_oeffnen(self) -> "Eingang":
        """Nach einem Abriss: dasselbe Gerät wieder öffnen.

        Erst einfach neu öffnen. Nur wenn das Gerät in der Liste fehlt (USB-Kabel war ab), die Geräteliste von
        PortAudio neu einlesen. Das beendet nämlich alle offenen Tonströme des Programms."""
        self.schliessen()
        try:
            return Eingang(kanaele=self.kanaele, name=self.geraet_name, api=self.api_name, rollen=self.rollen)
        except AudioFehler:
            pass
        try:
            sd = _sounddevice()
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        return Eingang(kanaele=self.kanaele, name=self.geraet_name, api=self.api_name, rollen=self.rollen)
