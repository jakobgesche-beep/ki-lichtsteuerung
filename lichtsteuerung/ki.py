"""Der Zugang zu Claude für die ganze Lichtsteuerung: Schlüssel, Modelle und Kosten an einer Stelle.

Drei Teile fragen Claude:
    Licht-Chat       programmiert Looks, Fader, Profile und Song-Shows (großes Modell, in der Probe)
    KI-Lichtdesign   baut aus einer Probe-Aufnahme die Show für einen Song (großes Modell, vor dem Auftritt)
    KI-Regie         sagt live alle paar Sekunden, was gerade los ist und welcher Look passt (schnelles Modell)

Grundregeln aus CLAUDE.md:
    Offline zuerst   Ohne Schlüssel oder ohne Internet läuft alles ohne Claude weiter.
    Kein Key im Code Der Schlüssel liegt nur in lokal.json im Datenordner (oder in ANTHROPIC_API_KEY).
                     Die Oberfläche sieht nur den Anfang.
    Kosten im Blick  Jede Antwort wird mitgezählt. Die Live-Regie hat zusätzlich ein Limit pro Sitzung.

Claude bekommt nie den Ton selbst, nur Zahlen und Namen.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Optional

from . import daten

MODELL = "claude-opus-5-5"            # Chat und Lichtdesign: gründlich
MODELL_SCHNELL = "claude-haiku-5-5"   # Live-Regie: antwortet in 1 bis 2 Sekunden
# Dollar pro Million Tokens (Eingabe, Ausgabe, Cache lesen, Cache schreiben). Nur für die Kosten-Anzeige.
PREISE = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
BEREICHE = ("chat", "design", "regie")


class Schluessel:
    """Der API-Schlüssel steht in lokal.json im Datenordner. Die Oberfläche sieht ihn nie ganz."""

    def __init__(self, pfad):
        self.pfad = pfad

    def _aus_datei(self) -> str:
        return str(daten.lese_json(self.pfad, {}).get("anthropic_api_key") or "").strip()

    def lesen(self) -> Optional[str]:
        return self._aus_datei() or os.environ.get("ANTHROPIC_API_KEY") or None

    def quelle(self) -> Optional[str]:
        if self._aus_datei():
            return "datei"
        return "umgebung" if os.environ.get("ANTHROPIC_API_KEY") else None

    def maskiert(self) -> Optional[str]:
        schluessel = self.lesen()
        return f"{schluessel[:7]}…{schluessel[-4:]}" if schluessel else None

    def speichern(self, schluessel: str) -> None:
        schluessel = schluessel.strip()
        if not re.fullmatch(r"sk-ant-[A-Za-z0-9_\-]{20,}", schluessel):
            raise ValueError("Das sieht nicht wie ein Claude-Schlüssel aus. Er beginnt mit sk-ant- "
                             "und steht in der Claude Console unter API Keys.")
        inhalt = daten.lese_json(self.pfad, {})
        inhalt["anthropic_api_key"] = schluessel
        daten.schreibe_json(self.pfad, inhalt)
        try:
            os.chmod(self.pfad, 0o600)       # nur der eigene Benutzer darf die Datei lesen
        except OSError:
            pass

    def loeschen(self) -> None:
        inhalt = daten.lese_json(self.pfad, {})
        if inhalt.pop("anthropic_api_key", None) is not None:
            daten.schreibe_json(self.pfad, inhalt)


def kosten_cent(usage, modell: str) -> float:
    """Ungefähre Kosten einer Antwort in Cent (Dollar-Cent, gerundet reicht für den Überblick)."""
    ein, aus, lesen, schreiben = PREISE.get(modell, PREISE[MODELL])
    try:
        dollar = (usage.input_tokens * ein + usage.output_tokens * aus
                  + (getattr(usage, "cache_read_input_tokens", 0) or 0) * lesen
                  + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * schreiben) / 1_000_000
    except (AttributeError, TypeError):
        return 0.0
    return dollar * 100


class KiKonto:
    """Schlüssel, Modelle und Kosten. Einstellungen stehen in lokal.json (bleibt auf diesem Rechner):

        "modell"            Modell für Chat und Lichtdesign (Standard claude-opus-5-5)
        "regie_modell"      Modell für die Live-Regie (Standard claude-haiku-5-5)
        "regie_limit_cent"  so viel darf die Live-Regie pro Sitzung kosten (Standard 100 Cent)
    """

    def __init__(self, pfad_lokal):
        self.pfad = pfad_lokal
        self.schluessel = Schluessel(pfad_lokal)
        self.kosten = {bereich: 0.0 for bereich in BEREICHE}     # Cent in dieser Sitzung
        self._sperre = threading.Lock()

    def einstellung(self, name: str, standard):
        wert = daten.lese_json(self.pfad, {}).get(name)
        return standard if wert in (None, "") else wert

    def modell(self) -> str:
        return str(self.einstellung("modell", MODELL))

    def modell_schnell(self) -> str:
        return str(self.einstellung("regie_modell", MODELL_SCHNELL))

    def regie_limit_cent(self) -> float:
        try:
            return float(self.einstellung("regie_limit_cent", 100.0))
        except (TypeError, ValueError):
            return 100.0

    def bereit(self) -> bool:
        return bool(self.schluessel.lesen())

    def client(self, zeitlimit_s: float, wiederholen: int = 2):
        import anthropic
        return anthropic.Anthropic(api_key=self.schluessel.lesen(), timeout=zeitlimit_s, max_retries=wiederholen)

    def buchen(self, bereich: str, usage, modell: str) -> float:
        cent = kosten_cent(usage, modell)
        with self._sperre:
            self.kosten[bereich] = self.kosten.get(bereich, 0.0) + cent
        return cent

    def status(self) -> dict:
        return {"bereit": self.bereit(), "quelle": self.schluessel.quelle(), "maskiert": self.schluessel.maskiert(),
                "modell": self.modell(), "modell_schnell": self.modell_schnell(),
                "kosten_cent": {b: round(c, 1) for b, c in self.kosten.items()},
                "kosten_gesamt_cent": round(sum(self.kosten.values()), 1)}


def antwort_text(antwort) -> str:
    """Der Text einer Antwort (Denk-Blöcke und Werkzeuge weggelassen)."""
    return "".join(getattr(b, "text", "") for b in antwort.content if getattr(b, "type", "") == "text").strip()
