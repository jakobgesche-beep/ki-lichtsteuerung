"""Generalprobe: Setlist mit veränderten Probe-Aufnahmen durchspielen und sagen, wo es unsicher ist."""
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten, generalprobe
from lichtsteuerung.audio import livefassung
from lichtsteuerung.audio.quellen import ABTASTRATE
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show
from test_song_erkennung import kunstsong


def zweiteiler(folge_a, folge_b, grundton, tempo, seed):
    """Ein Song mit zwei verschiedenen Teilen (Strophe, Refrain), damit es einen Teilwechsel gibt."""
    a = kunstsong(folge_a, grundton, tempo=tempo, takte=8, stille_s=2.0, seed=seed)[:-2 * ABTASTRATE]
    b = kunstsong(folge_b, grundton * 1.5, tempo=tempo, takte=8, stille_s=0.0, seed=seed + 1)
    return np.concatenate([a, b * 1.6]).astype(np.float32)


@pytest.fixture(scope="module")
def show(tmp_path_factory):
    wurzel = tmp_path_factory.mktemp("gp") / "d"
    daten.einrichten(wurzel)
    s = Show(daten.Pfade(wurzel, daten.PROJEKT / "catalog"))
    s.proben.speichern("Eins", zweiteiler([0, 4, 5, 3], [5, 3, 0, 4], 130.8, 120.0, 1))
    s.proben.speichern("Zwei", zweiteiler([0, 3, 4, 4], [1, 4, 0, 5], 110.0, 96.0, 7))
    for name in ("Eins", "Zwei"):
        s.show_aus_probe(name)
    return s


def test_live_fassung_kennt_ihre_stellen():
    ton = np.sin(2 * np.pi * 440 * np.arange(20 * ABTASTRATE) / ABTASTRATE).astype(np.float32) * 0.5
    fassung = livefassung.bauen(ton, 2.0, 18.0, tempo=1.05, vorlauf_s=3.0)
    assert fassung.probe_zeit(1.0) is None                         # davor spielt die Band nicht
    assert abs(fassung.probe_zeit(3.0 + 10.0) - (2.0 + 10.5)) < 1e-6
    assert abs(fassung.live_zeit(fassung.probe_zeit(7.0)) - 7.0) < 1e-6
    assert abs((fassung.musik_bis_s - fassung.musik_ab_s) - 16.0 / 1.05) < 0.1
    # Schneller gespielt, aber gleiche Tonhöhe
    stueck = fassung.ton[int(5 * ABTASTRATE):int(7 * ABTASTRATE)]
    spektrum = np.abs(np.fft.rfft(stueck))
    assert abs(np.argmax(spektrum) * ABTASTRATE / len(stueck) - 440) < 2


def test_bewerten():
    gut = {"titel": "wie live", "erkennung": {"ergebnis": "erkannt", "nach_s": 9.0},
           "teilwechsel": [{"teil": "Refrain C", "fehler_s": 0.2}]}
    knapp = {"titel": "schwierig", "erkennung": {"ergebnis": "nicht"},
             "teilwechsel": [{"teil": "Refrain C", "fehler_s": 2.1}]}
    weg = {"titel": "schwierig", "erkennung": {"ergebnis": "verwechselt", "mit": "Zwei", "nach_s": 8.0},
           "teilwechsel": [{"teil": "Refrain C", "fehler_s": None}]}
    assert generalprobe.erkennung_bewerten([gut, gut])["stufe"] == "ok"
    spaet = {**gut, "erkennung": {"ergebnis": "erkannt", "nach_s": 22.0}}
    assert "spät" in generalprobe.erkennung_bewerten([gut, spaet])["text"]
    assert generalprobe.erkennung_bewerten([gut, knapp])["stufe"] == "hinweis"
    assert "Zwei" in generalprobe.erkennung_bewerten([gut, weg])["text"]
    assert generalprobe.erkennung_bewerten([gut, weg])["stufe"] == "problem"
    assert generalprobe.licht_bewerten([gut])["stufe"] == "ok"
    assert generalprobe.licht_bewerten([gut, knapp])["stufe"] == "hinweis"
    assert "zu spät" in generalprobe.licht_bewerten([gut, knapp])["text"]
    assert generalprobe.licht_bewerten([gut, weg])["stufe"] == "problem"


def test_ganze_generalprobe_mit_ergebnis_und_konzert_check(show):
    gp = show.generalprobe
    assert generalprobe.check_punkt(gp)[1].startswith("Noch keine Generalprobe")
    ergebnis = gp._alles(show.song.setlist(frisch=True))
    assert [s["name"] for s in ergebnis["songs"]] == ["Eins", "Zwei"]
    for song in ergebnis["songs"]:
        assert song["stufe"] in generalprobe.STUFEN and len(song["laeufe"]) == len(generalprobe.DURCHLAEUFE)
        assert song["laeufe"][0]["teilwechsel"], "der Teilwechsel wird gemessen"
        assert song["erkennung"]["text"] and song["licht"]["text"]
    assert ergebnis["rechnen_faktor"] > 0
    # Speichern und im Konzert-Check zeigen
    gp.ergebnis = ergebnis
    daten.schreibe_json(gp.pfad, ergebnis)
    assert generalprobe.Generalprobe(show).ergebnis["zeit"] == ergebnis["zeit"]
    assert gp.veraltet() == []
    stufe, text = generalprobe.check_punkt(gp)
    assert "Generalprobe" in text and stufe in generalprobe.STUFEN
    # Eine Aufnahme ändert sich: Die Generalprobe ist veraltet
    ergebnis["stand"]["Eins"] -= 100.0
    assert gp.veraltet() == ["Eins"]
    assert "Nochmal" in generalprobe.check_punkt(gp)[1]


def test_nicht_waehrend_eines_songs_und_abbrechen(show):
    gp = show.generalprobe
    show.song.starten("Eins", jetzt=time.monotonic())
    try:
        with pytest.raises(ValueError, match="läuft ein Song"):
            gp.starten()
    finally:
        show.song.stoppen()
    gp.starten()
    show.song.starten("Zwei", jetzt=time.monotonic())        # das Konzert hat Vorrang
    try:
        gp._faden.join(timeout=60)
        assert not gp.laeuft and "Song gestartet" in gp.fehler
    finally:
        show.song.stoppen()
    gp.starten()
    gp.abbrechen()
    gp._faden.join(timeout=60)
    assert gp.fehler == "Abgebrochen."


def test_ueber_den_server(show):
    with TestClient(erstelle_app(show)) as client:
        zustand = client.get("/api/generalprobe").json()
        assert zustand["dauer_schaetzung_s"] > 0 and not zustand["laeuft"]
        assert client.post("/api/generalprobe/start").json()["laeuft"]
        assert client.post("/api/generalprobe/start").status_code == 400      # läuft schon
        client.post("/api/generalprobe/stopp")
        show.generalprobe._faden.join(timeout=60)
        assert not client.get("/api/generalprobe").json()["laeuft"]
        punkte = client.get("/api/check").json()["punkte"]
        assert any(p["thema"] == "Generalprobe" for p in punkte)
