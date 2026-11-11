"""DMX-Ausgabe mit einem nachgebauten Enttec. Ein echtes lag nicht vor."""
import time

import pytest

from lichtsteuerung.dmx_ausgabe import DmxAusgabe, EnttecFehler, EnttecFtdiTreiber, EnttecSeriell, pro_paket


class FalschesEnttec:
    vorhanden = True
    pakete = []

    @classmethod
    def suchen(cls):
        return ["gerät"] if cls.vorhanden else []

    def sende(self, bild):
        FalschesEnttec.pakete.append(bytes(bild))

    def schliessen(self):
        pass


@pytest.fixture(autouse=True)
def zuruecksetzen():
    FalschesEnttec.vorhanden = True
    FalschesEnttec.pakete = []


def test_beim_start_ist_die_ausgabe_aus():
    ausgabe = DmxAusgabe(FalschesEnttec)
    assert not ausgabe.eingeschaltet
    time.sleep(0.06)
    assert FalschesEnttec.pakete == []


def test_ohne_enttec_laesst_sie_sich_nicht_einschalten():
    FalschesEnttec.vorhanden = False
    ausgabe = DmxAusgabe(FalschesEnttec)
    with pytest.raises(EnttecFehler):
        ausgabe.einschalten()
    assert not ausgabe.eingeschaltet


def test_sendet_laufend_auch_ohne_aenderung():
    ausgabe = DmxAusgabe(FalschesEnttec)
    ausgabe.setze_bild(bytes([7]) * 512)
    ausgabe.einschalten()
    time.sleep(0.5)
    ausgabe.ausschalten()
    gesendet = [p for p in FalschesEnttec.pakete if p[0] == 7]
    assert 5 <= len(gesendet) <= 17       # höchstens 30 Bilder pro Sekunde, Testrechner können langsam sein


def test_beim_ausschalten_gehen_die_lichter_aus():
    ausgabe = DmxAusgabe(FalschesEnttec)
    ausgabe.setze_bild(bytes([7]) * 512)
    ausgabe.einschalten()
    ausgabe.ausschalten()
    assert FalschesEnttec.pakete[-1] == bytes(512)
    assert not ausgabe.eingeschaltet


def test_abgezogenes_kabel_gibt_meldung_und_verbindet_sich_von_selbst_wieder():
    class Wackelig(FalschesEnttec):
        kaputt = True

        def sende(self, bild):
            if Wackelig.kaputt:
                raise OSError("USB weg")
            FalschesEnttec.pakete.append(bytes(bild))

    ausgabe = DmxAusgabe(Wackelig)
    ausgabe.setze_bild(bytes([9]) * 512)
    ausgabe.einschalten()
    time.sleep(0.15)
    assert ausgabe.eingeschaltet and not ausgabe.verbunden
    assert "USB weg" in ausgabe.fehler
    Wackelig.kaputt = False                  # Kabel wieder drin
    time.sleep(1.4)
    assert ausgabe.verbunden and ausgabe.fehler is None and ausgabe.verbindungen >= 2
    assert any(p[0] == 9 for p in FalschesEnttec.pakete)
    ausgabe.ausschalten()


def test_pro_paket():
    paket = pro_paket(bytes([1, 2, 3]))
    assert paket == bytes([0x7E, 6, 4, 0, 0, 1, 2, 3, 0xE7])
    assert len(pro_paket(bytes(512))) == 518


class FalscheDll:
    """Nachgebaute ftd2xx.dll: ein Enttec Open DMX an Platz 0."""

    def __init__(self, beschreibung=b"FT232R USB UART", belegt=False):
        self.beschreibung, self.belegt = beschreibung, belegt
        self.aufrufe = []

    def __getattr__(self, name):
        def funktion(*argumente):
            self.aufrufe.append((name, argumente))
            return 0
        return funktion

    def FT_CreateDeviceInfoList(self, anzahl):
        anzahl._obj.value = 1
        return 0

    def FT_GetDeviceInfoDetail(self, index, flags, typ, kennung, ort, seriennummer, beschreibung, griff):
        flags._obj.value = 1 if self.belegt else 0
        kennung._obj.value = (0x0403 << 16) | 0x6001
        beschreibung.value = self.beschreibung
        return 0

    def FT_Open(self, index, griff):
        self.aufrufe.append(("FT_Open", (index,)))
        return 3 if self.belegt else 0

    def FT_Write(self, griff, daten, laenge, geschrieben):
        self.aufrufe.append(("FT_Write", (bytes(daten),)))
        geschrieben._obj.value = laenge
        return 0


