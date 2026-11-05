"""Die Musik-Engine: macht aus der Musik ein Licht, wie es ein Operator fahren würde.

Sie arbeitet mit Looks. Ein Look ist ein festes Bild: Farbe, Gobo, Stand oder
Bewegung und eine Art, im Beat zu pulsieren. So entsteht Ruhe statt Dauerwechsel:

    Ein Look bleibt mindestens eine Phrase stehen (16 Beats).
    Er wechselt, wenn die Musik stärker oder ruhiger wird, oder nach 32 Beats.
    Ein Drop (plötzlich viel mehr Energie) wechselt sofort, mit einem Akzent.
    Leise Stellen und Rede gehen auf das ruhige Grundlicht.

Was im Look passiert:
    Puls       Dimmer geht im Beat auf und zu. Beim Akzent kurz doppelt hell.
    Farbe      bleibt stehen, oder zwei Farben wechseln sich alle 4 Beats ab.
    Bewegung   nur in manchen Looks, dann langsam und weich. Sonst steht das Licht.

Wie stark alles wirkt, sagt das Profil. Die Engine spricht nur die Gruppen
"Farb-PARs" und "Spots" an. Sie läuft komplett lokal und braucht kein Internet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .farben import farbe as lies_farbe
from .audio.analyse import Messwerte
from .pantilt import ZielAusserhalb
from .render import Eigenschaften, mischen
from .szenen import bereiche_von, loese_auf, zeige_auf

GRUPPE_FARBE = "Farb-PARs"
GRUPPE_BEWEGUNG = "Spots"
STANDARD_TEMPO = 120.0
PULS_ABKLANG = 0.45      # wie schnell der Lichtpuls ausklingt, in Beats
AKZENT_ABKLANG = 1.2     # der Akzent ("doppelt hell") klingt langsamer aus
FARB_BLENDE_S = 0.25     # Überblendung der LED-Farben
WINKEL_GLAETTUNG_S = 0.35 # so weich laufen Pan und Tilt, auch beim Look-Wechsel
MAX_GRAD_PRO_S = 180     # schneller folgt auch ein echter Kopf nicht sauber
PHRASE = 16              # so viele Beats bleibt ein Look mindestens stehen
ABWECHSLUNG = 32         # spätestens dann kommt ein neuer Look derselben Stärke
BEATS_BEWEGUNG = 16      # ein Bewegungs-Durchlauf, bei "langsam" doppelt so lang
STUFEN = (0.35, 0.6, 0.8) # Energie-Grenzen zwischen ruhig, mittel, stark, Höhepunkt
HYSTERESE = 0.08         # damit es an einer Grenze nicht hin und her springt
DROP = 0.25              # so viel Energie mehr als zuletzt gilt als Drop
STROBO_ENERGIE = 0.92
STROBO_NACH_S = 2.0
ERSATZ_HELLIGKEIT = 0.5
UEBERGANG_S = 1.5        # so lange dauert der Wechsel zwischen Musik und Grundlicht
ZIEL_HOEHE_M = 0.8       # die Spots zielen auf den Bühnenboden


@dataclass(frozen=True)
class Look:
    name: str
    stufe: int                       # 0 ruhig, 1 mittel, 2 stark, 3 Höhepunkt
    bewegung: Optional[str] = None   # None: das Licht steht
    farben: str = "eine"             # eine, zwei (fest verteilt), wechsel (alle 4 Beats)
    gobo: bool = False
    drehung: float = 0.0
    puls: str = "beat"               # atmen, beat, akzent (Takt-Eins doppelt hell)


LOOKS = (
    Look("Ruhe", 0, puls="atmen"),
    Look("Ruhe mit Gobo", 0, puls="atmen", gobo=True),
    Look("Stehen", 1, gobo=True),
    Look("Farbwechsel", 1, farben="wechsel"),
    Look("Zwei Farben", 1, farben="zwei", gobo=True, drehung=0.2),
    Look("Schwenk", 2, bewegung="schwenk", gobo=True),
    Look("Kreuz", 2, bewegung="kreuz", farben="zwei", gobo=True, drehung=0.3),
    Look("Stehen mit Akzent", 2, farben="wechsel", puls="akzent"),
    Look("Kreis", 3, bewegung="kreis", farben="wechsel", gobo=True, drehung=0.5, puls="akzent"),
    Look("Fächer", 3, bewegung="faecher", farben="zwei", gobo=True, drehung=0.6, puls="akzent"),
    Look("Höhepunkt stehend", 3, farben="wechsel", gobo=True, puls="akzent"),
)


class Engine:
    def __init__(self, patch, buehne, positionen: dict, grenzen):
        self.patch = patch
        self.buehne = buehne
        self.positionen = positionen
        self.grenzen = grenzen
        self.beats = 0
        self.letzter_beat = -99.0
        self.letzter_akzent = -99.0
        self.phase = 0.0                # zählt Beats weich mit, für die Bewegung
        self.stufe = 0
        self.energie_langsam = 0.0
        self.look = LOOKS[0]
        self.look_seit = 0              # bei welchem Beat der Look begann
        self.look_nummer = 0            # zählt Looks, daraus kommen Farben und Gobos
        self.dauer = 0.0
        self.led_farbe = {}
        self.gobo_listen = {}
        self.musik_anteil = 0.0     # 0 = Grundlicht, 1 = volle Musik-Regeln
        self.letzte_zeit: Optional[float] = None
        self.laut_seit: Optional[float] = None
        self.winkel = {}
        self.grund_kopie = {}
        self.zustand_text = "Grundlicht"

    def bewerte(self, messwerte: Optional[Messwerte], profil: dict, jetzt: float,
                pause: bool = False) -> dict:
        """Das Ergebnis pro Bild: {Geräte-id: Eigenschaften}."""
        dauer = 0.0 if self.letzte_zeit is None else jetzt - self.letzte_zeit
        self.letzte_zeit = jetzt
        self.dauer = dauer

        grund, _ = loese_auf(profil["grundlicht"]["werte"], self.patch, self.buehne, self.positionen)
        if not any(e.helligkeit > 0 for e in grund.values()):
            grund = self._ersatz_grundlicht()
        grund = {i: e.kopie(helligkeit=min(e.helligkeit, profil["max_helligkeit"])) for i, e in grund.items()}

        if messwerte is not None:
            tempo = messwerte.tempo_bpm if 40.0 <= messwerte.tempo_bpm <= 240.0 else STANDARD_TEMPO
            self.phase += dauer * tempo / 60.0
            if messwerte.beat:
                self.beats += 1
                self.letzter_beat = jetzt
        ruhig = (messwerte is None or pause or profil["beat_reaktion"] <= 0
                 or messwerte.leise or messwerte.rede)
        self._text_setzen(messwerte, pause, profil)
        schritt = dauer / UEBERGANG_S
        self.musik_anteil = max(0.0, min(1.0, self.musik_anteil + (-schritt if ruhig else schritt)))
        # Fällt die Analyse aus, soll das nicht mitten im Blitz stehen bleiben.
        if self.musik_anteil <= 0.0 or messwerte is None:
            self.musik_anteil = 0.0 if messwerte is None else self.musik_anteil
            return grund

        musik = self._musik(messwerte, profil, jetzt)
        ergebnis = dict(grund)
        for geraet_id, eigenschaften in musik.items():
            ausgang = grund.get(geraet_id, Eigenschaften(farbe=eigenschaften.farbe,
                                                         pan=eigenschaften.pan, tilt=eigenschaften.tilt))
            ergebnis[geraet_id] = mischen(ausgang, eigenschaften, self.musik_anteil)
        return ergebnis

    def _ersatz_grundlicht(self) -> dict:
        """Passt das Grundlicht zu keinem gepatchten Gerät, darf die Bühne nicht dunkel bleiben."""
        warm = lies_farbe("warmweiss")
        ergebnis = {}
        for geraet in self.patch.geraete:
            e = Eigenschaften(helligkeit=ERSATZ_HELLIGKEIT, farbe=warm)
            self._ruhelage(geraet, e)
            ergebnis[geraet["id"]] = e
        return ergebnis

    def _text_setzen(self, messwerte, pause, profil) -> None:
        if pause:
            self.zustand_text = "Automatik pausiert: Grundlicht"
        elif messwerte is None:
            self.zustand_text = "Kein Ton: Grundlicht"
        elif profil["beat_reaktion"] <= 0:
            self.zustand_text = "Profil ohne Automatik: Grundlicht"
        elif messwerte.leise:
            self.zustand_text = "Leise Stelle: Grundlicht"
        elif messwerte.rede:
            self.zustand_text = "Rede erkannt: Grundlicht"
        else:
            self.zustand_text = f"Musik: {self.look.name}"

    # --- Looks wählen --------------------------------------------------------

    def _stufe(self, energie: float) -> int:
        """Energie in vier Stufen, mit etwas Abstand, damit es nicht flattert."""
        stufe = self.stufe
        while stufe < 3 and energie > STUFEN[stufe] + HYSTERESE / 2:
            stufe += 1
        while stufe > 0 and energie < STUFEN[stufe - 1] - HYSTERESE / 2:
            stufe -= 1
        return stufe

    def _passende_looks(self, stufe: int, profil: dict) -> list:
        reaktion = profil["beat_reaktion"]
        if reaktion < 0.3:
            stufe = min(stufe, 1)       # ruhige Profile bleiben ruhig
        looks = [l for l in LOOKS if l.stufe == stufe]
        if profil["bewegung"] == "aus":
            looks = [l for l in looks if l.bewegung is None] or [l for l in LOOKS if l.bewegung is None and l.stufe <= stufe]
        if reaktion < 0.3:
            looks = [l for l in looks if l.farben == "eine"] or [LOOKS[0]]
        return looks

    def _look_waehlen(self, m: Messwerte, profil: dict, jetzt: float) -> None:
        """Nur am Ende einer Phrase wechseln, außer bei einem Drop."""
        stufe = self._stufe(m.energie)
        if self.look_nummer == 0:
            self.energie_langsam = m.energie
        # Ein Drop: von ruhig oder mittel plötzlich auf Höhepunkt, deutlich über dem Schnitt.
        drop = (stufe == 3 and self.stufe <= 1 and m.energie - self.energie_langsam > DROP)
        self.energie_langsam += (m.energie - self.energie_langsam) * min(1.0, self.dauer / 8.0)
        seit = self.beats - self.look_seit
        phrase_um = m.beat and seit >= PHRASE and seit % 8 == 0
        # Passt der Look gar nicht (zwei Stufen daneben), wartet er nur bis zum nächsten Takt.
        weit_daneben = abs(stufe - self.look.stufe) >= 2 and m.beat and seit % 4 == 0
        erster = self.look_nummer == 0          # beim ersten Ton gleich den passenden Look nehmen
        wechseln = erster or (drop and seit >= 4) or weit_daneben or (
            phrase_um and (stufe != self.stufe or seit >= ABWECHSLUNG))
        self.stufe = stufe if (wechseln or seit < 1) else self.stufe
        if not wechseln and self.look in self._passende_looks(self.look.stufe, profil):
            return
        looks = self._passende_looks(stufe, profil)
        andere = [l for l in looks if l != self.look] or looks
        self.look = andere[self.look_nummer % len(andere)]
        self.look_nummer += 1
        self.look_seit = self.beats
        self.stufe = stufe
        if drop or stufe >= 2:
            self.letzter_akzent = jetzt     # der neue Look kommt mit einem hellen Akzent

    # --- Ein Bild ------------------------------------------------------------

    def _weiche_farbe(self, geraet_id: str, ziel) -> tuple:
        """LED-Farben wechseln nicht hart, sondern blenden kurz über."""
        alt = self.led_farbe.get(geraet_id, ziel)
        anteil = min(1.0, self.dauer / FARB_BLENDE_S)
        farbe = tuple(a + (z - a) * anteil for a, z in zip(alt, ziel))
        self.led_farbe[geraet_id] = farbe
        return farbe

    def _gobos(self, geraet: dict) -> list:
        """Welche Gobos hat dieses Gerät? Steht im Katalog, nicht im Programm."""
        if geraet["id"] not in self.gobo_listen:
            namen = []
            for _, kanal in self.patch.typ(geraet).kanaele_im_modus(geraet["modus"]):
                if kanal["typ"] == "gobo":
                    namen += [b["name"] for b in kanal.get("bereiche", [])
                              if b["typ"] == "platz" and b.get("name") != "Offen"]
            self.gobo_listen[geraet["id"]] = namen
        return self.gobo_listen[geraet["id"]]

    def _farbe(self, palette: list, nummer: int) -> tuple:
        """Die Farbe eines Geräts im aktuellen Look."""
        a = palette[self.look_nummer % len(palette)]
        b = palette[(self.look_nummer + 1) % len(palette)]
        if self.look.farben == "eine":
            return a
        if self.look.farben == "zwei":
            return a if nummer % 2 == 0 else b
        # Wechsel: alle 4 Beats tauschen die Geräte ihre Farben.
        return a if (self.beats // 4 + nummer) % 2 == 0 else b

    def _helligkeit(self, m: Messwerte, grenze: float, reaktion: float, nummer: int, anzahl: int,
                    jetzt: float, periode: float) -> float:
        """Grundhelligkeit, darauf der Puls im Beat und ab und zu ein Akzent."""
        look = self.look
        if look.puls == "atmen":
            return grenze * (0.6 + 0.2 * math.sin(2 * math.pi * self.phase / 8))
        puls = math.exp(-(jetzt - self.letzter_beat) / (PULS_ABKLANG * periode))
        # Die Lampen wechseln sich auf dem Beat ab, das wirkt auch mit nur zweien lebendig.
        if anzahl > 1 and self.beats % anzahl != nummer % anzahl:
            puls *= 0.35
        grund = 1.0 - (0.3 + 0.4 * reaktion)        # so tief geht der Dimmer zwischen den Beats
        hell = grund + (1.0 - grund) * max(puls, 0.5 * m.bass)
        if look.puls == "akzent" and self.beats % 4 == 0:
            # Auf der Eins im Takt: alle zusammen voll, und langsamer wieder runter.
            hell = max(hell, math.exp(-(jetzt - self.letzter_beat) / (AKZENT_ABKLANG * periode)))
        # Beim Wechsel in einen starken Look: kurz doppelt hell.
        hell = max(hell, math.exp(-(jetzt - self.letzter_akzent) / (AKZENT_ABKLANG * periode)))
        return grenze * min(1.0, hell)

    def _musik(self, m: Messwerte, profil: dict, jetzt: float) -> dict:
        reaktion = profil["beat_reaktion"]
        palette = [lies_farbe(f) for f in profil["palette"]]
        grenze = profil["max_helligkeit"]
        tempo = m.tempo_bpm if 40.0 <= m.tempo_bpm <= 240.0 else STANDARD_TEMPO
        periode = 60.0 / tempo
        self._look_waehlen(m, profil, jetzt)
        ergebnis = {}

        pars = self.patch.in_gruppe(GRUPPE_FARBE)
        for nummer, geraet in enumerate(pars):
            hell = self._helligkeit(m, grenze, reaktion, nummer, len(pars), jetzt, periode)
            ziel = self._farbe(palette, nummer + 1)
            ergebnis[geraet["id"]] = Eigenschaften(helligkeit=hell, farbe=self._weiche_farbe(geraet["id"], ziel))

        strobo = self._strobo_hz(m, profil, jetzt)
        spots = self.patch.in_gruppe(GRUPPE_BEWEGUNG)
        for nummer, geraet in enumerate(spots):
            e = Eigenschaften(helligkeit=self._helligkeit(m, grenze, reaktion, nummer, len(spots), jetzt, periode),
                              farbe=self._farbe(palette, nummer),
                              strobo_hz=strobo if "Effektlicht" in self.patch.gruppen_von(geraet) else 0.0)
            gobos = self._gobos(geraet)
            if gobos and self.look.gobo and reaktion >= 0.3:
                e.gobo = gobos[self.look_nummer % len(gobos)]
                seite = 1 if nummer % 2 == 0 else -1
                e.gobo_drehung = seite * self.look.drehung if reaktion >= 0.5 and self.look.drehung else None
            elif gobos:
                e.gobo = "Offen"
            if self.look.bewegung and profil["bewegung"] != "aus":
                self._bewegen(geraet, nummer, profil["bewegung"], m.energie, e)
            else:
                self._stehen(geraet, nummer, len(spots), e)
            ergebnis[geraet["id"]] = e
        return ergebnis

    def _ruhelage(self, geraet: dict, e: Eigenschaften) -> None:
        """Ohne Bewegung zeigen Spots auf die Bühnenmitte, nicht einfach nach oben."""
        if bereiche_von(self.patch, geraet) is None:
            return
        masse = self.buehne.daten["buehne"]
        try:
            e.pan, e.tilt = zeige_auf(geraet, (0.0, masse["tiefe_m"] / 2, ZIEL_HOEHE_M),
                                      self.patch, self.buehne)
        except ZielAusserhalb:
            pass

    def _stehen(self, geraet: dict, nummer: int, anzahl: int, e: Eigenschaften) -> None:
        """Licht steht: Die Spots zeigen ruhig auf feste Punkte und gleiten nur dorthin."""
        masse = self.buehne.daten["buehne"]
        if anzahl > 1:
            # Zwei Spots: gespiegelt, je nach Look enger oder weiter
            weite = (0.15, 0.25, 0.1)[self.look_nummer % 3] * masse["breite_m"]
            x = -weite + 2 * weite * nummer / (anzahl - 1)
        else:
            x = 0.0
        self._zielen(geraet, (x, masse["tiefe_m"] / 2, ZIEL_HOEHE_M), e)

    def _muster(self, nummer: int, zyklus: float, weite: float, muster: Optional[str] = None) -> tuple:
        """Ein Punkt der Bewegung auf dem Bühnenboden. Nie im Publikum."""
        masse = self.buehne.daten["buehne"]
        breite, tiefe = masse["breite_m"], masse["tiefe_m"]
        winkel = 2 * math.pi * self.phase / zyklus
        seite = 1 if nummer % 2 == 0 else -1
        versatz = nummer * math.pi
        muster = muster or self.look.bewegung or "schwenk"
        if muster == "faecher":      # gespiegelt auf und zu
            return (seite * breite * weite * (0.1 + 0.15 * (1 + math.sin(winkel))), tiefe * 0.5)
        if muster == "kreis":        # Kreise, die sich gegenüberliegen
            return (0.3 * breite * weite * math.cos(winkel + versatz),
                    tiefe * (0.5 + 0.3 * weite * math.sin(winkel + versatz)))
        if muster == "kreuz":        # die Strahlen tauschen langsam die Seiten
            return (seite * 0.38 * breite * weite * math.sin(winkel), tiefe * 0.5)
        return (0.35 * breite * weite * math.sin(winkel + versatz / 2), tiefe * 0.5)   # Schwenk

    def _bewegen(self, geraet: dict, nummer: int, bewegung: str, energie: float, e: Eigenschaften) -> None:
        """Die Spots folgen dem Muster des Looks, langsam und geglättet."""
        zyklus = BEATS_BEWEGUNG * (2 if bewegung == "langsam" else 1)
        x, y = self._muster(nummer, zyklus, 0.6 + 0.4 * energie)
        self._zielen(geraet, (x, y, ZIEL_HOEHE_M), e)

    def _zielen(self, geraet: dict, ziel: tuple, e: Eigenschaften) -> None:
        """Gleitet weich zum Ziel. Gleiche Rechnung für Stehen und Bewegung."""
        if bereiche_von(self.patch, geraet) is None:
            return
        alt = self.winkel.get(geraet["id"])
        try:
            pan, tilt = zeige_auf(geraet, ziel, self.patch, self.buehne, alt)
        except ZielAusserhalb:
            if alt:
                e.pan, e.tilt = alt
            return
        if alt:
            anteil = min(1.0, self.dauer / WINKEL_GLAETTUNG_S)
            schritt = MAX_GRAD_PRO_S * self.dauer
            begrenze = lambda d: max(-schritt, min(schritt, d * anteil))
            pan, tilt = alt[0] + begrenze(pan - alt[0]), alt[1] + begrenze(tilt - alt[1])
        e.pan, e.tilt = pan, tilt
        self.winkel[geraet["id"]] = (pan, tilt)

    def _strobo_hz(self, m: Messwerte, profil: dict, jetzt: float) -> float:
        """Strobo nur, wenn das Profil es erlaubt und die Energie lange sehr hoch ist."""
        if profil["strobo"] == "aus" or m.energie < STROBO_ENERGIE:
            self.laut_seit = None
            return 0.0
        if self.laut_seit is None:
            self.laut_seit = jetzt
        if jetzt - self.laut_seit < STROBO_NACH_S:
            return 0.0
        return min(profil["strobo"]["max_blitze_pro_sekunde"], self.grenzen.strobo_max_hz)
