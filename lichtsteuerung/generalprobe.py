"""Generalprobe: Das Programm spielt die Setlist mit den Probe-Aufnahmen durch und sagt, wo es unsicher ist.

Für jeden Song (in der Reihenfolge der Setlist) gibt es zwei Durchläufe mit einer veränderten Aufnahme,
so wie es beim Konzert klingen könnte (audio/livefassung.py):

    wie live      3 % schneller, anderer Mix, etwas Publikum (so kommt der Ton vom X32)
    schwierig     4 % langsamer, Saal mit Hall, lautes Publikum (so hört ein Mikrofon im Saal)

In jedem Durchlauf hört die Song-Erkennung zu (mit allen geprobten Songs, wie beim Konzert), und der
Song-Folger folgt der Band, nachdem der Song-Knopf eine Sekunde zu früh gedrückt wurde. Gemessen wird:

    Erkennung     nach wie vielen Sekunden der Song erkannt wurde, oder ob er verwechselt wurde
    Licht         wie pünktlich die Teilwechsel kamen (Sekunden zu früh oder zu spät)

Grün heißt: gute Chancen. Gelb: geht, aber beim Konzert aufpassen. Rot: so nicht (verwechselt, oder das
Licht kam viel zu spät). Eine echte Band spielt noch etwas anders als die veränderte Aufnahme.

Die Generalprobe rechnet nebenher und braucht viel Rechenzeit. Sie startet nicht, solange ein Song
läuft, und hört auf, sobald einer startet: Das Konzert hat immer Vorrang.
"""
from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Callable, Optional

import numpy as np

from . import daten
from .audio import erkennen, folgen, livefassung
from .audio.quellen import ABTASTRATE as RATE, BLOCK, lade_datei

PRUEFEN_ALLE_S = 0.5            # so oft prüft die Song-Erkennung (wie live)
ERKENNEN_BIS_S = 40.0           # so lange nach dem Einsatz der Band darf die Erkennung brauchen
ERKENNEN_GUT_S = 15.0
START_FRUEH_S = 1.0             # der Song-Knopf wird etwas zu früh gedrückt
GUT_S = 1.0                     # Teilwechsel höchstens so weit daneben: gut
GEHT_S = 3.0                    # ... so weit: geht noch
LANGSAM_FAKTOR = 3.0            # rechnet der Laptop weniger als 3-mal so schnell wie die Musik: knapp
VERSION = 1

DURCHLAEUFE = (
    {"art": "live", "titel": "wie live", "text": "3 % schneller, anderer Mix, etwas Publikum",
     "tempo": 1.03, "nachhall_s": 0.0, "publikum_db": 14.0, "seed": 1},
    {"art": "schwer", "titel": "schwierig", "text": "4 % langsamer, Saal mit Hall, lautes Publikum",
     "tempo": 0.96, "nachhall_s": 1.6, "publikum_db": 6.0, "seed": 2},
)


class Abgebrochen(Exception):
    pass


def _sekunden(wert: float) -> str:
    return f"{wert:.1f}".replace(".", ",")


# --- Messen ----------------------------------------------------------------------

def erkennung_messen(fassung: livefassung.LiveFassung, song: str, referenzen: dict,
                     abbruch: Callable[[], bool] = lambda: False, weitere: Optional[dict] = None) -> dict:
    """Hört den Anfang der Live-Fassung wie zwischen zwei Songs: Wird der richtige Song erkannt, und wann?

    referenzen: Name -> Merkmale (wie SongErkenner.referenzen, also schon ausgedünnt)."""
    erkenner = erkennen.SongErkenner()
    erkenner.referenzen = referenzen
    erkenner.weitere = dict(weitere or {})      # Mitschnitte und weitere Proben, wie beim Konzert
    ton = fassung.ton
    ende = min(len(ton), int((fassung.musik_ab_s + ERKENNEN_BIS_S) * RATE))
    naechste = PRUEFEN_ALLE_S
    for a in range(0, ende - BLOCK, BLOCK):
        if a % (40 * BLOCK) == 0 and abbruch():
            raise Abgebrochen()
        jetzt = (a + BLOCK) / RATE
        erkenner.hoeren(ton[a:a + BLOCK], jetzt)
        if jetzt < naechste:
            continue
        naechste += PRUEFEN_ALLE_S
        treffer = erkenner.pruefen(jetzt)
        if treffer is None:
            continue
        nach = round(max(0.0, jetzt - fassung.musik_ab_s), 1)
        if treffer["name"] != song:
            return {"ergebnis": "verwechselt", "mit": treffer["name"], "nach_s": nach}
        wahr = fassung.probe_zeit(jetzt)
        if wahr is None or abs(treffer["stelle"] - wahr) > 2.0:
            return {"ergebnis": "falsche_stelle", "nach_s": nach,
                    "daneben_s": None if wahr is None else round(treffer["stelle"] - wahr, 1)}
        return {"ergebnis": "erkannt", "nach_s": nach}
    return {"ergebnis": "nicht"}


