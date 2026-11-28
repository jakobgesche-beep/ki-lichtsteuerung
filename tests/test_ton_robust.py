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
    ende = time.monotonic() + 5                                # langsame Rechner (CI) brauchen länger
    while time.monotonic() < ende and not betrieb.fehler:
        time.sleep(0.05)
    assert betrieb.fehler and "Ton weg" in betrieb.fehler
    time.sleep(0.6)
    assert betrieb.frisch() is None                            # ehrlich: gerade kommt kein Ton
    assert betrieb.abrisse == 1
    ende = time.monotonic() + 9
    while time.monotonic() < ende and betrieb.wieder_verbunden == 0:
        time.sleep(0.2)
    assert betrieb.wieder_verbunden == 1 and betrieb.fehler is None and betrieb.abrisse == 1
    time.sleep(0.6)
    assert betrieb.frisch() is not None and betrieb.aktuell() is not None
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


# --- Ton-Stabilität 2.5: kurze Aussetzer, Logbuch ohne Flut, Takt-Uhr, Vorlauf, Schlaf --------------------

class Aussetzer:
    """Liefert Ton, macht nach `bis` Blöcken eine Pause von `pause_s` und liefert dann weiter (ohne Abriss)."""

    def __init__(self, bis, pause_s):
        self.bis, self.pause_s, self.n = bis, pause_s, 0

    def lies(self):
        self.n += 1
        if self.n == self.bis:
            time.sleep(self.pause_s)
        time.sleep(BLOCK / ABTASTRATE)
        return (np.random.default_rng(self.n).standard_normal(BLOCK) * 0.1).astype(np.float32)

    def schliessen(self):
        pass


def test_kurzer_aussetzer_haelt_die_werte_statt_grundlicht():
    from lichtsteuerung.audio import betrieb as betrieb_modul
    betrieb = AudioBetrieb()
    betrieb.starten(Aussetzer(bis=30, pause_s=1.5), "Eingang: X32")
    ende = time.monotonic() + 5
    gesehen_frisch_weg, gesehen_gehalten = False, False
    while time.monotonic() < ende:
        if betrieb.messwerte is not None and betrieb.frisch() is None:
            gesehen_frisch_weg = True
            gesehen_gehalten = gesehen_gehalten or betrieb.aktuell() is not None
        time.sleep(0.05)
    betrieb.stoppen()
    assert gesehen_frisch_weg and gesehen_gehalten            # 1,5 s Pause: frisch weg, aber noch gehalten
    assert betrieb_modul.HALTEN_S >= 2.0


class ToterEingang:
    """Öffnet sich immer wieder, liefert aber nie Ton (wie das Mikrofon bei zugeklapptem Deckel)."""

    def __init__(self):
        self.geoeffnet = 0

    def lies(self):
        time.sleep(0.02)
        raise AudioFehler("Vom Audio-Eingang kommt nichts mehr (Testgerät).")

    def neu_oeffnen(self):
        self.geoeffnet += 1
        return self

    def schliessen(self):
        pass


def test_toter_eingang_flutet_das_logbuch_nicht(caplog, monkeypatch):
    from lichtsteuerung.audio import betrieb as betrieb_modul
    monkeypatch.setattr(betrieb_modul, "ERSTE_PAUSE_S", 0.05)
    monkeypatch.setattr(betrieb_modul, "LAENGSTE_PAUSE_S", 0.1)
    quelle = ToterEingang()
    betrieb = AudioBetrieb()
    with caplog.at_level("INFO"):
        betrieb.starten(quelle, "Eingang: MacBook-Mikrofon")
        ende = time.monotonic() + 5
        while time.monotonic() < ende and quelle.geoeffnet < 10:
            time.sleep(0.05)
        betrieb.stoppen()
    assert quelle.geoeffnet >= 10
    zeilen = [r.getMessage() for r in caplog.records if "Audio-Eingang" in r.getMessage()]
    assert len(zeilen) == 1 and "weg" in zeilen[0]             # einmal „weg“, nie „wieder da“ ohne echten Ton
    assert betrieb.wieder_verbunden == 0 and betrieb.abrisse == 1


def _klick(bpm, sekunden):
    return quellen.erzeuge_takt(bpm, sekunden)


