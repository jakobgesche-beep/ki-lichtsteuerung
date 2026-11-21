"""KI-Regie: Claude sagt, was los ist und welcher Look passt; die Engine wechselt im Takt und hält die Grenzen ein."""
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.audio.analyse import Messwerte
from lichtsteuerung.buehne import Buehne
from lichtsteuerung.engine import LOOKS, REGIE_GUELTIG_S, Engine
from lichtsteuerung.licht_chat import unionen
from lichtsteuerung.patch import Patch
from lichtsteuerung.regie import KiRegie, Lagebuch, lage_text, schema
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show
from lichtsteuerung.sicherheit import Grenzen

SCHLUESSEL = "sk-ant-test-" + "x" * 40
GRUND = {"werte": [{"gruppe": "Farb-PARs", "farbe": "warmweiss", "helligkeit": 0.4}]}
PARTY = {"name": "Party", "palette": ["rot", "blau", "gruen"], "max_helligkeit": 1.0, "bewegung": "voll",
         "beat_reaktion": 1.0, "strobo": "aus", "hazer": False, "grundlicht": GRUND}
LOOK = {look.name: look for look in LOOKS}


@pytest.fixture
def engine(pfade, katalog):
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("test/par", "6", 2, "PAR 1-2", gruppen=["Farb-PARs"])
    patch.hinzufuegen("test/kopf", "7", 1, "Kopf", gruppen=["Spots"])
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("kopf", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend", "drehung_grad": 180})
    return Engine(patch, buehne, {"Mitte": {"x": 0, "y": 2, "z": 2.4}}, Grenzen(3, 5, 30))


def spielen(engine, profil, sekunden, von=0.0, staerke=0.7, rede=False, tempo=120.0, eins_alle=4):
    """Musik mit Beats (und Takt-Einsen) für die Engine, 40 Bilder pro Sekunde."""
    periode = 60.0 / tempo
    naechster, beat = von, 0
    zustand = None
    for i in range(int(sekunden * 40)):
        jetzt = von + i / 40
        schlag = jetzt >= naechster
        if schlag:
            naechster += periode
            beat += 1
        m = Messwerte(beat=schlag, eins=schlag and beat % eins_alle == 1, tempo_bpm=tempo, bass=staerke,
                      energie=staerke, intensitaet=staerke, leise=False, rede=rede, pegel=0.1)
        zustand = engine.bewerte(m, profil, jetzt)
    return zustand, von + sekunden


def entscheidung(look, lage="refrain", wechsel="naechste_phrase", farben=None):
    return {"hoere": "", "lage": lage, "look": look, "wechsel": wechsel, "farben": farben}


def test_claudes_look_kommt_im_takt_nicht_sofort(engine):
    _, t = spielen(engine, PARTY, 10.0, staerke=0.85)
    vorher = engine.look
    ziel = next(l for l in LOOKS if l.stufe == 3 and l != vorher)
    engine.regie_setzen(entscheidung(ziel.name, farben=("blau", "gruen")), t)
    engine.bewerte(Messwerte(tempo_bpm=120, energie=0.85, intensitaet=0.85, leise=False), PARTY, t + 0.01)
    assert engine.look == vorher                       # kein Wechsel zwischen zwei Schlägen
    _, t = spielen(engine, PARTY, 20.0, von=t + 0.02, staerke=0.85)
    assert engine.look == ziel and engine.farben_paar == ("blau", "gruen")
    assert "KI-Regie" in engine.zustand_text


def test_bei_lauter_musik_nie_schwaecher_als_die_engine(engine):
    """Getestet mit dem echten Claude: Er hielt ein Schlagzeug-Solo einmal für eine ruhige Strophe."""
    _, t = spielen(engine, PARTY, 10.0, staerke=0.95)
    engine.regie_setzen(entscheidung("Ruhe", lage="strophe", wechsel="jetzt"), t)
    spielen(engine, PARTY, 3.0, von=t, staerke=0.95)
    assert engine.look.stufe == 3


def test_hoechstens_eine_stufe_kraeftiger_als_die_engine(engine):
    """Eine Rede, die Claude für ein Solo hält, darf nicht wie ein Höhepunkt aussehen."""
    _, t = spielen(engine, PARTY, 10.0, staerke=0.2)
    engine.regie_setzen(entscheidung("Höhepunkt", lage="solo", wechsel="jetzt"), t)
    spielen(engine, PARTY, 3.0, von=t, staerke=0.2)
    assert engine.look.stufe <= 1


def test_claude_ueberstimmt_nie_die_eigene_rede_erkennung(engine):
    _, t = spielen(engine, PARTY, 6.0, staerke=0.8)
    engine.regie_setzen(entscheidung("Höhepunkt", lage="schlagzeug_solo", wechsel="jetzt"), t)
    spielen(engine, PARTY, 3.0, von=t, staerke=0.8, rede=True)
    assert engine.musik_anteil == 0.0 and "Rede" in engine.zustand_text


def test_ansage_von_claude_macht_ruhig_aber_nicht_bei_kraeftiger_musik(engine):
    _, t = spielen(engine, PARTY, 6.0, staerke=0.3)
    engine.regie_setzen(entscheidung("Ruhe", lage="ansage", wechsel="jetzt"), t)
    spielen(engine, PARTY, 3.0, von=t, staerke=0.3)
    assert engine.musik_anteil == 0.0 and "Ansage" in engine.zustand_text
    _, t = spielen(engine, PARTY, 6.0, von=t + 3, staerke=0.3)
    engine.regie_setzen(entscheidung("Ruhe", lage="applaus", wechsel="jetzt"), t)
    spielen(engine, PARTY, 3.0, von=t, staerke=0.9)
    assert engine.musik_anteil == 1.0                    # laut: Claudes "Applaus" gilt hier nicht


def test_entscheidung_verfaellt_und_die_engine_macht_allein_weiter(engine):
    _, t = spielen(engine, PARTY, 6.0)
    engine.regie_setzen(entscheidung("Kreis"), t)
    spielen(engine, PARTY, REGIE_GUELTIG_S + 1, von=t)
    assert engine.regie is None


def test_profil_ohne_bewegung_bekommt_einen_stehenden_look(engine):
    ruhig = {**PARTY, "bewegung": "aus"}
    _, t = spielen(engine, ruhig, 10.0, staerke=0.9)
    engine.regie_setzen(entscheidung("Kreis", wechsel="jetzt"), t)
    spielen(engine, ruhig, 3.0, von=t, staerke=0.9)
    assert engine.look.bewegung is None


def test_ruhige_musik_nach_einem_falschen_drop_beendet_das_drop_licht(engine):
    _, t = spielen(engine, PARTY, 4.0, staerke=0.3)
    engine.drop_zeit, engine.drop_beat = t, engine.beats            # die Automatik meint: Drop
    assert engine.drop_laeuft()
    engine.regie_setzen(entscheidung("Ruhe schwenkt", lage="ruhige_musik"), t + 2.0)
    spielen(engine, PARTY, 1.0, von=t + 2.0, staerke=0.3)
    assert not engine.drop_laeuft()


# --- Lagebuch und Nachricht ----------------------------------------------------------------

def test_lagebuch_fasst_pro_sekunde_zusammen_und_tempo_nur_mit_schlaegen():
    buch = Lagebuch()
    for i in range(40 * 6):
        jetzt = i / 40
        rede = jetzt >= 3.0
        buch.messen(Messwerte(beat=(not rede and i % 20 == 0), tempo_bpm=146, energie=0.6, pegel=0.05,
                              leise=False, rede=rede), jetzt)
    eimer = buch.letzte(6)
    assert 5 <= len(eimer) <= 6 and eimer[0]["tempo"] == 146 and eimer[-1]["tempo"] == 0    # Rede: kein Tempo
    assert eimer[-1]["rede"] == 1.0 and buch.lokal == "Rede"
    text = lage_text(buch, 6.0)
    assert "Eigene Erkennung" in text and "Rede seit 3 s" in text and "NEUESTE ZUERST" in text
    zeilen = [z for z in text.splitlines() if z.startswith("vor")]
    assert zeilen[0].startswith("vor   0") and "| - |" in zeilen[0]                         # neueste oben


def test_schema_nur_mit_farben_der_palette_und_ohne_unionen():
    s = schema(["rot", "blau"])
    assert s["properties"]["farbe_a"]["enum"] == ["rot", "blau"] and unionen(s) == 0
    assert KiRegie.pruefen({"lage": "refrain", "look": "Kreis", "farbe_a": "rot", "farbe_b": "lila",
                            "wechsel": "jetzt"}, ["rot", "blau"])["farben"] is None
    assert KiRegie.pruefen({"lage": "tanzen", "look": "Kreis"}, ["rot"]) is None
    assert KiRegie.pruefen({"lage": "refrain", "look": "Disco"}, ["rot"]) is None


# --- Mit der ganzen Show und einem falschen Claude -----------------------------------------

@pytest.fixture
def show(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    daten.einrichten(tmp_path / "d")
    return Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))


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


