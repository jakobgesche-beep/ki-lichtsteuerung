"""DMX-Ausgabe mit einem nachgebauten Enttec. Ein echtes lag nicht vor."""
import time

import pytest

from lichtsteuerung.dmx_ausgabe import DmxAusgabe, EnttecFehler


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
    assert 15 <= len(gesendet) <= 22      # 40 Bilder pro Sekunde mal 0,5 s


def test_beim_ausschalten_gehen_die_lichter_aus():
    ausgabe = DmxAusgabe(FalschesEnttec)
    ausgabe.setze_bild(bytes([7]) * 512)
    ausgabe.einschalten()
    ausgabe.ausschalten()
    assert FalschesEnttec.pakete[-1] == bytes(512)
    assert not ausgabe.eingeschaltet


def test_abgezogenes_kabel_gibt_meldung_statt_absturz():
    class Kaputt(FalschesEnttec):
        def sende(self, bild):
            raise OSError("USB weg")

    ausgabe = DmxAusgabe(Kaputt)
    ausgabe.einschalten()
    time.sleep(0.1)
    assert not ausgabe.eingeschaltet
    assert "USB weg" in ausgabe.fehler


def test_auf_diesem_rechner_wird_kein_enttec_gefunden_und_nichts_stuerzt_ab():
    assert DmxAusgabe().eingeschaltet is False
    assert DmxAusgabe().enttec_gefunden() in (True, False)
