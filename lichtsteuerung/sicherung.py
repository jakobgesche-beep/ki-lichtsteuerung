"""Show sichern und laden: eine Datei für den Weg vom MacBook zum Windows-Laptop (und zurück).

In der Datei steht alles, was die Show ausmacht: Patch, Bühne, Positionen, Profile, Sequenzen,
Fader-Belegung, eigene Gerätetypen (auch eingemessene Strobos) und auf Wunsch die Proben-Aufnahmen.
Nicht darin: der Claude-Schlüssel (lokal.json) und was nur zu diesem Rechner gehört (Ton-Eingang,
Logbuch). So kann man die Datei weitergeben, ohne etwas Geheimes mitzuschicken.

Laden geht beim nächsten Start: Dann ist nichts geöffnet, was dazwischenfunken könnte. Vorher wird
der alte Stand gesichert (Ordner "sicherungen"). Bei jedem Start legt das Programm außerdem selbst
eine kleine Sicherung an (ohne Aufnahmen, die letzten 10 bleiben).
"""
from __future__ import annotations

import datetime
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional

DATEIEN = ("fixtures.json", "stage.json", "positions.json", "x32.json")
ORDNER = ("profile", "cues", "catalog/eigene")
PROBEN = ("daten/proben", "daten/audio")
NIE = {"lokal.json", "daten/sitzung.json", "logbuch.txt"}
WARTET = "daten/show_beim_start_laden.zip"
SICHERUNGEN = "sicherungen"
MAX_GROESSE = 3 * 1024 ** 3                 # entpackt höchstens 3 GB
AUTOMATISCH_BEHALTEN = 10


def _jetzt() -> datetime.datetime:
    return datetime.datetime.now()


def _erlaubt(name: str, mit_proben: bool = True) -> bool:
    """Nur bekannte Show-Dateien, nie Pfade nach oben oder an andere Orte."""
    pfad = PurePosixPath(name)
    if pfad.is_absolute() or ".." in pfad.parts or "\\" in name or ":" in name:
        return False
    text = pfad.as_posix()
    if text in NIE or text.endswith("/"):
        return False
    if text in DATEIEN:
        return True
    ordner = ORDNER + (PROBEN if mit_proben else ())
    return any(text.startswith(o + "/") for o in ordner)


def _dateien(wurzel: Path, mit_proben: bool) -> list:
    gefunden = []
    for name in DATEIEN:
        if (wurzel / name).is_file():
            gefunden.append(name)
    for ordner in ORDNER + (PROBEN if mit_proben else ()):
        basis = wurzel / ordner
        if basis.is_dir():
            for datei in sorted(basis.rglob("*")):
                if datei.is_file() and not datei.name.startswith(".") and not datei.name.endswith(".tmp"):
                    gefunden.append(datei.relative_to(wurzel).as_posix())
    return [name for name in gefunden if _erlaubt(name, mit_proben)]


def exportieren(wurzel: Path, ziel: Path, mit_proben: bool = True) -> Path:
    """Schreibt die Show als eine .zip-Datei. Gibt den Pfad zurück."""
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    zwischen = ziel.with_suffix(".teil")
    with zipfile.ZipFile(zwischen, "w", compression=zipfile.ZIP_DEFLATED) as archiv:
        for name in _dateien(Path(wurzel), mit_proben):
            # Aufnahmen sind schon groß und lassen sich kaum packen: nur ablegen geht schneller
            art = zipfile.ZIP_STORED if name.endswith(".wav") else zipfile.ZIP_DEFLATED
            archiv.write(Path(wurzel) / name, name, compress_type=art)
        archiv.writestr("lichtsteuerung-show.txt", "Show-Datei der Lichtsteuerung der Technik-AG.\n"
                        f"Gesichert am {_jetzt():%d.%m.%Y %H:%M}.\n")
    zwischen.replace(ziel)
    return ziel


