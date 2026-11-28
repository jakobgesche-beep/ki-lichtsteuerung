"""DIP-Schalter und Display: So stellt man die DMX-Adresse am Gerät ein (Binärcode, Schalter pro Gerätetyp)."""
from lichtsteuerung import adressierung, daten
from lichtsteuerung.patchplan import einstellen_html, eintraege
from lichtsteuerung.show import Show


def test_adresse_28_ist_schalter_3_4_5():
    info = adressierung.info_fuer(None)
    e = adressierung.einstellen(28, info)
    assert e["dip"]["an"] == [3, 4, 5] and e["dip"]["text"] == "Schalter 3 + 4 + 5 an"
    assert e["display"] == "A028" and e["warnung"] == ""
    assert [s["an"] for s in e["dip"]["schalter"]][:6] == [False, False, True, True, True, False]


def test_grenzen_1_255_256_511_512():
    info = adressierung.info_fuer(None)
    assert adressierung.einstellen(1, info)["dip"]["an"] == [1]
    assert adressierung.einstellen(255, info)["dip"]["an"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert adressierung.einstellen(256, info)["dip"]["an"] == [9]
    assert sum(2 ** (n - 1) for n in adressierung.einstellen(511, info)["dip"]["an"]) == 511
    assert "512" in adressierung.einstellen(512, info)["warnung"]           # passt nicht auf 9 Schalter
    zehn = adressierung.info_fuer({"adresse_einstellen": {"art": "dip", "dip": {"anzahl": 10, "adresse": 10}}})
    assert adressierung.einstellen(512, zehn)["dip"]["an"] == [10] and not adressierung.einstellen(512, zehn)["warnung"]


def test_stairville_par_64_modus_schalter_10_bis_12_aus(ordner):
    daten.einrichten(ordner / "d")
    show = Show(daten.Pfade(ordner / "d", daten.PROJEKT / "catalog"))
    for typ_id in ("stairville/led-par-64-10mm-rgb", "stairville/led-par-64"):
        info = adressierung.info_fuer(show.katalog.typ(typ_id).daten)
        e = adressierung.einstellen(28, info)
        assert len(e["dip"]["schalter"]) == 12 and e["display"] is None
        assert e["dip"]["text"] == "Schalter 3 + 4 + 5 an, 10, 11, 12 aus"
        assert [s["rolle"] for s in e["dip"]["schalter"]][9:] == ["modus"] * 3
        assert "10, 11 und 12" in e["hinweis"]
    mh = adressierung.einstellen(16, adressierung.info_fuer(show.katalog.typ("stairville/mh-x25").daten))
    assert mh["dip"] is None and mh["display"] == "A016"


def test_patch_und_katalog_schicken_die_einstell_art_mit(ordner):
    from fastapi.testclient import TestClient
    from lichtsteuerung.server import erstelle_app
    daten.einrichten(ordner / "d")
    show = Show(daten.Pfade(ordner / "d", daten.PROJEKT / "catalog"))
    with TestClient(erstelle_app(show)) as client:
        geraete = client.get("/api/patch").json()["geraete"]
        assert all("adresse_einstellen" in g for g in geraete)
        eintrag = client.get("/api/katalog/stairville/led-par-64-10mm-rgb").json()
        assert eintrag["adresse_einstellen"]["dip"]["anzahl"] == 12
        kurz = client.get("/api/katalog?suche=par 64 10 mm").json()["geraete"]
        assert any(k.get("adresse_einstellen", {}).get("art") == "dip" for k in kurz)
        plan = client.get("/patchplan").text
        assert "Am Gerät einstellen" in plan


def test_patchplan_zelle(ordner):
    daten.einrichten(ordner / "d")
    show = Show(daten.Pfade(ordner / "d", daten.PROJEKT / "catalog"))
    for e in eintraege(show):
        html = einstellen_html(e["einstellen"])
        assert html and ("dip" in html or "Display" in html)
