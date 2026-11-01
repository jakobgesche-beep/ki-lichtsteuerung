"""Katalog und Patch über den Webserver."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


@pytest.fixture
def client(pfade):
    return TestClient(erstelle_app(Show(pfade)))


def test_patchen_mit_ort(client):
    antwort = client.post("/api/patch", json={"typ": "test/par", "modus": "6", "anzahl": 2,
                                              "name": "PAR 1-2", "ort": "traverse"}).json()
    assert [g["adresse"] for g in antwort["geraete"]] == [1, 7]
    assert antwort["geraete"][0]["ort"]["montage"] == "haengend"


def test_fehler_kommt_als_lesbare_meldung(client):
    antwort = client.post("/api/patch", json={"typ": "test/par", "modus": "6", "name": "A", "start": 600})
    assert antwort.status_code == 400
    assert "512" in antwort.json()["fehler"]


def test_ueberschneidung_wird_rot(client):
    client.post("/api/patch", json={"typ": "test/par", "modus": "6", "name": "A", "start": 1})
    antwort = client.post("/api/patch", json={"typ": "test/par", "modus": "6", "name": "B", "start": 3}).json()
    assert all(g["problem"] for g in antwort["geraete"])


def test_fremde_webseite_wird_abgewiesen(client):
    antwort = client.post("/api/patch", headers={"Origin": "http://boese.example"},
                          json={"typ": "test/par", "modus": "6", "name": "A"})
    assert antwort.status_code == 403
