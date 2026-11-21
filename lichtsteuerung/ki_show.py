"""KI-Lichtdesign: Claude entwirft aus einer Probe-Aufnahme die Lichtshow für einen Song.

So geht es:
  1. Das Programm misst die Aufnahme (audio/songanalyse.py): Tempo, Takte, Songteile, große Schläge.
     Dazu kommt pro Takt eine Zeile mit Zahlen: Lautstärke, Bass/Mitten/Höhen, wie viel los ist,
     welcher frühere Takt genauso klingt (Wiederholungen zeigen Strophe und Refrain), Markierungen.
  2. Claude bekommt diese Tabelle, den Songtitel (falls bekannt), die Geräte, das Profil und die Wünsche.
     Er erkennt die Songteile (viele Songs kennt er) und entwirft für jeden Teil einen Look.
  3. Das Programm baut daraus die Sequenz. Die Zeiten kommen immer aus den gemessenen Takten, nie von Claude.
     Jeder Wert läuft durch dieselbe Prüfung wie alles andere.
  4. Der Vorschlag läuft nur in der 3D-Vorschau, bis der Mensch Übernehmen drückt (Grundregel).

Ohne Schlüssel oder ohne Internet bleibt "Show neu bauen" (probe.show_bauen) wie bisher.
Claude bekommt nie den Ton selbst, nur die Zahlen.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np

from .audio import songanalyse
from .audio.quellen import lade_datei
from .farben import farbpaar, ist_farbe
from .ki import antwort_text
from .licht_chat import pruefen, welt_text
from .probe import (AKZENT_S, ANALYSE_VERSION, LOOKS, PHRASE_TAKTE, PHRASE_ZEIT_S, SCHLAG_S, TEIL_NAMEN, ZEITEN_S,
                    _phrasen, _pulse_alle, akzent_cue, akzente_im_teil, aufbau_cue, look_cue, schlag_cue,
                    schlaege_im_teil)

ZEITLIMIT_S = 240.0
LICHT_VERSION_KI = 3                  # 3: von Claude entworfen
KLASSEN = ["ruhig", "mittel", "stark", "hoehepunkt"]
BEWEGUNGEN = ["keine", "schwenk", "kreis", "acht", "nicken", "publikum"]
PULSE = ["atmen", "puls", "kraeftig"]
MIN_TAKTE = 8

SYSTEM = """Du bist der Lichtdesigner der Technik-AG einer Schule. Du entwirfst die Lichtshow für einen Song, \
den die Schulband spielt. Du bekommst die Probe-Aufnahme als Messwerte, Takt für Takt (nicht den Ton selbst).

Deine Aufgabe:
1. Erkenne die Songteile. Nutze dafür die Tabelle: Wiederholungen („≈T17“ heißt: klingt wie Takt 17 und die \
Takte danach), Lautstärke, Bass, wie viel los ist (Einsätze) und die Markierungen. Kennst du den Song, nutze dein \
Wissen über seinen Aufbau, aber die Band kann anders spielen: Die Messwerte gewinnen. Die Teile der Analyse sind \
ein Startpunkt; sie können falsch sein (oft zu grob). Sind sie offensichtlich von Hand gesetzt, weiche nur mit \
gutem Grund ab.
2. Entwirf für jeden Teil einen Look. So soll das Licht sein:
   - Ruhige Stellen ruhig: eine Farbe, wenig oder keine Bewegung, Licht atmet langsam. Nicht ständig wechseln.
   - Laute, rhythmische Stellen kräftig: Refrain, Solo (auch Schlagzeug-Solo!), Höhepunkt und Drop müssen \
richtig knallen: kräftiger Puls, Bewegung, beide Farben, kurze weiße Akzente auf großen Schlägen.
   - Steigern: Der letzte Refrain oder das Finale ist der Höhepunkt. Gleiche Teile sehen gleich aus, der \
Höhepunkt bekommt mehr.
   - Zwei Song-Farben (A und B), die zusammenpassen, aus der Palette des Profils. Weiß nur für Akzente.
   - Akzente (akzent_takte): Takte, auf deren Eins ein großer Schlag kommt (Zeichen S in der Tabelle, auch \
Taste D vom Menschen). Lieber wenige und gezielt (Anfang eines Refrains, Ende eines Solos) als viele.
   - Strobo nur in Teilen mit klasse stark oder hoehepunkt, nur wenn das Profil es erlaubt, sparsam.
