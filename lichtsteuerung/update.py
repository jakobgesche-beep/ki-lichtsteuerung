"""Selbst-Update der App (Mac und Windows): Niemand muss die App neu herunterladen.

Ablauf:
  1. Beim Start und danach alle 30 Minuten schaut die App im GitHub-Release
     nach (latest.json), dazu auf Knopfdruck. Ohne Internet passiert einfach
     nichts. Die Show braucht das nie.
  2. Gibt es eine neuere Version, lädt sie die ZIP-Datei im Hintergrund und
     vergleicht die Prüfsumme.
  3. Oben erscheint ein Knopf. Installiert wird nur auf Klick und nie, solange
     die DMX-Ausgabe läuft: Ein Neustart mitten in der Show wäre ein Blackout.
  4. Ein kleines Skript wartet, bis die App beendet ist, tauscht das App-Paket
     aus und startet sie neu. Geht etwas schief, bleibt die alte Version.
     Unter Windows führt das Skript stattdessen den neuen Installer still aus.

Die Show-Daten liegen außerhalb der App (siehe daten.py) und bleiben unberührt.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

from . import daten
from .version import VERSION

BASIS_URL = "https://github.com/jakobgesche-beep/ki-lichtsteuerung/releases/latest/download/"
ZEITLIMIT_S = 30
ABSTAND_S = 30 * 60
ARCHITEKTUREN = {"arm64": "arm64", "x86_64": "intel"}

WINDOWS_SKRIPT = r"""param([int]$AppPid, [string]$Installer, [string]$Programm)
# Wartet, bis die App zu ist (hoechstens 20 Sekunden; laeuft sie dann noch,
# schliesst der Installer sie selbst). Dann still installieren und neu starten.
try { Wait-Process -Id $AppPid -Timeout 20 -ErrorAction Stop } catch { }
$p = Start-Process -FilePath $Installer -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER' -Wait -PassThru
Remove-Item -LiteralPath $Installer -ErrorAction SilentlyContinue
if (-not $env:LICHT_KEIN_NEUSTART) { Start-Process -FilePath $Programm }
"""


def paket() -> str:
    """Welche Datei aus latest.json passt zu diesem Rechner."""
    if sys.platform == "win32":
        return "windows"
    return ARCHITEKTUREN[platform.machine()]

INSTALLIER_SKRIPT = """#!/bin/sh
# Bekommt: Prozessnummer der App, ZIP-Datei, Pfad der App
pid=$1; zip=$2; app=$3
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
neu="$app.neu"; alt="$app.alt"
rm -rf "$neu" "$alt"
mkdir "$neu"
if ditto -x -k "$zip" "$neu" && [ -d "$neu/Lichtsteuerung.app" ] \\
        && codesign --verify --deep "$neu/Lichtsteuerung.app"; then
    mv "$app" "$alt" && mv "$neu/Lichtsteuerung.app" "$app" && rm -rf "$alt"
