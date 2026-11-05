"""Das Lichtpult: Programmer, Effekte, Sequenzen mit Tracking, Executoren."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung.buehne import Buehne
from lichtsteuerung.patch import Patch
from lichtsteuerung.pult import pruefe_cue, pruefe_effekt
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show

DIMMER, ROT, BLAU = 0, 1, 3
KOPF_DIMMER = 16


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
    s.automatik_an = False        # dunkle Bühne: man sieht nur, was das Pult macht
    s.profil = {**s.profil, "max_helligkeit": 1.0}
    return s


def kopf(show, bild, nummer=1):
    return next(g for g in show.simulator.lies(bild) if g["id"] == f"kopf-{nummer}")


def cue(name, werte=None, effekte=None, zeit=0.0, folgen=None):
    c = {"name": name, "zeit_s": zeit, "folgen_s": folgen, "werte": werte or []}
    if effekte is not None:
        c["effekte"] = effekte
    return c


# --- Programmer -----------------------------------------------------------------

def test_programmer_geht_sofort_live(show):
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 0.8, "farbe": "rot"})
    bild = show.baue_bild(0.0)
    assert bild[DIMMER] == round(0.8 * 255) and bild[ROT] == 255
    assert bild[6] == 0                        # PAR 2 bleibt aus


def test_blind_nur_in_der_vorschau(show):
    show.pult.programmer.blind = True
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 1, "farbe": "blau"})
    bild = show.baue_bild(0.0)
    assert bild[DIMMER] == 0
    vorschau = next(g for g in show.live_daten()["vorschau"]["geraete"] if g["id"] == "par-1")
    assert vorschau["hell"] == 1 and vorschau["farbe"] == [0, 0, 1]


def test_programmer_leeren_gibt_die_buehne_frei(show):
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 1})
    show.baue_bild(0.0)
    show.pult.programmer.leeren()
    assert show.baue_bild(0.1)[DIMMER] == 0


def test_neue_position_ersetzt_winkel(show):
    p = show.pult.programmer
    p.setzen(["kopf-1"], {"pan": 10, "tilt": 20})
    p.setzen(["kopf-1"], {"position": "Mitte"})
    assert p.werte["kopf-1"] == {"position": "Mitte"}


def test_blackout_schlaegt_den_programmer(show):
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 1})
    show.overrides.blackout = True
    assert show.baue_bild(0.0)[DIMMER] == 0


# --- Effekte --------------------------------------------------------------------

KREIS = {"art": "kreis", "ziel": {"gruppe": "Spots"}, "groesse": 0.6, "tempo": 120, "beats": 4, "verteilung": 0.5}


def test_kreis_bewegt_die_koepfe_und_bleibt_auf_der_buehne(show):
    show.pult.programmer.setzen(["kopf-1", "kopf-2"], {"helligkeit": 1})
    show.pult.programmer.effekt_dazu(KREIS)
    richtungen = set()
    for i in range(80):
        bild = show.baue_bild(i / 40)
        richtungen.add(tuple(round(w, 2) for w in kopf(show, bild)["richtung"]))
        assert not any("Sperrzone" in m for m in show.meldungen)
    assert len(richtungen) > 20


def test_verteilung_versetzt_die_geraete(show):
    show.pult.programmer.setzen(["kopf-1", "kopf-2"], {"helligkeit": 1})
    show.pult.programmer.effekt_dazu(KREIS)
    bild = show.baue_bild(0.5)
    assert kopf(show, bild, 1)["richtung"] != kopf(show, bild, 2)["richtung"]


def test_ueber_das_publikum_aber_nie_auf_kopfhoehe(show):
    """Der Effekt fährt übers Publikum. Die Sperrzone darf dabei kein einziges Mal anschlagen."""
    show.pult.programmer.setzen(["kopf-1", "kopf-2"], {"helligkeit": 1})
    show.pult.programmer.effekt_dazu({"art": "publikum", "ziel": {"gruppe": "Spots"}, "groesse": 1.0,
                                      "tempo": 120, "beats": 8})
    for i in range(160):
        bild = show.baue_bild(i / 40)
        assert not any("Sperrzone" in m for m in show.meldungen)
        assert kopf(show, bild)["richtung"][1] < 0          # zeigt Richtung Publikum
        assert kopf(show, bild)["hell"] == 1


def test_dimmer_welle_laeuft_durch(show):
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 1})
    show.pult.programmer.effekt_dazu({"art": "dimmer_welle", "ziel": {"geraete": ["par-1"]}, "tempo": 60, "beats": 1})
    werte = {show.baue_bild(i / 10)[DIMMER] for i in range(10)}
    assert min(werte) < 60 and max(werte) > 200


def test_farbwechsel(show):
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 1})
    show.pult.programmer.effekt_dazu({"art": "farbwechsel", "ziel": {"geraete": ["par-1"]}, "tempo": 60,
                                      "beats": 2, "farben": ["rot", "blau"]})
    a, b = show.baue_bild(0.1), show.baue_bild(1.1)
    assert (a[ROT], a[BLAU]) == (255, 0) and (b[ROT], b[BLAU]) == (0, 255)


def test_effekt_tempo_folgt_der_musik(show):
    effekte = show.pult.effekte
    effekte.takt(1.0, 128)
    assert effekte.musik_beats == pytest.approx(128 / 60)


def test_gleicher_effekt_ersetzt_den_alten(show):
    p = show.pult.programmer
    p.effekt_dazu(KREIS)
    p.effekt_dazu({**KREIS, "groesse": 0.2})
    assert len(p.effekte) == 1 and p.effekte[0]["groesse"] == 0.2


def test_neue_bewegung_ersetzt_die_alte_aber_nicht_den_dimmer(show):
    p = show.pult.programmer
    p.effekt_dazu(KREIS)
    p.effekt_dazu({**KREIS, "art": "dimmer_welle"})
    p.effekt_dazu({**KREIS, "art": "acht"})
    assert sorted(e["art"] for e in p.effekte) == ["acht", "dimmer_welle"]


@pytest.mark.parametrize("effekt", [
    {"art": "tanz", "ziel": {"gruppe": "Spots"}},
    {"art": "kreis", "ziel": {"gruppe": "Gibtsnicht"}},
    {"art": "kreis", "ziel": {}},
    {"art": "kreis", "ziel": {"gruppe": "Spots"}, "groesse": 3},
    {"art": "kreis", "ziel": {"gruppe": "Spots"}, "tempo": 5000},
    {"art": "farbwechsel", "ziel": {"gruppe": "Spots"}, "farben": ["blubb"]},
])
def test_kaputte_effekte_werden_abgelehnt(show, effekt):
    assert pruefe_effekt(effekt, show.patch.gruppen(), [g["id"] for g in show.patch.geraete])


# --- Sequenzen und Executoren ------------------------------------------------------

def sequenz_anlegen(show, cues, name="Show"):
    show.pult.sequenz_speichern({"name": name, "cues": cues})
    show.pult.executor(1).belegen(show.pult.sequenzen.lesen(name))


def test_go_plus_go_minus(show):
    sequenz_anlegen(show, [cue("Rot", [{"gruppe": "Farb-PARs", "farbe": "rot", "helligkeit": 1}]),
                           cue("Blau", [{"gruppe": "Farb-PARs", "farbe": "blau"}])])
    show.pult.go(1, 0.0)
    assert show.baue_bild(0.1)[ROT] == 255
    show.pult.go(1, 1.0)
    bild = show.baue_bild(1.1)
    assert bild[BLAU] == 255 and bild[ROT] == 0
    assert bild[DIMMER] == 255           # Tracking: Helligkeit aus Cue 1 bleibt stehen
    show.pult.go(1, 2.0, -1)
    assert show.baue_bild(2.1)[ROT] == 255


def test_nach_dem_letzten_cue_geht_es_von_vorn_los(show):
    sequenz_anlegen(show, [cue("A", [{"geraet": "par-1", "helligkeit": 1}]), cue("B", [{"geraet": "par-1", "helligkeit": 0.5}])])
    for t in (0, 1, 2):
        show.pult.go(1, t)
    assert show.pult.executor(1).index == 0


def test_ueberblendzeit(show):
    sequenz_anlegen(show, [cue("A", [{"geraet": "par-1", "helligkeit": 1}], zeit=2.0)])
    show.pult.go(1, 0.0)
    werte = [show.baue_bild(t)[DIMMER] for t in (0.0, 1.0, 2.0)]
    assert werte[0] < werte[1] < werte[2] == 255


def test_folgezeit_startet_den_naechsten_cue(show):
    sequenz_anlegen(show, [cue("A", [{"geraet": "par-1", "helligkeit": 1}], folgen=1.0),
                           cue("B", [{"geraet": "par-1", "helligkeit": 0.2}])])
    show.pult.go(1, 0.0)
    show.baue_bild(0.5)
    assert show.pult.executor(1).index == 0
    show.baue_bild(1.1)
    assert show.pult.executor(1).index == 1


def test_fader_blendet_ueber_die_automatik(show):
    show.automatik_an = True
    sequenz_anlegen(show, [cue("Blau", [{"gruppe": "Farb-PARs", "farbe": "blau", "helligkeit": 1}])])
    show.pult.go(1, 0.0)
    show.pult.executor(1).fader = 0.0
    unten = show.baue_bild(0.1)
    show.pult.executor(1).fader = 1.0
    oben = show.baue_bild(0.2)
    assert unten[ROT] > 0 and oben[ROT] == 0 and oben[BLAU] == 255


def test_executor_aus_blendet_weg(show):
    sequenz_anlegen(show, [cue("A", [{"geraet": "par-1", "helligkeit": 1}])])
    show.pult.go(1, 0.0)
    show.baue_bild(0.1)
    show.pult.executor(1).aus(1.0)
    assert 0 < show.baue_bild(1.5)[DIMMER] < 255
    assert show.baue_bild(2.1)[DIMMER] == 0


def test_zuletzt_gestarteter_executor_liegt_oben(show):
    show.pult.sequenz_speichern({"name": "Rot", "cues": [cue("r", [{"geraet": "par-1", "farbe": "rot", "helligkeit": 1}])]})
    show.pult.sequenz_speichern({"name": "Blau", "cues": [cue("b", [{"geraet": "par-1", "farbe": "blau", "helligkeit": 1}])]})
    show.pult.executor(1).belegen(show.pult.sequenzen.lesen("Rot"))
    show.pult.executor(2).belegen(show.pult.sequenzen.lesen("Blau"))
    show.pult.go(1, 0.0)
    show.pult.go(2, 0.1)
    assert show.baue_bild(0.2)[BLAU] == 255
    show.pult.go(1, 0.3)
    assert show.baue_bild(0.4)[ROT] == 255


def test_effekte_im_cue_und_tracking_der_effekte(show):
    sequenz_anlegen(show, [cue("Kreis", [{"gruppe": "Spots", "helligkeit": 1}], [KREIS]),
                           cue("Rot", [{"gruppe": "Spots", "farbe": "rot"}]),
                           cue("Stopp", [], [])])
    show.pult.go(1, 0.0)
    a = kopf(show, show.baue_bild(0.1))["richtung"]
    b = kopf(show, show.baue_bild(0.6))["richtung"]
    assert a != b
    show.pult.go(1, 1.0)                     # Cue 2 hat keine Effekte: Der Kreis läuft weiter
    a = kopf(show, show.baue_bild(1.1))["richtung"]
    b = kopf(show, show.baue_bild(1.6))["richtung"]
    assert a != b and kopf(show, show.baue_bild(1.7))["farbe"] == [1, 0, 0]
    show.pult.go(1, 2.0)                     # Cue 3 setzt "effekte": [] und hält an
    a = kopf(show, show.baue_bild(2.1))["richtung"]
    assert kopf(show, show.baue_bild(2.6))["richtung"] == a


def test_programmer_als_cue_speichern_und_wieder_laden(show):
    p = show.pult.programmer
    p.setzen(["kopf-1", "kopf-2"], {"helligkeit": 1, "farbe": "rot", "gobo": "Rot"})
    p.effekt_dazu(KREIS)
    sequenz = show.pult.cue_speichern("Weihnachten", "Rot dreht", 2.0, None)
    assert sequenz["cues"][0]["effekte"][0]["art"] == "kreis"
    assert pruefe_cue(sequenz["cues"][0], show.patch, show.positionen) == []
    p.leeren()
    p.aus_cue(sequenz["cues"][0], show.patch)
    assert p.werte["kopf-2"]["farbe"] == "rot" and p.effekte[0]["art"] == "kreis"


def test_leerer_programmer_laesst_sich_nicht_speichern(show):
    with pytest.raises(ValueError):
        show.pult.cue_speichern("X", "leer", 1.0, None)


def test_cue_ueberschreiben(show):
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 1})
    show.pult.cue_speichern("S", "eins", 1, None)
    show.pult.programmer.setzen(["par-1"], {"helligkeit": 0.3})
    sequenz = show.pult.cue_speichern("S", "eins neu", 1, None, nummer=1)
    assert len(sequenz["cues"]) == 1 and sequenz["cues"][0]["werte"][0]["helligkeit"] == 0.3


def test_cue_ueberlebt_den_geraetetausch(show):
    sequenz_anlegen(show, [cue("Rot", [{"gruppe": "Farb-PARs", "farbe": "rot", "helligkeit": 1}])])
    show.patch.tauschen("par-1", "test/par", "4")
    show.aufbauen()
    show.pult.go(1, 0.0)
    bild = show.baue_bild(0.1)
    assert bild[0] == 255 and bild[3] == 255      # Rot und Dimmer an den neuen Stellen


def test_belegung_bleibt_nach_neustart(show, pfade):
    sequenz_anlegen(show, [cue("A", [{"geraet": "par-1", "helligkeit": 1}])])
    show.pult.belegung_speichern()
    neu = Show(pfade)
    assert neu.pult.executor(1).sequenz["name"] == "Show" and neu.pult.executor(1).index == -1


def test_kaputte_sequenz_wird_abgelehnt(show):
    with pytest.raises(ValueError):
        show.pult.sequenz_speichern({"name": "x", "cues": [cue("a", [{"gruppe": "Gibtsnicht", "helligkeit": 1}])]})


def test_automatik_aus_macht_dunkel_automatik_an_bringt_grundlicht(show):
    assert show.baue_bild(0.0)[DIMMER] == 0
    show.automatik_an = True
    assert show.baue_bild(0.1)[DIMMER] > 0


# --- Profil-Entwürfe gehen weiter nur über Vorschau und Übernehmen ---------------

PROFIL = {"name": "KI-Profil", "palette": ["rot"], "max_helligkeit": 0.5, "bewegung": "aus",
          "beat_reaktion": 0.5, "strobo": "aus", "hazer": False,
          "grundlicht": {"werte": [{"gruppe": "Farb-PARs", "farbe": "rot", "helligkeit": 0.3}]}}


def test_profil_entwurf_geht_nicht_live_und_wird_erst_beim_uebernehmen_gespeichert(show):
    vorher = show.baue_bild(0.0)
    show.vorschau.entwurf_setzen("profil", PROFIL)
    assert show.baue_bild(0.1) == vorher and "KI-Profil" not in show.profile.namen()
    show.vorschau.uebernehmen()
    assert "KI-Profil" in show.profile.namen() and show.profil["name"] != "KI-Profil"


def test_kaputter_profil_entwurf(show):
    with pytest.raises(ValueError):
        show.vorschau.entwurf_setzen("profil", {**PROFIL, "palette": []})


# --- Über den Server ----------------------------------------------------------------

def test_ablauf_ueber_den_server(show):
    with TestClient(erstelle_app(show)) as client:
        info = client.get("/api/pult").json()
        koepfe = [g for g in info["geraete"] if g["beweglich"]]
        assert len(koepfe) == 2 and koepfe[0]["farbe"] == "rad" and info["effekte"]["kreis"] == "Kreis"
        assert client.post("/api/programmer/werte", json={"geraete": [], "werte": {"helligkeit": 1}}).status_code == 400
        assert client.post("/api/programmer/werte", json={"geraete": ["par-1"], "werte": {"helligkeit": 7}}).status_code == 400
        client.post("/api/programmer/werte", json={"geraete": ["par-1", "par-2"], "werte": {"helligkeit": 1, "farbe": "rot"}})
        client.post("/api/programmer/effekt", json={**KREIS})
        sequenz = client.post("/api/sequenzen/Weihnachten/speichern", json={"cue_name": "Rot", "zeit_s": 1}).json()
        assert sequenz["cues"][0]["name"] == "Rot"
        client.post("/api/programmer/leeren")
        client.post("/api/executor/1/belegen", json={"sequenz": "Weihnachten"})
        assert client.post("/api/go/plus").json()["executoren"][0]["index"] == 0
        assert client.post("/api/executor/1/fader", json={"wert": 0.5}).json()["executoren"][0]["fader"] == 0.5
        assert client.post("/api/executor/1/aus").json()["executoren"][0]["index"] == -1
        assert client.post("/api/executor/9/go").status_code == 400
        assert client.post("/api/sequenzen/Weihnachten/cue/1/laden").json()["programmer"]["effekte"]
        assert client.delete("/api/sequenzen/Weihnachten").json()["sequenzen"] == []
