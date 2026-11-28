"""Das iPad-Pult: die Live-Verbindung (WebSocket) zwischen iPad und MacBook.

Ablauf einer Verbindung:
    1. Das iPad öffnet ws://<MacBook>:8765/pult/ws und schickt als Erstes {"typ": "hallo", "token": …}.
       (Safari kann bei WebSockets keine eigenen Kopfzeilen schicken, und so steht der Schlüssel nicht im Link.)
    2. Stimmt der Schlüssel (siehe kopplung.py), kommt {"typ": "fest", …}: Geräte, Gruppen, Presets, Looks …
    3. Danach 25-mal pro Sekunde {"typ": "zustand", …} – aber nur mit den Teilen, die sich geändert haben.
       Alle 5 Sekunden einmal alles, damit nichts hängen bleibt.
    4. Das iPad schickt Befehle {"typ": "befehl", "seq": 17, "was": "fader", "nr": 3, "wert": 0.6} und bekommt
       {"typ": "antwort", "seq": 17, "ok": true} (oder "fehler"). Was erlaubt ist, steht in aktionen.py.
    5. Jede Sekunde {"typ": "ping"}. Kommt 4 s lang nichts, lässt das MacBook alle Tasten los, die dieses iPad
       festhielt (Flash, Weiß voll …). Das Licht selbst läuft immer weiter, auch ohne iPad.

Fader-Bewegungen werden zusammengefasst: Kommt ein neuer Wert, bevor der alte verarbeitet ist, zählt nur der neue.
Befehle laufen der Reihe nach in einem eigenen Faden, damit die Verbindung nie auf die Show-Sperre wartet.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from typing import Optional
from urllib.parse import urlparse

from . import adressierung, aktionen, showtasten
from .pult import EFFEKT_ARTEN, EXECUTOR_FARBEN, SEITEN, PRO_SEITE, TASTEN_ARTEN
from .version import VERSION

PROTOKOLL = 1
TAKT_S = 1 / 25
BUEHNE_JEDER = 2          # Bühnenbild jeden zweiten Takt (12,5-mal pro Sekunde)
VOLL_ALLE_S = 5.0
FEST_PRUEFEN_S = 2.0
HALLO_S = 3.0
STILL_S = 4.0             # so lange keine Nachricht: Tasten des iPads loslassen
INTERNET_S = 30.0
MAX_CHAT = 30             # so viele Chat-Zeilen gehen ans iPad


def _r(wert, stellen=3):
    return round(float(wert), stellen) if isinstance(wert, (int, float)) else wert


def fest(show) -> dict:
    """Was sich selten ändert: Geräte (mit Adresse und DIP), Gruppen, Presets, Looks, Bühne."""
    with show.sperre:
        geraete = []
        for g in show.patch.geraete:
            typ = show.patch.typ(g)
            geraete.append({**show.faehigkeiten(g), "adresse": g["adresse"],
                            "kanaele": show.patch.kanalzahl(g), "modus": g["modus"],
                            "typ": f"{typ.daten['hersteller']} {typ.daten['name']}",
                            "einstellen": adressierung.info_fuer(typ.daten)})
        presets = [{"nummer": i, "name": p["name"], "art": p["art"]} for i, p in enumerate(show.pult.presets)]
        aufbau = show.buehnen_aufbau()
    return {"version": VERSION, "protokoll": PROTOKOLL, "geraete": geraete, "gruppen": show.patch.gruppen(),
            "presets": presets, "positionen": sorted(show.positionen), "sequenzen": show.pult.sequenzen.namen(),
            "looks": [{"id": l["id"], "name": l["name"], "taste": l.get("taste")} for l in showtasten.LOOKS],
            "farben": showtasten.FARBEN, "halten": showtasten.HALTEN, "effekte": list(EFFEKT_ARTEN),
            "profile": show.profile.namen(), "aufbau": aufbau, "exec_farben": list(EXECUTOR_FARBEN),
            "tasten_arten": TASTEN_ARTEN, "seiten": SEITEN, "pro_seite": PRO_SEITE,
            "setlist": show.song.setlist()}


def _executor(pult, e) -> dict:
    info = pult.executor_info(e)
    if e.sequenz and 0 <= e.index < len(e.sequenz["cues"]):
        cue = e.sequenz["cues"][e.index]
        dauer = float(cue.get("zeit_s") or 0)
        info["blende"] = 1.0 if dauer <= 0 else _r(min(1.0, (time.monotonic() - e.start) / dauer), 2)
    return info


def stand(show, mit_buehne: bool) -> dict:
    """Was sich ständig ändert. Muss unter der Show-Sperre gebaut werden (macht der Aufrufer)."""
    pult = show.pult
    haupt = pult.executor(pult.haupt + 1)
    werte = show.audio.aktuell()
    frisch = show.audio.frisch() is not None
    song = show.song.zustand()
    tasten = {"look": pult.look if pult.tasten.index >= 0 else None, "farbe_1": pult.farbe_1, "farbe_2": pult.farbe_2,
              "halten": {a: s is not None for a, s in pult.halten.items()}, "tempo_quelle": pult.tempo_quelle,
              "tempo_getippt": _r(pult.tempo_getippt, 1) if pult.tempo_getippt else None}
    ergebnis = {
        "exec": {str(e.nummer): _executor(pult, e) for e in pult.executoren},
        "master": {"grand": _r(pult.grand), "haupt": pult.haupt + 1,
                   "haupt_cues": [c["name"] for c in haupt.sequenz["cues"]] if haupt.sequenz else [],
                   "haupt_index": haupt.index, "tempo_faktor": _r(pult.effekte.faktor if pult.effekte else 1.0, 2),
                   "oops": len(pult.oops)},
        "ov": dict(vars(show.overrides)),
        "prog": {"auswahl": list(pult.auswahl), "werte": pult.programmer.werte, "effekte": pult.programmer.effekte,
                 "blind": pult.programmer.blind, "highlight": pult.highlight},
        "musik": {"bpm": _r(show._musik_bpm(), 1), "beats": show.audio.beat_zaehler, "eins": show.audio.eins_zaehler,
                  "ton": "ok" if frisch else ("gehalten" if werte is not None else ("aus" if show.audio.name == "aus" else "weg")),
                  "quelle": show.audio.name, "rede": bool(werte and werte.rede), "applaus": bool(werte and werte.applaus),
                  "drop": bool(werte and (werte.drop or werte.spannung >= 0.3)), "leise": bool(werte and werte.leise),
                  "staerke": _r(werte.intensitaet if werte else 0.0, 2), "stufe": show.engine.stufe,
                  "look": show.engine.look.name if show.automatik_an else None, "engine": show.engine.zustand_text},
        "show": {"automatik": show.automatik_an, "profil": show.profil["name"], "regie": show.regie.an,
                 "look": tasten["look"], "farbe_1": tasten["farbe_1"], "farbe_2": tasten["farbe_2"],
                 "halten": tasten["halten"], "tap": tasten["tempo_getippt"], "tempo_quelle": tasten["tempo_quelle"],
                 "song": song if song.get("laeuft") else None, "erkennung": show.song.erkennung_zustand(),
                 "follow_spot": show.follow_spot.zustand(), "strobo_erlaubt": show.profil["strobo"] != "aus"},
        "chat": {"denkt": show.chat.denkt, "zeilen": show.chat.status()["anzeige"][-MAX_CHAT:],
                 "entwurf": _entwurf(show.chat.entwurf), "bereit": show.ki.status().get("bereit", False)},
        "dmx": {"an": show.ausgabe.eingeschaltet, "verbunden": bool(show.ausgabe.status().get("verbunden"))},
        "meld": sorted(set(show.meldungen))[:8] + pult.aktuelle_hinweise(),
    }
    if mit_buehne:
        geraete = show.simulator.lies(show.letztes_bild)
        ergebnis["buehne"] = [{"id": g["id"], "hell": _r(g["hell"], 2), "farbe": [_r(f, 2) for f in g["farbe"]],
                               "richtung": [_r(r, 2) for r in g["richtung"]] if g.get("richtung") else None}
                              for g in geraete]
        vorschau = show.chat_vorschau_geraete if show.chat.entwurf else None
        ergebnis["vorschau"] = ([{"id": g["id"], "hell": _r(g["hell"], 2), "farbe": [_r(f, 2) for f in g["farbe"]],
                                  "richtung": [_r(r, 2) for r in g["richtung"]] if g.get("richtung") else None}
                                 for g in vorschau] if vorschau else None)
    return ergebnis


def _entwurf(entwurf: Optional[dict]) -> Optional[dict]:
    if not entwurf:
        return None
    sequenz = entwurf.get("sequenz") or {}
    return {"art": entwurf.get("art"), "name": sequenz.get("name") or entwurf.get("name"),
            "erklaerung": entwurf.get("erklaerung", ""), "fader": entwurf.get("fader"), "cue": entwurf.get("cue", 0),
            "cues": [{"name": c.get("name", ""), "zeit_s": c.get("zeit_s"),
                      "effekte": [e.get("art") for e in c.get("effekte", [])]} for c in sequenz.get("cues", [])]}


def _herkunft_passt(websocket) -> bool:
    """Wie am MacBook: Eine fremde Seite darf keine Verbindung aufbauen (Origin muss zum Host passen)."""
    origin = websocket.headers.get("origin")
    if not origin:
        return True                      # keine Browser-Seite (zum Beispiel Tests)
    return urlparse(origin).netloc == websocket.headers.get("host", "")


class Verbindung:
    def __init__(self, websocket, sitzung: aktionen.Sitzung):
        self.ws = websocket
        self.sitzung = sitzung
        self.zuletzt: dict = {}
        self.zuletzt_exec: dict = {}
        self.voll_zeit = 0.0
        self.fest_kennung = None
        self.letzte_nachricht = time.monotonic()
        self.losgelassen = False
        self.warteschlange: asyncio.Queue = asyncio.Queue()
        self.fader_neu: dict = {}         # Fader-Nummer -> (Wert, seq): nur der neueste zählt
        self.sperre = asyncio.Lock()      # nie zwei Nachrichten gleichzeitig senden

    async def senden(self, nachricht: dict) -> None:
        async with self.sperre:
            await self.ws.send_json(nachricht)

    async def zustand_senden(self, teil_stand: dict, voll: bool) -> None:
        teile = {}
        for schluessel, wert in teil_stand.items():
            if schluessel == "exec":
                neu = {n: e for n, e in wert.items() if voll or self.zuletzt_exec.get(n) != e}
                if neu:
                    teile["exec"] = neu
                    self.zuletzt_exec.update(neu)
            elif voll or self.zuletzt.get(schluessel) != wert:
                teile[schluessel] = wert
                self.zuletzt[schluessel] = wert
        if voll:
            self.voll_zeit = time.monotonic()
        if teile:
            await self.senden({"typ": "zustand", "voll": voll, **teile})


class Hub:
    """Alle verbundenen iPads. Ein Takt baut den Stand einmal und schickt jedem seine Änderungen."""

    def __init__(self, show, kopplung):
        self.show = show
        self.kopplung = kopplung
        self.verbindungen: set = set()
        self._takt: Optional[asyncio.Task] = None
        self._fest: Optional[dict] = None
        self._fest_kennung = 0
        self._fest_zeit = 0.0
        self.internet: Optional[bool] = None
        self._internet_zeit = -INTERNET_S

    def anzahl(self) -> int:
        return len(self.verbindungen)

    # --- Eine Verbindung --------------------------------------------------------------

    async def verbinden(self, websocket) -> None:
        await websocket.accept()
        if not _herkunft_passt(websocket):
            await websocket.close(code=4403)
            return
        try:
            hallo = await asyncio.wait_for(websocket.receive_json(), HALLO_S)
        except Exception:
            await self._schliessen(websocket, 4400)
            return
        geraet = self.kopplung.pruefen(str(hallo.get("token") or "")) if isinstance(hallo, dict) else None
        if not isinstance(hallo, dict) or hallo.get("typ") != "hallo" or geraet is None:
            await self._schliessen(websocket, 4401)
            return
        verbindung = Verbindung(websocket, aktionen.Sitzung(self.show, geraet["name"]))
        try:
            await self._fest_senden(verbindung, erzwingen=True)
            self.verbindungen.add(verbindung)
            logging.info("iPad-Pult: „%s“ verbunden", geraet["name"])
            if self._takt is None or self._takt.done():
                self._takt = asyncio.ensure_future(self._takten())
            arbeiter = asyncio.ensure_future(self._abarbeiten(verbindung))
            try:
                await self._empfangen(verbindung)
            finally:
                arbeiter.cancel()
        finally:
            self.verbindungen.discard(verbindung)
            await asyncio.to_thread(aktionen.loslassen, self.show, verbindung.sitzung)
            logging.info("iPad-Pult: „%s“ getrennt", geraet["name"])

    async def _schliessen(self, websocket, code: int) -> None:
        try:
            await websocket.close(code=code)
        except Exception:
            pass

    async def _empfangen(self, verbindung: Verbindung) -> None:
        while True:
            try:
                nachricht = await asyncio.wait_for(verbindung.ws.receive_json(), STILL_S)
            except asyncio.TimeoutError:
                if not verbindung.losgelassen:          # iPad schläft oder WLAN weg: Tasten los, Verbindung offen
                    verbindung.losgelassen = True
                    await asyncio.to_thread(aktionen.loslassen, self.show, verbindung.sitzung)
                continue
            except Exception:
                return                                   # Verbindung zu
            verbindung.letzte_nachricht = time.monotonic()
            verbindung.losgelassen = False
            if not isinstance(nachricht, dict):
                continue
            typ = nachricht.get("typ")
            if typ == "ping":
                await verbindung.senden({"typ": "pong", "t": nachricht.get("t")})
            elif typ == "befehl":
                if nachricht.get("was") == "fader":
                    neu = (nachricht, nachricht.get("seq"))
                    schon = str(nachricht.get("nr")) in verbindung.fader_neu
                    verbindung.fader_neu[str(nachricht.get("nr"))] = neu
                    if not schon:
                        verbindung.warteschlange.put_nowait(("fader", str(nachricht.get("nr"))))
                else:
                    verbindung.warteschlange.put_nowait(("befehl", nachricht))

    async def _abarbeiten(self, verbindung: Verbindung) -> None:
        """Befehle der Reihe nach, jeweils in einem Faden (die Show-Sperre blockiert so nie die Verbindung)."""
        while True:
            art, inhalt = await verbindung.warteschlange.get()
            if art == "fader":
                nachricht, _ = verbindung.fader_neu.pop(inhalt, (None, None))
                if nachricht is None:
                    continue
            else:
                nachricht = inhalt
            was = str(nachricht.get("was", ""))
            antwort = {"typ": "antwort", "seq": nachricht.get("seq"), "was": was}
            try:
                if was in aktionen.LANGSAM:
                    # Claude & Co. brauchen Sekunden: nebenher, damit Fader und Tasten nicht warten
                    asyncio.ensure_future(self._langsam(verbindung, nachricht, antwort))
                    continue
                ergebnis = await asyncio.to_thread(aktionen.ausfuehren, self.show, was, nachricht, verbindung.sitzung)
                antwort.update(ok=True, ergebnis=ergebnis)
            except (ValueError, KeyError, PermissionError) as fehler:
                antwort.update(ok=False, fehler=str(fehler))
            except Exception as fehler:
                logging.exception("iPad-Befehl %s", was)
                antwort.update(ok=False, fehler=f"Interner Fehler: {fehler}")
            try:
                await verbindung.senden(antwort)
            except Exception:
                return

    async def _langsam(self, verbindung: Verbindung, nachricht: dict, antwort: dict) -> None:
        try:
            ergebnis = await asyncio.to_thread(aktionen.ausfuehren, self.show, antwort["was"], nachricht,
                                               verbindung.sitzung)
            antwort.update(ok=True, ergebnis=ergebnis)
        except (ValueError, KeyError, PermissionError) as fehler:
            antwort.update(ok=False, fehler=str(fehler))
        except Exception as fehler:
            logging.exception("iPad-Befehl %s", antwort["was"])
            antwort.update(ok=False, fehler=f"Interner Fehler: {fehler}")
        try:
            await verbindung.senden(antwort)
        except Exception:
            pass

    # --- Der Takt ---------------------------------------------------------------------

    async def _fest_senden(self, verbindung: Verbindung, erzwingen: bool = False) -> None:
        jetzt = time.monotonic()
        if self._fest is None or jetzt - self._fest_zeit > FEST_PRUEFEN_S:
            neu = await asyncio.to_thread(fest, self.show)
            if neu != self._fest:
                self._fest, self._fest_kennung = neu, self._fest_kennung + 1
            self._fest_zeit = jetzt
        if erzwingen or verbindung.fest_kennung != self._fest_kennung:
            verbindung.fest_kennung = self._fest_kennung
            await verbindung.senden({"typ": "fest", "internet": self.internet, **self._fest})

    def _stand_bauen(self, mit_buehne: bool) -> Optional[dict]:
        if not self.show.sperre.acquire(timeout=0.03):
            return None                                  # Show rechnet gerade lange: diesen Takt auslassen
        try:
            teil = stand(self.show, mit_buehne)
        finally:
            self.show.sperre.release()
        teil["netz"] = {"internet": self.internet, "ipads": len(self.verbindungen)}
        return teil

    def _internet_pruefen(self) -> None:
        try:
            with socket.create_connection(("api.anthropic.com", 443), timeout=2.0):
                self.internet = True
        except OSError:
            self.internet = False

    async def _takten(self) -> None:
        nummer = 0
        schleife = asyncio.get_event_loop()
        while self.verbindungen:
            beginn = schleife.time()
            try:
                if time.monotonic() - self._internet_zeit > INTERNET_S:
                    self._internet_zeit = time.monotonic()
                    threading.Thread(target=self._internet_pruefen, name="Internet?", daemon=True).start()
                teil = await asyncio.to_thread(self._stand_bauen, nummer % BUEHNE_JEDER == 0)
                if teil is not None:
                    for verbindung in list(self.verbindungen):
                        try:
                            await self._fest_senden(verbindung)
                            voll = time.monotonic() - verbindung.voll_zeit > VOLL_ALLE_S
                            await verbindung.zustand_senden(teil, voll)
                        except Exception:
                            self.verbindungen.discard(verbindung)
            except Exception:
                logging.exception("iPad-Takt")
            nummer += 1
            await asyncio.sleep(max(0.0, TAKT_S - (schleife.time() - beginn)))
