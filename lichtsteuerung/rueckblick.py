"""Rückblick: ein Logbuch der Show. Was lief wann, wie sicher hat das Programm mitgehört, wo wurde korrigiert?

Jeder Tag bekommt eine eigene Datei (daten/rueckblick/2026-11-12.jsonl, eine Zeile pro Ereignis).
So geht nichts verloren, auch wenn der Laptop abstürzt. Auf der Show-Seite zeigt "Rückblick …":

    Songs        wie jeder Song gestartet wurde (von Hand, erkannt, als Vorschlag bestätigt), wie lange er lief,
                 wie viel davon das Programm sicher mitgehört hat und wie oft von Hand korrigiert wurde
    Üben         was man in der Probe prüfen sollte (zum Beispiel: "Hh: im Refrain C zweimal korrigiert")
    Ablauf       alle Ereignisse mit Uhrzeit

Gespeichert wird nur, was das Programm selbst tut: kein Ton, keine Namen von Personen.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

PROBE_ALLE_S = 1.0          # so oft wird nachgesehen, wie sicher das Mithören gerade ist
TON_WEG_S = 3.0             # so lange kein Ton, dann steht es im Logbuch
UNSICHER_GRENZE = 0.6       # weniger sicher mitgehört als das: Hinweis
KORREKTUR_GRENZE = 2        # so oft im selben Teil korrigiert: Hinweis
TAGE_ZEIGEN = 30
DATEI = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")
WIE_TEXT = {"hand": "von Hand", "erkannt": "erkannt", "vorschlag": "Vorschlag bestätigt"}
ENDE_TEXT = {"durch": "bis zum Schluss", "applaus": "Applaus am Schluss", "stopp": "gestoppt",
             "neuer_song": "nächster Song gestartet"}


def _jetzt() -> datetime.datetime:
    return datetime.datetime.now()


class Rueckblick:
    def __init__(self, show, ordner: Optional[Path] = None):
        self.show = show
        self.ordner = Path(ordner) if ordner else Path(show.pfade.wurzel) / "daten" / "rueckblick"
        self.lauf: Optional[dict] = None            # der Song, der gerade läuft
        self._folger_id: Optional[int] = None
        self._naechste_probe = 0.0
        self._look: Optional[str] = None
        self._blackout = False
        self._ton_weg_seit: Optional[float] = None
        self._ton_weg_gemeldet = False
        self._dmx_weg = False
        self._zwischen = "aus"

    # --- Schreiben ---------------------------------------------------------------

    def ereignis(self, art: str, **felder) -> None:
        """Eine Zeile ins Logbuch von heute. Fehler beim Schreiben stören die Show nie."""
        zeit = _jetzt()
        zeile = {"zeit": zeit.strftime("%H:%M:%S"), "art": art, **felder}
        try:
            self.ordner.mkdir(parents=True, exist_ok=True)
            with open(self.ordner / f"{zeit:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as datei:
                datei.write(json.dumps(zeile, ensure_ascii=False) + "\n")
        except OSError:
            logging.exception("Rückblick schreiben")

    def korrektur(self, aktion: str) -> None:
        """Von Hand eingegriffen: Nächster Teil, Teil zurück, Teil oder Cue angeklickt."""
        song = self.show.song
        if song.folger is None:
            return
        teil = self._teil_name(song, song.folger.stelle)
        if self.lauf is not None:
            self.lauf["korrekturen"][teil] += 1
        self.ereignis("korrektur", song=song.name, aktion=aktion, teil=teil, stelle=round(song.folger.stelle, 1))

    @staticmethod
    def _teil_name(song, stelle: float) -> str:
        teile = song.karte.get("teile", [])
        if not teile:
            return ""
        teil = teile[song._teil_index(stelle)]
        name = f"{teil.get('name', 'Teil')} {teil.get('gruppe', '')}".strip()
        start = float(teil.get("start", 0.0))
        return f"{name} ({int(start // 60)}:{int(start % 60):02d})"      # gleiche Namen gibt es öfter im Song

    # --- Jedes Bild (unter der Sperre der Show) ------------------------------------------

    def takt(self, jetzt: float) -> None:
        try:
            self._song_beobachten(jetzt)
            self._tasten_beobachten()
            if jetzt >= self._naechste_probe:
                self._naechste_probe = jetzt + PROBE_ALLE_S
                self._mithoeren_proben(jetzt)
                self._technik_beobachten(jetzt)
        except Exception:                       # das Logbuch darf nie das Licht stören
            logging.exception("Rückblick")

    def _song_beobachten(self, jetzt: float) -> None:
        song = self.show.song
        folger_id = id(song.folger) if song.folger is not None else None
        if folger_id != self._folger_id:
            if self.lauf is not None and not self.lauf.get("fertig"):
                self._lauf_beenden(jetzt, "neuer_song" if folger_id is not None else "stopp")
            self._folger_id = folger_id
            self.lauf = None
            if folger_id is not None:
                wie = getattr(song, "start_wie", "hand")
                self.lauf = {"song": song.name, "wie": wie, "start": jetzt, "zustaende": Counter(),
                             "teile": {}, "korrekturen": Counter(), "fertig": False}
                self.ereignis("start", song=song.name, wie=wie, stelle=round(song.folger.stelle, 1))
            return
        if self.lauf is not None and not self.lauf["fertig"] and song.folger is not None and song._am_ende():
            self._lauf_beenden(jetzt, "applaus" if song.vorbei else "durch")

    def _mithoeren_proben(self, jetzt: float) -> None:
        song = self.show.song
        if self.lauf is None or self.lauf["fertig"] or song.folger is None or song.folger.bereit:
            return
        art = song.folger.zustand(jetzt)["art"]
        self.lauf["zustaende"][art] += 1
        teil = self._teil_name(song, song.folger.stelle)
        self.lauf["teile"].setdefault(teil, Counter())[art] += 1

    def _lauf_beenden(self, jetzt: float, wie: str) -> None:
        lauf = self.lauf
        lauf["fertig"] = True
        zaehler = lauf["zustaende"]
        gesamt = sum(zaehler.values())
        anteil = (lambda *arten: round(sum(zaehler[a] for a in arten) / gesamt, 2)) if gesamt else (lambda *arten: None)
        unsicher = []
        for teil, teil_zaehler in lauf["teile"].items():
            summe = sum(teil_zaehler.values())
            if summe >= 5 and teil_zaehler["hoert"] / summe < UNSICHER_GRENZE:
                unsicher.append(teil)
        self.ereignis("ende", song=lauf["song"], wie=wie, start_wie=lauf["wie"], dauer_s=round(jetzt - lauf["start"]),
                      sicher=anteil("hoert"), ohne_ton=anteil("uhr"), unsicher_in=unsicher,
                      korrekturen=dict(lauf["korrekturen"]))

    def _tasten_beobachten(self) -> None:
        pult = self.show.pult
        look = pult.look if pult.tasten.index >= 0 else None
        if look != self._look:
            self._look = look
            if look:
                self.ereignis("look", look=look)
        blackout = bool(self.show.overrides.blackout)
        if blackout != self._blackout:
            self._blackout = blackout
            self.ereignis("blackout", an=blackout)
        zustand = self.show.zwischenlicht.zustand
        if zustand != self._zwischen:
            self._zwischen = zustand
            if zustand in ("applaus", "pause"):
                self.ereignis(zustand)

    def _technik_beobachten(self, jetzt: float) -> None:
        audio = self.show.audio
        weg = audio.name != "aus" and audio.aktuell(jetzt) is None
        if weg:
            self._ton_weg_seit = self._ton_weg_seit if self._ton_weg_seit is not None else jetzt
            if not self._ton_weg_gemeldet and jetzt - self._ton_weg_seit >= TON_WEG_S:
                self._ton_weg_gemeldet = True
                self.ereignis("ton_weg", eingang=audio.name)
        else:
            if self._ton_weg_gemeldet:
                self.ereignis("ton_da", eingang=audio.name, nach_s=round(jetzt - self._ton_weg_seit))
            self._ton_weg_seit, self._ton_weg_gemeldet = None, False
        dmx = self.show.ausgabe.status()
        dmx_weg = bool(dmx.get("eingeschaltet") and not dmx.get("verbunden"))
        if dmx_weg != self._dmx_weg:
            self._dmx_weg = dmx_weg
            self.ereignis("dmx_weg" if dmx_weg else "dmx_da")

    # --- Lesen ---------------------------------------------------------------------

    def tage(self) -> list:
        if not self.ordner.is_dir():
            return []
        return sorted((p.stem for p in self.ordner.iterdir() if DATEI.match(p.name)), reverse=True)[:TAGE_ZEIGEN]

    def lesen(self, tag: str) -> list:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", tag or ""):
            raise ValueError("Unbekannter Tag.")
        pfad = self.ordner / f"{tag}.jsonl"
        ereignisse = []
        if pfad.is_file():
            for zeile in pfad.read_text(encoding="utf-8").splitlines():
                try:
                    eintrag = json.loads(zeile)
                except ValueError:
                    continue                      # eine halbe Zeile nach einem Absturz
                if isinstance(eintrag, dict) and "art" in eintrag:
                    ereignisse.append(eintrag)
        return ereignisse

    def zusammenfassung(self, tag: Optional[str] = None) -> dict:
        tage = self.tage()
        tag = tag or (tage[0] if tage else f"{_jetzt():%Y-%m-%d}")
        ereignisse = self.lesen(tag)
        songs, offen = [], {}
        for e in ereignisse:
            if e["art"] == "start":
                offen[e.get("song")] = e
            elif e["art"] == "ende":
                start = offen.pop(e.get("song"), {})
                songs.append({"song": e.get("song"), "zeit": start.get("zeit", e["zeit"]), "wie": WIE_TEXT.get(e.get("start_wie"), ""),
                              "ende": ENDE_TEXT.get(e.get("wie"), ""), "dauer_s": e.get("dauer_s"), "sicher": e.get("sicher"),
                              "ohne_ton": e.get("ohne_ton"), "unsicher_in": e.get("unsicher_in") or [],
                              "korrekturen": e.get("korrekturen") or {}})
        hinweise = []
        for s in songs:
            name = f"„{s['song']}“ ({s['zeit'][:5]})"
            if s["sicher"] is not None and s["sicher"] < UNSICHER_GRENZE and (s["ohne_ton"] or 0) < 0.3:
                teile = f" Vor allem in: {', '.join(s['unsicher_in'][:3])}." if s["unsicher_in"] else ""
                hinweise.append(f"{name}: Das Programm war oft unsicher (nur {round(s['sicher'] * 100)} % sicher mitgehört).{teile} "
                                "In der Probe neu aufnehmen, oder die Band spielt live anders als in der Aufnahme.")
            if (s["ohne_ton"] or 0) >= 0.2:
                hinweise.append(f"{name}: {round(s['ohne_ton'] * 100)} % der Zeit kam kein Ton an. Kabel und Eingang prüfen.")
            for teil, anzahl in s["korrekturen"].items():
                if anzahl >= KORREKTUR_GRENZE:
                    hinweise.append(f"{name}: im Teil „{teil}“ {anzahl}-mal von Hand korrigiert. In der Probe die Teilgrenzen prüfen.")
        ton_weg = [e["zeit"][:5] for e in ereignisse if e["art"] == "ton_weg"]
        if ton_weg:
            hinweise.append(f"Der Ton war {len(ton_weg)}-mal weg ({', '.join(ton_weg[:5])}). Kabel, Stecker und den Eingang am Laptop prüfen.")
        dmx_weg = [e["zeit"][:5] for e in ereignisse if e["art"] == "dmx_weg"]
        if dmx_weg:
            hinweise.append(f"DMX war {len(dmx_weg)}-mal weg ({', '.join(dmx_weg[:5])}). USB-Kabel des Enttec prüfen (nicht über einen Hub).")
        return {"tag": tag, "tage": tage, "songs": songs, "hinweise": hinweise,
                "laeuft": [{"song": n, "zeit": e["zeit"]} for n, e in offen.items()],
                "ereignisse": [self._text(e) for e in ereignisse]}

    @staticmethod
    def _text(e: dict) -> dict:
        art = e.get("art")
        song = f"„{e.get('song', '')}“"
        if art == "start":
            text = f"{song} gestartet ({WIE_TEXT.get(e.get('wie'), '')})"
        elif art == "ende":
            sicher = f", {round(e['sicher'] * 100)} % sicher mitgehört" if e.get("sicher") is not None else ""
            text = f"{song} zu Ende ({ENDE_TEXT.get(e.get('wie'), '')}{sicher})"
        elif art == "korrektur":
            aktion = {"vor": "Nächster Teil", "zurueck": "Teil zurück", "teil": "Teil angeklickt", "cue": "Cue angeklickt"}
            text = f"{aktion.get(e.get('aktion'), 'Korrektur')} in {song}, Teil {e.get('teil', '')}"
        elif art == "vorschlag":
            text = f"Klingt nach {song}: als Vorschlag gezeigt"
        elif art == "look":
            from .showtasten import LOOKS
            namen = {look["id"]: look["name"] for look in LOOKS}
            text = f"Look-Taste: {namen.get(e.get('look'), e.get('look'))}"
        elif art == "blackout":
            text = "Blackout an" if e.get("an") else "Blackout aus"
        elif art == "applaus":
            text = "Applaus-Licht"
        elif art == "pause":
            text = "Pausenlicht"
        elif art == "ton_weg":
            text = f"Kein Ton mehr von „{e.get('eingang', '')}“"
        elif art == "ton_da":
            text = f"Ton wieder da (nach {e.get('nach_s', '?')} s)"
        elif art == "dmx_weg":
            text = "DMX weg: Das Enttec antwortet nicht"
        elif art == "dmx_da":
            text = "DMX wieder da"
        elif art == "fernbedienung":
            text = ("Fernbedienung an" if e.get("an") else "Fernbedienung aus") if "an" in e else "Handy verbunden"
        elif art == "mitschnitt":
            text = f"Mitschnitt von {song}: {e.get('ergebnis', '')}"
        elif art == "programm":
            text = f"Programm gestartet (Version {e.get('version', '')})"
        else:
            text = str(art)
        return {"zeit": e.get("zeit", ""), "art": art, "text": text}
