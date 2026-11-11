"""Songteile von Hand richtigstellen: Namen, Stärke, Grenzen auf Takt-Einsen, D-Marken als Grenzen."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.probe import teile_aendern
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


def analyse():
    return {"name": "Song", "tempo_bpm": 120, "dauer_s": 40.0, "version": 2,
            "einsen_s": [float(x) for x in range(0, 40, 2)], "markiert_s": [9.7, 25.2],
            "teile": [{"start": 0.0, "ende": 10.0, "name": "Intro", "gruppe": "A", "klasse": "ruhig", "takte": 5},
                      {"start": 10.0, "ende": 20.0, "name": "Strophe", "gruppe": "B", "klasse": "mittel", "takte": 5},
                      {"start": 20.0, "ende": 40.0, "name": "Refrain", "gruppe": "C", "klasse": "stark", "takte": 10}]}


def test_name_und_staerke():
    neu = teile_aendern(analyse(), "name", 1, "Solo")
    neu = teile_aendern(neu, "klasse", 1, "hoehepunkt")
    assert neu["teile"][1]["name"] == "Solo" and neu["teile"][1]["klasse"] == "hoehepunkt" and neu["von_hand"]
    with pytest.raises(ValueError):
        teile_aendern(neu, "klasse", 1, "laut")


def test_grenze_um_einen_takt_verschieben():
    neu = teile_aendern(analyse(), "verschieben", 1, -1)
    assert neu["teile"][1]["start"] == 8.0 and neu["teile"][0]["ende"] == 8.0
    assert neu["teile"][0]["takte"] == 4 and neu["teile"][1]["takte"] == 6
    with pytest.raises(ValueError):
        teile_aendern(analyse(), "verschieben", 0, 1)


def test_teilen_und_verbinden():
    neu = teile_aendern(analyse(), "teilen", 2)
    assert [t["start"] for t in neu["teile"]] == [0.0, 10.0, 20.0, 30.0]
    neu = teile_aendern(neu, "verbinden", 2)
    assert [(t["start"], t["ende"]) for t in neu["teile"]] == [(0.0, 10.0), (10.0, 20.0), (20.0, 40.0)]


def test_d_marken_werden_grenzen_auf_der_naechsten_eins():
    neu = teile_aendern(analyse(), "marken", 0)
    assert [t["start"] for t in neu["teile"]] == [0.0, 10.0, 26.0]
    assert [t["name"] for t in neu["teile"]] == ["Intro", "Strophe", "Refrain"]



def test_ueber_den_server_und_show_neu_bauen(tmp_path):
    import numpy as np
    from lichtsteuerung.audio.quellen import ABTASTRATE, erzeuge_takt
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    ton = np.concatenate([np.zeros(ABTASTRATE, np.float32)] + [erzeuge_takt(120, 16) * l for l in (0.1, 0.8, 0.15, 0.8)])
    show.proben.speichern("Band", ton.astype(np.float32), markierungen=[17.0, 33.0])
    with TestClient(erstelle_app(show)) as client:
        vorher = client.get("/api/proben").json()["proben"][0]
        antwort = client.post("/api/proben/Band/teile", json={"aktion": "name", "index": 0, "wert": "Solo"}).json()
        assert antwort["teile"][0]["name"] == "Solo" and antwort["von_hand"]
        assert client.post("/api/proben/Band/teile", json={"aktion": "quatsch", "index": 0}).status_code == 400
        sequenz = client.post("/api/proben/Band/neu").json()
        assert sequenz["song"]["teile"][0]["name"] == "Solo"
        assert show.proben.neu_analysieren("Band")["teile"][0]["name"] == "Solo"     # bleibt beim Neubauen
        assert len(vorher["teile"]) >= 1
