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
from pathlib import Path
import io
import logging
import secrets
import socket
import sys
import threading
import time
from typing import Optional

from fastapi import Body, FastAPI, Header, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import daten, showtasten
from .kopplung import Kopplung
from .tablet import Hub
from .version import VERSION

PORT_WUNSCH = 8765
PIN_STELLEN = 6
FEHLVERSUCHE_PRO_HANDY = 5
SPERRE_HANDY_S = 30.0
FEHLVERSUCHE_GESAMT = 30
SPERRE_GESAMT_S = 300.0
MAX_HANDYS = 10
AKTIV_S = 10.0                 # so lange nach der letzten Anfrage zählt ein Handy als verbunden
TABLET = daten.PROJEKT / "web" / "tablet"
GEMEINSAM = daten.PROJEKT / "web" / "gemeinsam"
MEDIEN = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".png": "image/png",
          ".svg": "image/svg+xml", ".json": "application/json", ".webmanifest": "application/manifest+json",
          ".html": "text/html; charset=utf-8"}


def rechnername() -> Optional[str]:
    """Der Bonjour-Name des Macs (zum Beispiel MacBook-Air-von-Jakob): Damit bleibt die iPad-Adresse gleich,
    auch wenn der Router dem Mac eine andere IP gibt."""
    import subprocess
    import sys
    if sys.platform != "darwin":
        return None
    try:
        name = subprocess.run(["/usr/sbin/scutil", "--get", "LocalHostName"], capture_output=True, text=True,
                              timeout=3).stdout.strip()
    except Exception:
        return None
    return name or None


def _datei_aus(ordner, pfad: str):
    """Eine Datei aus dem Ordner, nie darüber hinaus (kein ../, kein absoluter Pfad).

    Absichtlich ohne resolve(): In der Mac-App liegen die Dateien hinter Symlinks (Contents/Frameworks →
    Contents/Resources). Mit resolve() sah jede Datei so aus, als läge sie außerhalb (Fehler in 2.5.0)."""
    teile = Path(str(pfad).replace("\\", "/")).parts
    if not teile or Path(pfad).is_absolute() or any(t in ("..", "") or ":" in t for t in teile):
        raise FileNotFoundError(pfad)
    ziel = Path(ordner, *teile)
    if not ziel.is_file():
        raise FileNotFoundError(pfad)
    return ziel


NAMEN_NEU_S = 30.0             # so lange gelten die über den Rechnernamen gefundenen Adressen
NAMEN_WARTEN_S = 0.3           # so lange wartet eine Anfrage höchstens auf die Namensauflösung
_namen = {"zeit": None, "liste": [], "faden": None}
_namen_sperre = threading.Lock()


def _namen_nachschlagen() -> None:
    try:
        liste = [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except (OSError, UnicodeError):
        liste = []
    with _namen_sperre:
        _namen.update(zeit=time.monotonic(), liste=liste)


def _namens_adressen(warten_s: float = NAMEN_WARTEN_S) -> list:
    """Adressen über den Rechnernamen. Das kann hängen: ohne DNS im Router (Saal ohne Internet) oder auf den
    Mac-Bau-Rechnern bei GitHub mehrere Sekunden lang (daran scheiterte der Selbsttest von 2.5.0). Darum im
    Hintergrund, mit Zwischenspeicher, und eine Anfrage wartet höchstens kurz darauf."""
    neu = None
    with _namen_sperre:
        veraltet = _namen["zeit"] is None or time.monotonic() - _namen["zeit"] >= NAMEN_NEU_S
        faden = _namen["faden"]
        if veraltet and (faden is None or not faden.is_alive()):
            neu = threading.Thread(target=_namen_nachschlagen, name="Rechnername", daemon=True)
            _namen["faden"] = neu
            neu.start()
    if neu is not None and warten_s > 0:
        neu.join(warten_s)          # nur wer die Suche startet, wartet kurz; alle anderen nehmen den letzten Stand
    with _namen_sperre:
        return list(_namen["liste"])


def lan_adressen() -> list:
    """Die Adressen dieses Rechners im Netz (WLAN, Kabel), die beste zuerst. Immer schnell (höchstens ~0,3 s)."""
    adressen = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))           # schickt nichts, sucht nur die Schnittstelle aus
            adressen.append(probe.getsockname()[0])
    except OSError:
        pass
    for adresse in _namens_adressen():
        if adresse not in adressen:
            adressen.append(adresse)
    return [a for a in adressen if not a.startswith("127.") and not a.startswith("0.")]


def _port_frei(host: str, port: int) -> Optional[int]:
    with socket.socket() as probe:
        if sys.platform != "win32":
            # Wie uvicorn selbst: Verbindungen eines eben beendeten Programms (TIME_WAIT) blockieren den Port nicht
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
            return probe.getsockname()[1]
        except OSError:
            return None