def pruefen(datei: Path) -> dict:
    """Ist das eine Show-Datei, die wir laden dürfen? Gibt eine kurze Übersicht zurück."""
    try:
        with zipfile.ZipFile(datei) as archiv:
            namen = [i for i in archiv.infolist() if not i.is_dir()]
            if "fixtures.json" not in {i.filename for i in namen}:
                raise ValueError("Das ist keine Show-Datei der Lichtsteuerung (fixtures.json fehlt).")
            if sum(i.file_size for i in namen) > MAX_GROESSE:
                raise ValueError("Die Show-Datei ist zu groß.")
            schlecht = [i.filename for i in namen if not _erlaubt(i.filename) and i.filename != "lichtsteuerung-show.txt"]
            if schlecht:
                raise ValueError(f"Die Datei enthält Unerwartetes ({schlecht[0]}). Sie wird nicht geladen.")
            return {"dateien": len(namen),
                    "sequenzen": sum(1 for i in namen if i.filename.startswith("cues/sequenzen/")),
                    "proben": sum(1 for i in namen if i.filename.startswith("daten/proben/") and i.filename.endswith(".wav"))}
    except zipfile.BadZipFile as fehler:
        raise ValueError("Das ist keine gültige .zip-Datei.") from fehler


def vormerken(wurzel: Path, datei: Path) -> dict:
    """Prüft die Datei und legt sie bereit. Übernommen wird sie beim nächsten Start."""
    uebersicht = pruefen(datei)
    ziel = Path(wurzel) / WARTET
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(datei), ziel)
    return uebersicht


def vorgemerkt(wurzel: Path) -> bool:
    return (Path(wurzel) / WARTET).is_file()


def beim_start_laden(wurzel: Path) -> Optional[str]:
    """Wenn eine Show-Datei bereitliegt: alten Stand sichern, dann die neue Show auspacken."""
    wurzel = Path(wurzel)
    datei = wurzel / WARTET
    if not datei.is_file():
        return None
    try:
        pruefen(datei)
    except ValueError as fehler:
        datei.unlink(missing_ok=True)
        return f"Die bereitgelegte Show-Datei war kaputt und wurde nicht geladen: {fehler}"
    stempel = f"{_jetzt():%Y-%m-%d_%H-%M-%S}"
    exportieren(wurzel, wurzel / SICHERUNGEN / f"vor-dem-laden-{stempel}.zip", mit_proben=True)
    # Was die neue Show nicht mitbringt, soll auch nicht aus der alten übrig bleiben (zum Beispiel Sequenzen)
    for ordner in ("cues/sequenzen", "profile"):
        if (wurzel / ordner).is_dir():
            shutil.rmtree(wurzel / ordner)
    with zipfile.ZipFile(datei) as archiv:
        for info in archiv.infolist():
            if info.is_dir() or not _erlaubt(info.filename):
                continue
            ziel = wurzel / Path(*PurePosixPath(info.filename).parts)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            with archiv.open(info) as quelle, open(ziel, "wb") as senke:
                shutil.copyfileobj(quelle, senke)
    datei.unlink()
    return f"Show geladen. Der vorige Stand liegt in „{SICHERUNGEN}/vor-dem-laden-{stempel}.zip“."


def automatisch_sichern(wurzel: Path) -> Optional[Path]:
    """Kleine Sicherung bei jedem Start (ohne Aufnahmen). Die letzten 10 bleiben."""
    wurzel = Path(wurzel)
    if not (wurzel / "fixtures.json").is_file():
        return None
    ordner = wurzel / SICHERUNGEN
    ziel = exportieren(wurzel, ordner / f"automatisch-{_jetzt():%Y-%m-%d_%H-%M-%S}.zip", mit_proben=False)
    alte = sorted(ordner.glob("automatisch-*.zip"))
    for datei in alte[:-AUTOMATISCH_BEHALTEN]:
        datei.unlink(missing_ok=True)
    return ziel


def downloads_ordner() -> Path:
    """Wohin die Show-Datei geschrieben wird: der Downloads-Ordner (Mac und Windows), sonst der Schreibtisch."""
    for kandidat in (Path.home() / "Downloads", Path.home() / "Desktop", Path.home()):
        if kandidat.is_dir():
            return kandidat
    return Path.home()
