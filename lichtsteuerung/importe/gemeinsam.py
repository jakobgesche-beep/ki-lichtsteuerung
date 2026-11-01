"""Was alle Datei-Importe teilen: den Eintrag in catalog/importiert/ speichern."""
from __future__ import annotations

from pathlib import Path

from .. import daten
from ..katalog import KatalogFehler, pruefe_eintrag


def speichere_import(eintrag: dict, katalog_ordner: Path) -> str:
    """Prüft einen importierten Eintrag und legt ihn ab. Gibt die id zurück."""
    fehler = pruefe_eintrag(eintrag)
    if fehler:
        raise KatalogFehler("Import fehlgeschlagen: " + " ".join(fehler))
    hersteller, geraet = eintrag["id"].split("/")
    daten.schreibe_json(Path(katalog_ordner) / "importiert" / hersteller / f"{geraet}.json", eintrag)
    return eintrag["id"]
