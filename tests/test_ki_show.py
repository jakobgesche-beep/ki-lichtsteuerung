"""KI-Lichtdesign: Takt-Tabelle aus der Aufnahme, Claudes Plan prüfen und in eine Song-Show umbauen (ohne echtes Netz)."""
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from lichtsteuerung import daten
from lichtsteuerung.ki_show import SCHEMA, plan_ordnen, show_aus_plan, takt_tabelle
from lichtsteuerung.licht_chat import pruefen, unionen
from lichtsteuerung.probe import analysieren
from lichtsteuerung.show import Show
from werkzeuge import testmusik

SCHLUESSEL = "sk-ant-test-" + "x" * 40


@pytest.fixture(scope="module")
def song():
    """Ein Kunstsong mit bekanntem Aufbau (Intro, Strophe, Überleitung, Refrain ... Schluss), 120 BPM."""
    ton, wahr = testmusik.song_mit_form(120.0, seed=2)
    return ton, wahr, analysieren(ton, "Testsong")


@pytest.fixture
def show(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.automatik_an = False
    return s


def plan_aus_wahrheit(wahr, analyse, **teil_extra):
    """So würde Claude antworten, wenn er die Teile richtig erkennt."""
    einsen = analyse["einsen_s"]
    klassen = {"Intro": "ruhig", "Strophe": "mittel", "Überleitung": "mittel", "Refrain": "stark", "Bridge": "ruhig",
               "Schluss": "ruhig"}
    teile = []
    for teil in wahr["teile"]:
        takt = min(range(len(einsen)), key=lambda i: abs(einsen[i] - teil["start"])) + 1
        teile.append({"name": teil["name"], "von_takt": takt, "klasse": klassen[teil["name"]],
                      "bewegung": "kreis" if teil["name"] == "Refrain" else "keine", "farben": "BA", "puls": "puls",
                      "strobo": teil["name"] == "Refrain", "akzent_takte": [takt] if teil["name"] == "Refrain" else [],
                      "idee": "passt", **teil_extra})
    teile[-2]["klasse"] = "hoehepunkt"           # der letzte Refrain
    return {"song_erkannt": "unbekannt", "farbe_a": "blau", "farbe_b": "rot", "teile": teile,
            "erklaerung": "Strophen ruhig, Refrains kräftig."}


def test_takt_tabelle_zeigt_takte_wiederholungen_und_schlaege(song):
    ton, wahr, analyse = song
    tabelle = takt_tabelle(analyse, ton)
    zeilen = tabelle["text"].splitlines()
    assert tabelle["anzahl"] == len(analyse["einsen_s"]) == len(zeilen) - 1 == len(tabelle["starts"])
    assert zeilen[1].split()[0] == "1" and "▶" in zeilen[1]
    # Der zweite Refrain klingt wie der erste: In seinen Takten steht ein Verweis auf frühere Takte
    zweiter_refrain = [t for t in wahr["teile"] if t["name"] == "Refrain"][1]
    takt = min(range(len(analyse["einsen_s"])), key=lambda i: abs(analyse["einsen_s"][i] - zweiter_refrain["start"]))
    assert any("≈T" in zeile for zeile in zeilen[takt + 1:takt + 9])
    assert len(tabelle["text"]) < 12000                                   # passt gut in eine Anfrage


def test_zu_wenig_takte_ist_eine_klare_meldung():
    with pytest.raises(ValueError, match="zu wenige Takte"):
        takt_tabelle({"einsen_s": [0.0, 2.0], "dauer_s": 4.0}, None)


def test_plan_wird_geordnet_und_repariert():
    teile = plan_ordnen({"teile": [
        {"name": "Refrain", "von_takt": 9, "klasse": "stark", "bewegung": "kreis", "farben": "BA", "puls": "kraeftig",
         "strobo": True, "akzent_takte": [9, 12, 40], "idee": ""},
        {"name": "Intro", "von_takt": 3, "klasse": "ruhig", "bewegung": "keine", "farben": "A", "puls": "atmen",
         "strobo": False, "akzent_takte": [], "idee": ""},
        {"name": "Erfunden", "von_takt": 9, "klasse": "laut", "bewegung": "tanz", "farben": "C", "puls": "x",
         "strobo": False, "akzent_takte": [], "idee": ""},
        {"name": "Schluss", "von_takt": 99, "klasse": "ruhig", "bewegung": "keine", "farben": "A", "puls": "atmen",
         "strobo": False, "akzent_takte": [], "idee": ""}]}, anzahl=20)
    assert [(t["name"], t["von_takt"], t["bis_takt"]) for t in teile] == [
        ("Intro", 1, 9), ("Refrain", 9, 20), ("Schluss", 20, 21)]       # erster Teil ab Takt 1, Doppelte weg
    assert teile[1]["akzent_takte"] == [9, 12]                         # Takt 40 liegt nicht im Teil
    with pytest.raises(ValueError):
        plan_ordnen({"teile": []}, anzahl=20)


def test_aus_dem_plan_wird_eine_gueltige_song_show(song, show):
    ton, wahr, analyse = song
    tabelle = takt_tabelle(analyse, ton)
    plan = plan_aus_wahrheit(wahr, analyse)
    sequenz = show_aus_plan(analyse, plan, tabelle, show.patch, ["blau", "rot", "gold"], show.gobos_der_gruppe,
                            show.positionen, strobo_erlaubt=False)
    assert pruefen(show, sequenz) == []
    assert sequenz["zeitcode"] == sorted(sequenz["zeitcode"]) and len(sequenz["zeitcode"]) == len(sequenz["cues"])
    karte = sequenz["song"]["teile"]
    assert [t["name"] for t in karte] == [t["name"] for t in wahr["teile"]]
    for teil, echt in zip(karte[1:], wahr["teile"][1:]):
        assert abs(teil["start"] - echt["start"]) < 0.1                 # Zeiten kommen aus den gemessenen Takten
        assert sequenz["zeitcode"][teil["cue"]] <= teil["start"] + 0.3
    assert sequenz["farben"] == ["blau", "rot"]
    # Strobo nur, wenn das Profil ihn erlaubt
    blitze = [w for c in sequenz["cues"] for w in c["werte"] if w.get("strobo_hz")]
    assert blitze == []
    mit = show_aus_plan(analyse, plan, tabelle, show.patch, ["blau", "rot"], show.gobos_der_gruppe, show.positionen,
                        strobo_erlaubt=True)
    if "Strobo" in show.patch.gruppen():
        assert any(w.get("strobo_hz") for c in mit["cues"] for w in c["werte"])
    # Refrain: Bewegung und Akzent auf dem ersten Takt
    refrain = mit["cues"][karte[3]["cue"]]
    assert any(e["art"] == "kreis" for e in refrain["effekte"]) or refrain["name"] == "Schlag"


def test_farben_ausserhalb_der_palette_werden_ersetzt(song, show):
    ton, wahr, analyse = song
    plan = dict(plan_aus_wahrheit(wahr, analyse), farbe_a="pink", farbe_b="cyan")
    sequenz = show_aus_plan(analyse, plan, takt_tabelle(analyse, ton), show.patch, ["gold", "rot", "warmweiss"],
                            show.gobos_der_gruppe, show.positionen)
    assert set(sequenz["farben"]) <= {"gold", "rot", "warmweiss"}


def test_schema_ohne_unionen():
    assert unionen(SCHEMA) == 0


class FalscherClaude:
    def __init__(self, antworten):
        self.antworten, self.anfragen = list(antworten), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **anfrage):
        self.anfragen.append(anfrage)
        naechste = self.antworten.pop(0)
        if isinstance(naechste, Exception):
            raise naechste
        return naechste


