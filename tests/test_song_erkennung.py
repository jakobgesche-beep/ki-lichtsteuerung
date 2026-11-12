"""Song-Erkennung: Welcher geprobte Song wird gespielt? Der erwartete startet von selbst, andere nur als Vorschlag."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.audio import erkennen, folgen
from lichtsteuerung.audio.quellen import ABTASTRATE
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show

DUR = [0, 2, 4, 5, 7, 9, 11]


def kunstsong(folge, grundton, tempo=120.0, takte=16, stille_s=1.0, seed=1):
    """Ein Song aus einer Akkordfolge (Stufen der Dur-Tonleiter), mit Bass, Schlag und Melodie."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / tempo
    t = np.arange(int(beat * ABTASTRATE)) / ABTASTRATE
    stuecke = [np.zeros(int(stille_s * ABTASTRATE), np.float32)]
    for takt in range(takte):
        stufe = folge[takt % len(folge)]
        noten = [grundton * 2 ** ((DUR[(stufe + i) % 7] + 12 * ((stufe + i) // 7)) / 12) for i in (0, 2, 4)]
        for schlag in range(4):
            x = sum(np.sin(2 * np.pi * f * t) for f in noten) * 0.12 * np.exp(-t * 2)
            x += 0.25 * np.sin(2 * np.pi * noten[0] / 2 * t) * np.exp(-t * 3)
            x += 0.1 * np.sin(2 * np.pi * noten[int(rng.integers(0, 3))] * 2 * t) * np.exp(-t * 4)
            x += (0.5 if schlag % 2 == 0 else 0.2) * np.sin(2 * np.pi * 55 * t) * np.exp(-t * 30)
            stuecke.append(x.astype(np.float32))
    stuecke.append(np.zeros(int(2 * ABTASTRATE), np.float32))
    return np.concatenate(stuecke)


SONGS = {
    "Eins": dict(folge=[0, 4, 5, 3], grundton=130.8),
    "Zwei": dict(folge=[5, 3, 0, 4], grundton=146.8, tempo=100.0),
    "Drei": dict(folge=[0, 3, 4, 4], grundton=110.0, tempo=140.0),
}
FREMD = dict(folge=[1, 4, 0, 5], grundton=123.5, tempo=112.0)


@pytest.fixture(scope="module")
def toene():
    return {name: kunstsong(**art) for name, art in SONGS.items()}


def einspielen(erkenner, ton, ab_s, dauer_s, aufruf):
    """Spielt Ton ab einer Stelle ein und ruft alle 0,5 s aufruf(t) auf. Gibt das erste Ergebnis zurück."""
    a0, letzte = int(ab_s * ABTASTRATE), 0.0
    for a in range(a0, min(len(ton), a0 + int(dauer_s * ABTASTRATE)) - 512, 512):
        t = (a - a0) / ABTASTRATE
        erkenner.hoeren(ton[a:a + 512], t)
        if t - letzte >= 0.5:
            letzte = t
            ergebnis = aufruf(t)
            if ergebnis:
                return t, ergebnis
    return None, None


def test_erkennt_den_richtigen_song_an_der_richtigen_stelle(toene):
    erkenner = erkennen.SongErkenner()
    for name, ton in toene.items():
        erkenner.referenz(name, folgen.merkmale_der_aufnahme(ton)[0])
    zeit, ergebnis = einspielen(erkenner, toene["Zwei"], 10.0, 16.0, erkenner.pruefen)
    assert ergebnis and ergebnis["name"] == "Zwei"
    assert abs(ergebnis["stelle"] - (10.0 + zeit)) < 1.0 and zeit < 13.0


def test_ein_fremder_song_oder_publikum_wird_nicht_erkannt(toene):
    erkenner = erkennen.SongErkenner()
    for name, ton in toene.items():
        erkenner.referenz(name, folgen.merkmale_der_aufnahme(ton)[0])
    _, ergebnis = einspielen(erkenner, kunstsong(**FREMD, seed=9), 2.0, 20.0, erkenner.pruefen)
    assert ergebnis is None
    erkenner.zuruecksetzen()
    rauschen = (np.random.default_rng(3).standard_normal(20 * ABTASTRATE) * 0.05).astype(np.float32)
    _, ergebnis = einspielen(erkenner, rauschen, 0.0, 20.0, erkenner.pruefen)
    assert ergebnis is None


@pytest.fixture
def show(tmp_path, toene):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    for name, ton in toene.items():
        s.proben.speichern(name, ton)
        s.show_aus_probe(name)
    s.song.erkennen_vorbereiten()
    return s


def test_erwarteter_song_startet_von_selbst_an_der_richtigen_stelle(show, toene):
    show.song.setlist_setzen(["Zwei", "Eins", "Drei"], "automatisch")
    assert show.song.erwartet() == "Zwei"
    zeit, ergebnis = einspielen(show.song.erkenner, toene["Zwei"], 8.0, 16.0, show.song.erkennen_takt)
    assert ergebnis["gestartet"] and show.song.name == "Zwei"
    assert abs(show.song.folger.stelle - (8.0 + zeit)) < 1.0         # dort, wo die Band gerade ist
    assert show.song.erwartet() == "Eins"


def test_unerwarteter_song_wird_nur_vorgeschlagen(show, toene):
    show.song.setlist_setzen(["Eins", "Zwei", "Drei"], "automatisch")
    zeit, ergebnis = einspielen(show.song.erkenner, toene["Drei"], 5.0, 16.0, show.song.erkennen_takt)
    assert ergebnis and not ergebnis["gestartet"] and show.song.folger is None
    assert show.song.erkennung_zustand()["vorschlag"]["name"] == "Drei"
    show.song.vorschlag_starten()
    assert show.song.name == "Drei" and show.song.vorschlag is None


def test_modus_aus_und_vorschlagen(show, toene):
    show.song.setlist_setzen(None, "aus")
    assert einspielen(show.song.erkenner, toene["Eins"], 5.0, 10.0, show.song.erkennen_takt) == (None, None)
    show.song.setlist_setzen(None, "vorschlagen")
    show.song.erkenner.zuruecksetzen()
    _, ergebnis = einspielen(show.song.erkenner, toene["Eins"], 5.0, 16.0, show.song.erkennen_takt)
    assert ergebnis and not ergebnis["gestartet"]                   # auch der erwartete nur als Vorschlag
    with pytest.raises(ValueError):
        show.song.setlist_setzen(None, "zaubern")


def test_setlist_ueber_den_server(show):
    with TestClient(erstelle_app(show)) as client:
        zustand = client.post("/api/setlist", json={"reihenfolge": ["Drei", "Eins"], "modus": "vorschlagen"}).json()
        assert zustand["setlist"] == ["Drei", "Eins", "Zwei"] and zustand["modus"] == "vorschlagen"
        assert client.post("/api/song/vorschlag").status_code == 400
        assert client.get("/api/show").status_code == 200
