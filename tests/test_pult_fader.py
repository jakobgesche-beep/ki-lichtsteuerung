"""Pult-Tab wie bei grandMA: Fader-Seiten, Fader-Arten, Store/Update/Assign, Flash, Grand Master, Oops."""
import json

import pytest
from fastapi.testclient import TestClient

from lichtsteuerung.befehle import Befehlszeile
from lichtsteuerung.buehne import Buehne
from lichtsteuerung.patch import Patch
from lichtsteuerung.pult import ANZAHL_EXECUTOREN, SONG_NUMMER, tempo_faktor
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show

DIMMER = 0          # PAR 1, Kanal 1


@pytest.fixture
def show(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/par", "6", 2, "PAR 1-2", gruppen=["Farb-PARs"])
    patch.hinzufuegen("test/kopf", "7", 2, "Kopf 1-2", gruppen=["Spots"])
    patch.speichern()
    buehne = Buehne(pfade.stage)
    for geraet, x in (("kopf-1", -1.4), ("kopf-2", 1.4)):
        buehne.setze_geraet(geraet, {"ort": "traverse", "x": x, "y": 2, "z": 3.9, "montage": "haengend",
                                     "drehung_grad": 180})
    buehne.speichern()
    s = Show(pfade)
    s.automatik_an = False
    s.profil = {**s.profil, "max_helligkeit": 1.0}
    return s


def rot_programmieren(show, hell=1.0):
    show.pult.programmer.setzen(["par-1", "par-2"], {"helligkeit": hell, "farbe": "rot"})


def test_vierzig_fader_und_store_auf_leeren_fader(show):
    assert len(show.pult.executoren) == ANZAHL_EXECUTOREN == 40
    rot_programmieren(show)
    sequenz = show.pult.speichern_auf(5)
    assert sequenz["name"] == "Sequenz 1" and show.pult.executor(5).sequenz["name"] == "Sequenz 1"
    show.pult.programmer.setzen(["par-1"], {"farbe": "blau"})
    sequenz = show.pult.speichern_auf(5)
    assert [c["name"] for c in sequenz["cues"]] == ["Cue 1", "Cue 2"]


def test_fader_hoch_startet_fader_runter_schaltet_aus(show):
    rot_programmieren(show)
    show.pult.speichern_auf(1)
    show.pult.programmer.leeren()
    show.pult.fader_setzen(1, 0.0, 0.0)
    assert show.pult.executor(1).index == -1
    show.pult.fader_setzen(1, 0.6, 0.1)
    assert show.pult.executor(1).index == 0
    show.baue_bild(5.0)
    assert show.letztes_bild[DIMMER] == round(0.6 * 255)
    show.pult.fader_setzen(1, 0.0, 5.1)
    assert show.pult.executor(1).index == -1


def test_flash_schaltet_ein_und_beim_loslassen_wieder_aus(show):
    rot_programmieren(show)
    show.pult.speichern_auf(2, zeit_s=3.0)
    show.pult.programmer.leeren()
    show.pult.executor(2).fader = 0.2
    show.pult.flash(2, True, 1.0)
    assert show.baue_bild(1.0)[DIMMER] == 255        # sofort voll, ohne Überblendzeit, Fader egal
    show.pult.flash(2, False, 1.5)
    assert show.baue_bild(1.5)[DIMMER] == 0           # sofort wieder aus
    assert show.pult.executor(2).index == -1


def test_haengender_flash_geht_von_selbst_aus(show):
    rot_programmieren(show)
    show.pult.speichern_auf(2)
    show.pult.programmer.leeren()
    show.pult.flash(2, True, 0.0)
    show.baue_bild(25.0)
    assert show.pult.executor(2).flash_seit is None and show.pult.executor(2).index == -1


def test_gruppen_master_regelt_flash_und_aus(show):
    rot_programmieren(show)
    show.pult.zuweisen(3, "gruppe", "Farb-PARs")
    show.pult.fader_setzen(3, 0.5, 0.0)
    assert show.baue_bild(0.1)[DIMMER] == round(0.5 * 255)
    show.pult.aus(3, 0.2)                                  # Aus-Taste: Gruppe dunkel
    assert show.baue_bild(0.3)[DIMMER] == 0
    show.pult.aus(3, 0.4)                                  # nochmal: wieder an
    show.pult.flash(3, True, 0.5)
    assert show.baue_bild(0.6)[DIMMER] == 255
    show.pult.flash(3, False, 0.7)
    assert show.baue_bild(0.8)[DIMMER] == round(0.5 * 255)


def test_tempo_fader_macht_effekte_schneller_ohne_sprung(show):
    assert tempo_faktor(0.5) == 1.0 and tempo_faktor(1.0) == pytest.approx(4.0) and tempo_faktor(0.0) == pytest.approx(0.25)
    effekte = show.pult.effekte
    effekte.musik_beats = 10.0
    vorher = effekte.effekt_beats("musik")
    show.pult.zuweisen(10, "tempo")
    show.pult.fader_setzen(10, 0.75, 0.0)                  # doppelt so schnell
    assert effekte.faktor == pytest.approx(2.0)
    assert effekte.effekt_beats("musik") == pytest.approx(vorher)     # kein Sprung
    effekte.takt(1.0, 120.0)                               # 2 Beats Musik
    assert effekte.effekt_beats("musik") == pytest.approx(vorher + 4.0)
    show.pult.zuweisen(10, None)
    assert effekte.faktor == 1.0


def test_grand_master_dimmt_alles_aber_nicht_warmweiss(show):
    rot_programmieren(show)
    show.pult.grand_setzen(0.5, 0.0)
    assert show.baue_bild(0.1)[DIMMER] == round(0.5 * 255)
    show.overrides.warmweiss = True
    assert show.baue_bild(0.2)[DIMMER] > 0.5 * 255         # Warmweiß (Rede) hat Vorrang vor dem Grand Master


def test_update_arbeitet_den_programmer_in_den_laufenden_cue_ein(show):
    rot_programmieren(show, 0.5)
    show.pult.speichern_auf(1)
    show.pult.programmer.leeren()
    show.pult.go(1, 0.0)
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 0.9})
    sequenz = show.pult.aktualisieren(1)
    werte = sequenz["cues"][0]["werte"]
    assert next(w for w in werte if w["geraet"] == "par-1") == {"geraet": "par-1", "helligkeit": 0.9, "farbe": "rot"}
    assert len(werte) == 2


