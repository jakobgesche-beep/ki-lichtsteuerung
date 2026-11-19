"""Testmusik mit bekannten Beats und Takt-Einsen, zum Messen der Erkennung (kein Teil des Programms).

    song("rock", 120, takte=32)  ->  (Ton, {"beats": [...], "einsen": [...], "tempo": 120, "teile": [...]})

Stile: rock, pop, punk, shuffle (Achtel im Swing: provoziert falsche Tempi), ballade (erst ohne Schlagzeug),
edm (Bassdrum auf jedem Viertel), akustik (nur geschlagene Akkorde, ohne Schlagzeug),
sechsachtel (12/8: jeder Schlag in drei Achtel geteilt, wie viele langsame Balladen).
Mit drift=0.03 wird die Band im Lauf des Songs um bis zu 3 % schneller und wieder langsamer (wie live).
"""
from __future__ import annotations

import numpy as np

RATE = 44100
DUR = [0, 2, 4, 5, 7, 9, 11]
FOLGEN = [[0, 4, 5, 3], [0, 5, 3, 4], [5, 3, 0, 4], [0, 3, 4, 4], [1, 4, 0, 0], [0, 0, 3, 4]]


def _akkord(stufe: int, grundton: float) -> list:
    return [grundton * 2 ** ((DUR[(stufe + i) % 7] + 12 * ((stufe + i) // 7)) / 12) for i in (0, 2, 4)]


def _ton(freqs, dauer, laut, rng, obertoene=4, abkling=2.5) -> np.ndarray:
    t = np.arange(int(dauer * RATE)) / RATE
    x = np.zeros(len(t))
    for f in freqs:
        for o in range(1, obertoene + 1):
            x += np.sin(2 * np.pi * f * o * t + rng.uniform(0, 6)) / o ** 1.3
    return laut * x * np.exp(-t * abkling) / max(1, len(freqs))


def _kick(rng) -> np.ndarray:
    t = np.arange(int(0.25 * RATE)) / RATE
    f = 45 + 80 * np.exp(-t * 30)
    return 0.9 * np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-t * 9)


def _snare(rng) -> np.ndarray:
    t = np.arange(int(0.2 * RATE)) / RATE
    return (0.45 * rng.standard_normal(len(t)) * np.exp(-t * 22) + 0.25 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30))


def _hihat(rng, laut=0.08) -> np.ndarray:
    t = np.arange(int(0.06 * RATE)) / RATE
    rauschen = rng.standard_normal(len(t))
    return laut * np.diff(np.concatenate([[0], rauschen])) * np.exp(-t * 70)


def _einfuegen(ziel: np.ndarray, klang: np.ndarray, start: float) -> None:
    a = int(start * RATE)
    if a >= len(ziel):
        return
    b = min(len(ziel), a + len(klang))
    ziel[a:b] += klang[: b - a]


def song(stil: str = "rock", tempo: float = 120.0, takte: int = 32, seed: int = 1, drift: float = 0.0,
         vorlauf_s: float = 1.0) -> tuple:
    rng = np.random.default_rng(seed)
    grundton = 98.0 * 2 ** (int(rng.integers(0, 12)) / 12)
    folge_a, folge_b = (FOLGEN[i] for i in rng.choice(len(FOLGEN), 2, replace=False))
    # Beat-Zeiten (mit Drift: langsames Schneller- und Langsamerwerden)
    anzahl = takte * 4
    beats, t = [], vorlauf_s
    for k in range(anzahl + 1):
        beats.append(t)
        faktor = 1.0 + drift * np.sin(2 * np.pi * k / max(1, anzahl))
        t += 60.0 / (tempo * faktor)
    dauer = beats[-1] + 2.0
    ton = np.zeros(int(dauer * RATE))
    teile = []
    for takt in range(takte):
        teil = (takt // 8) % 4                      # 8 Takte A, 8 Takte B, ...
        if takt % 8 == 0:
            teile.append({"start": beats[takt * 4], "name": "Strophe" if teil % 2 == 0 else "Refrain"})
        folge = folge_a if teil % 2 == 0 else folge_b
        laut = 0.7 if teil % 2 == 0 else 1.0
        akkord = _akkord(folge[takt % len(folge)], grundton)
        ohne_schlagzeug = stil == "akustik" or (stil == "ballade" and takt < 8)
        for schlag in range(4):
            b = beats[takt * 4 + schlag]
            periode = beats[takt * 4 + schlag + 1] - b
            if stil == "sechsachtel":
                # 12/8: jeder Schlag in drei Achtel geteilt (Triolen-Gefühl), Arpeggio auf jedem Achtel
                if schlag == 0:
                    _einfuegen(ton, _ton(akkord, 4 * periode, 0.2 * laut, rng, abkling=0.8), b)
                for achtel in range(3):
                    note = akkord[(schlag * 3 + achtel) % 3] * 2
                    _einfuegen(ton, _ton([note], periode / 3, (0.16 if achtel == 0 else 0.11) * laut, rng, abkling=5.0),
                               b + achtel * periode / 3)
                    _einfuegen(ton, _hihat(rng, 0.07 if achtel == 0 else 0.045), b + achtel * periode / 3)
                _einfuegen(ton, _ton([akkord[0] / 2], periode, 0.3 * laut, rng, obertoene=2, abkling=4.0), b)
                if schlag == 0:
                    _einfuegen(ton, _kick(rng), b)
                elif schlag == 1:
                    _einfuegen(ton, _kick(rng) * 0.6, b + 2 * periode / 3)
                elif schlag == 2:
                    _einfuegen(ton, _snare(rng), b)
                continue
            if stil in ("akustik", "ballade"):
                # geschlagene Akkorde: auf jedem Viertel, die Eins etwas stärker
                _einfuegen(ton, _ton(akkord, periode, (0.35 if schlag == 0 else 0.22) * laut, rng, abkling=3.0), b)
            elif schlag in (0, 2) or stil == "punk":
                _einfuegen(ton, _ton(akkord, 2 * periode if stil != "punk" else periode, 0.25 * laut, rng, abkling=1.2), b)
            _einfuegen(ton, _ton([akkord[0] / 2], periode, 0.3 * laut, rng, obertoene=2, abkling=4.0), b)   # Bass
            if ohne_schlagzeug:
                continue
            if stil == "edm":
                _einfuegen(ton, _kick(rng), b)
                _einfuegen(ton, _hihat(rng, 0.12), b + periode / 2)
                if schlag in (1, 3):
                    _einfuegen(ton, _snare(rng) * 0.6, b)
                continue
            if stil == "punk":
                _einfuegen(ton, _kick(rng) if schlag % 2 == 0 else _snare(rng), b)
                _einfuegen(ton, _kick(rng) * 0.7, b + periode / 2)
                _einfuegen(ton, _hihat(rng, 0.1), b)
                _einfuegen(ton, _hihat(rng, 0.1), b + periode / 2)
                continue
            if schlag in (0, 2):
                _einfuegen(ton, _kick(rng), b)
            else:
                _einfuegen(ton, _snare(rng), b)
            if stil == "pop" and schlag == 2:
                _einfuegen(ton, _kick(rng) * 0.6, b + periode / 2)
            if stil == "shuffle":
                _einfuegen(ton, _hihat(rng), b)
                _einfuegen(ton, _hihat(rng, 0.06), b + periode * 2 / 3)       # Swing-Achtel
                if schlag in (1, 3):
                    _einfuegen(ton, _kick(rng) * 0.5, b + periode * 2 / 3)     # punktierte Bassdrum
            else:
                _einfuegen(ton, _hihat(rng), b)
                _einfuegen(ton, _hihat(rng, 0.06), b + periode / 2)
    ton = ton / (np.max(np.abs(ton)) + 1e-9) * 0.8
    wahr = {"beats": [round(b, 4) for b in beats[:anzahl]], "einsen": [round(b, 4) for b in beats[:anzahl:4]],
            "tempo": tempo, "teile": teile}
    return ton.astype(np.float32), wahr


STILE = ("rock", "pop", "punk", "shuffle", "ballade", "edm", "akustik", "sechsachtel")


# --- Songs mit Form: Teile, die sich anhören wie echte Strophen und Refrains --------------------

FORM_POP = [("Intro", 4, "leer"), ("Strophe", 8, "strophe"), ("Überleitung", 4, "vor"), ("Refrain", 8, "refrain"),
            ("Strophe", 8, "strophe"), ("Überleitung", 4, "vor"), ("Refrain", 8, "refrain"), ("Bridge", 8, "bridge"),
            ("Refrain", 8, "refrain"), ("Schluss", 4, "leer")]


def song_mit_form(tempo: float = 120.0, form: list = None, seed: int = 1, vorlauf_s: float = 1.0) -> tuple:
    """Ein Song mit Strophen, Überleitungen, Refrains und Bridge. Wie in echten Songs unterscheiden sich die Teile
    in Akkorden, Lautstärke und Schlagzeug (Strophe: nur Bassdrum und Hi-Hat, Refrain: volles Schlagzeug mit Becken).

    Gibt (Ton, {"beats", "einsen", "tempo", "teile": [{"start", "name"}]}) zurück."""
    form = form or FORM_POP
    rng = np.random.default_rng(seed)
    grundton = 98.0 * 2 ** (int(rng.integers(0, 12)) / 12)
    folgen = {art: FOLGEN[i] for art, i in zip(("strophe", "refrain", "bridge", "vor", "leer"),
                                               rng.choice(len(FOLGEN), 5, replace=False))}
    folgen["leer"] = folgen["strophe"]
    takte = sum(t for _, t, _ in form)
    periode = 60.0 / tempo
    beats = [vorlauf_s + k * periode for k in range(takte * 4 + 1)]
    ton = np.zeros(int((beats[-1] + 2.0) * RATE))
    teile, takt = [], 0
    for name, laenge, art in form:
        teile.append({"start": round(beats[takt * 4], 4), "name": name})
        for t in range(laenge):
            akkord = _akkord(folgen[art][t % 4], grundton)
            for schlag in range(4):
                b = beats[(takt + t) * 4 + schlag]
                laut = {"leer": 0.35, "strophe": 0.55, "vor": 0.65 + 0.3 * t / laenge, "refrain": 1.0, "bridge": 0.45}[art]
                if schlag in (0, 2):
                    _einfuegen(ton, _ton(akkord, 2 * periode, 0.25 * laut, rng, abkling=1.0), b)
                _einfuegen(ton, _ton([akkord[0] / 2], periode, 0.3 * laut, rng, obertoene=2, abkling=4.0), b)
                if art == "leer":
                    continue
                if art in ("strophe", "bridge"):
                    if schlag in ((0,) if art == "bridge" else (0, 2)):
                        _einfuegen(ton, _kick(rng) * 0.8, b)
                    _einfuegen(ton, _hihat(rng, 0.05), b)
                    _einfuegen(ton, _hihat(rng, 0.03), b + periode / 2)
                    continue
                _einfuegen(ton, _kick(rng) if schlag in (0, 2) else _snare(rng) * (0.7 if art == "vor" else 1.0), b)
                if art == "vor":
                    _einfuegen(ton, _snare(rng) * 0.3 * t / laenge, b + periode / 2)     # Snare-Wirbel wird dichter
                _einfuegen(ton, _hihat(rng, 0.09), b)
                _einfuegen(ton, _hihat(rng, 0.06), b + periode / 2)
                if art == "refrain" and t == 0 and schlag == 0:
                    becken = rng.standard_normal(int(1.5 * RATE)) * np.exp(-np.arange(int(1.5 * RATE)) / RATE * 3)
                    _einfuegen(ton, 0.25 * np.diff(np.concatenate([[0], becken])), b)
        takt += laenge
    ton = ton / (np.max(np.abs(ton)) + 1e-9) * 0.8
    return ton.astype(np.float32), {"beats": [round(b, 4) for b in beats[:-1]],
                                    "einsen": [round(b, 4) for b in beats[:-1:4]], "tempo": tempo, "teile": teile}


def rede(sekunden: float = 20.0, seed: int = 1) -> np.ndarray:
    """Künstliche Sprache: Silben (Stimme mit Grundton und Formanten), kurze Lücken, Pausen zwischen den Sätzen.
    Unregelmäßig wie echte Rede, also ohne festen Takt."""
    rng = np.random.default_rng(seed)
    ton = np.zeros(int(sekunden * RATE))
    t, silbe = 0.3, 0
    while t < sekunden - 0.5:
        dauer = rng.uniform(0.12, 0.26)
        n = int(dauer * RATE)
        zeit = np.arange(n) / RATE
        f0 = rng.uniform(110, 190) * (1 + 0.04 * np.sin(2 * np.pi * rng.uniform(3, 6) * zeit))
        phase = 2 * np.pi * np.cumsum(f0) / RATE
        formanten = rng.choice([(700, 1200), (400, 2000), (300, 900), (500, 1700), (600, 1000)])
        stimme = np.zeros(n)
        for k in range(1, 25):
            f = f0.mean() * k
            gewicht = sum(np.exp(-0.5 * ((f - fm) / 120) ** 2) for fm in formanten) + 0.05 / k
            stimme += gewicht * np.sin(k * phase)
        huelle = np.minimum(1, zeit / 0.02) * np.minimum(1, (dauer - zeit) / 0.05)
        _einfuegen(ton, 0.3 * stimme * huelle * rng.uniform(0.6, 1.0), t)
        silbe += 1
        t += dauer + rng.uniform(0.03, 0.09)
        if silbe % int(rng.integers(4, 9)) == 0:
            t += rng.uniform(0.3, 0.7)                 # Pause zwischen zwei Sätzen
    ton = ton / (np.max(np.abs(ton)) + 1e-9) * 0.7
    ton += 0.003 * rng.standard_normal(len(ton))          # Raumrauschen am Mikrofon (nie ganz still)
    return ton.astype(np.float32)


def _tom(rng, hoehe: float) -> np.ndarray:
    t = np.arange(int(0.35 * RATE)) / RATE
    f = hoehe * (1 + 0.5 * np.exp(-t * 25))
    return 0.8 * np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-t * 7) + 0.1 * rng.standard_normal(len(t)) * np.exp(-t * 40)


def _becken(rng, laut: float = 0.35) -> np.ndarray:
    n = int(1.6 * RATE)
    rauschen = rng.standard_normal(n)
    return laut * np.diff(np.concatenate([[0], rauschen])) * np.exp(-np.arange(n) / RATE * 2.5)


def schlagzeug_solo(tempo: float = 150.0, sekunden: float = 60.0, seed: int = 1) -> np.ndarray:
    """Ein lautes Schlagzeug-Solo ohne Band: erst Groove, dann Wirbel über Snare und Toms, Becken auf der Eins,
    Doppel-Bassdrum, kurze Breaks, am Ende wieder Groove. So, wie es ein Schlagzeuger zum Ausprobieren spielt."""
    rng = np.random.default_rng(seed)
    ton = np.zeros(int((sekunden + 2) * RATE))
    beat = 60.0 / tempo
    t, takt = 0.5, 0
    while t < sekunden:
        art = "groove" if takt < 4 or takt % 12 >= 10 else ("break" if takt % 7 == 6 else "solo")
        for schlag in range(4):
            b = t + schlag * beat
            if art == "groove":
                _einfuegen(ton, _kick(rng) if schlag in (0, 2) else _snare(rng), b)
                for achtel in range(2):
                    _einfuegen(ton, _hihat(rng, 0.12), b + achtel * beat / 2)
                if schlag == 0 and takt % 4 == 0:
                    _einfuegen(ton, _becken(rng), b)
            elif art == "break":
                if schlag == 0:
                    _einfuegen(ton, _becken(rng, 0.45), b)
                    _einfuegen(ton, _kick(rng), b)
            else:
                if schlag == 0:
                    _einfuegen(ton, _becken(rng, 0.4), b)
                for sechzehntel in range(4):
                    s = b + sechzehntel * beat / 4 + rng.normal(0, 0.006)
                    wahl = rng.random()
                    if wahl < 0.35:
                        _einfuegen(ton, _snare(rng) * rng.uniform(0.6, 1.0), s)
                    elif wahl < 0.75:
                        _einfuegen(ton, _tom(rng, rng.choice([90.0, 120.0, 160.0, 210.0])) * rng.uniform(0.6, 1.0), s)
                    if sechzehntel % 2 == 0 and rng.random() < 0.7:
                        _einfuegen(ton, _kick(rng) * 0.8, s)
        t += 4 * beat * (1 + rng.normal(0, 0.01))
        takt += 1
    return (ton / (np.max(np.abs(ton)) + 1e-9) * 0.9).astype(np.float32)
