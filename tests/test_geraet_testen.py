"""Setup → DMX-Test → "Ein Gerät testen": nur dieses Gerät bekommt Werte; Enttec-Art von Hand; als Gerät speichern."""
import time

import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten, dmx_ausgabe
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import GERAET_TEST_S, Show


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    return Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))


@pytest.fixture(autouse=True)
def art_zuruecksetzen():
    yield
    dmx_ausgabe.ART_ERZWUNGEN = None


def test_nur_dieses_geraet(show):
    show.pult.look_druecken("hoehepunkt", time.monotonic())        # die Show will hell leuchten
    show.baue_bild()
    assert any(show.letztes_bild)
    show.test_setzen(None, {1: 255, 4: 200, 9: 17}, nur=True)
    bild = show.baue_bild()
    assert bild[0] == 255 and bild[3] == 200 and bild[8] == 17
    assert sum(1 for wert in bild if wert) == 3                      # alles andere bleibt auf 0
    assert show.test_max_s == GERAET_TEST_S
    show.overrides.umschalten("blackout")
    assert not any(show.baue_bild())                                 # Blackout gilt immer
    show.overrides.umschalten("blackout")
    show.test_setzen(None, {}, nur=False)
    assert not show.test_nur


def test_bewegen_faehrt_pan_und_tilt(show):
    show.test_setzen(None, {3: 255}, nur=True, bewegen=(1, 2))
    werte = set()
    for _ in range(6):
        bild = show.baue_bild()
        werte.add((bild[0], bild[1]))
        time.sleep(0.2)
    assert len(werte) > 2 and all(58 <= pan <= 198 and 83 <= tilt <= 173 for pan, tilt in werte)


def test_enttec_art_von_hand():
    assert dmx_ausgabe.ist_pro("DMX USB PRO") and not dmx_ausgabe.ist_pro("FT232R USB UART")
    dmx_ausgabe.ART_ERZWUNGEN = "pro"
    assert dmx_ausgabe.ist_pro("FT232R USB UART")
    dmx_ausgabe.ART_ERZWUNGEN = "open"
    assert not dmx_ausgabe.ist_pro("DMX USB PRO")


def test_ueber_den_server_und_als_geraet_speichern(show, tmp_path):
    with TestClient(erstelle_app(show)) as client:
        antwort = client.post("/api/dmxtest", json={"kanaele": {"1": 255, "2": 128}, "nur": True, "bewegen": [1, 0]}).json()
        assert antwort["nur"] is True and antwort["bild"][1] == 128 and sum(1 for w in antwort["bild"][2:] if w) == 0
        assert client.post("/api/dmxtest", json={}).json()["nur"] is False
        assert client.post("/api/dmx/art", json={"art": "quatsch"}).status_code == 400
        assert client.post("/api/dmx/art", json={"art": "pro"}).json()["art"] == "pro"
        assert daten.lese_json(show.pfade.wurzel / "daten" / "dmx.json")["art"] == "pro"
        client.post("/api/dmx/art", json={"art": "auto"})
        # So speichert die Seite ein getestetes Gerät (gleiche Daten wie in dmxtest.js)
        kanaele = {"Kanal 1 Pan": {"typ": "pan", "standard": 128, "grad": 540},
                   "Kanal 2 Tilt": {"typ": "tilt", "standard": 128, "grad": 270},
                   "Kanal 3 Dimmer": {"typ": "dimmer", "standard": 0},
                   "Kanal 4 Rot": {"typ": "rot", "standard": 0}, "Kanal 5 Grün": {"typ": "gruen", "standard": 0},
                   "Kanal 6 Blau": {"typ": "blau", "standard": 0},
                   "Kanal 7 Strobo / Shutter": {"typ": "strobo", "standard": 8,
                                                "bereiche": [{"von": 8, "bis": 8, "typ": "offen", "name": "Licht an"}]},
                   "Kanal 8 Auto / Programm / Reset": {"typ": "makro", "standard": 0}}
        eintrag = {"id": "eigene/moving-head-amazon", "hersteller": "Eigene", "name": "Moving Head Amazon",
                   "kategorien": ["Moving Head"], "physik": {"gewicht_kg": None, "abstrahlwinkel_grad": None},
                   "kanaele": kanaele, "modi": [{"name": "8 Kanäle", "kanaele": list(kanaele)}],
                   "quelle": {"art": "eigener Eintrag"}, "handbuch_geprueft": False}
        assert client.post("/api/katalog", json=eintrag).status_code == 200
        frei = client.get("/api/patch/naechste_freie", params={"kanaele": 8}).json()["adresse"]
        antwort = client.post("/api/patch", json={"typ": "eigene/moving-head-amazon", "modus": "8 Kanäle", "anzahl": 1,
                                                 "name": "Moving Head Amazon", "start": frei, "gruppen": ["Spots"],
                                                 "ort": "traverse"})
        assert antwort.status_code == 200
        geraet = next(g for g in show.patch.geraete if g["name"] == "Moving Head Amazon")
        assert geraet["adresse"] == frei
    # In der Show: Der Shutter steht auf dem beim Testen gefundenen Wert, blitzen geht nicht
    show.pult.look_druecken("ballade", time.monotonic())
    bild = show.baue_bild()
    assert bild[frei - 1 + 6] == 8 and bild[frei - 1 + 7] == 0
