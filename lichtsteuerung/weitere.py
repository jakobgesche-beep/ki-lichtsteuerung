"""Mehrere Aufnahmen pro Song: Mitschnitte vom Konzert und weitere Proben helfen der Song-Erkennung.

Jeder Song hat eine Haupt-Aufnahme (die Probe). Nach ihr richten sich Teile, Show und Song-Folger.
Dazu kann es bis zu 4 weitere Aufnahmen geben (daten/proben/weitere/<Song>/, als FLAC: halb so groß):

    Mitschnitt   Läuft beim Konzert ein Song mit Song-Start, wird der Ton mitgeschnitten (abschaltbar
                 auf der Show-Seite). Die neuesten 2 Mitschnitte pro Song bleiben.
    Aufnahme     In der Probe: "Weitere Aufnahme" (zum Beispiel mit anderem Sänger oder in der Aula).
    Datei        eine Aufnahme als Datei, zum Beispiel ein Handy-Mitschnitt.

Jede weitere Aufnahme wird der Haupt-Aufnahme zugeordnet: Der Song-Folger hört sie einmal durch und merkt
sich, welche Stelle zu welcher Stelle der Probe gehört. Das braucht Rechenzeit und passiert darum erst, wenn
gerade kein Song läuft (es hört sofort auf, wenn einer startet). Hat der Song-Folger dabei weniger als 60 %
sicher mitgehört, wird die Aufnahme nicht genommen: Das ist wohl ein anderer Song, oder der Ton war schlecht.

Die Song-Erkennung vergleicht dann mit allen Aufnahmen eines Songs und nimmt die, die am besten passt.
Die Aufnahmen bleiben auf diesem Laptop (und in einer Show-Sicherung "mit Aufnahmen").
"""
from __future__ import annotations

import datetime
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import daten
from .audio import folgen
from .audio.quellen import ABTASTRATE as RATE, BLOCK, lade_datei

MAX_MITSCHNITTE = 2            # pro Song bleiben die neuesten 2 Mitschnitte
MAX_WEITERE = 4                # höchstens so viele weitere Aufnahmen pro Song
MIN_SICHER = 0.6               # so viel muss der Song-Folger sicher mitgehört haben
MIN_DAUER_S = 30.0             # kürzere Mitschnitte lohnen nicht
MAX_MITSCHNITT_S = 12 * 60     # länger schneidet das Programm nicht mit
RUHE_S = 20.0                  # so lange nach dem letzten Song wird mit dem Zuordnen gewartet
DATEI = re.compile(r"^[a-z0-9-]+\.flac$")


class Abgebrochen(Exception):
    pass


def zuordnen(merkmale: np.ndarray, pegel: np.ndarray, ton: np.ndarray,
             abbruch: Callable[[], bool] = lambda: False) -> dict:
    """Hört die Aufnahme mit dem Song-Folger durch: Welche Stelle gehört zu welcher Stelle der Probe?

    Gibt die Zuordnung zurück (alle 0,5 s ein Paar [Sekunde der Aufnahme, Sekunde der Probe], nur wo der
    Song-Folger sicher war) und wie viel davon sicher war."""
    folger = folgen.SongFolger(merkmale, pegel)
    folger.starten(jetzt=0.0)
    paare, sicher, gesamt = [], 0, 0
    naechste = 0.0
    for a in range(0, len(ton) - BLOCK, BLOCK):
        if a % (40 * BLOCK) == 0:
            if abbruch():
                raise Abgebrochen()
            time.sleep(0.0005)                    # die Show (Licht und Ton) kommt immer dran
        jetzt = a / RATE
        folger.hoeren(ton[a:a + BLOCK], jetzt)
        stelle = folger.takt(BLOCK / RATE, jetzt)
        if jetzt < naechste:
            continue
        naechste += 0.5
        art = folger.zustand(jetzt)["art"]
        if art in ("bereit", "wartet"):
            continue                              # vor dem Song oder in einer Pause: zählt nicht
        gesamt += 1
        if art == "hoert":
            sicher += 1
            paare.append([round(jetzt, 2), round(stelle, 2)])
    return {"zuordnung": paare, "sicher": round(sicher / gesamt, 2) if gesamt else 0.0}