def antwort(**entscheid):
    inhalt = {"hoere": "Lauter Refrain.", "lage": "refrain", "look": "Kreis", "farbe_a": "rot", "farbe_b": "blau",
              "wechsel": "naechste_phrase", **entscheid}
    nutzung = SimpleNamespace(input_tokens=2500, output_tokens=120, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0)
    return SimpleNamespace(stop_reason="end_turn", usage=nutzung,
                           content=[SimpleNamespace(type="text", text=json.dumps(inhalt))])


def musik_messen(show, sekunden=6.0):
    for i in range(int(sekunden * 40)):
        show.regie.messen(Messwerte(beat=i % 20 == 0, tempo_bpm=120, energie=0.8, intensitaet=0.8, pegel=0.1,
                                    leise=False), i / 40)


def test_regie_fragt_claude_richtig_und_gibt_die_entscheidung_an_die_engine(show, monkeypatch):
    show.ki.schluessel.speichern(SCHLUESSEL)
    show.profil = {**show.profil, "palette": ["rot", "blau"], "beat_reaktion": 0.8}
    show.automatik_an = True
    show.regie.einschalten(True)
    falsch = FalscherClaude([antwort()])
    monkeypatch.setattr(show.regie, "_client", lambda: falsch)
    musik_messen(show)
    entscheidung = show.regie.takt(6.0)
    assert entscheidung["look"] == "Kreis" and show.engine.regie["look"] == "Kreis"
    anfrage = falsch.anfragen[0]
    assert anfrage["model"] == "claude-haiku-5-5" and anfrage["output_config"]["effort"] == "low"
    assert anfrage["output_config"]["format"]["schema"]["properties"]["farbe_a"]["enum"] == ["rot", "blau"]
    assert "Eigene Erkennung" in anfrage["messages"][0]["content"] and SCHLUESSEL not in str(anfrage)
    assert show.ki.kosten["regie"] > 0
    status = show.regie.status(7.0)
    assert status["an"] and status["letzte"]["look"] == "Kreis" and status["letzte"]["gilt"]


