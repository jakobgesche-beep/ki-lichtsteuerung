"""Einzelkanäle vom X32: sichere Rede (Mikro offen, Band still), Schlagzeug-Solo, Übersprechen."""
import numpy as np

from lichtsteuerung.audio.analyse import Analyse
from lichtsteuerung.audio.quellen import ABTASTRATE as RATE, BLOCK
from lichtsteuerung.audio.rollen import RollenAnalyse
from lichtsteuerung.audio.takt import TaktFolger
from werkzeuge import testmusik

RNG = np.random.default_rng(4)


def rauschen(n, db=-70):
    return (RNG.standard_normal(n) * 10 ** (db / 20)).astype(np.float32)


def abspielen(summe, rollen):
    analyse = RollenAnalyse()
    werte = []
    for i in range(0, len(summe) - BLOCK, BLOCK):
        werte.append(analyse.verarbeite(summe[i:i + BLOCK], {k: v[i:i + BLOCK] for k, v in rollen.items()}))
    return werte


def anteil(werte, feld, ab_s=4.0):
    teil = werte[int(ab_s * RATE / BLOCK):]
    return sum(getattr(w, feld) for w in teil) / len(teil)


def test_ansage_ist_sicher_rede():
    stimme = testmusik.rede(20.0)
    n = len(stimme)
    werte = abspielen(stimme * 0.6, {"rednerpult": stimme, "bassdrum": rauschen(n), "snare": rauschen(n)})
    assert anteil(werte, "rede_sicher") > 0.8


def test_musik_mit_uebersprechen_ist_nie_rede():
    spuren = {}
    ton, _ = testmusik.song("rock", 120, 12, spuren=spuren)
    werte = abspielen(ton, {"gesang": (0.15 * ton + rauschen(len(ton))).astype(np.float32),
                            "bassdrum": spuren["bassdrum"], "snare": spuren["snare"]})
    assert anteil(werte, "rede_sicher") == 0.0
    assert anteil(werte, "band_aktiv") > 0.9


def test_schlagzeug_solo_trotz_uebersprechen_ins_gesangsmikro():
    spuren = {}
    testmusik.song("punk", 170, 16, spuren=spuren)
    trommeln = (spuren["bassdrum"] + spuren["snare"]).astype(np.float32)
    werte = abspielen(trommeln, {"gesang": (0.2 * trommeln + rauschen(len(trommeln))).astype(np.float32),
                                 "bassdrum": spuren["bassdrum"], "snare": spuren["snare"]})
    assert anteil(werte, "schlagzeug_solo", 6.0) > 0.7       # das Gesangsmikro hört nur das Schlagzeug


def test_song_mit_gesang_ist_kein_solo():
    spuren = {}
    ton, _ = testmusik.song("punk", 170, 16, spuren=spuren)
    gesang = testmusik.rede(len(ton) / RATE)[:len(ton)]          # eine Stimme, unabhängig vom Schlagzeug
    werte = abspielen(ton, {"gesang": (gesang + 0.1 * ton).astype(np.float32),
                            "bassdrum": spuren["bassdrum"], "snare": spuren["snare"]})
    assert anteil(werte, "schlagzeug_solo", 6.0) < 0.2


def test_analyse_nimmt_rede_aus_dem_mikro_nicht_aus_der_summe():
    stimme = testmusik.rede(16.0)
    n = len(stimme)
    analyse = Analyse(TaktFolger())
    rede = []
    for i in range(0, n - BLOCK, BLOCK):
        w = analyse.verarbeite(stimme[i:i + BLOCK] * 0.6, {"rednerpult": stimme[i:i + BLOCK],
                                                            "bassdrum": rauschen(BLOCK), "snare": rauschen(BLOCK)})
        rede.append(w.rede and w.rollen)
    assert sum(rede[int(5 * RATE / BLOCK):]) / len(rede[int(5 * RATE / BLOCK):]) > 0.8
