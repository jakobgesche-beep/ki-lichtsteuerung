"""Die Show: hält alle Daten und baut daraus 40-mal pro Sekunde ein DMX-Bild.

Hier läuft alles zusammen. Ein Bild entsteht immer in dieser Reihenfolge:

    Automatik      -> Engine reagiert auf die Musik, sonst Grundlicht
    Pult          -> Executoren und Programmer liegen über der Automatik
    Profil-Grenze  -> maximale Helligkeit und Blitz-Wächter
    Override       -> die Tasten haben immer Vorrang
    DMX-Test       -> nur, wenn er gerade läuft
    Prüfung        -> jeder Wert gegen die Gerätedatei
    Ausgabe        -> Simulator, und wenn eingeschaltet das Enttec
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Optional

import numpy as np

from . import daten
from .audio.betrieb import AudioBetrieb
from .buehne import Buehne
from .dmx_ausgabe import BILDER_PRO_SEKUNDE, DmxAusgabe
from .engine import Engine, GRUPPE_BEWEGUNG
from .katalog import Katalog
from .overrides import Overrides
from .patch import Patch
from .probe import Proben, show_bauen
from .pult import Pult
from .profile import Profile, RUHE_PROFIL, strobo_grenzen
from .pruefung import Pruefer, Vorgaben
from .render import Eigenschaften, Renderer
from .sicherheit import BlitzWaechter, Grenzen, StroboWaechter
from .simulator import Simulator
from .songspieler import SongSpieler
from .szenen import loese_auf
from .update import Aktualisierer
from .version import VERSION
from .vorschau import Vorschau


ERSTES_PROFIL = "Schulfest Abend"   # beim allerersten Start, damit das Licht auf Musik reagiert
WARM_POSITION = "Mitte"     # dorthin zeigen die Spots bei Warmweiß
EINMESS_S = 3.0             # so lange blitzt der Strobo beim Einmessen
SOFTWARE_BLITZ_S = 0.05     # so lange ist ein Blitz an, wenn das Programm selbst blitzt
TEST_MAX_S = 120.0          # Ein vergessener DMX-Test endet von selbst.


class Show:
    def __init__(self, pfade: Optional[daten.Pfade] = None, ausgabe: Optional[DmxAusgabe] = None):
        self.pfade = pfade or daten.standard_pfade()
        self.katalog = Katalog(self.pfade.katalog, self.pfade.eingebauter_katalog)
        self.patch = Patch(self.pfade.fixtures, self.katalog)
        self.buehne = Buehne(self.pfade.stage)
        self.positionen = daten.lese_json(self.pfade.positions, {"positionen": {}})["positionen"]
        self.grenzen = Grenzen.laden(self.pfade.sicherheit)
        self.ausgabe = ausgabe or DmxAusgabe()
        self.update = Aktualisierer(self)
        self.audio = AudioBetrieb()
        self.profile = Profile(self.pfade.profile)
        self.profil = RUHE_PROFIL
        self.overrides = Overrides()
        self.pult = Pult(self, self.pfade.sequenzen, self.pfade.executoren)
        self.proben = Proben(self.pfade.proben)
        self.song = SongSpieler(self)
        self._beat = False                 # kam in diesem Bild ein Schlag? (für das Einrasten der Effekte)
        self._letztes_tempo: Optional[float] = None
        self.aufnahme_name: Optional[str] = None
        self.aufnahme_marken = []
        self.automatik_an = True
        self.vorschau = Vorschau(self)
        self.vorschau_geraete = None
        self.blitze = BlitzWaechter()
        self.vorschau_blitze = BlitzWaechter()
        self.blitzt = False
        self.software_strobos = set()        # reine Strobos ohne bekanntes Tempo: das Programm blitzt selbst
        self.software_blitzt = set()
        self.software_waechter = StroboWaechter()
        self._software_letzter = {}
        self._software_schritt = {}

        self.sperre = threading.RLock()     # Oberfläche und Show-Schleife wechseln sich ab
        self.test_geraet: Optional[str] = None
        self.test_kanaele = {}              # DMX-Kanal (ab 1) -> Wert
        self.test_seit: Optional[float] = None
        self.pruefer: Optional[Pruefer] = None
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
            alter_waechter = self.pruefer.strobo if self.pruefer else None
            alte_einmessung = self.pruefer.einmessen_bis if self.pruefer else {}
            self.pruefer = Pruefer(self.patch, self.buehne, self.grenzen)
            self.pruefer.einmessen_bis = alte_einmessung
            if alter_waechter:
                # Eine Patch-Änderung darf die Strobo-Dauer nicht zurücksetzen.
                self.pruefer.strobo = alter_waechter
            self.simulator = Simulator(self.patch, self.buehne)
            self.engine = Engine(self.patch, self.buehne, self.positionen, self.grenzen)
            self.pult.aufbauen()
            self.vorschau_pruefer = Pruefer(self.patch, self.buehne, self.grenzen)
            ziel, _ = loese_auf([{"gruppe": GRUPPE_BEWEGUNG, "position": WARM_POSITION}],
                                self.patch, self.buehne, self.positionen)
            self.warm_stellung = {i: (e.pan, e.tilt) for i, e in ziel.items() if e.pan is not None}
            self.software_strobos = {g["id"] for g in self.patch.geraete if self.strobo_art(g) == "software"}

    def strobo_art(self, geraet: dict) -> str:
        """"eingemessen": blitzt mit eigenem Tempo. "software": reiner Strobo ohne bekanntes Tempo,
        das Programm blitzt selbst über die Helligkeit. "gesperrt": Strobo-Kanal ohne Tempo. "": keiner."""
        kanaele = [k for _, k in self.patch.typ(geraet).kanaele_im_modus(geraet["modus"])]
        typen = {k["typ"] for k in kanaele}
        if "strobo" not in typen:
            return ""
        bekannt = any(b.get("hz_bis") for k in kanaele if k["typ"] == "strobo"
                      for b in k.get("bereiche", []) if b["typ"] == "strobo")
        if bekannt:
            return "eingemessen"
        rein = not typen & {"rot", "gruen", "blau", "weiss", "amber", "uv", "pan", "tilt", "farbrad", "gobo"}
        return "software" if rein and "dimmer" in typen else "gesperrt"

    # --- Ein Bild bauen ---------------------------------------------------

    def baue_bild(self, jetzt: Optional[float] = None) -> bytes:
        jetzt = time.monotonic() if jetzt is None else jetzt
        with self.sperre:
            self._test_pruefen(jetzt)
            self._einmessen_pruefen(jetzt)
            zustand = self._automatik(jetzt)
            if not self._test_laeuft():
                zustand = self.pult.anwenden(zustand, jetzt, self._musik_bpm(), self._beat)
                self._blind_vorschau(zustand if self.pult.programmer.blind else None, jetzt)
                zustand = self._software_blitz(zustand, jetzt)
            else:
                self.software_blitzt = set()
            zustand = self._profil_grenzen(zustand, jetzt)
            zustand = self.overrides.anwenden(zustand, self.patch.geraete, self.warm_stellung)
            bild = self.renderer.bild(zustand)
            self._test_einmischen(bild)
            bild, meldungen, blitzt = self.pruefer.pruefe(bild, self._vorgaben(), jetzt)
            self.blitzt = blitzt or bool(self.software_blitzt)
            self.meldungen = meldungen + self.pult.meldungen
            self.letztes_bild = bytes(bild)
            return self.letztes_bild

    def test_setzen(self, geraet: Optional[str], kanaele: dict) -> None:
        with self.sperre:
            self.test_geraet, self.test_kanaele = geraet, kanaele
            self.test_seit = time.monotonic()

    def _test_pruefen(self, jetzt: float) -> None:
        if self.test_seit is not None and time.monotonic() - self.test_seit > TEST_MAX_S:
            self.test_geraet, self.test_kanaele, self.test_seit = None, {}, None

    def strobo_einmessen(self, geraet_id: str, wert: int, jetzt: Optional[float] = None) -> None:
        """Lässt einen Strobo EINMESS_S Sekunden lang mit diesem Tempo-Wert blitzen."""
        if not 1 <= wert <= 255:
            raise ValueError("Tempo-Wert von 1 bis 255.")
        geraet = self.patch.geraet(geraet_id)
        kanaele = {}
        for versatz, kanal in self.patch.typ(geraet).kanaele_im_modus(geraet["modus"]):
            if kanal["typ"] == "strobo":
                kanaele[geraet["adresse"] + versatz] = wert
            elif kanal["typ"] == "dimmer":
                kanaele[geraet["adresse"] + versatz] = 255
        if not any(w == wert for w in kanaele.values()):
            raise ValueError(f"{geraet['name']} hat keinen Strobo-Kanal.")
        jetzt = time.monotonic() if jetzt is None else jetzt
        with self.sperre:
            self.test_setzen(None, kanaele)
            self.pruefer.einmessen_bis[geraet_id] = jetzt + EINMESS_S
            self.einmessen_ende = (geraet_id, jetzt + EINMESS_S)

    def _einmessen_pruefen(self, jetzt: float) -> None:
        ende = getattr(self, "einmessen_ende", None)
        if ende and jetzt >= ende[1]:
            self.test_geraet, self.test_kanaele, self.test_seit = None, {}, None
            self.pruefer.einmessen_bis.pop(ende[0], None)
            self.einmessen_ende = None

    def strobo_auswerten(self, geraet_id: str, messungen: list) -> dict:
        """Aus gezählten Blitzen wird ein eingemessener Gerätetyp. Gibt das Ergebnis zurück."""
        geraet = self.patch.geraet(geraet_id)
        typ = self.patch.typ(geraet)
        werte = sorted((int(m["wert"]), float(m["blitze"]) / float(m.get("sekunden", EINMESS_S))) for m in messungen)
        if len(werte) < 2 or len({w for w, _ in werte}) < 2:
            raise ValueError("Bitte mindestens zwei verschiedene Werte messen.")
        hz = [h for _, h in werte]
        if any(b <= a for a, b in zip(hz, hz[1:])) or hz[0] <= 0:
            raise ValueError("Die Messung passt nicht: Ein höherer Wert muss schneller blitzen. Bitte noch einmal zählen.")
        # float(): numpy-Zahlen lassen sich nicht an die Oberfläche schicken.
        steigung, achse = (float(x) for x in np.polyfit([w for w, _ in werte], hz, 1))
        unten, oben = werte[0][0], werte[-1][0]
        hz_unten, hz_oben = max(0.1, steigung * unten + achse), steigung * oben + achse
        eintrag = json.loads(json.dumps(typ.daten))
        name, kanal = next((n, k) for n, k in eintrag["kanaele"].items() if k["typ"] == "strobo")
        # Nur den Strobo-Bereich aufteilen, in dem gemessen wurde. "Shutter zu", "offen" und
        # alles andere bleibt, wie es im Katalog steht.
        neu_bereiche, getroffen = [], False
        for bereich in kanal.get("bereiche", []):
            if bereich["typ"] == "strobo" and bereich["von"] <= unten and oben <= bereich["bis"]:
                getroffen = True
                neu_bereiche += [
                    {**bereich, "bis": unten - 1, "hz_von": None, "hz_bis": None},
                    {**bereich, "von": unten, "bis": oben, "hz_von": round(hz_unten, 2), "hz_bis": round(hz_oben, 2)},
                    {**bereich, "von": oben + 1, "hz_von": None, "hz_bis": None},
                ]
            else:
                neu_bereiche.append(bereich)
        if not getroffen:
            raise ValueError("Die gemessenen Werte liegen nicht alle im Strobo-Bereich dieses Geräts.")
        kanal["bereiche"] = [b for b in neu_bereiche if b["von"] <= b["bis"]]
        eintrag["basis"] = typ.daten.get("basis", typ.id)       # damit man die Einmessung zurücknehmen kann
        basis_name = typ.daten["name"].removesuffix(" eingemessen")
        eintrag.update(id=f"technik-ag/{geraet_id}-eingemessen", name=f"{basis_name} eingemessen",
                       hersteller="Technik-AG", platzhalter=False, eingemessen=messungen)
        eintrag["_hinweis"] = (f"Eingemessen: Wert {unten} ≈ {hz_unten:.1f} Blitze/s, Wert {oben} ≈ {hz_oben:.1f} Blitze/s. "
                               "Werte außerhalb bleiben gesperrt.")
        neu = self.katalog.speichere_eigenen(eintrag)
        with self.sperre:
            self.patch.tauschen(geraet_id, neu.id, geraet["modus"])
            self.patch.speichern()
            self.aufbauen()
        grenze = self.grenzen.strobo_max_hz
        nutzbar = bool(hz_unten <= grenze)
        return {"typ": neu.id, "von": unten, "bis": oben, "hz_von": round(hz_unten, 2), "hz_bis": round(hz_oben, 2),
                "nutzbar": nutzbar,
                "text": (f"Fertig. Bis {grenze:g} Blitze pro Sekunde darf er jetzt blitzen." if nutzbar else
                         f"Schon der kleinste Wert blitzt {hz_unten:.1f}-mal pro Sekunde, das ist über der Grenze von "
                         f"{grenze:g}. Bitte noch einen kleineren Wert messen.")}

    def _software_blitz(self, zustand: dict, jetzt: float) -> dict:
        """Strobo ohne bekanntes Tempo: Das Programm blitzt selbst über die Helligkeit.

        So bestimmt das Programm das Tempo, nicht das unbekannte Gerät: kurze Blitze
        (50 ms) auf dem Beat, nie öfter als erlaubt (3 pro Sekunde), nach der Höchstdauer
        kommt die Pause. Ohne Blitz-Wunsch bleibt der Strobo dunkel (kein Dauerlicht).
        """
        self.software_blitzt = set()
        if not self.software_strobos:
            return zustand
        hz, dauer = strobo_grenzen(self.profil, self.grenzen)
        grenze = 0.0 if self.overrides.strobo_aus else min(hz, self.grenzen.strobo_max_hz)
        wunsch = {i for i in self.software_strobos
                  if i in zustand and zustand[i].strobo_hz > 0 and zustand[i].helligkeit > 0}
        erlaubt = grenze > 0 and bool(wunsch) and self.software_waechter.erlaubt(jetzt)
        self.software_waechter.melde(erlaubt, jetzt, min(dauer, self.grenzen.strobo_max_dauer_s),
                                     self.grenzen.strobo_pause_s)
        beats = self.pult.effekte.musik_beats if self.pult.effekte is not None else jetzt * 2.0
        beat_hz = self._musik_bpm() / 60.0
        ergebnis = dict(zustand)
        for geraet_id in self.software_strobos:
            e = ergebnis.get(geraet_id)
            if e is None:
                continue
            if not erlaubt or geraet_id not in wunsch:
                ergebnis[geraet_id] = e.kopie(helligkeit=0.0, strobo_hz=0.0)
                self._software_schritt.pop(geraet_id, None)
                continue
            rate = min(e.strobo_hz, grenze)
            # Blitze pro Beat: so viele wie möglich, aber nie schneller als erlaubt
            pro_beat = next((teil for teil in (4, 2, 1, 0.5, 0.25) if beat_hz * teil <= rate + 1e-6), 0.25)
            schritt = math.floor(beats * pro_beat)
            vorher = self._software_schritt.get(geraet_id)
            seit = jetzt - self._software_letzter.get(geraet_id, -99.0)
            if (vorher is None or schritt != vorher) and seit >= 1.0 / grenze - 1e-3:
                self._software_letzter[geraet_id] = jetzt
            self._software_schritt[geraet_id] = schritt
            an = jetzt - self._software_letzter.get(geraet_id, -99.0) < SOFTWARE_BLITZ_S
            ergebnis[geraet_id] = e.kopie(helligkeit=e.helligkeit if an else 0.0, strobo_hz=0.0)
            if an:
                self.software_blitzt.add(geraet_id)
        return ergebnis

    def strobo_zuruecksetzen(self, geraet_id: str) -> dict:
        """Nimmt eine Einmessung zurück: Das Gerät bekommt wieder seinen ursprünglichen Typ."""
        geraet = self.patch.geraet(geraet_id)
        typ = self.patch.typ(geraet)
        basis = typ.daten.get("basis")
        if basis is None and typ.id.endswith("-eingemessen"):
            name = typ.daten["name"].removesuffix(" eingemessen")
            kanaele = set(typ.daten["kanaele"])
            basis = next((t.id for t in self.katalog.typen.values()
                          if t.daten["name"] == name and set(t.daten["kanaele"]) == kanaele
                          and not t.id.endswith("-eingemessen")), None)
        if basis is None:
            raise ValueError(f"{geraet['name']} ist nicht eingemessen.")
        with self.sperre:
            self.patch.tauschen(geraet_id, basis, geraet["modus"])
            self.patch.speichern()
            self.aufbauen()
        return {"typ": basis, "text": f"{geraet['name']}: Einmessung zurückgenommen. Sein Strobo ist wieder gesperrt."}

    def _test_laeuft(self) -> bool:
        return self.test_geraet is not None or bool(self.test_kanaele)

    def _automatik(self, jetzt: float) -> dict:
        self._beat = False
        if self._test_laeuft():
            zustand = {}
            if self.test_geraet is not None:
                zustand[self.test_geraet] = Eigenschaften(helligkeit=1.0, farbe=(1.0, 1.0, 1.0))
            return zustand
        if not self.automatik_an:
            werte = self.audio.abholen(jetzt)     # Beats trotzdem abholen, damit keiner nachträglich kommt
            self._beat = bool(werte is not None and werte.beat)
            return {}
        try:
            messwerte = self.audio.abholen(jetzt)
            self._beat = bool(messwerte is not None and messwerte.beat)
            return self.engine.bewerte(messwerte, self.profil, jetzt, self.overrides.pause)
        except Exception:
            # Sicherer Rückfall: Auch ein Fehler in den Regeln führt zum Grundlicht.
            logging.exception("Fehler in der Engine")
            return self.engine.bewerte(None, self.profil, jetzt)

    def _musik_bpm(self) -> float:
        """Tempo für alle Effekte. Fällt der Ton aus, läuft das Licht im letzten Tempo weiter.

        Reihenfolge: getippt (Tap) > Song-Start (Tempo der Probe, wie schnell die Band
        gerade spielt) > gehörtes Tempo > zuletzt gehörtes oder getipptes > 120.
        """
        if self.pult.tempo_quelle == "tap" and self.pult.tempo_getippt:
            return self.pult.tempo_getippt
        song = self.song.tempo()
        if song and 40 <= song <= 240:
            return song
        werte = self.audio.aktuell()
        if werte and 40 <= werte.tempo_bpm <= 240:
            self._letztes_tempo = werte.tempo_bpm
            return werte.tempo_bpm
        return self._letztes_tempo or self.pult.tempo_getippt or 120.0

    def _blind_vorschau(self, zustand: Optional[dict], jetzt: float) -> None:
        """Im Blind-Modus: Programmer nur in die 3D-Vorschau, nie an den Ausgang."""
        if zustand is None or self.pult.programmer.ist_leer():
            self.vorschau_geraete = None
            return
        vorschau = self._profil_grenzen(self.pult.vorschau(zustand), jetzt, eigener_waechter=True)
        bild = self.renderer.bild(vorschau)
        hz, dauer = self.grenzen.strobo_max_hz, self.grenzen.strobo_max_dauer_s
        bild, _, _ = self.vorschau_pruefer.pruefe(bild, Vorgaben(strobo_max_hz=hz, strobo_max_dauer_s=dauer), jetzt)
        self.vorschau_geraete = self.simulator.lies(bytes(bild))

    def _profil_grenzen(self, zustand: dict, jetzt: float, eigener_waechter: bool = False) -> dict:
        grenze = self.profil["max_helligkeit"]
        waechter = self.vorschau_blitze if eigener_waechter else self.blitze
        ergebnis = {}
        for geraet_id, e in zustand.items():
            hell = e.helligkeit if self._test_laeuft() else min(e.helligkeit, grenze)
            hell = waechter.begrenze(geraet_id, hell, jetzt, self.grenzen.strobo_max_hz)
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
                        strobo_aus=self.overrides.strobo_aus, software_blitz=frozenset(self.software_blitzt),
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

    def _sitzung_speichern(self) -> None:
        daten.schreibe_json(self.pfade.sitzung, {"profil": self.profil["name"], "automatik": self.automatik_an})

    def _sitzung_laden(self) -> None:
        """Nach einem Neustart: Letztes Profil und Executor-Belegung kommen zurück. DMX bleibt aus."""
        sitzung = daten.lese_json(self.pfade.sitzung, {})
        try:
            self.profil = self.profile.laden(sitzung.get("profil") or ERSTES_PROFIL)
        except ValueError:
            self.profil = RUHE_PROFIL
        self.automatik_an = sitzung.get("automatik", True)
        palette = self.profil.get("palette") or ["rot", "blau"]
        self.pult.farbe_1, self.pult.farbe_2 = palette[0], palette[1 % len(palette)]

    def gobos_der_gruppe(self, gruppe: str) -> list:
        """Gobo-Namen, die alle Geräte der Gruppe haben (ohne "Offen")."""
        listen = []
        for geraet in self.patch.in_gruppe(gruppe):
            namen = []
            for _, kanal in self.patch.typ(geraet).kanaele_im_modus(geraet["modus"]):
                if kanal["typ"] == "gobo":
                    namen += [b["name"] for b in kanal.get("bereiche", []) if b["typ"] == "platz"]
            listen.append([n for n in namen if n != "Offen"])
        gemeinsam = [n for n in (listen[0] if listen else []) if all(n in l for l in listen)]
        return gemeinsam or (listen[0] if listen else [])

    def show_aus_probe(self, name: str) -> dict:
        """Baut aus einer analysierten Probe die Sequenz mit demselben Namen."""
        analyse = self.proben.neu_analysieren(name)
        if analyse is None:
            raise ValueError(f"Probe {name!r} gibt es nicht.")
        sequenz = show_bauen(analyse, self.patch, self.profil["palette"], self.gobos_der_gruppe, self.positionen)
        with self.sperre:
            self.pult.sequenz_speichern(sequenz)
        return sequenz

    def live_daten(self) -> dict:
        """Das schickt der Server laufend an die 3D-Vorschau."""
        with self.sperre:
            werte = self.audio.aktuell()
            return {"geraete": self.simulator.lies(self.letztes_bild),
                    "dmx_ein": self.ausgabe.eingeschaltet, "meldungen": sorted(set(self.meldungen)),
                    "profil": self.profil["name"], "engine": self.engine.zustand_text,
                    "reagiert": self.profil["beat_reaktion"] > 0,
                    "overrides": vars(self.overrides), "blitzt": self.blitzt,
                    "test_laeuft": self._test_laeuft(), "version": VERSION,
                    "update": self.update.status(),
                    "pult": self.pult.status(), "automatik": self.automatik_an,
                    "song": self.song.zustand(), "tempo": round(self._musik_bpm(), 1),
                    "aufnahme": {"name": self.aufnahme_name,
                                 "sekunden": round(len(self.audio.aufnahme or []) * 512 / 44100, 1),
                                 "markierungen": len(self.aufnahme_marken)},
                    "vorschau": {"geraete": self.vorschau_geraete},
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
        naechstes = time.monotonic()
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
            # Fester Takt: Verspätete Bilder verschieben nicht alle folgenden.
            naechstes += abstand
            rest = naechstes - time.monotonic()
            if rest > 0:
                time.sleep(rest)
            else:
                naechstes = time.monotonic()
