"""Import von QLC+- und GDTF-Dateien.

Die .qxf ist die echte Datei des Hero Spot 60 aus QLC+. Eine echte GDTF-Datei
lag nicht vor, deshalb bauen wir hier eine kleine nach dem GDTF-Aufbau nach.
"""
import io
import zipfile
from pathlib import Path

import pytest

from lichtsteuerung.importe import gdtf, qxf
from lichtsteuerung.katalog import Katalog, pruefe_eintrag
from lichtsteuerung.importe.gemeinsam import speichere_import
from lichtsteuerung.buehne import Buehne
from lichtsteuerung.patch import Patch
from lichtsteuerung.pruefung import Pruefer, Vorgaben
from lichtsteuerung.render import Eigenschaften, Renderer
from lichtsteuerung.sicherheit import Grenzen

QXF = (Path(__file__).parent / "beispiele" / "Varytec-Hero-Spot-60.qxf").read_bytes()

GDTF_XML = b"""<?xml version="1.0"?>
<GDTF DataVersion="1.1"><FixtureType Name="Testkopf" Manufacturer="Muster">
 <Wheels>
  <Wheel Name="Farben"><Slot Name="Open" Color="0.3127,0.3290,100"/><Slot Name="Red" Color="0.64,0.33,21"/></Wheel>
 </Wheels>
 <DMXModes><DMXMode Name="Standard" Geometry="Kopf"><DMXChannels>
  <DMXChannel Geometry="Kopf" Offset="1,2" Default="32768/2">
   <LogicalChannel Attribute="Pan">
    <ChannelFunction Attribute="Pan" DMXFrom="0/2" PhysicalFrom="-270" PhysicalTo="270"/>
   </LogicalChannel>
  </DMXChannel>
  <DMXChannel Geometry="Kopf" Offset="3" Default="0/1">
   <LogicalChannel Attribute="Dimmer"><ChannelFunction Attribute="Dimmer" DMXFrom="0/1"/></LogicalChannel>
  </DMXChannel>
  <DMXChannel Geometry="Kopf" Offset="4" Default="10/1">
   <LogicalChannel Attribute="Shutter1">
    <ChannelFunction Attribute="Shutter1" DMXFrom="0/1">
     <ChannelSet Name="Closed" DMXFrom="0/1"/><ChannelSet Name="Open" DMXFrom="10/1"/>
    </ChannelFunction>
    <ChannelFunction Attribute="Shutter1Strobe" DMXFrom="20/1" PhysicalFrom="1" PhysicalTo="25"/>
   </LogicalChannel>
  </DMXChannel>
  <DMXChannel Geometry="Kopf" Offset="5" Default="0/1">
   <LogicalChannel Attribute="Color1">
    <ChannelFunction Attribute="Color1" DMXFrom="0/1" Wheel="Farben">
     <ChannelSet Name="Offen" DMXFrom="0/1" WheelSlotIndex="1"/><ChannelSet Name="Rot" DMXFrom="100/1" WheelSlotIndex="2"/>
    </ChannelFunction>
   </LogicalChannel>
  </DMXChannel>
  <DMXChannel Geometry="Kopf" Offset="" Default="0/1">
   <LogicalChannel Attribute="Virtual"><ChannelFunction Attribute="Virtual" DMXFrom="0/1"/></LogicalChannel>
  </DMXChannel>
 </DMXChannels></DMXMode></DMXModes>
</FixtureType></GDTF>"""


def gdtf_datei() -> bytes:
    speicher = io.BytesIO()
    with zipfile.ZipFile(speicher, "w") as archiv:
        archiv.writestr("description.xml", GDTF_XML)
    return speicher.getvalue()


def test_qxf_hero_spot_stimmt_mit_der_hardware_tabelle_ueberein():
    eintrag = qxf.wandle(QXF)
    assert pruefe_eintrag(eintrag) == []
    assert eintrag["physik"] == {"gewicht_kg": 4.6, "abstrahlwinkel_grad": 15}
    assert eintrag["kanaele"]["Pan"]["grad"] == 540 and eintrag["kanaele"]["Tilt"]["grad"] == 190
    assert [(m["name"], len(m["kanaele"])) for m in eintrag["modi"]] == [("8 Channel", 8), ("14 Channel", 14)]
    assert eintrag["kanaele"]["Pan Fine"]["grob"] == "Pan"


