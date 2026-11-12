"""Der Webserver: Die Oberfläche im Browser spricht nur über diese Datei mit der Show.

Alle Adressen beginnen mit /api. Was geändert wird, läuft durch dieselben
Prüfungen wie alles andere. Es gibt hier keinen Weg an der Prüfung vorbei.
"""
from __future__ import annotations

import asyncio
import threading
import time
import webbrowser
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .audio import quellen
from .daten import PROJEKT
from .dmx_ausgabe import EnttecFehler
from .farben import FARBNAMEN
from .importe import gdtf, qxf
from .importe.gemeinsam import speichere_import
from .katalog import KatalogFehler
from . import konzertcheck, showtasten, patchplan, sicherung
from .befehle import Befehlszeile
from .patch import FUNKTIONS_GRUPPEN, PatchFehler
from .profile import pruefe_profil
from .pult import EFFEKT_ARTEN, SONG_NUMMER, pruefe_effekt
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
    return show.faehigkeiten(geraet)


def erstelle_app(show: Optional[Show] = None) -> FastAPI:
    show = show or Show()
    befehlszeile = Befehlszeile(show)
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

    @app.get("/api/strobos")
    def strobos():
        """Alle gepatchten Geräte mit Strobo-Kanal, und ob ihr Tempo bekannt ist."""
        ergebnis = []
        for geraet in show.patch.geraete:
            art = show.strobo_art(geraet)
            if art:
                typ = show.patch.typ(geraet)
                ergebnis.append({"id": geraet["id"], "name": geraet["name"], "adresse": geraet["adresse"],
                                 "eingemessen": art == "eingemessen", "art": art,
                                 "rein": "Strobo" in show.patch.gruppen_von(geraet) or art == "software",
                                 "zuruecknehmbar": bool(typ.daten.get("basis") or typ.id.endswith("-eingemessen")),
                                 "hinweis": typ.daten.get("_hinweis", "")})
        # Echte Strobos zuerst: Sonst ist ein Scheinwerfer mit Shutter-Strobo vorausgewählt.
        ergebnis.sort(key=lambda g: not g["rein"])
        return {"strobos": ergebnis}

    @app.post("/api/strobos/{geraet_id}/zuruecksetzen")
    def strobo_zuruecksetzen(geraet_id: str):
        return show.strobo_zuruecksetzen(geraet_id)

    @app.post("/api/strobos/{geraet_id}/blitzen")
    def strobo_blitzen(geraet_id: str, auftrag: dict = Body(...)):
        if auftrag.get("bestaetigt") is not True:
            raise ValueError("Bitte zuerst bestätigen: Lehrkraft dabei, niemand im Raum reagiert empfindlich auf Blitzlicht.")
        show.strobo_einmessen(geraet_id, int(auftrag["wert"]))
        return {"sekunden": 3}

    @app.post("/api/strobos/{geraet_id}/auswerten")
    def strobo_auswerten(geraet_id: str, auftrag: dict = Body(...)):
        return show.strobo_auswerten(geraet_id, auftrag["messungen"])

    @app.get("/api/dmx")
    def dmx_status():
        return {**show.ausgabe.status(), "enttec_gefunden": show.ausgabe.enttec_gefunden(),
                "bild": list(show.letztes_bild)}

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

    @app.post("/api/auswahl")
    def auswahl(auftrag: dict = Body(...)):
        geraete = list(auftrag.get("geraete", []))
        if "gruppe" in auftrag:
            geraete = [g["id"] for g in show.patch.in_gruppe(auftrag["gruppe"])]
        with show.sperre:
            show.pult.waehlen(geraete, auftrag.get("art", "setzen"))
        return show.pult.status()

    @app.post("/api/befehl")
    def befehl(auftrag: dict = Body(...)):
        if auftrag.get("sequenz"):
            befehlszeile.sequenz = auftrag["sequenz"]
        try:
            return {"antwort": befehlszeile.ausfuehren(str(auftrag.get("text", ""))), "status": show.pult.status()}
        except (ValueError, KatalogFehler, PatchFehler) as fehler:
            return JSONResponse({"fehler": str(fehler)}, status_code=400)

    @app.post("/api/programmer/werte")
    def programmer_werte(auftrag: dict = Body(...)):
        geraete, werte = auftrag.get("geraete") or list(show.pult.auswahl), auftrag.get("werte", {})
        if not geraete:
            raise ValueError("Zuerst Geräte auswählen.")
        fehler = pruefe_werte([{"geraet": g, **werte} for g in geraete], None,
                              [g["id"] for g in show.patch.geraete], show.positionen)
        if fehler:
            raise ValueError(" ".join(fehler))
        with show.sperre:
            show.pult.merke_programmer()
            show.pult.programmer.setzen(geraete, werte)
        return show.pult.status()

    @app.post("/api/programmer/effekt")
    def programmer_effekt(effekt: dict = Body(...)):
        if not effekt.get("ziel"):
            effekt["ziel"] = {"geraete": list(show.pult.auswahl)}
        fehler = pruefe_effekt(effekt, show.patch.gruppen(), [g["id"] for g in show.patch.geraete])
        if fehler:
            raise ValueError(" ".join(fehler))
        with show.sperre:
            show.pult.merke_programmer()
            show.pult.programmer.effekt_dazu(effekt)
        return show.pult.status()

    @app.delete("/api/programmer/effekt/{nummer}")
    def programmer_effekt_weg(nummer: int):
        with show.sperre:
            show.pult.merke_programmer()
            del show.pult.programmer.effekte[nummer]
        return show.pult.status()

    @app.post("/api/programmer/leeren")
    def programmer_leeren():
        with show.sperre:
            if not show.pult.programmer.ist_leer():
                show.pult.merke_programmer()
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

    # --- Licht-Chat: Vorschlag nur in der Vorschau, gespeichert erst bei Übernehmen ---------

    @app.get("/api/chat")
    def chat_lesen():
        return show.chat.status()

    @app.post("/api/chat")
    def chat_senden(auftrag: dict = Body(...)):
        """Dauert mit Claude ein paar Sekunden. Die Show läuft in der Zeit ganz normal weiter."""
        return show.chat.senden(str(auftrag.get("text", "")))

    @app.post("/api/chat/neu")
    def chat_neu():
        show.chat.neu()
        return show.chat.status()

    @app.post("/api/chat/vorschau")
    def chat_vorschau(auftrag: dict = Body(...)):
        show.chat.vorschau_cue(int(auftrag.get("cue", 0)))
        return show.chat.status()

    @app.post("/api/chat/uebernehmen")
    def chat_uebernehmen(auftrag: dict = Body(default={})):
        fader = auftrag.get("fader")
        ergebnis = show.chat.uebernehmen(int(fader) if fader else None, auftrag.get("name") or None)
        return {**show.chat.status(), "ergebnis": ergebnis, "pult": show.pult.status()}

    @app.post("/api/chat/verwerfen")
    def chat_verwerfen():
        show.chat.verwerfen()
        return show.chat.status()

    @app.post("/api/ki/schluessel")
    def ki_schluessel(auftrag: dict = Body(...)):
        """Der Schlüssel wird nur gespeichert, nie zurückgegeben (die Oberfläche sieht nur den Anfang)."""
        show.chat.schluessel.speichern(str(auftrag.get("schluessel", "")))
        return show.chat.status()

    @app.delete("/api/ki/schluessel")
    def ki_schluessel_weg():
        show.chat.schluessel.loeschen()
        return show.chat.status()

    @app.get("/api/sequenzen")
    def sequenzen_pool():
        """Der Sequenzen-Pool: Name, Anzahl Cues und auf welchen Fadern sie liegt."""
        pool = []
        for name in show.pult.sequenzen.namen():
            sequenz = show.pult.sequenzen.lesen(name) or {"cues": []}
            pool.append({"name": name, "cues": len(sequenz.get("cues", [])), "song": bool(sequenz.get("zeitcode")),
                         "fader": [e.nummer for e in show.pult.executoren
                                   if e.sequenz and e.sequenz["name"] == name]})
        return {"sequenzen": pool}

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
            show.pult.sequenz_loeschen(name)
        return {"sequenzen": show.pult.sequenzen.namen()}

    @app.post("/api/sequenzen/{name}/speichern")
    def cue_speichern(name: str, auftrag: dict = Body(...)):
        """Speichert den Programmer als Cue in die Sequenz."""
        with show.sperre:
            sequenz = show.pult.cue_speichern(name, auftrag.get("cue_name") or "Cue",
                                              float(auftrag.get("zeit_s", 2)), auftrag.get("folgen_s"),
                                              auftrag.get("nummer"))
        return sequenz

    @app.post("/api/sequenzen/{name}/cue/{nummer}/aendern")
    def cue_aendern(name: str, nummer: int, felder: dict = Body(...)):
        with show.sperre:
            return show.pult.cue_aendern(name, nummer, felder)

    @app.post("/api/sequenzen/{name}/cue/{nummer}/verschieben")
    def cue_verschieben(name: str, nummer: int, auftrag: dict = Body(...)):
        with show.sperre:
            return show.pult.cue_verschieben(name, nummer, int(auftrag.get("richtung", 1)))

    @app.delete("/api/sequenzen/{name}/cue/{nummer}")
    def cue_loeschen(name: str, nummer: int):
        with show.sperre:
            return show.pult.cue_loeschen(name, nummer)

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
        """Assign: {"sequenz": Name}, {"gruppe": Name}, {"art": "tempo"} oder {} für frei."""
        with show.sperre:
            if auftrag.get("sequenz"):
                show.pult.zuweisen(nummer, "sequenz", auftrag["sequenz"])
            elif auftrag.get("gruppe"):
                show.pult.zuweisen(nummer, "gruppe", auftrag["gruppe"])
            elif auftrag.get("art") == "tempo":
                show.pult.zuweisen(nummer, "tempo")
            else:
                show.pult.zuweisen(nummer, None)
        return show.pult.status()

    @app.post("/api/executor/{nummer}/label")
    def executor_label(nummer: int, auftrag: dict = Body(...)):
        with show.sperre:
            show.pult.label_setzen(nummer, str(auftrag.get("label", "")))
        return show.pult.status()

    @app.post("/api/executor/{nummer}/speichern")
    def executor_speichern(nummer: int, auftrag: dict = Body(default={})):
        """Store auf einen Fader: Programmer als neuer Cue (leerer Fader: neue Sequenz)."""
        with show.sperre:
            sequenz = show.pult.speichern_auf(nummer, auftrag.get("cue_name") or None, float(auftrag.get("zeit_s", 2)))
        return {"sequenz": sequenz["name"], "cues": len(sequenz["cues"]), "status": show.pult.status()}

    @app.post("/api/executor/{nummer}/update")
    def executor_update(nummer: int):
        with show.sperre:
            sequenz = show.pult.aktualisieren(nummer)
        return {"sequenz": sequenz["name"], "status": show.pult.status()}

    @app.post("/api/executor/{nummer}/{aktion}")
    def executor_aktion(nummer: int, aktion: str, auftrag: dict = Body(default={})):
        jetzt = time.monotonic()
        with show.sperre:
            executor = show.pult.executor(nummer)
            if aktion in ("go", "zurueck", "aus") and executor.zeitcode is True:
                executor.zeitcode = False         # Probe ansehen endet, Song-Start bleibt
            if aktion == "go":
                show.pult.go(nummer, jetzt)
            elif aktion == "zurueck":
                show.pult.go(nummer, jetzt, -1)
            elif aktion == "aus":
                if show.song.laeuft_auf(nummer):
                    show.song.stoppen(jetzt)
                show.pult.aus(nummer, jetzt)
            elif aktion == "goto":
                show.pult.goto(nummer, int(auftrag["index"]), jetzt)
            elif aktion == "fader":
                show.pult.fader_setzen(nummer, float(auftrag["wert"]), jetzt)
            elif aktion == "flash":
                show.pult.flash(nummer, bool(auftrag.get("an", True)), jetzt)
            else:
                raise ValueError(f"Unbekannte Aktion {aktion!r}.")
        return show.pult.status()

    @app.post("/api/grand")
    def grand_master(auftrag: dict = Body(...)):
        with show.sperre:
            show.pult.grand_setzen(float(auftrag["wert"]), time.monotonic())
        return show.pult.status()

    @app.post("/api/pult/seite")
    def fader_seite(auftrag: dict = Body(...)):
        with show.sperre:
            show.pult.seite_setzen(int(auftrag["seite"]))
        return show.pult.status()

    @app.post("/api/oops")
    def oops():
        with show.sperre:
            text = show.pult.rueckgaengig()
        return {"antwort": text, "status": show.pult.status()}

    @app.post("/api/highlight")
    def highlight(auftrag: dict = Body(default={})):
        with show.sperre:
            show.pult.highlight = bool(auftrag.get("an", not show.pult.highlight))
        return show.pult.status()

    @app.post("/api/go/{richtung}")
    def go_haupt(richtung: str):
        """Leertaste und Pfeiltasten: Go+ und Go- auf dem zuletzt benutzten Executor."""
        nummer = show.pult.haupt + 1
        with show.sperre:
            show.pult.go(nummer, time.monotonic(), 1 if richtung == "plus" else -1)
        return show.pult.status()

    # --- Probe: aufnehmen, analysieren, Show bauen --------------------------

    @app.get("/api/proben")
    def proben_lesen():
        return {"proben": [show.proben.lesen(n) for n in show.proben.namen()],
                "aufnahme": show.aufnahme_name}

    @app.post("/api/proben/aufnahme")
    def probe_aufnehmen(auftrag: dict = Body(...)):
        name = str(auftrag.get("name", "")).strip()
        if not name:
            raise ValueError("Bitte einen Namen für den Song eingeben.")
        show.audio.aufnahme_starten()
        show.aufnahme_name = name
        show.aufnahme_marken = []
        return {"aufnahme": name}

    @app.post("/api/proben/markieren")
    def probe_markieren():
        """Taste D: Hier war der Drop. Nur während einer Aufnahme."""
        if not show.aufnahme_name:
            raise ValueError("Zum Markieren erst in der Probe eine Aufnahme starten.")
        show.aufnahme_marken.append(sum(len(b) for b in show.audio.aufnahme or []) / 44100)
        return {"markierungen": len(show.aufnahme_marken)}

    @app.post("/api/proben/stopp")
    def probe_stoppen():
        name, show.aufnahme_name = show.aufnahme_name, None
        ton = show.audio.aufnahme_beenden()
        if not name:
            raise ValueError("Es läuft keine Aufnahme.")
        marken, show.aufnahme_marken = show.aufnahme_marken, []
        show.proben.speichern(name, ton, marken)
        return {"analyse": show.proben.lesen(name), "sequenz": show.show_aus_probe(name)}

    @app.post("/api/proben/datei")
    async def probe_aus_datei(anfrage: Request, name: str, datei: str):
        """Einen Song als Datei analysieren, zum Beispiel das Original zum Vorbereiten."""
        if Path(datei).suffix.lower() not in AUDIO_ENDUNGEN:
            raise ValueError("Diese Dateiart kann das Programm nicht lesen.")
        show.pfade.audio.mkdir(parents=True, exist_ok=True)
        pfad = show.pfade.audio / Path(datei).name
        pfad.write_bytes(await anfrage.body())
        try:
            show.proben.aus_datei(name, pfad)
        except quellen.AudioFehler as fehler:
            raise ValueError(str(fehler)) from fehler
        return {"analyse": show.proben.lesen(name), "sequenz": show.show_aus_probe(name)}

    @app.post("/api/proben/{name}/teile")
    def probe_teile(name: str, auftrag: dict = Body(...)):
        """Songteile von Hand richtigstellen (Name, Stärke, Grenzen). Danach "Show neu bauen"."""
        return show.proben.teile_aendern(name, str(auftrag.get("aktion", "")), int(auftrag.get("index", 0)),
                                         auftrag.get("wert"))

    @app.post("/api/proben/{name}/neu")
    def probe_neu_bauen(name: str):
        return show.show_aus_probe(name)

    @app.post("/api/proben/{name}/abspielen")
    def probe_abspielen(name: str, auftrag: dict = Body(default={})):
        """Spielt die Aufnahme ab, das Licht folgt genau den erkannten Stellen."""
        nummer = int(auftrag.get("executor", SONG_NUMMER))     # eigener Platz: die Fader bleiben, wie sie sind
        show.song.stoppen()
        sequenz = show.pult.sequenzen.lesen(name)
        if sequenz is None:
            raise ValueError("Zu dieser Probe gibt es noch keine Sequenz.")
        try:
            show.audio.starten(quellen.Datei(show.proben.ton_pfad(name), float(auftrag.get("ab_s", 0) or 0)),
                               f"Probe: {name}")
        except quellen.AudioFehler as fehler:
            raise ValueError(str(fehler)) from fehler
        with show.sperre:
            executor = show.pult.executor(nummer)
            executor.belegen(sequenz)
            executor.zeitcode = True
            show.pult.go(nummer, time.monotonic())
            if executor is not show.pult.song_platz:
                show.pult.belegung_speichern()
        return show.pult.status()

    @app.post("/api/proben/ansehen/stopp")
    def probe_ansehen_stopp():
        """Probe ansehen beenden: Licht aus dem Song-Platz nehmen, die eigentliche Tonquelle wieder öffnen."""
        jetzt = time.monotonic()
        with show.sperre:
            platz = show.pult.song_platz
            if platz.zeitcode is True:
                platz.zeitcode = False
                platz.aus(jetzt)
        show.audio_quelle_setzen(show.audio_auftrag or {"art": "aus"}, merken=False)
        return show.pult.status()

    @app.delete("/api/proben/{name}")
    def probe_loeschen(name: str):
        show.proben.loeschen(name)
        return {"proben": show.proben.namen()}

    # --- Show: Song-Start und Show-Tasten ------------------------------------

    @app.get("/api/check")
    def konzert_check():
        """Konzert-Check: was bereit ist und was noch fehlt."""
        with show.sperre:
            return {"punkte": konzertcheck.pruefen(show)}

    @app.get("/api/show")
    def show_lesen():
        return {"songs": show.song.songs(), "looks": showtasten.LOOKS, "halten": showtasten.HALTEN,
                "farben": showtasten.FARBEN}

    @app.post("/api/song/start")
    def song_start(auftrag: dict = Body(...)):
        """Einmal drücken, wenn die Band anfängt: Der ganze Song läuft von selbst durch."""
        show.song.starten(str(auftrag.get("name", "")), int(auftrag.get("executor", SONG_NUMMER)))
        return show.song.zustand()

    @app.post("/api/setlist")
    def setlist(auftrag: dict = Body(...)):
        """Reihenfolge der Songs fürs Konzert und wie die Song-Erkennung arbeitet."""
        show.song.setlist_setzen(auftrag.get("reihenfolge"), auftrag.get("modus"))
        return show.song.erkennung_zustand()

    @app.post("/api/song/vorschlag")
    def song_vorschlag():
        """Knopf "Klingt nach …, starten"."""
        show.song.vorschlag_starten()
        return show.song.zustand()

    @app.post("/api/song/teil")
    def song_teil(auftrag: dict = Body(...)):
        """Klick auf einen Teil in der Zeitleiste: Der Song läuft ab dort weiter."""
        show.song.zu_teil(int(auftrag.get("index", 0)))
        return show.song.zustand()

    @app.post("/api/song/{aktion}")
    def song_aktion(aktion: str):
        if aktion == "stopp":
            show.song.stoppen()
        elif aktion == "vor":
            show.song.teil_vor()
        elif aktion == "zurueck":
            show.song.teil_zurueck()
        elif aktion == "los":
            show.song.jetzt_los()
        else:
            raise ValueError(f"Unbekannte Aktion {aktion!r}.")
        return show.song.zustand()

    @app.post("/api/look/{look_id}")
    def look(look_id: str):
        with show.sperre:
            if look_id == "aus":
                show.pult.look_aus(time.monotonic())
            else:
                show.pult.look_druecken(look_id, time.monotonic())
        return show.pult.status()

    @app.post("/api/farben")
    def farben(auftrag: dict = Body(...)):
        with show.sperre:
            show.pult.farben_setzen(auftrag.get("farbe_1"), auftrag.get("farbe_2"), time.monotonic())
        return show.pult.status()

    @app.post("/api/halten/{art}")
    def halten(art: str, auftrag: dict = Body(default={})):
        with show.sperre:
            show.pult.halten_setzen(art, bool(auftrag.get("an", True)), time.monotonic())
        return show.pult.status()

    @app.post("/api/tap")
    def tap():
        with show.sperre:
            tempo = show.pult.tap(time.monotonic())
        return {"tempo": tempo}

    @app.post("/api/tempo/quelle")
    def tempo_quelle(auftrag: dict = Body(...)):
        quelle = auftrag.get("quelle")
        if quelle not in ("ton", "tap"):
            raise ValueError('Tempo-Quelle ist "ton" oder "tap".')
        if quelle == "tap" and not show.pult.tempo_getippt:
            raise ValueError("Erst ein paar Mal auf Tap tippen.")
        show.pult.tempo_quelle = quelle
        return show.pult.status()

    # --- Audio -------------------------------------------------------------

    @app.get("/api/audio")
    def audio_lesen():
        ordner = show.pfade.audio
        dateien = sorted(p.name for p in ordner.glob("*") if p.suffix.lower() in AUDIO_ENDUNGEN)
        return {"eingaenge": quellen.eingaenge(), "dateien": dateien}

    @app.post("/api/audio/quelle")
    def audio_quelle(auftrag: dict = Body(...)):
        """Tonquelle wählen. Sie wird gemerkt und nach einem Neustart von selbst wieder geöffnet."""
        return {"quelle": show.audio_quelle_setzen(auftrag)}

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

    @app.post("/api/update/suchen")
    def update_suchen():
        show.update.jetzt_suchen()
        return show.update.status()

    @app.post("/api/update/installieren")
    def update_installieren():
        show.update.installieren()
        return {"zustand": "installiert"}

    # --- Patchplan zum Ausdrucken ------------------------------------------

    # --- Sicherung: Show als eine Datei, zum Beispiel vom MacBook zum Windows-Laptop -------

    @app.post("/api/sicherung/export")
    def sicherung_export(auftrag: dict = Body(default={})):
        stempel = time.strftime("%Y-%m-%d_%H-%M")
        name = f"Lichtsteuerung-Show-{stempel}.zip"
        mit_proben = bool(auftrag.get("mit_proben", True))
        try:
            pfad = sicherung.exportieren(show.pfade.wurzel, sicherung.downloads_ordner() / name, mit_proben)
        except PermissionError:
            # Der Mac kann den Zugriff auf "Downloads" verweigern: dann in den Ordner der Sicherungen
            pfad = sicherung.exportieren(show.pfade.wurzel, show.pfade.wurzel / sicherung.SICHERUNGEN / name, mit_proben)
        return {"pfad": str(pfad), "groesse_mb": round(pfad.stat().st_size / 1024 ** 2, 1)}

    @app.post("/api/sicherung/zeigen")
    def sicherung_zeigen(auftrag: dict = Body(...)):
        """Die gesicherte Datei im Finder oder Explorer zeigen (nur Dateien, die wir selbst geschrieben haben)."""
        pfad = Path(str(auftrag.get("pfad", "")))
        erlaubt = {sicherung.downloads_ordner(), show.pfade.wurzel / sicherung.SICHERUNGEN}
        if pfad.parent not in erlaubt or not pfad.name.startswith("Lichtsteuerung-Show-") or not pfad.is_file():
            raise ValueError("Diese Datei kann ich nicht zeigen.")
        import subprocess
        import sys as _sys
        if _sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(pfad)])
        elif _sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(pfad)])
        return {}

    @app.post("/api/sicherung/import")
    async def sicherung_import(anfrage: Request):
        """Show-Datei hochladen. Übernommen wird sie beim nächsten Start (vorher wird gesichert)."""
        zwischen = show.pfade.wurzel / "daten" / "show_hochgeladen.zip"
        zwischen.parent.mkdir(parents=True, exist_ok=True)
        groesse = 0
        try:
            with open(zwischen, "wb") as datei:
                async for stueck in anfrage.stream():
                    groesse += len(stueck)
                    if groesse > sicherung.MAX_GROESSE:
                        raise ValueError("Die Datei ist zu groß.")
                    datei.write(stueck)
            uebersicht = sicherung.vormerken(show.pfade.wurzel, zwischen)
        finally:
            zwischen.unlink(missing_ok=True)
        return {**uebersicht, "text": "Die Show wird beim nächsten Start geladen. Jetzt das Programm schließen und neu öffnen."}

    @app.get("/api/sicherung")
    def sicherung_status():
        ordner = show.pfade.wurzel / sicherung.SICHERUNGEN
        return {"vorgemerkt": sicherung.vorgemerkt(show.pfade.wurzel), "ordner": str(ordner),
                "sicherungen": sorted((p.name for p in ordner.glob("*.zip")), reverse=True)[:12] if ordner.is_dir() else []}

    @app.post("/api/beenden")
    def programm_beenden():
        """Programm schließen (zum Beispiel, damit eine geladene Show übernommen wird). Die Lichter gehen aus."""
        if show.update.beenden is None:
            raise ValueError("Beenden geht nur im laufenden Programm.")
        threading.Timer(0.5, show.update.beenden).start()
        return {}

    @app.get("/patchplan")
    def patchplan_seite():
        return HTMLResponse(patchplan.seite(show))

    @app.post("/api/patchplan/oeffnen")
    def patchplan_oeffnen(anfrage: Request):
        """Öffnet den Patchplan im normalen Browser. Dort kann man ihn drucken."""
        webbrowser.open(f"http://{anfrage.headers.get('host')}/patchplan")
        return {}

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