def _freier_port(host: str, wunsch: int, warten_s: float = 0.0) -> int:
    """Am liebsten immer derselbe Port: Das Symbol auf dem iPad merkt sich die Adresse mit Port.
    Nach einem schnellen Neustart darf es kurz dauern, bis der alte Port frei ist (`warten_s`)."""
    ende = time.monotonic() + warten_s
    while True:
        frei = _port_frei(host, wunsch)
        if frei is not None:
            return frei
        if time.monotonic() >= ende:
            break
        time.sleep(0.5)
    for port in (wunsch + 1, wunsch + 2, 0):
        frei = _port_frei(host, port)
        if frei is not None:
            return frei
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
        self.kopplung = Kopplung(show.pfade.wurzel / "daten" / "netz_geraete.json")
        self.hub = Hub(show, self.kopplung)
        self.einstellung_pfad = show.pfade.wurzel / "daten" / "netz.json"
        self._name = None
        self.app = self._app_bauen()

    # --- Ein und aus (vom Laptop aus) ------------------------------------------------

    @property
    def an(self) -> bool:
        return self.server is not None

    def einschalten(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        import uvicorn
        host = host or self.host
        with self.sperre:
            if self.server is not None:
                return
            port = port or _freier_port(host, PORT_WUNSCH, warten_s=8.0 if self.kopplung.hat_ipad() else 0.0)
            if port != PORT_WUNSCH and host == self.host:
                logging.warning("Netz-Server: Port %d belegt, nehme %d (Lesezeichen auf dem iPad passen dann nicht)",
                                PORT_WUNSCH, port)
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

    # --- iPad-Pult ---------------------------------------------------------------------

    def beim_start(self) -> bool:
        return bool((daten.lese_json_sicher(self.einstellung_pfad, {}) or {}).get("beim_start", True))

    def beim_start_setzen(self, an: bool) -> None:
        daten.schreibe_json(self.einstellung_pfad, {"beim_start": bool(an)})

    def automatisch_starten(self) -> None:
        """Beim Programmstart: Ist ein iPad gekoppelt (und nicht abgeschaltet), läuft der Netz-Server gleich mit."""
        if self.kopplung.hat_ipad() and self.beim_start():
            try:
                self.einschalten()
            except Exception as fehler:
                logging.warning("Netz-Server startet nicht: %s", fehler)

    def ipad_koppeln(self) -> dict:
        """Knopf am MacBook: Netz-Server an (falls aus) und 5 Minuten Kopplungsfenster mit PIN."""
        if self.server is None:
            self.einschalten()
        self.kopplung.fenster_oeffnen()
        return self.ipad_zustand()

    def ipad_links(self, pin: Optional[str] = None) -> list:
        if self.server is None:
            return []
        if self._name is None:
            self._name = rechnername() or ""
        frage = f"?pin={pin}" if pin else ""
        links = []
        if self._name:
            links.append({"art": "name", "link": f"http://{self._name}.local:{self.port}/pult/{frage}"})
        links += [{"art": "ip", "link": f"http://{a}:{self.port}/pult/{frage}"} for a in lan_adressen()]
        return links

    def ipad_zustand(self) -> dict:
        fenster = self.kopplung.fenster()
        links = self.ipad_links(fenster["pin"] if fenster["offen"] else None)
        qr = None
        if links:
            link = links[0]["link"]
            if self._qr[0] != link:
                self._qr = (link, qr_svg(link))
            qr = self._qr[1]
        return {"an": self.server is not None, "port": self.port, "links": links, "qr": qr, "fenster": fenster,
                "geraete": self.kopplung.liste(), "verbunden": self.hub.anzahl(), "beim_start": self.beim_start(),
                "fehler": self.fehler}

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
                "zwischenlicht": show.zwischenlicht.zustand, "follow_spot": show.follow_spot.zustand(),
                "buehne": show.buehne.daten.get("buehne")}

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

        # --- iPad-Pult: Seite und Dateien (ohne Schlüssel, darin steht nichts Geheimes) ---------------

        @app.get("/pult")
        @app.get("/pult/")
        def pult_seite():
            html = (TABLET / "index.html").read_text("utf-8").replace("{{VERSION}}", VERSION)
            return HTMLResponse(html)

        @app.get("/pult/static/{pfad:path}")
        def pult_datei(pfad: str):
            try:
                ziel = _datei_aus(TABLET, pfad)
            except FileNotFoundError:
                return JSONResponse({"fehler": "Gibt es nicht."}, status_code=404)
            return Response(ziel.read_bytes(), media_type=MEDIEN.get(ziel.suffix, "application/octet-stream"))

        @app.get("/gemeinsam/{pfad:path}")
        def gemeinsame_datei(pfad: str):
            try:
                ziel = _datei_aus(GEMEINSAM, pfad)
            except FileNotFoundError:
                return JSONResponse({"fehler": "Gibt es nicht."}, status_code=404)
            return Response(ziel.read_bytes(), media_type=MEDIEN.get(ziel.suffix, "application/octet-stream"))

        @app.get("/pult/manifest.webmanifest")
        def manifest():
            return JSONResponse({
                "name": "Lichtpult", "short_name": "Lichtpult", "start_url": "/pult/", "scope": "/pult/",
                "display": "standalone", "orientation": "landscape", "background_color": "#000000",
                "theme_color": "#000000",
                "icons": [{"src": "/pult/static/symbol-192.png", "sizes": "192x192", "type": "image/png"},
                          {"src": "/pult/static/symbol-512.png", "sizes": "512x512", "type": "image/png"}]},
                media_type="application/manifest+json")

        @app.post("/pult/koppeln")
        def pult_koppeln(anfrage: Request, auftrag: dict = Body(...)):
            adresse = anfrage.client.host if anfrage.client else "?"
            token = fern.kopplung.koppeln(str(auftrag.get("pin", "")), str(auftrag.get("name", "iPad")), adresse)
            fern.show.rueckblick.ereignis("fernbedienung", handy="iPad gekoppelt")
            return {"token": token}

        @app.websocket("/pult/ws")
        async def pult_ws(websocket: WebSocket):
            await fern.hub.verbinden(websocket)

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

        @app.post("/fern/followspot")
        def follow_spot(auftrag: dict = Body(...), x_fern: Optional[str] = Header(default=None)):
            fern._pruefen(x_fern)
            with fern.show.sperre:
                if auftrag.get("aus"):
                    fern.show.follow_spot.aus()
                else:
                    fern.show.follow_spot.setzen(float(auftrag["x"]), float(auftrag["y"]))
            return fern.show.follow_spot.zustand()

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
