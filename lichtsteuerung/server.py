"""Der Webserver: Die Oberfläche im Browser spricht nur über diese Datei mit der Show.

Alle Adressen beginnen mit /api. Was geändert wird, läuft durch dieselben
Prüfungen wie alles andere. Es gibt hier keinen Weg an der Prüfung vorbei.
"""
from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .audio import quellen
from .cues import pruefe_cueliste
from .daten import PROJEKT
from .dmx_ausgabe import EnttecFehler
from .farben import FARBNAMEN
from .importe import gdtf, qxf
from .importe.gemeinsam import speichere_import
from .katalog import KatalogFehler
from .patch import FUNKTIONS_GRUPPEN, PatchFehler
from .profile import pruefe_profil
from .show import Show

WEB_ORDNER = PROJEKT / "web"
LIVE_BILDER_PRO_SEKUNDE = 25
AUDIO_ENDUNGEN = {".wav", ".flac", ".mp3", ".ogg", ".aiff"}


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

    @app.post("/api/katalog/importieren")
    async def katalog_importieren(anfrage: Request, name: str):
        """Nimmt eine .qxf- oder .gdtf-Datei entgegen."""
        endung = Path(name).suffix.lower()
        inhalt = await anfrage.body()
        try:
            if endung == ".qxf":
                eintrag = qxf.wandle(inhalt)
            elif endung == ".gdtf":
                eintrag = gdtf.wandle(inhalt)
            else:
                raise ValueError("Bitte eine .qxf- oder .gdtf-Datei wählen.")
        except ElementTree.ParseError as fehler:
            raise ValueError(f"Die Datei lässt sich nicht lesen: {fehler}") from fehler
        typ_id = speichere_import(eintrag, show.pfade.katalog)
        show.katalog.neu_laden()
        return {"id": typ_id}

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
        show.test_setzen(geraet, kanaele)
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

    # --- Override-Tasten ----------------------------------------------------

    @app.post("/api/override/{taste}")
    def override(taste: str):
        with show.sperre:
            show.overrides.umschalten(taste)
        return vars(show.overrides)

    # --- Profile -----------------------------------------------------------

    @app.get("/api/profile")
    def profile_lesen():
        return {"namen": show.profile.namen(), "aktiv": show.profil["name"]}

    @app.get("/api/profile/{name}")
    def profil_lesen(name: str):
        return show.profile.laden(name)

    @app.post("/api/profile/{name}/laden")
    def profil_laden(name: str):
        show.profil_laden(name)
        return {"aktiv": show.profil["name"]}

    @app.post("/api/profile")
    def profil_speichern(profil: dict = Body(...)):
        fehler = pruefe_profil(profil, show.patch.gruppen())
        if fehler:
            raise ValueError(" ".join(fehler))
        show.profile.speichern(profil)
        return {"name": profil["name"]}

    # --- Szenen und Vorschau ------------------------------------------------

    @app.get("/api/szenen")
    def szenen_lesen():
        gobos = {}
        for geraet in show.patch.geraete:
            for _, kanal in show.patch.typ(geraet).kanaele_im_modus(geraet["modus"]):
                if kanal["typ"] == "gobo":
                    for bereich in kanal.get("bereiche", []):
                        if bereich["typ"] == "platz":
                            gobos[bereich.get("name")] = True
        return {"namen": show.szenen.namen(), "positionen": list(show.positionen),
                "gruppen": show.patch.gruppen(), "gobos": list(gobos), "farben": list(FARBNAMEN),
                "geraete": [{"id": g["id"], "name": g["name"]} for g in show.patch.geraete]}

    @app.get("/api/szenen/{name}")
    def szene_lesen(name: str):
        szene = show.szenen.lesen(name)
        if szene is None:
            raise ValueError(f"Szene {name!r} gibt es nicht.")
        return szene

    @app.delete("/api/szenen/{name}")
    def szene_loeschen(name: str):
        show.szenen.loeschen(name)
        return {"namen": show.szenen.namen()}

    @app.post("/api/vorschau")
    def vorschau_setzen(auftrag: dict = Body(...)):
        """Zeigt einen Entwurf nur in der 3D-Vorschau. Nichts wird gesendet oder gespeichert."""
        return {"meldungen": show.vorschau.entwurf_setzen(auftrag["art"], auftrag["inhalt"])}

    @app.delete("/api/vorschau")
    def vorschau_verwerfen():
        show.vorschau.verwerfen()
        return {}

    @app.post("/api/vorschau/uebernehmen")
    def vorschau_uebernehmen():
        return {"name": show.vorschau.uebernehmen()}

    # --- Cuelisten ----------------------------------------------------------

    @app.get("/api/cuelisten")
    def cuelisten_lesen():
        return {"namen": show.cuelisten.namen()}

    @app.get("/api/cuelisten/{name}")
    def cueliste_lesen(name: str):
        liste = show.cuelisten.lesen(name)
        if liste is None:
            raise ValueError(f"Cueliste {name!r} gibt es nicht.")
        return liste

    @app.post("/api/cuelisten")
    def cueliste_speichern(liste: dict = Body(...)):
        fehler = pruefe_cueliste(liste, show.szenen)
        if fehler:
            raise ValueError(" ".join(fehler))
        show.cuelisten.schreiben(liste)
        if show.cues.liste and show.cues.liste["name"] == liste["name"]:
            show.cueliste_laden(liste["name"])
        return {"name": liste["name"]}

    @app.post("/api/cuelisten/{name}/laden")
    def cueliste_laden(name: str):
        show.cueliste_laden(name)
        return show.cues.status()

    @app.post("/api/cue/weiter")
    def cue_weiter():
        with show.sperre:
            show.cues.weiter(time.monotonic())
        return show.cues.status()

    @app.post("/api/cue/stopp")
    def cue_stopp():
        with show.sperre:
            show.cues.stopp(time.monotonic())
        return show.cues.status()

    # --- Fader --------------------------------------------------------------

    @app.post("/api/fader/{nummer}")
    def fader_setzen(nummer: int, auftrag: dict = Body(...)):
        with show.sperre:
            show.fader.setze(nummer, auftrag["wert"])
        return {}

    @app.post("/api/fader/{nummer}/belegen")
    def fader_belegen(nummer: int, belegung: dict = Body(...)):
        with show.sperre:
            show.fader.belegen(nummer, belegung, show.szenen, show.patch.gruppen())
        return {"fader": show.fader.status()}

    # --- Audio -------------------------------------------------------------

    @app.get("/api/audio")
    def audio_lesen():
        ordner = show.pfade.audio
        dateien = sorted(p.name for p in ordner.glob("*") if p.suffix.lower() in AUDIO_ENDUNGEN)
        return {"eingaenge": quellen.eingaenge(), "dateien": dateien}

    @app.post("/api/audio/quelle")
    def audio_quelle(auftrag: dict = Body(...)):
        art = auftrag.get("art", "aus")
        try:
            if art == "aus":
                show.audio.stoppen()
            elif art == "test":
                show.audio.starten(quellen.Testsignal(float(auftrag.get("bpm", 120))), "Testsignal")
            elif art == "datei":
                name = Path(auftrag["name"]).name     # nie aus dem Ordner hinaus
                show.audio.starten(quellen.Datei(show.pfade.audio / name), name)
            elif art == "eingang":
                nummer = auftrag.get("geraet")
                kanaele = tuple(auftrag.get("kanaele", (1,)))
                show.audio.starten(quellen.Eingang(nummer, kanaele), "Eingang")
            else:
                raise ValueError(f"Unbekannte Audioquelle: {art}")
        except quellen.AudioFehler as fehler:
            raise ValueError(str(fehler)) from fehler
        return {"quelle": show.audio.name}

    @app.post("/api/audio/hochladen")
    async def audio_hochladen(anfrage: Request, name: str):
        ziel = Path(name).name
        if Path(ziel).suffix.lower() not in AUDIO_ENDUNGEN:
            raise ValueError("Diese Dateiart kann das Programm nicht lesen.")
        show.pfade.audio.mkdir(parents=True, exist_ok=True)
        (show.pfade.audio / ziel).write_bytes(await anfrage.body())
        return {"name": ziel}

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
