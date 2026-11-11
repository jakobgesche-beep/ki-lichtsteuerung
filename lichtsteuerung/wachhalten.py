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
            subprocess.Popen(["/usr/bin/caffeinate", "-d", "-i", "-w", str(os.getpid())],
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
