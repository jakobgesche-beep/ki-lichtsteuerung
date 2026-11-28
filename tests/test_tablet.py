"""iPad-Pult übers WLAN: Koppeln (bleibt nach Neustart), Live-Verbindung, erlaubte Befehle, Sicherheit."""
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lichtsteuerung import daten
from lichtsteuerung.kopplung import Kopplung, fingerabdruck
from lichtsteuerung.show import Show

WILD = {"name": "Wild", "cues": [{"name": "Wild", "zeit_s": 0, "werte": [{"gruppe": "Spots", "helligkeit": 1}]}]}


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.pult.sequenz_speichern(WILD)
    return s


# --- Kopplung ---------------------------------------------------------------------------------------

def test_koppeln_nur_mit_offenem_fenster_und_richtiger_pin(tmp_path):
    k = Kopplung(tmp_path / "netz_geraete.json")
    with pytest.raises(PermissionError, match="Kopplungsfenster"):
        k.koppeln("123456", "iPad", "1.2.3.4")
    pin = k.fenster_oeffnen()["pin"]
    with pytest.raises(PermissionError, match="Falsche PIN"):
        k.koppeln("000000" if pin != "000000" else "111111", "iPad", "1.2.3.4")
    token = k.koppeln(pin, "iPad Technik", "1.2.3.4")
    assert k.pruefen(token)["name"] == "iPad Technik" and k.pruefen("geraten") is None
    datei = (tmp_path / "netz_geraete.json").read_text()
    assert token not in datei and fingerabdruck(token) in datei          # nur der Fingerabdruck liegt auf der Platte
    assert not k.fenster()["offen"]                                      # ein Fenster koppelt genau ein Gerät
    neu = Kopplung(tmp_path / "netz_geraete.json")                       # nach einem Neustart
    assert neu.pruefen(token) is not None and neu.hat_ipad()
    neu.entfernen(0)
    assert neu.pruefen(token) is None


def test_zu_viele_falsche_pins_sperren(tmp_path):
    k = Kopplung(tmp_path / "netz_geraete.json")
    pin = k.fenster_oeffnen()["pin"]
    falsch = "999999" if pin != "999999" else "888888"
    for _ in range(5):
        with pytest.raises(PermissionError):
            k.koppeln(falsch, "x", "5.5.5.5")
    with pytest.raises(PermissionError, match="warten"):
        k.koppeln(pin, "x", "5.5.5.5")                                   # auch die richtige PIN muss warten
    assert k.koppeln(pin, "anderes iPad", "6.6.6.6")                       # andere Geräte nicht


# --- Seite und Dateien -------------------------------------------------------------------------------

def test_seite_dateien_und_kein_ausbruch(show):
    client = TestClient(show.fernbedienung.app)
    seite = client.get("/pult/")
    assert seite.status_code == 200 and "{{VERSION}}" not in seite.text
    assert client.get("/pult/static/app.js").status_code == 200
    assert client.get("/gemeinsam/dip.js").status_code == 200
    assert client.get("/pult/static/../../lichtsteuerung/ki.py").status_code == 404
    assert client.get("/pult/static/%2e%2e/%2e%2e/lokal.json").status_code == 404
    assert client.get("/pult/manifest.webmanifest").json()["display"] == "standalone"


# --- Live-Verbindung ---------------------------------------------------------------------------------

def _koppeln(show):
    pin = show.fernbedienung.kopplung.fenster_oeffnen()["pin"]
    return TestClient(show.fernbedienung.app).post("/pult/koppeln", json={"pin": pin, "name": "Test-iPad"}).json()["token"]


def _bis(ws, bedingung, hoechstens=300):
    for _ in range(hoechstens):
        nachricht = ws.receive_json()
        if bedingung(nachricht):
            return nachricht
    raise AssertionError("Nachricht kam nicht")


def _befehl(ws, seq, was, **felder):
    ws.send_json({"typ": "befehl", "seq": seq, "was": was, **felder})
    return _bis(ws, lambda n: n.get("typ") == "antwort" and n.get("seq") == seq)


def test_falscher_schluessel_und_fremde_seite_kommen_nicht_rein(show):
    _koppeln(show)
    client = TestClient(show.fernbedienung.app)
    with client.websocket_connect("/pult/ws") as ws:
        ws.send_json({"typ": "hallo", "token": "geraten"})
        with pytest.raises(WebSocketDisconnect) as fehler:
            ws.receive_json()
        assert fehler.value.code == 4401
    with client.websocket_connect("/pult/ws", headers={"origin": "http://boese.example"}) as ws:
        with pytest.raises(WebSocketDisconnect) as fehler:
            ws.receive_json()
        assert fehler.value.code == 4403


