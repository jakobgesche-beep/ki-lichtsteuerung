"""Die Musik-Engine: Regeln, die aus Messwerten Licht machen.

    Beat          -> Farbschritt der PARs, Lichtpuls, abwechselnde Akzente
    Bass          -> Helligkeit
    Energie       -> Größe der Bewegung der Moving Heads
    alle 2 Beats  -> neue Farbe der Spots, alle 4 ein neues Gobo
    alle 8 Beats  -> neues Bewegungsmuster
    leise / Rede  -> ruhiges Grundlicht

Alles läuft weich: Farben blenden, Winkel werden geglättet, der Puls klingt aus.

Wie stark jede Regel wirkt, sagt das Profil. Die Engine spricht nur die Gruppen
"Farb-PARs" und "Spots" an. Ein anderes Modell in der Gruppe ändert hier nichts.
Sie läuft komplett lokal und braucht kein Internet.
"""
from __future__ import annotations

import math
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
FARB_BLENDE_S = 0.12     # Überblendung der LED-Farben
WINKEL_GLAETTUNG_S = 0.12 # so weich laufen Pan und Tilt
MAX_GRAD_PRO_S = 240     # schneller folgt auch ein echter Kopf nicht sauber
BEATS_VOLL = 8           # ein Bewegungs-Durchlauf bei Bewegung "voll"
BEATS_LANGSAM = 32
BEATS_PRO_MUSTER = 8
STROBO_ENERGIE = 0.92
STROBO_NACH_S = 2.0
ERSATZ_HELLIGKEIT = 0.5
UEBERGANG_S = 1.5        # so lange dauert der Wechsel zwischen Musik und Grundlicht
ZIEL_HOEHE_M = 0.8       # die Spots wandern über den Bühnenboden


