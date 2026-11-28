"""Startet die Lichtsteuerung mit frischen Beispieldaten in einem Wegwerf-Ordner – für Browser-Tests.

DMX bleibt aus, kein Ton-Eingang, nur 127.0.0.1. Die echten Show-Daten werden nie angefasst.
    .venv/bin/python -m werkzeuge.testserver --port 8399 --ordner /tmp/licht-test [--netz-port 8798]
Mit --netz-port startet auch der Netz-Server (iPad-Pult, Handy) auf 127.0.0.1.
"""
from __future__ import annotations

import argparse
import tempfile
import threading
from pathlib import Path

import uvicorn

from lichtsteuerung import daten
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


def main() -> None:
    teile = argparse.ArgumentParser()
    teile.add_argument("--port", type=int, default=8399)
    teile.add_argument("--ordner", default="")
    teile.add_argument("--netz-port", type=int, default=0)
    a = teile.parse_args()
    ordner = Path(a.ordner) if a.ordner else Path(tempfile.mkdtemp(prefix="licht-test-"))
    if not (ordner / "fixtures.json").exists():
        daten.einrichten(ordner)
    show = Show(daten.Pfade(ordner, daten.PROJEKT / "catalog"))
    app = erstelle_app(show)
    if a.netz_port:
        netz = getattr(show, "fernbedienung", None)
        def netz_an():
            netz.einschalten(host="127.0.0.1", port=a.netz_port)
        app.router.add_event_handler("startup", lambda: threading.Timer(0.3, netz_an).start())
    print(f"Testserver: http://127.0.0.1:{a.port}/  Daten: {ordner}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
