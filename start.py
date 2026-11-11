#!/usr/bin/env python3
"""Startet das Programm:  python start.py

Mit --netz ist die Oberfläche auch vom Tablet aus erreichbar. In der fertigen
App (Mac und Windows) öffnet sich statt des Browsers ein eigenes Fenster.
"""
import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from lichtsteuerung import daten
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


def freier_port(wunsch: int) -> int:
    for port in (wunsch, 0):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return probe.getsockname()[1]
            except OSError:
                continue
    raise OSError("Kein freier Port gefunden.")


def starte_server(show: Show, host: str, port: int) -> uvicorn.Server:
    konfiguration = uvicorn.Config(erstelle_app(show), host=host, port=port,
                                   log_level="warning", log_config=None)
    server = uvicorn.Server(konfiguration)
    threading.Thread(target=server.run, name="Server", daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


def beenden(show: Show, server: uvicorn.Server) -> None:
    server.should_exit = True
    time.sleep(0.3)
    show.stopp()
    os._exit(0)


def selbsttest(adresse: str) -> None:
    """Für die automatische Prüfung der gebauten App."""
    with urllib.request.urlopen(adresse + "/api/patch", timeout=10) as antwort:
        patch = json.load(antwort)
    with urllib.request.urlopen(adresse + "/api/katalog", timeout=10) as antwort:
        katalog = json.load(antwort)
    with urllib.request.urlopen(adresse + "/vendor/three.module.min.js", timeout=10) as antwort:
        assert antwort.status == 200
    assert len(patch["geraete"]) == 10 and katalog["gesamt"] > 600
    import sounddevice, soundfile  # noqa: E401,F401  Audio muss sich laden lassen
    import webview  # noqa: F401  das eigene Fenster muss sich laden lassen
    if sys.platform == "win32":
        import clr  # noqa: F401  unter Windows braucht das Fenster pythonnet
    from lichtsteuerung.dmx_ausgabe import EnttecOpenDmx
    EnttecOpenDmx.suchen()
    import anthropic  # noqa: F401  der Licht-Chat muss sich laden lassen (auch ohne Schlüssel)
    from lichtsteuerung.licht_chat import werkzeuge
    assert len(werkzeuge()) == 2
    print("Selbsttest bestanden")


def app_fenster(adresse: str, show: Show, server: uvicorn.Server) -> None:
    """Eigenes Fenster. Klappt das nicht, tut es auch der Browser."""
    try:
        import webview
        webview.create_window("Lichtsteuerung", adresse, width=1400, height=900)
        webview.start()
    except Exception:
        logging.exception("Fenster ließ sich nicht öffnen, nehme den Browser")
        webbrowser.open(adresse)
        threading.Event().wait()
    beenden(show, server)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lichtsteuerung der Technik-AG")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--netz", action="store_true",
                        help="auch für andere Geräte im Netz erreichbar machen (Tablet)")
    parser.add_argument("--kein-browser", action="store_true", help="den Browser nicht selbst öffnen")
    parser.add_argument("--selbsttest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if daten.ALS_APP:
        pfade = daten.standard_pfade()
        logging.basicConfig(filename=pfade.wurzel / "logbuch.txt", level=logging.INFO, encoding="utf-8")
    show = Show()
    port = freier_port(args.port)
    adresse = f"http://localhost:{port}"
    server = starte_server(show, "0.0.0.0" if args.netz else "127.0.0.1", port)
    show.update.beenden = lambda: beenden(show, server)

    if args.selbsttest:
        # Fehler ergeben einen Exit-Code statt eines Fensters: Die Prüfung läuft ohne Bildschirm.
        try:
            selbsttest(adresse)
            code = 0
            if daten.ALS_APP:
                # Für die Prüfung im Bau: Ein Fenster-Programm hat keine Konsole für "bestanden".
                (daten.datenordner() / "selbsttest.txt").write_text("bestanden", encoding="utf-8")
        except BaseException:
            logging.exception("Selbsttest fehlgeschlagen")
            code = 1
        show.stopp()
        os._exit(code)
    show.update.im_hintergrund_pruefen()
    if daten.ALS_APP:
        app_fenster(adresse, show, server)
        return
    print(f"Lichtsteuerung läuft: {adresse}  (Beenden mit Strg+C)")
    if not args.kein_browser:
        webbrowser.open(adresse)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        beenden(show, server)


if __name__ == "__main__":
    sys.exit(main())
