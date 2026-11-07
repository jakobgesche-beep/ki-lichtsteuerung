"""Der Gerätekatalog: Was kann welcher Gerätetyp?

Jeder Gerätetyp ist eine JSON-Datei in catalog/. So sieht sie aus:

    id          "stairville/mh-x25" (Ordner/Datei)
    hersteller, name
    kategorien  zum Beispiel ["Moving Head"]
    physik      gewicht_kg, abstrahlwinkel_grad
    kanaele     Name -> Kanal (siehe unten)
    modi        Liste aus {"name": ..., "kanaele": [Kanalname, ...]}
    quelle      woher der Eintrag stammt und unter welcher Lizenz
    handbuch_geprueft   false, bis jemand ihn mit dem Handbuch verglichen hat

Ein Kanal hat einen `typ` (siehe KANAL_TYPEN) und einen `standard`-Wert.
Pan und Tilt haben zusätzlich `grad`, Feinkanäle (16 bit) ein `grob`.
`bereiche` teilt die Werte 0-255 auf, zum Beispiel beim Shutter:
    {"von": 0, "bis": 3, "typ": "zu"}
    {"von": 8, "bis": 215, "typ": "strobo", "hz_von": 1, "hz_bis": 20}

Die Prüfung und die Umrechnung in DMX lesen nur diese Daten. Deshalb kommt
im Programm kein einziger Modellname vor.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import daten

FARB_TYPEN = {
    "rot": "#ff0000", "gruen": "#00ff00", "blau": "#0000ff", "weiss": "#ffffff",
    "warmweiss": "#ffd9a0", "kaltweiss": "#dfeaff", "amber": "#ffb000",
    "uv": "#6000ff", "cyan": "#00ffff", "magenta": "#ff00ff", "gelb": "#ffff00",
    "limette": "#b0ff00", "indigo": "#4b00c0",
}
KANAL_TYPEN = {
    "dimmer", "pan", "tilt", "pan_fein", "tilt_fein", "fein", "strobo",
    "farbrad", "gobo", "gobo_rotation", "prisma", "fokus", "zoom", "iris",
    "tempo", "nebel", "luefter", "makro", "sonstiges",
} | set(FARB_TYPEN)

# Diese Kanäle starten Programme oder Reset. Die Prüfung hält sie auf `standard`.
GESPERRTE_TYPEN = {"makro"}


class KatalogFehler(Exception):
    """Ein Gerätetyp oder Modus fehlt oder ist kaputt."""


@dataclass
class Geraetetyp:
    """Ein Eintrag aus dem Katalog mit bequemen Hilfsfunktionen."""

    daten: dict

    @property
    def id(self) -> str:
        return self.daten["id"]

    def modus(self, name: str) -> dict:
        for modus in self.daten["modi"]:
            if modus["name"] == name:
                return modus
        namen = ", ".join(m["name"] for m in self.daten["modi"])
        raise KatalogFehler(f"{self.id} hat keinen Modus {name!r} (vorhanden: {namen}).")

    def kanalzahl(self, modus: str) -> int:
        return len(self.modus(modus)["kanaele"])

    def kanal(self, name: Optional[str]) -> Optional[dict]:
        """Kanal-Daten nach Name. Leere Plätze im Modus ergeben None."""
        if name is None:
            return None
        return self.daten["kanaele"].get(name)

    def kanaele_im_modus(self, modus: str) -> list:
        """Liste aus (Versatz ab Startadresse, Kanal). Leere Plätze entfallen."""
        ergebnis = []
        for versatz, name in enumerate(self.modus(modus)["kanaele"]):
            kanal = self.kanal(name)
            if kanal is not None:
                ergebnis.append((versatz, kanal))
        return ergebnis

    def kurzinfo(self) -> dict:
        return {
            "id": self.id,
            "hersteller": self.daten["hersteller"],
            "name": self.daten["name"],
            "kategorien": self.daten.get("kategorien", []),
            "modi": [
                {"name": m["name"], "kanaele": len(m["kanaele"])}
                for m in self.daten["modi"]
            ],
            "eigener_eintrag": self.daten.get("quelle", {}).get("art") != "ofl",
            "handbuch_geprueft": self.daten.get("handbuch_geprueft", False),
        }


def pruefe_eintrag(eintrag: dict) -> list:
    """Gibt alle Fehler eines Katalog-Eintrags als Sätze zurück (leer = in Ordnung)."""
    fehler = []
    for feld in ("id", "hersteller", "name", "kanaele", "modi"):
        if not eintrag.get(feld):
            fehler.append(f"Das Feld {feld!r} fehlt.")
    if fehler:
        return fehler
    if len(eintrag["id"].split("/")) != 2:
        fehler.append("Die id muss die Form hersteller/geraet haben.")
    for name, kanal in eintrag["kanaele"].items():
        if kanal.get("typ") not in KANAL_TYPEN:
            fehler.append(f"Kanal {name}: unbekannter Typ {kanal.get('typ')!r}.")
        if not 0 <= kanal.get("standard", 0) <= 255:
            fehler.append(f"Kanal {name}: Standardwert muss zwischen 0 und 255 liegen.")
        for bereich in kanal.get("bereiche", []):
            if not 0 <= bereich["von"] <= bereich["bis"] <= 255:
                fehler.append(f"Kanal {name}: Bereich {bereich['von']}-{bereich['bis']} ist ungültig.")
    for modus in eintrag["modi"]:
        if not modus.get("name") or not modus.get("kanaele"):
            fehler.append("Jeder Modus braucht einen Namen und mindestens einen Kanal.")
            continue
        for name in modus["kanaele"]:
            if name is not None and name not in eintrag["kanaele"]:
                fehler.append(f"Modus {modus['name']}: Kanal {name!r} ist nicht definiert.")
    return fehler


class Katalog:
    """Alle Gerätetypen. Eigene Einträge haben Vorrang vor importierten."""

    def __init__(self, ordner: Path, eingebaut: Optional[Path] = None):
        self.ordner = Path(ordner)
        self.eingebaut = Path(eingebaut) if eingebaut else None   # kommt mit der App und jedem Update
        self.typen = {}
        self.neu_laden()

    def neu_laden(self) -> None:
        self.typen = {}
        orte = [self.ordner / name for name in ("ofl", "importiert", "eigene")]
        if self.eingebaut:
            # Auch mitgelieferte eigene Einträge (zum Beispiel der Strobo ohne Namen)
            orte = [self.eingebaut / "ofl", self.eingebaut / "importiert", self.eingebaut / "eigene"] + orte
        for ort in orte:
            for pfad in sorted(ort.glob("*/*.json")):
                eintrag = daten.lese_json(pfad)
                self.typen[eintrag["id"]] = Geraetetyp(eintrag)

    def typ(self, typ_id: str) -> Geraetetyp:
        try:
            return self.typen[typ_id]
        except KeyError:
            raise KatalogFehler(f"Gerätetyp {typ_id!r} steht nicht im Katalog.") from None

    def suche(self, text: str = "", grenze: int = 50) -> list:
        """Findet Geräte, in denen alle Wörter aus `text` vorkommen."""
        woerter = text.lower().split()
        treffer = []
        for typ in self.typen.values():
            suchtext = f"{typ.daten['hersteller']} {typ.daten['name']} {typ.id}".lower()
            if all(wort in suchtext for wort in woerter):
                treffer.append(typ)
        # Eigene Einträge zuerst, sie sind meistens die gesuchten.
        treffer.sort(key=lambda t: (t.daten.get("quelle", {}).get("art") == "ofl",
                                    t.daten["hersteller"].lower(), t.daten["name"].lower()))
        return [t.kurzinfo() for t in treffer[:grenze]]

    def speichere_eigenen(self, eintrag: dict) -> Geraetetyp:
        """Speichert einen Eintrag aus dem Editor. Andere Quellen bleiben unberührt."""
        fehler = pruefe_eintrag(eintrag)
        if fehler:
            raise KatalogFehler(" ".join(fehler))
        hersteller, geraet = eintrag["id"].split("/")
        pfad = self.ordner / "eigene" / daten.dateiname(hersteller) / f"{daten.dateiname(geraet)}.json"
        eintrag = {**eintrag, "id": f"{daten.dateiname(hersteller)}/{daten.dateiname(geraet)}"}
        eintrag.setdefault("quelle", {"art": "eigener Eintrag"})
        if eintrag["quelle"].get("art") == "ofl":
            # Kopie aus der Library: Herkunft behalten (MIT-Lizenz verlangt die Nennung).
            eintrag["quelle"] = {**eintrag["quelle"], "art": "kopie von ofl"}
        eintrag["handbuch_geprueft"] = bool(eintrag.get("handbuch_geprueft", False))
        daten.schreibe_json(pfad, eintrag)
        self.typen[eintrag["id"]] = Geraetetyp(eintrag)
        return self.typen[eintrag["id"]]
