"""Fernbedienung: Handy oder Tablet im Saal drückt Looks, Farben und Halte-Tasten.

Auf der Show-Seite "Handy …" einschalten: Das Programm zeigt einen QR-Code und eine PIN. Wer den Code mit dem
Handy scannt, kommt auf eine eigene, kleine Seite mit großen Knöpfen:

    Looks 1-9 und Look aus, Farbe 1 und 2, Halten (Weiß voll, Strobo, Dunkel), Tap, Blackout,
    Song: Teil zurück, Nächster Teil, Songs der Setlist starten, Song stoppen.

Sicherheit:
    Die Fernbedienung ist ein eigener Zugang (eigener Port) und kann nur diese Knöpfe. Patch, Profile,
    Einstellungen, Sicherung und der Claude-Schlüssel sind von dort nie erreichbar.
    Ohne die 6-stellige PIN geht nichts. Nach 5 falschen PINs muss das Handy 30 s warten; nach 30 falschen
    insgesamt nimmt die Fernbedienung 5 Minuten lang gar keine PIN an (und der Laptop zeigt das).
    Sie ist nach jedem Programmstart aus. "Neue PIN" meldet alle Handys ab.
    Alle Grenzen gelten wie immer (Strobo, Prüfer), auch für das Handy.
    Die Verbindung ist nicht verschlüsselt: nur im eigenen WLAN oder im Handy-Hotspot benutzen.
"""
from __future__ import annotations

import hmac
import io
import logging
import secrets
import socket
import threading
import time
from typing import Optional

from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse

from . import daten, showtasten

PORT_WUNSCH = 8765
PIN_STELLEN = 6
FEHLVERSUCHE_PRO_HANDY = 5
SPERRE_HANDY_S = 30.0
FEHLVERSUCHE_GESAMT = 30
SPERRE_GESAMT_S = 300.0
MAX_HANDYS = 10
AKTIV_S = 10.0                 # so lange nach der letzten Anfrage zählt ein Handy als verbunden


def lan_adressen() -> list:
    """Die Adressen dieses Rechners im Netz (WLAN, Kabel), die beste zuerst."""
    adressen = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))           # schickt nichts, sucht nur die Schnittstelle aus
            adressen.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            adresse = info[4][0]
            if adresse not in adressen:
                adressen.append(adresse)
    except OSError:
        pass
    return [a for a in adressen if not a.startswith("127.") and not a.startswith("0.")]


def _freier_port(host: str, wunsch: int) -> int:
    for port in (wunsch, wunsch + 1, wunsch + 2, 0):
        with socket.socket() as probe:
            try:
                probe.bind((host, port))
                return probe.getsockname()[1]
            except OSError:
                continue
    raise OSError("Kein freier Port für die Fernbedienung.")


def qr_svg(text: str) -> str:
    import segno
    puffer = io.BytesIO()
    segno.make(text, error="m").save(puffer, kind="svg", scale=6, border=2, dark="#000000", light="#ffffff",
                                     xmldecl=False, svgns=True)
    return puffer.getvalue().decode("utf-8")


