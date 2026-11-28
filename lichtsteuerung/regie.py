"""KI-Regie: Claude hört live mit (über die Messwerte, nie den Ton) und sagt alle paar Sekunden,
was gerade los ist und welcher Look passt. Die Engine setzt es im Takt um.

So ist das gedacht (CLAUDE.md, "Version 2: Live-Regisseur"):
    Claude entscheidet, WAS passt (Lage, Look, Farben). WANN es wechselt, bestimmt die Engine: auf der Eins,
    am Anfang einer Phrase, beim Drop sofort. Für jeden einzelnen Schlag wäre Claude viel zu langsam.

Sicherheit:
    - Claude bleibt in den Grenzen des Profils: Ein Look mit Bewegung bei "Bewegung aus" wird durch einen
      stehenden ersetzt, Farben nur aus der Palette, Strobo regelt weiter nur die Engine (mit Grenze).
    - Ruhiger machen darf Claude immer. Kräftiger nur, wenn die Musik wirklich laut ist.
    - Override-Tasten gehen immer vor; die Prüfung jedes DMX-Werts bleibt.
    - Kommt keine Antwort (kein Internet, Fehler, Limit), läuft die Automatik allein weiter. Eine Entscheidung
      gilt höchstens 20 Sekunden.
    - Kosten: das schnelle Modell (Haiku), etwa 10 bis 20 Cent pro Stunde, mit Limit pro Sitzung.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import deque
from typing import Optional

from .engine import LAGE_NAMEN, LOOKS
from .ki import antwort_text

TAKT_S = 8.0               # so oft fragt die Regie, wenn nichts Besonderes passiert
MIN_ABSTAND_S = 2.5        # frühestens dann die nächste Frage (auch bei Ereignissen)
ZEITLIMIT_S = 8.0          # live hilft eine spätere Antwort nicht mehr
GUELTIG_S = 20.0           # so lange gilt eine Entscheidung, dann macht die Engine allein weiter
STILLE_PAUSE_S = 30.0      # so lange nur Stille: Die Regie fragt nicht (spart Kosten)
WECHSEL_HALTEN_S = 1.0     # so lange muss die eigene Erkennung etwas Neues hören, bis die Regie gleich fragt
EIMER_S = 1.0              # Messwerte werden pro Sekunde zusammengefasst
EIMER_ANZAHL = 60

LAGEN = list(LAGE_NAMEN)
WECHSEL = ["jetzt", "naechste_phrase", "bleiben"]
LOOK_TEXT = {
    "Ruhe": "steht, atmet langsam, eine Farbe",
    "Ruhe schwenkt": "langsamer Schwenk, atmet",
    "Ruhe kreist": "sehr langsamer Kreis, atmet, zwei Farben",
    "Stehen": "steht, Puls im Beat, Gobo",
    "Sanfter Schwenk": "sanfter Schwenk, zwei Farben",
    "Farbwechsel": "langsamer Kreis, Farben tauschen pro Phrase",
    "Langsame Acht": "langsame Acht, zwei Farben",
    "Wippen": "Köpfe wippen langsam gegeneinander",
    "Schwenk": "Schwenk mit Ruck auf dem Beat",
    "Kreuz": "Strahlen kreuzen sich",
    "Nicken": "Köpfe nicken im Beat",
    "Stehen mit Akzent": "steht, Eins im Takt doppelt hell",
    "Acht": "Acht im Takt, Gobos drehen",
    "Gegenlauf": "gespiegelte Kreise in Gegenrichtung, Akzent auf der Eins",
    "Kreis": "Kreise, Akzent auf der Eins",
    "Fächer": "Fächer auf und zu, schnell",
    "Höhepunkt": "schnelles Kreuzen, alles voll",
    "Ballyhoo": "große wilde Bewegung, drei Farben wandern",
    "Farb-Lauf": "Acht, drei Farben wandern über die Geräte",
}

SYSTEM = """Du bist die Live-Lichtregie der Technik-AG bei einer Schulveranstaltung. Alle paar Sekunden bekommst \
du Messwerte vom Mischpult (nicht den Ton) und entscheidest, was gerade los ist und welcher Look jetzt passt. \
Das Programm setzt deine Entscheidung im Takt um. Ohne deine Antwort fährt die Automatik allein weiter.

