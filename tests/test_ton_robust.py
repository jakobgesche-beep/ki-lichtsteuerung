"""Ton-Eingang fürs Konzert: Abtastrate umrechnen, Geräteliste unter Windows, Abriss, nach Neustart wieder da."""
import time

import numpy as np
import pytest

from lichtsteuerung import daten
from lichtsteuerung.audio import quellen
from lichtsteuerung.audio.betrieb import AudioBetrieb
from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK, AudioFehler, Umrechner
from lichtsteuerung.show import Show


def test_umrechner_48k_auf_44k_genau_und_ohne_luecken():
    umrechner = Umrechner(48000)
    t = np.arange(96000) / 48000
    ton = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    raus = np.concatenate([umrechner(ton[i:i + 333]) for i in range(0, len(ton), 333)])
    assert abs(len(raus) - 2 * ABTASTRATE) <= 1
    erwartet = np.sin(2 * np.pi * 440 * np.arange(len(raus)) / ABTASTRATE)
    assert np.max(np.abs(raus - erwartet)) < 0.01


class FalschesSounddevice:
    """Wie unter Windows: jedes Gerät mehrmals, einmal pro Schnittstelle."""

    APIS = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]
    GERAETE = [
        {"name": "Microsoft Soundmapper - Input", "hostapi": 0, "max_input_channels": 2},
        {"name": "X-USB 1-2 (BEHRINGER X-USB)", "hostapi": 0, "max_input_channels": 2},
        {"name": "Mikrofon (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 2},
        {"name": "X-USB 1-2 (BEHRINGER X-USB)", "hostapi": 1, "max_input_channels": 2},
        {"name": "X-USB 1-2 (BEHRINGER X-USB)", "hostapi": 2, "max_input_channels": 2},
        {"name": "Mikrofon (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 2},
        {"name": "Lautsprecher (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 0},
        {"name": "X-USB 1-2 (BEHRINGER X-USB)", "hostapi": 3, "max_input_channels": 2},
    ]

    def query_hostapis(self, nummer=None):
        return self.APIS if nummer is None else self.APIS[nummer]

    def query_devices(self, *argumente):
        return self.GERAETE


def test_unter_windows_steht_jedes_geraet_nur_einmal_da(monkeypatch):
    monkeypatch.setattr(quellen, "_sounddevice", FalschesSounddevice)
    liste = quellen.eingaenge()
    namen = [(e["name"], e["api"]) for e in liste]
    assert ("X-USB 1-2 (BEHRINGER X-USB)", "Windows WASAPI") in namen
    assert ("Mikrofon (Realtek(R) Audio)", "Windows WASAPI") in namen
    assert sum(1 for n, _ in namen if n.startswith("X-USB")) == 1
    assert all(api != "Windows WDM-KS" for _, api in namen)
    assert quellen.geraet_suchen("X-USB 1-2 (BEHRINGER X-USB)", "Windows WASAPI") == 4


class Wackelquelle:
    """Liefert Ton, bis das Kabel "rausfällt". Danach öffnet neu_oeffnen() eine frische Quelle."""

    def __init__(self, bloecke_bis_abriss):
        self.rest = bloecke_bis_abriss
        self.geoeffnet = 0

    def lies(self):
        time.sleep(BLOCK / ABTASTRATE)
        if self.rest is not None:
            if self.rest <= 0:
                raise AudioFehler("Vom Audio-Eingang kommt nichts mehr.")
            self.rest -= 1
        return (np.random.default_rng(1).standard_normal(BLOCK) * 0.1).astype(np.float32)

    def neu_oeffnen(self):
        self.geoeffnet += 1
        if self.geoeffnet < 2:
            raise AudioFehler("Gerät noch nicht da")
        return Wackelquelle(None)

    def schliessen(self):
        pass


def test_abgerissener_eingang_kommt_von_selbst_wieder():
    betrieb = AudioBetrieb()
    betrieb.starten(Wackelquelle(20), "Eingang: X32")
    time.sleep(1.0)
    assert betrieb.fehler and "Ton weg" in betrieb.fehler
    assert betrieb.aktuell() is None                           # Rückfall: Grundlicht, nicht Blackout
    ende = time.monotonic() + 7
    while time.monotonic() < ende and betrieb.wieder_verbunden == 0:
        time.sleep(0.2)
    assert betrieb.wieder_verbunden == 1 and betrieb.fehler is None
    time.sleep(0.6)
    assert betrieb.aktuell() is not None
    betrieb.stoppen()


class FalscherEingang:
    def __init__(self, geraet=None, kanaele=(1,), name=None, api=None):
        self.geraet_name, self.api_name, self.kanaele = name or "X-USB 1-2", api or "Core Audio", kanaele

    def lies(self):
        time.sleep(BLOCK / ABTASTRATE)
        return np.zeros(BLOCK, np.float32)

    def schliessen(self):
        pass


def test_tonquelle_ist_nach_dem_neustart_wieder_da(tmp_path, monkeypatch):
    monkeypatch.setattr(quellen, "Eingang", FalscherEingang)
    daten.einrichten(tmp_path / "d")
    pfade = daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog")
    show = Show(pfade)
    assert show.audio_quelle_setzen({"art": "eingang", "geraet": 3, "kanaele": [1, 2]}) == "Eingang: X-USB 1-2"
    show.audio.stoppen()
    neu = Show(pfade)
    assert neu.audio_auftrag == {"art": "eingang", "name": "X-USB 1-2", "api": "Core Audio", "kanaele": [1, 2]}
    neu._audio_wiederherstellen()
    assert neu.audio.name == "Eingang: X-USB 1-2"
    neu.audio.stoppen()
    with pytest.raises(ValueError):
        neu.audio_quelle_setzen({"art": "quatsch"})
