"""DMX-Ausgabe: Ein eigener Thread sendet ständig das aktuelle Bild.

Das Enttec Open DMX hat keinen eigenen Prozessor. Der Rechner muss das Signal
selbst laufend schicken, auch wenn sich nichts ändert. Das Enttec DMX USB Pro
bekommt ein fertiges Paket und kümmert sich selbst um den Takt. Beides geht.

Beim Start ist die Ausgabe aus. Dann gehen die Werte nur an den Simulator.
Eingeschaltet wird sie ausschließlich per Knopf und nur, wenn ein Enttec da ist.

Drei Wege zum Enttec, der erste, der klappt, wird benutzt:
    FTDI-Treiber   Windows: ftd2xx.dll, kommt mit dem normalen FTDI-Treiber (Windows lädt ihn meist selbst).
    USB direkt     pyftdi über libusb (Mac; unter Windows nur nach Zadig/WinUSB).
    Serieller Port Der Port, den der eingebaute Treiber anlegt (Mac: /dev/cu.usbserial-…, Windows: COM3 …).

Reißt die Verbindung ab (Kabel wackelt), läuft die Show im Simulator weiter und die
Ausgabe sucht jede Sekunde das Enttec. Ist es wieder da, sendet sie von selbst weiter.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Optional

BILDER_PRO_SEKUNDE = 40     # so oft rechnet die Show ein neues Bild
SENDEN_PRO_SEKUNDE = 30     # 512 Kanäle brauchen 23 ms auf der Leitung, dazu die Pause: 30 Pakete sind sicher
KANAELE = 512
FTDI_HERSTELLER, FTDI_PRODUKT = 0x0403, 0x6001
NEU_VERSUCHEN_S = 1.0


class EnttecFehler(Exception):
    """Kein Enttec gefunden oder die Verbindung ist abgerissen."""


def pro_paket(bild: bytes) -> bytes:
    """Ein Paket für das Enttec DMX USB Pro: Kopf, Startcode 0, Werte, Ende."""
    daten = b"\x00" + bytes(bild)
    return bytes([0x7E, 6, len(daten) & 0xFF, len(daten) >> 8]) + daten + b"\xE7"


def ist_pro(beschreibung: Optional[str]) -> bool:
    return "PRO" in (beschreibung or "").upper()


# --- Weg 1: FTDI-Treiber (Windows) ---------------------------------------------------

class EnttecFtdiTreiber:
    """Windows mit dem normalen FTDI-Treiber (ftd2xx.dll). Kein Zadig nötig."""

    art = "FTDI-Treiber"
    _dll = None

    @classmethod
    def dll(cls):
        if cls._dll is None and sys.platform == "win32":
            import ctypes
            for name in ("ftd2xx.dll", "ftd2xx64.dll"):
                try:
                    cls._dll = ctypes.WinDLL(name)
                    break
                except OSError:
                    continue
        return cls._dll

    @classmethod
    def suchen(cls) -> list:
        dll = cls.dll()
        if dll is None:
            return []
        import ctypes
        try:
            anzahl = ctypes.c_ulong(0)
            if dll.FT_CreateDeviceInfoList(ctypes.byref(anzahl)) != 0:
                return []
            gefunden = []
            for index in range(anzahl.value):
                flags, typ, kennung, ort = (ctypes.c_ulong(0) for _ in range(4))
                seriennummer, beschreibung = ctypes.create_string_buffer(64), ctypes.create_string_buffer(64)
                griff = ctypes.c_void_p()
                if dll.FT_GetDeviceInfoDetail(index, ctypes.byref(flags), ctypes.byref(typ), ctypes.byref(kennung),
                                              ctypes.byref(ort), seriennummer, beschreibung, ctypes.byref(griff)) != 0:
                    continue
                if (kennung.value >> 16, kennung.value & 0xFFFF) == (FTDI_HERSTELLER, FTDI_PRODUKT):
                    gefunden.append({"index": index, "beschreibung": beschreibung.value.decode("ascii", "replace"),
                                     "belegt": bool(flags.value & 1)})
            return gefunden
        except Exception:
            return []

    def __init__(self):
        import ctypes
        self.ctypes = ctypes
        dll = self.dll()
        geraete = self.suchen()
        if dll is None or not geraete:
            raise EnttecFehler("Kein Enttec über den FTDI-Treiber gefunden.")
        geraet = geraete[0]
        self.pro = ist_pro(geraet["beschreibung"])
        self.griff = ctypes.c_void_p()
        status = dll.FT_Open(geraet["index"], ctypes.byref(self.griff))
        if status != 0:
            grund = " Ein anderes Programm (zum Beispiel QLC+) benutzt es gerade." if geraet["belegt"] else ""
            raise EnttecFehler(f"Enttec lässt sich nicht öffnen (FTDI-Fehler {status}).{grund}")
        try:
            self._pruefe(dll.FT_ResetDevice(self.griff), "zurücksetzen")
            if not self.pro:
                self._pruefe(dll.FT_SetBaudRate(self.griff, 250000), "Tempo setzen")
                self._pruefe(dll.FT_SetDataCharacteristics(self.griff, 8, 2, 0), "Format setzen")   # 8N2
                self._pruefe(dll.FT_SetFlowControl(self.griff, 0, 0, 0), "Flusskontrolle")
                dll.FT_ClrRts(self.griff)
            dll.FT_Purge(self.griff, 3)
            dll.FT_SetTimeouts(self.griff, 200, 200)
        except Exception:
            dll.FT_Close(self.griff)
            raise

    @staticmethod
    def _pruefe(status: int, was: str) -> None:
        if status != 0:
            raise EnttecFehler(f"Enttec: {was} ging nicht (FTDI-Fehler {status}).")

    def _warten_bis_gesendet(self) -> None:
        """Erst wenn das vorige Bild ganz draußen ist, darf die Pause (Break) kommen."""
        ctypes = self.ctypes
        rein, raus, ereignis = ctypes.c_ulong(0), ctypes.c_ulong(0), ctypes.c_ulong(0)
        ende = time.monotonic() + 0.05
        while time.monotonic() < ende:
            if self.dll().FT_GetStatus(self.griff, ctypes.byref(rein), ctypes.byref(raus), ctypes.byref(ereignis)) != 0:
                return
            if raus.value == 0:
                return
            time.sleep(0.001)

    def sende(self, bild: bytes) -> None:
        dll = self.dll()
        if self.pro:
            daten = pro_paket(bild)
        else:
            self._warten_bis_gesendet()
            self._pruefe(dll.FT_SetBreakOn(self.griff), "Break")
            self._pruefe(dll.FT_SetBreakOff(self.griff), "Break")
            daten = b"\x00" + bytes(bild)
        geschrieben = self.ctypes.c_ulong(0)
        status = dll.FT_Write(self.griff, daten, len(daten), self.ctypes.byref(geschrieben))
        if status != 0 or geschrieben.value != len(daten):
            raise OSError(f"Senden ging nicht (FTDI-Fehler {status}, {geschrieben.value} von {len(daten)} Bytes)")

    def schliessen(self) -> None:
        self.dll().FT_Close(self.griff)


# --- Weg 2: USB direkt über libusb (pyftdi) -----------------------------------------------

def _lade_usb_treiber() -> None:
    """Macht den mitgelieferten libusb-Treiber bekannt. Danach findet ihn auch pyftdi."""
    import libusb_package
    import usb.backend.libusb1
    usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)


class EnttecOpenDmx:
    """Spricht direkt mit dem FTDI-Chip im Enttec (Vorlage: pyopendmx). Mac; Windows nur mit Zadig/WinUSB."""

    art = "USB direkt"

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
        geraete = self.suchen()
        beschreibung = getattr(geraete[0][0], "description", "") if geraete else ""
        self.pro = ist_pro(beschreibung)
        self.ftdi = Ftdi()
        try:
            self.ftdi.open(FTDI_HERSTELLER, FTDI_PRODUKT)
            self.ftdi.reset()
            if not self.pro:
                self.ftdi.set_baudrate(250000)
                self.ftdi.set_line_property(8, 2, "N")
        except Exception as fehler:
            try:
                self.ftdi.close()
            except Exception:
                pass
            raise EnttecFehler(f"Enttec lässt sich nicht direkt öffnen: {fehler}") from fehler

    def sende(self, bild: bytes) -> None:
        if self.pro:
            self.ftdi.write_data(pro_paket(bild))
            return
        # Ein DMX-Paket: Break, dann Startcode 0, dann 512 Werte.
        self.ftdi.set_break(True)
        self.ftdi.set_break(False)
        self.ftdi.write_data(b"\x00" + bytes(bild))

    def schliessen(self) -> None:
        self.ftdi.close()


# --- Weg 3: der serielle Port des eingebauten Treibers ----------------------------------------

class EnttecSeriell:
    """Über den seriellen Port, den Mac (Apple-Treiber) oder Windows (FTDI-Treiber) selbst anlegen."""

    art = "Serieller Port"

    @staticmethod
    def suchen() -> list:
        try:
            from serial.tools import list_ports
            return [p for p in list_ports.comports() if (p.vid, p.pid) == (FTDI_HERSTELLER, FTDI_PRODUKT)]
        except Exception:
            return []

    def __init__(self):
        import serial
        ports = self.suchen()
        if not ports:
            raise EnttecFehler("Kein serieller Port vom Enttec gefunden.")
        port = ports[0]
        self.pro = ist_pro(f"{port.description} {port.product or ''}")
        try:
            self.leitung = serial.Serial(port.device, baudrate=57600 if self.pro else 250000,
                                         bytesize=8, parity="N", stopbits=2, timeout=0.2, write_timeout=0.5)
        except Exception as fehler:
            raise EnttecFehler(f"Port {port.device} lässt sich nicht öffnen: {fehler}") from fehler

    def sende(self, bild: bytes) -> None:
        if self.pro:
            self.leitung.write(pro_paket(bild))
            return
        self.leitung.flush()                       # erst muss das vorige Bild draußen sein
        self.leitung.break_condition = True
        time.sleep(0.00015)                        # Break: mindestens 88 µs
        self.leitung.break_condition = False
        self.leitung.write(b"\x00" + bytes(bild))

    def schliessen(self) -> None:
        self.leitung.close()


def standard_wege() -> list:
    if sys.platform == "win32":
        return [EnttecFtdiTreiber, EnttecOpenDmx, EnttecSeriell]
    return [EnttecOpenDmx, EnttecSeriell]


def kein_enttec_text() -> str:
    if sys.platform == "win32":
        return ("Kein Enttec gefunden. USB-Kabel prüfen. Erkennt Windows es nicht, den FTDI-Treiber installieren "
                "(ftdichip.com → Drivers → VCP/D2XX, „setup executable“) und das Enttec neu einstecken.")
    return "Kein Enttec gefunden. USB-Kabel prüfen und das Enttec neu einstecken."


class DmxAusgabe:
    def __init__(self, geraet_klasse=None):
        self.wege = [geraet_klasse] if geraet_klasse is not None else standard_wege()
        self.bild = bytes(KANAELE)
        self.geraet = None
        self.weg: Optional[str] = None             # über welchen Weg das Enttec gerade spricht
        self.gewuenscht = False                    # der Knopf steht auf "an"
        self.gesendet = 0
        self.verbindungen = 0
        self.fehler: Optional[str] = None
        self._sperre = threading.Lock()
        self._stopp = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def eingeschaltet(self) -> bool:
        """Der Knopf steht auf an. Ob das Enttec gerade wirklich antwortet, sagt `verbunden`."""
        return self.gewuenscht

    @property
    def verbunden(self) -> bool:
        return self.geraet is not None

    def enttec_gefunden(self) -> bool:
        return any(weg.suchen() for weg in self.wege)

    def setze_bild(self, bild: bytes) -> None:
        self.bild = bytes(bild)

    def _oeffnen(self):
        """Probiert die Wege der Reihe nach. Gibt das offene Gerät zurück."""
        gruende = []
        for weg in self.wege:
            if not weg.suchen():
                continue
            try:
                geraet = weg()
                self.weg = getattr(weg, "art", weg.__name__)
                return geraet
            except Exception as fehler:
                gruende.append(str(fehler))
        raise EnttecFehler(" ".join(gruende) or kein_enttec_text())

    def einschalten(self) -> None:
        """Nur vom Knopf aufzurufen. Ohne Enttec gibt es einen Fehler."""
        with self._sperre:
            if self.gewuenscht:
                return
            if not self.enttec_gefunden():
                raise EnttecFehler(kein_enttec_text())
            self.geraet = self._oeffnen()
            self.gewuenscht = True
            self.verbindungen += 1
            self.fehler = None
            self._stopp.clear()
            self._thread = threading.Thread(target=self._schleife, name="DMX-Ausgabe", daemon=True)
            self._thread.start()

    def ausschalten(self) -> None:
        with self._sperre:
            self.gewuenscht = False
            self._stopp.set()
            if self._thread is not None:
                self._thread.join(timeout=1.5)
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
            self.fehler = None

    def _schleife(self) -> None:
        abstand = 1.0 / SENDEN_PRO_SEKUNDE
        naechstes = time.monotonic()
        letzter_versuch = 0.0
        while not self._stopp.is_set():
            if self.geraet is None:
                # Kabel war weg: jede Sekunde neu suchen. Die Show läuft so lange im Simulator weiter.
                if time.monotonic() - letzter_versuch >= NEU_VERSUCHEN_S:
                    letzter_versuch = time.monotonic()
                    try:
                        geraet = self._oeffnen()
                        if self._stopp.is_set():
                            geraet.schliessen()
                            return
                        self.geraet, self.fehler = geraet, None
                        self.verbindungen += 1
                        naechstes = time.monotonic()
                        continue
                    except Exception:
                        pass
                self._stopp.wait(0.1)
                continue
            try:
                self.geraet.sende(self.bild)
                self.gesendet += 1
            except Exception as fehler:
                self.fehler = f"DMX-Verbindung unterbrochen ({fehler}). Das Programm sucht das Enttec und sendet von selbst weiter."
                try:
                    self.geraet.schliessen()
                except Exception:
                    pass
                self.geraet = None
                letzter_versuch = time.monotonic()
                continue
            naechstes += abstand
            warten = naechstes - time.monotonic()
            if warten > 0:
                self._stopp.wait(warten)
            else:
                naechstes = time.monotonic()

    def status(self) -> dict:
        return {"eingeschaltet": self.gewuenscht, "verbunden": self.verbunden, "weg": self.weg if self.verbunden else None,
                "fehler": self.fehler, "gesendet": self.gesendet}