Entscheide für JETZT: Die obersten Zeilen (die letzten Sekunden) zählen am meisten, ältere Zeilen sind nur der \
Zusammenhang. Beschreibe in hoere, was gerade jetzt zu hören ist.

So erkennst du die Lage an den Zahlen (Pegel in dBFS: -60 Stille, -35 leise, -20 laut, -10 sehr laut):
- stille: Pegel unter etwa -45, nichts los.
- ansage (Rede): Die eigene Erkennung meldet Rede, Rede-Anteil hoch, kein Takt-Tempo, wenig Bass. Silben zählen \
dabei oft als Treffer. Meldet die eigene Erkennung seit 2 Sekunden oder länger Rede, ist es eine Ansage, kein Solo.
- applaus: Applaus-Anteil hoch, rauschig, viele Treffer ohne Takt, keine Töne. Oft direkt nach einem Song.
- schlagzeug_solo: sehr viele Treffer (über 5 pro Sekunde), viel Bass und Höhen, kaum Mitten (keine Akkorde), laut.
- solo (Gitarre, Keyboard): laut, Mitten und Höhen stark, Takt läuft weiter.
- refrain: laut, viel Bass, Treffer im Takt, Stärke hoch im Vergleich zum Song.
- hoehepunkt: die stärkste Stelle des Songs, oft der letzte Refrain.
- strophe: mittlere Stärke, gleichmäßig. ruhige_musik: leise, langsam, wenige Treffer (Ballade).
- break: mitten im Song für 1 bis 4 Sekunden deutlich leiser; danach geht es meist kräftig weiter.
- aufbau: Stärke und Treffer steigen über mehrere Sekunden. drop: nach Aufbau plötzlich sehr kräftig.
- Ein „DROP der Automatik“ direkt nach einer Pause ist oft nur ein Songanfang. Ist die Musik danach leise \
(Pegel unter etwa -30 oder Stärke unter 0.4), ist es kein Drop: dann ruhige_musik oder strophe.
- unklar: wenn du es wirklich nicht sagen kannst.

So soll das Licht sein (Wünsche des Teams):
- Ruhige Stellen ruhig. Ein Look bleibt stehen, solange er passt: Wähle dann wechsel = bleiben. Kein Dauerwechsel.
- Laute Musik und vor allem Soli müssen richtig knallen: Refrain, Solo und Höhepunkt mit einem Look der Stufe 3 \
(Kreis, Fächer, Höhepunkt), eine laute Strophe mit Stufe 2. Ein Schlagzeug-Solo ist NIE ruhig.
- Ansage, Applaus, Stille: lage entsprechend, das Programm geht dann auf das ruhige Grundlicht.
- wechsel: jetzt nur bei einem klaren Umbruch (Solo beginnt, Refrain setzt ein, Song endet), sonst \
naechste_phrase, und bleiben, wenn der jetzige Look noch passt.
- Farben: zwei aus der Palette, die zusammenpassen. Innerhalb eines Songs gleich lassen; neue Farben nur bei \
einem neuen Song.

