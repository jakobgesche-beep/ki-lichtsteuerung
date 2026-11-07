"""Selbst-Update und Trennung von App und Show-Daten."""
import hashlib
import json
import shutil
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lichtsteuerung import daten, update
from lichtsteuerung.dmx_ausgabe import DmxAusgabe
from lichtsteuerung.show import Show
from lichtsteuerung.update import Aktualisierer, ist_neuer, starte_skript


def test_versionen_vergleichen():
    assert ist_neuer("1.0.10", "1.0.9")
    assert not ist_neuer("1.0.0", "1.0.0")
    assert not ist_neuer("0.9.9", "1.0.0")
    with pytest.raises(ValueError):
        ist_neuer("1.0", "1.0.0")


def test_einrichten_kopiert_nur_was_fehlt(tmp_path):
    ziel = tmp_path / "daten"
    daten.einrichten(ziel)
    assert (ziel / "fixtures.json").exists() and (ziel / "profile" / "weihnachten.json").exists()
    (ziel / "stage.json").write_text('{"meins": true}')
    (ziel / "profile" / "weihnachten.json").write_text('{"meins": true}')
    daten.einrichten(ziel)         # zweiter Start und jedes Update
    assert "meins" in (ziel / "stage.json").read_text()
    assert "meins" in (ziel / "profile" / "weihnachten.json").read_text()


def test_app_daten_mit_eingebautem_katalog(tmp_path):
    ziel = tmp_path / "daten"
    daten.einrichten(ziel)
    show = Show(daten.Pfade(ziel, daten.PROJEKT / "catalog"))
    assert len(show.katalog.typen) > 600 and len(show.patch.geraete) == 10
    eintrag = dict(show.katalog.typ("stairville/mh-x25").daten, id="stairville/mein-kopf", name="Mein Kopf")
    show.katalog.speichere_eigenen(eintrag)
    assert (ziel / "catalog/eigene/stairville/mein-kopf.json").exists()
    assert not (daten.PROJEKT / "catalog/eigene/stairville").exists()


class Ausgabe(DmxAusgabe):
    an = False

    @property
    def eingeschaltet(self):
        return self.an


@pytest.fixture
def show(pfade):
    pfade.wurzel.mkdir(exist_ok=True)
    return Show(pfade, Ausgabe())


@pytest.fixture
def webserver(tmp_path):
    ordner = tmp_path / "web"
    ordner.mkdir()

    class Stumm(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Stumm, directory=str(ordner)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield ordner, f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


def veroeffentlichen(ordner, version, inhalt=b"neue app", summe=None):
    (ordner / "Lichtsteuerung-arm64.zip").write_bytes(inhalt)
    (ordner / "Lichtsteuerung-intel.zip").write_bytes(inhalt)
    eintrag = {"sha256": summe or hashlib.sha256(inhalt).hexdigest()}
    (ordner / "latest.json").write_text(json.dumps({"version": version, "dateien": {
        "arm64": {**eintrag, "name": "Lichtsteuerung-arm64.zip"},
        "intel": {**eintrag, "name": "Lichtsteuerung-intel.zip"}}}))


@pytest.fixture
def ohne_certifi(monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen",
                        partial(lambda f, u, timeout, context: f(u, timeout=timeout), update.urllib.request.urlopen))


def test_neue_version_wird_geladen(show, webserver, ohne_certifi):
    ordner, url = webserver
    veroeffentlichen(ordner, "99.0.0")
    a = Aktualisierer(show, url)
    a.pruefen()
    assert a.zustand == "bereit" and a.neu == "99.0.0" and a.zip.read_bytes() == b"neue app"


def test_gleiche_version_laedt_nichts(show, webserver, ohne_certifi):
    ordner, url = webserver
    veroeffentlichen(ordner, "0.0.1")
    a = Aktualisierer(show, url)
    a.pruefen()
    assert a.zustand == "ruht" and a.zip is None


def test_falsche_pruefsumme_wird_verworfen(show, webserver, ohne_certifi):
    ordner, url = webserver
    veroeffentlichen(ordner, "99.0.0", summe="0" * 64)
    a = Aktualisierer(show, url)
    a.pruefen()
    assert a.zustand == "ruht" and a.zip is None
    assert list((show.pfade.wurzel / "update").glob("*")) == []


def test_ohne_internet_passiert_nichts(show, ohne_certifi):
    a = Aktualisierer(show, "http://127.0.0.1:9/")
    a.pruefen()
    assert a.zustand == "ruht"
    assert show.baue_bild(0.0)


def test_kein_update_waehrend_die_dmx_ausgabe_laeuft(show):
    a = show.update
    a.zustand, a.zip = "bereit", show.pfade.wurzel / "x.zip"
    show.ausgabe.an = True
    with pytest.raises(ValueError, match="DMX"):
        a.installieren()


def test_ohne_download_kein_installieren(show):
    with pytest.raises(ValueError):
        show.update.installieren()


def test_kein_update_aus_dem_download_ordner(show, monkeypatch, tmp_path):
    monkeypatch.setattr(update, "app_pfad", lambda: daten.Path("/Volumes/Lichtsteuerung/Lichtsteuerung.app"))
    assert "Programme" in show.update.sperrgrund()


def baue_app(ordner, text):
    app = ordner / "Lichtsteuerung.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    programm = app / "Contents/MacOS/Lichtsteuerung"
    programm.write_text("#!/bin/sh\n")
    programm.chmod(0o755)
    (app / "Contents/inhalt.txt").write_text(text)
    subprocess.run(["codesign", "--force", "--deep", "-s", "-", str(app)], check=True, capture_output=True)
    return app


def warte_auf(prozess):
    prozess.wait(timeout=20)


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("ditto"), reason="nur auf dem Mac")
def test_skript_tauscht_die_app_und_daten_bleiben(tmp_path, monkeypatch):
    monkeypatch.setenv("LICHT_KEIN_NEUSTART", "1")
    alt = tmp_path / "alt mit leerzeichen"
    alt.mkdir()
    app = baue_app(alt, "alt")
    neu = tmp_path / "neu"
    neu.mkdir()
    baue_app(neu, "neu")
    zip_datei = tmp_path / "update.zip"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(neu / "Lichtsteuerung.app"), str(zip_datei)], check=True)
    warte_auf(starte_skript(999999, zip_datei, app))
    assert (app / "Contents/inhalt.txt").read_text() == "neu"
    assert sorted(p.name for p in alt.iterdir()) == ["Lichtsteuerung.app"]
    assert not zip_datei.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="nur auf dem Mac")
