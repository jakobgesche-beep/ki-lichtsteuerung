"""DMX-Test für die Kommandozeile. Setzt einzelne Kanäle oder prüft jedes Gerät.

Beispiele:
    python -m lichtsteuerung.werkzeuge.dmx_test --kanal 1 --wert 255 --sekunden 5
    python -m lichtsteuerung.werkzeuge.dmx_test --geraete

Ohne --senden bleibt es beim Simulator: Es wird nur angezeigt, was gesendet
würde. Auch hier läuft jeder Wert durch die Prüfung.
"""
from __future__ import annotations

import argparse
import time

from ..dmx_ausgabe import EnttecFehler
from ..show import Show


def zeige(show: Show, von: int, bis: int) -> None:
    bild = show.baue_bild()
    print(f"  Kanal {von}-{bis}: {list(bild[von - 1:bis])}")
    for meldung in show.meldungen:
        print("  Prüfung:", meldung)


def main() -> None:
    parser = argparse.ArgumentParser(description="DMX-Test")
    parser.add_argument("--kanal", type=int, help="DMX-Kanal 1 bis 512")
    parser.add_argument("--wert", type=int, default=255, help="Wert 0 bis 255")
    parser.add_argument("--sekunden", type=float, default=3.0)
    parser.add_argument("--geraete", action="store_true", help="jedes Gerät kurz einzeln an")
    parser.add_argument("--senden", action="store_true", help="wirklich über das Enttec senden")
    args = parser.parse_args()

    show = Show()
    show.start()
    try:
        if args.senden:
            show.ausgabe.einschalten()
            print("Enttec gefunden, DMX-Ausgabe läuft.")
        else:
            print("Simulator: Es geht nichts an die Lichter (mit --senden wirklich senden).")
        if args.geraete:
            for geraet in show.patch.geraete:
                print(f"{geraet['name']} (Adresse {geraet['adresse']})")
                show.test_geraet = geraet["id"]
                zeige(show, geraet["adresse"], geraet["adresse"] + show.patch.kanalzahl(geraet) - 1)
                time.sleep(args.sekunden)
            show.test_geraet = None
        elif args.kanal:
            if not 1 <= args.kanal <= 512 or not 0 <= args.wert <= 255:
                parser.error("Kanal 1 bis 512, Wert 0 bis 255.")
            show.test_kanaele = {args.kanal: args.wert}
            zeige(show, args.kanal, args.kanal)
            time.sleep(args.sekunden)
        else:
            parser.print_help()
    except EnttecFehler as fehler:
        print(f"Abgebrochen: {fehler}")
    finally:
        show.stopp()


if __name__ == "__main__":
    main()
