"""DMX-Ausgabe: Ein eigener Thread sendet ständig das aktuelle Bild.

Das Enttec Open DMX hat keinen eigenen Prozessor. Der Rechner muss das Signal
selbst laufend schicken, auch wenn sich nichts ändert (40 Bilder pro Sekunde).

Beim Start ist die Ausgabe aus. Dann gehen die Werte nur an den Simulator.
Eingeschaltet wird sie ausschließlich per Knopf und nur, wenn ein Enttec da ist.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

BILDER_PRO_SEKUNDE = 40
KANAELE = 512
FTDI_HERSTELLER, FTDI_PRODUKT = 0x0403, 0x6001


def _lade_usb_treiber() -> None:
    """Macht den mitgelieferten libusb-Treiber bekannt. Danach findet ihn auch pyftdi."""
    import libusb_package
    import usb.backend.libusb1
    usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)


class EnttecFehler(Exception):
    """Kein Enttec gefunden oder die Verbindung ist abgerissen."""


class EnttecOpenDmx:
    """Spricht direkt mit dem FTDI-Chip im Enttec Open DMX USB (Vorlage: pyopendmx)."""

    @staticmethod
    def suchen() -> list:
        """Liste der angeschlossenen Geräte. Leer, wenn keins da ist."""
        try:
            _lade_usb_treiber()
            from pyftdi.usbtools import UsbTools
            return UsbTools.find_all([(FTDI_HERSTELLER, FTDI_PRODUKT)])
        except ImportError:
            return []
        except Exception:
            # Zum Beispiel: USB-Treiber libusb fehlt. Für uns heißt das: nichts gefunden.
            return []

    def __init__(self):
        _lade_usb_treiber()
        from pyftdi.ftdi import Ftdi
        self.ftdi = Ftdi()
        try:
            self.ftdi.open(FTDI_HERSTELLER, FTDI_PRODUKT)
            self.ftdi.reset()
            self.ftdi.set_baudrate(250000)
            self.ftdi.set_line_property(8, 2, "N")
        except Exception as fehler:
            raise EnttecFehler(f"Enttec lässt sich nicht öffnen: {fehler}") from fehler

    def sende(self, bild: bytes) -> None:
        # Ein DMX-Paket: Break, dann Startcode 0, dann 512 Werte.
        self.ftdi.set_break(True)
        self.ftdi.set_break(False)
        self.ftdi.write_data(b"\x00" + bytes(bild))

    def schliessen(self) -> None:
        self.ftdi.close()


class DmxAusgabe:
    def __init__(self, geraet_klasse=EnttecOpenDmx):
        self.geraet_klasse = geraet_klasse
        self.bild = bytes(KANAELE)
        self.geraet = None
        self.gesendet = 0
        self.fehler: Optional[str] = None
        self._sperre = threading.Lock()
        self._stopp = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def eingeschaltet(self) -> bool:
        return self.geraet is not None

    def enttec_gefunden(self) -> bool:
        return bool(self.geraet_klasse.suchen())

    def setze_bild(self, bild: bytes) -> None:
        self.bild = bytes(bild)

    def einschalten(self) -> None:
        """Nur vom Knopf aufzurufen. Ohne Enttec gibt es einen Fehler."""
        with self._sperre:
            if self.geraet is not None:
                return
            if not self.enttec_gefunden():
                raise EnttecFehler("Kein Enttec gefunden.")
            self.geraet = self.geraet_klasse()
            self.fehler = None
            self._stopp.clear()
            self._thread = threading.Thread(target=self._schleife, name="DMX-Ausgabe", daemon=True)
            self._thread.start()

    def ausschalten(self) -> None:
        with self._sperre:
            self._stopp.set()
            if self._thread is not None:
                self._thread.join(timeout=1.0)
                self._thread = None
            if self.geraet is not None:
                try:
                    # Lichter nicht auf dem letzten Stand stehen lassen.
                    for _ in range(3):
                        self.geraet.sende(bytes(KANAELE))
                    self.geraet.schliessen()
                except Exception:
                    pass
                self.geraet = None

    def _schleife(self) -> None:
        abstand = 1.0 / BILDER_PRO_SEKUNDE
        naechstes = time.monotonic()
        while not self._stopp.is_set():
            try:
                self.geraet.sende(self.bild)
                self.gesendet += 1
            except Exception as fehler:
                # Kabel gezogen: Die Show läuft im Simulator weiter.
                self.fehler = f"DMX-Ausgabe unterbrochen: {fehler}"
                self.geraet = None
                return
            naechstes += abstand
            warten = naechstes - time.monotonic()
            if warten > 0:
                time.sleep(warten)
            else:
                naechstes = time.monotonic()
