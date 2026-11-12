"""Mehrere Aufnahmen pro Song: Mitschnitte und weitere Proben helfen der Song-Erkennung."""
import io
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten, weitere
from lichtsteuerung.audio import erkennen, folgen, livefassung
from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show
from test_generalprobe import zweiteiler
from test_song_erkennung import einspielen, kunstsong


@pytest.fixture(scope="module")
def song():
    return zweiteiler([0, 4, 5, 3], [5, 3, 0, 4], 130.8, 120.0, 1)


@pytest.fixture
def show(tmp_path, song):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.automatik_an = False
    s.proben.speichern("Eins", song)
    s.show_aus_probe("Eins")
    return s


def test_zuordnen_findet_die_stellen_der_probe(song):
    merkmale, pegel = folgen.merkmale_der_aufnahme(song)
    anfang = folgen.musik_anfang(pegel) / folgen.RATE
    live = livefassung.bauen(song, anfang, len(song) / ABTASTRATE, tempo=1.04, vorlauf_s=3.0)
    ergebnis = weitere.zuordnen(merkmale, pegel, live.ton)
    assert ergebnis["sicher"] >= 0.6 and len(ergebnis["zuordnung"]) > 20
    fehler = [abs(probe - live.probe_zeit(t)) for t, probe in ergebnis["zuordnung"] if live.probe_zeit(t) is not None]
    assert np.median(fehler) < 0.3


def test_ablage_mit_grenzen(tmp_path, song):
    ablage = weitere.WeitereAufnahmen(tmp_path)
    for _ in range(3):
        ablage.speichern("Eins", song, "Mitschnitt")
        time.sleep(1.05)                                  # eigener Dateiname (Sekunde)
    liste = ablage.liste("Eins")
    assert len(liste) == weitere.MAX_MITSCHNITTE and all(e["zuordnung"] is None for e in liste)
    assert all(ablage.ton_pfad("Eins", e["datei"]).is_file() for e in liste)
    datei = liste[0]["datei"]
    assert ablage.zuordnung_setzen("Eins", datei, {"sicher": 0.3, "zuordnung": [[0, 0]] * 30}) is None
    assert [e["datei"] for e in ablage.liste("Eins")] == [liste[1]["datei"]]       # passt nicht: weg
    eintrag = ablage.zuordnung_setzen("Eins", liste[1]["datei"], {"sicher": 0.9, "zuordnung": [[i, i] for i in range(30)]})
    assert eintrag["sicher"] == 0.9 and len(ablage.fuer_erkennung("Eins")) == 1
    with pytest.raises(ValueError):
        ablage.ton_pfad("Eins", "../../geheim.flac")
    with pytest.raises(ValueError):
        ablage.speichern("Eins", song[: ABTASTRATE * 5], "Datei")             # zu kurz


def test_erkennung_rechnet_die_stelle_der_weiteren_aufnahme_in_die_probe_um():
    probe = kunstsong([0, 4, 5, 3], 130.8, takte=16)
    anders = kunstsong([1, 4, 0, 5], 123.5, tempo=112.0, takte=20, seed=4)    # klingt ganz anders als die Probe
    erkenner = erkennen.SongErkenner()
    erkenner.referenz("Eins", folgen.merkmale_der_aufnahme(probe)[0])
    _, ergebnis = einspielen(erkenner, anders, 2.0, 20.0, erkenner.pruefen)
    assert ergebnis is None                               # ohne die weitere Aufnahme: nichts
    # Die weitere Aufnahme "anders" gehört zu Sekunde 100 bis 145 der Probe (zum Beispiel ein Solo live)
    zuordnung = [[t, 100.0 + t] for t in np.arange(0.0, 45.0, 0.5)]
    erkenner.weitere_setzen("Eins", [(folgen.merkmale_der_aufnahme(anders)[0], zuordnung)])
    erkenner.zuruecksetzen()
    zeit, ergebnis = einspielen(erkenner, anders, 2.0, 20.0, erkenner.pruefen)
    assert ergebnis is not None and ergebnis["name"] == "Eins"
    assert abs(ergebnis["stelle"] - (100.0 + 2.0 + zeit)) < 1.0


def test_mitschnitt_beim_konzert_und_zuordnen_wenn_ruhig(show, song, monkeypatch):
    monkeypatch.setattr(weitere, "RUHE_S", 0.0)
    m = show.mitschnitt
    show.song.starten("Eins", jetzt=0.0)
    show.baue_bild(0.0)
    assert m.song == "Eins"
    for a in range(0, len(song) - BLOCK, BLOCK):
        m._hoeren(song[a:a + BLOCK], a / ABTASTRATE)
    show.song.stoppen(50.0)
    show.baue_bild(50.0)
    assert m.song is None
    for _ in range(100):
        if show.proben.weitere.liste("Eins"):
            break
        time.sleep(0.05)
    assert show.proben.weitere.liste("Eins")[0]["quelle"] == "Mitschnitt"
    show.baue_bild(80.0)                                  # Ruhe: jetzt wird zugeordnet
    m._arbeiter.join(timeout=120)
    eintrag = show.proben.weitere.liste("Eins")[0]
    assert eintrag["sicher"] >= 0.6
    show.song.erkennen_vorbereiten()
    assert len(show.song.erkenner.weitere["Eins"]) == 1
    arten = [e.get("ergebnis", "") for e in show.rueckblick.lesen(show.rueckblick.tage()[0]) if e["art"] == "mitschnitt"]
    assert arten[0] == "aufgenommen" and arten[1].startswith("übernommen")


def test_mitschnitt_abschaltbar(show):
    show.song.setlist_setzen(mitschnitt=False)
    show.song.starten("Eins", jetzt=0.0)
    show.baue_bild(0.0)
    assert show.mitschnitt.song is None and show.song.erkennung_zustand()["mitschnitt"] is False


def test_ueber_den_server(show, song):
    import soundfile
    puffer = io.BytesIO()
    soundfile.write(puffer, song, ABTASTRATE, format="WAV")
    with TestClient(erstelle_app(show)) as client:
        antwort = client.post("/api/proben/Eins/weitere", params={"datei": "handy.wav"}, content=puffer.getvalue())
        assert antwort.status_code == 200 and antwort.json()["weitere"]["quelle"] == "Datei"
        probe = client.get("/api/proben").json()["proben"][0]
        assert probe["weitere"][0]["zugeordnet"] is False and "zuordnung" not in probe["weitere"][0]
        assert client.post("/api/proben/Gibtsnicht/weitere", params={"datei": "x.wav"}, content=b"1").status_code == 400
        datei = probe["weitere"][0]["datei"]
        assert client.delete(f"/api/proben/Eins/weitere/{datei}").json()["weitere"] == 0
        assert client.post("/api/proben/aufnahme", json={"name": "Gibtsnicht", "weitere": True}).status_code == 400
    show.proben.loeschen("Eins")
    assert not (show.proben.weitere.ordner / "eins").exists()
