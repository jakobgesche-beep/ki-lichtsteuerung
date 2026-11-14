"""Handy-Fernbedienung: eigener Zugang mit PIN, nur Show-Tasten, Schutz gegen PIN-Raten."""
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten, fernbedienung
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.fernbedienung.host = "127.0.0.1"
    return s


def angemeldet(show):
    fern = show.fernbedienung
    fern.pin = "123456"
    handy = TestClient(fern.app)
    token = handy.post("/fern/anmelden", json={"pin": "123 456"}).json()["token"]
    handy.headers["X-Fern"] = token
    return handy


def test_nur_mit_pin(show):
    fern = show.fernbedienung
    handy = TestClient(fern.app)
    assert handy.get("/").status_code == 200 and "Fernbedienung" in handy.get("/").text
    assert handy.post("/fern/anmelden", json={"pin": "123456"}).status_code == 401      # aus: keine PIN gültig
    fern.pin = "123456"
    assert handy.get("/fern/zustand").status_code == 401
    assert handy.get("/fern/zustand", headers={"X-Fern": "geraten"}).status_code == 401
    assert handy.post("/fern/anmelden", json={"pin": "000000"}).json()["fehler"] == "Falsche PIN."
    antwort = handy.post("/fern/anmelden", json={"pin": "123456"})
    assert antwort.status_code == 200
    zustand = handy.get("/fern/zustand", headers={"X-Fern": antwort.json()["token"]}).json()
    assert len(zustand["looks"]) == 9 and "blackout" in zustand
    # Die Fernbedienung kennt nur ihre eigenen Wege, nicht die des Pults
    assert handy.get("/api/patch").status_code == 404
    assert handy.post("/api/ki/schluessel", json={"schluessel": "x"}).status_code == 404


def test_tasten_vom_handy(show):
    handy = angemeldet(show)
    assert handy.post("/fern/look/ballade").json()["look"] == "ballade"
    assert handy.post("/fern/look/quatsch").status_code == 400
    assert handy.post("/fern/look/aus").json()["look"] is None
    assert handy.post("/fern/farben", json={"farbe_1": "gruen"}).json()["farbe_1"] == "gruen"
    handy.post("/fern/halten/strobo", json={"an": True})
    assert show.pult.halten["strobo"] is not None
    handy.post("/fern/halten/strobo", json={"an": False})
    assert show.pult.halten["strobo"] is None
    assert handy.post("/fern/halten/quatsch", json={"an": True}).status_code == 400
    assert handy.post("/fern/blackout").json()["blackout"] is True
    assert handy.post("/fern/blackout").json()["blackout"] is False
    assert handy.post("/fern/tap").status_code == 200
    assert handy.post("/fern/song/start", json={"name": "gibt es nicht"}).status_code == 400


def test_neue_pin_meldet_alle_ab(show):
    handy = angemeldet(show)
    show.fernbedienung.server = object()           # tut so, als liefe sie
    show.fernbedienung.neue_pin()
    show.fernbedienung.server = None
    assert handy.get("/fern/zustand").status_code == 401
    assert len(show.fernbedienung.pin) == fernbedienung.PIN_STELLEN


def test_schutz_gegen_pin_raten(show):
    fern = show.fernbedienung
    fern.pin = "123456"
    for _ in range(fernbedienung.FEHLVERSUCHE_PRO_HANDY):
        with pytest.raises(PermissionError, match="Falsche PIN"):
            fern.anmelden("999999", "10.0.0.5")
    with pytest.raises(PermissionError, match="warten"):
        fern.anmelden("123456", "10.0.0.5")                 # auch die richtige: erst warten
    assert fern.anmelden("123456", "10.0.0.6")              # ein anderes Handy darf
    for i in range(fernbedienung.FEHLVERSUCHE_GESAMT):
        try:
            fern.anmelden("999999", f"10.0.1.{i}")
        except PermissionError:
            pass
    with pytest.raises(PermissionError, match="keine PIN"):
        fern.anmelden("123456", "10.0.0.7")                 # jetzt nimmt sie gar keine PIN mehr an


def test_echter_server_an_und_aus(show):
    fern = show.fernbedienung
    fern.einschalten()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{fern.port}/", timeout=5) as antwort:
            assert antwort.status == 200
        zustand = fern.zustand()
        assert zustand["an"] and len(zustand["pin"]) == 6
        if zustand["link"]:                                 # ohne Netzwerk gibt es keine Adresse
            assert zustand["link"].endswith("?pin=" + zustand["pin"]) and zustand["qr"].startswith("<svg")
    finally:
        port = fern.port
        fern.ausschalten()
    with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)


def test_ueber_den_pult_server_und_konzert_check(show):
    with TestClient(erstelle_app(show)) as client:
        assert client.get("/api/fernbedienung").json()["an"] is False
        assert client.post("/api/fernbedienung/neue_pin").status_code == 400          # aus
        try:
            assert client.post("/api/fernbedienung", json={"an": True}).json()["an"] is True
            assert any(p["thema"] == "Handy" for p in client.get("/api/check").json()["punkte"])
        finally:
            assert client.post("/api/fernbedienung", json={"an": False}).json()["an"] is False
