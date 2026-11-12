"""Licht-Chat: Vorschlag nur in der Vorschau, Prüfung, Übernehmen auf einen Fader, Claude-Anbindung (ohne echtes Netz)."""
import os
import sys
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.licht_chat import MODELL, aus_vorschlag, einfach_verstehen, pruefen
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show

SCHLUESSEL = "sk-ant-test-" + "x" * 40


@pytest.fixture
def show(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.automatik_an = False
    return s


def look(name="Blaue Spots", **cue_felder):
    """So sieht ein Werkzeug-Aufruf von Claude aus (alle Felder da, leere als None)."""
    wert = {"gruppe": "Spots", "geraet": None, "helligkeit": 0.8, "farbe": "blau", "position": "Mitte",
            "gobo": None, "gobo_drehung": None, "strobo_hz": None}
    effekt = {"art": "kreis", "gruppe": "Spots", "groesse": 0.4, "beats": 8.0, "verteilung": 0.5, "tempo": None,
              "tiefe": None, "farben": None, "mitte": None}
    cue = {"name": "Blau", "zeit_s": 2.0, "folgen_s": None, "werte": [wert], "effekte": [effekt]}
    cue.update(cue_felder)
    return {"name": name, "erklaerung": "Spots blau, langsamer Kreis.", "fader": 3, "ersetzt": False, "cues": [cue]}


def antwort(*bloecke, stop="tool_use"):
    nutzung = SimpleNamespace(input_tokens=1200, output_tokens=300, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0)
    return SimpleNamespace(stop_reason=stop, content=list(bloecke), usage=nutzung)


def aufruf(name, eingabe, nummer="1"):
    return SimpleNamespace(type="tool_use", name=name, input=eingabe, id="toolu_" + nummer)


def text(inhalt):
    return SimpleNamespace(type="text", text=inhalt)


class FalscherClaude:
    """Spielt vorher festgelegte Antworten ab und merkt sich jede Anfrage."""

    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.anfragen = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **anfrage):
        self.anfragen.append({**anfrage, "messages": list(anfrage["messages"])})
        naechste = self.antworten.pop(0)
        if isinstance(naechste, Exception):
            raise naechste
        return naechste


def mit_claude(show, monkeypatch, antworten):
    show.chat.schluessel.speichern(SCHLUESSEL)
    falsch = FalscherClaude(antworten)
    monkeypatch.setattr(show.chat, "_client", lambda: falsch)
    return falsch


def test_ohne_schluessel_versteht_der_chat_einfache_saetze_und_nichts_geht_live(show):
    vorher = show.baue_bild(0.0)
    status = show.chat.senden("Spots blau, langsamer Kreis, auf Fader 4")
    assert status["entwurf"]["name"] == "Blau Kreis" and status["entwurf"]["fader"] == 4
    assert status["entwurf"]["quelle"] == "einfach"
    bild = show.baue_bild(0.1)
    assert bild == vorher                                       # nichts geht live
    vorschau = show.live_daten()["chat_vorschau"]["geraete"]
    assert any(g["hell"] > 0 and g["farbe"][2] > 0.9 for g in vorschau)   # aber in der Vorschau blau


def test_uebernehmen_speichert_legt_auf_den_fader_und_oops_nimmt_beides_zurueck(show):
    show.chat.senden("PARs rot, pulsieren im Beat")
    ergebnis = show.chat.uebernehmen(fader=5)
    assert show.pult.executor(5).sequenz["name"] == ergebnis["name"]
    assert show.chat.entwurf is None
    show.pult.rueckgaengig()
    assert show.pult.executor(5).art is None and show.pult.sequenzen.lesen(ergebnis["name"]) is None


def test_unverstaendliches_ohne_internet(show):
    status = show.chat.senden("Wie spät ist es?")
    assert status["entwurf"] is None and "nicht verstanden" in status["anzeige"][-1]["text"]


def test_einfach_versteht_gruppen_farben_positionen(show):
    vorschlag = einfach_verstehen(show, "PARs grün und Köpfe weiß auf Sänger links, in 4 Sekunden")
    cue = vorschlag["sequenz"]["cues"][0]
    assert cue["zeit_s"] == 4.0
    werte = {w["gruppe"]: w for w in cue["werte"]}
    assert werte["Farb-PARs"]["farbe"] == "gruen" and werte["Spots"]["position"] == "Sänger links"
    assert pruefen(show, vorschlag["sequenz"]) == []