Looks (Stufe 0 ruhig bis 3 Höhepunkt):
{looks}
"""


def _db(pegel: float) -> float:
    return 20 * math.log10(max(pegel, 1e-6))


class Lagebuch:
    """Fasst die Messwerte (40 pro Sekunde) pro Sekunde zusammen. Billig, läuft in der Show-Schleife."""

    def __init__(self):
        self.eimer = deque(maxlen=EIMER_ANZAHL)
        self._jetzt: Optional[dict] = None
        self.musik_seit: Optional[float] = None
        self.ruhe_seit: Optional[float] = None
        self.lokal = "leise"                   # was die eigene Erkennung gerade hört
        self.lokal_seit = 0.0

    def messen(self, m, jetzt: float) -> None:
        if self._jetzt is None or jetzt - self._jetzt["start"] >= EIMER_S:
            if self._jetzt is not None and self._jetzt["n"]:
                self.eimer.append(self._fertig(self._jetzt))
            self._jetzt = {"start": jetzt, "n": 0, "pegel": 0.0, "energie": 0.0, "staerke": 0.0, "bass": 0.0,
                           "mitte": 0.0, "hoehe": 0.0, "beats": 0, "treffer": 0, "schlaege": 0, "rede": 0,
                           "applaus": 0, "leise": 0, "spannung": 0.0, "drop": False, "tempo": 0.0}
        e = self._jetzt
        if m is None:
            return
        e["n"] += 1
        e["pegel"] += m.pegel ** 2
        e["energie"] += m.energie
        e["staerke"] += m.intensitaet if m.intensitaet > 0 else m.energie
        e["bass"] += m.bass
        e["mitte"] += m.mitte
        e["hoehe"] += m.hoehe
        e["beats"] += int(m.beat)
        e["treffer"] += int(m.treffer)
        e["schlaege"] += int(m.schlag)
        e["rede"] += int(m.rede)
        e["applaus"] += int(m.applaus)
        e["leise"] += int(m.leise)
        e["spannung"] = max(e["spannung"], m.spannung)
        e["drop"] = e["drop"] or m.drop
        if m.beat and 40 <= m.tempo_bpm <= 240:
            e["tempo"] = m.tempo_bpm         # nur mit Schlägen: Bei einer Rede bleibt sonst das Tempo des letzten Songs stehen
        lokal = "Rede" if m.rede else "Applaus" if m.applaus else "leise" if m.leise else "Musik"
        if lokal != self.lokal:
            self.lokal, self.lokal_seit = lokal, jetzt
        musik = not (m.leise or m.rede or m.applaus)
        if musik:
            self.musik_seit = jetzt if self.musik_seit is None else self.musik_seit
            self.ruhe_seit = None
        else:
            self.ruhe_seit = jetzt if self.ruhe_seit is None else self.ruhe_seit
            if jetzt - self.ruhe_seit >= 3.0:
                self.musik_seit = None

    @staticmethod
    def _fertig(e: dict) -> dict:
        n = max(e["n"], 1)
        return {"start": e["start"], "pegel_db": round(_db(math.sqrt(e["pegel"] / n)), 1),
                "energie": round(e["energie"] / n, 2), "staerke": round(e["staerke"] / n, 2),
                "bass": round(e["bass"] / n, 2), "mitte": round(e["mitte"] / n, 2), "hoehe": round(e["hoehe"] / n, 2),
                "beats": e["beats"], "treffer": e["treffer"], "schlaege": e["schlaege"],
                "rede": round(e["rede"] / n, 2), "applaus": round(e["applaus"] / n, 2), "leise": round(e["leise"] / n, 2),
                "spannung": round(e["spannung"], 2), "drop": e["drop"], "tempo": round(e["tempo"])}

    def letzte(self, sekunden: int) -> list:
        """Die letzten Sekunden; die laufende Sekunde zählt mit, sobald sie eine Viertelsekunde Werte hat."""
        alle = list(self.eimer)
        if self._jetzt is not None and self._jetzt["n"] >= 10:
            alle.append(self._fertig(self._jetzt))
        return alle[-sekunden:]

    def nur_stille(self, sekunden: float) -> bool:
        letzte = self.letzte(int(sekunden))
        return len(letzte) >= int(sekunden) and all(e["pegel_db"] < -50 for e in letzte)


def _zeile(gruppe: list, jetzt: float) -> str:
    mittel = lambda feld: sum(e[feld] for e in gruppe) / len(gruppe)
    zeichen = []
    if any(e["drop"] for e in gruppe):
        zeichen.append("DROP der Automatik")
    if any(e["schlaege"] for e in gruppe):
        zeichen.append("großer Schlag")
    if max(e["spannung"] for e in gruppe) >= 0.3:
        zeichen.append(f"Aufbau {max(e['spannung'] for e in gruppe):.1f}")
    starts = [e["start"] for e in gruppe]
    von, bis = jetzt - max(starts) - EIMER_S, jetzt - min(starts)     # wie lange her: Ende des neuesten, Anfang des ältesten
    tempo = max(e["tempo"] for e in gruppe)
    return (f"vor {max(0.0, von):3.0f}-{bis:2.0f} s: {mittel('pegel_db'):6.1f} | {mittel('staerke'):.2f} | "
            f"{mittel('bass'):.2f}/{mittel('mitte'):.2f}/{mittel('hoehe'):.2f} | "
            f"{sum(e['treffer'] for e in gruppe) / len(gruppe):4.1f} | {sum(e['beats'] for e in gruppe)} | "
            f"{round(tempo) if tempo else '-'} | {mittel('rede'):.0%}/{mittel('applaus'):.0%}/{mittel('leise'):.0%}"
            + (" | " + ", ".join(zeichen) if zeichen else ""))


def lage_text(buch: Lagebuch, jetzt: float) -> str:
    """Neueste zuerst: die letzten 6 Sekunden einzeln, dann bis 12 Sekunden in 2-Sekunden-Schritten, dazu eine Minute
    im Überblick und was die eigene Erkennung gerade hört."""
    eimer = buch.letzte(12)[::-1]
    zeilen = [f"Eigene Erkennung (hört Rede und Applaus meist zuverlässig): {buch.lokal} seit "
              f"{max(0.0, jetzt - buch.lokal_seit):.0f} s.",
              "Messwerte, NEUESTE ZUERST: Pegel dBFS | Stärke 0-1 (im Vergleich zum Song) | Bass/Mitten/Höhen 0-1 | "
              "Treffer pro s | Beats | Takt-Tempo (- = kein Takt) | Rede-/Applaus-/Leise-Anteil | Zeichen"]
    zeilen += [_zeile([e], jetzt) for e in eimer[:6]]
    zeilen += [_zeile(eimer[i:i + 2], jetzt) for i in range(6, len(eimer), 2)]
    minute = buch.letzte(60)
    if minute:
        zeilen.append(
            f"Letzte {len(minute)} s: Pegel max {max(e['pegel_db'] for e in minute):.0f} dBFS, Stärke Mittel "
            f"{sum(e['staerke'] for e in minute) / len(minute):.2f} / max {max(e['staerke'] for e in minute):.2f}, "
            f"Treffer Mittel {sum(e['treffer'] for e in minute) / len(minute):.1f}/s, Rede "
            f"{sum(e['rede'] for e in minute) / len(minute):.0%}, Applaus {sum(e['applaus'] for e in minute) / len(minute):.0%}.")
    if buch.musik_seit is not None:
        zeilen.append(f"Musik läuft seit {jetzt - buch.musik_seit:.0f} s ohne Pause.")
    return "\n".join(zeilen)


def schema(palette: list) -> dict:
    """Was Claude antworten darf. Farben nur aus der Palette des Profils (deshalb pro Profil gebaut)."""
    farben = list(dict.fromkeys(str(f) for f in palette)) or ["warmweiss"]
    return {"type": "object", "additionalProperties": False,
            "required": ["hoere", "lage", "look", "farbe_a", "farbe_b", "wechsel"],
            "properties": {
                "hoere": {"type": "string", "description": "ein kurzer Satz: was du aus den Zahlen hörst"},
                "lage": {"type": "string", "enum": LAGEN},
                "look": {"type": "string", "enum": [look.name for look in LOOKS]},
                "farbe_a": {"type": "string", "enum": farben},
                "farbe_b": {"type": "string", "enum": farben},
                "wechsel": {"type": "string", "enum": WECHSEL},
            }}


class KiRegie:
    def __init__(self, show):
        self.show = show
        self.buch = Lagebuch()
        self.an = False
        self.letzte: Optional[dict] = None       # letzte Entscheidung mit Zeit und Antwortdauer
        self.verlauf = deque(maxlen=6)
        self.meldung = "aus"
        self.fragen_zahl = 0
        self.letzte_frage: Optional[float] = None
        self._lage_lokal: Optional[str] = None   # was die eigene Erkennung zuletzt meinte (für Ereignisse)
        self._lage_neu: Optional[str] = None
        self._lage_neu_seit = 0.0
        self._wecker = threading.Event()
        self._stopp = threading.Event()
        self._faden: Optional[threading.Thread] = None

    # --- In der Show-Schleife (40-mal pro Sekunde): nur sammeln ---------------------

    def messen(self, m, jetzt: float) -> None:
        self.buch.messen(m, jetzt)
        if m is None:
            return
        lokal = "rede" if m.rede else "applaus" if m.applaus else "leise" if m.leise else "musik"
        if m.drop:
            self._wecker.set()               # ein Drop: gleich fragen
        if lokal != self._lage_neu:
            self._lage_neu, self._lage_neu_seit = lokal, jetzt
        elif (lokal != self._lage_lokal and jetzt - self._lage_neu_seit >= WECHSEL_HALTEN_S):
            # Die eigene Erkennung hört seit einer Sekunde etwas anderes: gleich fragen, nicht erst nach 8 Sekunden
            if self._lage_lokal is not None and lokal != "leise":
                self._wecker.set()
            self._lage_lokal = lokal

    # --- An und aus --------------------------------------------------------------

    def einschalten(self, an: bool) -> None:
        self.an = bool(an)
        if not self.an:
            self.show.engine.regie = None
            self.meldung = "aus"
        else:
            self.meldung = "wartet auf Musik"
            self._wecker.set()

    def starten(self) -> None:
        if self._faden is not None and self._faden.is_alive():
            return
        self._stopp.clear()
        self._faden = threading.Thread(target=self._schleife, name="KI-Regie", daemon=True)
        self._faden.start()

    def stoppen(self) -> None:
        self._stopp.set()
        self._wecker.set()

    def _schleife(self) -> None:
        while not self._stopp.is_set():
            self._wecker.wait(TAKT_S)
            self._wecker.clear()
            if self._stopp.is_set():
                return
            try:
                self.takt(time.monotonic())
            except Exception:
                logging.exception("KI-Regie")
                self.meldung = "Fehler, die Automatik macht allein weiter"

    # --- Fragen ----------------------------------------------------------------------

    def bereit(self, jetzt: float) -> Optional[str]:
        """None, wenn die Regie jetzt fragen darf, sonst der Grund."""
        show = self.show
        if not self.an:
            return "aus"
        if not show.ki.bereit():
            return "kein Claude-Schlüssel"
        if show.ki.kosten.get("regie", 0.0) >= show.ki.regie_limit_cent():
            return f"Limit von {show.ki.regie_limit_cent():.0f} Cent für diese Sitzung erreicht"
        if not show.automatik_an:
            return "Automatik ist aus"
        if show.overrides.blackout or show.overrides.warmweiss or show.overrides.pause:
            return "Override-Taste gedrückt"
        if show.song.folger is not None:
            return "Song-Show läuft (die ist schon fertig entworfen)"
        if show.profil.get("beat_reaktion", 0) <= 0:
            return "Profil ohne Automatik"
        if len(self.buch.eimer) < 4:
            return "hört noch zu"
        if self.buch.nur_stille(STILLE_PAUSE_S):
            return "nur Stille"
        if self.letzte_frage is not None and jetzt - self.letzte_frage < MIN_ABSTAND_S:
            return "eben erst gefragt"
        return None

    def nachricht(self, jetzt: float) -> str:
        show = self.show
        engine = show.engine
        profil = show.profil
        farben = "/".join(engine.farben_paar) if engine.farben_paar else "noch keine"
        vorher = "; ".join(f"vor {jetzt - v['zeit']:.0f} s: {v['lage']}, {v['look']}, {v['wechsel']}"
                           for v in list(self.verlauf)[-3:]) or "keine"
        return (lage_text(self.buch, jetzt)
                + f"\nJetzt im Licht: Look „{engine.look.name}“ (Stufe {engine.look.stufe}), Farben {farben}, "
                  f"Text der Automatik: {engine.zustand_text}."
                + f"\nDeine letzten Entscheidungen: {vorher}."
                + f"\nProfil „{profil['name']}“: Palette {', '.join(profil.get('palette') or [])}, Bewegung "
                  f"{profil.get('bewegung')}, Beat-Reaktion {profil.get('beat_reaktion')}."
                + (f" Hinweise: {profil['hinweise_ki']}" if profil.get("hinweise_ki") else ""))

    def _client(self):
        return self.show.ki.client(ZEITLIMIT_S, wiederholen=0)

    def _denken(self, modell: str) -> dict:
        """Live zählt jede Sekunde. Sonnet 5.5: Nachdenken aus (between_tools), Opus 5.5 denkt immer (adaptive).
        Haiku: kurz nachdenken (adaptive, Aufwand niedrig), es sei denn, lokal.json sagt "regie_denken": false."""
        if "sonnet" in modell:
            return {"type": "between_tools"}
        if "opus" in modell or self.show.ki.einstellung("regie_denken", True):
            return {"type": "adaptive"}
        return {"type": "disabled"}

    def takt(self, jetzt: float) -> Optional[dict]:
        grund = self.bereit(jetzt)
        if grund is not None:
            if grund not in ("eben erst gefragt",):
                self.meldung = grund
            return None
        return self.fragen(jetzt)

    def fragen(self, jetzt: float) -> Optional[dict]:
        import anthropic
        show = self.show
        self.letzte_frage = jetzt
        modell = show.ki.modell_schnell()
        palette = show.profil.get("palette") or ["warmweiss"]
        looks = "\n".join(f"- {look.name} (Stufe {look.stufe}): {LOOK_TEXT.get(look.name, '')}" for look in LOOKS)
        start = time.monotonic()
        try:
            antwort = self._client().beta.messages.create(
                model=modell, max_tokens=2000, system=SYSTEM.format(looks=looks),
                messages=[{"role": "user", "content": self.nachricht(jetzt)}],
                thinking=self._denken(modell), cache_control={"type": "ephemeral"},     # der feste Teil kommt aus dem Cache
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema(palette)}})
        except (anthropic.APIConnectionError, anthropic.APITimeoutError):
            self.meldung = "kein Internet, die Automatik macht allein weiter"
            return None
        except anthropic.AuthenticationError:
            self.meldung = "Claude-Schlüssel stimmt nicht"
            return None
        except anthropic.APIStatusError as fehler:
            logging.warning("KI-Regie: %s", getattr(fehler, "message", fehler))
            self.meldung = f"Claude antwortet nicht (Fehler {fehler.status_code}), die Automatik macht allein weiter"
            return None
        dauer = time.monotonic() - start
        show.ki.buchen("regie", antwort.usage, modell)
        self.fragen_zahl += 1
        try:
            entscheidung = json.loads(antwort_text(antwort))
        except ValueError:
            self.meldung = "Antwort unlesbar, die Automatik macht weiter"
            return None
        entscheidung = self.pruefen(entscheidung, palette)
        if entscheidung is None:
            self.meldung = "Antwort passte nicht, die Automatik macht weiter"
            return None
        jetzt_danach = time.monotonic() if jetzt is None else jetzt + dauer
        entscheidung.update(zeit=jetzt_danach, dauer_s=round(dauer, 2))
        with show.sperre:
            show.engine.regie_setzen(entscheidung, jetzt_danach)
        self.letzte = entscheidung
        self.verlauf.append(entscheidung)
        self.meldung = "hört mit"
        return entscheidung

    @staticmethod
    def pruefen(roh: dict, palette: list) -> Optional[dict]:
        """Nur bekannte Werte; Farben aus der Palette. Sonst gilt die Antwort nicht."""
        namen = {look.name for look in LOOKS}
        if not isinstance(roh, dict) or roh.get("lage") not in LAGEN or roh.get("look") not in namen:
            return None
        farben = [f for f in (roh.get("farbe_a"), roh.get("farbe_b")) if f in palette]
        return {"hoere": str(roh.get("hoere") or "")[:200], "lage": roh["lage"], "look": roh["look"],
                "farben": tuple(farben) if len(farben) == 2 and farben[0] != farben[1] else None,
                "wechsel": roh.get("wechsel") if roh.get("wechsel") in WECHSEL else "naechste_phrase"}

    def status(self, jetzt: Optional[float] = None) -> dict:
        jetzt = time.monotonic() if jetzt is None else jetzt
        letzte = None
        if self.letzte:
            letzte = {k: self.letzte[k] for k in ("hoere", "lage", "look", "wechsel", "dauer_s")}
            letzte["farben"] = list(self.letzte["farben"]) if self.letzte.get("farben") else None
            letzte["vor_s"] = round(jetzt - self.letzte["zeit"], 1)
            letzte["gilt"] = jetzt - self.letzte["zeit"] <= GUELTIG_S
        return {"an": self.an, "meldung": self.meldung, "letzte": letzte, "fragen": self.fragen_zahl,
                "kosten_cent": round(self.show.ki.kosten.get("regie", 0.0), 2),
                "limit_cent": self.show.ki.regie_limit_cent(), "modell": self.show.ki.modell_schnell(),
                "bereit": self.show.ki.bereit()}