def test_windows_ftdi_treiber_sendet_break_und_512_werte(monkeypatch):
    dll = FalscheDll()
    monkeypatch.setattr(EnttecFtdiTreiber, "_dll", dll)
    assert EnttecFtdiTreiber.suchen()[0]["beschreibung"] == "FT232R USB UART"
    enttec = EnttecFtdiTreiber()
    namen = [n for n, _ in dll.aufrufe]
    assert namen[:5] == ["FT_Open", "FT_ResetDevice", "FT_SetBaudRate", "FT_SetDataCharacteristics", "FT_SetFlowControl"]
    assert ("FT_SetBaudRate", (enttec.griff, 250000)) in dll.aufrufe
    assert ("FT_SetDataCharacteristics", (enttec.griff, 8, 2, 0)) in dll.aufrufe
    dll.aufrufe.clear()
    enttec.sende(bytes([5]) * 512)
    namen = [n for n, _ in dll.aufrufe]
    assert namen.index("FT_SetBreakOn") < namen.index("FT_SetBreakOff") < namen.index("FT_Write")
    geschrieben = dll.aufrufe[namen.index("FT_Write")][1][0]
    assert len(geschrieben) == 513 and geschrieben[0] == 0 and geschrieben[1] == 5


def test_windows_ftdi_treiber_mit_pro_und_belegt(monkeypatch):
    dll = FalscheDll(b"DMX USB PRO")
    monkeypatch.setattr(EnttecFtdiTreiber, "_dll", dll)
    enttec = EnttecFtdiTreiber()
    dll.aufrufe.clear()
    enttec.sende(bytes(512))
    assert [n for n, _ in dll.aufrufe] == ["FT_Write"] and dll.aufrufe[0][1][0][:2] == bytes([0x7E, 6])
    monkeypatch.setattr(EnttecFtdiTreiber, "_dll", FalscheDll(belegt=True))
    with pytest.raises(EnttecFehler, match="anderes Programm"):
        EnttecFtdiTreiber()


def test_serieller_port_break_dann_bild(monkeypatch):
    import serial
    from serial.tools import list_ports
    port = type("Port", (), {"vid": 0x0403, "pid": 0x6001, "device": "/dev/cu.usbserial-EN1", "description": "FT232R", "product": None})()
    monkeypatch.setattr(list_ports, "comports", lambda: [port])
    protokoll = []

    class Leitung:
        def __init__(self, geraet, **einstellungen):
            protokoll.append(("auf", geraet, einstellungen["baudrate"], einstellungen["stopbits"]))

        def flush(self):
            protokoll.append("flush")

        def __setattr__(self, name, wert):
            protokoll.append((name, wert))

        def write(self, daten):
            protokoll.append(("write", len(daten), daten[0]))

    monkeypatch.setattr(serial, "Serial", Leitung)
    enttec = EnttecSeriell()
    enttec.sende(bytes(512))
    assert protokoll == [("auf", "/dev/cu.usbserial-EN1", 250000, 2), "flush", ("break_condition", True),
                         ("break_condition", False), ("write", 513, 0)]


def test_erster_weg_klappt_nicht_der_naechste_schon():
    class Blockiert(FalschesEnttec):
        def __init__(self):
            raise EnttecFehler("vom Apple-Treiber belegt")

    ausgabe = DmxAusgabe()
    ausgabe.wege = [Blockiert, FalschesEnttec]
    ausgabe.einschalten()
    assert ausgabe.verbunden and ausgabe.weg == "FalschesEnttec"
    ausgabe.ausschalten()


def test_auf_diesem_rechner_wird_kein_enttec_gefunden_und_nichts_stuerzt_ab():
    assert DmxAusgabe().eingeschaltet is False
    assert DmxAusgabe().enttec_gefunden() in (True, False)
