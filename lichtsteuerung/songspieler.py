"""Song-Start: Ein ganzer Song läuft von selbst durch, nachdem man einmal Start gedrückt hat.

    Start          Wenn die Band anfängt. Das Licht beginnt mit dem ersten Teil.
    Mithören       Der Song-Folger (audio/folgen.py) vergleicht laufend mit der Probe
                   und schaltet die Teile weiter, auch wenn die Band schneller spielt.
    Kein Ton       Dann läuft der Song im Tempo der Probe weiter, wie eine Uhr.
    Korrigieren    "Nächster Teil" und "Teil zurück" setzen die Stelle von Hand.
                   Go+ und Go- auf diesem Executor machen dasselbe.
    Stopp          Der Executor blendet aus, die Automatik übernimmt wieder.

Angezeigt wird immer: welcher Teil gerade läuft, wie lange noch, und was danach kommt.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

from .audio import folgen
from .audio.quellen import lade_datei


def karte_aus(sequenz: dict, analyse: Optional[dict]) -> dict:
    """Die Song-Karte: Teile mit Zeiten und dem Cue, mit dem sie beginnen.

    Neue Sequenzen haben sie schon ("song"), ältere bekommen sie aus der Analyse.
    """
    if sequenz.get("song", {}).get("teile"):
        return sequenz["song"]
    zeitcode = sequenz.get("zeitcode") or []
    teile = []
    for teil in (analyse or {}).get("teile", []):
        cue = max((i for i, z in enumerate(zeitcode) if z <= teil["start"] + 0.05), default=0)
        teile.append({"name": teil.get("name", "Teil"), "gruppe": teil.get("gruppe", ""), "klasse": teil.get("klasse", "mittel"),
                      "start": teil["start"], "ende": teil["ende"], "takte": teil.get("takte"), "cue": cue})
    if not teile and zeitcode:
        ende = (analyse or {}).get("dauer_s", zeitcode[-1] + 30)
        grenzen = list(zeitcode) + [ende]
        teile = [{"name": c["name"], "gruppe": "", "klasse": "mittel", "start": a, "ende": b, "takte": None, "cue": i}
                 for i, (c, a, b) in enumerate(zip(sequenz["cues"], grenzen, grenzen[1:]))]
    return {"probe": sequenz["name"], "tempo_bpm": (analyse or {}).get("tempo_bpm", 120.0),
            "dauer_s": (analyse or {}).get("dauer_s", teile[-1]["ende"] if teile else 0.0), "teile": teile}


class SongSpieler:
    def __init__(self, show):
        self.show = show
        self.folger: Optional[folgen.SongFolger] = None
        self.name: Optional[str] = None
        self.nummer = 1
        self.karte: dict = {}
        self.zeitcode: list = []
        self.letzte_zeit: Optional[float] = None
        self._merkmale = {}          # Name -> (Dateistand, Merkmale, Pegel), damit Start schnell geht

    # --- Welche Songs gibt es ---------------------------------------------

    def songs(self) -> list:
        """Alle Songs, die man starten kann: eine Probe mit Aufnahme und gebauter Sequenz."""
        ergebnis = []
        for name in self.show.proben.namen():
            sequenz = self.show.pult.sequenzen.lesen(name)
            if not sequenz or not sequenz.get("zeitcode") or not self.show.proben.ton_pfad(name).exists():
                continue
            karte = karte_aus(sequenz, self.show.proben.lesen(name))
            ergebnis.append({"name": name, "tempo_bpm": karte.get("tempo_bpm"), "dauer_s": karte.get("dauer_s"),
                             "teile": karte.get("teile", [])})
        return ergebnis

    def _referenz(self, name: str) -> tuple:
        pfad = self.show.proben.ton_pfad(name)
        stand = pfad.stat().st_mtime
        if name in self._merkmale and self._merkmale[name][0] == stand:
            return self._merkmale[name][1:]
        merkmale, pegel = folgen.merkmale_der_aufnahme(lade_datei(pfad))
        self._merkmale[name] = (stand, merkmale, pegel)
        return merkmale, pegel

    # --- Bedienen -------------------------------------------------------

    def starten(self, name: str, nummer: int = 1, jetzt: Optional[float] = None) -> None:
        sequenz = self.show.pult.sequenzen.lesen(name)
        if not sequenz or not sequenz.get("zeitcode"):
            raise ValueError(f"Zu „{name}“ gibt es keine Song-Show. In der Probe „Show neu bauen“ drücken.")
        if not self.show.proben.ton_pfad(name).exists():
            raise ValueError(f"Zu „{name}“ fehlt die Probe-Aufnahme. Ohne sie geht nur das Drücken von Hand.")
        merkmale, pegel = self._referenz(name)
        folger = folgen.SongFolger(merkmale, pegel)
        jetzt = time.monotonic() if jetzt is None else jetzt
        with self.show.sperre:
            self.stoppen(jetzt)
            folger.starten()
            self.folger, self.name, self.nummer = folger, name, nummer
            self.karte = karte_aus(sequenz, self.show.proben.lesen(name))
            self.zeitcode = list(sequenz["zeitcode"])
            self.letzte_zeit = None
            executor = self.show.pult.executor(nummer)
            executor.belegen(sequenz)
            executor.zeitcode = "song"
            self.show.pult.nach_oben(executor, jetzt)
            self.show.pult.haupt = nummer - 1
            self.show.pult.belegung_speichern()
        self.show.audio.zuhoerer = folger.hoeren

    def stoppen(self, jetzt: Optional[float] = None) -> None:
        if self.folger is None:
            return
        jetzt = time.monotonic() if jetzt is None else jetzt
        self.folger.stoppen()
        if self.show.audio.zuhoerer == self.folger.hoeren:
            self.show.audio.zuhoerer = None
        with self.show.sperre:
            executor = self.show.pult.executor(self.nummer)
            if executor.zeitcode == "song":
                executor.zeitcode = False
                executor.aus(jetzt)
        self.folger, self.name = None, None

    def laeuft_auf(self, nummer: int) -> bool:
        return self.folger is not None and self.nummer == nummer

    def _teil_index(self, stelle: float) -> int:
        index = 0
        for nummer, teil in enumerate(self.karte.get("teile", [])):
            if teil["start"] <= stelle + 0.05:
                index = nummer
        return index

    def teil_vor(self) -> None:
        if self.folger is None:
            return
        teile = self.karte.get("teile", [])
        index = self._teil_index(self.folger.stelle)
        if index + 1 < len(teile):
            self.folger.setzen(teile[index + 1]["start"] + 0.01)

    def teil_zurueck(self) -> None:
        """Wie beim CD-Spieler: erst an den Anfang des Teils, dann einen Teil zurück."""
        if self.folger is None:
            return
        teile = self.karte.get("teile", [])
        if not teile:
            return
        index = self._teil_index(self.folger.stelle)
        if self.folger.stelle - teile[index]["start"] < 3.0 and index > 0:
            index -= 1
        self.folger.setzen(teile[index]["start"] + 0.01)

    def zu_teil(self, index: int) -> None:
        teile = self.karte.get("teile", [])
        if self.folger is not None and 0 <= index < len(teile):
            self.folger.setzen(teile[index]["start"] + 0.01)

    def zu_cue(self, index: int) -> None:
        if self.folger is not None and 0 <= index < len(self.zeitcode):
            self.folger.setzen(self.zeitcode[index] + 0.01)

    # --- Jedes Bild ---------------------------------------------------------

    def stelle(self, jetzt: float) -> Optional[float]:
        """Für das Pult: Wo im Song sind wir? (Sekunden der Probe-Aufnahme)"""
        if self.folger is None:
            return None
        dauer = 0.0 if self.letzte_zeit is None else max(0.0, min(0.5, jetzt - self.letzte_zeit))
        self.letzte_zeit = jetzt
        try:
            return self.folger.takt(dauer, jetzt)
        except Exception:
            logging.exception("Song-Folger")
            return self.folger.stelle

    def tempo(self) -> Optional[float]:
        """Das Tempo der Band laut Song-Folger: Tempo der Probe mal wie viel schneller sie spielt."""
        if self.folger is None or not self.karte.get("tempo_bpm"):
            return None
        return float(self.karte["tempo_bpm"]) * self.folger.rate

    def zustand(self, jetzt: Optional[float] = None) -> dict:
        if self.folger is None:
            return {"laeuft": False}
        jetzt = time.monotonic() if jetzt is None else jetzt
        stelle = self.folger.stelle
        teile = self.karte.get("teile", [])
        index = self._teil_index(stelle)
        tempo = float(self.karte.get("tempo_bpm") or 120.0)
        rate = max(self.folger.rate, 0.5)

        def info(nummer):
            if not 0 <= nummer < len(teile):
                return None
            teil = teile[nummer]
            return {"name": teil["name"], "gruppe": teil.get("gruppe", ""), "klasse": teil.get("klasse", "mittel"),
                    "takte": teil.get("takte")}

        jetzt_teil = info(index) or {"name": "", "gruppe": "", "klasse": "mittel", "takte": None}
        if teile:
            rest = max(0.0, teile[index]["ende"] - stelle)
            jetzt_teil.update(rest_s=round(rest / rate, 1), rest_takte=int(math.ceil(rest * tempo / 60.0 / 4.0 - 0.05)))
        return {"laeuft": True, "name": self.name, "executor": self.nummer, "stelle": round(stelle, 2),
                "dauer_s": self.karte.get("dauer_s"), "teil": index, "jetzt": jetzt_teil, "naechster": info(index + 1),
                "teile": [{"name": t["name"], "gruppe": t.get("gruppe", ""), "klasse": t.get("klasse", "mittel"),
                           "start": t["start"], "ende": t["ende"]} for t in teile],
                "tempo_bpm": round(tempo * self.folger.rate, 1), "folger": self.folger.zustand(jetzt)}
