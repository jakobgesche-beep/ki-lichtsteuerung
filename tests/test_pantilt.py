"""Die Pan/Tilt-Rechnung."""
import math

import pytest

from lichtsteuerung.pantilt import (Montage, ZielAusserhalb, anteil_zu_winkel, richtung,
                                    winkel_fuer_ziel, winkel_zu_anteil)


def fast_gleich(a, b, genau=1e-6):
    return all(abs(x - y) < genau for x, y in zip(a, b))


def test_stehend_mitte_zeigt_nach_oben():
    assert fast_gleich(richtung(Montage(0, 0, 0), 0, 0), (0, 0, 1))


def test_haengend_mitte_zeigt_nach_unten():
    assert fast_gleich(richtung(Montage(0, 0, 3, haengend=True), 0, 0), (0, 0, -1))


def test_tilt_kippt_zur_vorderseite():
    assert fast_gleich(richtung(Montage(0, 0, 0), 0, 90), (0, 1, 0))
    # Um 180° gedreht ist vorne beim Publikum
    assert fast_gleich(richtung(Montage(0, 0, 0, drehung_grad=180), 0, 90), (0, -1, 0))
    assert fast_gleich(richtung(Montage(0, 0, 3, haengend=True, drehung_grad=180), 0, 90), (0, -1, 0))


def test_pan_dreht_um_die_achse():
    assert fast_gleich(richtung(Montage(0, 0, 0), 90, 90), (1, 0, 0))
    assert fast_gleich(richtung(Montage(0, 0, 0), -90, 90), (-1, 0, 0))


def test_ziel_direkt_unter_haengendem_kopf():
    pan, tilt = winkel_fuer_ziel(Montage(1, 2, 4, haengend=True), (1, 2, 0), 540, 270)
    assert tilt == pytest.approx(0, abs=1e-6)


MONTAGEN = [
    Montage(0, 2, 3.9, haengend=True, drehung_grad=180),
    Montage(-3.5, -1, 2.5, drehung_grad=0),
    Montage(3.5, -1, 2.5, drehung_grad=25),
    Montage(1, 3, 3.9, haengend=True, drehung_grad=90, pan_versatz_grad=3, tilt_versatz_grad=-2),
    Montage(0, 0, 1, pan_umkehren=True, tilt_umkehren=True),
]
ZIELE = [(0, 1, 0.8), (-2.5, 1, 2.4), (3, 4, 0.8), (0.3, 2.2, 2.0), (-4, 1, 2)]


@pytest.mark.parametrize("montage", MONTAGEN)
@pytest.mark.parametrize("ziel", ZIELE)
def test_hin_und_zurueck_trifft_das_ziel(montage, ziel):
    """Wichtigste Probe: Mit den berechneten Winkeln zeigt der Kopf wirklich aufs Ziel."""
    pan, tilt = winkel_fuer_ziel(montage, ziel, 540, 270)
    strahl = richtung(montage, pan, tilt)
    d = [ziel[i] - (montage.x, montage.y, montage.z)[i] for i in range(3)]
    laenge = math.sqrt(sum(w * w for w in d))
    assert fast_gleich(strahl, [w / laenge for w in d])


def test_ergebnis_bleibt_im_bereich():
    for ziel in ZIELE:
        pan, tilt = winkel_fuer_ziel(MONTAGEN[0], ziel, 540, 190)
        assert abs(pan) <= 270 and abs(tilt) <= 95


def test_ziel_ausserhalb_gibt_meldung():
    # Hängt der Kopf (Tilt ±95°), kommt er nicht an einen Punkt schräg über sich.
    with pytest.raises(ZielAusserhalb):
        winkel_fuer_ziel(Montage(0, 0, 3, haengend=True), (0, 0.5, 6), 540, 190)


def test_ziel_im_geraet_gibt_meldung():
    with pytest.raises(ZielAusserhalb):
        winkel_fuer_ziel(Montage(1, 1, 1), (1, 1, 1), 540, 270)


def test_kuerzester_weg_vom_aktuellen_stand():
    montage = Montage(0, 0, 0)
    ziel = (0, 1, 1)           # Lösungen bei Pan 0° oder ±180° (mit Tilt andersherum)
    pan, _ = winkel_fuer_ziel(montage, ziel, 540, 270, aktuell=(170, -45))
    assert pan == pytest.approx(180)
    pan, _ = winkel_fuer_ziel(montage, ziel, 540, 270, aktuell=(0, 45))
    assert pan == pytest.approx(0)


def test_auch_ein_kleiner_bereich_findet_die_andere_loesung():
    # Ziel bei Pan 200° ist bei ±120° nur über Pan 20° und negativen Tilt erreichbar.
    montage = Montage(0, 0, 0)
    ziel = (math.sin(math.radians(200)), math.cos(math.radians(200)), 1)
    pan, tilt = winkel_fuer_ziel(montage, ziel, 240, 270)
    assert pan == pytest.approx(20) and tilt == pytest.approx(-45)


def test_umrechnung_in_dmx_anteil():
    assert winkel_zu_anteil(0, 540) == 0.5
    assert winkel_zu_anteil(-270, 540) == 0
    assert winkel_zu_anteil(270, 540) == 1
    assert winkel_zu_anteil(999, 540) == 1     # nie über den Bereich hinaus
    assert anteil_zu_winkel(0.75, 190) == pytest.approx(47.5)