class Engine:
    def __init__(self, patch, buehne, positionen: dict, grenzen):
        self.patch = patch
        self.buehne = buehne
        self.positionen = positionen
        self.grenzen = grenzen
        self.farb_schritt = 0
        self.beats = 0
        self.letzter_schritt = -99.0
        self.letzter_beat = -99.0
        self.phase = 0.0
        self.tanz = 0.0
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
            self.zustand_text = "Musik"

    def _beat_schritt(self, messwerte: Messwerte, reaktion: float, tempo: float, jetzt: float) -> None:
        """Ein Farbschritt pro Beat, aber nicht schneller, als es die Grenze erlaubt."""
        # Viel Energie heißt doppeltes Tempo. Die Phase läuft dabei ohne Sprung weiter.
        self.phase += self.dauer * tempo / 60.0 * (1.0 + messwerte.energie)
        if not messwerte.beat:
            return
        self.beats += 1
        self.letzter_beat = jetzt
        if reaktion < 0.3:
            return           # Bei wenig Reaktion bleiben die Farben fest.
        alle = 1 if reaktion >= 0.7 else 2
        kleinster_abstand = 1.0 / max(self.grenzen.strobo_max_hz, 0.5)
        if self.beats % alle == 0 and jetzt - self.letzter_schritt >= kleinster_abstand:
            self.farb_schritt += 1
            self.letzter_schritt = jetzt

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

    def _musik(self, m: Messwerte, profil: dict, jetzt: float) -> dict:
        reaktion = profil["beat_reaktion"]
        palette = [lies_farbe(f) for f in profil["palette"]]
        grenze = profil["max_helligkeit"]
        tempo = m.tempo_bpm if 40.0 <= m.tempo_bpm <= 240.0 else STANDARD_TEMPO
        periode = 60.0 / tempo
        self._beat_schritt(m, reaktion, tempo, jetzt)
        # Der Puls springt auf dem Beat hoch und klingt weich aus.
        puls = math.exp(-(jetzt - self.letzter_beat) / (PULS_ABKLANG * periode))
        self.tanz = puls if profil["bewegung"] == "voll" else 0.0
        ergebnis = {}

        pars = self.patch.in_gruppe(GRUPPE_FARBE)
        tiefe = 0.7 * reaktion
        for nummer, geraet in enumerate(pars):
            akzent = puls if reaktion < 0.7 or self.beats % len(pars) == nummer else 0.3 * puls
            hell = grenze * ((1.0 - tiefe) + tiefe * max(m.bass, akzent))
            ziel = palette[(self.farb_schritt + nummer) % len(palette)]
            ergebnis[geraet["id"]] = Eigenschaften(helligkeit=hell, farbe=self._weiche_farbe(geraet["id"], ziel))

        strobo = self._strobo_hz(m, profil, jetzt)
        spots = self.patch.in_gruppe(GRUPPE_BEWEGUNG)
        for nummer, geraet in enumerate(spots):
            # Die Lampen wechseln sich auf dem Beat ab, das wirkt auch mit nur zweien lebendig.
            akzent = puls if self.beats % len(spots) == nummer else 0.35 * puls
            farb_nummer = nummer if reaktion < 0.3 else self.beats // 2 + nummer
            tiefe_spot = 0.3 + 0.5 * reaktion        # tiefere Pulse, je stärker das Profil reagiert
            pegel = max(akzent, 0.5 * m.bass, 0.6 * m.energie)
            e = Eigenschaften(helligkeit=grenze * ((1.0 - tiefe_spot) + tiefe_spot * pegel),
                              farbe=palette[farb_nummer % len(palette)],
                              strobo_hz=strobo if "Effektlicht" in self.patch.gruppen_von(geraet) else 0.0)
            gobos = self._gobos(geraet)
            if gobos and reaktion >= 0.5:
                e.gobo = gobos[(self.beats // 4 + nummer) % len(gobos)]
                seite = 1 if nummer % 2 == 0 else -1
                e.gobo_drehung = seite * (0.25 + 0.45 * m.energie)
            if profil["bewegung"] != "aus":
                self._bewegen(geraet, nummer, profil["bewegung"], m.energie, e)
            elif geraet["id"] in self.winkel:
                e.pan, e.tilt = self.winkel[geraet["id"]]
            else:
                self._ruhelage(geraet, e)
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

    def _muster(self, nummer: int, zyklus: float, weite: float) -> tuple:
        """Das aktuelle Bewegungsmuster: ein Punkt auf dem Bühnenboden. Nie im Publikum."""
        masse = self.buehne.daten["buehne"]
        breite, tiefe = masse["breite_m"], masse["tiefe_m"]
        winkel = 2 * math.pi * self.phase / zyklus
        seite = 1 if nummer % 2 == 0 else -1
        versatz = nummer * math.pi
        muster = (self.beats // BEATS_PRO_MUSTER) % 4
        if muster == 0:      # Fächer: gespiegelt auf und zu
            return (seite * breite * weite * (0.1 + 0.15 * (1 + math.sin(winkel))),
                    tiefe * 0.5)
        if muster == 1:      # Kreise, die sich gegenüberliegen
            return (0.3 * breite * weite * math.cos(winkel + versatz),
                    tiefe * (0.5 + 0.3 * weite * math.sin(winkel + versatz)))
        if muster == 2:      # Kreuz: die Strahlen tauschen die Seiten
            return (seite * 0.38 * breite * weite * math.sin(winkel),
                    tiefe * (0.5 + 0.25 * math.sin(2 * winkel)))
        return (0.4 * breite * weite * math.sin(winkel + versatz / 2),   # Welle: laufen nacheinander
                tiefe * (0.5 + 0.25 * math.cos(winkel)))

    def _bewegen(self, geraet: dict, nummer: int, bewegung: str, energie: float, e: Eigenschaften) -> None:
        """Die Spots folgen dem Muster im Takt. Die Winkel werden geglättet."""
        if bereiche_von(self.patch, geraet) is None:
            return
        zyklus = BEATS_LANGSAM if bewegung == "langsam" else BEATS_VOLL
        x, y = self._muster(nummer, zyklus, 0.45 + 0.55 * energie)
        y += self.tanz * self.buehne.daten["buehne"]["tiefe_m"] * 0.12    # kleiner Schub auf dem Beat
        alt = self.winkel.get(geraet["id"])
        try:
            pan, tilt = zeige_auf(geraet, (x, y, ZIEL_HOEHE_M), self.patch, self.buehne, alt)
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
