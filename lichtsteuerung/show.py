"""Die Show: hält alle Daten und baut daraus 40-mal pro Sekunde ein DMX-Bild.

Hier läuft alles zusammen. Ein Bild entsteht immer in dieser Reihenfolge:

    Automatik      -> Engine reagiert auf die Musik, sonst Grundlicht
    Cues und Fader -> liegen über der Automatik
    Profil-Grenze  -> maximale Helligkeit und Blitz-Wächter
    Override       -> die Tasten haben immer Vorrang
    DMX-Test       -> nur, wenn er gerade läuft
    Prüfung        -> jeder Wert gegen die Gerätedatei
    Ausgabe        -> Simulator, und wenn eingeschaltet das Enttec
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from . import daten
from .audio.betrieb import AudioBetrieb
from .buehne import Buehne
from .cues import CueSpieler, FaderBank, Sammlung, pruefe_cueliste
from .dmx_ausgabe import BILDER_PRO_SEKUNDE, DmxAusgabe
from .engine import Engine
from .katalog import Katalog
from .overrides import Overrides
from .patch import Patch
from .profile import Profile, RUHE_PROFIL, strobo_grenzen
from .pruefung import Pruefer, Vorgaben
from .render import Eigenschaften, Renderer
from .sicherheit import BlitzWaechter, Grenzen
from .simulator import Simulator
from .vorschau import Vorschau


class Show:
    def __init__(self, pfade: Optional[daten.Pfade] = None, ausgabe: Optional[DmxAusgabe] = None):
        self.pfade = pfade or daten.Pfade()
        self.katalog = Katalog(self.pfade.katalog)
        self.patch = Patch(self.pfade.fixtures, self.katalog)
        self.buehne = Buehne(self.pfade.stage)
        self.positionen = daten.lese_json(self.pfade.positions, {"positionen": {}})["positionen"]
        self.grenzen = Grenzen.laden(self.pfade.sicherheit)
        self.ausgabe = ausgabe or DmxAusgabe()
        self.audio = AudioBetrieb()
        self.profile = Profile(self.pfade.profile)
        self.profil = RUHE_PROFIL
        self.overrides = Overrides()
        self.szenen = Sammlung(self.pfade.szenen)
        self.cuelisten = Sammlung(self.pfade.cuelisten)
        self.fader = FaderBank(self.pfade.fader)
        self.cues = None
        self.vorschau = Vorschau(self)
        self.blitze = BlitzWaechter()
        self.blitzt = False

        self.sperre = threading.RLock()     # Oberfläche und Show-Schleife wechseln sich ab
        self.test_geraet: Optional[str] = None
        self.test_kanaele = {}              # DMX-Kanal (ab 1) -> Wert
        self.meldungen = []
        self.letztes_bild = bytes(512)
        self._stopp = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.aufbauen()
        self._sitzung_laden()

    def aufbauen(self) -> None:
        """Muss nach jeder Änderung am Patch oder an der Bühne laufen."""
        with self.sperre:
            self.renderer = Renderer(self.patch)
            self.pruefer = Pruefer(self.patch, self.buehne, self.grenzen)
            self.simulator = Simulator(self.patch, self.buehne)
            self.engine = Engine(self.patch, self.buehne, self.positionen, self.grenzen)
            liste = self.cues.liste if self.cues else None
            self.cues = CueSpieler(self.patch, self.buehne, self.positionen, self.szenen)
            if liste:
                self.cues.laden(liste)

    # --- Ein Bild bauen ---------------------------------------------------

    def baue_bild(self, jetzt: Optional[float] = None) -> bytes:
        jetzt = time.monotonic() if jetzt is None else jetzt
        with self.sperre:
            zustand = self._automatik(jetzt)
            if not self._test_laeuft():
                zustand = self.cues.ueberlagern(zustand, jetzt)
                zustand = self.fader.anwenden(zustand, self.patch, self.buehne, self.positionen, self.szenen)
            zustand = self._profil_grenzen(zustand, jetzt)
            zustand = self.overrides.anwenden(zustand, self.patch.geraete)
            bild = self.renderer.bild(zustand)
            self._test_einmischen(bild)
            bild, meldungen, self.blitzt = self.pruefer.pruefe(bild, self._vorgaben(), jetzt)
            self.meldungen = meldungen + self.cues.meldungen
            self.letztes_bild = bytes(bild)
            return self.letztes_bild

    def _test_laeuft(self) -> bool:
        return self.test_geraet is not None or bool(self.test_kanaele)

    def _automatik(self, jetzt: float) -> dict:
        if self._test_laeuft():
            zustand = {}
            if self.test_geraet is not None:
                zustand[self.test_geraet] = Eigenschaften(helligkeit=1.0, farbe=(1.0, 1.0, 1.0))
            return zustand
        try:
            messwerte = self.audio.aktuell(jetzt)
            return self.engine.bewerte(messwerte, self.profil, jetzt, self.overrides.pause)
        except Exception:
            # Sicherer Rückfall: Auch ein Fehler in den Regeln führt zum Grundlicht.
            logging.exception("Fehler in der Engine")
            return self.engine.bewerte(None, self.profil, jetzt)

    def _profil_grenzen(self, zustand: dict, jetzt: float) -> dict:
        grenze = self.profil["max_helligkeit"]
        ergebnis = {}
        for geraet_id, e in zustand.items():
            hell = e.helligkeit if self._test_laeuft() else min(e.helligkeit, grenze)
            hell = self.blitze.begrenze(geraet_id, hell, jetzt, self.grenzen.strobo_max_hz)
            ergebnis[geraet_id] = e.kopie(helligkeit=hell)
        return ergebnis

    def _test_einmischen(self, bild: bytearray) -> None:
        """Rohe Testwerte gelten nur, solange keine Override-Taste gedrückt ist."""
        if not (self.overrides.blackout or self.overrides.warmweiss):
            for kanal, wert in self.test_kanaele.items():
                bild[kanal - 1] = wert

    def _vorgaben(self) -> Vorgaben:
        hz, dauer = strobo_grenzen(self.profil, self.grenzen)
        if self.overrides.strobo_aus:
            hz = 0.0
        return Vorgaben(strobo_max_hz=hz, strobo_max_dauer_s=dauer, blackout=self.overrides.blackout,
                        hazer_erlaubt=self.profil["hazer"] and not self.overrides.blackout)

    def notbild(self) -> bytes:
        """Falls beim Bauen etwas schiefgeht: letztes Bild halten, Blackout bleibt Blackout."""
        return bytes(512) if self.overrides.blackout else self.letztes_bild

    # --- Profile und Sitzung ----------------------------------------------

    def profil_laden(self, name: str) -> None:
        profil = self.profile.laden(name)
        with self.sperre:
            self.profil = profil
        self._sitzung_speichern()

    def cueliste_laden(self, name: str) -> None:
        liste = self.cuelisten.lesen(name)
        if liste is None:
            raise ValueError(f"Cueliste {name!r} gibt es nicht.")
        fehler = pruefe_cueliste(liste, self.szenen)
        if fehler:
            raise ValueError(" ".join(fehler))
        with self.sperre:
            self.cues.laden(liste)
        self._sitzung_speichern()

    def _sitzung_speichern(self) -> None:
        daten.schreibe_json(self.pfade.sitzung, {
            "profil": self.profil["name"],
            "cueliste": self.cues.liste["name"] if self.cues.liste else None})

    def _sitzung_laden(self) -> None:
        """Nach einem Neustart: Letztes Profil und letzte Cueliste laden. DMX bleibt aus."""
        sitzung = daten.lese_json(self.pfade.sitzung, {})
        if sitzung.get("profil"):
            try:
                self.profil = self.profile.laden(sitzung["profil"])
            except ValueError:
                self.profil = RUHE_PROFIL
        if sitzung.get("cueliste"):
            try:
                self.cueliste_laden(sitzung["cueliste"])
            except ValueError:
                pass

    def live_daten(self) -> dict:
        """Das schickt der Server laufend an die 3D-Vorschau."""
        with self.sperre:
            werte = self.audio.aktuell()
            return {"geraete": self.simulator.lies(self.letztes_bild),
                    "dmx_ein": self.ausgabe.eingeschaltet, "meldungen": sorted(set(self.meldungen)),
                    "profil": self.profil["name"], "engine": self.engine.zustand_text,
                    "overrides": vars(self.overrides), "blitzt": self.blitzt,
                    "cues": self.cues.status(), "fader": self.fader.status(),
                    "vorschau": {"art": self.vorschau.art, "geraete": self.vorschau.geraete,
                                 "meldungen": self.vorschau.meldungen},
                    "strobo_erlaubt": self.profil["strobo"] != "aus",
                    "hazer_erlaubt": self.profil["hazer"],
                    "audio": {"quelle": self.audio.name, "fehler": self.audio.fehler,
                              "erkennung": self.audio.beat_erkennung, "beats": self.audio.beat_zaehler,
                              "werte": vars(werte) if werte else None}}

    def buehnen_aufbau(self) -> dict:
        return {"buehne": self.buehne.daten["buehne"], "publikum": self.buehne.publikum,
                "traverse": self.buehne.traverse, "geraete": self.simulator.aufbau(),
                "positionen": self.positionen}

    # --- Die Schleife -----------------------------------------------------

    def start(self) -> None:
        self._stopp.clear()
        self._thread = threading.Thread(target=self._schleife, name="Show", daemon=True)
        self._thread.start()

    def stopp(self) -> None:
        self._stopp.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.audio.stoppen()
        self.ausgabe.ausschalten()

    def _schleife(self) -> None:
        abstand = 1.0 / BILDER_PRO_SEKUNDE
        while not self._stopp.is_set():
            beginn = time.monotonic()
            try:
                bild = self.baue_bild(beginn)
            except Exception as fehler:
                # Die Show läuft weiter, auch wenn ein Bild misslingt.
                logging.exception("Bild konnte nicht gebaut werden")
                self.meldungen = [f"Interner Fehler: {fehler}"]
                bild = self.notbild()
            self.ausgabe.setze_bild(bild)
            rest = abstand - (time.monotonic() - beginn)
            if rest > 0:
                time.sleep(rest)
