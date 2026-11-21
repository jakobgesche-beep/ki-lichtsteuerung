"""Cameo PAR 56 CAN RGB 10 (Weihnachtszauber-Probe, 21.11.2026): Als einfacher RGB-PAR eingetragen blieb er dunkel,
weil Kanal 4 sein Master-Dimmer ist. Mit dem richtigen Gerätetyp bekommt der Dimmer die Helligkeit."""
from lichtsteuerung import daten
from lichtsteuerung.render import Eigenschaften
from lichtsteuerung.show import Show

TYP = "cameo/par-56-can-rgb-10"


def test_cameo_par_56_leuchtet_mit_dimmer_in_beiden_modi(tmp_path):
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    assert [m["name"] for m in show.katalog.typ(TYP).daten["modi"]] == ["4-Kanal (roter Punkt)", "6-Kanal (kein Punkt)"]
    vier = show.patch.hinzufuegen(TYP, "4-Kanal (roter Punkt)", 1, "Cameo 4", start=400, gruppen=["Farb-PARs"])[0]
    sechs = show.patch.hinzufuegen(TYP, "6-Kanal (kein Punkt)", 1, "Cameo 6", start=410, gruppen=["Farb-PARs"])[0]
    show.aufbauen()
    rot = Eigenschaften(helligkeit=1.0, farbe=(1.0, 0.0, 0.0))
    bild = show.renderer.bild({vier["id"]: rot, sechs["id"]: rot})
    assert list(bild[399:403]) == [255, 0, 0, 255]               # Rot, Grün, Blau, Dimmer
    assert list(bild[409:413]) == [255, 0, 0, 255]
    assert bild[413] <= 16 and bild[414] <= 31                    # Strobo aus, Modus "Farbe über DMX"
    halb = show.renderer.bild({vier["id"]: Eigenschaften(helligkeit=0.5, farbe=(0.0, 0.0, 1.0))})
    assert halb[401] == 255 and 120 <= halb[402] <= 135           # Blau voll, Dimmer halb