def test_takt_uhr_zaehlt_verlorene_bloecke_mit():
    from lichtsteuerung.audio.takt import TaktFolger
    ton = _klick(120, 24)
    bloecke = [ton[i:i + BLOCK] for i in range(0, len(ton) - BLOCK + 1, BLOCK)]

    def phasen(art):
        """Lage der Beats nach 18 s im 0,5-s-Raster. art: ohne Lücke, Lücke mitgezählt, Lücke vergessen."""
        folger = TaktFolger()
        beats = []
        for nummer, block in enumerate(bloecke):
            if art != "ohne" and 1400 <= nummer < 1410:        # 10 Blöcke (116 ms) gehen verloren
                if nummer == 1400 and art == "mitgezaehlt":
                    folger.luecke(10 * BLOCK)
                continue
            if folger.verarbeite(block)[0]:
                beats.append((nummer + 1) * BLOCK / ABTASTRATE)
        return np.array([b % 0.5 for b in beats if 16.5 < b < 20.0])

    ohne, mitgezaehlt, vergessen = phasen("ohne"), phasen("mitgezaehlt"), phasen("vergessen")
    assert len(ohne) >= 6 and len(mitgezaehlt) == len(ohne) == len(vergessen)
    assert np.max(np.abs(mitgezaehlt - ohne)) < 0.02          # wie ohne Lücke
    assert np.max(np.abs(vergessen - ohne)) > 0.06            # Gegenprobe: so lägen die Beats daneben


def test_vorlauf_meldet_beats_frueher():
    from lichtsteuerung.audio.takt import TaktFolger
    ton = _klick(120, 20)
    bloecke = [ton[i:i + BLOCK] for i in range(0, len(ton) - BLOCK + 1, BLOCK)]

    def beatzeiten(vorlauf):
        folger = TaktFolger()
        folger.vorlauf_s = vorlauf
        zeiten = []
        for nummer, block in enumerate(bloecke):
            if folger.verarbeite(block)[0]:
                zeiten.append((nummer + 1) * BLOCK / ABTASTRATE)
        return [z for z in zeiten if z > 12.0]

    ohne, mit = beatzeiten(0.0), beatzeiten(0.08)
    assert ohne and mit
    versatz = np.median([min(abs(m - o) for o in ohne) for m in mit])
    assert 0.06 <= versatz <= 0.1 and np.median(mit) < np.median(ohne) + 0.01


def test_vorlauf_je_nach_tonquelle():
    from lichtsteuerung.show import vorlauf_fuer
    assert vorlauf_fuer("X-USB 1-32 (BEHRINGER X-USB)") == 0.06
    assert vorlauf_fuer("MacBook Air-Mikrofon") == 0.10
    assert vorlauf_fuer("MacBook Air-Mikrofon", 40) == 0.04


def test_mac_stand_liest_netzteil_und_deckel(monkeypatch):
    import subprocess
    import sys
    from lichtsteuerung import wachhalten
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(wachhalten._mac_stand, "zeit", -99.0)

    def falsch(befehl, **_):
        if "pmset" in befehl[0]:
            return subprocess.CompletedProcess(befehl, 0, "Now drawing from 'Battery Power'\n", "")
        return subprocess.CompletedProcess(befehl, 0, '  "AppleClamshellState" = Yes\n', "")

    assert wachhalten.mac_stand(1000.0, ausfuehren=falsch) == {"netzteil": False, "deckel_zu": True}


def test_konzert_check_warnt_bei_zugeklapptem_deckel_und_akku(tmp_path, monkeypatch):
    from lichtsteuerung import konzertcheck, wachhalten
    monkeypatch.setattr(wachhalten, "mac_stand", lambda *a, **k: {"netzteil": False, "deckel_zu": True})
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    texte = [p["text"] for p in konzertcheck.pruefen(show) if p["thema"] == "Rechner" and p["stufe"] == "problem"]
    assert any("Deckel" in t for t in texte) and any("Akku" in t for t in texte)


def test_schlaf_landet_im_rueckblick(tmp_path):
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    show._geschlafen(6000)
    tag = show.rueckblick.tage()[0]
    auswertung = show.rueckblick.zusammenfassung(tag)
    assert any(e["art"] == "schlaf" and "100" in e["text"] for e in auswertung["ereignisse"])
    assert any("geschlafen" in h for h in auswertung["hinweise"])
