"""Importiert Gerätedateien von QLC+ (.qxf) in unser Katalog-Format.

Aufruf:   python -m lichtsteuerung.importe.qxf datei.qxf
Oder in der Oberfläche unter Katalog.
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from .. import daten
from .gemeinsam import speichere_import

NS = "{http://www.qlcplus.org/FixtureDefinition}"
QUELLE = {"art": "qlc+", "name": "QLC+ Gerätebibliothek", "lizenz": "Apache-2.0",
          "url": "https://github.com/mcallegari/qlcplus"}

KANAL_VORLAGEN = {
    "IntensityDimmer": "dimmer", "IntensityMasterDimmer": "dimmer",
    "IntensityRed": "rot", "IntensityGreen": "gruen", "IntensityBlue": "blau",
    "IntensityWhite": "weiss", "IntensityAmber": "amber", "IntensityUV": "uv",
    "IntensityCyan": "cyan", "IntensityMagenta": "magenta", "IntensityYellow": "gelb",
    "IntensityLime": "limette", "IntensityIndigo": "indigo",
    "IntensityWarmWhite": "warmweiss", "IntensityColdWhite": "kaltweiss",
    "PositionPan": "pan", "PositionTilt": "tilt",
    "PositionPanFine": "pan_fein", "PositionTiltFine": "tilt_fein",
    "BeamFocusNearFar": "fokus", "BeamFocusFarNear": "fokus",
    "BeamZoomSmallBig": "zoom", "BeamZoomBigSmall": "zoom",
    "SpeedPanTiltSlowFast": "tempo", "SpeedPanTiltFastSlow": "tempo",
}
GRUPPEN = {"Pan": "pan", "Tilt": "tilt", "Colour": "farbrad", "Gobo": "gobo", "Shutter": "strobo",
           "Speed": "tempo", "Prism": "prisma", "Beam": "fokus", "Effect": "makro",
           "Maintenance": "makro", "Nothing": "sonstiges"}
FARBEN = {"Red": "rot", "Green": "gruen", "Blue": "blau", "White": "weiss", "Amber": "amber",
          "UV": "uv", "Cyan": "cyan", "Magenta": "magenta", "Yellow": "gelb", "Lime": "limette",
          "Indigo": "indigo"}


def bereich_aus(faehigkeit, typ: str) -> dict:
    vorlage = faehigkeit.get("Preset", "")
    text = (faehigkeit.text or "").strip()
    bereich = {"von": int(faehigkeit.get("Min")), "bis": int(faehigkeit.get("Max")), "typ": "sonstiges"}
    if text:
        bereich["name"] = text
    if vorlage == "ShutterOpen":
        bereich["typ"] = "offen"
    elif vorlage == "ShutterClose":
        bereich["typ"] = "zu"
    elif vorlage.startswith("Strobe") or (typ == "strobo" and "strobe" in text.lower()):
        hz_von = hz_bis = None
        if vorlage == "StrobeFreqRange":
            hz_von, hz_bis = float(faehigkeit.get("Res1")), float(faehigkeit.get("Res2"))
        elif vorlage == "StrobeFrequency":
            hz_von = hz_bis = float(faehigkeit.get("Res1"))
        bereich.update(typ="strobo", hz_von=hz_von, hz_bis=hz_bis)
    elif vorlage == "ColorMacro":
        bereich.update(typ="platz", farbe=faehigkeit.get("Res1"))
    elif vorlage == "GoboMacro":
        bereich.update(typ="platz", name="Offen" if text.lower() == "open" else text)
    elif "strobe" in text.lower():
        # Auch in Effekt-Kanälen versteckt sich Strobo. Für die Sicherheit zählt es.
        bereich.update(typ="strobo", hz_von=None, hz_bis=None)
    return bereich


def wandle_kanal(knoten) -> dict:
    vorlage = knoten.get("Preset")
    if vorlage:
        return wandle_vorlage(vorlage, knoten.get("Name"))
    gruppe = knoten.find(NS + "Group")
    name = gruppe.text if gruppe is not None else "Nothing"
    farbe = knoten.find(NS + "Colour")
    if name == "Intensity":
        typ = FARBEN.get(farbe.text if farbe is not None else "", "dimmer")
    else:
        typ = GRUPPEN.get(name, "sonstiges")
    if typ == "gobo" and "rot" in knoten.get("Name", "").lower():
        typ = "gobo_rotation"
    kanal = {"typ": typ, "standard": int(knoten.get("Default", 0))}
    if gruppe is not None and gruppe.get("Byte") == "1" and typ in ("pan", "tilt"):
        kanal["typ"] = f"{typ}_fein"
    bereiche = [bereich_aus(f, typ) for f in knoten.findall(NS + "Capability")]
    if bereiche:
        kanal["bereiche"] = bereiche
    if typ == "strobo":
        offene = [b for b in bereiche if b["typ"] == "offen"]
        if offene:
            kanal["standard"] = offene[0]["von"]
    return kanal


def wandle_vorlage(vorlage: str, name: str) -> dict:
    if vorlage in ("ShutterStrobeSlowFast", "ShutterStrobeFastSlow"):
        # Bedeutet: Wert 0 ist ruhig, darüber Strobo mit unbekanntem Tempo.
        return {"typ": "strobo", "standard": 0, "bereiche": [
            {"von": 0, "bis": 0, "typ": "offen"},
            {"von": 1, "bis": 255, "typ": "strobo", "hz_von": None, "hz_bis": None}]}
    typ = KANAL_VORLAGEN.get(vorlage, "sonstiges")
    kanal = {"typ": typ, "standard": 128 if typ in ("pan", "tilt") else 0}
    if vorlage == "SpeedPanTiltSlowFast":
        kanal.update(schnell_bei=255, standard=255)   # Ohne Vorgabe nicht im Schneckentempo
    elif vorlage == "SpeedPanTiltFastSlow":
        kanal.update(schnell_bei=0)
    return kanal


def wandle(xml: bytes) -> dict:
    wurzel = ElementTree.fromstring(xml)
    if wurzel.tag != NS + "FixtureDefinition":
        raise ValueError("Das ist keine QLC+-Gerätedatei.")
    hersteller = wurzel.findtext(NS + "Manufacturer", "Unbekannt").strip()
    modell = wurzel.findtext(NS + "Model", "Unbekannt").strip()
    kanaele = {k.get("Name"): wandle_kanal(k) for k in wurzel.findall(NS + "Channel")}

    grad = {"pan": None, "tilt": None}
    gewicht, winkel = None, None
    physik = wurzel.find(NS + "Physical")
    modi = []
    for modus in wurzel.findall(NS + "Mode"):
        plaetze = sorted(modus.findall(NS + "Channel"), key=lambda k: int(k.get("Number")))
        modi.append({"name": modus.get("Name"), "kanaele": [k.text for k in plaetze]})
        physik = modus.find(NS + "Physical") if modus.find(NS + "Physical") is not None else physik
    if physik is not None:
        fokus = physik.find(NS + "Focus")
        if fokus is not None:
            grad = {"pan": float(fokus.get("PanMax", 0)) or None,
                    "tilt": float(fokus.get("TiltMax", 0)) or None}
        masse = physik.find(NS + "Dimensions")
        gewicht = float(masse.get("Weight")) if masse is not None and masse.get("Weight") else None
        linse = physik.find(NS + "Lens")
        winkel = float(linse.get("DegreesMax", 0)) or None if linse is not None else None

    grobe = {}
    for name, kanal in kanaele.items():
        if kanal["typ"] in grad and grad[kanal["typ"]]:
            kanal["grad"] = grad[kanal["typ"]]
        if kanal["typ"] in ("pan", "tilt"):
            grobe[kanal["typ"]] = name
    for kanal in kanaele.values():
        if kanal["typ"] in ("pan_fein", "tilt_fein"):
            kanal.update(grob=grobe.get(kanal["typ"][:-5]), stufe=1)

    return {"id": f"{daten.dateiname(hersteller)}/{daten.dateiname(modell)}",
            "hersteller": hersteller, "name": modell, "kategorien": [wurzel.findtext(NS + "Type", "")],
            "physik": {"gewicht_kg": gewicht, "abstrahlwinkel_grad": winkel},
            "kanaele": kanaele, "modi": modi, "quelle": QUELLE, "handbuch_geprueft": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="QLC+-Gerätedatei importieren")
    parser.add_argument("datei", type=Path, nargs="+")
    args = parser.parse_args()
    for datei in args.datei:
        print(speichere_import(wandle(datei.read_bytes()), daten.Pfade().katalog), "importiert")


if __name__ == "__main__":
    main()
