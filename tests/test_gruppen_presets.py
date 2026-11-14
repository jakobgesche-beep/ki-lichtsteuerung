"""Eigene Gruppen ("Front links") und eigene Presets ("Lieblingsblau") wie bei grandMA."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.patch import Patch, PatchFehler
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    return Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))


def test_eigene_gruppe(show):
    patch = show.patch
    ids = [g["id"] for g in patch.geraete[:2]]
    patch.eigene_gruppe_speichern("Front links", ids + ["gibt-es-nicht"])
    assert "Front links" in patch.gruppen()
    assert [g["id"] for g in patch.in_gruppe("Front links")] == ids
    assert "Front links" in patch.alle_gruppen_von(patch.geraete[0])
    assert "Front links" not in patch.gruppen_von(patch.geraete[0])          # die Funktion bleibt, wie sie ist
    with pytest.raises(PatchFehler, match="schon"):
        patch.eigene_gruppe_speichern(patch.gruppen_von(patch.geraete[0])[0], ids)
    with pytest.raises(PatchFehler):
        patch.eigene_gruppe_speichern("Leer", [])
    neu = Patch(show.pfade.fixtures, show.katalog)                              # bleibt gespeichert
    assert [g["id"] for g in neu.in_gruppe("Front links")] == ids
    patch.eigene_gruppe_loeschen("Front links")
    assert "Front links" not in patch.gruppen() and patch.in_gruppe("Front links") == []
    # Die Auswahl einer eigenen Gruppe geht wie bei jeder Gruppe
    patch.eigene_gruppe_speichern("Paar", ids)
    with TestClient(erstelle_app(show)) as client:
        assert client.post("/api/auswahl", json={"gruppe": "Paar"}).json()["auswahl"] == ids
        info = client.get("/api/pult").json()
        assert "Paar" in info["eigene_gruppen"] and "Paar" in info["geraete"][0]["gruppen"]


def test_eigene_presets(show):
    pult = show.pult
    a, b, c = [g["id"] for g in show.patch.geraete[:3]]
    pult.waehlen([a, b], "setzen")
    pult.programmer.setzen([a], {"farbe": "#1030ff", "helligkeit": 0.5})
    pult.programmer.setzen([b], {"farbe": "#2040ee"})
    with pytest.raises(ValueError, match="keine Position"):
        pult.preset_speichern("Mitte", "position")
    preset = pult.preset_speichern("Lieblingsblau", "farbe")
    assert preset["werte"] == {a: {"farbe": "#1030ff"}, b: {"farbe": "#2040ee"}}       # nur die Farbe, je Gerät
    pult.programmer.leeren()
    pult.waehlen([b, c], "setzen")
    pult.preset_anwenden(0)
    assert pult.programmer.werte[b]["farbe"] == "#2040ee"                  # eigener Wert
    assert pult.programmer.werte[c]["farbe"] == "#1030ff"                  # sonst der erste
    assert pult.oops                                                      # Oops geht
    assert pult.status()["presets"] == [{"nummer": 0, "name": "Lieblingsblau", "art": "farbe"}]
    pult.preset_speichern("Lieblingsblau", "farbe")                       # gleicher Name: ersetzt
    assert len(pult.presets) == 1
    with pytest.raises(ValueError):
        pult.preset_speichern("", "farbe")
    with pytest.raises(ValueError):
        pult.preset_speichern("X", "effekt")
    # Bleibt gespeichert (nächster Start)
    neu = Show(show.pfade)
    assert neu.pult.presets[0]["name"] == "Lieblingsblau"
    pult.preset_loeschen(0)
    assert pult.presets == []


def test_ueber_den_server(show):
    a = show.patch.geraete[0]["id"]
    with TestClient(erstelle_app(show)) as client:
        client.post("/api/auswahl", json={"geraete": [a]})
        assert client.post("/api/gruppen", json={"name": "Solo"}).json()["eigene_gruppen"] == ["Solo"]
        assert client.post("/api/gruppen", json={"name": ""}).status_code == 400
        client.post("/api/programmer/werte", json={"werte": {"helligkeit": 0.4}})
        status = client.post("/api/presets", json={"name": "Halb", "art": "dimmer"}).json()
        assert status["presets"][0]["name"] == "Halb"
        client.post("/api/programmer/leeren")
        client.post("/api/programmer/leeren")
        assert client.post("/api/presets/0/anwenden").json()["programmer"]["werte"][a]["helligkeit"] == 0.4
        assert client.post("/api/presets/7/anwenden").status_code == 400
        assert client.delete("/api/presets/0").json()["presets"] == []
        assert client.delete("/api/gruppen/Solo").json()["eigene_gruppen"] == []
        assert client.delete("/api/gruppen/Solo").status_code == 400
