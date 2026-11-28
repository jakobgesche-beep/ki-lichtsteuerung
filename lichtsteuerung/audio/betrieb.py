"""Lässt die Analyse in einem eigenen Thread laufen und bewacht sie.

Fällt die Quelle aus, hält `aktuell()` die letzten Werte noch kurz fest (HALTEN_S): Ein kurzer Aussetzer
macht das Licht nicht ruhig. Danach ist es None, und die Engine geht aufs Grundlicht
(Grundregel „Sicherer Rückfall"). `frisch()` sagt ehrlich, ob gerade Ton ankommt (Konzert-Check, Rückblick).

Bleibt der Ton weg, wird der Eingang immer wieder geöffnet: erst nach 2 s, dann mit wachsender Pause bis 10 s.
Ins Logbuch kommen nur „weg“ (mit Grund) und „wieder da“ (mit Dauer und Versuchen), keine Zeile pro Versuch.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import replace
from typing import Optional

from .analyse import Analyse, Messwerte

MAX_AUFNAHME_BLOECKE = 20 * 60 * 44100 // 512   # höchstens 20 Minuten
MAX_ALTER_S = 0.5     # Jüngere Messwerte sind „frisch“
HALTEN_S = 3.0        # So lange gelten die letzten Messwerte nach einem Aussetzer noch (ohne neue Beats)
ERSTE_PAUSE_S = 2.0   # nach einem Abriss: so lange warten bis zum ersten neuen Versuch
LAENGSTE_PAUSE_S = 10.0
BERICHT_S = 60.0      # höchstens so oft eine Zeile „Ton holpert“ ins Logbuch


class AudioBetrieb:
    def __init__(self):
        self.quelle = None
        self.name = "aus"
        self.fehler: Optional[str] = None
        self.messwerte: Optional[Messwerte] = None
        self.zeitpunkt = 0.0
        self.beat_zaehler = 0
        self.abgeholt = 0
        self.drop_zaehler = 0
        self.drop_abgeholt = 0
        self.schlag_zaehler = 0
        self.schlag_abgeholt = 0
        self.eins_zaehler = 0
        self.eins_abgeholt = 0
        self.treffer_zaehler = 0
        self.treffer_abgeholt = 0
        self.aufnahme = None      # Liste von Blöcken, solange in der Probe aufgenommen wird
        self.beat_erkennung = None
        self.zuhoerer = None      # zum Beispiel der Song-Folger: bekommt jeden Block mit
        self.mithoerer = []       # weitere, zum Beispiel die Song-Erkennung
        self.wieder_verbunden = 0
        self.abrisse = 0              # so oft war der Ton weg (seit dem Start)
        self.weg_seit: Optional[float] = None     # Wanduhr: seit wann der Ton weg ist (zählt Schlaf mit)
        self.vorlauf_s = 0.0          # Beats so viel früher melden (Verzögerung von Ton, Licht und Weg ausgleichen)
        self.rechenzeiten: deque = deque(maxlen=600)      # Rechenzeit pro Block (Analyse + Zuhörer), Sekunden
        self._analyse: Optional[Analyse] = None
        # Gemerkte Lautstärke der lauten Stellen pro Ton-Eingang (dB), siehe audio/lautheit.py. Gelernt nach einer
        # Minute Musik (zum Beispiel beim Soundcheck), damit schon der erste Song am Abend richtig eingeschätzt wird.
        self.bezuege: dict = {}
        self.bezug_gelernt = None     # wird aufgerufen, wenn sich ein Bezug ändert (die Show speichert ihn dann)
        self._thread: Optional[threading.Thread] = None
        self._stopp = threading.Event()

    def starten(self, quelle, name: str) -> None:
        self.stoppen()
        self.quelle, self.name, self.fehler = quelle, name, None
        self._stopp = threading.Event()
        self._thread = threading.Thread(target=self._schleife, args=(quelle, self._stopp),
                                        name="Audio", daemon=True)
        self._thread.start()

    def stoppen(self) -> None:
        self._stopp.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self.quelle is not None:
            self.quelle.schliessen()
            self.quelle = None
        self.name = "aus"
        self.messwerte = None
        self.weg_seit = None
        self._analyse = None

    def vorlauf_setzen(self, sekunden: float) -> None:
        self.vorlauf_s = max(0.0, min(0.3, float(sekunden)))
        if self._analyse is not None and hasattr(self._analyse.beat, "vorlauf_s"):
            self._analyse.beat.vorlauf_s = self.vorlauf_s

    def _schleife(self, quelle, stopp: threading.Event) -> None:
        try:
            analyse = Analyse(bezug_db=self.bezuege.get(self._bezug_name(quelle)))
            self._analyse = analyse
            self.vorlauf_setzen(self.vorlauf_s)
            self.beat_erkennung = analyse.beat.name
            self._versuche, self._pause = 0, ERSTE_PAUSE_S
            verloren_gemeldet = getattr(quelle, "verloren", 0)
            bericht = {"zeit": time.monotonic(), "verloren": verloren_gemeldet, "luecken": getattr(quelle, "luecken", 0)}
            while not stopp.is_set():
                try:
                    block = quelle.lies()
                except Exception as fehler:
                    if not hasattr(quelle, "neu_oeffnen"):
                        raise
                    if self.weg_seit is None:
                        self._weg(quelle, fehler)
                    quelle = self._neu_oeffnen(quelle, stopp)
                    if quelle is None:
                        return
                    verloren_gemeldet = getattr(quelle, "verloren", 0)
                    continue
                if self.weg_seit is not None:            # erst ein echter Block heißt „wieder da“
                    logging.info("Audio-Eingang wieder da nach %.0f s (%d Versuche)", time.time() - self.weg_seit,
                                 self._versuche)
                    self.weg_seit, self.fehler = None, None
                    self.wieder_verbunden += 1
                    self._versuche, self._pause = 0, ERSTE_PAUSE_S
                    analyse.neu_einzaehlen()
                beginn = time.monotonic()
                verloren = getattr(quelle, "verloren", 0)
                if verloren > verloren_gemeldet:
                    # Verworfene Blöcke: Die Takt-Uhr zählt die fehlende Zeit mit, sonst kämen die Beats zu spät.
                    analyse.luecke((verloren - verloren_gemeldet) * len(block))
                    verloren_gemeldet = verloren
                if self.aufnahme is not None and len(self.aufnahme) < MAX_AUFNAHME_BLOECKE:
                    self.aufnahme.append(block.copy())
                werte = analyse.verarbeite(block, getattr(quelle, "letzte_rollen", None))
                jetzt = time.monotonic()
                for zuhoerer in [self.zuhoerer] + list(self.mithoerer):
                    if zuhoerer is None:
                        continue
                    try:
                        zuhoerer(block, jetzt)
                    except Exception:
                        logging.exception("Zuhörer der Audio-Analyse")
                if werte.beat:
                    self.beat_zaehler += 1
                if werte.drop:
                    self.drop_zaehler += 1
                if werte.schlag:
                    self.schlag_zaehler += 1
                if werte.eins:
                    self.eins_zaehler += 1
                if werte.treffer:
                    self.treffer_zaehler += 1
                self.messwerte, self.zeitpunkt = werte, time.monotonic()
                self.rechenzeiten.append(self.zeitpunkt - beginn)
                if self.zeitpunkt - bericht["zeit"] >= BERICHT_S:
                    self._bericht(quelle, bericht)
                    self._bezug_merken(quelle, analyse)
        except Exception as fehler:
            logging.exception("Audio-Analyse")
            self.fehler = str(fehler)

    def _weg(self, quelle, fehler: Exception) -> None:
        self.weg_seit = time.time()
        self.abrisse += 1
        self.fehler = f"Ton weg ({fehler}). Das Programm öffnet den Eingang von selbst neu."
        logging.warning("Audio-Eingang weg: %s", fehler)

    def _neu_oeffnen(self, quelle, stopp: threading.Event):
        """Öffnet den Eingang neu, bis es klappt: erst nach 2 s, dann mit wachsender Pause (höchstens 10 s).
        Die Pause wächst weiter, solange nach dem Öffnen kein Ton kommt (zum Beispiel Deckel zu)."""
        while not stopp.wait(self._pause):
            self._versuche += 1
            self._pause = min(self._pause * 1.5, LAENGSTE_PAUSE_S)
            try:
                neu = quelle.neu_oeffnen()
            except Exception:
                continue
            self.quelle = neu
            return neu
        return None

    def _bericht(self, quelle, bericht: dict) -> None:
        """Einmal pro Minute: Holpert der Ton (verworfene Blöcke, Lieferpausen)? Nur dann eine Zeile ins Logbuch."""
        verloren, luecken = getattr(quelle, "verloren", 0), getattr(quelle, "luecken", 0)
        neu_verloren, neu_luecken = verloren - bericht["verloren"], luecken - bericht["luecken"]
        if neu_verloren > 0 or neu_luecken > 0:
            logging.warning("Ton holpert: %d Blöcke verworfen, %d Lieferpausen in der letzten Minute (Rechenzeit "
                            "p95 %.1f ms)", max(0, neu_verloren), max(0, neu_luecken), self.rechenzeit_p95_ms())
        bericht.update(zeit=time.monotonic(), verloren=verloren, luecken=luecken)

    def _bezug_name(self, quelle) -> Optional[str]:
        """Unter diesem Namen wird der Bezug gemerkt: nur echte Eingänge, mit den Kanälen der Summe."""
        if not str(self.name).startswith("Eingang"):
            return None
        kanaele = getattr(quelle, "kanaele", None)
        return f"{self.name} | {','.join(str(k) for k in kanaele)}" if kanaele else self.name

    def _bezug_merken(self, quelle, analyse) -> None:
        name, gelernt = self._bezug_name(quelle), analyse.lautheit.gelernt()
        if name is None or gelernt is None:
            return
        alt = self.bezuege.get(name)
        if alt is None or abs(alt - gelernt) >= 0.5:
            self.bezuege[name] = gelernt
            logging.info("Ton: Bezug für „%s“ gemerkt: %.1f dB (laute Stellen)", name, gelernt)
            if self.bezug_gelernt is not None:
                try:
                    self.bezug_gelernt()
                except Exception:
                    logging.exception("Bezug speichern")

    def kanal_pegel(self) -> dict:
        """Für den Kanal-Finder: Pegel aller Kanäle des Eingangs und was die Rollen gerade hören."""
        quelle = self.quelle
        analyse = self._analyse
        return {"geraet": getattr(quelle, "geraet_name", None), "kanaele": quelle.pegel_liste() if hasattr(quelle, "pegel_liste") else [],
                "summe": list(getattr(quelle, "kanaele", ())), "rollen": {r: list(k) for r, k in getattr(quelle, "rollen", {}).items()},
                "rollen_pegel": analyse.rollen.pegel() if analyse is not None and analyse.rollen is not None else {}}

    def rechenzeit_p95_ms(self) -> float:
        if not self.rechenzeiten:
            return 0.0
        werte = sorted(self.rechenzeiten)
        return round(1000 * werte[int(0.95 * (len(werte) - 1))], 1)

    def gesundheit(self) -> dict:
        """Für Konzert-Check, Live-Seite und iPad: Wie gut kommt der Ton an?"""
        quelle = self.quelle
        return {"abrisse": self.abrisse, "wieder_verbunden": self.wieder_verbunden,
                "weg_seit_s": round(time.time() - self.weg_seit) if self.weg_seit else None,
                "verloren": getattr(quelle, "verloren", 0), "luecken": getattr(quelle, "luecken", 0),
                "treiber": getattr(quelle, "status_meldungen", 0),
                "rechenzeit_ms": self.rechenzeit_p95_ms(), "vorlauf_ms": round(self.vorlauf_s * 1000)}

    def aufnahme_starten(self) -> None:
        if self.quelle is None:
            raise ValueError("Zuerst auf der Live-Seite eine Tonquelle wählen, zum Beispiel den Eingang vom X32.")
        self.aufnahme = []

    def aufnahme_beenden(self):
        """Gibt den aufgenommenen Ton als eine lange Zahlenreihe zurück."""
        import numpy as np
        bloecke, self.aufnahme = self.aufnahme or [], None
        return np.concatenate(bloecke) if bloecke else np.zeros(0, dtype="float32")

    def position_s(self) -> Optional[float]:
        """Wo eine Audiodatei gerade steht. Für das Nachspielen der Probe."""
        stelle = getattr(self.quelle, "stelle", None)
        return None if stelle is None else stelle / 44100

    def abholen(self, jetzt: Optional[float] = None) -> Optional[Messwerte]:
        """Für die Show: Die Analyse läuft schneller als das Licht.

        Ein Beat steht nur in einem einzigen kurzen Block. Darum merken wir uns,
        welche Beats die Show schon gesehen hat. So geht keiner verloren.
        """
        werte = self.aktuell(jetzt)
        if werte is None:
            return None
        neuer_beat = self.beat_zaehler != self.abgeholt
        neuer_drop = self.drop_zaehler != self.drop_abgeholt
        neuer_schlag = self.schlag_zaehler != self.schlag_abgeholt
        neue_eins = self.eins_zaehler != self.eins_abgeholt
        neuer_treffer = self.treffer_zaehler != self.treffer_abgeholt
        self.abgeholt, self.drop_abgeholt, self.schlag_abgeholt = self.beat_zaehler, self.drop_zaehler, self.schlag_zaehler
        self.eins_abgeholt, self.treffer_abgeholt = self.eins_zaehler, self.treffer_zaehler
        return replace(werte, beat=neuer_beat, drop=neuer_drop, schlag=neuer_schlag, eins=neue_eins,
                       treffer=neuer_treffer)

    def aktuell(self, jetzt: Optional[float] = None) -> Optional[Messwerte]:
        """Die neuesten Messwerte. Nach einem Aussetzer gelten sie noch HALTEN_S lang, danach None (Grundlicht)."""
        jetzt = time.monotonic() if jetzt is None else jetzt
        if self.messwerte is None or jetzt - self.zeitpunkt > HALTEN_S:
            return None
        return self.messwerte

    def frisch(self, jetzt: Optional[float] = None) -> Optional[Messwerte]:
        """Nur wirklich frische Messwerte (jünger als 0,5 s): Kommt gerade Ton an?"""
        jetzt = time.monotonic() if jetzt is None else jetzt
        if self.messwerte is None or jetzt - self.zeitpunkt > MAX_ALTER_S:
            return None
        return self.messwerte