def folgen_messen(fassung: livefassung.LiveFassung, merkmale: np.ndarray, pegel: np.ndarray, teile: list,
                  abbruch: Callable[[], bool] = lambda: False,
                  fortschritt: Callable[[float], None] = lambda anteil: None) -> dict:
    """Song-Knopf eine Sekunde vor der Band, dann folgt der Song-Folger. Wann kommen die Teilwechsel?

    Gibt für jeden Teilwechsel zurück, wie weit er daneben lag (positiv: zu spät, None: kam gar nicht)."""
    folger = folgen.SongFolger(merkmale, pegel)
    grenzen = [(k, float(teil["start"]), f"{teil.get('name', 'Teil')} {teil.get('gruppe', '')}".strip())
               for k, teil in enumerate(teile) if k > 0]
    wahr = {k: fassung.live_zeit(start) for k, start, _ in grenzen}
    ueber: dict = {}
    ton = fassung.ton
    von = int(max(0.0, fassung.musik_ab_s - START_FRUEH_S) * RATE)
    letzte: Optional[float] = None
    beginn = time.perf_counter()
    folger.starten(jetzt=von / RATE)
    for a in range(von, len(ton) - BLOCK, BLOCK):
        if a % (40 * BLOCK) == 0:
            if abbruch():
                raise Abgebrochen()
            fortschritt((a - von) / max(1, len(ton) - von))
            time.sleep(0.0005)                    # die Show (Licht und Ton) kommt immer dran
        jetzt = a / RATE
        folger.hoeren(ton[a:a + BLOCK], jetzt)
        stelle = folger.takt(BLOCK / RATE, jetzt)
        if letzte is not None:
            for k, start, _ in grenzen:
                if k not in ueber and letzte < start <= stelle:
                    ueber[k] = jetzt
        letzte = stelle
    rechenzeit = time.perf_counter() - beginn
    teilwechsel = []
    for k, start, name in grenzen:
        if wahr[k] is None:
            continue                              # diese Stelle spielt die Band in der Fassung nicht
        fehler = round(ueber[k] - wahr[k], 2) if k in ueber else None
        teilwechsel.append({"teil": name, "fehler_s": fehler})
    return {"teilwechsel": teilwechsel, "rechenzeit_s": round(rechenzeit, 2),
            "musik_s": round((len(ton) - von) / RATE, 1)}


# --- Bewerten ----------------------------------------------------------------------

STUFEN = ("ok", "hinweis", "problem")


def _schlimmste(*stufen: str) -> str:
    return max(stufen, key=STUFEN.index)


