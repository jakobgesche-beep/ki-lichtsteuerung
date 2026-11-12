"""MIDI: Controller-Belegung mit Lernen und Fangen, fertige Vorlagen, Takt vom MIDI-Clock (ohne echtes Gerät)."""
import time

import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten, midi
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.automatik_an = False
    return s


def cc(nummer, wert, kanal=1):
    return [0xB0 + kanal - 1, nummer, wert]


def note(nummer, an=True, kanal=1):
    return [0x90 + kanal - 1, nummer, 100 if an else 0]


def test_lernen_und_tasten(show):
    m = show.midi
    m.lernen_starten("blackout")
    m.verarbeiten(note(5), 1.0)
    assert m.belegung == {"note:1:5": "blackout"} and m.lernen is None
    m.verarbeiten(note(5, an=False), 1.1)                 # Loslassen tut nichts
    assert not show.overrides.blackout
    m.verarbeiten(note(5), 2.0)
    assert show.overrides.blackout
    m.verarbeiten(note(5), 3.0)
    assert not show.overrides.blackout
    # Halte-Taste: an beim Drücken, aus beim Loslassen
    m.lernen_starten("halten:flash")
    m.verarbeiten(note(7), 4.0)
    m.verarbeiten(note(7), 4.5)
    assert show.pult.halten.get("flash")
    m.verarbeiten(note(7, an=False), 5.0)
    assert not show.pult.halten.get("flash")
    # Look-Taste, und gespeichert in cues/midi.json
    m.lernen_starten("look:ballade")
    m.verarbeiten(note(9), 6.0)
    m.verarbeiten(note(9), 6.1)
    assert show.pult.look == "ballade"
    assert midi.Midi(show).belegung["note:1:9"] == "look:ballade"
    with pytest.raises(ValueError):
        m.lernen_starten("quatsch")


def test_fader_faengt_erst_am_wert_der_software(show):
    m = show.midi
    m.lernen_starten("grand")
    m.verarbeiten(cc(48, 10), 0.0)
    assert show.pult.grand == 1.0                          # Lernen bewegt nichts
    m.verarbeiten(cc(48, 20), 0.1)
    assert show.pult.grand == 1.0                          # weit weg: fängt noch nicht
    m.verarbeiten(cc(48, 127), 0.2)                        # am Wert vorbei (ganz oben): gefangen
    m.verarbeiten(cc(48, 64), 0.3)
    assert abs(show.pult.grand - 64 / 127) < 1e-6
    show.pult.grand_setzen(0.2, 0.4)                       # jemand schiebt mit der Maus
    m.verarbeiten(cc(48, 70), 0.5)
    assert show.pult.grand == 0.2                          # der echte Fader muss erst wieder fangen
    m.verarbeiten(cc(48, 20), 0.6)
    assert abs(show.pult.grand - 20 / 127) < 1e-6


def test_fader_der_aktuellen_seite(show):
    m = show.midi
    m.vorlage_laden("apc_mini")
    show.pult.executor(1).fader, show.pult.executor(11).fader = 0.0, 0.0
    m.verarbeiten(cc(48, 0, kanal=3), 0.0)                 # Vorlagen gelten auf jedem Kanal
    m.verarbeiten(cc(48, 100, kanal=3), 0.1)
    assert abs(show.pult.executor(1).fader - 100 / 127) < 1e-6
    m.verarbeiten(note(84), 0.2)                           # Seite weiter (APC mini mk1, rechts)
    assert show.pult.seite == 2
    m.verarbeiten(cc(48, 90), 0.3)                         # Seite 2: Fader 11 steht auf 0, fängt erst dort
    assert show.pult.executor(11).fader == 0.0
    m.verarbeiten(cc(48, 0), 0.4)
    m.verarbeiten(cc(48, 50), 0.5)
    assert abs(show.pult.executor(11).fader - 50 / 127) < 1e-6
    assert abs(show.pult.executor(1).fader - 100 / 127) < 1e-6


def test_midi_clock_gibt_tempo_und_schlaege(show):
    m = show.midi
    beginn = time.monotonic() - 2.0
    m.verarbeiten([0xFA], beginn)
    takt = 60.0 / 128.0 / 24
    schlaege = 0
    for i in range(24 * 3):
        m.verarbeiten([0xF8], beginn + 1.0 + i * takt)
        schlaege += m.clock.beat_abholen()
    assert schlaege == 3
    assert m.clock.bpm(beginn + 1.0 + 71 * takt) == pytest.approx(128.0, abs=0.2)
    # In der Show: Das Tempo kommt jetzt vom Clock (vor Song und Ton), Tap geht trotzdem vor
    m.clock.ticks = type(m.clock.ticks)([time.monotonic() - 1.0 + i * takt for i in range(48)], maxlen=49)
    assert show._musik_bpm() == pytest.approx(128.0, abs=0.2)
    m.clock_setzen(False)
    assert show._musik_bpm() != pytest.approx(128.0, abs=0.2)


def test_ueber_den_server(show):
    with TestClient(erstelle_app(show)) as client:
        zustand = client.get("/api/midi").json()
        assert zustand["verfuegbar"] and any(a["schluessel"] == "fader:1" for a in zustand["aufgaben"])
        assert client.post("/api/midi/lernen", json={"aufgabe": "quatsch"}).status_code == 400
        assert client.post("/api/midi/lernen", json={"aufgabe": "tap"}).json()["lernen"] == "tap"
        assert client.post("/api/midi/lernen", json={"aufgabe": None}).json()["lernen"] is None
        belegung = client.post("/api/midi/vorlage", json={"id": "nanokontrol2"}).json()["belegung"]
        assert any(b["aufgabe"] == "fader:1" for b in belegung)
        assert client.post("/api/midi/loeschen", json={"alles": True}).json()["belegung"] == []
        assert client.post("/api/midi/clock", json={"an": False}).json()["clock"]["an"] is False
