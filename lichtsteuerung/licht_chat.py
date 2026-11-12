"""Licht-Chat: Man beschreibt, was man sehen will. Daraus wird ein Vorschlag (eine Sequenz mit Cues).

Die Grundregeln aus CLAUDE.md gelten hier besonders:
    Offline zuerst      Der Chat braucht Internet, die Show nicht. Ohne Internet oder ohne Schlüssel
                        versteht der Chat einfache Sätze selbst ("Spots blau, langsamer Kreis").
    Nichts geht live    Ein Vorschlag erscheint nur in der 3D-Vorschau. Gespeichert und auf einen Fader
                        gelegt wird er erst mit "Übernehmen". Es gibt kein Werkzeug, das live sendet.
    Alles wird geprüft  Jeder Vorschlag läuft durch dieselbe Prüfung wie alles, was man von Hand speichert.
                        Danach prüft die Show jedes Bild noch einmal (Strobo-Grenze, Publikum).
    Kein Key im Code    Der Schlüssel liegt in lokal.json im Datenordner (nie im Repository)
                        oder in der Umgebungsvariable ANTHROPIC_API_KEY.

Claude bekommt nur Lichtdaten (Gerätenamen, Gruppen, Positionen, Sequenzen), nie Ton oder Bilder.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from typing import Optional

from . import daten
from .farben import FARBNAMEN
from .pult import ANZAHL_EXECUTOREN, BEWEGUNGS_ARTEN, EFFEKT_ARTEN, pruefe_sequenz

MODELL = "claude-opus-5-5"
MAX_ANFRAGEN = 4               # höchstens so viele Anfragen an Claude pro Nachricht (Korrekturen eingeschlossen)
MAX_NACHRICHTEN = 40           # danach beginnt ein neues Gespräch (der Verlauf wird nie gekürzt oder geändert)
ZEITLIMIT_S = 90.0
# Preise Claude Opus 5.5 in Dollar pro Million Tokens, nur für die Kosten-Anzeige
PREISE = {"eingabe": 4.0, "ausgabe": 20.0, "cache_lesen": 0.20, "cache_schreiben": 5.0}


# --- Der Schlüssel ---------------------------------------------------------------

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


# --- Was Claude über die Bühne wissen muss -----------------------------------------------

def strobo_grenze(show) -> float:
    return min(3.0, show.grenzen.strobo_max_hz)


def welt(show) -> dict:
    """Gruppen, Geräte und ihre Fähigkeiten, Positionen, Farben: alles, was ein Vorschlag benutzen darf."""
    geraete = [show.faehigkeiten(g) | {"strobo": show.strobo_art(g)} for g in show.patch.geraete]
    gruppen = {}
    for gruppe in show.patch.gruppen():
        mitglieder = [g for g in geraete if gruppe in g["gruppen"]]
        gruppen[gruppe] = {
            "geraete": [f"{g['name']} (id {g['id']})" for g in mitglieder],
            "beweglich": any(g["beweglich"] for g in mitglieder),
            "farbe": sorted({g["farbe"] or "keine" for g in mitglieder}),
            "farbrad": sorted({f["name"] for g in mitglieder for f in g["farbrad"] if f.get("name")}),
            "gobos": sorted({x for g in mitglieder for x in g["gobos"]}),
            "strobo": sorted({g["strobo"] for g in mitglieder if g["strobo"]}),
        }
    return {"gruppen": gruppen, "geraete": geraete, "positionen": list(show.positionen),
            "farben": list(FARBNAMEN), "effekte": EFFEKT_ARTEN, "strobo_max_hz": strobo_grenze(show)}


def welt_text(show) -> str:
    w = welt(show)
    zeilen = ["GERÄTE NACH GRUPPEN:"]
    for name, g in w["gruppen"].items():
        kann = []
        if "mischung" in g["farbe"]:
            kann.append("jede Farbe (RGB-Mischung)")
        if g["farbrad"]:
            kann.append("Farbrad: " + ", ".join(g["farbrad"]))
        if g["beweglich"]:
            kann.append("beweglich (Positionen und Bewegungs-Effekte)")
        if g["gobos"]:
            kann.append("Gobos: " + ", ".join(g["gobos"]))
        if "software" in g["strobo"] or "eingemessen" in g["strobo"]:
            kann.append("Strobo")
        zeilen.append(f"- Gruppe „{name}“: {', '.join(g['geraete'])}. Kann: {'; '.join(kann) or 'nur Helligkeit'}.")
    zeilen.append("POSITIONEN (nur diese Namen): " + (", ".join(w["positionen"]) or "keine"))
    zeilen.append("FARBEN (Namen) : " + ", ".join(w["farben"]) + " – oder jede Farbe als #rrggbb.")
    zeilen.append("EFFEKTE: " + ", ".join(f"{art} ({text})" for art, text in w["effekte"].items()))
    zeilen.append(f"STROBO: höchstens {w['strobo_max_hz']:g} Blitze pro Sekunde (feste Sicherheitsgrenze).")
    return "\n".join(zeilen)


def stand_text(show) -> str:
    """Was sich laufend ändert (Sequenzen, Fader). Kommt mit jeder Nachricht, nicht in den Systemtext."""
    pult = show.pult
    sequenzen = []
    for name in pult.sequenzen.namen():
        sequenz = pult.sequenzen.lesen(name) or {"cues": []}
        sequenzen.append(f"„{name}“ ({len(sequenz.get('cues', []))} Cues{', Song' if sequenz.get('zeitcode') else ''})")
    belegt = [f"{e.nummer}: {pult.anzeigename(e)}" for e in pult.executoren if e.art]
    return ("[Stand jetzt] Sequenzen: " + (", ".join(sequenzen) or "keine")
            + ". Belegte Fader: " + (", ".join(belegt) or "keine") + f". Fader gibt es 1 bis {ANZAHL_EXECUTOREN}.")


SYSTEMTEXT = """Du bist der Licht-Assistent der Technik-AG einer Schule. Du hilfst nur beim Programmieren von Licht \
(Looks, Cues, Sequenzen, Fader) für die Geräte unten. Bei allen anderen Themen antwortest du: \
„Da kann ich nicht helfen, ich mache nur Licht.“

