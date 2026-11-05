"""Die Musik-Analyse, gefüttert mit künstlichen Signalen schneller als Echtzeit."""
import numpy as np
import pytest

from lichtsteuerung.audio.analyse import Analyse, AubioBeatErkennung, EigeneBeatErkennung
from lichtsteuerung.audio.betrieb import AudioBetrieb
from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK, AudioFehler, erzeuge_takt


def bloecke(ton):
    for start in range(0, len(ton) - BLOCK, BLOCK):
        yield ton[start:start + BLOCK]


def abspielen(analyse, ton):
    return [analyse.verarbeite(block) for block in bloecke(ton)]


ERKENNUNGEN = [EigeneBeatErkennung]
try:
    import aubio  # noqa: F401
    ERKENNUNGEN.append(AubioBeatErkennung)
except ImportError:
    pass


@pytest.mark.parametrize("erkennung", ERKENNUNGEN)
@pytest.mark.parametrize("bpm", [100, 128])
def test_erkennt_den_takt(erkennung, bpm):
    werte = abspielen(Analyse(erkennung()), erzeuge_takt(bpm, 20))
    ende = werte[len(werte) // 2:]
    assert ende[-1].tempo_bpm == pytest.approx(bpm, rel=0.05) or \
        ende[-1].tempo_bpm == pytest.approx(bpm * 2, rel=0.05)
    assert sum(w.beat for w in ende) >= 10 * bpm / 60 * 0.7


def test_bass_hoch_beim_tiefen_ton():
    zeit = np.arange(ABTASTRATE * 2) / ABTASTRATE
    tief = (0.5 * np.sin(2 * np.pi * 60 * zeit)).astype(np.float32)
    werte = abspielen(Analyse(EigeneBeatErkennung()), tief)[-1]
    assert werte.bass > 0.8


def test_stille_gilt_als_leise_nach_kurzer_zeit():
    analyse = Analyse(EigeneBeatErkennung())
    abspielen(analyse, erzeuge_takt(120, 3))
    werte = abspielen(analyse, np.zeros(ABTASTRATE * 2, dtype=np.float32))
    assert not werte[0].leise
    assert werte[-1].leise


def test_laute_stelle_hat_mehr_energie_als_leise():
    laut = erzeuge_takt(120, 10)
    analyse = Analyse(EigeneBeatErkennung())
    energie_laut = abspielen(analyse, laut)[-1].energie
    energie_leise = abspielen(analyse, laut * 0.1)[-1].energie
    assert energie_laut > energie_leise * 2


def test_energie_bleibt_zwischen_0_und_1():
    werte = abspielen(Analyse(EigeneBeatErkennung()), erzeuge_takt(140, 5) * 3)
    assert all(0 <= w.energie <= 1 and 0 <= w.bass <= 1 for w in werte)


class KaputteQuelle:
    def lies(self):
        raise AudioFehler("Kabel raus")

    def schliessen(self):
        pass


def test_ausfall_der_quelle_ergibt_keine_messwerte():
    betrieb = AudioBetrieb()
    betrieb.starten(KaputteQuelle(), "kaputt")
    betrieb._thread.join(1)
    assert betrieb.aktuell() is None
    assert "Kabel" in betrieb.fehler
    betrieb.stoppen()


def test_alte_messwerte_gelten_als_ausfall():
    betrieb = AudioBetrieb()
    betrieb.messwerte, betrieb.zeitpunkt = object(), 100.0
    assert betrieb.aktuell(100.2) is not None
    assert betrieb.aktuell(100.6) is None        # Analyse hängt


def test_beatuhr_ueberbrueckt_luecken_und_hoert_wieder_auf():
    from lichtsteuerung.audio.analyse import BeatUhr
    uhr = BeatUhr()
    schritt = 0.01
    beats = 0
    for i in range(int(4 / schritt)):      # 4 s bei 120 BPM, nur ein echter Beat am Anfang
        beats += uhr.takt(i == 0, 120.0, schritt)
    assert 7 <= beats <= 9
    for _ in range(int(10 / schritt)):     # danach Stille
        beats += uhr.takt(False, 120.0, schritt)
    assert beats <= 13                     # nach 6 s ist Schluss


def test_kein_beat_geht_verloren_auch_wenn_das_licht_langsamer_fragt():
    """Die Analyse läuft 86-mal pro Sekunde, das Licht 40-mal."""
    from lichtsteuerung.audio.analyse import Messwerte
    betrieb = AudioBetrieb()
    betrieb.zeitpunkt = 100.0
    gesehen = 0
    for block in range(860):
        betrieb.messwerte = Messwerte()
        if block % 40 == 0:
            betrieb.beat_zaehler += 1
            betrieb.messwerte = Messwerte(beat=True)
        if block % 2 == 1:                   # das Licht fragt nur jeden zweiten Block
            gesehen += betrieb.abholen(100.0).beat
    assert gesehen == 22                     # kein einziger fehlt


def test_abholen_zaehlt_einen_beat_nur_einmal():
    from lichtsteuerung.audio.analyse import Messwerte
    betrieb = AudioBetrieb()
    betrieb.messwerte, betrieb.zeitpunkt, betrieb.beat_zaehler = Messwerte(beat=True), 100.0, 1
    assert betrieb.abholen(100.0).beat and not betrieb.abholen(100.0).beat
    assert betrieb.aktuell(100.0).beat       # die Anzeige verbraucht nichts


# --- Drops: nur echte, mit Aufbau und Bass-Einschlag ---------------------------------

def drops_finden(ton):
    analyse = Analyse(EigeneBeatErkennung())
    drops, spannung = [], 0.0
    for start in range(0, len(ton) - BLOCK, BLOCK):
        werte = analyse.verarbeite(ton[start:start + BLOCK])
        if werte.drop:
            drops.append(start / ABTASTRATE)
        spannung = max(spannung, werte.spannung)
    return drops, spannung


@pytest.mark.parametrize("bpm", [100, 128, 174])
@pytest.mark.parametrize("mit_pause", [True, False])
def test_echter_drop_wird_auf_50_ms_genau_erkannt(bpm, mit_pause):
    from lichtsteuerung.audio.quellen import erzeuge_edm
    ton, zeit = erzeuge_edm(bpm, mit_pause=mit_pause)
    drops, spannung = drops_finden(ton)
    assert len(drops) == 1 and 0 <= drops[0] - zeit <= 0.08
    assert spannung > 0.8


def test_kein_drop_ohne_aufbau_oder_break():
    """Normale Songs: Strophe geht in einen lauten Refrain, Becken-Crescendo. Alles kein Drop."""
    rng = np.random.default_rng(1)
    refrain = np.concatenate([erzeuge_takt(120, 20) * 0.3,
                              erzeuge_takt(120, 20) * 0.9 + (rng.standard_normal(20 * ABTASTRATE) * 0.1).astype("float32")])
    zeit = np.arange(30 * ABTASTRATE) / ABTASTRATE
    crescendo = (erzeuge_takt(110, 30) * 0.6
                 + rng.standard_normal(len(zeit)) * np.clip((zeit - 10) / 10, 0, 1) * 0.2).astype("float32")
    for ton in (refrain, crescendo):
        assert drops_finden(ton)[0] == []


def test_break_dann_volle_band_ist_ein_drop():
    """Sechs Sekunden fast still, dann setzt die ganze Band ein: Das soll das Licht treffen."""
    rng = np.random.default_rng(1)
    ton = np.concatenate([erzeuge_takt(120, 20) * 0.3, erzeuge_takt(120, 6) * 0.05,
                          erzeuge_takt(120, 20) * 0.9 + (rng.standard_normal(20 * ABTASTRATE) * 0.1).astype("float32")])
    drops, _ = drops_finden(ton)
    assert len(drops) == 1 and 26 <= drops[0] <= 26.6


def handy(ton, rng=np.random.default_rng(5)):
    """Ungefähr so klingt es über einen Handy-Lautsprecher am Laptop-Mikrofon: kein Tiefbass, etwas Raum."""
    spektrum = np.fft.rfft(ton)
    frequenz = np.fft.rfftfreq(len(ton), 1 / ABTASTRATE)
    spektrum *= np.clip((frequenz - 120) / 200, 0, 1) * np.clip((12000 - frequenz) / 4000, 0, 1)
    gefiltert = np.fft.irfft(spektrum, len(ton)).astype("float32")
    hall = np.convolve(gefiltert, np.exp(-np.arange(2000) / 300) / 60, mode="same").astype("float32")
    return gefiltert * 0.4 + hall + rng.standard_normal(len(ton)).astype("float32") * 0.003


@pytest.mark.parametrize("bpm", [128, 174])
def test_drop_auch_ueber_handy_lautsprecher(bpm):
    """Ohne Tiefbass und mit einem Riser, der lauter ist als der Drop selbst."""
    from lichtsteuerung.audio.quellen import erzeuge_edm
    ton, zeit = erzeuge_edm(bpm)
    drops, _ = drops_finden(handy(ton))
    assert len(drops) == 1 and -0.05 <= drops[0] - zeit <= 0.1


def test_drop_ohne_pause_ueber_handy_hoechstens_einen_beat_spaet():
    from lichtsteuerung.audio.quellen import erzeuge_edm
    ton, zeit = erzeuge_edm(128, mit_pause=False)
    drops, _ = drops_finden(handy(ton))
    assert len(drops) == 1 and 0 <= drops[0] - zeit <= 60 / 128 + 0.05


def test_pause_vor_dem_drop_ist_nicht_leise():
    """Die Stille vor dem Drop darf nicht als leise Stelle aufs Grundlicht gehen."""
    from lichtsteuerung.audio.quellen import erzeuge_edm
    ton, zeit = erzeuge_edm(128)
    analyse = Analyse(EigeneBeatErkennung())
    pause_gesehen = False
    for start in range(0, int(zeit * ABTASTRATE), BLOCK):
        werte = analyse.verarbeite(ton[start:start + BLOCK])
        pause_gesehen |= werte.vor_drop
        if start / ABTASTRATE > zeit - 0.3:
            assert not werte.leise
    assert pause_gesehen


def test_messwerte_lassen_sich_immer_an_die_oberflaeche_schicken():
    """Ein numpy-Wert in den Messwerten hat einmal die Live-Verbindung abbrechen lassen."""
    import json
    from lichtsteuerung.audio.quellen import erzeuge_edm
    ton, _ = erzeuge_edm(128)
    analyse = Analyse(EigeneBeatErkennung())
    for start in range(0, len(ton) - BLOCK, BLOCK * 7):
        json.dumps(vars(analyse.verarbeite(ton[start:start + BLOCK])))