def test_regie_fragt_nicht_ohne_schluessel_bei_override_song_show_oder_ueber_dem_limit(show, monkeypatch):
    show.automatik_an = True
    show.profil = {**show.profil, "beat_reaktion": 0.8}
    show.regie.einschalten(True)
    musik_messen(show)
    assert show.regie.takt(6.0) is None and "Schlüssel" in show.regie.meldung
    show.ki.schluessel.speichern(SCHLUESSEL)
    show.overrides.blackout = True
    assert show.regie.takt(6.0) is None and "Override" in show.regie.meldung
    show.overrides.blackout = False
    show.song.folger = object()
    assert show.regie.takt(6.0) is None and "Song-Show" in show.regie.meldung
    show.song.folger = None
    show.ki.kosten["regie"] = 100.0
    assert show.regie.takt(6.0) is None and "Limit" in show.regie.meldung


def test_ohne_internet_macht_die_automatik_allein_weiter(show, monkeypatch):
    show.ki.schluessel.speichern(SCHLUESSEL)
    show.automatik_an = True
    show.profil = {**show.profil, "beat_reaktion": 0.8}
    show.regie.einschalten(True)
    anfrage = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    monkeypatch.setattr(show.regie, "_client", lambda: FalscherClaude([anthropic.APIConnectionError(request=anfrage)]))
    musik_messen(show)
    assert show.regie.takt(6.0) is None and "kein Internet" in show.regie.meldung and show.engine.regie is None


def test_regie_schalter_ueber_den_server_und_er_wird_gemerkt(show, tmp_path):
    with TestClient(erstelle_app(show)) as client:
        assert client.get("/api/ki").json()["regie"]["an"] is False      # ohne Schlüssel beim ersten Start aus
        assert client.post("/api/ki/regie", json={"an": True}).json()["an"] is True
        assert daten.lese_json(show.pfade.sitzung)["ki_regie"] is True
        assert client.get("/api/ki").json()["regie"]["an"] is True
    neu = Show(show.pfade)
    assert neu.regie.an is True
