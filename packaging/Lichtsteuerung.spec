# Bauanleitung für die Mac-App (PyInstaller). Aufruf: siehe packaging/bauen.sh
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

WURZEL = Path(SPECPATH).parent
VERSION = re.search(r'^VERSION = "(.+)"', (WURZEL / "lichtsteuerung/version.py").read_text(), re.M).group(1)

daten = [(str(WURZEL / name), name) for name in ("web", "catalog", "profile", "cues")]
daten += [(str(WURZEL / name), ".") for name in
          ("fixtures.json", "stage.json", "positions.json", "x32.json", "sicherheit.json")]
binaries, versteckt = [], collect_submodules("uvicorn") + collect_submodules("lichtsteuerung")
for paket in ("webview", "sounddevice", "soundfile", "libusb_package", "certifi", "pyftdi", "usb", "serial", "anthropic", "rtmidi"):
    d, b, v = collect_all(paket)
    daten += d
    binaries += b
    versteckt += v

a = Analysis([str(WURZEL / "start.py")], pathex=[str(WURZEL)], datas=daten, binaries=binaries,
             hiddenimports=versteckt, excludes=["aubio", "tkinter", "pytest", "matplotlib"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Lichtsteuerung", console=False)
sammlung = COLLECT(exe, a.binaries, a.datas, name="Lichtsteuerung")
app = BUNDLE(sammlung, name="Lichtsteuerung.app", icon=str(WURZEL / "packaging/symbol.icns"),
             bundle_identifier="de.technik-ag.lichtsteuerung", version=VERSION,
             info_plist={
                 "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                 "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "12.0",
                 "NSMicrophoneUsageDescription": "Die Lichtsteuerung analysiert den Ton, damit das Licht auf die Musik reagiert. Aufnahmen (Proben, Mitschnitte) bleiben auf diesem Mac, nichts wird gesendet.",
             })
