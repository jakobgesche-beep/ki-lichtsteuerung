"""Liest und schreibt die JSON-Dateien des Projekts.

Grundregel „Eine Quelle für alles": Alle Module holen ihre Daten über diese
Datei. Dateinamen stehen nur hier.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

PROJEKT = Path(__file__).resolve().parent.parent


class Pfade:
    """Alle Orte, an denen Show-Daten liegen. Tests geben einen eigenen Ordner an."""

    def __init__(self, wurzel: Path = PROJEKT):
        self.wurzel = Path(wurzel)
        self.katalog = self.wurzel / "catalog"
        self.fixtures = self.wurzel / "fixtures.json"
        self.stage = self.wurzel / "stage.json"
        self.positions = self.wurzel / "positions.json"
        self.x32 = self.wurzel / "x32.json"
        self.sicherheit = self.wurzel / "sicherheit.json"
        self.profile = self.wurzel / "profile"
        self.szenen = self.wurzel / "cues" / "szenen"
        self.cuelisten = self.wurzel / "cues" / "listen"
        self.fader = self.wurzel / "cues" / "fader.json"
        self.sitzung = self.wurzel / "daten" / "sitzung.json"
        self.audio = self.wurzel / "daten" / "audio"


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
