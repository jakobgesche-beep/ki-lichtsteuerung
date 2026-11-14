"""Konzert-Check: Ist alles bereit? Grün = gut, Gelb = besser ansehen, Rot = so geht es nicht.

Läuft auf der Show-Seite mit. Er schaltet nie etwas selbst, er sagt nur, was fehlt (und bietet
für einfache Dinge einen Knopf an, zum Beispiel DMX einschalten).
"""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from . import generalprobe, sicherung, wachhalten
from .dmx_ausgabe import kein_enttec_text


def pruefen(show) -> list:
    punkte = []

    def punkt(thema: str, stufe: str, text: str, aktion: str = None) -> None:
        punkte.append({"thema": thema, "stufe": stufe, "text": text, "aktion": aktion})

    # Licht raus: Enttec und DMX
    dmx = show.ausgabe.status()
    if dmx["eingeschaltet"] and dmx["verbunden"]:
        punkt("DMX", "ok", f"DMX ist an und sendet ({dmx['weg']}).")
    elif dmx["eingeschaltet"]:
        punkt("DMX", "problem", "DMX ist an, aber das Enttec antwortet nicht. USB-Kabel prüfen, es verbindet sich von selbst neu.")
    elif show.ausgabe.enttec_gefunden():
        punkt("DMX", "hinweis", "Enttec gefunden, DMX ist noch aus.", "dmx_ein")
    else:
        punkt("DMX", "problem", kein_enttec_text())

    # Ton rein
    werte = show.audio.aktuell()
    if show.audio.name == "aus":
        punkt("Ton", "problem", "Kein Ton-Eingang gewählt. Seite Live → Quelle: Eingang vom X32 (oder Mikrofon).")
    elif werte is None:
        punkt("Ton", "problem", show.audio.fehler or f"Von „{show.audio.name}“ kommt nichts an. Kabel und Card Out am X32 prüfen.")
    elif show.audio.name.startswith("Eingang"):
        punkt("Ton", "ok", f"Ton kommt an ({show.audio.name}).")
    else:
        punkt("Ton", "hinweis", f"Der Ton kommt aus „{show.audio.name}“, nicht aus einem Eingang. Für das Konzert den X32-Eingang wählen.")

    # Songs
    songs = show.song.songs()
    if not songs:
        punkt("Songs", "hinweis", "Noch keine Songs mit Probe-Aufnahme. Ohne geht nur Licht von Hand (Show-Tasten, Pult).")
    for song in songs:
        analyse = show.proben.lesen(song["name"]) or {}
        if song.get("alte_analyse"):
            punkt("Songs", "hinweis", f"„{song['name']}“: alte Erkennung. In der Probe „Show neu bauen“ drücken.")
        elif not analyse.get("von_hand"):
            punkt("Songs", "hinweis", f"„{song['name']}“: Teile noch nicht von Hand geprüft (Probe → Teile richtigstellen).")
        else:
            punkt("Songs", "ok", f"„{song['name']}“: bereit, {len(song['teile'])} Teile, von Hand geprüft.")

    # Generalprobe: Wo war das Programm unsicher?
    gp = generalprobe.check_punkt(show.generalprobe)
    if gp:
        punkt("Generalprobe", *gp)

    # Fernbedienung (Handy)
    fern = show.fernbedienung
    if fern.an:
        if time.monotonic() < fern.gesperrt_bis:
            punkt("Handy", "problem", "Jemand hat viele falsche PINs probiert. Die Fernbedienung nimmt 5 Minuten keine PIN an. "
                                      "Lieber ausschalten und eine neue PIN nehmen.")
        else:
            handys = fern.handys_aktiv()
            punkt("Handy", "ok", f"Fernbedienung ist an ({handys} Handy{'s' if handys != 1 else ''} verbunden).")

    # Profil und Strobo
    punkt("Profil", "ok", f"Profil: {show.profil['name']}.")
    if show.profil.get("strobo") not in (None, "aus"):
        punkt("Profil", "hinweis", "Dieses Profil erlaubt Strobo: Hinweisschild am Eingang aufhängen.")

    # Pult
    if show.overrides.blackout:
        punkt("Pult", "problem", "Blackout ist an (Taste B).")
    if show.overrides.warmweiss:
        punkt("Pult", "hinweis", "Warmweiß ist an (Taste W).")
    if show.overrides.pause:
        punkt("Pult", "hinweis", "Die Automatik ist pausiert (Taste P).")
    if show.pult.grand < 0.999:
        punkt("Pult", "hinweis", f"Grand Master steht auf {round(show.pult.grand * 100)} %.")
    if not show.pult.programmer.ist_leer():
        punkt("Pult", "hinweis", "Im Programmer stehen noch Werte. Sie liegen über allem (Pult → Clear, zweimal).")
    if show._test_laeuft():
        punkt("Pult", "problem", "Der DMX-Test läuft noch (Setup → DMX-Test beenden).")

    # Rechner
    if wachhalten.aktiv:
        punkt("Rechner", "ok", "Der Laptop schläft nicht ein, solange das Programm läuft. Netzteil anstecken, Deckel offen lassen.")
    else:
        punkt("Rechner", "hinweis", "Ruhezustand und Bildschirmschoner selbst ausschalten, Netzteil anstecken.")
    ordner = Path(show.pfade.wurzel) / sicherung.SICHERUNGEN
    heute = f"{datetime.date.today():%Y-%m-%d}"
    if ordner.is_dir() and any(heute in p.name for p in ordner.glob("*.zip")):
        punkt("Rechner", "ok", "Heute gibt es schon eine Sicherung der Show.")
    else:
        punkt("Rechner", "hinweis", "Heute noch keine Sicherung. Setup → Sicherung → Show sichern (auf einen USB-Stick).")
    return punkte