So arbeitest du:
- Beschreibt jemand einen Look, eine Szene, einen Ablauf oder was auf einen Fader soll, rufst du das Werkzeug \
vorschlag_machen auf. Der Vorschlag erscheint zuerst nur in der 3D-Vorschau. Gespeichert und auf einen Fader gelegt \
wird er erst, wenn der Mensch „Übernehmen“ drückt. Du kannst nichts live schalten.
- Eine Sequenz hat einen oder mehrere Cues. Ein Look für einen Fader ist meistens eine Sequenz mit einem Cue. \
Mehrere Cues nur für Abläufe („erst blau, nach 4 Sekunden rot“: folgen_s = 4 im ersten Cue).
- Tracking: Was ein Cue nicht ändert, bleibt aus dem vorigen Cue stehen. Effekte gelten nur in dem Cue, in dem sie stehen.
- Benutze Gruppen. Ein einzelnes Gerät (geraet = id) nur, wenn es ausdrücklich gemeint ist.
- helligkeit 0 bis 1. farbe nur Namen aus der Liste oder #rrggbb. position nur Namen aus der Liste und nur für \
bewegliche Gruppen. gobo nur Namen, die die Gruppe hat. strobo_hz nur für Gruppen mit Strobo und nie über der Grenze. \
zeit_s ist die Überblendzeit in Sekunden.
- Effekte: tempo null heißt im Tempo der Musik (meistens richtig). beats = Beats pro Runde (4 ist ein Takt, 8 oder 16 \
ist ruhig). Bewegungs-Effekte (kreis, acht, schwenk, nicken, publikum) nur für bewegliche Gruppen. \
farbwechsel braucht eine Liste farben. dimmer_welle und dimmer_puls brauchen eine Helligkeit über 0 im selben Cue.
- Lieber ruhig und schön als hektisch: wenige Farben, die zusammenpassen, weiche Überblendungen, langsame Bewegung. \
Schnell und Strobo nur, wenn es ausdrücklich gewünscht ist.
- Soll eine vorhandene Sequenz geändert werden, lies sie zuerst mit sequenz_lesen. Im Vorschlag dann derselbe Name \
und ersetzt = true.
- Nennt der Mensch einen Fader, setze fader auf diese Nummer. Sonst fader = null (der Mensch wählt beim Übernehmen).
- Meldet die Prüfung Fehler, korrigiere den Vorschlag und rufe vorschlag_machen noch einmal auf.
- Fehlt dir eine wichtige Angabe, frag kurz nach. Antworte immer kurz, in einfachem Deutsch und in der du-Form.
"""


def _nullbar(typ: str, text: str) -> dict:
    return {"anyOf": [{"type": typ}, {"type": "null"}], "description": text}


def werkzeuge() -> list:
    """Nur zwei Werkzeuge: Vorschlag machen und eine Sequenz lesen. Keins davon schaltet etwas live."""
    wert = {"type": "object", "additionalProperties": False, "properties": {
        "gruppe": _nullbar("string", "Gruppe aus der Liste; null, wenn geraet gesetzt ist"),
        "geraet": _nullbar("string", "Geräte-id, nur für ein einzelnes, ausdrücklich genanntes Gerät"),
        "helligkeit": _nullbar("number", "0 bis 1"),
        "farbe": _nullbar("string", "Farbname aus der Liste oder #rrggbb"),
        "position": _nullbar("string", "benannte Position, nur für bewegliche Gruppen"),
        "gobo": _nullbar("string", "Gobo-Name, den die Gruppe hat, zum Beispiel Offen"),
        "gobo_drehung": _nullbar("number", "-1 bis 1, Vorzeichen ist die Richtung"),
        "strobo_hz": _nullbar("number", "Blitze pro Sekunde, nie über der Grenze"),
    }}
    wert["required"] = list(wert["properties"])
    effekt = {"type": "object", "additionalProperties": False, "properties": {
        "art": {"type": "string", "enum": list(EFFEKT_ARTEN)},
        "gruppe": {"type": "string", "description": "Gruppe, auf der der Effekt läuft"},
        "groesse": _nullbar("number", "0 bis 1, Größe der Bewegung"),
        "beats": _nullbar("number", "Beats pro Runde, zum Beispiel 4, 8 oder 16"),
        "verteilung": _nullbar("number", "0 bis 1, Versatz zwischen den Geräten"),
        "tempo": _nullbar("number", "null: im Tempo der Musik; sonst feste BPM (10 bis 300)"),
        "tiefe": _nullbar("number", "nur Dimmer-Effekte: 0 bis 1, wie weit es dunkler wird"),
        "farben": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
                   "description": "nur farbwechsel: Farbnamen oder #rrggbb"},
        "mitte": _nullbar("string", "benannte Position als Mittelpunkt der Bewegung"),
    }}
    effekt["required"] = list(effekt["properties"])
    cue = {"type": "object", "additionalProperties": False, "properties": {
        "name": {"type": "string", "description": "kurzer Name des Cues"},
        "zeit_s": {"type": "number", "description": "Überblendzeit in Sekunden"},
        "folgen_s": _nullbar("number", "null: wartet auf Go. Zahl: geht nach der Überblendung und so vielen "
                                       "Sekunden von selbst zum nächsten Cue"),
        "werte": {"type": "array", "items": wert},
        "effekte": {"type": "array", "items": effekt},
    }}
    cue["required"] = list(cue["properties"])
    vorschlag = {"type": "object", "additionalProperties": False, "properties": {
        "name": {"type": "string", "description": "kurzer Name der Sequenz, steht auf dem Fader"},
        "erklaerung": {"type": "string", "description": "ein bis zwei Sätze für den Menschen: was man sehen wird"},
        "fader": _nullbar("integer", f"Fader 1 bis {ANZAHL_EXECUTOREN}, nur wenn der Mensch einen genannt hat"),
        "ersetzt": {"type": "boolean", "description": "true, wenn eine vorhandene Sequenz geändert wird"},
        "cues": {"type": "array", "items": cue},
    }}
    vorschlag["required"] = list(vorschlag["properties"])
    return [
        {"name": "vorschlag_machen", "strict": True, "input_schema": vorschlag,
         "description": "Legt einen Vorschlag (Sequenz mit Cues) in die Vorschau. Nichts geht live und nichts wird "
                        "gespeichert, bis der Mensch Übernehmen drückt. Gibt Prüf-Fehler zurück, falls etwas nicht passt."},
        {"name": "sequenz_lesen", "strict": True,
         "input_schema": {"type": "object", "additionalProperties": False,
                          "properties": {"name": {"type": "string"}}, "required": ["name"]},
         "description": "Liest eine vorhandene Sequenz mit allen Cues, zum Beispiel bevor sie geändert wird."},
    ]


# --- Vorschlag umwandeln und prüfen ---------------------------------------------------

def aus_vorschlag(eingabe: dict) -> dict:
    """Macht aus dem Werkzeug-Aufruf eine Sequenz, wie sie das Pult speichert (ohne leere Felder)."""
    cues = []
    for c in eingabe.get("cues") or []:
        werte = [{k: v for k, v in w.items() if v is not None} for w in c.get("werte") or []]
        effekte = []
        for e in c.get("effekte") or []:
            effekt = {"art": e.get("art"), "ziel": {"gruppe": e.get("gruppe")},
                      "tempo": "musik" if e.get("tempo") is None else e["tempo"]}
            for feld in ("groesse", "beats", "verteilung", "tiefe", "farben", "mitte"):
                if e.get(feld) is not None:
                    effekt[feld] = e[feld]
            effekte.append(effekt)
        cues.append({"name": str(c.get("name") or "Cue").strip()[:60], "zeit_s": c.get("zeit_s", 2.0),
                     "folgen_s": c.get("folgen_s"), "werte": werte, "effekte": effekte})
    return {"name": str(eingabe.get("name") or "").strip()[:40], "cues": cues}


def pruefen(show, sequenz: dict, fader: Optional[int] = None) -> list:
    """Alle Prüfungen fürs Speichern, dazu was nur hier wichtig ist (Strobo, Gobos, Bewegung)."""
    fehler = []
    if not sequenz.get("cues"):
        fehler.append("Der Vorschlag hat keinen Cue.")
    if len(sequenz.get("cues", [])) > 40:
        fehler.append("Höchstens 40 Cues.")
    if fader is not None and not 1 <= int(fader) <= ANZAHL_EXECUTOREN:
        fehler.append(f"Fader {fader} gibt es nicht (1 bis {ANZAHL_EXECUTOREN}).")
    fehler += pruefe_sequenz(sequenz, show.patch, show.positionen)
    w = welt(show)
    grenze = w["strobo_max_hz"]
    for nummer, cue in enumerate(sequenz.get("cues", []), start=1):
        for feld, oben in (("zeit_s", 60.0), ("folgen_s", 600.0)):
            wert = cue.get(feld)
            if isinstance(wert, (int, float)) and wert > oben:
                fehler.append(f"Cue {nummer}: {feld} höchstens {oben:g} Sekunden.")
        for wert in cue.get("werte", []):
            gruppe = w["gruppen"].get(wert.get("gruppe"))
            if wert.get("strobo_hz", 0) > grenze:
                fehler.append(f"Cue {nummer}: strobo_hz höchstens {grenze:g} (Sicherheitsgrenze).")
            if gruppe is None:
                continue
            if "gobo" in wert and wert["gobo"] not in gruppe["gobos"] + ["Offen"]:
                fehler.append(f"Cue {nummer}: Gobo „{wert['gobo']}“ hat die Gruppe {wert['gruppe']} nicht. "
                              f"Möglich: {', '.join(gruppe['gobos']) or 'keine'}.")
            if ("position" in wert or "punkt" in wert) and not gruppe["beweglich"]:
                fehler.append(f"Cue {nummer}: Die Gruppe {wert['gruppe']} bewegt sich nicht, Position geht nicht.")
        for effekt in cue.get("effekte", []):
            gruppe = w["gruppen"].get(effekt.get("ziel", {}).get("gruppe"))
            if gruppe is not None and effekt.get("art") in BEWEGUNGS_ARTEN and not gruppe["beweglich"]:
                fehler.append(f"Cue {nummer}: {effekt['art']} geht nur mit beweglichen Geräten.")
            if effekt.get("art") == "farbwechsel" and not effekt.get("farben"):
                fehler.append(f"Cue {nummer}: farbwechsel braucht eine Liste farben.")
            if "mitte" in effekt and effekt["mitte"] not in show.positionen:
                fehler.append(f"Cue {nummer}: Position „{effekt['mitte']}“ gibt es nicht.")
    return list(dict.fromkeys(fehler))


# --- Ohne Internet: einfache Sätze selbst verstehen ---------------------------------------

def _grundform(text: str) -> str:
    text = text.lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(alt, neu)
    return text


GRUPPEN_WOERTER = [
    (("spot", "spots", "moving", "movingheads", "koepfe", "kopf", "koepfen", "heads"), ("Spots", "Frontlicht")),
    (("frontlicht", "front"), ("Frontlicht", "Spots")),
    (("par", "pars", "farb-pars", "farbpars", "wash", "boden", "farblicht"), ("Farb-PARs",)),
    (("strobo", "stroboskop", "strobe", "blitzer"), ("Strobo",)),
    (("effektlicht",), ("Effektlicht",)),
]
FARB_WOERTER = {
    "rot": "rot", "rote": "rot", "roten": "rot", "gruen": "gruen", "gruene": "gruen", "gruenen": "gruen",
    "blau": "blau", "blaue": "blau", "blauen": "blau", "weiss": "weiss", "weisse": "weiss", "weissen": "weiss",
    "warmweiss": "warmweiss", "warm": "warmweiss", "gold": "gold", "golden": "gold", "goldene": "gold",
    "orange": "orange", "gelb": "gelb", "gelbe": "gelb", "pink": "pink", "rosa": "pink", "magenta": "pink",
    "lila": "lila", "violett": "lila", "purpur": "lila", "cyan": "cyan", "tuerkis": "cyan", "hellblau": "hellblau",
}
EFFEKT_WOERTER = {
    "kreis": "kreis", "kreise": "kreis", "kreisen": "kreis", "kreisend": "kreis", "acht": "acht",
    "schwenk": "schwenk", "schwenken": "schwenk", "schwenkt": "schwenk", "nicken": "nicken", "nickt": "nicken",
    "publikum": "publikum", "welle": "dimmer_welle", "atmen": "dimmer_welle", "atmet": "dimmer_welle",
    "wabern": "dimmer_welle", "puls": "dimmer_puls", "pulsieren": "dimmer_puls", "pulsiert": "dimmer_puls",
    "pulsierend": "dimmer_puls", "beat": "dimmer_puls", "takt": "dimmer_puls", "farbwechsel": "farbwechsel",
    "wechsel": "farbwechsel", "wechseln": "farbwechsel", "bunt": "farbwechsel", "regenbogen": "farbwechsel",
}
EFFEKT_STAEMME = (("kreis", "kreis"), ("schwenk", "schwenk"), ("pulsier", "dimmer_puls"), ("farbwechsel", "farbwechsel"))


def _effekt_art(wort: str) -> Optional[str]:
    """kreisen, kreisend, Kreise ... -> kreis"""
    if wort in EFFEKT_WOERTER:
        return EFFEKT_WOERTER[wort]
    return next((art for stamm, art in EFFEKT_STAEMME if wort.startswith(stamm)), None)


BEISPIELE = ("„Spots blau, langsamer Kreis“, „PARs rot, pulsieren im Beat“, „alles warmweiß 60 %“, "
             "„Party mit Strobo auf Fader 3“, „alle Lichter wirbeln durcheinander“, „ruhige Ballade“")


def _abdeckende_gruppen(show, gruppen: list) -> list:
    """Für "alles": so wenige Gruppen wie nötig, ohne doppelte Geräte (Frontlicht steckt zum Beispiel in Spots)."""
    gedeckt, auswahl = set(), []
    for gruppe in sorted(gruppen, key=lambda g: -len(show.patch.in_gruppe(g))):
        ids = {g["id"] for g in show.patch.in_gruppe(gruppe)}
        if ids - gedeckt:
            auswahl.append(gruppe)
            gedeckt |= ids
    return auswahl


# Stile: ein Wort, ein ganzer Look (Farben, Bewegung der Köpfe, was die PARs machen)
STILE = {
    "pop": {"name": "Pop", "farben": ["pink", "cyan"], "bewegung": "acht", "beats": 8, "pars": "puls"},
    "rock": {"name": "Rock", "farben": ["rot", "weiss"], "bewegung": "schwenk", "beats": 8, "pars": "puls"},
    "party": {"name": "Party", "farben": ["pink", "cyan", "lila", "gelb"], "bewegung": "kreis", "beats": 4,
              "pars": "wechsel", "durcheinander": True},
    "ballade": {"name": "Ballade", "farben": ["warmweiss", "gold"], "bewegung": None, "beats": 16, "pars": "welle",
                "hell": 0.7},
    "weihnachten": {"name": "Weihnachten", "farben": ["gold", "rot"], "bewegung": None, "beats": 16, "pars": "welle",
                    "hell": 0.8},
    "jazz": {"name": "Jazz", "farben": ["lila", "gold"], "bewegung": None, "beats": 16, "pars": "welle", "hell": 0.6},
}
STIL_WOERTER = {"pop": "pop", "popmusik": "pop", "rock": "rock", "rockig": "rock", "metal": "rock", "punk": "rock",
                "party": "party", "disco": "party", "club": "party", "techno": "party", "edm": "party", "rave": "party",
                "ballade": "ballade", "romantisch": "ballade", "gefuehlvoll": "ballade", "kuschelig": "ballade",
                "weihnachten": "weihnachten", "weihnachtlich": "weihnachten", "festlich": "weihnachten",
                "jazz": "jazz", "jazzig": "jazz", "lounge": "jazz"}
# Bewegung ohne genaue Angabe: Köpfe kreisen, jeder etwas anders ("durcheinander")
WIRBEL_WOERTER = ("wirbeln", "wirbelt", "wirbel", "durcheinander", "chaos", "chaotisch", "kreuz", "quer",
                  "drehen", "dreht", "bewegen", "bewegt", "bewegung", "tanzen", "tanzt", "fliegen", "rumfliegen")
STROBO_WOERTER = ("strobo", "stroboskop", "strobe", "blitzen", "blitzt", "blitze", "blitz", "flackern")
ALLE_WOERTER = ("alle", "alles", "komplett", "ganze", "buehne", "lichter", "licht", "lampen", "scheinwerfer")
TEMPO_LANGSAM = ("langsam", "ruhig", "sanft", "gemuetlich", "gemaechlich", "entspannt")
TEMPO_SCHNELL = ("schnell", "wild", "hektisch", "zackig", "flott", "rasant")


def _wortschatz() -> list:
    woerter = set(FARB_WOERTER) | set(EFFEKT_WOERTER) | set(STIL_WOERTER) | set(WIRBEL_WOERTER) | set(STROBO_WOERTER)
    woerter |= set(ALLE_WOERTER) | set(TEMPO_LANGSAM) | set(TEMPO_SCHNELL)
    for synonyme, _ in GRUPPEN_WOERTER:
        woerter |= set(synonyme)
    return sorted(w for w in woerter if len(w) >= 4)


WORTSCHATZ = _wortschatz()


def _korrigieren(wort: str, gruppen_namen: list) -> str:
    """Tippfehler verzeihen: "srobo" -> "strobo", "wirbelnd" -> "wirbeln". Kurze Wörter bleiben, wie sie sind."""
    if len(wort) < 5 or wort in WORTSCHATZ or wort in gruppen_namen or wort.isdigit():
        return wort
    import difflib
    treffer = difflib.get_close_matches(wort, WORTSCHATZ + gruppen_namen, n=1, cutoff=0.8)
    return treffer[0] if treffer else wort


def einfach_verstehen(show, text: str) -> Optional[dict]:
    """Versteht kurze Sätze ohne Internet. Gibt einen Vorschlag zurück oder None.

    Kennt: Gruppen (Spots, PARs, Strobo, alle Lichter), Farben, Helligkeit (60 %, halb, voll), Positionen,
    Effekte (Kreis, Acht, Schwenk, Welle, Puls, Farbwechsel), Stile (Pop, Rock, Party, Ballade, Weihnachten,
    Jazz), "durcheinander/wirbeln", langsam/schnell, "in 3 Sekunden", "auf Fader 4". Tippfehler verzeiht er.
    """
    w = welt(show)
    vorhanden = list(w["gruppen"])
    gruppen_namen = [_grundform(g) for g in vorhanden]
    licht = _abdeckende_gruppen(show, [g for g in vorhanden if g not in ("Strobo", "Dunst")])
    satz = _grundform(text)
    fader = None
    treffer = re.search(r"\bfader\s*(\d{1,2})\b", satz)
    if treffer:
        fader = int(treffer.group(1))
        satz = satz.replace(treffer.group(0), " ")
    zeit = 2.0
    treffer = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:s\b|sek|sekunde)", satz)
    if treffer:
        zeit = float(treffer.group(1).replace(",", "."))
        satz = satz.replace(treffer.group(0), " ")
    werte, effekte, verstanden, notizen, stil_namen = {}, [], [], [], []
    gruppen_vorher: list = []

    def effekt_setzen(art: str, gruppe: str, beats: float, **mehr) -> None:
        nonlocal effekte
        effekt = {"art": art, "ziel": {"gruppe": gruppe}, "tempo": "musik", "beats": beats, "verteilung": 0.5, **mehr}
        bewegung = art in BEWEGUNGS_ARTEN
        effekte = [e for e in effekte if not (e["ziel"] == effekt["ziel"] and (e["art"] in BEWEGUNGS_ARTEN) == bewegung
                                              and e["art"] != "farbwechsel" and art != "farbwechsel")]
        effekte = [e for e in effekte if not (e["ziel"] == effekt["ziel"] and e["art"] == art)]
        effekte.append(effekt)

    for teil in re.split(r"[,;.]|\bund\b|\bdazu\b|\bmit\b|\bwo\b", satz):
        woerter = [_korrigieren(x, gruppen_namen) for x in re.findall(r"[a-z0-9#%\-]+", teil)]
        if not woerter:
            continue
        gruppen = []
        strobo = any(x in STROBO_WOERTER for x in woerter)
        for wort in woerter:
            direkt = [g for g in vorhanden if wort == _grundform(g)]
            if direkt:
                gruppen += [g for g in direkt if g not in gruppen]
                continue
            for synonyme, ziele in GRUPPEN_WOERTER:
                if wort in synonyme:
                    gruppen += [z for z in ziele if z in vorhanden and z not in gruppen][:1]
            if wort in ALLE_WOERTER:
                gruppen += [g for g in licht if g not in gruppen]
        if strobo and "Strobo" not in vorhanden:
            notizen.append("Einen Strobo gibt es im Patch nicht.")
        gruppen = gruppen or gruppen_vorher or licht
        if strobo and "Strobo" in vorhanden and "Strobo" not in gruppen:
            gruppen = gruppen + ["Strobo"]
        gruppen_vorher = [g for g in gruppen if g != "Strobo"] or gruppen
        farben = [FARB_WOERTER[x] for x in woerter if x in FARB_WOERTER]
        farben += [x for x in woerter if re.fullmatch(r"#[0-9a-f]{6}", x)]
        stile = [STILE[STIL_WOERTER[x]] for x in woerter if x in STIL_WOERTER]
        stil = stile[0] if stile else None
        if stil:
            stil_namen.append(stil["name"])
        hell = None
        prozent = re.search(r"(\d{1,3})\s*(?:%|prozent)", teil)
        if prozent:
            hell = min(100, int(prozent.group(1))) / 100
        elif any(x in woerter for x in ("voll", "hell", "ganz")):
            hell = 1.0
        elif "halb" in woerter:
            hell = 0.5
        elif any(x in woerter for x in ("gedimmt", "leicht", "schwach", "dezent", "leise")):
            hell = 0.3
        elif any(x in woerter for x in ("dunkel", "aus", "schwarz")):
            hell = 0.0
        if hell is None and stil:
            hell = stil.get("hell")
        langsam = any(x.startswith(TEMPO_LANGSAM) for x in woerter)
        schnell = any(x.startswith(TEMPO_SCHNELL) for x in woerter)
        positionen = [p for p in w["positionen"] if _grundform(p) in teil]
        effekt_arten = list(dict.fromkeys(art for art in map(_effekt_art, woerter) if art))
        wirbel = any(x in WIRBEL_WOERTER for x in woerter) or bool(stil and stil.get("durcheinander"))
        if not farben and stil:
            farben = list(stil["farben"])
        if not farben and wirbel and not effekt_arten:
            farben = ["pink", "cyan", "lila", "gelb"]
        for gruppe in gruppen:
            info = w["gruppen"][gruppe]
            wert = werte.setdefault(gruppe, {"gruppe": gruppe})
            if gruppe == "Strobo":
                if strobo:
                    wert["strobo_hz"] = min(2.0, w["strobo_max_hz"])
                    wert["helligkeit"] = 1.0
                continue
            wechsel = "farbwechsel" in effekt_arten or (not info["beweglich"] and (wirbel or (stil and stil["pars"] == "wechsel")))
            if farben and not wechsel:
                wert["farbe"] = farben[(licht.index(gruppe) if gruppe in licht else 0) % len(farben)] \
                    if len(farben) > 1 and len(gruppen) > 1 else farben[0]
            if hell is not None:
                wert["helligkeit"] = hell
            if positionen and info["beweglich"]:
                wert["position"] = positionen[0]
            beats_bewegung = 16 if langsam else 4 if schnell else 8
            arten = list(effekt_arten)
            if info["beweglich"] and not any(a in BEWEGUNGS_ARTEN for a in arten):
                if wirbel:
                    arten.append("kreis")
                elif stil and stil["bewegung"]:
                    arten.append(stil["bewegung"])
            if not info["beweglich"] and stil and not arten:
                arten.append({"puls": "dimmer_puls", "welle": "dimmer_welle", "wechsel": "farbwechsel"}[stil["pars"]])
            if wechsel and "farbwechsel" not in arten:
                arten.append("farbwechsel")
            for art in arten:
                if art in BEWEGUNGS_ARTEN and not info["beweglich"]:
                    continue
                if art in BEWEGUNGS_ARTEN:
                    mehr = {"groesse": 0.6 if wirbel else 0.5}
                    if positionen:
                        mehr["mitte"] = positionen[0]
                    effekt_setzen(art, gruppe, (stil["beats"] if stil and not (langsam or schnell) else beats_bewegung),
                                  **mehr)
                    if wirbel:
                        effekte[-1]["verteilung"] = 1.0       # jeder Kopf anders: durcheinander
                elif art == "farbwechsel":
                    effekt_setzen(art, gruppe, 2 if schnell or wirbel else 4,
                                  farben=farben if len(farben) >= 2 else ["rot", "blau", "lila", "gold"])
                elif art == "dimmer_welle":
                    effekt_setzen(art, gruppe, 16 if langsam or (stil and stil["beats"] >= 16) else 8, tiefe=0.6)
                else:
                    effekt_setzen(art, gruppe, 1 if art == "dimmer_puls" else 4)
        verstanden += farben + effekt_arten + positionen + (["Helligkeit"] if hell is not None else []) \
            + (["Strobo"] if strobo else []) + (["Wirbel"] if wirbel else []) + ([stil["name"]] if stil else [])
    if not verstanden:
        return None
    for wert in werte.values():
        if "helligkeit" not in wert:
            wert["helligkeit"] = 1.0 if wert["gruppe"] != "Strobo" else 0.0
    wirbelt = any(e["art"] in BEWEGUNGS_ARTEN and e.get("verteilung") == 1.0 for e in effekte)
    if stil_namen:
        name = " ".join(dict.fromkeys(stil_namen))
    elif wirbelt:
        name = "Wirbel"
    else:
        teile = [farbe.capitalize() for farbe in dict.fromkeys(v.get("farbe") for v in werte.values())
                 if farbe and not farbe.startswith("#")]
        teile += [EFFEKT_ARTEN[e["art"]] for e in effekte]
        name = " ".join(dict.fromkeys(teile))
    zusatz = " mit Strobo" if any("strobo_hz" in v for v in werte.values()) else ""
    name = (name[:30 - len(zusatz)].strip() or "Look") + zusatz
    cue = {"name": name, "zeit_s": zeit, "folgen_s": None, "werte": list(werte.values()), "effekte": effekte}
    beschreibung = []
    for v in werte.values():
        if "strobo_hz" in v:
            beschreibung.append(f"{v['gruppe']} blitzt ({v['strobo_hz']:g} pro Sekunde)")
        else:
            beschreibung.append(f"{v['gruppe']}: {v.get('farbe', 'bunt')} {round(v['helligkeit'] * 100)} %"
                                + (f", auf {v['position']}" if v.get("position") else ""))
    erklaerung = ", ".join(beschreibung)
    if effekte:
        erklaerung += ". Effekte: " + ", ".join(
            f"{'Wirbel (Kreis, jeder Kopf anders)' if e.get('verteilung') == 1.0 and e['art'] in BEWEGUNGS_ARTEN else EFFEKT_ARTEN[e['art']]}"
            f" ({e['ziel']['gruppe']})" for e in effekte)
    erklaerung += "." + ("".join(" " + n for n in dict.fromkeys(notizen)) if notizen else "")
    return {"sequenz": {"name": name, "cues": [cue]}, "erklaerung": erklaerung, "fader": fader, "ersetzt": False}


# --- Der Chat --------------------------------------------------------------------

class LichtChat:
    def __init__(self, show):
        self.show = show
        self.schluessel = Schluessel(show.pfade.lokal)
        # Das Modell lässt sich in lokal.json ("modell") ändern, zum Beispiel wenn die Schule ein anderes will.
        self.modell = str(daten.lese_json(show.pfade.lokal, {}).get("modell") or MODELL)
        self.verlauf = []          # was an Claude geht (wird nur angehängt, nie geändert)
        self.anzeige = []          # was die Oberfläche zeigt
        self.systemtext: Optional[str] = None
        self.entwurf: Optional[dict] = None
        self.denkt = False
        self.kosten_cent = 0.0
        self._sperre = threading.Lock()

    # --- Für die Oberfläche ---------------------------------------------------

    def status(self) -> dict:
        entwurf = None
        if self.entwurf:
            sequenz = self.entwurf["sequenz"]
            entwurf = {"name": sequenz["name"], "erklaerung": self.entwurf["erklaerung"],
                       "fader": self.entwurf["fader"], "ersetzt": self.entwurf["ersetzt"],
                       "cue": self.entwurf["cue"], "quelle": self.entwurf["quelle"],
                       "cues": [{"name": c["name"], "zeit_s": c.get("zeit_s"), "folgen_s": c.get("folgen_s")}
                                for c in sequenz["cues"]],
                       "vorhanden": sequenz["name"] in self.show.pult.sequenzen.namen()}
        return {"anzeige": self.anzeige[-60:], "entwurf": entwurf, "denkt": self.denkt,
                "ki": {"bereit": bool(self.schluessel.lesen()), "quelle": self.schluessel.quelle(),
                       "maskiert": self.schluessel.maskiert(), "modell": self.modell},
                "kosten_cent": round(self.kosten_cent, 1), "beispiele": BEISPIELE}

    def neu(self) -> None:
        with self._sperre:
            self.verlauf, self.anzeige, self.systemtext = [], [], None

    def vorschau_cue(self, index: int) -> None:
        if not self.entwurf:
            raise ValueError("Es gibt keinen Vorschlag.")
        self.entwurf["cue"] = max(0, min(int(index), len(self.entwurf["sequenz"]["cues"]) - 1))

    def verwerfen(self) -> None:
        self.entwurf = None

    def uebernehmen(self, fader: Optional[int] = None, name: Optional[str] = None) -> dict:
        """Erst hier wird gespeichert. Mit Fader: gleich darauf legen (wie Assign)."""
        if not self.entwurf:
            raise ValueError("Es gibt keinen Vorschlag zum Übernehmen.")
        sequenz = copy.deepcopy(self.entwurf["sequenz"])
        if name:
            sequenz["name"] = str(name).strip()[:40]
        pult = self.show.pult
        if sequenz["name"] in pult.sequenzen.namen() and not (self.entwurf["ersetzt"] and not name):
            basis, nummer = sequenz["name"], 2
            while f"{basis} {nummer}" in pult.sequenzen.namen():
                nummer += 1
            sequenz["name"] = f"{basis} {nummer}"
        alt = pult.sequenzen.lesen(sequenz["name"])
        if alt and alt.get("zeitcode"):
            # Ein Song behält seine Zeiten, auch wenn der Chat die Looks geändert hat
            sequenz["zeitcode"] = alt["zeitcode"]
            if alt.get("song"):
                sequenz["song"] = alt["song"]
        fehler = pruefen(self.show, sequenz, fader)
        if fehler:
            raise ValueError(" ".join(fehler))
        with self.show.sperre:
            pult.sequenz_speichern(sequenz)
            if fader:
                pult.zuweisen(int(fader), "sequenz", sequenz["name"], zusammen=True)   # ein Oops-Schritt
        self.entwurf = None
        text = f"Übernommen: „{sequenz['name']}“" + (f" liegt auf Fader {fader}." if fader else " liegt im Sequenzen-Pool.")
        self.anzeige.append({"rolle": "hinweis", "text": text})
        return {"name": sequenz["name"], "fader": fader}

    # --- Eine Nachricht -------------------------------------------------------

    def senden(self, text: str) -> dict:
        text = str(text or "").strip()
        if not text:
            raise ValueError("Schreib, was du sehen willst. Zum Beispiel: " + BEISPIELE)
        if len(text) > 2000:
            raise ValueError("Bitte kürzer (höchstens 2000 Zeichen).")
        if not self._sperre.acquire(blocking=False):
            raise ValueError("Der Chat denkt noch über die letzte Nachricht nach.")
        try:
            self.denkt = True
            self.anzeige.append({"rolle": "du", "text": text})
            if self.schluessel.lesen():
                self._mit_claude(text)
            else:
                self._einfach(text, "Ohne Claude-Schlüssel verstehe ich einfache Sätze: Gruppen, Farben, Effekte, "
                                    "Stile wie Pop, Rock, Party, Ballade. Für freie Sätze unten den Schlüssel eintragen.")
        finally:
            self.denkt = False
            self._sperre.release()
        return self.status()

    def _einfach(self, text: str, grund: str) -> None:
        vorschlag = einfach_verstehen(self.show, text)
        if vorschlag is None:
            self.anzeige.append({"rolle": "ki", "text": f"{grund} Das habe ich nicht verstanden. Beispiele: {BEISPIELE}"})
            return
        fehler = pruefen(self.show, vorschlag["sequenz"], vorschlag["fader"])
        if fehler:
            self.anzeige.append({"rolle": "ki", "text": f"{grund} Mein Vorschlag passt nicht: {' '.join(fehler)}"})
            return
        self._entwurf_setzen(vorschlag, "einfach")
        self.anzeige.append({"rolle": "ki", "text": f"{grund} Vorschlag: {vorschlag['erklaerung']} "
                                                    "Schau ihn dir in der Vorschau an und drück Übernehmen."})

    def _entwurf_setzen(self, vorschlag: dict, quelle: str) -> None:
        self.entwurf = {"sequenz": vorschlag["sequenz"], "erklaerung": vorschlag["erklaerung"],
                        "fader": vorschlag.get("fader"), "ersetzt": bool(vorschlag.get("ersetzt")),
                        "cue": 0, "quelle": quelle}

    def _client(self):
        import anthropic
        return anthropic.Anthropic(api_key=self.schluessel.lesen(), timeout=ZEITLIMIT_S, max_retries=2)

    def _mit_claude(self, text: str) -> None:
        import anthropic
        if len(self.verlauf) >= MAX_NACHRICHTEN:
            self.verlauf, self.systemtext = [], None
            self.anzeige.append({"rolle": "hinweis", "text": "Neues Gespräch begonnen (das alte wurde zu lang)."})
        if self.systemtext is None:
            # Für ein Gespräch fest: Dann bleibt der Anfang gleich und Claude kann ihn zwischenspeichern.
            self.systemtext = SYSTEMTEXT + "\n" + welt_text(self.show)
        self.verlauf.append({"role": "user", "content": stand_text(self.show) + "\n\n" + text})
        try:
            client = self._client()
            for _ in range(MAX_ANFRAGEN):
                antwort = client.beta.messages.create(
                    model=self.modell, max_tokens=16000, system=self.systemtext, tools=werkzeuge(),
                    messages=self.verlauf, cache_control={"type": "ephemeral"},
                    output_config={"effort": "medium"},
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default")
                self._kosten(antwort.usage)
                if antwort.stop_reason == "refusal":
                    self.verlauf.pop()           # die abgelehnte Nachricht nicht im Verlauf lassen
                    self.anzeige.append({"rolle": "ki", "text": "Da kann ich nicht helfen, ich mache nur Licht."})
                    return
                self.verlauf.append({"role": "assistant", "content": antwort.content})
                texte = [b.text for b in antwort.content if b.type == "text" and b.text.strip()]
                aufrufe = [b for b in antwort.content if b.type == "tool_use"]
                if texte:
                    self.anzeige.append({"rolle": "ki", "text": "\n".join(texte)})
                if not aufrufe:
                    if antwort.stop_reason == "max_tokens":
                        self.anzeige.append({"rolle": "hinweis", "text": "Die Antwort war zu lang und ist abgeschnitten."})
                    return
                ergebnisse, fertig = [], False
                for aufruf in aufrufe:
                    inhalt, fehler, fertig_hier = self._werkzeug(aufruf.name, aufruf.input)
                    ergebnis = {"type": "tool_result", "tool_use_id": aufruf.id, "content": inhalt}
                    if fehler:
                        ergebnis["is_error"] = True
                    ergebnisse.append(ergebnis)
                    fertig = fertig or fertig_hier
                self.verlauf.append({"role": "user", "content": ergebnisse})
                if fertig:
                    # Ein gültiger Vorschlag liegt in der Vorschau. Keine weitere Anfrage nötig (spart Kosten).
                    return
            self.anzeige.append({"rolle": "hinweis", "text": "Ich habe es mehrmals versucht, aber der Vorschlag passt "
                                                            "noch nicht. Beschreib es bitte etwas genauer."})
        except anthropic.AuthenticationError:
            self.verlauf.pop()
            self.anzeige.append({"rolle": "hinweis", "text": "Der Claude-Schlüssel stimmt nicht. Bitte unten neu eintragen."})
        except anthropic.PermissionDeniedError:
            self.verlauf.pop()
            self.anzeige.append({"rolle": "hinweis", "text": "Der Schlüssel darf das nicht. Rechte in der Claude Console prüfen."})
        except anthropic.RateLimitError:
            self.verlauf.pop()
            self.anzeige.append({"rolle": "hinweis", "text": "Gerade zu viele Anfragen oder das Ausgabenlimit ist erreicht. "
                                                            "Kurz warten und nochmal senden."})
        except anthropic.BadRequestError as fehler:
            logging.warning("Licht-Chat: Anfrage abgelehnt: %s", fehler.message)
            self.verlauf, self.systemtext = [], None      # Gespräch neu beginnen, damit der Fehler nicht hängen bleibt
            self.anzeige.append({"rolle": "hinweis", "text": f"Claude hat die Anfrage abgelehnt ({fehler.message}). "
                                                            "Das Gespräch beginnt neu."})
        except (anthropic.APIConnectionError, anthropic.APITimeoutError):
            self.verlauf.pop()
            self._einfach(text, "Kein Internet:")
        except anthropic.APIStatusError as fehler:
            self.verlauf.pop()
            self.anzeige.append({"rolle": "hinweis", "text": f"Claude ist gerade nicht erreichbar (Fehler {fehler.status_code}). "
                                                            "Gleich nochmal versuchen."})
        finally:
            # Endet das Gespräch mit einem offenen Werkzeug-Aufruf (Fehler mittendrin), ist es kaputt: neu beginnen.
            if self.verlauf and self.verlauf[-1]["role"] == "assistant" and any(
                    getattr(b, "type", None) == "tool_use" for b in self.verlauf[-1]["content"]):
                self.verlauf, self.systemtext = [], None

    def _werkzeug(self, name: str, eingabe: dict) -> tuple:
        """Führt einen Werkzeug-Aufruf aus. Gibt (Text für Claude, ist Fehler, Vorschlag fertig) zurück."""
        if name == "sequenz_lesen":
            sequenz = self.show.pult.sequenzen.lesen(str(eingabe.get("name", "")))
            if sequenz is None:
                return f"Die Sequenz „{eingabe.get('name')}“ gibt es nicht. Vorhanden: " + \
                       ", ".join(self.show.pult.sequenzen.namen()), True, False
            kurz = {"name": sequenz["name"], "cues": sequenz["cues"]}
            return json.dumps(kurz, ensure_ascii=False), False, False
        if name == "vorschlag_machen":
            sequenz = aus_vorschlag(eingabe)
            fader = eingabe.get("fader")
            fehler = pruefen(self.show, sequenz, fader)
            if fehler:
                return "Die Prüfung meldet: " + " ".join(fehler), True, False
            self._entwurf_setzen({"sequenz": sequenz, "erklaerung": str(eingabe.get("erklaerung", "")).strip(),
                                  "fader": fader, "ersetzt": bool(eingabe.get("ersetzt"))}, "claude")
            self.anzeige.append({"rolle": "ki", "text": (self.entwurf["erklaerung"] or "Vorschlag fertig.")
                                 + " Er läuft jetzt in der Vorschau, noch nicht live."})
            return "Der Vorschlag ist geprüft und läuft in der Vorschau. Der Mensch entscheidet über Übernehmen.", False, True
        return f"Unbekanntes Werkzeug {name}.", True, False

    def _kosten(self, usage) -> None:
        """Ungefähre Kosten in Cent, damit man das Ausgabenlimit im Blick behält."""
        try:
            dollar = (usage.input_tokens * PREISE["eingabe"] + usage.output_tokens * PREISE["ausgabe"]
                      + (usage.cache_read_input_tokens or 0) * PREISE["cache_lesen"]
                      + (usage.cache_creation_input_tokens or 0) * PREISE["cache_schreiben"]) / 1_000_000
            self.kosten_cent += dollar * 100
        except (AttributeError, TypeError):
            pass
