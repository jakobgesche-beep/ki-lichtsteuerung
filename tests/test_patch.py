"""Adressprüfung und Patch-Assistent."""
import pytest

from lichtsteuerung.buehne import Buehne
from lichtsteuerung.katalog import KatalogFehler, pruefe_eintrag
from lichtsteuerung.patch import Patch, PatchFehler, namen_erzeugen


@pytest.fixture
def patch(pfade, katalog):
    return Patch(pfade.fixtures, katalog)


def test_adressen_zaehlen_wie_in_der_beschreibung(patch):
    # 6 Geräte mit je 6 Kanälen: 1, 7, 13, ... (bei 8 Kanälen wären es 1, 9, 17, ...)
    neue = patch.hinzufuegen("test/par", "6", 6, "PAR 1-6")
    assert [g["adresse"] for g in neue] == [1, 7, 13, 19, 25, 31]
    assert [g["name"] for g in neue] == [f"PAR {i}" for i in range(1, 7)]
    assert patch.probleme() == []


def test_naechste_freie_findet_luecke(patch):
    patch.hinzufuegen("test/par", "6", 1, "A", start=1)
    patch.hinzufuegen("test/par", "6", 1, "B", start=11)
    assert patch.hinzufuegen("test/par", "4", 1, "C")[0]["adresse"] == 7
    # Sechs Kanäle passen nicht mehr in die Lücke zwischen C und B
    assert patch.hinzufuegen("test/par", "6", 1, "D")[0]["adresse"] == 17


def test_ueberschneidung_wird_gemeldet(patch):
    patch.hinzufuegen("test/par", "6", 1, "A", start=1)
    patch.hinzufuegen("test/par", "6", 1, "B", start=6)
    probleme = patch.probleme()
    assert len(probleme) == 1
    assert probleme[0]["art"] == "ueberschneidung"
    assert probleme[0]["geraete"] == ["a", "b"]


def test_genau_bis_512_ist_erlaubt(patch):
    assert patch.hinzufuegen("test/par", "6", 1, "A", start=507)[0]["adresse"] == 507
    assert patch.probleme() == []


@pytest.mark.parametrize("start", [508, 512, 513, 0, -1])
def test_ueber_512_ist_gesperrt(patch, start):
    with pytest.raises(PatchFehler):
        patch.hinzufuegen("test/par", "6", 1, "A", start=start)
    assert patch.geraete == []


def test_mehrere_geraete_scheitern_ganz_oder_gar_nicht(patch):
    with pytest.raises(PatchFehler):
        patch.hinzufuegen("test/par", "6", 3, "A", start=500)
    assert patch.geraete == []


def test_universum_voll(patch):
    patch.hinzufuegen("test/par", "6", 85, "A")   # 510 Kanäle
    with pytest.raises(PatchFehler):
        patch.hinzufuegen("test/par", "6", 1, "B")


def test_aendern_sperrt_ueber_512(patch):
    patch.hinzufuegen("test/par", "6", 1, "A")
    with pytest.raises(PatchFehler):
        patch.aendern("a", adresse=510)
    assert patch.geraet("a")["adresse"] == 1


def test_tausch_behaelt_id_gruppen_und_adresse(patch):
    patch.hinzufuegen("test/par", "6", 1, "A", gruppen=["Farb-PARs"])
    patch.tauschen("a", "test/kopf", "7")
    geraet = patch.geraet("a")
    assert (geraet["typ"], geraet["modus"]) == ("test/kopf", "7")
    assert geraet["gruppen"] == ["Farb-PARs"]


def test_tausch_mit_falschem_modus_aendert_nichts(patch):
    patch.hinzufuegen("test/par", "6", 1, "A")
    with pytest.raises(KatalogFehler):
        patch.tauschen("a", "test/kopf", "99")
    assert patch.geraet("a")["typ"] == "test/par"


def test_speichern_und_neu_laden(patch, pfade, katalog):
    patch.hinzufuegen("test/par", "6", 2, "A")
    patch.speichern()
    assert len(Patch(pfade.fixtures, katalog).geraete) == 2


def test_traverse_warnt_bei_mehr_als_8_geraeten(patch, pfade):
    buehne = Buehne(pfade.stage)
    for geraet in patch.hinzufuegen("test/par", "6", 9, "A"):
        buehne.setze_geraet(geraet["id"], {"ort": "traverse"})
    assert any("8 Geräte" in w for w in patch.traverse_warnungen(buehne))


def test_traverse_warnt_bei_mehr_als_60_kg(patch, pfade):
    buehne = Buehne(pfade.stage)
    buehne.daten["traverse"]["max_geraete"] = 99
    for geraet in patch.hinzufuegen("test/kopf", "7", 13, "A"):   # 13 * 5 kg
        buehne.setze_geraet(geraet["id"], {"ort": "traverse"})
    assert any("60 kg" in w for w in patch.traverse_warnungen(buehne))


def test_geraete_am_boden_zaehlen_nicht_zur_traverse(patch, pfade):
    buehne = Buehne(pfade.stage)
    for geraet in patch.hinzufuegen("test/par", "6", 9, "A"):
        buehne.setze_geraet(geraet["id"], {"ort": "boden"})
    assert patch.traverse_warnungen(buehne) == []


def test_namen():
    assert namen_erzeugen("PAR 1–3", 3) == ["PAR 1", "PAR 2", "PAR 3"]
    assert namen_erzeugen("Spot", 2) == ["Spot 1", "Spot 2"]
    assert namen_erzeugen("Hazer", 1) == ["Hazer"]


def test_editor_lehnt_kaputten_eintrag_ab(katalog):
    with pytest.raises(KatalogFehler):
        katalog.speichere_eigenen({"id": "a/b", "hersteller": "A", "name": "B", "kanaele": {},
                                   "modi": []})


def test_editor_speichert_kopie(katalog, pfade):
    kopie = dict(katalog.typ("test/par").daten, id="test/mein-par", name="Mein PAR")
    katalog.speichere_eigenen(kopie)
    assert (pfade.katalog / "eigene" / "test" / "mein-par.json").exists()
    assert katalog.suche("mein par")[0]["id"] == "test/mein-par"


def test_editor_kann_nicht_aus_dem_ordner_ausbrechen(katalog, pfade):
    kopie = dict(katalog.typ("test/par").daten, id="../..", name="X")
    with pytest.raises((KatalogFehler, ValueError)):
        katalog.speichere_eigenen(kopie)


def test_pruefe_eintrag_findet_unbekannten_kanal():
    fehler = pruefe_eintrag({"id": "a/b", "hersteller": "A", "name": "B",
                             "kanaele": {"X": {"typ": "dimmer"}},
                             "modi": [{"name": "1", "kanaele": ["Y"]}]})
    assert any("Y" in f for f in fehler)