def antwort_json(plan):
    nutzung = SimpleNamespace(input_tokens=9000, output_tokens=3000, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0)
    return SimpleNamespace(stop_reason="end_turn", usage=nutzung,
                           content=[SimpleNamespace(type="thinking", thinking="..."),
                                    SimpleNamespace(type="text", text=json.dumps(plan, ensure_ascii=False))])


def test_ki_design_fragt_claude_und_liefert_einen_entwurf(song, show, monkeypatch):
    ton, wahr, analyse = song
    show.proben.speichern("Testsong", ton, markierungen=[wahr["teile"][3]["start"] + 0.05])
    analyse = show.proben.lesen("Testsong")
    show.ki.schluessel.speichern(SCHLUESSEL)
    falsch = FalscherClaude([antwort_json(plan_aus_wahrheit(wahr, analyse))])
    monkeypatch.setattr(show.ki_design, "_client", lambda: falsch)
    status = show.chat.song_entwerfen("Testsong", "Testsong von der Band", "Refrain soll knallen")
    entwurf = status["entwurf"]
    assert entwurf["art"] == "song" and entwurf["probe"] == "Testsong" and entwurf["quelle"] == "design"
    assert [t["name"] for t in entwurf["teile"]][:4] == ["Intro", "Strophe", "Überleitung", "Refrain"]
    assert show.pult.sequenzen.lesen("Testsong") is None                    # nichts gespeichert vor Übernehmen
    anfrage = falsch.anfragen[0]
    assert anfrage["model"] == "claude-opus-5-5" and anfrage["thinking"] == {"type": "adaptive"}
    assert anfrage["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    nachricht = anfrage["messages"][0]["content"]
    assert "TAKT-TABELLE" in nachricht and "Refrain soll knallen" in nachricht and " D" in nachricht
    assert "Spots" in anfrage["system"] and SCHLUESSEL not in str(anfrage)
    assert show.ki.kosten["design"] > 0
    # Die Vorschau folgt der Aufnahme, sobald sie läuft
    show.chat.entwurf["abspielen"] = True
    monkeypatch.setattr(show.audio, "position_s", lambda: wahr["teile"][3]["start"] + 1.0)
    bild_vorher = show.baue_bild(0.0)
    assert show.chat.entwurf["cue"] >= entwurf["teile"][3]["cue"]
    assert show.baue_bild(0.1) == bild_vorher                                 # nichts geht live
    monkeypatch.setattr(show, "audio_quelle_setzen", lambda *a, **k: "aus")
    show.chat.uebernehmen()
    assert show.pult.sequenzen.lesen("Testsong")["licht_version"] == 3


def test_ki_design_ohne_schluessel_oder_ohne_internet(song, show, monkeypatch):
    ton, _, _ = song
    show.proben.speichern("Testsong", ton)
    with pytest.raises(ValueError, match="Claude-Schlüssel"):
        show.ki_design.entwerfen("Testsong")
    show.ki.schluessel.speichern(SCHLUESSEL)
    anfrage = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    monkeypatch.setattr(show.ki_design, "_client", lambda: FalscherClaude([anthropic.APIConnectionError(request=anfrage)]))
    with pytest.raises(ValueError, match="Kein Internet"):
        show.ki_design.entwerfen("Testsong")
    assert show.chat.entwurf is None