def erkennung_bewerten(laeufe: list) -> dict:
    ergebnisse = [(lauf["titel"], lauf["erkennung"]) for lauf in laeufe]
    verwechselt = [e for _, e in ergebnisse if e["ergebnis"] == "verwechselt"]
    if verwechselt:
        return {"stufe": "problem",
                "text": f"Wurde für „{verwechselt[0]['mit']}“ gehalten. Beim Konzert die Song-Erkennung auf "
                        "„Vorschlagen“ stellen oder diesen Song von Hand antippen."}
    erkannt = [(titel, e) for titel, e in ergebnisse if e["ergebnis"] == "erkannt"]
    zeiten = " und ".join(f"{_sekunden(e['nach_s'])} s" for _, e in erkannt)
    if len(erkannt) == len(ergebnisse) and all(e["nach_s"] <= ERKENNEN_GUT_S for _, e in erkannt):
        return {"stufe": "ok", "text": f"Erkannt nach {zeiten}."}
    if len(erkannt) == len(ergebnisse):
        return {"stufe": "hinweis", "text": f"Erkannt, aber spät (nach {zeiten}). Bis dahin läuft das Pausenlicht oder "
                                            "die Automatik. Wer es genau will, tippt den Song von Hand an."}
    if erkannt:
        titel, e = erkannt[0]
        return {"stufe": "hinweis",
                "text": f"Nur „{titel}“ erkannt (nach {_sekunden(e['nach_s'])} s). Ist es im Saal laut, "
                        "den Song lieber von Hand antippen."}
    if any(e["ergebnis"] == "falsche_stelle" for _, e in ergebnisse):
        return {"stufe": "hinweis", "text": "Erkannt, aber an der falschen Stelle (Teile klingen sehr ähnlich). "
                                            "Den Song beim Konzert von Hand antippen, wenn die Band anfängt."}
    return {"stufe": "hinweis", "text": "Nicht erkannt. Beim Konzert den Song von Hand antippen, wenn die Band anfängt."}


def licht_bewerten(laeufe: list) -> dict:
    alle = [(lauf["titel"], w) for lauf in laeufe for w in lauf["teilwechsel"]]
    if not alle:
        return {"stufe": "ok", "text": "Der Song hat nur einen Teil: Es gibt keine Teilwechsel."}
    verpasst = [w["teil"] for _, w in alle if w["fehler_s"] is None]
    daneben = [w for _, w in alle if w["fehler_s"] is not None]
    schlimmster = max((abs(w["fehler_s"]) for w in daneben), default=0.0)
    anzahl = len(alle) // max(1, len(laeufe))
    if not verpasst and schlimmster <= GUT_S:
        return {"stufe": "ok", "text": f"Alle {anzahl} Teilwechsel pünktlich (höchstens {_sekunden(schlimmster)} s daneben)."}
    weit = [w for w in daneben if abs(w["fehler_s"]) > GUT_S]
    namen = sorted({w["teil"] for w in weit} | set(verpasst))
    teile = ", ".join(namen[:3]) + (" …" if len(namen) > 3 else "")
    if not verpasst and schlimmster <= GEHT_S:
        spaet = sum(1 for w in weit if w["fehler_s"] > 0)
        richtung = "zu spät" if spaet * 2 >= len(weit) else "zu früh"
        return {"stufe": "hinweis", "text": f"Teilwechsel bis zu {_sekunden(schlimmster)} s {richtung} ({teile}). "
                                            "Beim Konzert auf „Jetzt“ achten und notfalls „Nächster Teil jetzt“ drücken."}
    return {"stufe": "problem",
            "text": f"Das Licht kam bei {teile} viel zu spät oder gar nicht. In der Probe die Teile prüfen oder den Song "
                    "neu aufnehmen. Beim Konzert „Nächster Teil jetzt“ bereithalten."}


# --- Ablauf ------------------------------------------------------------------------

