"""Vorschau und „Übernehmen": die Schleuse für alles, was gespeichert werden soll.

Grundregel: Nichts von der KI geht direkt live. Ein Entwurf erscheint nur in der
3D-Vorschau, nie am DMX-Ausgang. Gespeichert wird erst bei uebernehmen(). Es
gibt hier bewusst keine Funktion, die etwas live schaltet.

Der Szenen-Editor benutzt diesen Weg schon heute. Licht-Chat (Schritt 8) und
Profile per API (Schritt 9) rufen später genau dieselben Funktionen auf:
    entwurf_setzen("szene", {...})     entwurf_setzen("profil", {...})
"""
from __future__ import annotations

from typing import Optional

from .cues import pruefe_szene
from .profile import pruefe_profil
from .pruefung import Pruefer, Vorgaben
from .szenen import loese_auf


class Vorschau:
    def __init__(self, show):
        self.show = show
        self.art: Optional[str] = None
        self.inhalt: Optional[dict] = None
        self.geraete: Optional[list] = None
        self.meldungen = []

    def entwurf_setzen(self, art: str, inhalt: dict) -> list:
        """Prüft den Entwurf und baut das Vorschau-Bild. Gibt Hinweise zurück."""
        fehler, werte = self._pruefen(art, inhalt)
        if fehler:
            raise ValueError(" ".join(fehler))
        show = self.show
        with show.sperre:
            zustand, meldungen = loese_auf(werte, show.patch, show.buehne, show.positionen)
            bild = show.renderer.bild(zustand)
            # Eine eigene Prüfung: Die Vorschau darf die Wächter der Show nicht anfassen.
            pruefer = Pruefer(show.patch, show.buehne, show.grenzen)
            hz, dauer = show.grenzen.strobo_max_hz, show.grenzen.strobo_max_dauer_s
            bild, hinweise, _ = pruefer.pruefe(bild, Vorgaben(strobo_max_hz=hz, strobo_max_dauer_s=dauer), 0.0)
            self.art, self.inhalt = art, inhalt
            self.geraete = show.simulator.lies(bytes(bild))
            self.meldungen = meldungen + hinweise
        return self.meldungen

    def _pruefen(self, art: str, inhalt: dict) -> tuple:
        show = self.show
        if art == "szene":
            return pruefe_szene(inhalt, show.patch, show.positionen), inhalt.get("werte", [])
        if art == "profil":
            return pruefe_profil(inhalt, show.patch.gruppen()), inhalt.get("grundlicht", {}).get("werte", [])
        raise ValueError(f"Unbekannte Art von Entwurf: {art}")

    def verwerfen(self) -> None:
        self.art = self.inhalt = self.geraete = None
        self.meldungen = []

    def uebernehmen(self) -> str:
        """Speichert den Entwurf als Datei. Live geht er damit noch nicht."""
        if self.inhalt is None:
            raise ValueError("Es gibt keinen Entwurf zum Übernehmen.")
        name = self.inhalt["name"]
        if self.art == "szene":
            self.show.szenen.schreiben(self.inhalt)
        else:
            self.show.profile.speichern(self.inhalt)
        self.verwerfen()
        return name
