"""Sperrzone Publikum: reine Rechnung und im echten Prüf-Ablauf."""
import pytest

from lichtsteuerung.buehne import Buehne
from lichtsteuerung.pantilt import Montage, richtung, winkel_fuer_ziel
from lichtsteuerung.patch import Patch
from lichtsteuerung.pruefung import Pruefer, Vorgaben
from lichtsteuerung.render import Eigenschaften, Renderer
from lichtsteuerung.sicherheit import Grenzen
from lichtsteuerung.sperrzone import zielt_ins_publikum

PUBLIKUM = {"x_von_m": -8, "x_bis_m": 8, "y_von_m": -14, "y_bis_m": -2,
            "kopfhoehe_m": 2.0, "sicherheitsabstand_m": 0.5}


def strahl_von(start, ziel):
    return tuple(z - s for s, z in zip(start, ziel))


def test_strahl_ins_publikum_auf_kopfhoehe():
    start = (0, 2, 3.9)
    assert zielt_ins_publikum(start, strahl_von(start, (0, -5, 1.6)), PUBLIKUM)


def test_strahl_auf_die_buehne_ist_erlaubt():
    start = (0, 2, 3.9)
    assert not zielt_ins_publikum(start, strahl_von(start, (0, 3, 0.8)), PUBLIKUM)


def test_strahl_ueber_die_koepfe_ist_erlaubt():
    start = (0, 2, 3.9)
    assert not zielt_ins_publikum(start, strahl_von(start, (0, -14, 3.5)), PUBLIKUM)


def test_strahl_von_hinten_nach_oben_ist_erlaubt():
    assert not zielt_ins_publikum((0, 2, 3.9), (0, 0, 1), PUBLIKUM)


def test_front_stativ_auf_die_buehne_ist_erlaubt():
    start = (-3.5, -1, 2.5)
    assert not zielt_ins_publikum(start, strahl_von(start, (-2.5, 1, 2.4)), PUBLIKUM, 15)


def test_sicherheitsabstand_zaehlt():
    start = (0, 2, 3.9)
    # Ziel knapp vor dem Publikum, aber innerhalb des Abstands
    ziel = (0, -1.7, 1.0)
    assert zielt_ins_publikum(start, strahl_von(start, ziel), PUBLIKUM)
    assert not zielt_ins_publikum(start, strahl_von(start, ziel), {**PUBLIKUM, "sicherheitsabstand_m": 0,
                                                                  "y_bis_m": -6})


def test_auch_der_kegelrand_zaehlt():
    start = (0, 2, 3.9)
    d = strahl_von(start, (0, -14, 4.5))   # Mitte klar über den Köpfen, Abstand groß
    assert not zielt_ins_publikum(start, d, PUBLIKUM, 0)
    assert zielt_ins_publikum(start, d, PUBLIKUM, 40)


@pytest.fixture
def aufbau(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf", gruppen=["Spots"])
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("kopf", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9,
                                 "montage": "haengend", "drehung_grad": 180})
    return patch, buehne, Pruefer(patch, buehne, Grenzen(3, 5, 30)), Renderer(patch)


def bild_fuer_ziel(renderer, buehne, ziel, hell=1.0):
    montage = Montage.aus_buehne(buehne.geraet("kopf"))
    pan, tilt = winkel_fuer_ziel(montage, ziel, 540, 270)
    return renderer.bild({"kopf": Eigenschaften(helligkeit=hell, pan=pan, tilt=tilt)})


def test_pruefung_laesst_buehne_durch(aufbau):
    _, buehne, pruefer, renderer = aufbau
    bild = bild_fuer_ziel(renderer, buehne, (0, 3, 0.8))
    geprueft, meldungen, _ = pruefer.pruefe(bild, Vorgaben())
    assert geprueft[:4] == bild[:4] and meldungen == []


