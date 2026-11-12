"""Song-Folger fürs Konzert: Start zu früh/zu spät, Band schneller, Teil ausgelassen, zweimal drücken."""
import numpy as np

from lichtsteuerung.audio import folgen
from lichtsteuerung.audio.quellen import ABTASTRATE

AKKORDE = {"A": [(261.6, 329.6, 392.0), (196.0, 246.9, 293.7)], "B": [(220.0, 261.6, 329.6), (174.6, 220.0, 261.6)],
           "C": [(293.7, 349.2, 440.0), (164.8, 207.7, 246.9)], "D": [(349.2, 440.0, 523.3), (392.0, 493.9, 587.3)]}


def song(teile, tempo=120.0, stille_s=1.0, takte=4):
    """Kunstsong: Jeder Teil hat eigene Akkorde, dazu ein Schlag auf jedem Beat. Gibt (Ton, Teilanfänge) zurück."""
    beat = 60.0 / tempo
    stuecke, anfaenge, jetzt = [np.zeros(int(stille_s * ABTASTRATE), np.float32)], [], stille_s
    t_beat = np.arange(int(beat * ABTASTRATE)) / ABTASTRATE
    schlag = (np.sin(2 * np.pi * 60 * t_beat) * np.exp(-t_beat * 30)).astype(np.float32)
    for teil in teile:
        anfaenge.append(jetzt)
        for takt in range(takte):
            akkord = AKKORDE[teil][takt % 2]
            for _ in range(4):
                ton = sum(np.sin(2 * np.pi * f * t_beat) for f in akkord) * 0.15 * np.exp(-t_beat * 2)
                stuecke.append((ton + 0.4 * schlag).astype(np.float32))
                jetzt += beat
    stuecke.append(np.zeros(int(2 * ABTASTRATE), np.float32))
    return np.concatenate(stuecke), anfaenge


def mithoeren(folger, ton, druck_s, bis_s=None):
    """Spielt den Ton blockweise ein, wie live. Gibt [(Zeit, Stelle)] zurück."""
    verlauf, gedrueckt = [], False
    ende = len(ton) if bis_s is None else int(bis_s * ABTASTRATE)
    for a in range(0, ende - 512, 512):
        t = a / ABTASTRATE
        if not gedrueckt and t >= druck_s:
            folger.starten(jetzt=t)
            gedrueckt = True
        if not gedrueckt:
            continue
        folger.hoeren(ton[a:a + 512], t)
        verlauf.append((t, folger.takt(512 / ABTASTRATE, t)))
    return verlauf


def bei(verlauf, zeit):
    return min(verlauf, key=lambda v: abs(v[0] - zeit))[1]


def test_start_zu_frueh_die_uhr_wartet_auf_die_band():
    probe, _ = song("ABCD", stille_s=1.0)
    live, _ = song("ABCD", stille_s=5.0)
    folger = folgen.SongFolger(*folgen.merkmale_der_aufnahme(probe))
    assert abs(folger.anfang - 1.0) < 0.3
    verlauf = mithoeren(folger, live, druck_s=1.5)          # 3,5 s zu früh gedrückt
    assert abs(bei(verlauf, 4.0) - folger.anfang) < 0.05     # wartet
    assert abs(bei(verlauf, 20.0) - (1.0 + 15.0)) < 0.5      # dann im Takt der Band


def test_start_zu_spaet_holt_auf():
    probe, _ = song("ABCD")
    folger = folgen.SongFolger(*folgen.merkmale_der_aufnahme(probe))
    verlauf = mithoeren(folger, probe, druck_s=2.5)          # 1,5 s nach dem Anfang gedrückt
    assert abs(bei(verlauf, 12.0) - 12.0) < 0.4


def test_band_spielt_schneller():
    probe, anfaenge = song("ABCD", tempo=120)
    live, live_anfaenge = song("ABCD", tempo=127)              # knapp 6 % schneller
    folger = folgen.SongFolger(*folgen.merkmale_der_aufnahme(probe))
    verlauf = mithoeren(folger, live, druck_s=1.0)
    for probe_zeit, live_zeit in zip(anfaenge[2:], live_anfaenge[2:]):
        assert abs(bei(verlauf, live_zeit) - probe_zeit) < 0.6
    assert 1.02 < folger.rate_lang < 1.1


def test_teil_ausgelassen_das_mithoeren_springt_hin():
    probe, anfaenge = song("ABCD")
    live, live_anfaenge = song("ACD")                         # Teil B fehlt
    folger = folgen.SongFolger(*folgen.merkmale_der_aufnahme(probe))
    verlauf = mithoeren(folger, live, druck_s=1.0)
    # Mitten in C (live) muss die Stelle in C der Probe sein, nicht mehr in B
    mitte_c = live_anfaenge[1] + 6.0
    assert abs(bei(verlauf, mitte_c) - (anfaenge[2] + 6.0)) < 1.0


def test_zweimal_druecken_heisst_jetzt_los():
    probe, _ = song("ABCD")
    folger = folgen.SongFolger(*folgen.merkmale_der_aufnahme(probe))
    folger.starten(jetzt=0.0)
    for i in range(20):                                       # Stille: wartet
        folger.hoeren(np.zeros(512, np.float32), i * 0.0116)
    assert folger.zustand(0.25)["art"] == "bereit" and folger.takt(0.1, 0.3) == folger.anfang
    folger.jetzt_los(0.3)
    assert folger.takt(0.5, 0.8) > folger.anfang


def test_von_hand_gesetzt_wird_nicht_mehr_am_anfang_nachgeprueft():
    """Nach "Nächster Teil" darf die Anfangs-Prüfung die Stelle nicht wieder an den Song-Anfang ziehen."""
    from lichtsteuerung.audio.folgen import SongFolger, merkmale_der_aufnahme
    from lichtsteuerung.audio.quellen import erzeuge_takt
    ton = erzeuge_takt(120, 40) * 0.5
    folger = SongFolger(*merkmale_der_aufnahme(ton))
    folger.starten(jetzt=0.0)
    for a in range(0, 3 * 44100, 512):                 # beim Drücken schon laut: Anfang wird nachgeprüft
        folger.hoeren(ton[a:a + 512], a / 44100)
    assert folger.pruefen_bis > 0
    folger.setzen(20.0)
    assert folger.pruefen_bis == 0.0 and folger.stelle == 20.0