def test_pruefung_haelt_strobo_grenze_gobos_und_bewegung_ein(show):
    sequenz = aus_vorschlag(look())
    assert pruefen(show, sequenz) == []
    zu_schnell = aus_vorschlag(look(werte=[{"gruppe": "Spots", "strobo_hz": 10.0}]))
    assert any("strobo_hz" in f for f in pruefen(show, zu_schnell))
    falsches_gobo = aus_vorschlag(look(werte=[{"gruppe": "Spots", "gobo": "Sterne"}]))
    assert any("Gobo" in f for f in pruefen(show, falsches_gobo))
    pars_kreisen = aus_vorschlag(look(effekte=[{"art": "kreis", "gruppe": "Farb-PARs"}]))
    assert any("beweglich" in f for f in pruefen(show, pars_kreisen))
    assert any("Fader 99" in f for f in pruefen(show, sequenz, 99))


def test_claude_korrigiert_sich_nach_pruef_fehler(show, monkeypatch):
    falsch = mit_claude(show, monkeypatch, [
        antwort(aufruf("vorschlag_machen", look(werte=[{"gruppe": "Spots", "geraet": None, "helligkeit": 1.0,
                                                        "farbe": "blau", "position": None, "gobo": "Sterne",
                                                        "gobo_drehung": None, "strobo_hz": None}]))),
        antwort(text("Ich habe das Gobo korrigiert."), aufruf("vorschlag_machen", look(), "2")),
    ])
    status = show.chat.senden("Blaue Spots mit Sternen, langsamer Kreis auf Fader 3")
    assert len(falsch.anfragen) == 2
    zweite = falsch.anfragen[1]
    fehler_ergebnis = zweite["messages"][-1]["content"][0]
    assert fehler_ergebnis["is_error"] and "Gobo" in fehler_ergebnis["content"]
    assert status["entwurf"]["name"] == "Blaue Spots" and status["entwurf"]["quelle"] == "claude"
    # So geht die Anfrage raus: richtiges Modell, feste Werkzeuge, Rückfall bei Ablehnung, Zwischenspeicher
    erste = falsch.anfragen[0]
    assert erste["model"] == MODELL == "claude-opus-5-5"
    assert all(w["strict"] for w in erste["tools"]) and {w["name"] for w in erste["tools"]} == {"vorschlag_machen", "sequenz_lesen"}
    assert erste["fallbacks"] == "default" and erste["betas"] == ["server-side-fallback-2026-07-01"]
    assert erste["cache_control"] == {"type": "ephemeral"} and erste["output_config"] == {"effort": "medium"}
    assert "Spots" in erste["system"] and "[Stand jetzt]" in erste["messages"][0]["content"]
    assert SCHLUESSEL not in str(erste)                         # der Schlüssel steht nie in der Anfrage selbst
    # Nichts live, Vorschau läuft
    show.baue_bild(0.0)
    assert show.live_daten()["chat_vorschau"] is not None
    show.chat.uebernehmen(fader=status["entwurf"]["fader"])
    assert show.pult.executor(3).sequenz["name"] == "Blaue Spots"


def test_claude_liest_eine_sequenz_und_ersetzt_sie(show, monkeypatch):
    show.pult.sequenz_speichern(dict(aus_vorschlag(look(name="Intro")), zeitcode=[0.0]))
    neu = look(name="Intro")
    neu["ersetzt"] = True
    neu["cues"][0]["werte"][0]["farbe"] = "rot"
    falsch = mit_claude(show, monkeypatch, [
        antwort(aufruf("sequenz_lesen", {"name": "Intro"})),
        antwort(aufruf("vorschlag_machen", neu, "2")),
    ])
    show.chat.senden("Mach Intro rot statt blau")
    assert '"name": "Intro"' in falsch.anfragen[1]["messages"][-1]["content"][0]["content"]
    show.chat.uebernehmen()
    gespeichert = show.pult.sequenzen.lesen("Intro")
    assert gespeichert["cues"][0]["werte"][0]["farbe"] == "rot" and gespeichert["zeitcode"] == [0.0]


def test_gleicher_name_ohne_ersetzen_bekommt_eine_nummer(show):
    show.chat.senden("Spots blau, langsamer Kreis")
    show.chat.uebernehmen()
    show.chat.senden("Spots blau, langsamer Kreis")
    assert show.chat.uebernehmen()["name"] == "Blau Kreis 2"