class Generalprobe:
    def __init__(self, show):
        self.show = show
        self.pfad = show.pfade.wurzel / "daten" / "generalprobe.json"
        gelesen = daten.lese_json_sicher(self.pfad, None)
        self.ergebnis: Optional[dict] = gelesen if isinstance(gelesen, dict) and gelesen.get("version") == VERSION else None
        self.laeuft = False
        self.fortschritt = 0.0
        self.schritt = ""
        self.fehler: Optional[str] = None
        self._abbrechen = False
        self._faden: Optional[threading.Thread] = None

    # --- Bedienen ---------------------------------------------------------------

    def starten(self) -> None:
        if self.laeuft:
            raise ValueError("Die Generalprobe läuft schon.")
        if self.show.song.folger is not None:
            raise ValueError("Gerade läuft ein Song. Erst „Stopp“ drücken, dann die Generalprobe starten.")
        songs = self.show.song.setlist(frisch=True)
        if not songs:
            raise ValueError("Noch keine Songs mit Probe-Aufnahme und Show. Erst in der Probe einen Song aufnehmen.")
        self.laeuft, self._abbrechen, self.fehler = True, False, None
        self.fortschritt, self.schritt = 0.0, "Startet …"
        self._faden = threading.Thread(target=self._lauf, args=(songs,), daemon=True, name="Generalprobe")
        self._faden.start()

    def abbrechen(self) -> None:
        self._abbrechen = True

    def _abbruch(self) -> bool:
        return self._abbrechen or self.show.song.folger is not None

    def zustand(self) -> dict:
        return {"laeuft": self.laeuft, "fortschritt": round(self.fortschritt, 3), "schritt": self.schritt,
                "fehler": self.fehler, "ergebnis": self.ergebnis, "veraltet": self.veraltet(),
                "dauer_schaetzung_s": self.dauer_schaetzen()}

    # --- Für den Konzert-Check ------------------------------------------------------

    def _staende(self, namen: list) -> dict:
        staende = {}
        for name in namen:
            pfad = self.show.proben.ton_pfad(name)
            sequenz = self.show.pfade.sequenzen / f"{daten.dateiname(name)}.json"
            try:
                staende[name] = max(pfad.stat().st_mtime, sequenz.stat().st_mtime if sequenz.exists() else 0.0)
            except OSError:
                staende[name] = 0.0
        return staende

    def veraltet(self) -> list:
        """Welche Songs sind neu oder haben sich seit der letzten Generalprobe geändert?"""
        if not self.ergebnis:
            return []
        alt = self.ergebnis.get("stand", {})
        jetzt = self._staende(self.show.song.setlist())
        return [name for name, stand in jetzt.items() if name not in alt or stand > alt[name] + 1.0]

    def dauer_schaetzen(self) -> float:
        """Wie lange die Generalprobe ungefähr braucht (Sekunden)."""
        musik = sum(float(s.get("dauer_s") or 0.0) for s in self.show.song.songs())
        faktor = float((self.ergebnis or {}).get("rechnen_faktor") or 6.0)
        return round(musik * len(DURCHLAEUFE) / max(1.0, faktor) * 1.3 + 5.0 * len(DURCHLAEUFE), 0)

    # --- Rechnen (eigener Faden) ------------------------------------------------------

    def _lauf(self, songs: list) -> None:
        try:
            ergebnis = self._alles(songs)
            self.ergebnis = ergebnis
            daten.schreibe_json(self.pfad, ergebnis)
            self.schritt = "Fertig."
        except Abgebrochen:
            self.fehler = ("Abgebrochen, weil ein Song gestartet wurde. Das Konzert hat Vorrang."
                           if not self._abbrechen else "Abgebrochen.")
        except Exception as fehler:                      # nie die Show stören
            logging.exception("Generalprobe")
            self.fehler = f"Die Generalprobe ist hängen geblieben: {fehler}"
        finally:
            self.laeuft = False

    def _alles(self, songs: list) -> dict:
        beginn = time.time()
        stand = self._staende(songs)
        alle_songs = {s["name"]: s for s in self.show.song.songs()}
        referenzen, folger_daten = {}, {}
        for name in alle_songs:
            merkmale, pegel = self.show.song._referenz(name)
            referenzen[name] = np.ascontiguousarray(merkmale[::erkennen.SCHRITT], np.float32)
            folger_daten[name] = (merkmale, pegel)
        ergebnisse = []
        rechenzeit = musikzeit = 0.0
        schritte = len(songs) * len(DURCHLAEUFE)
        for nummer, name in enumerate(songs):
            song = alle_songs.get(name)
            if song is None:
                continue
            analyse = self.show.proben.lesen(name) or {}
            ton = lade_datei(self.show.proben.ton_pfad(name))
            von = folgen.musik_anfang(folger_daten[name][1]) / folgen.RATE    # wie der Song-Folger den Anfang sieht
            bis = float(analyse.get("musik_bis_s") or len(ton) / RATE)
            laeufe = []
            for d, durchlauf in enumerate(DURCHLAEUFE):
                schritt = nummer * len(DURCHLAEUFE) + d
                self.schritt = f"„{name}“ {durchlauf['titel']} (Song {nummer + 1} von {len(songs)})"
                self.fortschritt = schritt / schritte
                if self._abbruch():
                    raise Abgebrochen()
                fassung = livefassung.bauen(ton, von, bis, tempo=durchlauf["tempo"], anderer_mix=True,
                                            nachhall_s=durchlauf["nachhall_s"], publikum_db=durchlauf["publikum_db"],
                                            seed=durchlauf["seed"] + nummer)
                erkennung = erkennung_messen(fassung, name, referenzen, self._abbruch, self.show.song.erkenner.weitere)

                def weiter(anteil, schritt=schritt):
                    self.fortschritt = (schritt + 0.1 + 0.9 * anteil) / schritte

                licht = folgen_messen(fassung, *folger_daten[name], song["teile"], self._abbruch, weiter)
                rechenzeit += licht["rechenzeit_s"]
                musikzeit += licht["musik_s"]
                laeufe.append({"art": durchlauf["art"], "titel": durchlauf["titel"], "text": durchlauf["text"],
                               "erkennung": erkennung, "teilwechsel": licht["teilwechsel"]})
                del fassung
            erkennung_text, licht_text = erkennung_bewerten(laeufe), licht_bewerten(laeufe)
            ergebnisse.append({"name": name, "stufe": _schlimmste(erkennung_text["stufe"], licht_text["stufe"]),
                               "erkennung": erkennung_text, "licht": licht_text, "laeufe": laeufe})
        self.fortschritt = 1.0
        faktor = round(musikzeit / rechenzeit, 1) if rechenzeit > 0 else None
        return {"version": VERSION, "zeit": datetime.datetime.now().strftime("%d.%m.%Y, %H:%M"),
                "dauer_s": round(time.time() - beginn), "songs": ergebnisse, "stand": stand,
                "rechnen_faktor": faktor, "rechner": self._rechner_text(faktor)}

    @staticmethod
    def _rechner_text(faktor: Optional[float]) -> dict:
        if faktor is None:
            return {"stufe": "ok", "text": ""}
        if faktor < LANGSAM_FAKTOR:
            return {"stufe": "hinweis",
                    "text": f"Der Laptop ist knapp: Er rechnet das Mithören nur {_sekunden(faktor)}-mal so schnell wie "
                            "die Musik. Andere Programme schließen, Netzteil anstecken."}
        return {"stufe": "ok", "text": f"Der Laptop schafft das Mithören locker ({_sekunden(faktor)}-mal so schnell wie die Musik)."}