def test_qxf_programmkanaele_sind_gesperrt_und_strobo_erkannt():
    kanaele = qxf.wandle(QXF)["kanaele"]
    assert kanaele["Automatic Shows"]["typ"] == "makro"
    assert kanaele["Moving Programs (Open Shutter)"]["typ"] == "makro"
    strobo = next(b for b in kanaele["Shutter"]["bereiche"] if b["typ"] == "strobo")
    assert strobo["hz_bis"] is None      # "slow to fast": Hertz unbekannt, also gesperrt


def test_qxf_farbrad_und_gobos():
    kanaele = qxf.wandle(QXF)["kanaele"]
    assert kanaele["Color"]["bereiche"][1]["farbe"] == "#ff0000"
    assert kanaele["Gobo"]["bereiche"][0]["name"] == "Offen"
    assert kanaele["Moving Speed"]["schnell_bei"] == 255
    assert kanaele["Gobo Rotation"]["typ"] == "gobo_rotation"


def test_qxf_gerät_laeuft_durch_die_ganze_kette(pfade, katalog):
    speichere_import(qxf.wandle(QXF), pfade.katalog)
    katalog.neu_laden()
    patch = Patch(pfade.fixtures, katalog)
    patch.hinzufuegen("varytec/hero-spot-60", "14 Channel", 1, "Spot")
    buehne = Buehne(pfade.stage)
    buehne.setze_geraet("spot", {"ort": "traverse", "x": 0, "y": 2, "z": 3.9, "montage": "haengend"})
    bild = Renderer(patch).bild({"spot": Eigenschaften(helligkeit=1, farbe=(1, 0, 0), gobo="Gobo 2")})
    bild[12] = 77     # Programm-Kanal absichtlich gesetzt
    bild, meldungen, _ = Pruefer(patch, buehne, Grenzen(3, 5, 30)).pruefe(bild, Vorgaben(), 0.0)
    assert bild[5] == 255          # Dimmer
    assert 25 <= bild[7] <= 50     # Farbrad auf Rot
    assert 27 <= bild[8] <= 43     # Gobo 2
    assert bild[12] == 0           # Programm bleibt aus
    assert meldungen == []


def test_kaputte_qxf():
    with pytest.raises(ValueError):
        qxf.wandle(b"<irgendwas/>")


def test_gdtf_kanaele_und_16_bit():
    eintrag = gdtf.wandle(gdtf_datei())
    assert pruefe_eintrag(eintrag) == []
    assert eintrag["id"] == "muster/testkopf"
    modus = eintrag["modi"][0]
    assert len(modus["kanaele"]) == 5              # virtueller Kanal fehlt
    pan = eintrag["kanaele"][modus["kanaele"][0]]
    assert pan["typ"] == "pan" and pan["grad"] == 540 and pan["standard"] == 128
    assert eintrag["kanaele"][modus["kanaele"][1]]["typ"] == "pan_fein"


def test_gdtf_strobo_in_hertz_und_farben():
    eintrag = gdtf.wandle(gdtf_datei())
    namen = eintrag["modi"][0]["kanaele"]
    shutter = eintrag["kanaele"][namen[3]]
    assert shutter["typ"] == "strobo"
    typen = {b["typ"] for b in shutter["bereiche"]}
    assert {"zu", "offen", "strobo"} <= typen
    strobo = next(b for b in shutter["bereiche"] if b["typ"] == "strobo")
    assert (strobo["von"], strobo["bis"], strobo["hz_von"], strobo["hz_bis"]) == (20, 255, 1, 25)
    rad = eintrag["kanaele"][namen[4]]["bereiche"]
    assert rad[1]["farbe"].startswith("#ff") and rad[0]["name"] == "Offen"


def test_kaputte_gdtf():
    with pytest.raises(ValueError):
        gdtf.wandle(b"kein zip")


def test_import_ueber_den_server(pfade):
    from fastapi.testclient import TestClient

    from lichtsteuerung.server import erstelle_app
    from lichtsteuerung.show import Show
    with TestClient(erstelle_app(Show(pfade))) as client:
        antwort = client.post("/api/katalog/importieren?name=spot.qxf", content=QXF)
        assert antwort.json() == {"id": "varytec/hero-spot-60"}
        assert client.get("/api/katalog/varytec/hero-spot-60").status_code == 200
        assert client.post("/api/katalog/importieren?name=x.gdtf", content=gdtf_datei()).status_code == 200
        assert client.post("/api/katalog/importieren?name=x.qxf", content=b"<<<").status_code == 400
        assert client.post("/api/katalog/importieren?name=x.txt", content=b"x").status_code == 400
