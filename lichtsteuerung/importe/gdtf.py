"""Importiert GDTF-Dateien (.gdtf), das Format, das grandMA3 einliest.

Eine .gdtf-Datei ist ein ZIP-Archiv mit einer description.xml darin. Wir lesen
nur diese eine Datei. Viele Geräte gibt es auf gdtf-share.com (kostenloses Konto).

Aufruf:   python -m lichtsteuerung.importe.gdtf datei.gdtf
"""
from __future__ import annotations

import argparse
import io
import re
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

from .. import daten
from .gemeinsam import speichere_import

ATTRIBUTE = {
    "Dimmer": "dimmer", "Pan": "pan", "Tilt": "tilt", "ColorAdd_R": "rot", "ColorAdd_G": "gruen",
    "ColorAdd_B": "blau", "ColorAdd_W": "weiss", "ColorAdd_A": "amber", "ColorAdd_UV": "uv",
    "ColorAdd_C": "cyan", "ColorAdd_M": "magenta", "ColorAdd_Y": "gelb", "ColorAdd_WW": "warmweiss",
    "ColorAdd_CW": "kaltweiss", "ColorAdd_RY": "amber", "ColorAdd_GY": "limette",
    "Zoom": "zoom", "Focus1": "fokus", "Iris": "iris", "Prism1": "prisma", "Fog1": "nebel",
    "Haze": "nebel", "PanTiltSpeed": "tempo", "PanTiltTime": "tempo",
}


def wert_lesen(text: str) -> int:
    """GDTF schreibt "128/1" oder "32768/2": Wert und Byte-Zahl. Wir wollen 0 bis 255."""
    wert, bytes_ = (text or "0/1").split("/")
    return int(wert) >> (8 * (int(bytes_) - 1))


def typ_von(attribut: str) -> str:
    if attribut in ATTRIBUTE:
        return ATTRIBUTE[attribut]
    if re.fullmatch(r"Shutter\d+.*", attribut):
        return "strobo"
    if re.fullmatch(r"Color\d+", attribut):
        return "farbrad"
    if re.fullmatch(r"Gobo\d+", attribut):
        return "gobo"
    if re.fullmatch(r"Gobo\d+(Pos|PosRotate)", attribut):
        return "gobo_rotation"
    if attribut.startswith(("Control", "Effects", "Reset", "Function")):
        return "makro"
    return "sonstiges"


def farbe_aus_cie(text: str) -> str:
    """GDTF speichert Farben als CIE xyY. Wir brauchen ein einfaches #rrggbb."""
    x, y, helligkeit = (float(w) for w in text.split(","))
    if y <= 0:
        return "#ffffff"
    gross_x, gross_y, gross_z = x / y, 1.0, (1 - x - y) / y
    rgb = (3.2406 * gross_x - 1.5372 * gross_y - 0.4986 * gross_z,
           -0.9689 * gross_x + 1.8758 * gross_y + 0.0415 * gross_z,
           0.0557 * gross_x - 0.2040 * gross_y + 1.0570 * gross_z)
    groesster = max(max(rgb), 1e-6)
    return "#" + "".join(f"{round(max(0.0, w / groesster) * 255):02x}" for w in rgb)


def bereiche_aus(logisch, raeder: dict) -> tuple:
    """Liest die Teilbereiche eines Kanals. Gibt (Bereiche, Hauptfunktion) zurück."""
    funktionen = sorted(logisch.findall("ChannelFunction"), key=lambda f: wert_lesen(f.get("DMXFrom")))
    bereiche = []
    for nummer, funktion in enumerate(funktionen):
        von = wert_lesen(funktion.get("DMXFrom"))
        bis = wert_lesen(funktionen[nummer + 1].get("DMXFrom")) - 1 if nummer + 1 < len(funktionen) else 255
        attribut = funktion.get("Attribute", "")
        saetze = funktion.findall("ChannelSet")
        if re.fullmatch(r"Shutter\d+Strobe.*", attribut):
            hz_von = float(funktion.get("PhysicalFrom", 0))
            hz_bis = float(funktion.get("PhysicalTo", 0))
            hat_hz = attribut.endswith("Strobe") and hz_bis > 0
            bereiche.append({"von": von, "bis": bis, "typ": "strobo",
                             "hz_von": hz_von if hat_hz else None, "hz_bis": hz_bis if hat_hz else None})
        elif saetze:
            bereiche += satz_bereiche(saetze, von, bis, funktion.get("Wheel"), raeder)
        else:
            bereiche.append({"von": von, "bis": bis, "typ": "sonstiges", "name": funktion.get("Name", "")})
    return bereiche, funktionen[0] if funktionen else None


