"""MIDI: echte Fader und Tasten (zum Beispiel ein Akai APC mini) und der Takt vom Schlagzeug (MIDI-Clock).

    Controller   Ein MIDI-Gerät am USB. Jeder Regler und jede Taste kann eine Aufgabe bekommen: Fader 1 bis 10
                 der aktuellen Seite, Grand Master, Go+/Go-/Flash/Aus eines Faders, Look-Tasten, Halte-Tasten
                 (Weiß voll, Strobo, Dunkel), Blackout, Tap, Nächster Teil, Teil zurück, Seite.
                 Am einfachsten mit "Lernen": Aufgabe anklicken, dann am Gerät den Regler bewegen oder die
                 Taste drücken. Für drei bekannte Geräte gibt es eine fertige Belegung (ohne Gerät gebaut,
                 darum "ungeprüft": Lernen geht immer).
    Fader        Ein echter Fader fängt erst, wenn er am Wert der Software vorbeikommt (wie an großen Pulten).
                 So springt nach einem Seitenwechsel oder nach der Maus nichts.
    MIDI-Clock   Schickt die Band einen Click (24 Schläge pro Viertel), laufen alle Effekte genau in diesem Tempo
                 und auf diesen Schlägen. Tippen (Tap) geht trotzdem immer vor. Kommt 2 s lang kein Clock mehr,
                 gilt wieder das gehörte Tempo.

Die Belegung liegt in cues/midi.json (kommt in jede Sicherung). Wird das Gerät abgesteckt, verbindet sich
das Programm von selbst wieder, sobald es zurück ist. Ohne MIDI-Gerät tut dieses Modul nichts.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Optional

from . import daten, showtasten

try:                                         # fehlt die Bibliothek, geht alles andere trotzdem
    import rtmidi
except Exception:                            # pragma: no cover - nur ohne python-rtmidi
    rtmidi = None

FANGEN = 0.04                                # so nah am Wert der Software fängt ein Fader sofort
CLOCK_PRO_VIERTEL = 24
CLOCK_WEG_S = 2.0
PRUEFEN_S = 2.0                              # so oft wird nach dem Gerät gesehen (abgesteckt, wieder da?)


def aufgaben() -> list:
    """Alle Aufgaben, die ein Regler oder eine Taste bekommen kann: (Schlüssel, Name, Art)."""
    liste = [(f"fader:{n}", f"Fader {n}", "regler") for n in range(1, 11)]
    liste.append(("grand", "Grand Master", "regler"))
    for n in range(1, 11):
        liste += [(f"go:{n}", f"Go+ Fader {n}", "taste"), (f"zurueck:{n}", f"Go- Fader {n}", "taste"),
                  (f"flash:{n}", f"Flash Fader {n}", "taste"), (f"aus:{n}", f"Aus Fader {n}", "taste")]
    liste += [(f"look:{look['id']}", f"Look {look['taste']}: {look['name']}", "taste") for look in showtasten.LOOKS]
    liste.append(("look:aus", "Look aus", "taste"))
    liste += [(f"halten:{art}", f"Halten: {name}", "taste") for art, name in showtasten.HALTEN.items()]
    liste += [("blackout", "Blackout", "taste"), ("tap", "Tap (Tempo tippen)", "taste"),
              ("go:haupt", "Go+ (letzter Fader, wie Leertaste)", "taste"),
              ("teil_vor", "Song: Nächster Teil jetzt", "taste"), ("teil_zurueck", "Song: Teil zurück", "taste"),
              ("seite:+", "Fader-Seite weiter", "taste"), ("seite:-", "Fader-Seite zurück", "taste")]
    return [{"schluessel": s, "name": n, "art": a} for s, n, a in liste]


def _apc_mini() -> dict:
    belegung = {f"cc:*:{48 + i}": f"fader:{i + 1}" for i in range(8)}
    belegung["cc:*:56"] = "grand"
    for i in range(8):                                   # Raster: unterste Reihe Go+, darüber Flash, darüber Aus
        belegung[f"note:*:{i}"] = f"go:{i + 1}"
        belegung[f"note:*:{8 + i}"] = f"flash:{i + 1}"
        belegung[f"note:*:{16 + i}"] = f"aus:{i + 1}"
    for i, look in enumerate(showtasten.LOOKS[:8]):      # oberste Reihe: Looks 1 bis 8
        belegung[f"note:*:{56 + i}"] = f"look:{look['id']}"
    zweite = [f"look:{showtasten.LOOKS[8]['id']}", "look:aus", "halten:flash", "halten:strobo", "halten:dunkel",
              "blackout", "tap", "go:haupt"]
    for i, aufgabe in enumerate(zweite):                 # zweite Reihe von oben
        belegung[f"note:*:{48 + i}"] = aufgabe
    for start in (82, 112):                              # Tasten rechts (mk1: 82-89, mk2: 112-119)
        for i, aufgabe in enumerate(["teil_vor", "teil_zurueck", "seite:+", "seite:-"]):
            belegung[f"note:*:{start + i}"] = aufgabe
    return belegung


def _nanokontrol2() -> dict:
    belegung = {f"cc:*:{i}": f"fader:{i + 1}" for i in range(8)}
    belegung["cc:*:23"] = "grand"                        # der achte Drehregler
    for i in range(8):
        belegung[f"cc:*:{32 + i}"] = f"flash:{i + 1}"    # S
        belegung[f"cc:*:{48 + i}"] = f"go:{i + 1}"       # M
        belegung[f"cc:*:{64 + i}"] = f"aus:{i + 1}"      # R
    belegung.update({"cc:*:58": "teil_zurueck", "cc:*:59": "teil_vor", "cc:*:46": "tap", "cc:*:43": "seite:-",
                     "cc:*:44": "seite:+", "cc:*:41": "go:haupt", "cc:*:42": "look:aus", "cc:*:45": "blackout"})
    return belegung


def _xtouch_mini() -> dict:
    belegung = {f"cc:*:{1 + i}": f"fader:{i + 1}" for i in range(8)}   # Drehregler (Ebene A)
    belegung["cc:*:9"] = "grand"                                       # der Fader
    for i in range(8):
        belegung[f"note:*:{8 + i}"] = f"go:{i + 1}"                     # obere Tastenreihe
        belegung[f"note:*:{16 + i}"] = f"flash:{i + 1}"                 # untere Tastenreihe
    return belegung


VORLAGEN = {
    "apc_mini": ("Akai APC mini (mk1 und mk2)", _apc_mini),
    "nanokontrol2": ("Korg nanoKONTROL2", _nanokontrol2),
    "xtouch_mini": ("Behringer X-Touch Mini", _xtouch_mini),
}


class MidiClock:
    """Tempo und Schläge aus dem MIDI-Clock (24 Takte pro Viertel)."""

    def __init__(self):
        self.ticks: deque = deque(maxlen=2 * CLOCK_PRO_VIERTEL + 1)
        self.zaehler = 0
        self._start = False
        self._beat = False
        self.laeuft = False

    def tick(self, jetzt: float) -> None:
        self.ticks.append(jetzt)
        if self._start:
            self._start, self.zaehler, self._beat = False, 1, True    # erster Clock nach Start: Schlag 1
            return
        self.zaehler += 1
        if (self.zaehler - 1) % CLOCK_PRO_VIERTEL == 0:
            self._beat = True

    def start(self) -> None:
        self._start, self.laeuft = True, True

    def weiter(self) -> None:
        self.laeuft = True

    def stopp(self) -> None:
        self.laeuft = False

    def bpm(self, jetzt: float) -> Optional[float]:
        if len(self.ticks) < CLOCK_PRO_VIERTEL // 2 or jetzt - self.ticks[-1] > CLOCK_WEG_S:
            return None
        pro_tick = (self.ticks[-1] - self.ticks[0]) / (len(self.ticks) - 1)
        if pro_tick <= 0:
            return None
        bpm = 60.0 / (pro_tick * CLOCK_PRO_VIERTEL)
        return round(bpm, 1) if 30.0 <= bpm <= 300.0 else None

    def beat_abholen(self) -> bool:
        beat, self._beat = self._beat, False
        return beat


class Midi:
    def __init__(self, show):
        self.show = show
        self.pfad = show.pfade.sequenzen.parent / "midi.json"
        roh = daten.lese_json_sicher(self.pfad, {}) or {}
        self.belegung: dict = {str(k): str(v) for k, v in (roh.get("belegung") or {}).items()}
        self.geraet: Optional[str] = roh.get("geraet") or None       # gewünschtes Gerät (Name)
        self.clock_an = bool(roh.get("clock", True))
        self.verbunden: Optional[str] = None
        self.fehler: Optional[str] = None if rtmidi else "Die MIDI-Bibliothek fehlt in diesem Programm."
        self.lernen: Optional[str] = None
        self.zuletzt: Optional[dict] = None
        self.clock = MidiClock()
        self._eingang = None
        self._liste = None
        self._gefangen: dict = {}            # Regler -> (Aufgabe, Seite, zuletzt gesetzter Wert)
        self._letzter: dict = {}             # Regler -> letzter Wert vom Gerät
        self._sperre = threading.Lock()
        self._stopp = threading.Event()

    # --- Gerät ---------------------------------------------------------------

    def geraete(self) -> list:
        if rtmidi is None:
            return []
        try:
            if self._liste is None:
                self._liste = rtmidi.MidiIn()
            return [name for name in self._liste.get_ports() if "Lichtsteuerung" not in name]
        except Exception as fehler:
            self.fehler = f"MIDI-Geräte lassen sich nicht abfragen: {fehler}"
            return []

    def starten(self) -> None:
        """Eigener Thread: verbindet sich mit dem gewünschten Gerät und bleibt dran (abstecken, wieder anstecken)."""
        if rtmidi is None:
            return
        threading.Thread(target=self._wachen, name="MIDI", daemon=True).start()

    def stoppen(self) -> None:
        self._stopp.set()
        self._schliessen()

    def _wachen(self) -> None:
        while not self._stopp.is_set():
            try:
                self._verbinden()
            except Exception:
                logging.exception("MIDI")
            self._stopp.wait(PRUEFEN_S)

    def _verbinden(self) -> None:
        with self._sperre:
            if not self.geraet:
                if self.verbunden:
                    self._schliessen()
                return
            vorhanden = self.geraete()
            if self.verbunden == self.geraet and self.geraet in vorhanden:
                return
            if self.verbunden and self.geraet not in vorhanden:
                self._schliessen()
                self.fehler = f"„{self.geraet}“ ist nicht mehr da (abgesteckt?). Sobald es zurück ist, geht es weiter."
                return
            if self.geraet in vorhanden:
                self._schliessen()
                eingang = rtmidi.MidiIn()
                eingang.ignore_types(sysex=True, timing=False, active_sense=True)     # Clock (timing) brauchen wir
                eingang.open_port(vorhanden.index(self.geraet))
                eingang.set_callback(self._nachricht)
                self._eingang, self.verbunden, self.fehler = eingang, self.geraet, None
            elif not self.verbunden:
                self.fehler = f"„{self.geraet}“ ist nicht angeschlossen."

    def _schliessen(self) -> None:
        eingang, self._eingang, self.verbunden = self._eingang, None, None
        if eingang is not None:
            try:
                eingang.cancel_callback()
                eingang.close_port()
            except Exception:
                logging.exception("MIDI schließen")

    def geraet_waehlen(self, name: Optional[str]) -> None:
        if name and rtmidi is None:
            raise ValueError("Die MIDI-Bibliothek fehlt in diesem Programm.")
        with self._sperre:
            self.geraet = name or None
            self.fehler = None
        self._speichern()
        threading.Thread(target=self._verbinden, daemon=True).start()

    # --- Belegung -------------------------------------------------------------

    def _speichern(self) -> None:
        daten.schreibe_json(self.pfad, {"geraet": self.geraet, "clock": self.clock_an, "belegung": self.belegung})

    def vorlage_laden(self, name: str) -> None:
        if name not in VORLAGEN:
            raise ValueError("Diese Vorlage gibt es nicht.")
        self.belegung = VORLAGEN[name][1]()
        self._gefangen = {}
        self._speichern()

    def lernen_starten(self, aufgabe: Optional[str]) -> None:
        if aufgabe and aufgabe not in {a["schluessel"] for a in aufgaben()}:
            raise ValueError("Diese Aufgabe gibt es nicht.")
        self.lernen = aufgabe or None

    def aufgabe_loeschen(self, aufgabe: str) -> None:
        self.belegung = {regler: a for regler, a in self.belegung.items() if a != aufgabe}
        self._speichern()

    def alles_loeschen(self) -> None:
        self.belegung, self._gefangen = {}, {}
        self._speichern()

    def clock_setzen(self, an: bool) -> None:
        self.clock_an = bool(an)
        self._speichern()

    # --- Nachrichten vom Gerät (MIDI-Thread) ----------------------------------------

    def _nachricht(self, ereignis, _daten=None) -> None:
        try:
            nachricht, _abstand = ereignis
            self.verarbeiten(list(nachricht), time.monotonic())
        except Exception:
            logging.exception("MIDI-Nachricht")

    def verarbeiten(self, nachricht: list, jetzt: float) -> None:
        if not nachricht:
            return
        status = nachricht[0]
        if status == 0xF8:
            self.clock.tick(jetzt)
            return
        if status == 0xFA:
            self.clock.start()
            return
        if status == 0xFB:
            self.clock.weiter()
            return
        if status == 0xFC:
            self.clock.stopp()
            return
        if len(nachricht) < 3:
            return
        art, kanal, nummer, wert = status & 0xF0, (status & 0x0F) + 1, nachricht[1], nachricht[2]
        if art == 0xB0:
            regler = f"cc:{kanal}:{nummer}"
            text = f"Regler {nummer} (CC, Kanal {kanal}): {wert}"
        elif art in (0x90, 0x80):
            regler = f"note:{kanal}:{nummer}"
            wert = wert if art == 0x90 else 0
            text = f"Taste {nummer} (Note, Kanal {kanal}): {'gedrückt' if wert else 'losgelassen'}"
        else:
            return
        self.zuletzt = {"regler": regler, "text": text}
        if self.lernen:
            if art == 0x80 or (art == 0x90 and wert == 0):
                return                                   # Loslassen zählt nicht als Lernen
            aufgabe, self.lernen = self.lernen, None
            self.belegung = {r: a for r, a in self.belegung.items() if a != aufgabe and r != regler}
            self.belegung[regler] = aufgabe
            self._speichern()
            return
        aufgabe = self.belegung.get(regler) or self.belegung.get(f"{regler.split(':')[0]}:*:{nummer}")
        if aufgabe:
            self.ausfuehren(aufgabe, regler, wert / 127.0, jetzt)

    def ausfuehren(self, aufgabe: str, regler: str, wert: float, jetzt: float) -> None:
        """Eine Aufgabe ausführen. wert: 0 bis 1 (Tasten: über der Hälfte heißt gedrückt)."""
        show, pult = self.show, self.show.pult
        an = wert >= 0.5
        art, _, ziel = aufgabe.partition(":")
        if art in ("teil_vor", "teil_zurueck"):
            if an:
                show.song.teil_vor() if art == "teil_vor" else show.song.teil_zurueck()
            return
        with show.sperre:
            if art in ("fader", "grand"):
                nummer = (pult.seite - 1) * 10 + int(ziel) if art == "fader" else None
                jetziger = pult.executor(nummer).fader if nummer else pult.grand
                if self._fangen(regler, aufgabe, pult.seite, jetziger, wert):
                    pult.fader_setzen(nummer, wert, jetzt) if nummer else pult.grand_setzen(wert, jetzt)
                    self._gefangen[regler] = (aufgabe, pult.seite, wert)
                return
            if art == "flash":
                pult.flash((pult.seite - 1) * 10 + int(ziel), an, jetzt)
            elif art == "halten":
                pult.halten_setzen(ziel, an, jetzt)
            elif not an:
                return                                   # alle anderen Tasten: nur beim Drücken
            elif art == "go":
                pult.go(pult.haupt + 1 if ziel == "haupt" else (pult.seite - 1) * 10 + int(ziel), jetzt, 1)
            elif art == "zurueck":
                pult.go((pult.seite - 1) * 10 + int(ziel), jetzt, -1)
            elif art == "aus":
                pult.aus((pult.seite - 1) * 10 + int(ziel), jetzt)
            elif art == "look":
                pult.look_aus(jetzt) if ziel == "aus" else pult.look_druecken(ziel, jetzt)
            elif art == "blackout":
                show.overrides.umschalten("blackout")
            elif art == "tap":
                pult.tap(jetzt)
            elif art == "seite":
                pult.seite_setzen(pult.seite + (1 if ziel == "+" else -1))

    def _fangen(self, regler: str, aufgabe: str, seite: int, jetziger: float, wert: float) -> bool:
        """Fängt der echte Fader? Erst wenn er am Wert der Software vorbeikommt (oder schon dort ist)."""
        alt = self._gefangen.get(regler)
        if alt and alt[0] == aufgabe and alt[1] == seite and abs(alt[2] - jetziger) < 0.02:
            return True                                  # schon gefangen, und niemand hat dazwischen geschoben
        vorher = self._letzter.get(regler)
        self._letzter[regler] = wert
        if abs(wert - jetziger) <= FANGEN:
            return True
        return vorher is not None and (vorher - jetziger) * (wert - jetziger) <= 0

    # --- Für die Show ----------------------------------------------------------

    def clock_bpm(self) -> Optional[float]:
        """Tempo vom MIDI-Clock (None: kein Clock oder abgeschaltet). Die Clock-Zeiten kommen aus der echten Uhr."""
        return self.clock.bpm(time.monotonic()) if self.clock_an else None

    def beat_abholen(self) -> Optional[bool]:
        """Schlag vom MIDI-Clock in diesem Bild? None: kein Clock, dann zählt der gehörte Schlag."""
        if self.clock_bpm() is None:
            return None
        return self.clock.beat_abholen()

    def zustand(self) -> dict:
        jetzt = time.monotonic()
        namen = {a["schluessel"]: a["name"] for a in aufgaben()}
        return {"verfuegbar": rtmidi is not None, "geraete": self.geraete(), "geraet": self.geraet,
                "verbunden": self.verbunden, "fehler": self.fehler, "lernen": self.lernen, "zuletzt": self.zuletzt,
                "belegung": [{"regler": r, "aufgabe": a, "name": namen.get(a, a)} for r, a in sorted(self.belegung.items())],
                "aufgaben": aufgaben(), "vorlagen": [{"id": k, "name": v[0]} for k, v in VORLAGEN.items()],
                "clock": {"an": self.clock_an, "bpm": self.clock.bpm(jetzt), "laeuft": self.clock.laeuft}}

    def kurz(self) -> dict:
        """Für die Live-Daten (40-mal pro Sekunde): nur das Nötigste."""
        return {"verbunden": self.verbunden, "clock_bpm": self.clock_bpm(), "lernen": self.lernen}