def test_kaputtes_update_laesst_die_alte_app_stehen(tmp_path, monkeypatch):
    monkeypatch.setenv("LICHT_KEIN_NEUSTART", "1")
    app = baue_app(tmp_path, "alt")
    zip_datei = tmp_path / "update.zip"
    zip_datei.write_bytes(b"kein zip")
    warte_auf(starte_skript(999999, zip_datei, app))
    assert (app / "Contents/inhalt.txt").read_text() == "alt"
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("Licht")) == ["Lichtsteuerung.app"]


def test_status_steht_in_den_live_daten(show):
    live = show.live_daten()
    assert live["version"] and live["update"]["zustand"] == "ruht"


def test_aus_dem_quellcode_gibt_es_keine_updates_aber_eine_antwort(show):
    show.update.jetzt_suchen()
    assert "fertigen App" in show.update.text


def test_aktuelle_version_wird_gemeldet(show, webserver, ohne_certifi):
    ordner, url = webserver
    veroeffentlichen(ordner, "0.0.1")
    a = Aktualisierer(show, url)
    a.pruefen()
    assert "aktuell" in a.text


def test_paket_und_datenordner_je_system(monkeypatch, tmp_path):
    monkeypatch.delenv("LICHT_DATEN", raising=False)
    monkeypatch.setattr(update.sys, "platform", "win32")
    assert update.paket() == "windows"
    monkeypatch.setattr(daten.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert daten.datenordner() == tmp_path / "Roaming" / "Lichtsteuerung"
    monkeypatch.setattr(daten.sys, "platform", "darwin")
    assert str(daten.datenordner()).endswith("Library/Application Support/Lichtsteuerung")


@pytest.mark.skipif(sys.platform != "win32", reason="nur unter Windows")
def test_windows_skript_wartet_bis_die_app_zu_ist_und_installiert(tmp_path, monkeypatch):
    import time
    monkeypatch.setenv("LICHT_KEIN_NEUSTART", "1")
    marke = tmp_path / "installiert.txt"
    installer = tmp_path / "setup.bat"
    installer.write_text(f'@echo %* > "{marke}"\r\n', encoding="ascii")
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
    skript = update.starte_windows_skript(app.pid, installer, tmp_path / "Lichtsteuerung.exe")
    time.sleep(1.5)
    assert not marke.exists()                     # die App läuft noch: warten
    app.wait()
    skript.wait(timeout=60)
    assert "/VERYSILENT" in marke.read_text()
