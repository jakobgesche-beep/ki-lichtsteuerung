"""Der Webserver: Die Oberfläche im Browser spricht nur über diese Datei mit der Show.

Alle Adressen beginnen mit /api. Was geändert wird, läuft durch dieselben
Prüfungen wie alles andere. Es gibt hier keinen Weg an der Prüfung vorbei.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .daten import PROJEKT
from .dmx_ausgabe import EnttecFehler
from .katalog import KatalogFehler
from .patch import FUNKTIONS_GRUPPEN, PatchFehler
from .show import Show

WEB_ORDNER = PROJEKT / "web"
LIVE_BILDER_PRO_SEKUNDE = 25


def patch_antwort(show: Show) -> dict:
    """Alles, was die Patch-Seite anzeigt."""
    probleme = show.patch.probleme()
    rot = {g for p in probleme for g in p["geraete"]}
    geraete = []
    for geraet in show.patch.geraete:
        typ = show.patch.typ(geraet)
        kanalzahl = show.patch.kanalzahl(geraet)
        geraete.append({
            **geraet, "kanalzahl": kanalzahl, "letzte_adresse": geraet["adresse"] + kanalzahl - 1,
            "typ_name": f"{typ.daten['hersteller']} {typ.daten['name']}",
            "handbuch_geprueft": typ.daten.get("handbuch_geprueft", False),
            "ort": show.buehne.geraet(geraet["id"]) or {}, "problem": geraet["id"] in rot,
        })
    return {"geraete": geraete, "probleme": probleme,
            "warnungen": show.patch.traverse_warnungen(show.buehne),
            "gruppen": sorted(set(FUNKTIONS_GRUPPEN) | set(show.patch.gruppen()))}


def erstelle_app(show: Optional[Show] = None) -> FastAPI:
    show = show or Show()
    app = FastAPI(title="Lichtsteuerung Technik-AG")
    app.state.show = show
    app.router.add_event_handler("startup", show.start)
    app.router.add_event_handler("shutdown", show.stopp)

    @app.middleware("http")
    async def nur_eigene_seite(anfrage: Request, weiter):
        """Fremde Webseiten dürfen die Show nicht fernsteuern."""
        herkunft = anfrage.headers.get("origin")
        if (anfrage.method != "GET" and herkunft
                and urlparse(herkunft).netloc != anfrage.headers.get("host")):
            return JSONResponse({"fehler": "Anfrage von fremder Seite."}, status_code=403)
        return await weiter(anfrage)

    @app.exception_handler(PatchFehler)
    @app.exception_handler(KatalogFehler)
    @app.exception_handler(ValueError)
    async def fehler_als_meldung(_anfrage, fehler):
        return JSONResponse({"fehler": str(fehler)}, status_code=400)

    # --- Katalog ---------------------------------------------------------

    @app.get("/api/katalog")
    def katalog_suche(suche: str = ""):
        return {"geraete": show.katalog.suche(suche), "gesamt": len(show.katalog.typen)}

    @app.get("/api/katalog/{hersteller}/{geraet}")
    def katalog_eintrag(hersteller: str, geraet: str):
        return show.katalog.typ(f"{hersteller}/{geraet}").daten

    @app.post("/api/katalog")
    def katalog_speichern(eintrag: dict = Body(...)):
        return show.katalog.speichere_eigenen(eintrag).kurzinfo()

    # --- Patch -----------------------------------------------------------

    @app.get("/api/patch")
    def patch_lesen():
        return patch_antwort(show)

    @app.get("/api/patch/naechste_freie")
    def patch_naechste_freie(kanaele: int):
        return {"adresse": show.patch.naechste_freie(kanaele)}

    @app.post("/api/patch")
    def patch_hinzufuegen(auftrag: dict = Body(...)):
        neue = show.patch.hinzufuegen(
            auftrag["typ"], auftrag["modus"], int(auftrag.get("anzahl", 1)), auftrag["name"],
            start=auftrag.get("start"), gruppen=auftrag.get("gruppen", []))
        ort = auftrag.get("ort", "boden")
        for nummer, geraet in enumerate(neue):
            platz = show.buehne.ort_vorschlag(ort, nummer, len(neue))
            if auftrag.get("montage"):
                platz["montage"] = auftrag["montage"]
            show.buehne.setze_geraet(geraet["id"], platz)
        speichern(show)
        return patch_antwort(show)

    @app.patch("/api/patch/{geraet_id}")
    def patch_aendern(geraet_id: str, aenderung: dict = Body(...)):
        ort = aenderung.pop("ort", None)
        erlaubt = {k: aenderung[k] for k in ("name", "adresse", "modus", "gruppen") if k in aenderung}
        show.patch.aendern(geraet_id, **erlaubt)
        if ort:
            show.buehne.setze_geraet(geraet_id, ort)
        speichern(show)
        return patch_antwort(show)

    @app.post("/api/patch/{geraet_id}/tausch")
    def patch_tausch(geraet_id: str, auftrag: dict = Body(...)):
        show.patch.tauschen(geraet_id, auftrag["typ"], auftrag["modus"])
        speichern(show)
        return patch_antwort(show)

    @app.delete("/api/patch/{geraet_id}")
    def patch_entfernen(geraet_id: str):
        show.patch.entfernen(geraet_id)
        show.buehne.entferne_geraet(geraet_id)
        speichern(show)
        return patch_antwort(show)

    # --- DMX-Test ---------------------------------------------------------

    @app.post("/api/dmxtest")
    def dmx_test(auftrag: dict = Body(...)):
        """Ein Gerät einzeln an, oder rohe Kanalwerte setzen. Leer beendet den Test."""
        kanaele = {int(k): int(v) for k, v in auftrag.get("kanaele", {}).items()}
        for kanal, wert in kanaele.items():
            if not 1 <= kanal <= 512 or not 0 <= wert <= 255:
                raise ValueError("Kanal 1 bis 512, Wert 0 bis 255.")
        geraet = auftrag.get("geraet")
        if geraet is not None:
            show.patch.geraet(geraet)
        with show.sperre:
            show.test_geraet, show.test_kanaele = geraet, kanaele
        return {"bild": list(show.baue_bild()), "meldungen": show.meldungen}

    @app.get("/api/dmx")
    def dmx_status():
        return {"eingeschaltet": show.ausgabe.eingeschaltet,
                "enttec_gefunden": show.ausgabe.enttec_gefunden(),
                "fehler": show.ausgabe.fehler, "bild": list(show.letztes_bild)}

    @app.post("/api/dmx/ein")
    def dmx_ein():
        try:
            show.ausgabe.einschalten()
        except EnttecFehler as fehler:
            raise ValueError(str(fehler)) from fehler
        return {"eingeschaltet": True}

    @app.post("/api/dmx/aus")
    def dmx_aus():
        show.ausgabe.ausschalten()
        return {"eingeschaltet": False}

    # --- Live-Daten für die 3D-Vorschau ------------------------------------

    @app.get("/api/buehne")
    def buehne_lesen():
        return show.buehnen_aufbau()

    @app.websocket("/api/live")
    async def live(verbindung: WebSocket):
        await verbindung.accept()
        try:
            while True:
                await verbindung.send_json(show.live_daten())
                await asyncio.sleep(1 / LIVE_BILDER_PRO_SEKUNDE)
        except (WebSocketDisconnect, RuntimeError):
            pass

    # --- Die Oberfläche ---------------------------------------------------

    @app.get("/")
    def startseite():
        return FileResponse(Path(WEB_ORDNER) / "index.html")

    app.mount("/", StaticFiles(directory=WEB_ORDNER), name="web")
    return app


def speichern(show: Show) -> None:
    show.patch.speichern()
    show.buehne.speichern()
    show.aufbauen()