class WeitereAufnahmen:
    """Ablage: pro Song ein Ordner mit den Tondateien und einer Liste (liste.json)."""

    def __init__(self, proben_ordner: Path):
        self.ordner = Path(proben_ordner) / "weitere"
        self.sperre = threading.Lock()

    def _ordner(self, name: str) -> Path:
        return self.ordner / daten.dateiname(name)

    def liste(self, name: str) -> list:
        roh = daten.lese_json_sicher(self._ordner(name) / "liste.json", [])
        if not isinstance(roh, list):
            return []
        return [e for e in roh if isinstance(e, dict) and DATEI.match(str(e.get("datei", "")))]

    def _schreiben(self, name: str, liste: list) -> None:
        daten.schreibe_json(self._ordner(name) / "liste.json", liste)

    def ton_pfad(self, name: str, datei: str) -> Path:
        if not DATEI.match(datei or ""):
            raise ValueError("Unbekannte Aufnahme.")
        return self._ordner(name) / datei

    def speichern(self, name: str, ton: np.ndarray, quelle: str) -> dict:
        """Legt eine weitere Aufnahme ab. Zugeordnet wird sie später (wenn gerade kein Song läuft)."""
        import soundfile
        if len(ton) < MIN_DAUER_S * RATE:
            raise ValueError(f"Die Aufnahme ist kürzer als {int(MIN_DAUER_S)} Sekunden.")
        jetzt = datetime.datetime.now()
        with self.sperre:
            ordner = self._ordner(name)
            ordner.mkdir(parents=True, exist_ok=True)
            art = {"Mitschnitt": "mitschnitt", "Aufnahme": "aufnahme"}.get(quelle, "datei")
            datei = f"{art}-{jetzt:%Y-%m-%d-%H%M%S}.flac"
            zwischen = ordner / (datei + ".tmp")
            soundfile.write(str(zwischen), np.clip(ton, -1, 1), RATE, format="FLAC", subtype="PCM_16")
            zwischen.replace(ordner / datei)
            eintrag = {"datei": datei, "quelle": quelle, "zeit": f"{jetzt:%d.%m.%Y %H:%M}",
                       "dauer_s": round(len(ton) / RATE, 1), "zuordnung": None, "sicher": None}
            liste = self.liste(name) + [eintrag]
            # Zu viele? Erst alte Mitschnitte weg, dann die ältesten überhaupt (nie die neue)
            mitschnitte = [e for e in liste if e["quelle"] == "Mitschnitt"]
            weg = mitschnitte[:-MAX_MITSCHNITTE] if len(mitschnitte) > MAX_MITSCHNITTE else []
            rest = [e for e in liste if e not in weg]
            while len(rest) > MAX_WEITERE:
                alt = next((e for e in rest if e["quelle"] == "Mitschnitt" and e is not eintrag),
                           next(e for e in rest if e is not eintrag))
                weg.append(alt)
                rest.remove(alt)
            for alt in weg:
                (ordner / alt["datei"]).unlink(missing_ok=True)
            self._schreiben(name, rest)
        return eintrag

    def zuordnung_setzen(self, name: str, datei: str, ergebnis: dict) -> Optional[dict]:
        """Ergebnis des Zuordnens eintragen. Passt die Aufnahme nicht, kommt sie weg (gibt None zurück)."""
        with self.sperre:
            liste = self.liste(name)
            eintrag = next((e for e in liste if e["datei"] == datei), None)
            if eintrag is None:
                return None
            if ergebnis["sicher"] < MIN_SICHER or len(ergebnis["zuordnung"]) < 20:
                liste.remove(eintrag)
                (self._ordner(name) / datei).unlink(missing_ok=True)
                self._schreiben(name, liste)
                return None
            eintrag.update(zuordnung=ergebnis["zuordnung"], sicher=ergebnis["sicher"])
            self._schreiben(name, liste)
            return eintrag

    def loeschen(self, name: str, datei: str) -> None:
        with self.sperre:
            liste = [e for e in self.liste(name) if e["datei"] != datei]
            self.ton_pfad(name, datei).unlink(missing_ok=True)
            self._schreiben(name, liste)

    def alle_loeschen(self, name: str) -> None:
        with self.sperre:
            if self._ordner(name).is_dir():
                shutil.rmtree(self._ordner(name))

    def offen(self, namen: list) -> list:
        """Aufnahmen, die noch zugeordnet werden müssen: [(Song, Datei), ...]."""
        return [(name, e["datei"]) for name in namen for e in self.liste(name) if e.get("zuordnung") is None]

    def fuer_erkennung(self, name: str) -> list:
        """Zugeordnete Aufnahmen: [(Pfad, Zuordnung als Array)]."""
        ergebnis = []
        for e in self.liste(name):
            if e.get("zuordnung"):
                pfad = self._ordner(name) / e["datei"]
                if pfad.is_file():
                    ergebnis.append((pfad, np.asarray(e["zuordnung"], float)))
        return ergebnis


