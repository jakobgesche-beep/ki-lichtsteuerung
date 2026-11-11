"""Show sichern und laden (MacBook <-> Windows-Laptop): was drin ist, was nie drin ist, Laden beim Start."""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten, sicherung
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


@pytest.fixture
def wurzel(tmp_path):
    ordner = tmp_path / "show"
    daten.einrichten(ordner)
    (ordner / "cues" / "sequenzen").mkdir(parents=True, exist_ok=True)
    (ordner / "cues" / "sequenzen" / "Intro.json").write_text(json.dumps({"name": "Intro", "cues": []}), encoding="utf-8")
    (ordner / "daten" / "proben").mkdir(parents=True)
    (ordner / "daten" / "proben" / "song.wav").write_bytes(b"RIFF....")
    (ordner / "daten" / "proben" / "song.json").write_text("{}", encoding="utf-8")
    (ordner / "lokal.json").write_text('{"anthropic_api_key": "sk-ant-geheim"}', encoding="utf-8")
    (ordner / "daten" / "sitzung.json").write_text('{"audio": {"name": "Mikro"}}', encoding="utf-8")
    (ordner / "catalog" / "eigene" / "technik-ag").mkdir(parents=True)
    (ordner / "catalog" / "eigene" / "technik-ag" / "strobo-eingemessen.json").write_text("{}", encoding="utf-8")
    return ordner


def namen(datei):
    with zipfile.ZipFile(datei) as archiv:
        return set(archiv.namelist())


def test_export_hat_die_show_aber_nie_den_schluessel(wurzel, tmp_path):
    mit = namen(sicherung.exportieren(wurzel, tmp_path / "a.zip", mit_proben=True))
    assert {"fixtures.json", "stage.json", "cues/sequenzen/Intro.json", "daten/proben/song.wav",
            "catalog/eigene/technik-ag/strobo-eingemessen.json"} <= mit
    assert "lokal.json" not in mit and "daten/sitzung.json" not in mit
    ohne = namen(sicherung.exportieren(wurzel, tmp_path / "b.zip", mit_proben=False))
    assert "daten/proben/song.wav" not in ohne and "cues/sequenzen/Intro.json" in ohne


def test_kaputte_oder_boese_dateien_werden_abgelehnt(tmp_path):
    (tmp_path / "kein.zip").write_bytes(b"hallo")
    with pytest.raises(ValueError, match="keine gültige"):
        sicherung.pruefen(tmp_path / "kein.zip")
    for inhalt in ({"stage.json": "{}"}, {"fixtures.json": "{}", "../../boese.txt": "x"},
                   {"fixtures.json": "{}", "lokal.json": "{}"}):
        puffer = io.BytesIO()
        with zipfile.ZipFile(puffer, "w") as archiv:
            for name, text in inhalt.items():
                archiv.writestr(name, text)
        (tmp_path / "x.zip").write_bytes(puffer.getvalue())
        with pytest.raises(ValueError):
            sicherung.pruefen(tmp_path / "x.zip")


def test_laden_beim_start_ersetzt_die_show_und_sichert_vorher(wurzel, tmp_path):
    andere = tmp_path / "andere"
    daten.einrichten(andere)
    (andere / "cues" / "sequenzen").mkdir(parents=True, exist_ok=True)
    (andere / "cues" / "sequenzen" / "Finale.json").write_text(json.dumps({"name": "Finale", "cues": []}), encoding="utf-8")
    datei = sicherung.exportieren(andere, tmp_path / "andere.zip")
    uebersicht = sicherung.vormerken(wurzel, datei)
    assert uebersicht["sequenzen"] == 1 and sicherung.vorgemerkt(wurzel)
    meldung = sicherung.beim_start_laden(wurzel)
    assert "Show geladen" in meldung and not sicherung.vorgemerkt(wurzel)
    assert (wurzel / "cues" / "sequenzen" / "Finale.json").exists()
    assert not (wurzel / "cues" / "sequenzen" / "Intro.json").exists()      # alte Sequenzen sind weg ...
    sicherungen = list((wurzel / "sicherungen").glob("vor-dem-laden-*.zip"))
    assert sicherungen and "cues/sequenzen/Intro.json" in namen(sicherungen[0])   # ... aber gesichert
    assert json.loads((wurzel / "lokal.json").read_text(encoding="utf-8"))["anthropic_api_key"] == "sk-ant-geheim"
    assert sicherung.beim_start_laden(wurzel) is None


def test_automatische_sicherung_behaelt_zehn(wurzel, monkeypatch):
    import datetime as dt
    for nummer in range(13):
        zeit = dt.datetime(2026, 11, 1, 10, 0, nummer)
        monkeypatch.setattr(sicherung, "_jetzt", lambda z=zeit: z)
        sicherung.automatisch_sichern(wurzel)
    assert len(list((wurzel / "sicherungen").glob("automatisch-*.zip"))) == 10


def test_ueber_den_server(wurzel, tmp_path, monkeypatch):
    monkeypatch.setattr(sicherung, "downloads_ordner", lambda: tmp_path)
    show = Show(daten.Pfade(wurzel, daten.PROJEKT / "catalog"))
    with TestClient(erstelle_app(show)) as client:
        ergebnis = client.post("/api/sicherung/export", json={"mit_proben": False}).json()
        assert ergebnis["pfad"].startswith(str(tmp_path)) and "Lichtsteuerung-Show-" in ergebnis["pfad"]
        with open(ergebnis["pfad"], "rb") as datei:
            antwort = client.post("/api/sicherung/import", content=datei.read()).json()
        assert antwort["sequenzen"] >= 1 and client.get("/api/sicherung").json()["vorgemerkt"]
        assert client.post("/api/sicherung/import", content=b"kein zip").status_code == 400
        assert client.post("/api/sicherung/zeigen", json={"pfad": "/etc/passwd"}).status_code == 400
        assert client.post("/api/beenden").status_code == 400       # im Test gibt es kein Programm zum Beenden


def test_kaputte_dateien_halten_den_start_nicht_auf(wurzel):
    (wurzel / "cues" / "sequenzen" / "Kaputt.json").write_text("{nicht fertig", encoding="utf-8")
    (wurzel / "catalog" / "eigene" / "technik-ag" / "kaputt.json").write_text("[]", encoding="utf-8")
    show = Show(daten.Pfade(wurzel, daten.PROJEKT / "catalog"))
    assert "Intro" in show.pult.sequenzen.namen() and show.pult.sequenzen.lesen("Kaputt") is None
    assert show.katalog.kaputt


def test_konzert_check_sagt_was_fehlt(wurzel):
    from lichtsteuerung import konzertcheck
    show = Show(daten.Pfade(wurzel, daten.PROJEKT / "catalog"))
    punkte = konzertcheck.pruefen(show)
    themen = {p["thema"]: p["stufe"] for p in punkte if p["stufe"] != "ok"}
    assert themen["Ton"] == "problem"                     # kein Eingang gewählt
    assert "DMX" in themen
    show.overrides.blackout = True
    show.pult.grand = 0.5
    texte = " ".join(p["text"] for p in konzertcheck.pruefen(show))
    assert "Blackout ist an" in texte and "Grand Master steht auf 50 %" in texte
    with TestClient(erstelle_app(show)) as client:
        assert client.get("/api/check").json()["punkte"]