3. Halte dich an die Wünsche des Menschen, wenn er welche nennt. Sie gehen vor.

Format: teile in der Reihenfolge des Songs. Jeder Teil beginnt mit von_takt (Takt-Nummer aus der Tabelle) und \
geht bis zum nächsten Teil; der erste Teil beginnt bei Takt 1. Teile kürzer als 2 Takte nur für einen Drop. \
klasse: ruhig, mittel, stark, hoehepunkt. bewegung der Spots: keine oder ein Muster. farben: A (alles in Farbe A), \
B (alles in B), BA (Spots in B über PARs in A). puls: atmen (langsame Welle), puls (im Takt), kraeftig (jeder Schlag). \
idee: ein kurzer Satz, warum dieser Look. erklaerung: zwei Sätze für den Menschen über die ganze Show. \
Schreib Namen und Sätze auf Deutsch, in einfacher Sprache.
"""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["song_erkannt", "farbe_a", "farbe_b", "teile", "erklaerung"],
    "properties": {
        "song_erkannt": {"type": "string", "description": "welcher Song es ist, falls du ihn kennst, sonst unbekannt"},
        "farbe_a": {"type": "string", "description": "Song-Farbe A (Farbname aus der Palette)"},
        "farbe_b": {"type": "string", "description": "Song-Farbe B (Farbname aus der Palette)"},
        "teile": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "von_takt", "klasse", "bewegung", "farben", "puls", "strobo", "akzent_takte", "idee"],
            "properties": {
                "name": {"type": "string", "enum": TEIL_NAMEN},
                "von_takt": {"type": "integer"},
                "klasse": {"type": "string", "enum": KLASSEN},
                "bewegung": {"type": "string", "enum": BEWEGUNGEN},
                "farben": {"type": "string", "enum": ["A", "B", "BA"]},
                "puls": {"type": "string", "enum": PULSE},
                "strobo": {"type": "boolean"},
                "akzent_takte": {"type": "array", "items": {"type": "integer"}},
                "idee": {"type": "string"},
            }}},
        "erklaerung": {"type": "string"},
    },
}


# --- Die Takt-Tabelle ------------------------------------------------------------------

def _skala(werte: np.ndarray) -> np.ndarray:
    """0 bis 9 im Vergleich zum Rest des Songs (leiseste 5 % = 0, lauteste 5 % = 9)."""
    if len(werte) == 0:
        return werte
    unten, oben = np.percentile(werte, 5), np.percentile(werte, 95)
    return np.clip(np.round(9 * (werte - unten) / max(oben - unten, 1e-9)), 0, 9).astype(int)


def _wiederholungen(chroma: np.ndarray, fenster: int = 4, abstand: int = 4) -> list:
    """Für jeden Takt: Welcher frühere Takt klingt (mit den Takten danach) am ähnlichsten? (Takt-Index, Ähnlichkeit 0-9)"""
    n = len(chroma)
    ergebnis = [None] * n
    if n < fenster + abstand:
        return ergebnis
    stapel = np.nan_to_num(np.array([chroma[i:i + fenster].ravel() for i in range(n - fenster + 1)], dtype=np.float64))
    stapel = stapel / (np.linalg.norm(stapel, axis=1, keepdims=True) + 1e-9)
    for i in range(abstand, len(stapel)):
        with np.errstate(all="ignore"):         # numpy auf dem Mac meldet hier Fehlalarme
            aehnlich = np.nan_to_num(stapel[:i - abstand + 1] @ stapel[i])
        j = int(np.argmax(aehnlich))
        wert = float(aehnlich[j])
        if wert >= 0.6:
            ergebnis[i] = (j, int(round(9 * (wert - 0.6) / 0.4)))
    return ergebnis


def takt_tabelle(analyse: dict, ton: np.ndarray) -> dict:
    """Messwerte pro Takt. Gibt {"text", "starts" (Sekunden), "anzahl"} zurück."""
    einsen = [float(e) for e in analyse.get("einsen_s") or []]
    if len(einsen) < MIN_TAKTE:
        raise ValueError("In dieser Aufnahme hat die Analyse zu wenige Takte gefunden. Für das Lichtdesign braucht "
                         "es einen Song mit erkennbarem Takt.")
    dauer = float(analyse.get("dauer_s") or len(ton) / songanalyse.ABTASTRATE)
    takt_s = float(np.median(np.diff(einsen)))
    ende = min(dauer, einsen[-1] + takt_s)
    zeiten = np.array(einsen + [ende])
    m = songanalyse.spektral_merkmale(ton)
    mk = songanalyse.takt_merkmale(m, zeiten)
    lb = m["baender"]
    linear = np.expm1(lb) / 1e4
    frequenz = songanalyse.FREQ_MITTEN
    with np.errstate(all="ignore"):
        baender = {name: 10 * np.log10(songanalyse.beat_synchron(linear[:, maske].sum(axis=1)[:, None],
                                                                 songanalyse.RATE, zeiten)[:, 0] + 1e-12)
                   for name, maske in (("B", frequenz < 150), ("M", (frequenz >= 150) & (frequenz < 2000)),
                                       ("H", frequenz >= 2000))}
    skalen = {name: _skala(werte) for name, werte in baender.items()}
    einsaetze = _skala(mk["dichte"])
    laut = mk["laut"]
    gleich = _wiederholungen(mk["chroma"])
    anzahl = len(laut)

    def takt_von(sekunde: float) -> int:
        return int(np.searchsorted(zeiten, sekunde + 0.05, side="right"))     # 1-basiert

    zeichen = {i: [] for i in range(1, anzahl + 1)}
    for art, stellen in (("S", analyse.get("schlaege_s") or []), ("D", analyse.get("markiert_s") or []),
                         ("Drop", analyse.get("drops_s") or [])):
        for stelle in stellen:
            nummer = takt_von(float(stelle))
            if 1 <= nummer <= anzahl:
                zeichen[nummer].append(art)
    for extra in analyse.get("akzente_extra") or []:
        nummer = takt_von(float(extra.get("zeit", 0)))
        if 1 <= nummer <= anzahl:
            zeichen[nummer].append("Hand-" + ("S" if extra.get("art") == "schlag" else "D"))
    anfaenge = {}
    for teil in analyse.get("teile") or []:
        nummer = max(1, takt_von(float(teil["start"])))
        anfaenge.setdefault(nummer, f"▶{teil.get('name', '?')} {teil.get('gruppe', '')} ({teil.get('klasse', '?')})")

    zeilen = ["Takt  Zeit   Laut  B M H  Einsätze  wie  Zeichen / Teil laut Analyse"]
    for i in range(anzahl):
        nummer = i + 1
        minute, sekunde = divmod(zeiten[i], 60)
        wie = f"≈T{gleich[i][0] + 1}({gleich[i][1]})" if gleich[i] else "-"
        rest = " ".join(zeichen[nummer] + ([anfaenge[nummer]] if nummer in anfaenge else []))
        zeilen.append(f"{nummer:>4}  {int(minute)}:{sekunde:04.1f}  {laut[i]:>4.0f}  {skalen['B'][i]} {skalen['M'][i]} "
                      f"{skalen['H'][i]}  {einsaetze[i]:>8}  {wie:<9} {rest}".rstrip())
    return {"text": "\n".join(zeilen), "starts": [round(float(z), 3) for z in zeiten[:-1]], "anzahl": anzahl,
            "ende": round(float(ende), 3)}


# --- Den Plan prüfen und in eine Sequenz umbauen ----------------------------------------------

def plan_ordnen(plan: dict, anzahl: int) -> list:
    """Sortiert die Teile, entfernt doppelte Anfänge und Takte außerhalb des Songs. Der erste Teil beginnt bei Takt 1."""
    teile, gesehen = [], set()
    for teil in sorted(plan.get("teile") or [], key=lambda t: int(t.get("von_takt") or 0)):
        von = max(1, min(int(teil.get("von_takt") or 1), anzahl))
        if von in gesehen:
            continue
        gesehen.add(von)
        teile.append({**teil, "von_takt": von})
    if not teile:
        raise ValueError("Claude hat keine Songteile geliefert.")
    teile[0]["von_takt"] = 1
    for nummer, teil in enumerate(teile):
        teil["bis_takt"] = teile[nummer + 1]["von_takt"] if nummer + 1 < len(teile) else anzahl + 1
        if teil.get("name") not in TEIL_NAMEN:
            teil["name"] = "Zwischenteil"
        if teil.get("klasse") not in KLASSEN:
            teil["klasse"] = "mittel"
        if teil.get("bewegung") not in BEWEGUNGEN:
            teil["bewegung"] = "keine"
        if teil.get("farben") not in ("A", "B", "BA"):
            teil["farben"] = "BA"
        if teil.get("puls") not in PULSE:
            teil["puls"] = "puls"
        teil["akzent_takte"] = sorted({int(t) for t in teil.get("akzent_takte") or []
                                       if isinstance(t, (int, float)) and teil["von_takt"] <= int(t) < teil["bis_takt"]})
    return teile


def _farben_waehlen(plan: dict, palette: list, tempo: float, vergeben: tuple) -> tuple:
    """Die Song-Farben von Claude, wenn sie gültig sind und (bei mehrfarbiger Palette) in der Palette stehen."""
    a, b = str(plan.get("farbe_a") or "").strip().lower(), str(plan.get("farbe_b") or "").strip().lower()
    erlaubt = [str(f).lower() for f in palette or []]
    gut = lambda f: ist_farbe(f) and f not in ("weiss", "#ffffff") and (len(erlaubt) < 2 or f in erlaubt)
    if gut(a) and gut(b) and a != b:
        return a, b
    if gut(a):
        andere = [f for f in erlaubt if f != a and gut(f)]
        if andere:
            return a, andere[0]
    return farbpaar(palette, tempo, vergeben)


def _look(teil: dict, gruppen: list, farbe_a: str, farbe_b: str, gobo: Optional[str], band: Optional[str],
          tempo: float, variante: int, strobo_erlaubt: bool, name: str, zeit: Optional[float] = None) -> dict:
    """Ein Look nach Claudes Plan, gebaut mit denselben Bausteinen wie das Song-Licht von Hand (probe.look_cue)."""
    klasse = teil["klasse"]
    drop = teil["name"] == "Drop"
    cue = look_cue(name, klasse, gruppen, farbe_a, farbe_b, gobo, band, drop=drop, zeit_s=zeit,
                   tempo_bpm=tempo, variante=variante, farben=teil["farben"])
    _, groesse, beats, _hell, _drehung, tiefe, pro_minute, _ = LOOKS[klasse]
    effekte = [e for e in cue["effekte"] if e["art"] not in ("kreis", "acht", "schwenk", "nicken", "publikum",
                                                              "dimmer_welle", "dimmer_puls")]
    spots = "Spots" in gruppen
    if spots and not drop:
        werte_spots = next((w for w in cue["werte"] if w["gruppe"] == "Spots"), None)
        if teil["bewegung"] == "keine":
            if werte_spots is not None and band:
                werte_spots["position"] = band
        else:
            if werte_spots is not None:
                werte_spots.pop("position", None)
            effekte.append({"art": teil["bewegung"], "ziel": {"gruppe": "Spots"}, "tempo": "musik",
                            "groesse": max(groesse, 0.3), "beats": beats if beats <= 32 else 32, "verteilung": 0.5,
                            **({"mitte": band} if band else {})})
    elif drop:
        effekte += [e for e in cue["effekte"] if e["art"] in ("kreis", "acht", "schwenk", "nicken", "publikum")]
    for ziel in ("Spots", "Farb-PARs"):
        if ziel not in gruppen:
            continue
        if teil["puls"] == "atmen":
            effekte.append({"art": "dimmer_welle", "ziel": {"gruppe": ziel}, "tempo": "musik", "tiefe": max(tiefe, 0.3),
                            "beats": 16, "verteilung": 0.5})
        elif teil["puls"] == "kraeftig":
            effekte.append({"art": "dimmer_puls", "ziel": {"gruppe": ziel}, "tempo": "musik", "tiefe": 0.7,
                            "beats": 1 if tempo <= 140 else 2, "verteilung": 0.0})
        else:
            effekte.append({"art": "dimmer_puls", "ziel": {"gruppe": ziel}, "tempo": "musik", "tiefe": tiefe,
                            "beats": _pulse_alle(tempo, pro_minute or 60), "verteilung": 0.0})
    cue["effekte"] = effekte
    blitzt = strobo_erlaubt and teil.get("strobo") and klasse in ("stark", "hoehepunkt")
    for wert in cue["werte"]:
        if wert["gruppe"] == "Strobo":
            wert["helligkeit"] = 1.0 if blitzt else 0.0
            wert["strobo_hz"] = 3.0 if blitzt else 0.0
    return cue


def show_aus_plan(analyse: dict, plan: dict, tabelle: dict, patch, palette: list, gobos_von,
                  positionen: Optional[dict] = None, strobo_erlaubt: bool = False, vergeben: tuple = ()) -> dict:
    """Baut aus Claudes Plan die Sequenz für den Song-Start: Cues, Zeiten (aus den Takten) und die Song-Karte."""
    gruppen = patch.gruppen()
    tempo = float(analyse.get("tempo_bpm") or 120.0)
    starts, anzahl = tabelle["starts"], tabelle["anzahl"]
    dauer = float(analyse.get("dauer_s") or tabelle["ende"])
    teile = plan_ordnen(plan, anzahl)
    farbe_a, farbe_b = _farben_waehlen(plan, palette, tempo, vergeben)
    gobos = gobos_von("Spots") if "Spots" in gruppen else []
    band = next((p for p in ("Band", "Mitte") if positionen and p in positionen), None)
    zeit_von = lambda takt: 0.0 if takt <= 1 else (starts[takt - 1] if takt - 1 < len(starts) else dauer)
    ereignisse, karte, buchstaben = [], [], {}
    for index, teil in enumerate(teile):
        start, ende = zeit_von(teil["von_takt"]), zeit_von(teil["bis_takt"]) if teil["bis_takt"] <= anzahl else dauer
        takte = teil["bis_takt"] - teil["von_takt"]
        gruppe = buchstaben.setdefault((teil["name"], teil["klasse"], teil["bewegung"], teil["farben"]),
                                       chr(ord("A") + len(buchstaben) % 26))
        stueck = {"start": round(start, 2), "ende": round(ende, 2), "gruppe": gruppe, "name": teil["name"]}
        titel = f"{teil['name']} {gruppe} ({takte} Takte)"
        karte.append({"name": teil["name"], "gruppe": gruppe, "klasse": teil["klasse"], "start": stueck["start"],
                      "ende": stueck["ende"], "takte": takte, "idee": str(teil.get("idee") or "")[:200],
                      "_erstes": len(ereignisse)})
        naechster = teile[index + 1] if index + 1 < len(teile) else None
        if teil["name"] == "Aufbau" or (teil["name"] == "Überleitung" and naechster and naechster["name"] == "Drop"):
            cue = aufbau_cue(stueck, gruppen, farbe_b)
            cue["name"] = titel
            ereignisse.append((stueck["start"], cue))
            continue
        nummer = ord(gruppe) - ord("A")          # gleiche Teile bekommen dasselbe Gobo

        def look(variante: int, name: str = titel, zeit: Optional[float] = None) -> dict:
            gobo = gobos[(nummer + variante) % len(gobos)] if gobos else None
            return _look(teil, gruppen, farbe_a, farbe_b, gobo, band, tempo, variante, strobo_erlaubt, name, zeit)

        cue = look(0, zeit=4.0 if teil["name"] == "Schluss" else ZEITEN_S[teil["klasse"]])
        schlaege = schlaege_im_teil(analyse, {**stueck}, teil["klasse"])
        zeit_look = stueck["start"]
        if schlaege and abs(schlaege[0] - stueck["start"]) <= 0.3:
            ereignisse.append((stueck["start"], schlag_cue(gruppen)))     # der Teil beginnt mit einem großen Schlag
            zeit_look = round(stueck["start"] + SCHLAG_S, 2)
        ereignisse.append((zeit_look, cue))
        phrasen = [] if teil["klasse"] == "ruhig" or teil["name"] == "Drop" else _phrasen(analyse, stueck)
        looks = [(zeit_look, cue)]
        for k, stelle in enumerate(phrasen, start=1):
            neu = look(k, f"{titel} · Takt {PHRASE_TAKTE * k + 1}", PHRASE_ZEIT_S)
            ereignisse.append((stelle, neu))
            looks.append((stelle, neu))
        # Akzente: von Hand markierte (Taste D, Zeitleiste) bleiben immer, dazu Claudes Takte
        akzente = [(stelle, "akzent") for stelle in akzente_im_teil(analyse, stueck)]
        for takt in teil["akzent_takte"]:
            stelle = zeit_von(takt)
            nah = [s for s in analyse.get("schlaege_s") or [] if abs(s - stelle) <= 0.35]
            stelle = nah[0] if nah else stelle
            if stelle > zeit_look + 0.5 and all(abs(stelle - a) > 1.5 for a, _ in akzente):
                akzente.append((stelle, "schlag"))
        for stelle, art in sorted(akzente):
            dauer_akzent = AKZENT_S if art == "akzent" else SCHLAG_S
            jetzt_look = max((l for l in looks if l[0] <= stelle + 0.01), key=lambda l: l[0])[1]
            ereignisse.append((round(stelle, 2), akzent_cue(gruppen) if art == "akzent" else schlag_cue(gruppen)))
            ereignisse.append((round(stelle + dauer_akzent, 2), {**jetzt_look, "name": jetzt_look["name"] + " weiter",
                                                                 "zeit_s": 0.5}))
    reihenfolge = sorted(range(len(ereignisse)), key=lambda i: (ereignisse[i][0], i))
    neue_stelle = {alt: neu for neu, alt in enumerate(reihenfolge)}
    for teil in karte:
        teil["cue"] = neue_stelle[teil.pop("_erstes")]
    return {"name": analyse["name"], "cues": [ereignisse[i][1] for i in reihenfolge],
            "zeitcode": [ereignisse[i][0] for i in reihenfolge], "farben": [farbe_a, farbe_b],
            "licht_version": LICHT_VERSION_KI,
            "song": {"probe": analyse["name"], "tempo_bpm": analyse["tempo_bpm"], "dauer_s": analyse["dauer_s"],
                     "musik_von_s": analyse.get("musik_von_s", 0.0), "musik_bis_s": analyse.get("musik_bis_s"),
                     "teile": karte, "ki": {"song_erkannt": str(plan.get("song_erkannt") or "")[:120],
                                            "erklaerung": str(plan.get("erklaerung") or "")[:600]}},
            "_hinweis": "Von Claude entworfen (KI-Lichtdesign) und vom Menschen übernommen. Im Pult frei änderbar."}


# --- Claude fragen -------------------------------------------------------------------

class KiDesign:
    def __init__(self, show):
        self.show = show
        self.letzte_tabelle: Optional[str] = None      # zum Nachsehen und für Tests

    def _client(self):
        return self.show.ki.client(ZEITLIMIT_S, wiederholen=1)

    def nachricht(self, probe: str, analyse: dict, tabelle: dict, titel: str, wuensche: str) -> str:
        show = self.show
        profil = show.profil
        strobo = profil.get("strobo", "aus")
        alte = show.pult.sequenzen.lesen(probe)
        alt_text = ""
        if alte and alte.get("song", {}).get("teile"):
            alt_text = "\nSo sieht die jetzige Show aus (Teile): " + "; ".join(
                f"{t.get('name')} ab {t.get('start')} s ({t.get('klasse')})" for t in alte["song"]["teile"])
            if alte.get("farben"):
                alt_text += f". Farben jetzt: {', '.join(alte['farben'])}."
        return (f"Song: „{probe}“{' – Titel: ' + titel if titel.strip() else ''}. Tempo {analyse.get('tempo_bpm')} BPM, "
                f"{tabelle['anzahl']} Takte, {analyse.get('dauer_s')} s.\n"
                f"Profil „{profil['name']}“: Palette {', '.join(profil.get('palette') or [])}; "
                f"Bewegung {profil.get('bewegung')}; Strobo {'erlaubt' if strobo != 'aus' else 'aus'}."
                + (f" Hinweise für die KI: {profil['hinweise_ki']}" if profil.get("hinweise_ki") else "")
                + alt_text
                + (f"\n\nWÜNSCHE DES MENSCHEN (gehen vor): {wuensche.strip()}" if wuensche.strip() else "")
                + "\n\nTAKT-TABELLE (Laut in dB, B/M/H = Bass/Mitten/Höhen 0-9 im Vergleich zum Rest des Songs, "
                  "Einsätze 0-9 = wie viel los ist, „wie“ = klingt wie dieser frühere Takt (Ähnlichkeit 0-9), "
                  "S = großer Schlag der Band, D = Taste D vom Menschen (wichtige Stelle), Drop = erkannter Drop, "
                  "Hand- = von Hand gesetzt):\n" + tabelle["text"])

    def entwerfen(self, probe: str, titel: str = "", wuensche: str = "") -> dict:
        """Fragt Claude und baut die Sequenz. Gibt {"probe", "sequenz", "plan", "erklaerung"} zurück."""
        import anthropic
        show = self.show
        if not show.ki.bereit():
            raise ValueError("Für das KI-Lichtdesign braucht es den Claude-Schlüssel (Licht-Chat → Claude-Schlüssel).")
        analyse = show.proben.lesen(probe)
        if analyse is None:
            raise ValueError(f"Probe „{probe}“ gibt es nicht.")
        if analyse.get("version") != ANALYSE_VERSION:
            analyse = show.proben.neu_analysieren(probe) or analyse
        ton = lade_datei(show.proben.ton_pfad(probe))
        tabelle = takt_tabelle(analyse, ton)
        self.letzte_tabelle = tabelle["text"]
        modell = show.ki.modell()
        system = SYSTEM + "\n" + welt_text(show)
        nachricht = self.nachricht(probe, analyse, tabelle, titel, wuensche)
        try:
            antwort = self._client().beta.messages.create(
                model=modell, max_tokens=16000, system=system,
                messages=[{"role": "user", "content": nachricht}],
                thinking={"type": "adaptive"},
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except anthropic.AuthenticationError as fehler:
            raise ValueError("Der Claude-Schlüssel stimmt nicht.") from fehler
        except anthropic.RateLimitError as fehler:
            raise ValueError("Gerade zu viele Anfragen oder das Ausgabenlimit ist erreicht.") from fehler
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as fehler:
            raise ValueError("Kein Internet: Das KI-Lichtdesign geht gerade nicht. „Show neu bauen“ geht ohne.") from fehler
        except anthropic.APIStatusError as fehler:
            logging.warning("KI-Lichtdesign: %s", getattr(fehler, "message", fehler))
            raise ValueError(f"Claude hat das Lichtdesign abgelehnt (Fehler {fehler.status_code}).") from fehler
        show.ki.buchen("design", antwort.usage, modell)
        if antwort.stop_reason == "refusal":
            raise ValueError("Claude wollte dieses Lichtdesign nicht machen.")
        if antwort.stop_reason == "max_tokens":
            raise ValueError("Die Antwort von Claude war zu lang. Bitte nochmal versuchen.")
        try:
            plan = json.loads(antwort_text(antwort))
        except ValueError as fehler:
            raise ValueError("Die Antwort von Claude ließ sich nicht lesen. Bitte nochmal versuchen.") from fehler
        vergeben = []
        for anderer in show.proben.namen():
            alte = show.pult.sequenzen.lesen(anderer) if anderer != probe else None
            if alte and len(alte.get("farben") or []) == 2:
                vergeben.append(tuple(alte["farben"]))
        strobo_erlaubt = show.profil.get("strobo", "aus") != "aus"
        sequenz = show_aus_plan(analyse, plan, tabelle, show.patch, show.profil.get("palette") or [],
                                show.gobos_der_gruppe, show.positionen, strobo_erlaubt, tuple(vergeben))
        fehler = pruefen(show, sequenz)
        if fehler:
            raise ValueError("Der Entwurf besteht die Prüfung nicht: " + " ".join(fehler[:5]))
        erklaerung = str(plan.get("erklaerung") or "").strip() or "Show entworfen."
        erkannt = str(plan.get("song_erkannt") or "").strip()
        if erkannt and erkannt.lower() not in ("unbekannt", "nicht erkannt"):
            erklaerung = f"Erkannt: {erkannt}. {erklaerung}"
        return {"probe": probe, "sequenz": sequenz, "plan": plan, "erklaerung": erklaerung}
