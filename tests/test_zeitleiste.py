"""Zeitleiste mit Wellenform: Teilgrenzen ziehen, Akzente abschalten, verschieben, setzen."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.probe import akzent_aendern, akzente_alle, akzente_im_teil, schlaege_im_teil, teile_aendern
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


def analyse():
    return {"name": "Song", "tempo_bpm": 120, "dauer_s": 40.0, "version": 3,
            "einsen_s": [float(x) for x in range(0, 40, 2)], "markiert_s": [12.0], "drops_s": [],
            "schlaege_s": [22.0, 30.0],
            "teile": [{"start": 0.0, "ende": 10.0, "name": "Intro", "gruppe": "A", "klasse": "ruhig"},
                      {"start": 10.0, "ende": 20.0, "name": "Strophe", "gruppe": "B", "klasse": "mittel"},
                      {"start": 20.0, "ende": 40.0, "name": "Refrain", "gruppe": "C", "klasse": "stark"}]}


def test_grenze_ziehen_landet_auf_der_takt_eins():
    neu = teile_aendern(analyse(), "grenze", 2, 23.3)
    assert neu["teile"][2]["start"] == 24.0 and neu["teile"][1]["ende"] == 24.0
    with pytest.raises(ValueError):
        teile_aendern(analyse(), "grenze", 2, 9.0)        # Strophe wäre leer
    with pytest.raises(ValueError):
        teile_aendern(analyse(), "grenze", 0, 3.0)


def test_akzente_aus_an_verschieben_neu():
    a = analyse()
    refrain = a["teile"][2]
    assert schlaege_im_teil(a, refrain, "stark") == [22.0, 30.0]
    a = akzent_aendern(a, "aus", 22.05)
    assert schlaege_im_teil(a, refrain, "stark") == [30.0]
    assert [x["aus"] for x in akzente_alle(a) if x["art"] == "schlag"] == [True, False]
    a = akzent_aendern(a, "an", 22.0)
    assert schlaege_im_teil(a, refrain, "stark") == [22.0, 30.0]
    a = akzent_aendern(a, "verschieben", 30.0, 31.5)                  # erkannter Schlag: alt aus, neu von Hand
    assert schlaege_im_teil(a, refrain, "stark") == [22.0, 31.5]
    a = akzent_aendern(a, "verschieben", 31.5, 33.0)                  # von Hand gesetzter: wird nur verschoben
    assert schlaege_im_teil(a, refrain, "stark") == [22.0, 33.0]
    assert len(a["akzente_extra"]) == 1
    a = akzent_aendern(a, "neu", 15.0, art="akzent")
    assert akzente_im_teil(a, a["teile"][1]) == [12.0, 15.0]
    a = akzent_aendern(a, "weg", 15.0)
    assert akzente_im_teil(a, a["teile"][1]) == [12.0]
    with pytest.raises(ValueError):
        akzent_aendern(a, "weg", 12.0)                                # erkannte/markierte: nur ausschalten
    with pytest.raises(ValueError):
        akzent_aendern(a, "neu", 99.0)
    # Von Hand gesetzte Schläge gehen auch in ruhigen Teilen
    a = akzent_aendern(a, "neu", 5.0, art="schlag")
    assert schlaege_im_teil(a, a["teile"][0], "ruhig") == [5.0]


def test_ueber_den_server_mit_show(tmp_path):
    from lichtsteuerung.audio.quellen import ABTASTRATE, erzeuge_takt
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    ton = np.concatenate([np.zeros(ABTASTRATE, np.float32)] + [erzeuge_takt(120, 16) * l for l in (0.1, 0.8, 0.15, 0.8)])
    show.proben.speichern("Band", ton.astype(np.float32))
    with TestClient(erstelle_app(show)) as client:
        welle = client.get("/api/proben/Band/welle").json()
        assert len(welle["punkte"]) == 1200 and 0 <= min(welle["punkte"]) and max(welle["punkte"]) <= 1
        probe = client.get("/api/proben").json()["proben"][0]
        assert "akzente" in probe
        antwort = client.post("/api/proben/Band/akzente", json={"aktion": "neu", "zeit": 20.0, "art": "schlag"}).json()
        assert any(a["zeit"] == 20.0 and a["quelle"] == "von Hand" for a in antwort["akzente"])
        sequenz = client.post("/api/proben/Band/neu").json()
        assert any(c["name"] == "Schlag" for c in sequenz["cues"])
        assert client.post("/api/proben/Band/akzente", json={"aktion": "quatsch", "zeit": 1}).status_code == 400
        assert client.get("/api/proben/Gibtsnicht/welle").status_code == 400


def test_aenderungen_waehrend_einer_neu_analyse_gehen_nicht_verloren(tmp_path):
    """Lange Neu-Analyse und gleichzeitig ein Akzent aus der Zeitleiste: Beides muss danach drin sein."""
    import threading
    from lichtsteuerung.audio.quellen import ABTASTRATE, erzeuge_takt
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    ton = np.concatenate([np.zeros(ABTASTRATE, np.float32)] + [erzeuge_takt(120, 16) * l for l in (0.1, 0.8, 0.15, 0.8)])
    show.proben.speichern("Band", ton.astype(np.float32))
    pfad = show.proben.ordner / "Band.json"
    alt = daten.lese_json(pfad)
    alt["version"] = 2                                   # alte Analyse: Die nächste Änderung rechnet erst neu
    alt["von_hand"] = True
    daten.schreibe_json(pfad, alt)
    faden = threading.Thread(target=show.proben.teile_aendern, args=("Band", "name", 0, "Solo"))
    faden.start()
    show.proben.akzent_aendern("Band", "neu", 20.0, art="schlag")
    faden.join()
    ergebnis = show.proben.lesen("Band")
    assert ergebnis["teile"][0]["name"] == "Solo" and ergebnis["akzente_extra"] == [{"zeit": 20.0, "art": "schlag"}]
