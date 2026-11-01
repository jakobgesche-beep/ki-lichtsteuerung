"""Der Import der Open Fixture Library."""
import json

from lichtsteuerung.importe.ofl import hertz, importiere, wandle_geraet
from lichtsteuerung.katalog import Katalog, pruefe_eintrag

BEISPIEL = {
    "name": "Testkopf", "categories": ["Moving Head"],
    "physical": {"weight": 7.0, "lens": {"degreesMinMax": [10, 25]}},
    "wheels": {"Farbrad": {"slots": [{"type": "Open"}, {"type": "Color", "name": "Red", "colors": ["#ff0000"]}]}},
    "availableChannels": {
        "Pan": {"fineChannelAliases": ["Pan fine"], "capability": {"type": "Pan", "angleStart": "0deg", "angleEnd": "540deg"}},
        "Dimmer": {"capability": {"type": "Intensity"}},
        "Rot": {"capability": {"type": "ColorIntensity", "color": "Red"}},
        "Shutter": {"capabilities": [
            {"dmxRange": [0, 9], "type": "ShutterStrobe", "shutterEffect": "Closed"},
            {"dmxRange": [10, 19], "type": "ShutterStrobe", "shutterEffect": "Open"},
            {"dmxRange": [20, 99], "type": "ShutterStrobe", "shutterEffect": "Strobe", "speedStart": "1Hz", "speedEnd": "25Hz"},
            {"dmxRange": [100, 255], "type": "ShutterStrobe", "shutterEffect": "Strobe", "speedStart": "slow", "speedEnd": "fast"}]},
        "Farbrad": {"capabilities": [
            {"dmxRange": [0, 127], "type": "WheelSlot", "wheel": "Farbrad", "slotNumber": 1},
            {"dmxRange": [128, 255], "type": "WheelSlot", "wheel": "Farbrad", "slotNumber": 2}]},
    },
    "modes": [{"name": "Voll", "channels": ["Pan", "Pan fine", "Dimmer", "Rot", "Shutter", "Farbrad", None]}],
}


def test_wandelt_alle_wichtigen_angaben():
    eintrag = wandle_geraet("test", "Test", "kopf", BEISPIEL)
    assert pruefe_eintrag(eintrag) == []
    kanaele = eintrag["kanaele"]
    assert kanaele["Pan"]["typ"] == "pan" and kanaele["Pan"]["grad"] == 540
    assert kanaele["Pan fine"] == {"typ": "pan_fein", "standard": 0, "grob": "Pan", "stufe": 1}
    assert kanaele["Dimmer"]["typ"] == "dimmer"
    assert kanaele["Rot"]["typ"] == "rot"
    assert eintrag["physik"] == {"gewicht_kg": 7.0, "abstrahlwinkel_grad": 25}
    assert eintrag["quelle"]["lizenz"] == "MIT"


def test_strobo_mit_hertz_und_ohne():
    bereiche = wandle_geraet("t", "T", "k", BEISPIEL)["kanaele"]["Shutter"]["bereiche"]
    assert bereiche[2]["typ"] == "strobo" and (bereiche[2]["hz_von"], bereiche[2]["hz_bis"]) == (1, 25)
    # "slow/fast" ist keine Zahl: Das muss None bleiben, die Prüfung sperrt es dann.
    assert bereiche[3]["typ"] == "strobo" and bereiche[3]["hz_bis"] is None


def test_shutter_steht_standardmaessig_offen():
    assert wandle_geraet("t", "T", "k", BEISPIEL)["kanaele"]["Shutter"]["standard"] == 10


def test_hertz_aus_bpm():
    assert hertz({"speedStart": "60bpm", "speedEnd": "120bpm"}) == (1, 2)


def test_farbrad_kennt_farben():
    bereiche = wandle_geraet("t", "T", "k", BEISPIEL)["kanaele"]["Farbrad"]["bereiche"]
    assert bereiche[1]["farbe"] == "#ff0000"


def test_importiere_schreibt_lesbaren_katalog(tmp_path):
    ofl = tmp_path / "ofl"
    (ofl / "fixtures" / "test").mkdir(parents=True)
    (ofl / "fixtures" / "manufacturers.json").write_text(json.dumps({"test": {"name": "Test"}}))
    (ofl / "fixtures" / "test" / "kopf.json").write_text(json.dumps(BEISPIEL))
    (ofl / "fixtures" / "test" / "alt.json").write_text(json.dumps({"redirectTo": "test/kopf"}))
    ziel = tmp_path / "catalog" / "ofl"
    assert importiere(ofl, ziel)["importiert"] == 1
    assert "test/kopf" in Katalog(tmp_path / "catalog").typen


def test_der_echte_katalog_enthaelt_unsere_geraete():
    from lichtsteuerung.daten import PROJEKT
    katalog = Katalog(PROJEKT / "catalog")
    assert len(katalog.typen) > 600
    for typ_id in ("stairville/mh-x25", "stairville/hz-200-compact-hazer",
                   "stairville/quad-par-profile-rgbw-5x8w", "varytec/hero-spot-60"):
        assert pruefe_eintrag(katalog.typ(typ_id).daten) == []
