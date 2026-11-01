"""Szenen, Cues, Fader, und dass Entwürfe nie live gehen."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung.buehne import Buehne
from lichtsteuerung.cues import pruefe_cueliste
from lichtsteuerung.patch import Patch
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show

ROT = {"name": "Rot", "werte": [{"gruppe": "Farb-PARs", "farbe": "rot", "helligkeit": 0.8}]}
BLAU = {"name": "Blau", "werte": [{"gruppe": "Farb-PARs", "farbe": "blau", "helligkeit": 0.4}]}
SPOT = {"name": "Spot", "werte": [{"gruppe": "Spots", "position": "Mitte", "helligkeit": 1}]}
LISTE = {"name": "Stück", "cues": [
    {"name": "Eins", "szene": "Rot", "einblenden_s": 2, "ausblenden_s": 2, "warten_s": 0},
    {"name": "Zwei", "szene": "Blau", "einblenden_s": 0, "ausblenden_s": 0, "warten_s": 3},
    {"name": "Drei", "szene": "Rot", "einblenden_s": 0, "ausblenden_s": 1, "warten_s": 0}]}
DIMMER, K_ROT, K_BLAU = 0, 1, 3


@pytest.fixture
def show(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/par", "6", 2, "PAR 1-2", gruppen=["Farb-PARs"])
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf", gruppen=["Spots"])
    patch.speichern()
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("kopf", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend",
                                 "drehung_grad": 180})
    buehne.speichern()
    s = Show(pfade)
    for szene in (ROT, BLAU, SPOT):
        s.szenen.schreiben(szene)
    s.cuelisten.schreiben(LISTE)
    s.profil = {**s.profil, "max_helligkeit": 1.0}
    s.cueliste_laden("Stück")
    return s


def test_cue_blendet_ein(show):
    show.cues.weiter(0.0)
    anfang = show.baue_bild(0.0)
    mitte = show.baue_bild(1.0)
    ende = show.baue_bild(2.0)
    assert anfang[K_BLAU] > mitte[K_BLAU] > ende[K_BLAU] == 0
    assert ende[DIMMER] == round(0.8 * 255) and ende[K_ROT] == 255


def test_weiter_geht_der_reihe_nach_und_stoppt_am_ende(show):
    assert show.cues.weiter(0.0) and show.cues.index == 0
    assert show.cues.weiter(1.0) and show.cues.index == 1
    assert show.cues.weiter(2.0) and show.cues.index == 2
    assert not show.cues.weiter(3.0)


def test_wartezeit_startet_den_naechsten_cue_von_selbst(show):
    show.cues.weiter(0.0)
    show.cues.weiter(5.0)      # "Zwei": 3 s warten
    show.baue_bild(7.0)
    assert show.cues.index == 1
    show.baue_bild(8.1)
    assert show.cues.index == 2


def test_cue_loslassen_blendet_zur_automatik(show):
    show.cues.weiter(0.0)
    show.baue_bild(2.0)
    show.cues.stopp(2.0)
    assert show.baue_bild(3.0)[K_ROT] > 0
    bild = show.baue_bild(4.1)
    assert bild[DIMMER] == round(0.5 * 255)      # Grundlicht des Ruhe-Profils
    assert show.cues.status()["aktiv"] is None


def test_cue_steht_in_eigenschaften_und_ueberlebt_den_geraetetausch(show, katalog):
    """Ein anderes Modell, andere Kanäle: Der Cue läuft einfach weiter."""
    show.patch.tauschen("par-1", "test/par", "4")     # Rot, Grün, Blau, Dimmer
    show.aufbauen()
    show.cues.weiter(0.0)
    bild = show.baue_bild(2.0)
    assert bild[0] == 255 and bild[3] == round(0.8 * 255)


def test_max_helligkeit_gilt_auch_fuer_cues(show):
    show.profil = {**show.profil, "max_helligkeit": 0.5}
    show.cues.weiter(0.0)
    assert show.baue_bild(2.0)[DIMMER] == round(0.5 * 255)


def test_blackout_schlaegt_den_cue(show):
    show.cues.weiter(0.0)
    show.baue_bild(2.0)
    show.overrides.blackout = True
    assert show.baue_bild(2.1)[DIMMER] == 0


def test_position_in_szene_zielt_mit_pan_tilt(show):
    show.cues.laden({"name": "x", "cues": [{"name": "a", "szene": "Spot", "einblenden_s": 0,
                                           "ausblenden_s": 0, "warten_s": 0}]})
    show.positionen["Mitte"] = {"x": 0.0, "y": 3.0, "z": 0.8}
    show.cues.weiter(0.0)
    bild = show.baue_bild(0.1)
    kopf = next(g for g in show.simulator.lies(bild) if g["id"] == "kopf")
    assert kopf["hell"] == 1 and kopf["richtung"][2] < -0.9


def test_cue_ins_publikum_wird_von_der_pruefung_gestoppt(show):
    show.positionen["Mitte"] = {"x": 0.0, "y": -6.0, "z": 1.6}
    show.cues.laden({"name": "x", "cues": [{"name": "a", "szene": "Spot", "einblenden_s": 0,
                                           "ausblenden_s": 0, "warten_s": 0}]})
    show.cues.weiter(0.0)
    bild = show.baue_bild(0.1)
    assert any("Sperrzone" in m for m in show.meldungen)
    kopf = next(g for g in show.simulator.lies(bild) if g["id"] == "kopf")
    assert kopf["hell"] == 0


def test_cueliste_mit_fehlender_szene_wird_abgelehnt(show):
    assert pruefe_cueliste({"name": "x", "cues": [{"name": "a", "szene": "Gibtsnicht"}]}, show.szenen)


def test_negative_zeit_wird_abgelehnt(show):
    assert pruefe_cueliste({"name": "x", "cues": [{"name": "a", "szene": "Rot", "einblenden_s": -1}]}, show.szenen)


def test_gruppen_fader_dimmt(show):
    show.fader.belegen(0, {"art": "gruppe", "ziel": "Farb-PARs"}, show.szenen, show.patch.gruppen())
    show.cues.weiter(0.0)
    show.baue_bild(2.0)
    show.fader.setze(0, 0.5)
    assert show.baue_bild(2.1)[DIMMER] == round(0.8 * 0.5 * 255)


def test_szenen_fader_blendet_stufenlos(show):
    show.fader.belegen(1, {"art": "szene", "ziel": "Rot"}, show.szenen, show.patch.gruppen())
    grund = show.baue_bild(0.0)
    assert grund[K_BLAU] > 100             # warmweißes Grundlicht hat Blau-Anteil
    show.fader.setze(1, 0.5)
    halb = show.baue_bild(0.1)
    assert 0 < halb[K_BLAU] < grund[K_BLAU]
    show.fader.setze(1, 1.0)
    bild = show.baue_bild(0.2)
    assert bild[K_BLAU] == 0 and bild[DIMMER] == round(0.8 * 255)


def test_fader_belegung_wird_gespeichert(show, pfade):
    show.fader.belegen(2, {"art": "szene", "ziel": "Rot"}, show.szenen, show.patch.gruppen())
    assert Show(pfade).fader.belegung[2] == {"art": "szene", "ziel": "Rot"}


def test_fader_mit_falschem_ziel(show):
    with pytest.raises(ValueError):
        show.fader.belegen(0, {"art": "gruppe", "ziel": "Gibtsnicht"}, show.szenen, show.patch.gruppen())
    with pytest.raises(ValueError):
        show.fader.belegen(99, {"art": "frei"}, show.szenen, show.patch.gruppen())


# --- Grundregel: Nichts geht direkt live, gespeichert wird erst nach „Übernehmen“ ---

NEU = {"name": "Neu", "werte": [{"gruppe": "Farb-PARs", "farbe": "gruen", "helligkeit": 1}]}


def test_entwurf_aendert_den_ausgang_nicht(show):
    vorher = show.baue_bild(0.0)
    show.vorschau.entwurf_setzen("szene", NEU)
    assert show.baue_bild(0.1) == vorher


def test_entwurf_erscheint_in_der_vorschau(show):
    show.vorschau.entwurf_setzen("szene", NEU)
    par = show.live_daten()["vorschau"]["geraete"][0]
    assert par["farbe"] == [0, 1, 0] and par["hell"] == 1


def test_entwurf_wird_erst_beim_uebernehmen_gespeichert(show):
    show.vorschau.entwurf_setzen("szene", NEU)
    assert show.szenen.lesen("Neu") is None
    assert show.vorschau.uebernehmen() == "Neu"
    assert show.szenen.lesen("Neu") is not None
    assert show.live_daten()["vorschau"]["geraete"] is None


def test_verwerfen_speichert_nichts(show):
    show.vorschau.entwurf_setzen("szene", NEU)
    show.vorschau.verwerfen()
    with pytest.raises(ValueError):
        show.vorschau.uebernehmen()
    assert show.szenen.lesen("Neu") is None


def test_uebernehmen_macht_noch_nichts_live(show):
    vorher = show.baue_bild(0.0)
    show.vorschau.entwurf_setzen("szene", NEU)
    show.vorschau.uebernehmen()
    assert show.baue_bild(0.1) == vorher


def test_kaputter_entwurf_kommt_gar_nicht_in_die_vorschau(show):
    with pytest.raises(ValueError):
        show.vorschau.entwurf_setzen("szene", {"name": "X", "werte": [{"gruppe": "Gibtsnicht"}]})
    with pytest.raises(ValueError):
        show.vorschau.entwurf_setzen("szene", {"name": "X", "werte": [{"gruppe": "Farb-PARs", "helligkeit": 5}]})
    assert show.vorschau.inhalt is None


def test_vorschau_zeigt_strobo_nur_mit_fester_grenze(show):
    entwurf = {"name": "Blitz", "werte": [{"gruppe": "Farb-PARs", "helligkeit": 1, "strobo_hz": 20}]}
    hinweise = show.vorschau.entwurf_setzen("szene", entwurf)
    assert any("begrenzt" in h for h in hinweise)
    assert show.live_daten()["vorschau"]["geraete"][0]["strobo_hz"] <= 3


def test_vorschau_meldet_sperrzone(show):
    show.positionen["Publikum"] = {"x": 0.0, "y": -6.0, "z": 1.6}
    hinweise = show.vorschau.entwurf_setzen(
        "szene", {"name": "Falsch", "werte": [{"gruppe": "Spots", "position": "Publikum", "helligkeit": 1}]})
    assert any("Sperrzone" in h for h in hinweise)


def test_profil_entwurf_geht_denselben_weg(show):
    profil = {"name": "KI-Profil", "palette": ["rot"], "max_helligkeit": 0.5, "bewegung": "aus",
              "beat_reaktion": 0.5, "strobo": "aus", "hazer": False,
              "grundlicht": {"werte": [{"gruppe": "Farb-PARs", "farbe": "rot", "helligkeit": 0.3}]}}
    vorher = show.baue_bild(0.0)
    show.vorschau.entwurf_setzen("profil", profil)
    assert show.baue_bild(0.1) == vorher and "KI-Profil" not in show.profile.namen()
    show.vorschau.uebernehmen()
    assert "KI-Profil" in show.profile.namen()
    assert show.profil["name"] != "KI-Profil"       # geladen wird nur von Hand


def test_ablauf_ueber_den_server(pfade, show):
    with TestClient(erstelle_app(show)) as client:
        assert client.post("/api/vorschau", json={"art": "szene", "inhalt": NEU}).status_code == 200
        assert client.post("/api/vorschau/uebernehmen").json() == {"name": "Neu"}
        assert "Neu" in client.get("/api/szenen").json()["namen"]
        assert client.post("/api/cuelisten", json=LISTE).status_code == 200
        kaputt = {"name": "x", "cues": [{"name": "a", "szene": "Gibtsnicht"}]}
        assert client.post("/api/cuelisten", json=kaputt).status_code == 400
        assert client.get("/api/cuelisten").json()["namen"] == ["Stück"]
        assert client.post("/api/cuelisten/St%C3%BCck/laden").status_code == 200
        assert client.post("/api/cue/weiter").json()["aktiv"] == "Eins"
        assert client.post("/api/cue/stopp").json()["aktiv"] is None
        assert client.post("/api/fader/9", json={"wert": 1}).status_code == 400


def test_neustart_laedt_letzte_cueliste_ohne_sie_zu_starten(show, pfade):
    neu = Show(pfade)
    assert neu.cues.liste["name"] == "Stück" and neu.cues.index == -1