def test_oops_nimmt_store_assign_und_leeren_zurueck(show):
    rot_programmieren(show)
    show.pult.speichern_auf(4)
    assert show.pult.executor(4).sequenz is not None
    show.pult.rueckgaengig()                               # ein Schritt: Cue und Belegung zurück
    assert show.pult.executor(4).sequenz is None and show.pult.sequenzen.lesen("Sequenz 1") is None
    show.pult.merke_programmer()
    show.pult.programmer.leeren()
    show.pult.rueckgaengig()
    assert show.pult.programmer.werte["par-1"]["farbe"] == "rot"
    with pytest.raises(ValueError):
        show.pult.rueckgaengig()


def test_cues_bearbeiten_und_song_sequenzen_sind_geschuetzt(show):
    rot_programmieren(show)
    for _ in range(3):
        show.pult.speichern_auf(1)
    name = show.pult.executor(1).sequenz["name"]
    show.pult.cue_aendern(name, 2, {"name": "Refrain", "zeit_s": 4, "folgen_s": ""})
    show.pult.cue_verschieben(name, 2, -1)
    sequenz = show.pult.cue_loeschen(name, 3)
    assert [c["name"] for c in sequenz["cues"]] == ["Refrain", "Cue 1"] and sequenz["cues"][0]["zeit_s"] == 4.0
    song = dict(sequenz, name="Song", zeitcode=[0.0, 10.0])
    show.pult.sequenz_speichern(song)
    with pytest.raises(ValueError, match="Song"):
        show.pult.cue_loeschen("Song", 1)


def test_belegung_neues_und_altes_dateiformat(show, pfade):
    rot_programmieren(show)
    show.pult.speichern_auf(1)
    show.pult.zuweisen(2, "gruppe", "Spots")
    show.pult.zuweisen(3, "tempo")
    show.pult.label_setzen(1, "Rot")
    show.pult.grand_setzen(0.8, 0.0)
    show.pult.belegung_speichern()
    neu = Show(pfade)
    assert neu.pult.executor(1).label == "Rot" and neu.pult.executor(2).gruppe == "Spots"
    assert neu.pult.executor(3).art == "tempo" and neu.pult.grand == 0.8
    pfade.executoren.write_text(json.dumps({"executoren": ["Sequenz 1", None]}), encoding="utf-8")
    alt = Show(pfade)
    assert alt.pult.executor(1).sequenz["name"] == "Sequenz 1" and alt.pult.executor(2).art is None


def test_go_auf_leerem_fader_sagt_was_fehlt(show):
    with pytest.raises(ValueError, match="liegt nichts"):
        show.pult.go(7, 0.0)


