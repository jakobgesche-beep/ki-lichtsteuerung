"""Wie man die DMX-Adresse am Gerät einstellt: DIP-Schalter (Binärcode) oder Display.

DIP-Schalter: Jeder Schalter zählt doppelt so viel wie der vorige.
    Schalter  1   2   3   4   5   6   7    8    9
    zählt     1   2   4   8  16  32  64  128  256
Adresse 28 = 16 + 8 + 4, also Schalter 5, 4 und 3 an (oben), alle anderen aus.
Viele Geräte haben hinter den Adress-Schaltern noch Schalter für den Modus. Beim Stairville LED PAR 64 müssen
10, 11 und 12 aus sein, sonst hört er nicht auf DMX (dann läuft Musiksteuerung oder Automatik).

Woher das Programm weiß, wie ein Gerät eingestellt wird (in dieser Reihenfolge):
  1. Feld "adresse_einstellen" im Katalogeintrag (bei eigenen Einträgen, catalog/eigene/…)
  2. BEKANNT unten (für Einträge aus der Open Fixture Library, die beim Neu-Import überschrieben würden)
  3. sonst unbekannt: Vorschlag für beide Arten (DIP mit 9 Adress-Schaltern und Display „A028“)

Dieselbe Rechnung steht für die Oberfläche in web/js/dip.js (dort live beim Tippen).
"""
from __future__ import annotations

from typing import Optional

ADRESS_SCHALTER = 9            # 1 bis 511; für 512 bräuchte man einen zehnten Schalter

# Schreibweise auf Displays: {} wird durch die Adresse ersetzt, z. B. "A{:03d}" -> A028
BEKANNT = {
    "stairville/led-par-64": {
        "art": "dip", "dip": {"anzahl": 12, "adresse": 9, "aus": [10, 11, 12]},
        "hinweis": "Schalter 10, 11 und 12 aus = DMX-Modus (Thomann-Anleitung, Kapitel 7.5)."},
    "stairville/led-par-56": {
        "art": "dip", "dip": {"anzahl": 12, "adresse": 9, "aus": [10, 11, 12]},
        "hinweis": "Schalter 10, 11 und 12 aus = DMX-Modus (Thomann-Anleitung, Kapitel 7.5)."},
    "stairville/mh-x25": {
        "art": "display", "display": "A{:03d}",
        "hinweis": "Am Display im Menü die Adresse einstellen (meist als A001 bis A512 angezeigt)."},
}

STANDARD = {"art": "unbekannt", "dip": {"anzahl": ADRESS_SCHALTER, "adresse": ADRESS_SCHALTER, "aus": []},
            "display": "A{:03d}",
            "hinweis": "Wie dieses Gerät eingestellt wird, steht in seinem Handbuch: entweder DIP-Schalter wie "
                       "gezeigt oder am Display."}


def info_fuer(typ_daten: Optional[dict]) -> dict:
    """Die Einstell-Art eines Gerätetyps (ohne Adresse). Geht so auch an die Oberfläche."""
    typ_daten = typ_daten or {}
    eigen = typ_daten.get("adresse_einstellen")
    roh = eigen if isinstance(eigen, dict) else BEKANNT.get(typ_daten.get("id", ""), STANDARD)
    art = roh.get("art", "unbekannt")
    dip = None
    if art in ("dip", "beides", "unbekannt"):
        quelle = roh.get("dip") or {}
        anzahl = int(quelle.get("anzahl", ADRESS_SCHALTER))
        dip = {"anzahl": max(1, min(16, anzahl)),
               "adresse": max(1, min(anzahl, int(quelle.get("adresse", min(anzahl, ADRESS_SCHALTER))))),
               "aus": [int(n) for n in quelle.get("aus", []) if 1 <= int(n) <= anzahl],
               "an": [int(n) for n in quelle.get("an", []) if 1 <= int(n) <= anzahl]}
    display = roh.get("display") if art in ("display", "beides", "unbekannt") else None
    return {"art": art, "dip": dip, "display": display, "hinweis": roh.get("hinweis", "")}


def einstellen(adresse: int, info: dict) -> dict:
    """Was man für diese Adresse am Gerät einstellt: Schalterstellungen und/oder Display-Text."""
    adresse = int(adresse)
    ergebnis = {"adresse": adresse, "art": info["art"], "dip": None, "display": None,
                "hinweis": info.get("hinweis", ""), "warnung": ""}
    dip = info.get("dip")
    if dip:
        schalter = []
        for nummer in range(1, dip["anzahl"] + 1):
            if nummer <= dip["adresse"]:
                schalter.append({"nr": nummer, "an": bool(adresse >> (nummer - 1) & 1), "rolle": "adresse"})
            else:
                schalter.append({"nr": nummer, "an": nummer in dip["an"], "rolle": "modus"})
        an = [s["nr"] for s in schalter if s["an"] and s["rolle"] == "adresse"]
        if adresse >= 2 ** dip["adresse"]:
            ergebnis["warnung"] = (f"Adresse {adresse} lässt sich mit {dip['adresse']} Adress-Schaltern nicht "
                                   f"einstellen (höchstens {2 ** dip['adresse'] - 1}).")
        teile = [("Schalter " + " + ".join(str(n) for n in an) + " an") if an else "alle Adress-Schalter aus"]
        if dip["aus"]:
            teile.append(", ".join(str(n) for n in dip["aus"]) + " aus")
        if dip["an"]:
            teile.append(", ".join(str(n) for n in dip["an"]) + " an")
        ergebnis["dip"] = {"schalter": schalter, "an": an, "text": ", ".join(teile)}
    if info.get("display"):
        try:
            ergebnis["display"] = info["display"].format(adresse)
        except (IndexError, KeyError, ValueError):
            ergebnis["display"] = f"{adresse:03d}"
    return ergebnis


def fuer_geraet(geraet: dict, typ_daten: dict) -> dict:
    return einstellen(geraet["adresse"], info_fuer(typ_daten))