def satz_bereiche(saetze: list, von: int, bis: int, rad: str, raeder: dict) -> list:
    ergebnis = []
    for nummer, satz in enumerate(saetze):
        anfang = wert_lesen(satz.get("DMXFrom")) if satz.get("DMXFrom") else von
        ende = wert_lesen(saetze[nummer + 1].get("DMXFrom")) - 1 if nummer + 1 < len(saetze) else bis
        name = satz.get("Name", "")
        bereich = {"von": anfang, "bis": ende, "typ": "sonstiges", "name": name}
        if name.lower() in ("open", "closed"):
            bereich["typ"] = "offen" if name.lower() == "open" else "zu"
        if satz.get("WheelSlotIndex") and rad in raeder:
            platz = raeder[rad][int(satz.get("WheelSlotIndex")) - 1]
            bereich.update(typ="platz", name="Offen" if platz["name"].lower() == "open" else platz["name"])
            if platz.get("farbe"):
                bereich["farbe"] = platz["farbe"]
        ergebnis.append(bereich)
    return ergebnis


def lies_description(inhalt: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(inhalt)) as archiv:
            return archiv.read("description.xml")
    except (zipfile.BadZipFile, KeyError) as fehler:
        raise ValueError("Das ist keine gültige GDTF-Datei.") from fehler


def wandle(inhalt: bytes) -> dict:
    typ = ElementTree.fromstring(lies_description(inhalt)).find("FixtureType")
    if typ is None:
        raise ValueError("In der GDTF-Datei fehlt der Gerätetyp.")
    hersteller, modell = typ.get("Manufacturer", "Unbekannt"), typ.get("Name", "Unbekannt")
    raeder = {}
    for rad in typ.findall("./Wheels/Wheel"):
        plaetze = []
        for platz in rad.findall("Slot"):
            eintrag = {"name": platz.get("Name", "")}
            if platz.get("Color"):
                eintrag["farbe"] = farbe_aus_cie(platz.get("Color"))
            plaetze.append(eintrag)
        raeder[rad.get("Name")] = plaetze

    kanaele, modi = {}, []
    for modus in typ.findall("./DMXModes/DMXMode"):
        belegt = {}
        for kanal in modus.findall("./DMXChannels/DMXChannel"):
            versatz = [int(z) for z in (kanal.get("Offset") or "").split(",") if z and z != "None"]
            if not versatz:
                continue      # virtueller Kanal ohne DMX-Adresse
            logisch = kanal.find("LogicalChannel")
            attribut = logisch.get("Attribute", "Unbekannt")
            name = f"{kanal.get('Geometry', '')} {attribut} ({modus.get('Name')})".strip()
            bereiche, haupt = bereiche_aus(logisch, raeder)
            eintrag = {"typ": typ_von(attribut), "standard": wert_lesen(kanal.get("Default"))}
            if eintrag["typ"] in ("pan", "tilt") and haupt is not None:
                eintrag["grad"] = abs(float(haupt.get("PhysicalTo", 0)) - float(haupt.get("PhysicalFrom", 0)))
            elif len(bereiche) > 1 or eintrag["typ"] in ("strobo", "farbrad", "gobo"):
                eintrag["bereiche"] = bereiche
            kanaele[name] = eintrag
            belegt[versatz[0]] = name
            for stufe, adresse in enumerate(versatz[1:], start=1):
                fein = f"{name} fein {stufe}"
                art = f"{eintrag['typ']}_fein" if eintrag["typ"] in ("pan", "tilt") else "fein"
                kanaele[fein] = {"typ": art, "standard": 0, "grob": name, "stufe": stufe}
                belegt[adresse] = fein
        if belegt:
            modi.append({"name": modus.get("Name"),
                         "kanaele": [belegt.get(n) for n in range(1, max(belegt) + 1)]})
    return {"id": f"{daten.dateiname(hersteller)}/{daten.dateiname(modell)}",
            "hersteller": hersteller, "name": modell, "kategorien": [],
            "physik": {"gewicht_kg": None, "abstrahlwinkel_grad": None},
            "kanaele": kanaele, "modi": modi,
            "quelle": {"art": "gdtf", "name": "GDTF-Datei"}, "handbuch_geprueft": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="GDTF-Datei importieren")
    parser.add_argument("datei", type=Path, nargs="+")
    args = parser.parse_args()
    for datei in args.datei:
        print(speichere_import(wandle(datei.read_bytes()), daten.Pfade().katalog), "importiert")


if __name__ == "__main__":
    main()