def test_pruefung_haelt_kopf_auf_letzter_sicherer_stellung(aufbau):
    _, buehne, pruefer, renderer = aufbau
    sicher = bild_fuer_ziel(renderer, buehne, (0, 3, 0.8))
    pruefer.pruefe(sicher, Vorgaben())
    gefaehrlich = bild_fuer_ziel(renderer, buehne, (0, -5, 1.6))
    geprueft, meldungen, _ = pruefer.pruefe(gefaehrlich, Vorgaben())
    assert geprueft[:4] == sicher[:4]
    assert "Sperrzone" in meldungen[0]


def test_ohne_sichere_stellung_bleibt_der_kopf_dunkel(aufbau):
    _, buehne, pruefer, renderer = aufbau
    geprueft, meldungen, _ = pruefer.pruefe(bild_fuer_ziel(renderer, buehne, (0, -5, 1.6)), Vorgaben())
    assert geprueft[4] == 0        # Dimmer aus
    assert geprueft[5] <= 3        # Shutter zu
    assert meldungen


def test_rohe_dmx_werte_werden_genauso_geprueft(aufbau):
    """Auch der DMX-Test kommt nicht ins Publikum: Es zählt das fertige Bild."""
    _, buehne, pruefer, renderer = aufbau
    bild = bild_fuer_ziel(renderer, buehne, (0, -5, 1.6))
    roh = bytearray(renderer.bild({"kopf": Eigenschaften(helligkeit=1)}))
    roh[0:4] = bild[0:4]
    _, meldungen, _ = pruefer.pruefe(roh, Vorgaben())
    assert any("Sperrzone" in m for m in meldungen)


def test_gerät_ohne_ort_bleibt_dunkel(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf")
    buehne = Buehne(pfade.stage)
    pruefer = Pruefer(patch, buehne, Grenzen(3, 5, 30))
    geprueft, meldungen, _ = pruefer.pruefe(Renderer(patch).bild({"kopf": Eigenschaften(helligkeit=1)}), Vorgaben())
    assert geprueft[4] == 0 and "fehlt" in meldungen[0]


def test_hin_und_rueckrechnung_aus_dem_bild_ist_genau(aufbau):
    """Die Prüfung liest Winkel aus dem Bild. 16 bit müssen auf 0,1° genau sein."""
    _, buehne, _, renderer = aufbau
    montage = Montage.aus_buehne(buehne.geraet("kopf"))
    pan, tilt = winkel_fuer_ziel(montage, (0.7, 3, 0.8), 540, 270)
    bild = bild_fuer_ziel(renderer, buehne, (0.7, 3, 0.8))
    p = (bild[0] * 256 + bild[1]) / 65535
    t = (bild[2] * 256 + bild[3]) / 65535
    assert (p - 0.5) * 540 == pytest.approx(pan, abs=0.1)
    assert (t - 0.5) * 270 == pytest.approx(tilt, abs=0.1)
    assert richtung(montage, (p - 0.5) * 540, (t - 0.5) * 270)[2] < 0


def test_sprung_durchs_publikum_bleibt_dunkel_bis_der_kopf_da_ist(aufbau):
    """Von über den Köpfen direkt auf die Bühnenkante: Der Weg geht durch die Kopfhöhe."""
    _, buehne, pruefer, renderer = aufbau
    oben = bild_fuer_ziel(renderer, buehne, (0, -8, 5.5))
    unten = bild_fuer_ziel(renderer, buehne, (0, 0.3, 0.8))
    assert pruefer.pruefe(oben, Vorgaben(), jetzt=0.0)[0][4] == 255
    geprueft, _, _ = pruefer.pruefe(unten, Vorgaben(), jetzt=0.1)
    assert geprueft[4] == 0                           # unterwegs dunkel
    assert pruefer.pruefe(unten, Vorgaben(), jetzt=5.0)[0][4] == 255   # angekommen


def test_kleiner_schritt_bleibt_hell(aufbau):
    _, buehne, pruefer, renderer = aufbau
    pruefer.pruefe(bild_fuer_ziel(renderer, buehne, (0, 3, 0.8)), Vorgaben(), jetzt=0.0)
    geprueft, _, _ = pruefer.pruefe(bild_fuer_ziel(renderer, buehne, (0.5, 3, 0.8)), Vorgaben(), jetzt=0.025)
    assert geprueft[4] == 255
