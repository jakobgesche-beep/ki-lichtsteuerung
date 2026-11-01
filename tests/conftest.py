"""Gemeinsame Bausteine für die Tests. Jeder Test bekommt eigene Dateien."""
import json
import shutil
from pathlib import Path

import pytest

from lichtsteuerung.daten import PROJEKT, Pfade
from lichtsteuerung.katalog import Katalog

TEST_PAR = {
    "id": "test/par", "hersteller": "Test", "name": "PAR", "physik": {"gewicht_kg": 2.0},
    "kanaele": {
        "Dimmer": {"typ": "dimmer", "standard": 0},
        "Rot": {"typ": "rot", "standard": 0},
        "Grün": {"typ": "gruen", "standard": 0},
        "Blau": {"typ": "blau", "standard": 0},
        "Strobo": {"typ": "strobo", "standard": 0, "bereiche": [
            {"von": 0, "bis": 9, "typ": "offen"},
            {"von": 10, "bis": 255, "typ": "strobo", "hz_von": 1, "hz_bis": 20}]},
        "Programm": {"typ": "makro", "standard": 0},
    },
    "modi": [{"name": "6", "kanaele": ["Dimmer", "Rot", "Grün", "Blau", "Strobo", "Programm"]},
             {"name": "4", "kanaele": ["Rot", "Grün", "Blau", "Dimmer"]}],
}

TEST_KOPF = {
    "id": "test/kopf", "hersteller": "Test", "name": "Kopf", "physik": {"gewicht_kg": 5.0},
    "kanaele": {
        "Pan": {"typ": "pan", "standard": 128, "grad": 540},
        "Pan fein": {"typ": "pan_fein", "standard": 0, "grob": "Pan", "stufe": 1},
        "Tilt": {"typ": "tilt", "standard": 128, "grad": 270},
        "Tilt fein": {"typ": "tilt_fein", "standard": 0, "grob": "Tilt", "stufe": 1},
        "Dimmer": {"typ": "dimmer", "standard": 0},
        "Shutter": {"typ": "strobo", "standard": 4, "bereiche": [
            {"von": 0, "bis": 3, "typ": "zu"}, {"von": 4, "bis": 7, "typ": "offen"},
            {"von": 8, "bis": 255, "typ": "strobo", "hz_von": None, "hz_bis": None}]},
        "Farbe": {"typ": "farbrad", "standard": 0, "bereiche": [
            {"von": 0, "bis": 9, "typ": "platz", "name": "Offen", "farbe": "#ffffff"},
            {"von": 10, "bis": 19, "typ": "platz", "name": "Rot", "farbe": "#ff0000"},
            {"von": 20, "bis": 29, "typ": "platz", "name": "Blau", "farbe": "#0000ff"}]},
    },
    "modi": [{"name": "7", "kanaele": ["Pan", "Pan fein", "Tilt", "Tilt fein", "Dimmer",
                                       "Shutter", "Farbe"]}],
}


@pytest.fixture
def ordner(tmp_path) -> Path:
    """Ein eigener Show-Ordner: echte Beispieldaten, kleiner Katalog."""
    for datei in ("stage.json", "positions.json", "sicherheit.json"):
        shutil.copy(PROJEKT / datei, tmp_path / datei)
    (tmp_path / "catalog" / "eigene" / "test").mkdir(parents=True)
    for eintrag in (TEST_PAR, TEST_KOPF):
        name = eintrag["id"].split("/")[1]
        (tmp_path / "catalog" / "eigene" / "test" / f"{name}.json").write_text(
            json.dumps({**eintrag, "quelle": {"art": "test"}}), encoding="utf-8")
    return tmp_path


@pytest.fixture
def pfade(ordner) -> Pfade:
    return Pfade(ordner)


@pytest.fixture
def katalog(pfade) -> Katalog:
    return Katalog(pfade.katalog)
