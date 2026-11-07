"""Probe: Analyse der Songteile, gebaute Show, Nachspielen, Patchplan."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.audio.quellen import ABTASTRATE, erzeuge_takt
from lichtsteuerung.patchplan import dip, eintraege
from lichtsteuerung.probe import analysieren
from lichtsteuerung.pult import pruefe_sequenz
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show

WECHSEL = [16, 40, 64, 88, 112]


def beispielsong():
    rng = np.random.default_rng(3)

    def teil(sek, laut, rauschen=0.0):
        ton = erzeuge_takt(120, sek) * laut
        return ton + (rng.standard_normal(len(ton)) * rauschen).astype("float32")
    return np.concatenate([teil(16, 0.05), teil(24, 0.25), teil(24, 0.8, 0.08),
                           teil(24, 0.25), teil(24, 0.8, 0.08), teil(12, 0.05)])


@pytest.fixture(scope="module")
def analyse():
    return analysieren(beispielsong(), "Testsong")


def test_findet_alle_wechsel_auf_zwei_sekunden_genau(analyse):
    starts = [t["start"] for t in analyse["teile"]][1:]
    assert len(starts) == len(WECHSEL)
    assert all(abs(a - b) <= 2.0 for a, b in zip(starts, WECHSEL))


def test_tempo(analyse):
    assert analyse["tempo_bpm"] == pytest.approx(120, rel=0.04)


def test_gleiche_teile_bekommen_denselben_buchstaben(analyse):
    gruppen = [t["gruppe"] for t in analyse["teile"]]
    assert gruppen[1] == gruppen[3] and gruppen[2] == gruppen[4] and gruppen[1] != gruppen[2]


def test_namen_und_staerke(analyse):
    namen = [t["name"] for t in analyse["teile"]]
    assert namen[0] == "Intro" and namen[-1] == "Schluss" and namen[2] == namen[4] == "Refrain"
    assert analyse["teile"][2]["klasse"] in ("stark", "hoehepunkt")
    assert analyse["teile"][0]["klasse"] == "ruhig"


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    return s


def test_gebaute_show_ist_gueltig_und_gleiche_teile_sehen_gleich_aus(show, analyse):
    daten.schreibe_json(show.pfade.proben / "testsong.json", analyse)
    sequenz = show.show_aus_probe("Testsong")
    assert pruefe_sequenz(sequenz, show.patch, show.positionen) == []
    assert len(sequenz["cues"]) == 6 and len(sequenz["zeitcode"]) == 6
    assert sequenz["cues"][2]["werte"] == sequenz["cues"][4]["werte"]
    assert sequenz["cues"][2]["effekte"] == sequenz["cues"][4]["effekte"]
    assert sequenz["cues"][1]["werte"] != sequenz["cues"][2]["werte"]
    assert "Takte" in sequenz["cues"][1]["name"]


def test_gebaute_show_bleibt_sicher(show, analyse):
    """Jeden Cue eine Weile laufen lassen: nie Sperrzone, nie Strobo."""
    daten.schreibe_json(show.pfade.proben / "testsong.json", analyse)
    show.show_aus_probe("Testsong")
    show.pult.executor(1).belegen(show.pult.sequenzen.lesen("Testsong"))
    zeit = 0.0
    for _ in range(6):
        show.pult.go(1, zeit)
        for _ in range(80):
            zeit += 0.025
            show.baue_bild(zeit)
            assert not any("Sperrzone" in m for m in show.meldungen)
            assert not show.blitzt


def test_aufnahme_speichern_analysieren_und_nachspielen(show):
    with TestClient(erstelle_app(show)) as client:
        show.audio.quelle = object()            # tut so, als liefe ein Eingang
        assert client.post("/api/proben/aufnahme", json={"name": "Song 1"}).status_code == 200
        show.audio.aufnahme = [beispielsong()]
        antwort = client.post("/api/proben/stopp").json()
        show.audio.quelle = None
        assert len(antwort["analyse"]["teile"]) == 6 and antwort["sequenz"]["name"] == "Song 1"
        assert show.proben.ton_pfad("Song 1").exists()
        status = client.post("/api/proben/Song%201/abspielen", json={"executor": 2}).json()
        assert status["executoren"][1]["sequenz"] == "Song 1" and show.pult.executor(2).zeitcode
        show.audio.quelle.stelle = int(70 * ABTASTRATE)    # Aufnahme steht bei 1:10
        show.baue_bild(1000.0)
        assert show.pult.executor(2).index == 3
        client.post("/api/executor/2/go")                  # Go von Hand beendet das Mitlaufen
        assert not show.pult.executor(2).zeitcode
        show.audio.stoppen()


def test_ohne_tonquelle_keine_aufnahme(show):
    with TestClient(erstelle_app(show)) as client:
        assert client.post("/api/proben/aufnahme", json={"name": "X"}).status_code == 400
        assert client.post("/api/proben/aufnahme", json={"name": ""}).status_code == 400


def test_zu_kurze_aufnahme(show):
    with pytest.raises(ValueError):
        show.proben.speichern("kurz", np.zeros(ABTASTRATE))


# --- Patchplan ----------------------------------------------------------------

def test_dip_schalter():
    assert dip(1)[:3] == [True, False, False]
    assert dip(49)[:6] == [True, False, False, False, True, True]       # 1 + 16 + 32
    assert sum(2 ** i for i, an in enumerate(dip(511)) if an) == 511


def test_patchplan_sortiert_und_vollstaendig(show):
    plan = eintraege(show)
    assert len(plan) == len(show.patch.geraete)
    traverse = [e for e in plan if e["ort"] == "Traverse"]
    assert [e["x"] for e in traverse] == sorted(e["x"] for e in traverse)
    front = next(e for e in plan if e["name"] == "Front 1")
    assert (front["adresse"], front["kanaele"], front["haengend"]) == (49, 12, True)


def test_patchplan_seite(show):
    with TestClient(erstelle_app(show)) as client:
        html = client.get("/patchplan").text
    assert "Patchplan" in html and "049" in html and "12 Kanäle" in html


def test_probe_findet_drop_und_aufbau_und_merkt_markierung(show):
    from lichtsteuerung.audio.quellen import erzeuge_edm
    ton, zeit = erzeuge_edm(128)
    analyse = show.proben.speichern("Party", ton, markierungen=[zeit + 0.2])
    assert len(analyse["drops_s"]) == 1 and abs(analyse["drops_s"][0] - zeit) < 0.1
    namen = [t["name"] for t in analyse["teile"]]
    assert "Drop" in namen and namen[namen.index("Drop") - 1] == "Aufbau"
    assert analyse["markiert_s"] == [round(zeit + 0.2, 2)]
    sequenz = show.show_aus_probe("Party")
    drop_cue = sequenz["cues"][namen.index("Drop")]
    assert any(e["art"] == "acht" and e["beats"] == 4 for e in drop_cue["effekte"])
    assert sequenz["cues"][namen.index("Aufbau")]["name"].startswith("Aufbau")
    assert pruefe_sequenz(sequenz, show.patch, show.positionen) == []


def test_markieren_nur_waehrend_der_aufnahme(show):
    with TestClient(erstelle_app(show)) as client:
        assert client.post("/api/proben/markieren").status_code == 400

        class Quelle:
            def schliessen(self):
                pass
        show.audio.quelle = Quelle()
        client.post("/api/proben/aufnahme", json={"name": "Song"})
        show.audio.aufnahme = [np.zeros(44100, dtype="float32")]
        assert client.post("/api/proben/markieren").json() == {"markierungen": 1}
        show.audio.aufnahme = [beispielsong()]
        assert client.post("/api/proben/stopp").json()["analyse"]["markiert_s"] == [1.0]
        show.audio.quelle = None


def test_show_hat_nur_zwei_songfarben_und_akzente_an_markierungen(show, analyse):
    show.patch.hinzufuegen("technik-ag/strobo-ohne-namen", "2 Kanäle: Tempo, Helligkeit", 1, "Strobo", start=200)
    show.aufbauen()
    analyse = {**analyse, "markiert_s": [50.0, 50.3, 70.0]}
    daten.schreibe_json(show.pfade.proben / "testsong.json", analyse)
    sequenz = show.show_aus_probe("Testsong")
    farben = {w["farbe"] for c in sequenz["cues"] for w in c["werte"] if "farbe" in w}
    assert farben <= set(sequenz["farben"]) | {"weiss"} and len(sequenz["farben"]) == 2
    akzente = [i for i, c in enumerate(sequenz["cues"]) if c["name"] == "Akzent"]
    assert len(akzente) == 2                             # 50.0 und 70.0, 50.3 ist zu dicht dran
    assert sequenz["cues"][akzente[0]]["folgen_s"] == 0.4
    assert sequenz["cues"][akzente[0] + 1]["name"].endswith("weiter")
    assert sequenz["zeitcode"] == sorted(sequenz["zeitcode"]) and len(sequenz["zeitcode"]) == len(sequenz["cues"])
    starke = [c for c in sequenz["cues"] if "Refrain" in c["name"]]
    assert any(w.get("gruppe") == "Strobo" and w["strobo_hz"] > 0 for w in starke[0]["werte"])
    strophe = next(c for c in sequenz["cues"] if c["name"].startswith("Strophe"))
    assert all(w.get("strobo_hz", 0) == 0 for w in strophe["werte"])
    assert pruefe_sequenz(sequenz, show.patch, show.positionen) == []
