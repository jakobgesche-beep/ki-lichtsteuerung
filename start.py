#!/usr/bin/env python3
"""Startet das Programm:  python start.py

Mit --netz ist die Oberfläche auch vom Tablet aus erreichbar.
"""
import argparse

import uvicorn

from lichtsteuerung.server import erstelle_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Lichtsteuerung der Technik-AG")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--netz", action="store_true",
                        help="auch für andere Geräte im Netz erreichbar machen (Tablet)")
    args = parser.parse_args()
    host = "0.0.0.0" if args.netz else "127.0.0.1"
    print(f"Lichtsteuerung läuft: http://localhost:{args.port}  (Beenden mit Strg+C)")
    uvicorn.run(erstelle_app(), host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
