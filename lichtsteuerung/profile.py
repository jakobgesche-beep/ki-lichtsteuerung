"""Veranstaltungsprofile: die Grenzen, in denen die Engine live arbeitet.

Ein Profil ist eine JSON-Datei in profile/. Felder:
    name, palette (Farben), max_helligkeit (0-1), bewegung (aus/langsam/voll),
    beat_reaktion (0-1), strobo ("aus" oder {"max_blitze_pro_sekunde", "max_dauer_s"}),
    grundlicht (Szene für leise Stellen), hazer (true/false)

pruefe_profil() ist die Prüfung für jedes Profil, auch für solche, die später
die KI vorschlägt. Sie ändert nichts, sondern meldet Fehler.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import daten
from .farben import ist_farbe
from .sicherheit import Grenzen
from .szenen import pruefe_werte

BEWEGUNGEN = ("aus", "langsam", "voll")

# Falls gar kein Profil gewählt ist: ruhig und ohne jede Automatik.
RUHE_PROFIL = {
    "name": "Ruhe (kein Profil gewählt)", "palette": ["warmweiss"], "max_helligkeit": 0.5,
    "bewegung": "aus", "beat_reaktion": 0.0, "strobo": "aus", "hazer": False,
    "grundlicht": {"werte": [{"gruppe": "Farb-PARs", "farbe": "warmweiss", "helligkeit": 0.5}]},
}


def pruefe_profil(profil: dict, gruppen: Optional[list] = None) -> list:
    """Alle Fehler eines Profils als Sätze. Leer heißt: in Ordnung."""
    fehler = []
    if not str(profil.get("name", "")).strip():
        fehler.append("Das Profil braucht einen Namen.")
    palette = profil.get("palette")
    if not isinstance(palette, list) or not palette:
        fehler.append("Die Palette braucht mindestens eine Farbe.")
    else:
        fehler += [f"Unbekannte Farbe: {f}." for f in palette if not ist_farbe(str(f))]
    for feld in ("max_helligkeit", "beat_reaktion"):
        wert = profil.get(feld)
        if not isinstance(wert, (int, float)) or isinstance(wert, bool) or not 0 <= wert <= 1:
            fehler.append(f"{feld} muss zwischen 0 und 1 liegen.")
    if profil.get("bewegung") not in BEWEGUNGEN:
        fehler.append("bewegung muss aus, langsam oder voll sein.")
    if not isinstance(profil.get("hazer"), bool):
        fehler.append("hazer muss ja oder nein sein.")
    strobo = profil.get("strobo")
    if strobo != "aus":
        if not isinstance(strobo, dict):
            fehler.append('strobo muss "aus" sein oder Blitze und Dauer angeben.')
        else:
            for feld in ("max_blitze_pro_sekunde", "max_dauer_s"):
                wert = strobo.get(feld)
                if not isinstance(wert, (int, float)) or isinstance(wert, bool) or wert <= 0:
                    fehler.append(f"strobo: {feld} muss größer als 0 sein.")
    grundlicht = profil.get("grundlicht")
    if not isinstance(grundlicht, dict) or not grundlicht.get("werte"):
        fehler.append("Das Grundlicht darf nicht leer sein: Es ist der sichere Rückfall.")
    else:
        fehler += pruefe_werte(grundlicht["werte"], gruppen)
    return fehler


def strobo_grenzen(profil: dict, grenzen: Grenzen) -> tuple:
    """(Blitze pro Sekunde, Dauer), die wirklich gelten. Die feste Grenze gewinnt immer."""
    strobo = profil.get("strobo", "aus")
    if strobo == "aus":
        return 0.0, 0.0
    return (min(strobo["max_blitze_pro_sekunde"], grenzen.strobo_max_hz),
            min(strobo["max_dauer_s"], grenzen.strobo_max_dauer_s))


class Profile:
    def __init__(self, ordner: Path):
        self.ordner = Path(ordner)

    def namen(self) -> list:
        return sorted(daten.lese_json(p)["name"] for p in self.ordner.glob("*.json"))

    def laden(self, name: str) -> dict:
        profil = daten.lese_json(self.ordner / f"{daten.dateiname(name)}.json")
        if profil is None:
            raise ValueError(f"Profil {name!r} gibt es nicht.")
        fehler = pruefe_profil(profil)
        if fehler:
            raise ValueError(f"Profil {name!r} ist fehlerhaft: {' '.join(fehler)}")
        return profil

    def speichern(self, profil: dict) -> None:
        fehler = pruefe_profil(profil)
        if fehler:
            raise ValueError(" ".join(fehler))
        daten.schreibe_json(self.ordner / f"{daten.dateiname(profil['name'])}.json", profil)