fi
[ -d "$app" ] || mv "$alt" "$app"     # Falls etwas schiefging: alte Version zurück
rm -rf "$neu" "$zip"
[ -n "$LICHT_KEIN_NEUSTART" ] || open "$app"
"""


def version_zahlen(text: str) -> tuple:
    if not re.fullmatch(r"\d+\.\d+\.\d+", text):
        raise ValueError(f"Ungültige Version: {text!r}")
    return tuple(int(teil) for teil in text.split("."))


def ist_neuer(version: str, als: str = VERSION) -> bool:
    return version_zahlen(version) > version_zahlen(als)


def app_pfad() -> Optional[Path]:
    """Mac: der Ort von Lichtsteuerung.app. Windows: der Programmordner.
    None, wenn das Programm aus dem Quellcode läuft."""
    if not daten.ALS_APP:
        return None
    if sys.platform == "win32":
        return Path(sys.executable).resolve().parent
    return Path(sys.executable).resolve().parents[2]


def tls_kontext() -> ssl.SSLContext:
    import certifi
    return ssl.create_default_context(cafile=certifi.where())


class Aktualisierer:
    def __init__(self, show, basis_url: str = BASIS_URL):
        self.show = show
        self.basis_url = basis_url
        self.zustand = "ruht"     # ruht, sucht, laedt, bereit, fehler
        self.neu: Optional[str] = None
        self.text = ""
        self.zip: Optional[Path] = None
        self.beenden = None       # setzt start.py: beendet die App sauber

    def status(self) -> dict:
        return {"zustand": self.zustand, "neu": self.neu, "text": self.text,
                "gesperrt": self.sperrgrund()}

    def sperrgrund(self) -> str:
        """Warum gerade nicht installiert werden darf. Leer heißt: Es geht."""
        if self.show.ausgabe.eingeschaltet:
            return "Zum Aktualisieren erst die DMX-Ausgabe ausschalten."
        app = app_pfad()
        if app is None:
            return ""
        if sys.platform == "win32":
            if not os.access(app, os.W_OK):
                return "Keine Schreibrechte für den Programmordner. Bitte mit dem Installer von der Website neu installieren."
            return ""
        if "AppTranslocation" in str(app) or str(app).startswith("/Volumes/"):
            return "Bitte die App zuerst in den Ordner Programme ziehen."
        if not os.access(app.parent, os.W_OK):
            return "Keine Schreibrechte für den Ordner der App."
        return ""

    def im_hintergrund_pruefen(self, wiederholen: bool = True) -> None:
        """Beim Start, dann regelmäßig. Ein schon geladenes Update bleibt liegen."""
        if app_pfad() is None:
            return

        def schleife():
            while True:
                if self.zustand not in ("laedt", "bereit", "sucht"):
                    self.pruefen()
                if not wiederholen:
                    return
                time.sleep(ABSTAND_S)

        threading.Thread(target=schleife, name="Update", daemon=True).start()

    def jetzt_suchen(self) -> None:
        """Für den Knopf "Nach Update suchen"."""
        if app_pfad() is None:
            self.text = "Aus dem Quellcode gestartet: Updates gibt es nur in der fertigen App."
            return
        self.text = ""
        self.im_hintergrund_pruefen(wiederholen=False)

    def _oeffnen(self, name: str):
        return urllib.request.urlopen(self.basis_url + name, timeout=ZEITLIMIT_S, context=tls_kontext())

    def pruefen(self) -> None:
        """Fehler sind hier kein Problem: Dann bleibt alles, wie es ist."""
        self.zustand = "sucht"
        try:
            with self._oeffnen("latest.json") as antwort:
                manifest = json.load(antwort)
            if not ist_neuer(manifest["version"]):
                self.zustand = "ruht"
                self.text = f"Version {VERSION} ist aktuell."
                return
            eintrag = manifest["dateien"][paket()]
            self.neu = manifest["version"]
            self.zustand = "laedt"
            self.zip = self._laden(eintrag["name"], eintrag["sha256"])
            self.zustand = "bereit"
        except Exception as fehler:
            logging.info("Update nicht möglich: %s", fehler)
            self.zustand = "ruht"
            self.text = "Keine Verbindung zum Update-Server. Die Show läuft trotzdem."

    def _laden(self, name: str, pruefsumme: str) -> Path:
        ordner = self.show.pfade.wurzel / "update"
        ordner.mkdir(parents=True, exist_ok=True)
        ziel = ordner / Path(name).name
        summe = hashlib.sha256()
        with self._oeffnen(Path(name).name) as antwort, open(ziel, "wb") as datei:
            while True:
                stueck = antwort.read(1024 * 1024)
                if not stueck:
                    break
                summe.update(stueck)
                datei.write(stueck)
        if summe.hexdigest() != pruefsumme:
            ziel.unlink()
            raise ValueError("Die Prüfsumme stimmt nicht.")
        return ziel

    def installieren(self) -> None:
        """Nur auf Klick. Das Skript übernimmt, sobald die App beendet ist."""
        if self.zustand != "bereit" or self.zip is None:
            raise ValueError("Es liegt kein Update bereit.")
        grund = self.sperrgrund()
        if grund:
            raise ValueError(grund)
        if sys.platform == "win32":
            starte_windows_skript(os.getpid(), self.zip, app_pfad() / "Lichtsteuerung.exe")
        else:
            starte_skript(os.getpid(), self.zip, app_pfad())
        threading.Timer(0.3, self.beenden or (lambda: os._exit(0))).start()


def starte_skript(pid: int, zip_datei: Path, app: Path) -> subprocess.Popen:
    griff, pfad = tempfile.mkstemp(suffix=".sh", prefix="licht-update-")
    with os.fdopen(griff, "w") as datei:
        datei.write(INSTALLIER_SKRIPT)
    # Die Pfade gehen als Argumente mit, so stört kein Leerzeichen im Namen.
    return subprocess.Popen(["/bin/sh", pfad, str(pid), str(zip_datei), str(app)],
                            start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def starte_windows_skript(pid: int, installer: Path, programm: Path) -> subprocess.Popen:
    """Windows: Das Skript wartet, bis die App zu ist, und installiert dann still darüber."""
    griff, pfad = tempfile.mkstemp(suffix=".ps1", prefix="licht-update-")
    with os.fdopen(griff, "w", encoding="ascii") as datei:
        datei.write(WINDOWS_SKRIPT)
    ohne_fenster = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-WindowStyle", "Hidden", "-File", pfad, str(pid), str(installer), str(programm)],
                            creationflags=ohne_fenster, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
