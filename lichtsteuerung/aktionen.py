"""Was ein gekoppeltes iPad am Pult tun darf – geprüft wie am MacBook und unter der Show-Sperre.

Jede Aktion bekommt die Show, die Angaben aus der Nachricht und die Sitzung (das verbundene Gerät).
Erlaubt ist nur, was in AKTIONEN steht. Nicht dabei, mit Absicht: Patch ändern, Profile bearbeiten,
Ton-Quelle und Rollen, Claude-Schlüssel, Sicherung, Update, Beenden. Das passiert am MacBook.

Gehaltene Tasten (Flash, Halten) merkt sich die Sitzung. Reißt die Verbindung ab, lässt der Netz-Server
sie los (`loslassen`). Die Not-Tasten werden fest gesetzt (an/aus), nicht umgeschaltet.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from .befehle import Befehlszeile
from .pult import EFFEKT_ARTEN, pruefe_effekt
from .szenen import pruefe_werte

FEINER = 0.25            # Encoder „fein“: so viel langsamer
WINKEL_PRO_SCHRITT = 1.0  # XY-Feld: Grad pro Einheit (das iPad schickt schon skaliert)


class Sitzung:
    """Ein verbundenes iPad: was es gerade festhält, seine Befehlszeile."""

    def __init__(self, show, name: str = "iPad"):
        self.show = show
        self.name = name
        self.flashes: set = set()
        self.halten: set = set()
        self.befehlszeile = Befehlszeile(show)


def _zahl(daten: dict, feld: str, unten: float, oben: float) -> float:
    try:
        wert = float(daten[feld])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"„{feld}“ fehlt oder ist keine Zahl.") from None
    if wert != wert:                     # NaN
        raise ValueError(f"„{feld}“ ist keine Zahl.")
    return max(unten, min(oben, wert))


def _nr(daten: dict) -> int:
    return int(_zahl(daten, "nr", 1, 40))


# --- Fader und Tasten -------------------------------------------------------------------

def fader(show, d, sitzung):
    with show.sperre:
        show.pult.fader_setzen(_nr(d), _zahl(d, "wert", 0, 1), time.monotonic())


def taste(show, d, sitzung):
    nummer, art = _nr(d), str(d.get("taste", ""))
    an = bool(d.get("an", True))
    erwartet = d.get("erwartet")
    erwartet = bool(erwartet) if isinstance(erwartet, bool) else None
    jetzt = time.monotonic()
    with show.sperre:
        executor = show.pult.executor(nummer)
        if art in ("go", "zurueck", "aus", "toggle") and executor.zeitcode is True:
            executor.zeitcode = False                 # „Probe ansehen“ endet, Song-Start bleibt
        if art == "aus" and show.song.laeuft_auf(nummer):
            show.song.stoppen(jetzt)
        show.pult.taste(nummer, art, jetzt, an=an, erwartet=erwartet)
    if art == "flash":
        (sitzung.flashes.add if an else sitzung.flashes.discard)(nummer)


def grand(show, d, sitzung):
    with show.sperre:
        show.pult.grand_setzen(_zahl(d, "wert", 0, 1), time.monotonic())


def go_haupt(show, d, sitzung):
    richtung = -1 if d.get("richtung") == "minus" else 1
    with show.sperre:
        show.pult.go(show.pult.haupt + 1, time.monotonic(), richtung)


def haupt_aus(show, d, sitzung):
    with show.sperre:
        show.pult.aus(show.pult.haupt + 1, time.monotonic())


def haupt_waehlen(show, d, sitzung):
    nummer = _nr(d)
    with show.sperre:
        show.pult.executor(nummer)
        show.pult.haupt = nummer - 1


def override(show, d, sitzung):
    with show.sperre:
        show.overrides.setzen(str(d.get("taste", "")), bool(d.get("an")))


# --- Programmieren ----------------------------------------------------------------------

def auswahl(show, d, sitzung):
    geraete = [str(g) for g in d.get("geraete") or []]
    if d.get("gruppe"):
        geraete = [g["id"] for g in show.patch.in_gruppe(str(d["gruppe"]))]
    bekannt = {g["id"] for g in show.patch.geraete}
    if any(g not in bekannt for g in geraete):
        raise ValueError("Unbekanntes Gerät.")
    with show.sperre:
        show.pult.waehlen(geraete, str(d.get("art", "setzen")))


def werte(show, d, sitzung):
    geraete = [str(g) for g in (d.get("geraete") or show.pult.auswahl)]
    neu = d.get("werte") or {}
    if not geraete:
        raise ValueError("Zuerst Geräte auswählen.")
    if not isinstance(neu, dict) or not neu:
        raise ValueError("Keine Werte.")
    fehler = pruefe_werte([{"geraet": g, **neu} for g in geraete], None,
                          [g["id"] for g in show.patch.geraete], show.positionen)
    if fehler:
        raise ValueError(" ".join(fehler))
    with show.sperre:
        show.pult.merke_programmer()
        show.pult.programmer.setzen(geraete, neu)


def encoder(show, d, sitzung):
    """Drehregler: ändert Helligkeit, Pan oder Tilt der Auswahl um `delta` (relativ zum jetzigen Wert)."""
    attribut = str(d.get("attribut", ""))
    delta = _zahl(d, "delta", -1000, 1000) * (FEINER if d.get("fein") else 1.0)
    grenzen = {"helligkeit": (0.0, 1.0), "pan": (-270.0, 270.0), "tilt": (-135.0, 135.0)}
    if attribut not in grenzen:
        raise ValueError(f"Encoder für {attribut!r} gibt es nicht.")
    unten, oben = grenzen[attribut]
    with show.sperre:
        geraete = list(show.pult.auswahl)
        if not geraete:
            raise ValueError("Zuerst Geräte auswählen.")
        if attribut != "helligkeit":
            geraete = [g for g in geraete if show.faehigkeiten(show.patch.geraet(g))["beweglich"]]
            if not geraete:
                raise ValueError("In der Auswahl ist kein Moving Head.")
        show.pult.merke_programmer(zusammen=True)
        for geraet_id in geraete:
            eintrag = show.pult.programmer.werte.get(geraet_id, {})
            jetzt = eintrag.get(attribut)
            if jetzt is None:
                live = show.letzter_zustand.get(geraet_id)
                jetzt = getattr(live, attribut, None) if live is not None else None
            if jetzt is None:
                jetzt = 0.0
            neu = max(unten, min(oben, float(jetzt) + delta))
            werte_neu = {attribut: round(neu, 4)}
            if attribut in ("pan", "tilt"):
                anderer = "tilt" if attribut == "pan" else "pan"
                if anderer not in eintrag:
                    live = show.letzter_zustand.get(geraet_id)
                    wert = getattr(live, anderer, None) if live is not None else None
                    werte_neu[anderer] = round(float(wert or 0.0), 4)
            show.pult.programmer.setzen([geraet_id], werte_neu)


def xy(show, d, sitzung):
    """XY-Feld wie die Kugel am Pult: relativ ziehen (dx = Pan, dy = Tilt, in Grad)."""
    dx, dy = _zahl(d, "dx", -90, 90), _zahl(d, "dy", -90, 90)
    if dx:
        encoder(show, {"attribut": "pan", "delta": dx, "fein": d.get("fein")}, sitzung)
    if dy:
        encoder(show, {"attribut": "tilt", "delta": dy, "fein": d.get("fein")}, sitzung)


def punkt(show, d, sitzung):
    """Punkt auf der Bühne antippen: Die gewählten Köpfe zeigen dorthin (x, y in Metern, Kopfhöhe)."""
    ziel = {"x": _zahl(d, "x", -50, 50), "y": _zahl(d, "y", -50, 50), "z": _zahl({"z": d.get("z", 1.6)}, "z", 0, 10)}
    werte(show, {"werte": {"punkt": ziel}}, sitzung)


def effekt(show, d, sitzung):
    neu = dict(d.get("effekt") or {})
    if neu.get("art") not in EFFEKT_ARTEN:
        raise ValueError("Unbekannter Effekt.")
    if not neu.get("ziel"):
        neu["ziel"] = {"geraete": list(show.pult.auswahl)}
    fehler = pruefe_effekt(neu, show.patch.gruppen(), [g["id"] for g in show.patch.geraete])
    if fehler:
        raise ValueError(" ".join(fehler))
    with show.sperre:
        show.pult.merke_programmer()
        show.pult.programmer.effekt_dazu(neu)


def effekt_weg(show, d, sitzung):
    with show.sperre:
        nummer = int(_zahl(d, "nummer", 0, 99))
        if not 0 <= nummer < len(show.pult.programmer.effekte):
            raise ValueError("Diesen Effekt gibt es nicht.")
        show.pult.merke_programmer()
        del show.pult.programmer.effekte[nummer]


def leeren(show, d, sitzung):
    with show.sperre:
        if not show.pult.programmer.ist_leer():
            show.pult.merke_programmer()
        show.pult.programmer.leeren()


def blind(show, d, sitzung):
    with show.sperre:
        show.pult.programmer.blind = bool(d.get("an"))


def highlight(show, d, sitzung):
    with show.sperre:
        show.pult.highlight = bool(d.get("an"))


def oops(show, d, sitzung):
    with show.sperre:
        return {"text": show.pult.rueckgaengig()}


def preset(show, d, sitzung):
    with show.sperre:
        show.pult.preset_anwenden(int(_zahl(d, "nummer", 0, 999)))


def preset_speichern(show, d, sitzung):
    with show.sperre:
        show.pult.preset_speichern(str(d.get("name", "")), str(d.get("art", "")))


def kommando(show, d, sitzung):
    """Befehlszeile wie am Pult („Fixture 1 Thru 3 At Full“, „Store Fader 3“)."""
    text = str(d.get("text", ""))[:300]
    return {"antwort": sitzung.befehlszeile.ausfuehren(text)}


# --- Speichern auf Fader (Store, Update, Assign, Label) -----------------------------------

def speichern(show, d, sitzung):
    with show.sperre:
        sequenz = show.pult.speichern_auf(_nr(d), str(d.get("cue_name") or "") or None,
                                          _zahl({"z": d.get("zeit_s", 2.0)}, "z", 0, 600))
    return {"sequenz": sequenz["name"], "cues": len(sequenz["cues"])}


def update(show, d, sitzung):
    with show.sperre:
        return {"sequenz": show.pult.aktualisieren(_nr(d))["name"]}


def zuweisen(show, d, sitzung):
    nummer = _nr(d)
    with show.sperre:
        if d.get("sequenz"):
            show.pult.zuweisen(nummer, "sequenz", str(d["sequenz"]))
        elif d.get("gruppe"):
            show.pult.zuweisen(nummer, "gruppe", str(d["gruppe"]))
        elif d.get("art") == "tempo":
            show.pult.zuweisen(nummer, "tempo")
        elif d.get("frei"):
            show.pult.zuweisen(nummer, None)
        else:
            raise ValueError("Was soll auf den Fader? (sequenz, gruppe, art tempo oder frei)")


def label(show, d, sitzung):
    with show.sperre:
        show.pult.label_setzen(_nr(d), str(d.get("text", "")))


def tasten(show, d, sitzung):
    with show.sperre:
        show.pult.tasten_setzen(_nr(d), d.get("tasten") or None)


def exec_farbe(show, d, sitzung):
    with show.sperre:
        show.pult.farbe_setzen(_nr(d), d.get("farbe") or None)


# --- Show: Looks, Farben, Halten, Tempo, Songs, Automatik ---------------------------------

def look(show, d, sitzung):
    look_id = str(d.get("id", ""))
    with show.sperre:
        if look_id == "aus":
            show.pult.look_aus(time.monotonic())
        else:
            show.pult.look_druecken(look_id, time.monotonic())


def farben(show, d, sitzung):
    with show.sperre:
        show.pult.farben_setzen(d.get("farbe_1"), d.get("farbe_2"), time.monotonic())


def halten(show, d, sitzung):
    art, an = str(d.get("art", "")), bool(d.get("an", True))
    with show.sperre:
        show.pult.halten_setzen(art, an, time.monotonic())
    (sitzung.halten.add if an else sitzung.halten.discard)(art)


def tap(show, d, sitzung):
    with show.sperre:
        return {"tempo": show.pult.tap(time.monotonic())}


def song(show, d, sitzung):
    aktion = str(d.get("aktion", ""))
    if aktion == "start":
        show.song.starten(str(d.get("name", "")))
    elif aktion == "stopp":
        show.song.stoppen()
    elif aktion == "vor":
        show.song.teil_vor()
    elif aktion == "zurueck":
        show.song.teil_zurueck()
    elif aktion == "los":
        show.song.jetzt_los()
    elif aktion == "vorschlag":
        show.song.vorschlag_starten()
    else:
        raise ValueError(f"Unbekannte Song-Aktion {aktion!r}.")


def automatik(show, d, sitzung):
    with show.sperre:
        show.automatik_an = bool(d.get("an"))
    show._sitzung_speichern()


def profil(show, d, sitzung):
    show.profil_laden(str(d.get("name", "")))


def regie(show, d, sitzung):
    show.regie.einschalten(bool(d.get("an")))
    show._sitzung_speichern()


def followspot(show, d, sitzung):
    with show.sperre:
        if d.get("aus"):
            show.follow_spot.aus()
        else:
            show.follow_spot.setzen(_zahl(d, "x", -50, 50), _zahl(d, "y", -50, 50), d.get("geraete"), d.get("hell"))


def dmx(show, d, sitzung):
    """DMX an/aus vom iPad nur mit ausdrücklicher Bestätigung (Rückfrage auf dem iPad)."""
    if not d.get("bestaetigt"):
        raise ValueError("DMX schalten braucht eine Bestätigung.")
    if d.get("an"):
        from .dmx_ausgabe import EnttecFehler
        try:
            show.ausgabe.einschalten()
        except EnttecFehler as fehler:
            raise ValueError(str(fehler)) from fehler
    else:
        show.ausgabe.ausschalten()


def aufblitzen(show, d, sitzung):
    """Ein Gerät kurz hell (wie Highlight für ein einzelnes Gerät): zum Finden beim Aufbau."""
    geraet_id = str(d.get("geraet", ""))
    if geraet_id not in {g["id"] for g in show.patch.geraete}:
        raise ValueError("Unbekanntes Gerät.")
    with show.sperre:
        show.pult.waehlen([geraet_id], "setzen")
        show.pult.highlight = bool(d.get("an", True))


# --- Licht-Chat (Claude) ------------------------------------------------------------------

def chat(show, d, sitzung):
    """Dauert mit Claude ein paar Sekunden: Der Netz-Server ruft das in einem eigenen Faden auf."""
    text = str(d.get("text", "")).strip()[:2000]
    if not text:
        raise ValueError("Leere Nachricht.")
    show.chat.senden(text)


def chat_vorschau(show, d, sitzung):
    show.chat.vorschau_cue(int(_zahl(d, "cue", 0, 999)))


def chat_uebernehmen(show, d, sitzung):
    nummer = d.get("fader")
    ergebnis = show.chat.uebernehmen(int(nummer) if nummer else None, str(d.get("name") or "") or None)
    if nummer:
        with show.sperre:
            show.pult.haupt = int(nummer) - 1        # die neue Szene liegt auf den großen Go-Tasten bereit
    return ergebnis


def chat_verwerfen(show, d, sitzung):
    show.chat.verwerfen()


def chat_neu(show, d, sitzung):
    show.chat.neu()


AKTIONEN: dict = {
    # Spielen
    "fader": fader, "taste": taste, "grand": grand, "go_haupt": go_haupt, "haupt_aus": haupt_aus,
    "haupt_waehlen": haupt_waehlen, "override": override,
    # Programmieren
    "auswahl": auswahl, "werte": werte, "encoder": encoder, "xy": xy, "punkt": punkt, "effekt": effekt,
    "effekt_weg": effekt_weg, "leeren": leeren, "blind": blind, "highlight": highlight, "oops": oops,
    "preset": preset, "preset_speichern": preset_speichern, "kommando": kommando,
    "speichern": speichern, "update": update, "zuweisen": zuweisen, "label": label, "tasten": tasten,
    "exec_farbe": exec_farbe,
    # Show
    "look": look, "farben": farben, "halten": halten, "tap": tap, "song": song, "automatik": automatik,
    "profil": profil, "regie": regie, "followspot": followspot, "dmx": dmx, "aufblitzen": aufblitzen,
    # Chat
    "chat": chat, "chat_vorschau": chat_vorschau, "chat_uebernehmen": chat_uebernehmen,
    "chat_verwerfen": chat_verwerfen, "chat_neu": chat_neu,
}
LANGSAM = {"chat", "chat_uebernehmen", "profil", "dmx", "song"}   # laufen in einem eigenen Faden


def ausfuehren(show, was: str, daten: dict, sitzung: Sitzung) -> Optional[dict]:
    aktion: Optional[Callable] = AKTIONEN.get(was)
    if aktion is None:
        raise ValueError(f"Das darf das iPad nicht ({was!r}).")
    return aktion(show, daten if isinstance(daten, dict) else {}, sitzung)


def loslassen(show, sitzung: Sitzung) -> None:
    """Verbindung weg: alle Tasten loslassen, die dieses iPad noch hielt (Flash, Weiß voll, Strobo …)."""
    jetzt = time.monotonic()
    with show.sperre:
        for nummer in list(sitzung.flashes):
            try:
                show.pult.flash(nummer, False, jetzt)
            except ValueError:
                pass
        for art in list(sitzung.halten):
            try:
                show.pult.halten_setzen(art, False, jetzt)
            except ValueError:
                pass
    sitzung.flashes.clear()
    sitzung.halten.clear()
