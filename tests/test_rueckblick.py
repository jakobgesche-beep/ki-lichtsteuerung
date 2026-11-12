"""Rückblick: Logbuch der Show mit Zusammenfassung und Hinweisen zum Üben."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten, rueckblick
from lichtsteuerung.audio.analyse import Messwerte
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show
from test_song_erkennung import kunstsong


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.automatik_an = False
    s.proben.speichern("Eins", kunstsong([0, 4, 5, 3], 130.8, takte=24))
    s.show_aus_probe("Eins")
    return s


def laufen(show, von, bis, messwerte=None):
    show.audio.abholen = lambda jetzt=None: messwerte
    for t in np.arange(von, bis, 0.05):
        show.baue_bild(float(t))


def test_song_mit_korrektur_und_ende_steht_im_logbuch(show):
    show.song.starten("Eins", jetzt=0.0, stelle=5.0)
    laufen(show, 0.0, 3.0)
    show.song.teil_vor()
    show.song.teil_zurueck()
    laufen(show, 3.0, 6.0)
    show.pult.look_druecken("ballade", 6.0)
    laufen(show, 6.0, 7.0)
    show.song.stoppen(7.0)
    laufen(show, 7.0, 8.0)
    ereignisse = show.rueckblick.lesen(show.rueckblick.tage()[0])
    arten = [e["art"] for e in ereignisse]
    assert arten[0] == "start" and ereignisse[0]["wie"] == "hand"
    assert arten.count("korrektur") == 2 and "look" in arten
    ende = [e for e in ereignisse if e["art"] == "ende"][0]
    assert ende["wie"] == "stopp" and ende["song"] == "Eins" and sum(ende["korrekturen"].values()) == 2
    zusammen = show.rueckblick.zusammenfassung()
    assert zusammen["songs"][0]["song"] == "Eins" and zusammen["songs"][0]["wie"] == "von Hand"
    assert any("Nächster Teil" in e["text"] for e in zusammen["ereignisse"])


def test_hinweise_zum_ueben(show, tmp_path):
    r = rueckblick.Rueckblick(show, tmp_path / "logbuch")
    zeilen = [{"zeit": "20:01:00", "art": "start", "song": "Hh", "wie": "erkannt"},
              {"zeit": "20:05:00", "art": "ende", "song": "Hh", "wie": "applaus", "start_wie": "erkannt", "dauer_s": 240,
               "sicher": 0.4, "ohne_ton": 0.0, "unsicher_in": ["Refrain C"], "korrekturen": {"Refrain C": 3}},
              {"zeit": "20:06:00", "art": "ton_weg", "eingang": "Eingang 1"},
              {"zeit": "20:06:"}, ]
    (tmp_path / "logbuch").mkdir()
    (tmp_path / "logbuch" / "2026-11-12.jsonl").write_text(
        "\n".join(json.dumps(z) for z in zeilen) + "\n{kaputt", encoding="utf-8")
    zusammen = r.zusammenfassung("2026-11-12")
    text = " ".join(zusammen["hinweise"])
    assert "unsicher" in text and "Refrain C" in text and "3-mal" in text and "Ton war 1-mal weg" in text
    assert zusammen["songs"][0]["ende"] == "Applaus am Schluss"
    with pytest.raises(ValueError):
        r.zusammenfassung("../../etc")


def test_applaus_und_technik(show):
    dauer = show.song.songs()[0]["dauer_s"]
    show.song.starten("Eins", jetzt=0.0, stelle=dauer - 3.0)
    laufen(show, 0.0, 6.0, Messwerte(leise=False, applaus=True, energie=0.3))
    arten = [e["art"] for e in show.rueckblick.lesen(show.rueckblick.tage()[0])]
    assert "ende" in arten and "applaus" in arten


def test_ueber_den_server(show):
    show.rueckblick.ereignis("programm", version="2.2.0")
    with TestClient(erstelle_app(show)) as client:
        antwort = client.get("/api/rueckblick").json()
        assert antwort["tage"] and antwort["ereignisse"][0]["text"].startswith("Programm gestartet")
        assert client.get("/api/rueckblick", params={"tag": "quatsch"}).status_code == 400
