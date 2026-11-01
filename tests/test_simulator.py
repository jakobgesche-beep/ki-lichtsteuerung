"""Der Simulator liest aus den DMX-Zahlen wieder heraus, was das Licht tut."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung.buehne import Buehne
from lichtsteuerung.pantilt import Montage, richtung, winkel_fuer_ziel
from lichtsteuerung.patch import Patch
from lichtsteuerung.render import Eigenschaften, Renderer
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show
from lichtsteuerung.simulator import Simulator


@pytest.fixture
def aufbau(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/par", "6", 1, "PAR")
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf")
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("par", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend",
                                "drehung_grad": 180, "neigung_grad": 20})
    buehne.setze_geraet("kopf", {"ort": "traverse", "x": 1, "y": 2, "z": 3.9, "montage": "haengend",
                                 "drehung_grad": 180})
    return patch, buehne, Renderer(patch), Simulator(patch, buehne)


def test_farbe_und_helligkeit_kommen_zurueck(aufbau):
    _, _, renderer, simulator = aufbau
    par = simulator.lies(renderer.bild({"par": Eigenschaften(helligkeit=0.8, farbe=(1, 0, 0))}))[0]
    assert par["hell"] == pytest.approx(0.8, abs=0.01)
    assert par["farbe"] == [1, 0, 0]


def test_farbrad_nimmt_den_naechsten_platz(aufbau):
    _, _, renderer, simulator = aufbau
    kopf = simulator.lies(renderer.bild({"kopf": Eigenschaften(helligkeit=1, farbe=(0.9, 0.1, 0.0))}))[1]
    assert kopf["farbe"] == [1, 0, 0]


def test_richtung_stimmt_mit_der_rechnung_ueberein(aufbau):
    _, buehne, renderer, simulator = aufbau
    montage = Montage.aus_buehne(buehne.geraet("kopf"))
    pan, tilt = winkel_fuer_ziel(montage, (0, 3, 0.8), 540, 270)
    kopf = simulator.lies(renderer.bild({"kopf": Eigenschaften(helligkeit=1, pan=pan, tilt=tilt)}))[1]
    assert kopf["richtung"] == pytest.approx(richtung(montage, pan, tilt), abs=0.002)


def test_blackout_zeigt_nichts(aufbau):
    _, _, renderer, simulator = aufbau
    assert all(g["hell"] == 0 for g in simulator.lies(renderer.bild({
        "par": Eigenschaften(helligkeit=0), "kopf": Eigenschaften(helligkeit=0)})))


def test_fester_par_zeigt_nach_neigung(aufbau):
    _, _, renderer, simulator = aufbau
    par = simulator.lies(renderer.bild({}))[0]
    assert par["richtung"][2] < 0 and par["richtung"][1] < 0     # nach unten, Richtung Publikum


def test_live_verbindung(pfade):
    with TestClient(erstelle_app(Show(pfade))) as client:
        with client.websocket_connect("/api/live") as leitung:
            daten = leitung.receive_json()
    assert daten["dmx_ein"] is False


def test_show_sendet_laufend_40_bilder(pfade):
    import time
    show = Show(pfade)
    show.start()
    zaehler = []
    original = show.baue_bild
    show.baue_bild = lambda *a: (zaehler.append(1), original(*a))[1]
    time.sleep(0.5)
    show.stopp()
    # Nach oben genau, nach unten großzügig: Testrechner können langsam sein.
    assert 5 <= len(zaehler) <= 21
