"""Show-Tasten, Halten, Tap-Tempo, Song-Start und Song-Folger."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.audio import folgen, songanalyse
from lichtsteuerung.audio.quellen import ABTASTRATE, erzeuge_takt
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    return Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))


def spots(show):
    return [g["id"] for g in show.patch.in_gruppe("Spots")]


def bild(show, jetzt):
    show.baue_bild(jetzt)
    return show.simulator.lies(show.letztes_bild)


def test_look_taste_setzt_look_und_aus_gibt_zurueck(show):
    show.pult.farben_setzen("gruen", "lila", 0.0)
    show.pult.look_druecken("strophe", 0.0)
    for t in np.arange(0.0, 3.0, 0.025):
        show.baue_bild(t)
    zustand = show.pult.anwenden({}, 3.0, 120.0)
    farben = {zustand[i].farbe for i in spots(show) if i in zustand}
    assert farben == {(0.0, 1.0, 0.0)}                     # Farbe 1 = grün auf den Spots
    assert show.pult.status()["tasten"]["look"] == "strophe"
    show.pult.look_aus(3.0)
    assert show.pult.status()["tasten"]["look"] is None


def test_alle_look_tasten_sind_gueltig_und_sicher(show):
    from lichtsteuerung import showtasten
    from lichtsteuerung.pult import pruefe_cue
    for look in showtasten.LOOKS:
        cue = showtasten.look_bauen(look["id"], show.patch, "rot", "blau", show.gobos_der_gruppe("Spots"), show.positionen)
        assert pruefe_cue(cue, show.patch, show.positionen) == [], look["id"]
        show.pult.look_druecken(look["id"], 0.0)
        for t in np.arange(0.0, 2.0, 0.05):
            show.baue_bild(t)                              # die Prüfung läuft bei jedem Bild mit


def test_farbwechsel_nimmt_den_laufenden_look_mit(show):
    show.pult.look_druecken("ruhig", 0.0)
    show.pult.farben_setzen(None, "pink", 0.5)
    assert show.pult.tasten.sequenz["cues"][0]["werte"][0]["farbe"] == "pink"   # ruhig = Farbe 2


def test_halten_flash_strobo_dunkel_und_notaus_hat_vorrang(show):
    show.pult.halten_setzen("flash", True, 0.0)
    zustand = show.pult.anwenden({}, 0.1, 120.0)
    assert all(zustand[i].helligkeit == 1.0 and zustand[i].farbe == (1.0, 1.0, 1.0) for i in spots(show))
    show.overrides.blackout = True
    show.baue_bild(0.2)
    licht = set(spots(show)) | {g["id"] for g in show.patch.in_gruppe("Farb-PARs")}
    assert all(g["hell"] == 0 for g in show.simulator.lies(show.letztes_bild) if g["id"] in licht)   # Blackout schlägt jede Taste
    show.overrides.blackout = False
    show.pult.halten_setzen("flash", False, 0.3)
    show.pult.halten_setzen("dunkel", True, 0.3)
    zustand = show.pult.anwenden({}, 0.4, 120.0)
    assert all(e.helligkeit == 0.0 for e in zustand.values())


def test_haengende_halte_taste_geht_von_selbst_aus(show):
    show.pult.halten_setzen("flash", True, 0.0)
    show.pult.anwenden({}, 25.0, 120.0)
    assert show.pult.status()["tasten"]["halten"]["flash"] is False


def test_tap_tempo_und_ohne_ton_bleibt_das_tempo(show):
    for t in (0.0, 0.5, 1.0, 1.5):
        show.pult.tap(t)
    assert show.pult.tempo_getippt == pytest.approx(120.0)
    assert show._musik_bpm() == pytest.approx(120.0)
    show.pult.tempo_quelle = "ton"
    show._letztes_tempo = 95.0                             # kein Ton mehr: das zuletzt gehörte Tempo bleibt
    assert show._musik_bpm() == pytest.approx(95.0)


def test_effekte_rasten_auf_den_beat_ein(show):
    effekte = show.pult.effekte
    effekte.musik_beats = 10.3
    for _ in range(20):
        effekte.takt(0.0, 120.0, beat=True)
    assert abs(effekte.musik_beats - 10.0) < 0.01


def bandsong():
    """Leise, laut, leise, laut: vier deutlich verschiedene Teile, 120 BPM."""
    rng = np.random.default_rng(5)
    teile = []
    for laut, rauschen in ((0.1, 0.0), (0.8, 0.1), (0.15, 0.0), (0.8, 0.1)):
        ton = erzeuge_takt(120, 16) * laut
        teile.append(ton + (rng.standard_normal(len(ton)) * rauschen).astype("float32"))
    return np.concatenate([np.zeros(ABTASTRATE, np.float32)] + teile)


def test_song_start_laeuft_ohne_ton_von_selbst_durch(show):
    show.proben.speichern("Band", bandsong())
    show.show_aus_probe("Band")
    songs = show.song.songs()
    assert [s["name"] for s in songs] == ["Band"] and len(songs[0]["teile"]) >= 3
    show.song.starten("Band", 1, jetzt=0.0)
    executor = show.pult.executor(1)
    gesehen = []
    for t in np.arange(0.0, 60.0, 0.05):
        show.baue_bild(float(t))
        if executor.index not in gesehen:
            gesehen.append(executor.index)
    assert len(gesehen) >= 3 and gesehen == sorted(gesehen)     # die Teile kommen von selbst, der Reihe nach
    zustand = show.song.zustand(60.0)
    assert zustand["laeuft"] and zustand["folger"]["art"] == "uhr" and zustand["jetzt"]["rest_s"] >= 0
    assert zustand["naechster"] is None or zustand["naechster"]["name"]


def test_song_korrigieren_go_und_stopp(show):
    show.proben.speichern("Band", bandsong())
    show.show_aus_probe("Band")
    show.song.starten("Band", 2, jetzt=0.0)
    show.baue_bild(0.0)
    teil_vorher = show.song.zustand(0.0)["teil"]
    show.pult.go(2, 0.1)                                   # Go+ im Song-Modus: nächster Teil jetzt
    show.baue_bild(0.15)
    assert show.song.zustand(0.15)["teil"] == teil_vorher + 1
    show.pult.go(2, 0.2, -1)                               # Go-: zurück
    show.baue_bild(0.25)
    assert show.song.zustand(0.25)["teil"] == teil_vorher
    show.song.stoppen(0.3)
    assert not show.song.zustand()["laeuft"] and show.pult.executor(2).index == -1


def test_song_ueber_den_server(show):
    show.proben.speichern("Band", bandsong())
    show.show_aus_probe("Band")
    client = TestClient(erstelle_app(show))
    daten_ = client.get("/api/show").json()
    assert daten_["songs"][0]["name"] == "Band" and len(daten_["looks"]) == 9
    assert daten_["songs"][0]["alte_analyse"] is False
    assert client.post("/api/song/start", json={"name": "Band"}).json()["laeuft"]
    assert client.post("/api/song/vor").status_code == 200
    assert client.post("/api/look/refrain").status_code == 200
    assert client.post("/api/halten/strobo", json={"an": True}).json()["tasten"]["halten"]["strobo"]
    assert client.post("/api/halten/strobo", json={"an": False}).status_code == 200
    assert client.post("/api/farben", json={"farbe_1": "orange"}).json()["tasten"]["farbe_1"] == "orange"
    assert client.post("/api/farben", json={"farbe_1": "kariert"}).status_code == 400
    assert client.post("/api/song/stopp").json() == {"laeuft": False}
    assert client.post("/api/song/start", json={"name": "Gibt es nicht"}).status_code == 400


def akkordsong():
    """Vier Akkorde im Wechsel, mit Takt: so etwas hört der Folger wirklich."""
    t = np.arange(int(2.0 * ABTASTRATE)) / ABTASTRATE
    stuecke = [np.zeros(ABTASTRATE)]
    for runde in range(8):
        for grund in (220.0, 196.0, 174.6, 261.6):
            akkord = sum(np.sin(2 * np.pi * grund * f * t) for f in (1.0, 1.26, 1.5)) * np.exp(-t * 1.5) * 0.2
            stuecke.append(akkord + erzeuge_takt(120, 2.0)[: len(t)] * 0.3 * (runde % 2 + 0.5))
    return np.concatenate(stuecke).astype(np.float32)


def test_folger_folgt_der_eigenen_aufnahme(tmp_path):
    ton = akkordsong()
    merkmale, pegel = folgen.merkmale_der_aufnahme(ton)
    folger = folgen.SongFolger(merkmale, pegel)
    start = folger.anfang
    assert abs(start - 1.0) < 0.3                          # die Stille vor der Band zählt nicht
    folger.starten()
    fehler = []
    a0 = int(start * ABTASTRATE)
    for a in range(a0, len(ton) - 512, 512):
        t = (a - a0) / ABTASTRATE
        folger.hoeren(ton[a:a + 512], t)
        stelle = folger.takt(512 / ABTASTRATE, t)
        if t > 5:
            fehler.append(abs(stelle - (start + t)))
    assert np.median(fehler) < 0.5


def test_folger_ohne_ton_laeuft_wie_eine_uhr():
    merkmale, pegel = folgen.merkmale_der_aufnahme(bandsong())
    folger = folgen.SongFolger(merkmale, pegel)
    folger.starten(10.0)
    for i in range(100):
        stelle = folger.takt(0.1, i * 0.1)
    assert stelle == pytest.approx(20.0, abs=0.2)
    assert folger.zustand(10.0)["art"] == "uhr"


def test_songanalyse_tempo_beats_und_takte():
    ergebnis = songanalyse.analysieren(np.concatenate([np.zeros(ABTASTRATE, np.float32), erzeuge_takt(128, 40)]))
    assert ergebnis["tempo_bpm"] == pytest.approx(128, rel=0.02)
    beats = np.array(ergebnis["beats_s"])
    assert beats[0] > 0.8                                  # kein Raster in der Stille davor
    assert np.std(np.diff(beats)) < 0.02
    assert len(ergebnis["einsen_s"]) == pytest.approx(len(beats) / 4, abs=1)
