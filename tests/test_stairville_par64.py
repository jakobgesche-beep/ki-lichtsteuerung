"""Stairville LED PAR 64 10 mm RGB (183 LEDs, Thomann): Kanal 7 ist der Master-Dimmer, Kanal 6 muss auf
„Farbe über DMX“ (0–31) bleiben, sonst läuft ein Programm. Werte laut Thomann-Anleitung, Kapitel 7.5."""
from lichtsteuerung import daten
from lichtsteuerung.katalog import pruefe_eintrag
from lichtsteuerung.render import Eigenschaften
from lichtsteuerung.show import Show

TYP = "stairville/led-par-64-10mm-rgb"


def test_stairville_par_64_leuchtet_mit_master_dimmer(tmp_path):
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    typ = show.katalog.typ(TYP)
    assert pruefe_eintrag(typ.daten) == [] and typ.daten["handbuch_geprueft"]
    par = show.patch.hinzufuegen(TYP, "7 Kanäle (DIP 10–12 aus)", 1, "PAR", start=28, gruppen=["Farb-PARs"])[0]
    show.aufbauen()
    rot = show.renderer.bild({par["id"]: Eigenschaften(helligkeit=1.0, farbe=(1.0, 0.0, 0.0))})
    assert list(rot[27:34]) == [255, 0, 0, 0, 0, 0, 255]       # R G B, Makro aus, kein Strobo, Modus DMX, Dimmer
    halb = show.renderer.bild({par["id"]: Eigenschaften(helligkeit=0.5, farbe=(0.0, 0.0, 1.0))})
    assert halb[29] == 255 and 120 <= halb[33] <= 135           # Blau voll, Dimmer halb