def test_ablehnung_und_nur_text(show, monkeypatch):
    mit_claude(show, monkeypatch, [antwort(stop="refusal"), antwort(text("Welche Farbe soll es sein?"), stop="end_turn")])
    assert "nur Licht" in show.chat.senden("Schreib mir ein Gedicht")["anzeige"][-1]["text"]
    status = show.chat.senden("Mach was Schönes")
    assert status["anzeige"][-1]["text"] == "Welche Farbe soll es sein?" and status["entwurf"] is None


def test_ohne_internet_springt_die_einfache_erkennung_ein(show, monkeypatch):
    anfrage = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    mit_claude(show, monkeypatch, [anthropic.APIConnectionError(request=anfrage)])
    status = show.chat.senden("Spots blau, langsamer Kreis")
    assert status["entwurf"]["quelle"] == "einfach" and "Kein Internet" in status["anzeige"][-1]["text"]
    assert show.chat.verlauf == []                              # kein halbes Gespräch bleibt hängen


def test_falscher_schluessel(show, monkeypatch):
    anfrage = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fehler = anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(401, request=anfrage), body=None)
    mit_claude(show, monkeypatch, [fehler])
    assert "Schlüssel stimmt nicht" in show.chat.senden("Spots blau")["anzeige"][-1]["text"]


def test_schluessel_bleibt_geheim(show, tmp_path):
    with pytest.raises(ValueError, match="sk-ant-"):
        show.chat.schluessel.speichern("hallo")
    show.chat.schluessel.speichern(SCHLUESSEL)
    status = show.chat.status()
    assert status["ki"]["bereit"] and SCHLUESSEL not in str(status) and status["ki"]["maskiert"].startswith("sk-ant-")
    if sys.platform != "win32":
        assert os.stat(show.pfade.lokal).st_mode & 0o077 == 0     # nur der eigene Benutzer darf lesen
    show.chat.schluessel.loeschen()
    assert not show.chat.status()["ki"]["bereit"]


def test_chat_ueber_den_server(show):
    with TestClient(erstelle_app(show)) as client:
        assert client.get("/api/chat").json()["ki"]["bereit"] is False
        status = client.post("/api/chat", json={"text": "alles warmweiß 60 %"}).json()
        assert status["entwurf"]["name"] == "Warmweiss"
        assert client.post("/api/chat/vorschau", json={"cue": 0}).status_code == 200
        antwort_ = client.post("/api/chat/uebernehmen", json={"fader": 7}).json()
        assert antwort_["ergebnis"]["fader"] == 7 and antwort_["pult"]["executoren"][6]["sequenz"] == "Warmweiss"
        assert client.post("/api/chat/uebernehmen", json={}).status_code == 400
        assert client.post("/api/ki/schluessel", json={"schluessel": "falsch"}).status_code == 400
        assert client.post("/api/ki/schluessel", json={"schluessel": SCHLUESSEL}).json()["ki"]["bereit"]
        assert SCHLUESSEL not in client.get("/api/chat").text
        assert client.delete("/api/ki/schluessel").json()["ki"]["bereit"] is False


def test_einfach_versteht_tippfehler_stile_und_wirbel(show):
    # Der Satz, den der Nutzer wirklich geschrieben hat (mit Tippfehlern)
    vorschlag = einfach_verstehen(show, "baue eine rop position mit srobo und wo alle Lichter durcheinander wirbeln")
    assert vorschlag is not None and vorschlag["sequenz"]["name"].startswith("Wirbel")
    cue = vorschlag["sequenz"]["cues"][0]
    bewegung = [e for e in cue["effekte"] if e["art"] == "kreis"]
    assert bewegung and bewegung[0]["verteilung"] == 1.0                    # jeder Kopf anders
    assert any(e["art"] == "farbwechsel" for e in cue["effekte"])           # PARs bunt
    assert pruefen(show, vorschlag["sequenz"]) == []
    pop = einfach_verstehen(show, "Pop Look auf Fader 2")
    assert pop["sequenz"]["name"] == "Pop" and pop["fader"] == 2
    assert einfach_verstehen(show, "ruhige Ballade")["sequenz"]["cues"][0]["effekte"][0]["art"] == "dimmer_welle"
    assert einfach_verstehen(show, "Wie spät ist es?") is None
