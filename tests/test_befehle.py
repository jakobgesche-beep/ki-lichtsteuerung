"""Die Befehlszeile."""
import pytest

from lichtsteuerung.befehle import BefehlsFehler, Befehlszeile
from lichtsteuerung.buehne import Buehne
from lichtsteuerung.patch import Patch
from lichtsteuerung.show import Show


@pytest.fixture
def zeile(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/par", "6", 3, "PAR 1-3", gruppen=["Farb-PARs"])
    patch.hinzufuegen("test/kopf", "7", 2, "Kopf 1-2", gruppen=["Spots"])
    patch.speichern()
    buehne = Buehne(pfade.stage)
    for g, x in (("kopf-1", -1), ("kopf-2", 1)):
        buehne.setze_geraet(g, {"ort": "traverse", "x": x, "y": 2, "z": 3.9, "montage": "haengend", "drehung_grad": 180})
    buehne.speichern()
    show = Show(pfade)
    return Befehlszeile(show)


def test_geraete_bis_und_auf(zeile):
    antwort = zeile.ausfuehren("Gerät 1 bis 3 auf 80")
    assert zeile.show.pult.auswahl == ["par-1", "par-2", "par-3"]
    assert zeile.show.pult.programmer.werte["par-2"]["helligkeit"] == 0.8
    assert "80 %" in antwort


def test_englisch_wie_bei_grandma(zeile):
    zeile.ausfuehren("Fixture 1 + 3 At Full")
    assert zeile.show.pult.auswahl == ["par-1", "par-3"]
    assert zeile.show.pult.programmer.werte["par-3"]["helligkeit"] == 1.0


def test_gruppe_farbe_position_gobo_effekt(zeile):
    zeile.ausfuehren("Gruppe Spots Farbe Rot Position Mitte Gobo Offen Effekt Kreis")
    werte = zeile.show.pult.programmer.werte["kopf-1"]
    assert werte["farbe"] == "rot" and werte["position"] == "Mitte" and werte["gobo"] == "Offen"
    assert zeile.show.pult.programmer.effekte[0]["art"] == "kreis"


def test_leeren_erst_auswahl_dann_programmer(zeile):
    zeile.ausfuehren("Gerät 1 auf 50")
    zeile.ausfuehren("Leeren")
    assert zeile.show.pult.auswahl == [] and zeile.show.pult.programmer.werte
    zeile.ausfuehren("Clear")
    assert zeile.show.pult.programmer.ist_leer()


def test_speichern_und_go(zeile):
    zeile.sequenz = "Weihnachten"
    zeile.ausfuehren("Gruppe Farb Farbe Rot auf voll")
    assert "Cue 1" in zeile.ausfuehren("Speichern")
    zeile.ausfuehren("Farbe Blau")
    zeile.ausfuehren("Speichern Cue 1")
    sequenz = zeile.show.pult.sequenzen.lesen("Weihnachten")
    assert len(sequenz["cues"]) == 1 and sequenz["cues"][0]["werte"][0]["farbe"] == "blau"
    zeile.show.pult.executor(1).belegen(sequenz)
    assert "Cue 1" in zeile.ausfuehren("Go")


@pytest.mark.parametrize("text, teil", [
    ("Gerät 9", "gibt es nicht"), ("auf 80", "Zuerst Geräte"), ("Gerät 1 auf 300", "0 bis 100"),
    ("Farbe Lila-Blassblau", "gibt es nicht"), ("Tanzen", "Unbekannt"), ("", "Kein Befehl"),
    ("Gruppe", "fehlt ein Name"),
])
def test_verstaendliche_fehler(zeile, text, teil):
    with pytest.raises(BefehlsFehler, match=teil):
        zeile.ausfuehren(text)


def test_server(zeile):
    from fastapi.testclient import TestClient
    from lichtsteuerung.server import erstelle_app
    with TestClient(erstelle_app(zeile.show)) as client:
        assert client.post("/api/befehl", json={"text": "Gerät 4 bis 5"}).json()["status"]["auswahl"] == ["kopf-1", "kopf-2"]
        assert client.post("/api/befehl", json={"text": "Quatsch"}).status_code == 400
        assert client.post("/api/auswahl", json={"gruppe": "Farb-PARs", "art": "dazu"}).json()["auswahl"][-1] == "par-3"
        assert client.post("/api/programmer/werte", json={"werte": {"helligkeit": 0.4}}).status_code == 200
        assert zeile.show.pult.programmer.werte["par-1"]["helligkeit"] == 0.4
