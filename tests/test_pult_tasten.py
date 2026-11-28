"""Executor-Tasten wie am grandMA, Fader-auf-0-Fehler, feste Not-Tasten (fürs iPad übers Netz)."""
import pytest

from lichtsteuerung import daten
from lichtsteuerung.overrides import Overrides
from lichtsteuerung.show import Show

EIN_CUE = {"name": "Wild", "cues": [{"name": "Wild", "zeit_s": 0, "werte": [{"gruppe": "Spots", "helligkeit": 1}]}]}
ZWEI_CUES = {"name": "Ablauf", "cues": [{"name": "A", "zeit_s": 0, "werte": [{"gruppe": "Spots", "helligkeit": 1}]},
                                        {"name": "B", "zeit_s": 0, "werte": [{"gruppe": "Spots", "helligkeit": 0.5}]}]}


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.pult.sequenz_speichern(EIN_CUE)
    s.pult.sequenz_speichern(ZWEI_CUES)
    return s


def test_zuweisen_zieht_einen_fader_auf_0_hoch(show):
    pult = show.pult
    pult.fader_setzen(3, 0.0, 1.0)
    pult.zuweisen(3, "sequenz", "Wild")
    assert pult.executor(3).fader == 1.0
    pult.fader_setzen(3, 0.4, 2.0)
    pult.zuweisen(3, "sequenz", "Ablauf")                  # ein gewollter Wert bleibt
    assert pult.executor(3).fader == 0.4


def test_go_auf_fader_0_faehrt_ihn_hoch(show):
    pult = show.pult
    pult.zuweisen(2, "sequenz", "Wild")
    pult.executor(2).fader = 0.0                           # wie beim Nutzer: Fader stand unten
    pult.taste(2, "toggle", 5.0)
    assert pult.executor(2).fader == 1.0 and pult.executor(2).index == 0
    assert any("stand auf 0" in m for m in pult.aktuelle_hinweise(5.5))


def test_standard_tasten_und_toggle(show):
    pult = show.pult
    pult.zuweisen(1, "sequenz", "Wild")
    pult.zuweisen(2, "sequenz", "Ablauf")
    assert pult.tasten_fuer(pult.executor(1)) == {"oben": "toggle", "mitte": "flash", "unten": "aus"}
    assert pult.tasten_fuer(pult.executor(2))["oben"] == "go"                       # mehrere Cues: Go+
    pult.taste(1, "toggle", 1.0)
    assert pult.executor(1).index == 0
    pult.taste(1, "toggle", 2.0, erwartet=True)            # Druck kam doppelt an: bleibt an
    assert pult.executor(1).index == 0
    pult.taste(1, "toggle", 3.0, erwartet=False)
    assert pult.executor(1).index < 0
    pult.taste(2, "go", 4.0)
    pult.taste(2, "go", 5.0)
    assert pult.executor(2).index == 1
    pult.taste(2, "zurueck", 6.0)
    assert pult.executor(2).index == 0
    pult.taste(1, "flash", 7.0, an=True)
    assert pult.executor(1).flash_seit is not None
    pult.taste(1, "flash", 7.5, an=False)
    assert pult.executor(1).flash_seit is None and pult.executor(1).index < 0
    with pytest.raises(ValueError):
        pult.taste(1, "quatsch", 8.0)


def test_eigene_tasten_und_farbe_bleiben_gespeichert(show, tmp_path):
    pult = show.pult
    pult.zuweisen(4, "sequenz", "Wild")
    pult.tasten_setzen(4, {"oben": "go", "unten": "zurueck"})
    pult.farbe_setzen(4, "#e07b39")
    info = pult.executor_info(pult.executor(4))
    assert info["tasten"] == {"oben": "go", "mitte": "flash", "unten": "zurueck"} and info["farbe"] == "#e07b39"
    neu = Show(show.pfade)
    assert neu.pult.executor(4).tasten == {"oben": "go", "unten": "zurueck"}
    assert neu.pult.executor(4).farbe == "#e07b39"
    with pytest.raises(ValueError):
        pult.tasten_setzen(4, {"oben": "loeschen"})
    with pytest.raises(ValueError):
        pult.farbe_setzen(4, "javascript:alert(1)")


def test_not_tasten_fest_an_und_aus():
    o = Overrides()
    o.setzen("blackout", True)
    o.setzen("blackout", True)                             # doppelt: bleibt an (Umschalten wäre jetzt aus)
    assert o.blackout is True
    o.setzen("blackout", False)
    assert o.blackout is False
    with pytest.raises(ValueError):
        o.setzen("alles", True)


def test_goto_aus_der_cue_liste_auch_vom_ipad(show):
    """Tipp auf einen Cue in der Cue-Liste (iPad wie Mac): genau dorthin, Fader auf 0 fährt hoch."""
    from lichtsteuerung import aktionen
    pult = show.pult
    pult.zuweisen(4, "sequenz", "Ablauf")
    pult.executor(4).fader = 0.0
    sitzung = aktionen.Sitzung(show, "Test-iPad")
    aktionen.ausfuehren(show, "goto", {"nr": 4, "index": 1}, sitzung)
    assert pult.executor(4).index == 1 and pult.executor(4).fader == 1.0 and pult.haupt == 3
    with pytest.raises(ValueError):
        aktionen.ausfuehren(show, "goto", {"nr": 4, "index": 7}, sitzung)
    with pytest.raises(ValueError):
        aktionen.ausfuehren(show, "goto", {"nr": 4, "index": "1"}, sitzung)
