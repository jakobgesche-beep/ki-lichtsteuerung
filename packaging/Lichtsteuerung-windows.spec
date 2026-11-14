# Bauanleitung für Windows (PyInstaller). Aufruf: python -m PyInstaller packaging/Lichtsteuerung-windows.spec
# Ergebnis: dist/Lichtsteuerung/Lichtsteuerung.exe mit allem, was dazugehört. Den Installer baut
# danach packaging/lichtsteuerung.iss (Inno Setup).
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

WURZEL = Path(SPECPATH).parent
VERSION = re.search(r'^VERSION = "(.+)"', (WURZEL / "lichtsteuerung/version.py").read_text(encoding="utf-8"), re.M).group(1)

daten = [(str(WURZEL / name), name) for name in ("web", "catalog", "profile", "cues")]
daten += [(str(WURZEL / name), ".") for name in
          ("fixtures.json", "stage.json", "positions.json", "x32.json", "sicherheit.json")]
binaries, versteckt = [], collect_submodules("uvicorn") + collect_submodules("lichtsteuerung")
# webview braucht unter Windows pythonnet (clr) für das Edge-Fenster
for paket in ("webview", "sounddevice", "soundfile", "libusb_package", "certifi", "pyftdi", "usb", "serial",
              "clr_loader", "pythonnet", "anthropic", "rtmidi", "segno"):
    try:
        d, b, v = collect_all(paket)
    except Exception:
        continue
    daten += d
    binaries += b
    versteckt += v
versteckt += ["clr"]

a = Analysis([str(WURZEL / "start.py")], pathex=[str(WURZEL)], datas=daten, binaries=binaries,
             hiddenimports=versteckt, excludes=["aubio", "tkinter", "pytest", "matplotlib"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Lichtsteuerung", console=False,
          icon=str(WURZEL / "packaging/symbol.ico"))
sammlung = COLLECT(exe, a.binaries, a.datas, name="Lichtsteuerung")
