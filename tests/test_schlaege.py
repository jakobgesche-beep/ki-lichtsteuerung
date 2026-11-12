"""Große Schläge der Band: in der Probe gefunden (Lichtakzent im Song) und live (Akzent in der Automatik)."""
import numpy as np

from lichtsteuerung.audio import songanalyse
from lichtsteuerung.audio.analyse import Analyse
from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK, erzeuge_takt


def mit_crash(ton, zeiten):
    rng = np.random.default_rng(2)
    ton = ton.copy()
    for bei in zeiten:
        i, lang = int(bei * ABTASTRATE), int(0.6 * ABTASTRATE)
        ton[i:i + lang] += (rng.standard_normal(lang) * np.exp(-np.arange(lang) / (0.15 * ABTASTRATE)) * 0.9).astype(np.float32)
    return ton


def live_schlaege(ton):
    analyse, gefunden = Analyse(), []
    for a in range(0, len(ton) - BLOCK, BLOCK):
        if analyse.verarbeite(ton[a:a + BLOCK]).schlag:
            gefunden.append(a / ABTASTRATE)
    return gefunden


def test_live_ein_crash_ist_ein_schlag_der_normale_takt_nicht():
    takt = np.concatenate([erzeuge_takt(120, 12), erzeuge_takt(120, 12)]) * 0.5
    assert live_schlaege(takt) == []
    gefunden = live_schlaege(mit_crash(takt, [8.0, 17.0]))
    assert len(gefunden) == 2 and abs(gefunden[0] - 8.0) < 0.1 and abs(gefunden[1] - 17.0) < 0.1


def test_in_der_probe_werden_die_crashs_gefunden_und_auf_den_beat_gelegt():
    takt = np.concatenate([np.zeros(ABTASTRATE, np.float32)] + [erzeuge_takt(120, 16)] * 3) * 0.5
    ergebnis = songanalyse.analysieren(mit_crash(takt, [13.0, 25.0, 37.0]))
    schlaege = ergebnis["schlaege_s"]
    assert len(schlaege) >= 3
    for bei in (13.0, 25.0, 37.0):
        assert any(abs(s - bei) < 0.1 for s in schlaege)


def test_engine_gibt_beim_schlag_einen_akzent(tmp_path):
    from lichtsteuerung import daten
    from lichtsteuerung.audio.analyse import Messwerte
    from lichtsteuerung.show import Show
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    engine, profil = show.engine, {**show.profile.laden("Schulfest Abend")}
    werte = Messwerte(beat=True, tempo_bpm=120, bass=0.8, mitte=0.6, hoehe=0.5, energie=0.7, pegel=0.3,
                      leise=False, intensitaet=0.7)
    for i in range(40):
        engine.bewerte(werte, profil, i * 0.025)
    vorher = engine.letzter_akzent
    engine.bewerte(Messwerte(**{**vars(werte), "schlag": True}), profil, 1.0)
    assert engine.letzter_akzent == 1.0 and vorher != 1.0