def test_stand_fader_tasten_und_verbotenes(show):
    token = _koppeln(show)
    client = TestClient(show.fernbedienung.app)
    with client.websocket_connect("/pult/ws") as ws:
        ws.send_json({"typ": "hallo", "token": token, "protokoll": 1})
        fest = _bis(ws, lambda n: n.get("typ") == "fest")
        assert fest["geraete"] and "einstellen" in fest["geraete"][0] and fest["pro_seite"] == 10
        voll = _bis(ws, lambda n: n.get("typ") == "zustand" and n.get("voll"))
        assert {"exec", "master", "ov", "prog", "musik", "show", "chat", "dmx"} <= set(voll)
        assert len(voll["exec"]) == 40
        assert _befehl(ws, 1, "zuweisen", nr=2, sequenz="Wild")["ok"]
        assert _befehl(ws, 2, "fader", nr=2, wert=0.5)["ok"]
        assert show.pult.executor(2).fader == 0.5
        assert _befehl(ws, 3, "taste", nr=2, taste="toggle")["ok"]
        assert show.pult.executor(2).index == 0
        neu = _bis(ws, lambda n: n.get("typ") == "zustand" and "2" in n.get("exec", {}))
        assert neu["exec"]["2"]["laeuft"] is True
        verboten = _befehl(ws, 4, "beenden")
        assert verboten["ok"] is False and "darf das iPad nicht" in verboten["fehler"]
        assert _befehl(ws, 5, "override", taste="blackout", an=True)["ok"]
        assert _befehl(ws, 6, "override", taste="blackout", an=True)["ok"]        # doppelt: bleibt an
        assert show.overrides.blackout is True
        falsch = _befehl(ws, 7, "fader", nr=2, wert="viel")
        assert falsch["ok"] is False
        ws.send_json({"typ": "ping", "t": 123})
        assert _bis(ws, lambda n: n.get("typ") == "pong")["t"] == 123


def test_flash_wird_beim_abbruch_losgelassen(show):
    token = _koppeln(show)
    show.pult.zuweisen(5, "sequenz", "Wild")
    client = TestClient(show.fernbedienung.app)
    with client.websocket_connect("/pult/ws") as ws:
        ws.send_json({"typ": "hallo", "token": token})
        _bis(ws, lambda n: n.get("typ") == "fest")
        assert _befehl(ws, 1, "taste", nr=5, taste="flash", an=True)["ok"]
        assert show.pult.executor(5).flash_seit is not None
        assert _befehl(ws, 2, "halten", art=next(iter(show.pult.halten)), an=True)["ok"]
    ende = time.monotonic() + 3
    while time.monotonic() < ende and show.pult.executor(5).flash_seit is not None:
        time.sleep(0.05)
    assert show.pult.executor(5).flash_seit is None                         # iPad weg: Flash los
    assert not any(seit is not None for seit in show.pult.halten.values())   # Halten auch


def test_chat_vorschlag_auf_fader_und_sofort_drueckbar(show):
    """Ohne Claude-Schlüssel antwortet der einfache Satz-Leser: Szene bauen, auf Fader legen, drücken."""
    token = _koppeln(show)
    client = TestClient(show.fernbedienung.app)
    with client.websocket_connect("/pult/ws") as ws:
        ws.send_json({"typ": "hallo", "token": token})
        _bis(ws, lambda n: n.get("typ") == "fest")
        assert _befehl(ws, 1, "chat", text="Moving Heads drehen sich wild und wechseln die ganze Zeit die Farbe")["ok"]
        zustand = _bis(ws, lambda n: n.get("typ") == "zustand" and (n.get("chat") or {}).get("entwurf"))
        assert zustand["chat"]["entwurf"]["cues"]
        antwort = _befehl(ws, 2, "chat_uebernehmen", fader=7)
        assert antwort["ok"], antwort
        executor = show.pult.executor(7)
        assert executor.sequenz is not None and executor.fader == 1.0
        assert _befehl(ws, 3, "taste", nr=7, taste="toggle")["ok"]
        assert show.pult.executor(7).index == 0


def test_desktop_routen_fuer_koppeln(show):
    from lichtsteuerung.server import erstelle_app
    show.fernbedienung.host = "127.0.0.1"                     # Tests: nie fürs ganze WLAN öffnen
    with TestClient(erstelle_app(show)) as client:
        zustand = client.post("/api/netz/koppeln").json()
        try:
            assert zustand["an"] and zustand["fenster"]["offen"] and len(zustand["fenster"]["pin"]) == 6
            assert zustand["links"] and "/pult/?pin=" in zustand["links"][0]["link"] and zustand["qr"].startswith("<")
            assert client.post("/api/netz/beim_start", json={"an": False}).json()["beim_start"] is False
        finally:
            client.post("/api/netz/aus")


def test_port_bleibt_nach_schnellem_neustart_gleich(show):
    """Das iPad-Symbol merkt sich den Port. Nach einem Neustart (alte Verbindungen noch in TIME_WAIT) muss
    derselbe Port wieder gehen, sonst zeigt das Symbol ins Leere."""
    import json
    import socket
    from websockets.sync.client import connect
    from lichtsteuerung import fernbedienung
    fern = show.fernbedienung
    port = fernbedienung._freier_port("127.0.0.1", 8799)
    fern.einschalten(host="127.0.0.1", port=port)
    try:
        for _ in range(3):                         # ein paar Verbindungen, die beim Ausschalten offen sind
            with connect(f"ws://127.0.0.1:{port}/pult/ws") as ws:
                ws.send(json.dumps({"typ": "hallo", "token": "x"}))
                try:
                    ws.recv(timeout=2)
                except Exception:
                    pass
    finally:
        fern.ausschalten()
    assert fernbedienung._freier_port("127.0.0.1", port) == port