def check_punkt(generalprobe: Generalprobe) -> Optional[tuple]:
    """Für den Konzert-Check: (Stufe, Text) oder None, wenn es keine Songs gibt."""
    if not generalprobe.show.song.songs():
        return None
    ergebnis = generalprobe.ergebnis
    if generalprobe.laeuft:
        return "hinweis", f"Die Generalprobe läuft gerade ({round(generalprobe.fortschritt * 100)} %)."
    if not ergebnis:
        minuten = max(1, round(generalprobe.dauer_schaetzen() / 60))
        return "hinweis", f"Noch keine Generalprobe gemacht. Show → Generalprobe (dauert etwa {minuten} Minuten)."
    veraltet = generalprobe.veraltet()
    if veraltet:
        return "hinweis", f"Seit der Generalprobe ist {', '.join('„' + n + '“' for n in veraltet[:3])} neu oder geändert. Nochmal laufen lassen."
    songs = ergebnis.get("songs", [])
    rot = [s["name"] for s in songs if s["stufe"] == "problem"]
    gelb = [s["name"] for s in songs if s["stufe"] == "hinweis"]
    if rot:
        return "problem", f"Generalprobe ({ergebnis['zeit']}): bei {', '.join(rot)} gab es Probleme. Show → Generalprobe ansehen."
    if gelb:
        return "hinweis", f"Generalprobe ({ergebnis['zeit']}): {', '.join(gelb)} unsicher. Show → Generalprobe ansehen."
    return "ok", f"Generalprobe ({ergebnis['zeit']}): alle {len(songs)} Songs gut."