def bandsong():
    import numpy as np
    from lichtsteuerung.audio.quellen import ABTASTRATE, erzeuge_takt
    teile = [erzeuge_takt(120, 16) * laut for laut in (0.1, 0.8, 0.15, 0.8)]
    return np.concatenate([np.zeros(ABTASTRATE, np.float32)] + teile).astype(np.float32)


def test_song_start_laesst_die_fader_in_ruhe(show):
    rot_programmieren(show)
    show.pult.speichern_auf(1)
    show.proben.speichern("Band", bandsong())
    show.show_aus_probe("Band")
    show.song.starten("Band", jetzt=0.0)
    assert show.pult.executor(1).sequenz["name"] == "Sequenz 1"
    assert show.song.laeuft_auf(SONG_NUMMER) and show.pult.song_platz.sequenz["name"] == "Band"
    show.pult.go(SONG_NUMMER, 0.5)                          # Leertaste im Song: nächster Teil
    assert show.pult.status()["haupt_info"]["song"]


def test_befehle_wie_bei_grandma(show):
    zeile = Befehlszeile(show)
    zeile.ausfuehren("Group 1 At Full Color Red")
    assert "Fader 5" in zeile.ausfuehren("Store Exec 5")
    zeile.ausfuehren("Store Exec 5")
    assert len(show.pult.executor(5).sequenz["cues"]) == 2
    zeile.ausfuehren("Assign Sequence 1 At Exec 3")
    assert show.pult.executor(3).sequenz["name"] == "Sequenz 1"
    zeile.ausfuehren("Zuweisen Gruppe Spots auf Fader 4")
    assert show.pult.executor(4).art == "gruppe"
    zeile.ausfuehren("Exec 3 At 50")
    assert show.pult.executor(3).fader == 0.5 and show.pult.executor(3).index == -1   # war schon oben: kein Start
    zeile.ausfuehren("Go Exec 3")
    assert show.pult.executor(3).index == 0
    zeile.ausfuehren("Label Exec 3 Rote Show")
    assert show.pult.executor(3).label == "Rote Show"
    zeile.ausfuehren("Off Exec 3")
    assert show.pult.executor(3).index == -1
    zeile.ausfuehren("Delete Exec 3")
    assert show.pult.executor(3).art is None
    zeile.ausfuehren("Oops")
    assert show.pult.executor(3).sequenz["name"] == "Sequenz 1"
    zeile.ausfuehren("Page 2")
    assert show.pult.seite == 2
    zeile.ausfuehren("Grandmaster At 70")
    assert show.pult.grand == pytest.approx(0.7)
    zeile.ausfuehren("Highlight")
    assert show.pult.highlight
    with pytest.raises(ValueError, match="laufenden Cue"):
        zeile.ausfuehren("Update Exec 5")      # Fader 5 läuft nicht
    zeile.ausfuehren("Go Exec 5")
    assert "Update" in zeile.ausfuehren("Update Exec 5")


def test_server_fader_funktionen(show):
    with TestClient(erstelle_app(show)) as client:
        rot_programmieren(show)
        antwort = client.post("/api/executor/6/speichern", json={}).json()
        assert antwort["sequenz"] == "Sequenz 1"
        assert client.post("/api/executor/7/belegen", json={"gruppe": "Spots"}).json()["executoren"][6]["art"] == "gruppe"
        assert client.post("/api/executor/8/belegen", json={"art": "tempo"}).json()["executoren"][7]["faktor"] == 1.0
        assert client.post("/api/executor/6/flash", json={"an": True}).json()["executoren"][5]["flash"]
        assert client.post("/api/executor/6/flash", json={"an": False}).status_code == 200
        assert client.post("/api/executor/6/label", json={"label": "Intro"}).json()["executoren"][5]["name"] == "Intro"
        assert client.post("/api/grand", json={"wert": 0.4}).json()["grand"] == 0.4
        assert client.post("/api/pult/seite", json={"seite": 3}).json()["seite"] == 3
        pool = client.get("/api/sequenzen").json()["sequenzen"]
        assert pool == [{"name": "Sequenz 1", "cues": 1, "song": False, "fader": [6]}]
        assert client.post("/api/sequenzen/Sequenz 1/cue/1/aendern", json={"zeit_s": 5}).json()["cues"][0]["zeit_s"] == 5
        assert client.post("/api/oops").json()["antwort"].startswith("Rückgängig")
        assert client.post("/api/executor/9/go").status_code == 400
        assert client.post("/api/executor/41/go").status_code == 400
