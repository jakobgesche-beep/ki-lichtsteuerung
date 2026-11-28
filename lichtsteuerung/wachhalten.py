"""Der Laptop darf während der Show nicht einschlafen (sonst bleibt das Licht stehen oder geht aus).

Solange das Programm läuft, verhindert es den Ruhezustand und das Abschalten des Bildschirms:
    Mac      Hilfsprogramm "caffeinate" (gehört zu macOS), endet von selbst mit dem Programm.
    Windows  SetThreadExecutionState, gilt, bis das Programm endet.
Den MacBook-Deckel trotzdem offen lassen und das Netzteil anstecken.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys

aktiv = False


def einschalten() -> bool:
    global aktiv
    try:
        if sys.platform == "darwin":
            # -d Bildschirm an, -i kein Leerlauf-Schlaf, -s kein Schlaf am Netzteil. Deckel zu legt trotzdem
            # schlafen (und schaltet das eingebaute Mikrofon ab): Das meldet der Konzert-Check.
            subprocess.Popen(["/usr/bin/caffeinate", "-d", "-i", "-s", "-w", str(os.getpid())],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            aktiv = True
        elif sys.platform == "win32":
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
            aktiv = bool(ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED))
    except Exception:
        logging.exception("Ruhezustand ließ sich nicht verhindern")
        aktiv = False
    return aktiv


_mac_stand = {"zeit": -99.0, "netzteil": None, "deckel_zu": None}


def mac_stand(jetzt: float = None, ausfuehren=subprocess.run) -> dict:
    """Mac: Hängt er am Netzteil, ist der Deckel zu? (None = unbekannt, zum Beispiel unter Windows)

    Ein zugeklappter Deckel legt den Mac schlafen und schaltet das eingebaute Mikrofon ab. Am 21.11.2026 war
    genau das der Grund für lange „Ton weg“-Zeiten."""
    import time
    jetzt = time.monotonic() if jetzt is None else jetzt
    if sys.platform != "darwin":
        return {"netzteil": None, "deckel_zu": None}
    if jetzt - _mac_stand["zeit"] < 10.0:
        return {"netzteil": _mac_stand["netzteil"], "deckel_zu": _mac_stand["deckel_zu"]}
    _mac_stand["zeit"] = jetzt
    try:
        batt = ausfuehren(["/usr/bin/pmset", "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
        _mac_stand["netzteil"] = True if "AC Power" in batt else (False if "Battery Power" in batt else None)
    except Exception:
        _mac_stand["netzteil"] = None
    try:
        io = ausfuehren(["/usr/sbin/ioreg", "-r", "-k", "AppleClamshellState", "-d", "1"],
                        capture_output=True, text=True, timeout=3).stdout
        if '"AppleClamshellState" = Yes' in io:
            _mac_stand["deckel_zu"] = True
        elif '"AppleClamshellState" = No' in io:
            _mac_stand["deckel_zu"] = False
        else:
            _mac_stand["deckel_zu"] = None
    except Exception:
        _mac_stand["deckel_zu"] = None
    return {"netzteil": _mac_stand["netzteil"], "deckel_zu": _mac_stand["deckel_zu"]}
