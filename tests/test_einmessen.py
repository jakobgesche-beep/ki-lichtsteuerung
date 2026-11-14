"""Positionen einmessen (Pan-/Tilt-Versatz aus 2-3 angefahrenen Punkten) und Follow-Spot."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.einmessen import versatz_berechnen
from lichtsteuerung.pantilt import Montage, winkel_fuer_ziel
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show

ZIELE = [(0.0, 2.0, 2.4), (-2.5, 1.0, 2.4), (1.5, 3.0, 2.4)]


def gemessen(echt: Montage):
    """So stünde der Kopf, wenn jemand ihn genau auf die Ziele geschoben hat."""
    return [(ziel, *winkel_fuer_ziel(echt, ziel, 540, 270)) for ziel in ZIELE]


def test_versatz_und_umkehren_aus_drei_punkten():
    echt = Montage(x=-0.6, y=2.0, z=3.9, haengend=True, drehung_grad=180, pan_versatz_grad=7.0,
                   tilt_versatz_grad=-4.0, pan_umkehren=True)
    geschaetzt = Montage(x=-0.6, y=2.0, z=3.9, haengend=True, drehung_grad=180)
    ergebnis = versatz_berechnen(geschaetzt, gemessen(echt))
    assert ergebnis["pan_umkehren"] is True and ergebnis["tilt_umkehren"] is False
    assert ergebnis["pan_versatz_grad"] == pytest.approx(7.0, abs=0.1)
    assert ergebnis["tilt_versatz_grad"] == pytest.approx(-4.0, abs=0.1)
    assert ergebnis["abweichung_grad"] < 0.1
    # Mit dem Ergebnis trifft die Rechnung alle Punkte
    neu = Montage(x=-0.6, y=2.0, z=3.9, haengend=True, drehung_grad=180, **{k: v for k, v in ergebnis.items() if k != "abweichung_grad"})
    for ziel, pan, tilt in gemessen(echt):
        p, t = winkel_fuer_ziel(neu, ziel, 540, 270, (pan, tilt))
        assert abs(p - pan) < 0.2 and abs(t - tilt) < 0.2


def test_ein_punkt_reicht_fuer_den_versatz():
    echt = Montage(x=0.6, y=2.0, z=3.9, haengend=True, drehung_grad=180, pan_versatz_grad=-12.0, tilt_versatz_grad=3.0)
    ergebnis = versatz_berechnen(Montage(x=0.6, y=2.0, z=3.9, haengend=True, drehung_grad=180), gemessen(echt)[:1])
    assert ergebnis["pan_versatz_grad"] == pytest.approx(-12.0, abs=0.1) and ergebnis["tilt_versatz_grad"] == pytest.approx(3.0, abs=0.1)
    with pytest.raises(ValueError):
        versatz_berechnen(Montage(0, 0, 0), [])


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.automatik_an = False
    return s


def test_einmessen_in_der_show(show):
    kopf = show.follow_spot.moegliche()[0]
    e = show.einmessen
    with pytest.raises(ValueError):
        e.merken()
    e.starten(kopf["id"])
    e.hinfahren("Mitte")
    pan_gerechnet = e.pan
    e.schubsen(5, -2)
    assert e.pan == pytest.approx(pan_gerechnet + 5)
    e.merken()
    e.hinfahren("Rednerpult")
    e.schubsen(5, -2)
    e.merken()
    ergebnis = e.ausrechnen()
    assert ergebnis["abweichung_grad"] < 3.0
    e.uebernehmen()
    ort = daten.lese_json(show.pfade.stage)["geraete"][kopf["id"]]
    assert "pan_versatz_grad" in ort
    zustand = e.anwenden({})
    assert zustand[kopf["id"]].helligkeit == 1.0 and zustand[kopf["id"]].pan == e.pan
    e.beenden()
    assert e.anwenden({}) == {}


def test_follow_spot(show):
    fs = show.follow_spot
    fs.setzen(-1.0, 2.0)
    zustand = fs.anwenden({})
    koepfe = fs.geraete
    assert koepfe and all(zustand[k].helligkeit == 1.0 and zustand[k].pan is not None for k in koepfe)
    links = {k: (zustand[k].pan, zustand[k].tilt) for k in koepfe}
    fs.setzen(1.5, 2.0)
    rechts = {k: (fs.anwenden({})[k].pan, fs.anwenden({})[k].tilt) for k in koepfe}
    assert links != rechts                                        # die Köpfe folgen
    fs.setzen(0.0, -6.0)                                          # ins Publikum: bleibt an der Bühnenkante
    assert fs.punkt[1] == 0.0
    fs.aus()
    assert fs.anwenden({}) == {}


def test_ueber_den_server(show):
    with TestClient(erstelle_app(show)) as client:
        info = client.get("/api/positionen").json()
        assert "Mitte" in info["positionen"] and info["koepfe"]
        neu = dict(info["positionen"], **{"Schlagzeug": {"x": 0.5, "y": 4.0, "z": 2.4}})
        assert "Schlagzeug" in client.post("/api/positionen", json={"positionen": neu}).json()["positionen"]
        assert "Schlagzeug" in show.positionen and daten.lese_json(show.pfade.positions)["platzhalter"] is False
        assert client.post("/api/positionen", json={"positionen": {"Mond": {"x": 0, "y": 300, "z": 2}}}).status_code == 400
        kopf = info["koepfe"][0]["id"]
        assert client.post("/api/einmessen/start", json={"geraet": kopf}).json()["geraet"] == kopf
        assert client.post("/api/einmessen/hinfahren", json={"position": "Schlagzeug"}).json()["ziel"] == "Schlagzeug"
        client.post("/api/einmessen/schubsen", json={"pan": 2, "tilt": 0})
        assert len(client.post("/api/einmessen/merken").json()["punkte"]) == 1
        assert client.post("/api/einmessen/ausrechnen").json()["ergebnis"]["abweichung_grad"] == 0
        assert client.post("/api/einmessen/ende").json()["geraet"] is None
        assert client.post("/api/followspot", json={"x": 0, "y": 2}).json()["an"] is True
        assert client.post("/api/followspot/aus").json()["an"] is False
    # Auch vom Handy
    fern = show.fernbedienung
    fern.pin = "123456"
    handy = TestClient(fern.app)
    handy.headers["X-Fern"] = handy.post("/fern/anmelden", json={"pin": "123456"}).json()["token"]
    assert handy.post("/fern/followspot", json={"x": 1, "y": 1}).json()["an"] is True
    assert handy.post("/fern/followspot", json={"aus": True}).json()["an"] is False