class Fernbedienung:
    def __init__(self, show):
        self.show = show
        self.sperre = threading.Lock()
        self.server = None
        self._faden: Optional[threading.Thread] = None
        self.port: Optional[int] = None
        self.pin: Optional[str] = None
        self.handys: dict = {}                     # Token -> {"seit", "zuletzt", "ip"}
        self.fehlversuche: dict = {}               # IP -> (Anzahl, gesperrt bis)
        self.fehlversuche_gesamt = 0
        self.gesperrt_bis = 0.0
        self.fehler: Optional[str] = None
        self._qr = (None, None)                    # (Link, SVG): nur neu, wenn sich der Link ändert
        self.host = "0.0.0.0"                      # von allen Geräten im Netz erreichbar (Tests: nur dieser Rechner)
        self.app = self._app_bauen()

    # --- Ein und aus (vom Laptop aus) ------------------------------------------------

    @property
    def an(self) -> bool:
        return self.server is not None

    def einschalten(self, host: Optional[str] = None) -> None:
        import uvicorn
        host = host or self.host
        with self.sperre:
            if self.server is not None:
                return
            port = _freier_port(host, PORT_WUNSCH)
            server = uvicorn.Server(uvicorn.Config(self.app, host=host, port=port, log_level="warning", log_config=None))
            faden = threading.Thread(target=server.run, name="Fernbedienung", daemon=True)
            faden.start()
            ende = time.monotonic() + 5.0
            while not server.started and faden.is_alive() and time.monotonic() < ende:
                time.sleep(0.02)
            if not server.started:
                server.should_exit = True
                self.fehler = "Die Fernbedienung ließ sich nicht starten (Port belegt oder vom Rechner blockiert)."
                raise ValueError(self.fehler)
            self.server, self._faden, self.port = server, faden, port
            self.pin, self.handys, self.fehler = self._neue_pin(), {}, None
            self.fehlversuche, self.fehlversuche_gesamt, self.gesperrt_bis = {}, 0, 0.0
        self.show.rueckblick.ereignis("fernbedienung", an=True)

    def ausschalten(self) -> None:
        with self.sperre:
            server, faden = self.server, self._faden
            self.server, self._faden, self.pin, self.handys = None, None, None, {}
        if server is not None:
            server.should_exit = True
            if faden is not None:
                faden.join(timeout=3.0)
            self.show.rueckblick.ereignis("fernbedienung", an=False)

    def neue_pin(self) -> None:
        """Neue PIN: Alle Handys sind abgemeldet und müssen neu scannen."""
        with self.sperre:
            if self.server is None:
                raise ValueError("Die Fernbedienung ist aus.")
            self.pin, self.handys = self._neue_pin(), {}

    @staticmethod
    def _neue_pin() -> str:
        return "".join(str(secrets.randbelow(10)) for _ in range(PIN_STELLEN))

    def handys_aktiv(self) -> int:
        jetzt = time.monotonic()
        return sum(1 for h in list(self.handys.values()) if jetzt - h["zuletzt"] < AKTIV_S)

    def zustand(self) -> dict:
        jetzt = time.monotonic()
        if self.server is None:
            return {"an": False, "fehler": self.fehler}
        adressen = [f"http://{a}:{self.port}" for a in lan_adressen()]
        link = f"{adressen[0]}/?pin={self.pin}" if adressen else None
        if link and self._qr[0] != link:
            self._qr = (link, qr_svg(link))
        return {"an": True, "pin": self.pin, "adressen": adressen, "link": link,
                "qr": self._qr[1] if link else None, "handys": self.handys_aktiv(),
                "gesperrt": jetzt < self.gesperrt_bis,
                "fehler": None if adressen else "Kein Netzwerk gefunden. Laptop und Handy müssen im selben WLAN sein "
                                                "(oder den Laptop mit dem Hotspot des Handys verbinden)."}

    # --- Anmelden -----------------------------------------------------------------

    def anmelden(self, pin: str, ip: str) -> str:
        jetzt = time.monotonic()
        with self.sperre:
            if self.pin is None:
                raise PermissionError("Die Fernbedienung ist aus.")
            if jetzt < self.gesperrt_bis:
                raise PermissionError("Zu viele falsche PINs. Die Fernbedienung nimmt gerade keine PIN an.")
            anzahl, bis = self.fehlversuche.get(ip, (0, 0.0))
            if jetzt < bis:
                raise PermissionError(f"Zu viele falsche PINs. Bitte {int(bis - jetzt) + 1} s warten.")
            if not hmac.compare_digest(str(pin or "").replace(" ", "").encode(), self.pin.encode()):
                anzahl += 1
                self.fehlversuche[ip] = (0, jetzt + SPERRE_HANDY_S) if anzahl >= FEHLVERSUCHE_PRO_HANDY else (anzahl, 0.0)
                self.fehlversuche_gesamt += 1
                if self.fehlversuche_gesamt >= FEHLVERSUCHE_GESAMT:
                    self.fehlversuche_gesamt, self.gesperrt_bis = 0, jetzt + SPERRE_GESAMT_S
                    logging.warning("Fernbedienung: viele falsche PINs, 5 Minuten gesperrt")
                raise PermissionError("Falsche PIN.")
            self.fehlversuche.pop(ip, None)
            if len(self.handys) >= MAX_HANDYS:
                aeltestes = min(self.handys, key=lambda t: self.handys[t]["zuletzt"])
                self.handys.pop(aeltestes)
            token = secrets.token_urlsafe(24)
            self.handys[token] = {"seit": jetzt, "zuletzt": jetzt, "ip": ip}
        self.show.rueckblick.ereignis("fernbedienung", handy="verbunden")
        return token

    def _pruefen(self, token: Optional[str]) -> None:
        with self.sperre:
            handy = self.handys.get(token or "")
            if handy is None:
                raise PermissionError("Nicht angemeldet.")
            handy["zuletzt"] = time.monotonic()

    # --- Was das Handy sieht und kann ---------------------------------------------

    def status(self) -> dict:
        show = self.show
        with show.sperre:
            tasten = show.pult.status()["tasten"]
            song = show.song.zustand()
        return {"looks": [{"id": l["id"], "name": l["name"], "taste": l["taste"]} for l in showtasten.LOOKS],
                "farben": showtasten.FARBEN, "halten": showtasten.HALTEN, "setlist": show.song.setlist(),
                "look": tasten["look"], "farbe_1": tasten["farbe_1"], "farbe_2": tasten["farbe_2"],
                "gehalten": tasten["halten"], "blackout": show.overrides.blackout,
                "song": {"name": song["name"], "teil": f"{song['jetzt']['name']} {song['jetzt']['gruppe']}".strip(),
                         "danach": f"{song['naechster']['name']} {song['naechster']['gruppe']}".strip() if song["naechster"] else "Ende"}
                if song.get("laeuft") else None,
                "zwischenlicht": show.zwischenlicht.zustand}

    def _app_bauen(self) -> FastAPI:
        app = FastAPI(title="Licht-Fernbedienung", docs_url=None, redoc_url=None, openapi_url=None)
        fern = self

        @app.exception_handler(PermissionError)
        async def nicht_erlaubt(_anfrage, fehler):
            return JSONResponse({"fehler": str(fehler)}, status_code=401)

        @app.exception_handler(ValueError)
        async def fehler_als_meldung(_anfrage, fehler):
            return JSONResponse({"fehler": str(fehler)}, status_code=400)

        @app.middleware("http")
        async def keine_speicherung(anfrage: Request, weiter):
            antwort = await weiter(anfrage)
            antwort.headers["Cache-Control"] = "no-store"
            antwort.headers["X-Frame-Options"] = "DENY"
            return antwort

        @app.get("/")
        def seite():
            return FileResponse(daten.PROJEKT / "web" / "fern.html")

        @app.post("/fern/anmelden")
        def anmelden(anfrage: Request, auftrag: dict = Body(...)):
            ip = anfrage.client.host if anfrage.client else "?"
            return {"token": fern.anmelden(str(auftrag.get("pin", "")), ip)}

        @app.get("/fern/zustand")
        def zustand(x_fern: Optional[str] = Header(default=None)):
            fern._pruefen(x_fern)
            return fern.status()

        @app.post("/fern/look/{look_id}")
        def look(look_id: str, x_fern: Optional[str] = Header(default=None)):
            fern._pruefen(x_fern)
            if look_id != "aus" and look_id not in {l["id"] for l in showtasten.LOOKS}:
                raise ValueError("Diesen Look gibt es nicht.")
            with fern.show.sperre:
                if look_id == "aus":
                    fern.show.pult.look_aus(time.monotonic())
                else:
                    fern.show.pult.look_druecken(look_id, time.monotonic())
            return fern.status()

        @app.post("/fern/farben")
        def farben(auftrag: dict = Body(...), x_fern: Optional[str] = Header(default=None)):
            fern._pruefen(x_fern)
            with fern.show.sperre:
                fern.show.pult.farben_setzen(auftrag.get("farbe_1"), auftrag.get("farbe_2"), time.monotonic())
            return fern.status()

        @app.post("/fern/halten/{art}")
        def halten(art: str, auftrag: dict = Body(default={}), x_fern: Optional[str] = Header(default=None)):
            fern._pruefen(x_fern)
            if art not in showtasten.HALTEN:
                raise ValueError("Diese Taste gibt es nicht.")
            with fern.show.sperre:
                fern.show.pult.halten_setzen(art, bool(auftrag.get("an", True)), time.monotonic())
            return {"ok": True}

        @app.post("/fern/tap")
        def tap(x_fern: Optional[str] = Header(default=None)):
            fern._pruefen(x_fern)
            with fern.show.sperre:
                tempo = fern.show.pult.tap(time.monotonic())
            return {"tempo": tempo}

        @app.post("/fern/blackout")
        def blackout(x_fern: Optional[str] = Header(default=None)):
            fern._pruefen(x_fern)
            with fern.show.sperre:
                fern.show.overrides.umschalten("blackout")
            return fern.status()

        @app.post("/fern/song/{aktion}")
        def song(aktion: str, auftrag: dict = Body(default={}), x_fern: Optional[str] = Header(default=None)):
            fern._pruefen(x_fern)
            spieler = fern.show.song
            if aktion == "vor":
                spieler.teil_vor()
            elif aktion == "zurueck":
                spieler.teil_zurueck()
            elif aktion == "stopp":
                spieler.stoppen()
            elif aktion == "start":
                name = str(auftrag.get("name", ""))
                if name not in spieler.setlist():
                    raise ValueError("Diesen Song gibt es nicht.")
                spieler.starten(name)
            else:
                raise ValueError("Unbekannte Aktion.")
            return fern.status()

        return app
