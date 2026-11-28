"""Koppeln: Welche iPads das Pult über das WLAN bedienen dürfen – auch nach einem Neustart.

So geht es:
    Am MacBook „iPad koppeln“ drücken. Dann ist 5 Minuten lang ein Kopplungsfenster offen, mit einer
    6-stelligen PIN (steht auch im QR-Code). Das iPad schickt PIN und Namen und bekommt einen langen,
    zufälligen Schlüssel. Den merkt es sich; das MacBook speichert davon nur einen Fingerabdruck (SHA-256)
    in daten/netz_geraete.json. Wer die Datei liest, kann sich damit nicht anmelden.

Sicherheit:
    Ohne offenes Fenster wird keine PIN angenommen. 5 falsche PINs von einem Gerät: 30 s warten,
    30 falsche insgesamt: Fenster zu. Höchstens 10 Geräte; jedes lässt sich am MacBook einzeln entfernen.
    Die Verbindung ist nicht verschlüsselt: nur im eigenen WLAN der Technik-AG benutzen.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from . import daten

FENSTER_S = 300.0
PIN_STELLEN = 6
FEHLVERSUCHE_PRO_GERAET = 5
SPERRE_GERAET_S = 30.0
FEHLVERSUCHE_GESAMT = 30
MAX_GERAETE = 10
ZULETZT_SPEICHERN_S = 60.0     # „zuletzt gesehen“ höchstens einmal pro Minute auf die Platte


def fingerabdruck(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


class Kopplung:
    def __init__(self, pfad: Path, uhr=time.time, monoton=time.monotonic):
        self.pfad = Path(pfad)
        self.uhr, self.monoton = uhr, monoton
        self.sperre = threading.Lock()
        roh = daten.lese_json_sicher(self.pfad, {}) or {}
        self.geraete = [g for g in roh.get("geraete", []) if isinstance(g, dict) and len(str(g.get("hash", ""))) == 64]
        self.pin: Optional[str] = None
        self.fenster_bis = 0.0
        self.fehlversuche: dict = {}                 # Adresse -> (Anzahl, gesperrt bis)
        self.fehlversuche_gesamt = 0
        self._gespeichert = 0.0

    # --- Fenster am MacBook -----------------------------------------------------------

    def fenster_oeffnen(self) -> dict:
        with self.sperre:
            self.pin = "".join(str(secrets.randbelow(10)) for _ in range(PIN_STELLEN))
            self.fenster_bis = self.monoton() + FENSTER_S
            self.fehlversuche, self.fehlversuche_gesamt = {}, 0
        return self.fenster()

    def fenster_schliessen(self) -> None:
        with self.sperre:
            self.pin, self.fenster_bis = None, 0.0

    def fenster(self) -> dict:
        rest = self.fenster_bis - self.monoton()
        if self.pin is None or rest <= 0:
            return {"offen": False, "pin": None, "rest_s": 0}
        return {"offen": True, "pin": self.pin, "rest_s": int(rest)}

    # --- iPad meldet sich ------------------------------------------------------------

    def koppeln(self, pin: str, name: str, adresse: str, rolle: str = "ipad") -> str:
        jetzt = self.monoton()
        with self.sperre:
            if self.pin is None or jetzt >= self.fenster_bis:
                raise PermissionError("Am MacBook zuerst „iPad koppeln“ drücken (das Kopplungsfenster ist zu).")
            anzahl, bis = self.fehlversuche.get(adresse, (0, 0.0))
            if jetzt < bis:
                raise PermissionError(f"Zu viele falsche PINs. Bitte {int(bis - jetzt) + 1} s warten.")
            if not hmac.compare_digest(str(pin or "").replace(" ", "").encode(), self.pin.encode()):
                anzahl += 1
                self.fehlversuche[adresse] = (0, jetzt + SPERRE_GERAET_S) if anzahl >= FEHLVERSUCHE_PRO_GERAET else (anzahl, 0.0)
                self.fehlversuche_gesamt += 1
                if self.fehlversuche_gesamt >= FEHLVERSUCHE_GESAMT:
                    self.pin, self.fenster_bis = None, 0.0
                    logging.warning("Kopplung: zu viele falsche PINs, Fenster geschlossen")
                raise PermissionError("Falsche PIN.")
            token = secrets.token_urlsafe(32)
            name = " ".join(str(name or "iPad").split())[:40] or "iPad"
            self.geraete.append({"name": name, "rolle": rolle if rolle in ("ipad", "handy") else "ipad",
                                 "hash": fingerabdruck(token), "seit": self._datum(), "zuletzt": self._datum()})
            del self.geraete[:-MAX_GERAETE]
            self.pin, self.fenster_bis = None, 0.0           # ein Fenster koppelt genau ein Gerät
            self._speichern()
        logging.info("Kopplung: neues Gerät „%s“", name)
        return token

    def pruefen(self, token: str) -> Optional[dict]:
        """Das gekoppelte Gerät zu diesem Schlüssel, oder None."""
        gesucht = fingerabdruck(token)
        with self.sperre:
            for geraet in self.geraete:
                if hmac.compare_digest(gesucht, geraet["hash"]):
                    geraet["zuletzt"] = self._datum()
                    if self.monoton() - self._gespeichert > ZULETZT_SPEICHERN_S:
                        self._speichern()
                    return dict(geraet)
        return None

    # --- Verwalten am MacBook --------------------------------------------------------

    def liste(self) -> list:
        return [{"nummer": i, "name": g["name"], "rolle": g.get("rolle", "ipad"), "seit": g.get("seit", ""),
                 "zuletzt": g.get("zuletzt", "")} for i, g in enumerate(self.geraete)]

    def entfernen(self, nummer: int) -> None:
        with self.sperre:
            if not 0 <= nummer < len(self.geraete):
                raise ValueError("Dieses Gerät gibt es nicht.")
            del self.geraete[nummer]
            self._speichern()

    def alle_entfernen(self) -> None:
        with self.sperre:
            self.geraete = []
            self._speichern()

    def hat_ipad(self) -> bool:
        return any(g.get("rolle", "ipad") == "ipad" for g in self.geraete)

    # --- intern -------------------------------------------------------------------

    def _datum(self) -> str:
        return time.strftime("%d.%m.%Y %H:%M", time.localtime(self.uhr()))

    def _speichern(self) -> None:
        self._gespeichert = self.monoton()
        daten.schreibe_json(self.pfad, {"_hinweis": "Gekoppelte iPads (nur Fingerabdrücke der Schlüssel).",
                                        "geraete": self.geraete})
