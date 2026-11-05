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
from .daten import PROJEKT
from .dmx_ausgabe import EnttecFehler
from .farben import FARBNAMEN
from .importe import gdtf, qxf
from .importe.gemeinsam import speichere_import
from .katalog import KatalogFehler
from .patch import FUNKTIONS_GRUPPEN, PatchFehler
from .profile import pruefe_profil
from .pult import EFFEKT_ARTEN, pruefe_effekt
from .szenen import pruefe_werte
from .show import Show

WEB_ORDNER = PROJEKT / "web"
LIVE_BILDER_PRO_SEKUNDE = 40
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


def geraet_faehigkeiten(show: Show, geraet: dict) -> dict:
    """Was die Bedienung zu einem Gerät wissen muss, damit sie nur Passendes anbietet."""
    kanaele = [k for _, k in show.patch.typ(geraet).kanaele_im_modus(geraet["modus"])]
    typen = {k["typ"] for k in kanaele}
    gobos, farbrad = [], []
    for kanal in kanaele:
        plaetze = [b for b in kanal.get("bereiche", []) if b["typ"] == "platz"]
        if kanal["typ"] == "gobo":
            gobos = [b["name"] for b in plaetze]
        if kanal["typ"] == "farbrad":
            farbrad = [{"name": b.get("name"), "farbe": b.get("farbe")} for b in plaetze if b.get("farbe")]
    return {"id": geraet["id"], "name": geraet["name"], "gruppen": show.patch.gruppen_von(geraet),
            "dimmer": "dimmer" in typen or bool(typen & {"rot", "gruen", "blau", "weiss"}),
            "farbe": "mischung" if typen & {"rot", "gruen", "blau"} else "rad" if farbrad else None,
            "farbrad": farbrad, "beweglich": "pan" in typen or "tilt" in typen, "gobos": gobos,
            "drehung": any(b["typ"] == "drehung" for k in kanaele for b in k.get("bereiche", []))}


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
        if isinstance(ort, str):
            # Nur der Ort wurde gewählt: Das Programm hängt das Gerät passend hin.
            alter_ort = (show.buehne.geraet(geraet_id) or {}).get("ort")
            show.buehne.setze_geraet(geraet_id, show.buehne.ort_vorschlag(ort, 0, 1))
            show.buehne.verteilen(ort)
            if alter_ort and alter_ort != ort:
                show.buehne.verteilen(alter_ort)
        elif ort:
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

    # --- Profil-Entwürfe (Vorschau, dann Übernehmen) -------------------------

    @app.post("/api/vorschau")
    def vorschau_setzen(auftrag: dict = Body(...)):
        """Zeigt einen Entwurf nur in der Vorschau. Nichts wird gesendet oder gespeichert."""
        return {"meldungen": show.vorschau.entwurf_setzen(auftrag["art"], auftrag["inhalt"])}

    @app.delete("/api/vorschau")
    def vorschau_verwerfen():
        show.vorschau.verwerfen()
        return {}

    @app.post("/api/vorschau/uebernehmen")
    def vorschau_uebernehmen():
        return {"name": show.vorschau.uebernehmen()}

    # --- Pult: Programmer, Sequenzen, Executoren ----------------------------

    @app.get("/api/pult")
    def pult_lesen():
        return {"geraete": [geraet_faehigkeiten(show, g) for g in show.patch.geraete],
                "gruppen": show.patch.gruppen(), "positionen": list(show.positionen),
                "farben": list(FARBNAMEN), "effekte": EFFEKT_ARTEN,
                "sequenzen": show.pult.sequenzen.namen(), "status": show.pult.status()}

    @app.post("/api/programmer/werte")
    def programmer_werte(auftrag: dict = Body(...)):
        geraete, werte = auftrag.get("geraete", []), auftrag.get("werte", {})
        if not geraete:
            raise ValueError("Zuerst Geräte auswählen.")
        fehler = pruefe_werte([{"geraet": g, **werte} for g in geraete], None,
                              [g["id"] for g in show.patch.geraete], show.positionen)
        if fehler:
            raise ValueError(" ".join(fehler))
        with show.sperre:
            show.pult.programmer.setzen(geraete, werte)
        return show.pult.status()

    @app.post("/api/programmer/effekt")
    def programmer_effekt(effekt: dict = Body(...)):
        fehler = pruefe_effekt(effekt, show.patch.gruppen(), [g["id"] for g in show.patch.geraete])
        if fehler:
            raise ValueError(" ".join(fehler))
        with show.sperre:
            show.pult.programmer.effekt_dazu(effekt)
        return show.pult.status()

    @app.delete("/api/programmer/effekt/{nummer}")
    def programmer_effekt_weg(nummer: int):
        with show.sperre:
            del show.pult.programmer.effekte[nummer]
        return show.pult.status()

    @app.post("/api/programmer/leeren")
    def programmer_leeren():
        with show.sperre:
            show.pult.programmer.leeren()
        return show.pult.status()

    @app.post("/api/programmer/blind")
    def programmer_blind(auftrag: dict = Body(...)):
        with show.sperre:
            show.pult.programmer.blind = bool(auftrag.get("an"))
        return show.pult.status()

    @app.post("/api/automatik")
    def automatik(auftrag: dict = Body(...)):
        with show.sperre:
            show.automatik_an = bool(auftrag.get("an"))
        show._sitzung_speichern()
        return {"automatik": show.automatik_an}

    @app.get("/api/sequenzen/{name}")
    def sequenz_lesen(name: str):
        sequenz = show.pult.sequenzen.lesen(name)
        if sequenz is None:
            raise ValueError(f"Sequenz {name!r} gibt es nicht.")
        return sequenz

    @app.post("/api/sequenzen")
    def sequenz_speichern(sequenz: dict = Body(...)):
        with show.sperre:
            show.pult.sequenz_speichern(sequenz)
        return {"name": sequenz["name"]}

    @app.delete("/api/sequenzen/{name}")
    def sequenz_loeschen(name: str):
        with show.sperre:
            for executor in show.pult.executoren:
                if executor.sequenz and executor.sequenz["name"] == name:
                    executor.belegen(None)
            show.pult.sequenzen.loeschen(name)
            show.pult.belegung_speichern()
        return {"sequenzen": show.pult.sequenzen.namen()}

    @app.post("/api/sequenzen/{name}/speichern")
    def cue_speichern(name: str, auftrag: dict = Body(...)):
        """Speichert den Programmer als Cue in die Sequenz."""
        with show.sperre:
            sequenz = show.pult.cue_speichern(name, auftrag.get("cue_name") or "Cue",
                                              float(auftrag.get("zeit_s", 2)), auftrag.get("folgen_s"),
                                              auftrag.get("nummer"))
        return sequenz

    @app.post("/api/sequenzen/{name}/cue/{nummer}/laden")
    def cue_laden(name: str, nummer: int):
        sequenz = show.pult.sequenzen.lesen(name)
        if sequenz is None or not 1 <= nummer <= len(sequenz["cues"]):
            raise ValueError("Diesen Cue gibt es nicht.")
        with show.sperre:
            show.pult.programmer.aus_cue(sequenz["cues"][nummer - 1], show.patch)
        return show.pult.status()

    @app.post("/api/executor/{nummer}/belegen")
    def executor_belegen(nummer: int, auftrag: dict = Body(...)):
        name = auftrag.get("sequenz")
        sequenz = show.pult.sequenzen.lesen(name) if name else None
        if name and sequenz is None:
            raise ValueError(f"Sequenz {name!r} gibt es nicht.")
        with show.sperre:
            show.pult.executor(nummer).belegen(sequenz)
            show.pult.belegung_speichern()
        return show.pult.status()

    @app.post("/api/executor/{nummer}/{aktion}")
    def executor_aktion(nummer: int, aktion: str, auftrag: dict = Body(default={})):
        jetzt = time.monotonic()
        with show.sperre:
            executor = show.pult.executor(nummer)
            if aktion == "go":
                show.pult.go(nummer, jetzt)
            elif aktion == "zurueck":
                show.pult.go(nummer, jetzt, -1)
            elif aktion == "aus":
                executor.aus(jetzt)
            elif aktion == "fader":
                executor.fader = max(0.0, min(1.0, float(auftrag["wert"])))
            else:
                raise ValueError(f"Unbekannte Aktion {aktion!r}.")
        return show.pult.status()

    @app.post("/api/go/{richtung}")
    def go_haupt(richtung: str):
        """Leertaste und Pfeiltasten: Go+ und Go- auf dem zuletzt benutzten Executor."""
        nummer = show.pult.haupt + 1
        with show.sperre:
            show.pult.go(nummer, time.monotonic(), 1 if richtung == "plus" else -1)
        return show.pult.status()

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

    # --- Update -------------------------------------------------------------

    @app.post("/api/update/installieren")
    def update_installieren():
        show.update.installieren()
        return {"zustand": "installiert"}

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