class Mitschnitt:
    """Schneidet beim Konzert jeden Song mit (Song-Start bis Song-Ende) und ordnet später zu."""

    def __init__(self, show):
        self.show = show
        self.bloecke: Optional[list] = None
        self.song: Optional[str] = None
        self._folger_id: Optional[int] = None
        self.letztes_ende = -1e9
        self._pruefen_ab = 0.0
        self._arbeiter: Optional[threading.Thread] = None
        self.status = ""                              # zum Beispiel "ordnet Mitschnitt von Hh zu …"
        show.audio.mithoerer.append(self._hoeren)

    @property
    def weitere(self) -> WeitereAufnahmen:
        return self.show.proben.weitere

    def _hoeren(self, block: np.ndarray, jetzt: float) -> None:
        """Audio-Thread: nur anhängen, nichts rechnen."""
        bloecke = self.bloecke
        if bloecke is not None and len(bloecke) * BLOCK < MAX_MITSCHNITT_S * RATE:
            bloecke.append(block.copy())

    def takt(self, jetzt: float) -> None:
        """Jedes Bild (unter der Sperre der Show): Song-Start und -Ende beobachten."""
        try:
            song = self.show.song
            folger_id = id(song.folger) if song.folger is not None else None
            if folger_id != self._folger_id:
                self._beenden(jetzt)
                self._folger_id = folger_id
                if folger_id is not None and song.mitschnitt_an:
                    self.bloecke, self.song = [], song.name
            elif self.bloecke is not None and song.folger is not None and song._am_ende():
                self._beenden(jetzt)
            if folger_id is None and jetzt >= self._pruefen_ab:
                self._pruefen_ab = jetzt + 10.0
                self._zuordnen_wenn_ruhig(jetzt)
        except Exception:
            logging.exception("Mitschnitt")

    def _beenden(self, jetzt: float) -> None:
        bloecke, name = self.bloecke, self.song
        self.bloecke, self.song = None, None
        if bloecke is None:
            return
        self.letztes_ende = jetzt
        if len(bloecke) * BLOCK < MIN_DAUER_S * RATE:
            return
        threading.Thread(target=self._ablegen, args=(name, bloecke), name="Mitschnitt ablegen", daemon=True).start()

    def _ablegen(self, name: str, bloecke: list) -> None:
        try:
            self.weitere.speichern(name, np.concatenate(bloecke), "Mitschnitt")
            self.show.rueckblick.ereignis("mitschnitt", song=name, ergebnis="aufgenommen")
        except Exception:
            logging.exception("Mitschnitt ablegen")

    def _zuordnen_wenn_ruhig(self, jetzt: float) -> None:
        if self._arbeiter is not None and self._arbeiter.is_alive():
            return
        if jetzt - self.letztes_ende < RUHE_S or self.show.generalprobe.laeuft:
            return
        offen = self.weitere.offen(self.show.proben.namen())
        if offen:
            self._arbeiter = threading.Thread(target=self._zuordnen, args=(offen,), name="Aufnahmen zuordnen", daemon=True)
            self._arbeiter.start()

    def _stoerend(self) -> bool:
        return self.show.song.folger is not None or self.show.generalprobe.laeuft

    def _zuordnen(self, offen: list) -> None:
        for name, datei in offen:
            if self._stoerend():
                break
            try:
                self.status = f"ordnet eine weitere Aufnahme von „{name}“ zu …"
                merkmale, pegel = self.show.song._referenz(name)
                ton = lade_datei(self.weitere.ton_pfad(name, datei))
                ergebnis = zuordnen(merkmale, pegel, ton, self._stoerend)
                eintrag = self.weitere.zuordnung_setzen(name, datei, ergebnis)
                text = (f"übernommen ({round(ergebnis['sicher'] * 100)} % sicher mitgehört)" if eintrag
                        else f"nicht übernommen (nur {round(ergebnis['sicher'] * 100)} % sicher: anderer Song oder schlechter Ton?)")
                self.show.rueckblick.ereignis("mitschnitt", song=name, ergebnis=text)
            except Abgebrochen:
                break                                  # ein Song läuft: später weiter
            except Exception:
                logging.exception("Weitere Aufnahme zuordnen")
                try:
                    self.weitere.zuordnung_setzen(name, datei, {"sicher": 0.0, "zuordnung": []})
                except Exception:
                    logging.exception("Weitere Aufnahme verwerfen")
            finally:
                self.status = ""
