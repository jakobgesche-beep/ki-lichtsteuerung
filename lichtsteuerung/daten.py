"""Liest und schreibt die JSON-Dateien des Projekts.

Grundregel „Eine Quelle für alles": Alle Module holen ihre Daten über diese
Datei. Dateinamen stehen nur hier.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

# Läuft das Programm als fertige Mac-App, liegt der Code im App-Paket und darf
# nicht beschrieben werden. Ein Update tauscht das ganze Paket aus. Darum liegen
# die Show-Daten dann in einem eigenen Ordner, den kein Update anfasst.
ALS_APP = bool(getattr(sys, "frozen", False))
PROJEKT = Path(sys._MEIPASS) if ALS_APP else Path(__file__).resolve().parent.parent
STANDARD_DATEIEN = ("fixtures.json", "stage.json", "positions.json", "x32.json", "sicherheit.json")
STANDARD_ORDNER = ("profile", "cues")


class Pfade:
    """Alle Orte, an denen Show-Daten liegen. Tests geben einen eigenen Ordner an."""

    def __init__(self, wurzel: Path = PROJEKT, eingebauter_katalog: Optional[Path] = None):
        self.wurzel = Path(wurzel)
        self.katalog = self.wurzel / "catalog"
        self.eingebauter_katalog = eingebauter_katalog
        self.fixtures = self.wurzel / "fixtures.json"
        self.stage = self.wurzel / "stage.json"
        self.positions = self.wurzel / "positions.json"
        self.x32 = self.wurzel / "x32.json"
        self.sicherheit = self.wurzel / "sicherheit.json"
        self.profile = self.wurzel / "profile"
        self.sequenzen = self.wurzel / "cues" / "sequenzen"
        self.executoren = self.wurzel / "cues" / "executoren.json"
        self.sitzung = self.wurzel / "daten" / "sitzung.json"
        self.audio = self.wurzel / "daten" / "audio"
        self.proben = self.wurzel / "daten" / "proben"


def datenordner() -> Path:
    """Wo die App ihre Show-Daten ablegt. LICHT_DATEN ist für Tests gedacht."""
    return Path(os.environ.get("LICHT_DATEN", Path.home() / "Library/Application Support/Lichtsteuerung"))


def einrichten(ziel: Path, vorlage: Path = PROJEKT) -> None:
    """Legt beim ersten Start die Beispieldaten an. Vorhandenes bleibt immer unberührt."""
    ziel.mkdir(parents=True, exist_ok=True)
    for name in STANDARD_DATEIEN:
        if not (ziel / name).exists():
            shutil.copy(vorlage / name, ziel / name)
    for name in STANDARD_ORDNER:
        if not (ziel / name).exists():
            shutil.copytree(vorlage / name, ziel / name)


def standard_pfade() -> Pfade:
    """Im Projektordner die Dateien dort, in der App der eigene Datenordner."""
    if not ALS_APP:
        return Pfade()
    ordner = datenordner()
    einrichten(ordner)
    return Pfade(ordner, PROJEKT / "catalog")


def lese_json(pfad: Path, standard: Any = None) -> Any:
    """Liest eine JSON-Datei. Fehlt sie, kommt `standard` zurück."""
    try:
        with open(pfad, encoding="utf-8") as datei:
            return json.load(datei)
    except FileNotFoundError:
        return standard


def schreibe_json(pfad: Path, inhalt: Any) -> None:
    """Schreibt sicher: Erst in eine Hilfsdatei, dann umbenennen.

    Stürzt das Programm beim Schreiben ab, bleibt die alte Datei heil.
    """
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    griff, hilfsdatei = tempfile.mkstemp(dir=pfad.parent, suffix=".tmp")
    try:
        with os.fdopen(griff, "w", encoding="utf-8") as datei:
            json.dump(inhalt, datei, ensure_ascii=False, indent=2)
            datei.write("\n")
        os.replace(hilfsdatei, pfad)
    except BaseException:
        if os.path.exists(hilfsdatei):
            os.unlink(hilfsdatei)
        raise


def dateiname(name: str) -> str:
    """Macht aus einem Anzeigenamen einen sicheren Dateinamen.

    "Schulfest Abend" wird "schulfest-abend". Schrägstriche und Punkte
    fliegen raus, damit niemand Dateien außerhalb des Ordners schreiben kann.
    """
    text = name.lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(alt, neu)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        raise ValueError(f"Aus dem Namen {name!r} lässt sich kein Dateiname machen.")
    return text
