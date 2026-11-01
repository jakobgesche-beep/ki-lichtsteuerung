"""Importiert die Open Fixture Library (OFL) in unser Katalog-Format.

Quelle: https://github.com/OpenLightingProject/open-fixture-library (MIT-Lizenz)

Aufruf:   python -m lichtsteuerung.importe.ofl
          (lädt die aktuelle Fassung; braucht Internet, läuft nie während einer Show)
Oder:     python -m lichtsteuerung.importe.ofl --ordner /pfad/zur/entpackten/ofl
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from .. import daten
from ..katalog import pruefe_eintrag

ARCHIV_URL = ("https://codeload.github.com/OpenLightingProject/"
              "open-fixture-library/tar.gz/refs/heads/master")
PROJEKT_URL = "https://github.com/OpenLightingProject/open-fixture-library"

# Farbnamen der OFL in unsere Kanaltypen
OFL_FARBEN = {
    "Red": "rot", "Green": "gruen", "Blue": "blau", "White": "weiss",
    "Warm White": "warmweiss", "Cold White": "kaltweiss", "Amber": "amber",
    "UV": "uv", "Cyan": "cyan", "Magenta": "magenta", "Yellow": "gelb",
    "Lime": "limette", "Indigo": "indigo",
}
EINFACHE_TYPEN = {
    "Intensity": "dimmer", "Pan": "pan", "Tilt": "tilt", "Focus": "fokus",
    "Zoom": "zoom", "BeamAngle": "zoom", "Iris": "iris", "Prism": "prisma",
    "PrismRotation": "prisma", "Fog": "nebel", "FogOutput": "nebel",
    "PanTiltSpeed": "tempo", "Speed": "tempo", "EffectSpeed": "tempo",
    "Time": "tempo", "Maintenance": "makro", "Effect": "makro",
    "ColorPreset": "makro", "Generic": "sonstiges", "NoFunction": "sonstiges",
}


def zahl_aus(text, einheit: str):
    """Liest "540deg" oder "20Hz" als Zahl. Wörter wie "fast" ergeben None."""
    if isinstance(text, (int, float)):
        return float(text)
    treffer = re.fullmatch(rf"(-?\d+(?:\.\d+)?){einheit}", str(text or ""))
    return float(treffer.group(1)) if treffer else None


def hertz(faehigkeit: dict):
    """Strobo-Tempo in Hz. (None, None), wenn die Bibliothek nur "fast" sagt."""
    start = faehigkeit.get("speedStart", faehigkeit.get("speed"))
    ende = faehigkeit.get("speedEnd", faehigkeit.get("speed"))
    faktor = {"Hz": 1.0, "bpm": 1 / 60}
    for einheit, umrechnung in faktor.items():
        von, bis = zahl_aus(start, einheit), zahl_aus(ende, einheit)
        if von is not None and bis is not None:
            return von * umrechnung, bis * umrechnung
    return None, None


def wandle_bereich(faehigkeit: dict, raeder: dict) -> dict:
    """Eine OFL-Fähigkeit wird ein Bereich in unserem Format."""
    von, bis = faehigkeit.get("dmxRange", [0, 255])
    while bis > 255:   # 16-bit-Angaben: Wir rechnen im groben Kanal.
        von, bis = von // 256, bis // 256
    bereich = {"von": von, "bis": bis, "typ": "sonstiges"}
    art = faehigkeit["type"]
    if art == "ShutterStrobe":
        effekt = faehigkeit.get("shutterEffect")
        if effekt == "Closed":
            bereich["typ"] = "zu"
        elif effekt == "Open":
            bereich["typ"] = "offen"
        else:
            # Puls, Rampe, Zufall: Für die Sicherheit zählt alles als Strobo.
            hz_von, hz_bis = hertz(faehigkeit)
            bereich.update(typ="strobo", hz_von=hz_von, hz_bis=hz_bis)
    elif art == "StrobeSpeed":
        hz_von, hz_bis = hertz(faehigkeit)
        bereich.update(typ="strobo", hz_von=hz_von, hz_bis=hz_bis)
    elif art == "Effect" and "strobe" in str(faehigkeit.get("effectName", "")).lower():
        bereich.update(typ="strobo", hz_von=None, hz_bis=None)
    elif art == "Intensity":
        bereich["typ"] = "dimmer"
    elif art == "NoFunction":
        bereich["typ"] = "aus"
    elif art in ("WheelSlot", "WheelShake"):
        rad = raeder.get(faehigkeit.get("wheel"), {})
        nummer = faehigkeit.get("slotNumber")
        if art == "WheelSlot" and isinstance(nummer, int) and rad.get("slots"):
            # OFL zählt ab 1 und wiederholt das Rad bei größeren Nummern.
            platz = rad["slots"][(nummer - 1) % len(rad["slots"])]
            if platz.get("type") == "Open":
                bereich.update(typ="platz", name="Offen", farbe="#ffffff")
            elif platz.get("type") == "Color":
                bereich.update(typ="platz", name=platz.get("name", f"Platz {nummer}"))
                if platz.get("colors"):
                    bereich["farbe"] = platz["colors"][0]
            elif platz.get("type") == "Gobo":
                bereich.update(typ="platz", name=platz.get("name", f"Gobo {nummer}"))
    return bereich


def kanal_typ(name: str, faehigkeiten: list, raeder: dict) -> str:
    """Bestimmt den Typ. Bei gemischten Kanälen zählt die Mehrheit der DMX-Werte."""
    punkte = {}
    for faehigkeit in faehigkeiten:
        art = faehigkeit["type"]
        if art == "ColorIntensity":
            typ = OFL_FARBEN.get(faehigkeit.get("color"), "sonstiges")
        elif art in ("ShutterStrobe", "StrobeSpeed", "StrobeDuration"):
            typ = "strobo"
        elif art in ("WheelSlot", "WheelShake", "WheelRotation"):
            rad_name = faehigkeit.get("wheel") or name
            rad = raeder.get(rad_name, {})
            arten = {platz.get("type") for platz in rad.get("slots", [])}
            typ = "gobo" if "Gobo" in arten or "gobo" in str(rad_name).lower() else "farbrad"
        elif art == "WheelSlotRotation":
            typ = "gobo_rotation"
        else:
            typ = EINFACHE_TYPEN.get(art, "sonstiges")
        von, bis = faehigkeit.get("dmxRange", [0, 255])
        punkte[typ] = punkte.get(typ, 0) + bis - von + 1
    for wichtig in ("pan", "tilt"):
        if wichtig in punkte:
            return wichtig
    # "sonstiges" gewinnt nur, wenn sonst nichts da ist.
    punkte.pop("sonstiges", None)
    return max(punkte, key=punkte.get) if punkte else "sonstiges"


def standardwert(kanal: dict, bereiche: list, typ: str) -> int:
    wert = kanal.get("defaultValue")
    if isinstance(wert, str) and wert.endswith("%"):
        return round(float(wert[:-1]) * 2.55)
    if isinstance(wert, (int, float)):
        return max(0, min(255, int(wert)))
    if typ in ("pan", "tilt"):
        return 128
    if typ == "strobo":
        # Sicherer Standard: Der Shutter steht offen und blitzt nicht.
        offene = [b for b in bereiche if b["typ"] == "offen"]
        return offene[0]["von"] if offene else 0
    return 0


def wandle_kanal(name: str, kanal: dict, raeder: dict) -> dict:
    faehigkeiten = kanal.get("capabilities") or [kanal.get("capability", {"type": "Generic"})]
    typ = kanal_typ(name, faehigkeiten, raeder)
    bereiche = [wandle_bereich(f, raeder) for f in faehigkeiten]
    ergebnis = {"typ": typ, "standard": standardwert(kanal, bereiche, typ)}
    if any(b["typ"] != "sonstiges" for b in bereiche) or len(bereiche) > 1:
        ergebnis["bereiche"] = bereiche
    if typ in ("pan", "tilt"):
        for faehigkeit in faehigkeiten:
            start = zahl_aus(faehigkeit.get("angleStart"), "deg")
            ende = zahl_aus(faehigkeit.get("angleEnd"), "deg")
            if start is not None and ende is not None:
                ergebnis["grad"] = abs(ende - start)
    return ergebnis


def pixel_liste(fixture: dict, wiederholen) -> list:
    """Welche Pixel bei einem Matrix-Gerät (LED-Leiste) dran sind."""
    if isinstance(wiederholen, list):
        return wiederholen
    matrix = fixture.get("matrix", {})
    if "pixelKeys" in matrix:
        tasten = [t for ebene in matrix["pixelKeys"] for reihe in ebene for t in reihe if t]
    else:
        x, y, z = matrix.get("pixelCount", [1, 1, 1])
        tasten = []
        for tz in range(1, z + 1):
            for ty in range(1, y + 1):
                for tx in range(1, x + 1):
                    teile = [str(n) for n, m in ((tx, x), (ty, y), (tz, z)) if m > 1]
                    tasten.append(" ".join(teile) or "1")
    return tasten


def fein_aus_vorlage(alias: str, taste: str, vorlagen: dict, kanaele: dict) -> None:
    """Feinkanal eines Pixels, zum Beispiel "Red $pixelKey fine"."""
    for vorlage, kanal in vorlagen.items():
        aliase = kanal.get("fineChannelAliases", [])
        if alias in aliase:
            kanaele[alias.replace("$pixelKey", taste)] = {
                "typ": "fein", "standard": 0, "stufe": aliase.index(alias) + 1,
                "grob": vorlage.replace("$pixelKey", taste)}
            return


def aus_vorlage(name: str, vorlagen: dict, kanaele: dict, raeder: dict) -> None:
    """Kanäle wie "Red Master" entstehen aus der Vorlage "Red $pixelKey"."""
    for vorlage, kanal in vorlagen.items():
        muster = re.escape(vorlage).replace(r"\$pixelKey", ".+")
        if re.fullmatch(muster, name):
            kanaele[name] = wandle_kanal(name, kanal, raeder)
            return


def erweitere_modus(fixture: dict, kanalnamen: list, kanaele: dict) -> list:
    """Löst die Pixel-Wiederholungen der OFL zu einer flachen Kanalliste auf."""
    vorlagen = fixture.get("templateChannels", {})
    flach = []
    for eintrag in kanalnamen:
        if not isinstance(eintrag, dict):
            if eintrag is not None and eintrag not in kanaele:
                aus_vorlage(eintrag, vorlagen, kanaele, fixture.get("wheels", {}))
            flach.append(eintrag)
            continue
        pixel = pixel_liste(fixture, eintrag["repeatFor"])
        namen = eintrag["templateChannels"]
        if eintrag.get("channelOrder") == "perChannel":
            paare = [(n, p) for n in namen for p in pixel]
        else:
            paare = [(n, p) for p in pixel for n in namen]
        for name, taste in paare:
            if name is None:
                flach.append(None)
                continue
            konkret = name.replace("$pixelKey", str(taste))
            if konkret not in kanaele and name in vorlagen:
                kanaele[konkret] = wandle_kanal(name, vorlagen[name], fixture.get("wheels", {}))
            elif konkret not in kanaele:
                fein_aus_vorlage(name, str(taste), vorlagen, kanaele)
            flach.append(konkret)
    return flach


def lese_fein_kanaele(quelle: dict, kanaele: dict) -> None:
    """Legt für 16-bit-Kanäle die Feinkanäle an ("Pan fine" gehört zu "Pan")."""
    for name, kanal in quelle.items():
        for stufe, alias in enumerate(kanal.get("fineChannelAliases", []), start=1):
            typ = kanaele[name]["typ"]
            kanaele[alias] = {
                "typ": f"{typ}_fein" if typ in ("pan", "tilt") else "fein",
                "standard": 0, "grob": name, "stufe": stufe,
            }


def lese_schalt_kanaele(quelle: dict, kanaele: dict) -> None:
    """Manche Kanäle wechseln ihre Bedeutung, je nach Wert eines anderen Kanals.

    Die OFL nennt das "switchChannels". Wir nehmen die Bedeutung, die in der
    ersten Stellung des Schalters gilt, also die im Normalbetrieb.
    """
    for kanal in quelle.values():
        for faehigkeit in kanal.get("capabilities", []):
            for alias, ziel in faehigkeit.get("switchChannels", {}).items():
                if alias not in kanaele and ziel in kanaele:
                    kanaele[alias] = dict(kanaele[ziel])


def wandle_geraet(hersteller_id: str, hersteller: str, datei_name: str, fixture: dict) -> dict:
    """Wandelt eine OFL-Datei in einen Katalog-Eintrag um."""
    raeder = fixture.get("wheels", {})
    quelle = fixture.get("availableChannels", {})
    kanaele = {name: wandle_kanal(name, k, raeder) for name, k in quelle.items()}
    lese_fein_kanaele(quelle, kanaele)
    lese_schalt_kanaele(quelle, kanaele)
    modi = []
    for modus in fixture.get("modes", []):
        modi.append({
            "name": modus["name"],
            "kanaele": erweitere_modus(fixture, modus.get("channels", []), kanaele),
        })
    physisch = fixture.get("physical", {})
    linse = physisch.get("lens", {}).get("degreesMinMax") or [None]
    return {
        "id": f"{hersteller_id}/{datei_name}",
        "hersteller": hersteller,
        "name": fixture["name"],
        "kategorien": fixture.get("categories", []),
        "physik": {"gewicht_kg": physisch.get("weight"), "abstrahlwinkel_grad": linse[-1]},
        "kanaele": kanaele,
        "modi": modi,
        "quelle": {"art": "ofl", "name": "Open Fixture Library", "url": PROJEKT_URL,
                   "lizenz": "MIT"},
        "handbuch_geprueft": False,
    }


def importiere(ofl_ordner: Path, ziel: Path) -> dict:
    """Ersetzt catalog/ofl durch die Geräte aus `ofl_ordner`. Gibt Zahlen zurück."""
    with open(ofl_ordner / "fixtures" / "manufacturers.json", encoding="utf-8") as datei:
        hersteller = json.load(datei)
    if ziel.exists():
        shutil.rmtree(ziel)
    ergebnis = {"importiert": 0, "uebersprungen": []}
    for pfad in sorted((ofl_ordner / "fixtures").glob("*/*.json")):
        hersteller_id = pfad.parent.name
        with open(pfad, encoding="utf-8") as datei:
            fixture = json.load(datei)
        if "redirectTo" in fixture:
            continue
        try:
            eintrag = wandle_geraet(hersteller_id, hersteller[hersteller_id]["name"],
                                    pfad.stem, fixture)
            fehler = pruefe_eintrag(eintrag)
        except (KeyError, TypeError, ValueError, IndexError) as grund:
            fehler = [repr(grund)]
        if fehler:
            ergebnis["uebersprungen"].append(f"{hersteller_id}/{pfad.stem}: {fehler[0]}")
            continue
        daten.schreibe_json(ziel / hersteller_id / f"{pfad.stem}.json", eintrag)
        ergebnis["importiert"] += 1
    return ergebnis


def lade_archiv(ziel: Path) -> Path:
    """Lädt das Archiv herunter und entpackt nur Gerätedaten und Lizenz."""
    with urllib.request.urlopen(ARCHIV_URL, timeout=120) as antwort:
        inhalt = antwort.read()
    with tarfile.open(fileobj=io.BytesIO(inhalt), mode="r:gz") as archiv:
        for eintrag in archiv.getmembers():
            teile = Path(eintrag.name).parts
            if eintrag.isfile() and len(teile) >= 2 and teile[1] in ("fixtures", "LICENSE"):
                ausgabe = ziel.joinpath(*teile[1:])
                ausgabe.parent.mkdir(parents=True, exist_ok=True)
                ausgabe.write_bytes(archiv.extractfile(eintrag).read())
    return ziel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ordner", type=Path, help="schon entpackte OFL statt Download")
    args = parser.parse_args()
    ziel = daten.Pfade().katalog / "ofl"
    if args.ordner:
        ergebnis = importiere(args.ordner, ziel)
    else:
        with tempfile.TemporaryDirectory() as hilfsordner:
            ergebnis = importiere(lade_archiv(Path(hilfsordner)), ziel)
    print(f"{ergebnis['importiert']} Geräte importiert.")
    for zeile in ergebnis["uebersprungen"]:
        print("  übersprungen:", zeile)


if __name__ == "__main__":
    main()
