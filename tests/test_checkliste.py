"""Aufbau-Checkliste zum Ausdrucken (für den Aufbau am Veranstaltungsort)."""
from fastapi.testclient import TestClient

from lichtsteuerung import checkliste, daten
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show


def test_checkliste_hat_geraete_dip_ton_ipad_und_notfall(tmp_path):
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    html = checkliste.seite(show)
    for teil in ("Aufbau-Checkliste", "Geräte adressieren", "Ton vom X32", "Card Out", "iPad-Pult", "Gesten aus",
                 "Soundcheck", "Notfall am Abend", "Blackout", "Lautstärke der Band ist noch nicht gemerkt"):
        assert teil in html, teil
    for geraet in show.patch.geraete:
        assert f"{geraet['adresse']:03d}" in html                 # jede Startadresse steht drin
    assert 'class="dip' in html                                   # Schalterreihen wie im Patchplan
    show.audio.bezuege["Eingang: X-USB | 15,16"] = -18.0
    assert "Lautstärke der Band ist gemerkt" in checkliste.seite(show)


def test_checkliste_ueber_den_server(tmp_path):
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    antwort = TestClient(erstelle_app(show)).get("/checkliste")
    assert antwort.status_code == 200 and "Aufbau-Checkliste" in antwort.text


def test_konzert_check_sagt_ob_der_soundcheck_gemerkt_ist(tmp_path, monkeypatch):
    import time
    import numpy as np
    from lichtsteuerung import konzertcheck
    from lichtsteuerung.audio import quellen
    from lichtsteuerung.audio.quellen import ABTASTRATE, BLOCK

    class Band:
        def __init__(self, geraet=None, kanaele=(1,), name=None, api=None, rollen=None):
            self.geraet_name, self.api_name, self.kanaele, self.rollen = "X-USB", "Core Audio", kanaele, {}
            self.zufall = np.random.default_rng(1)

        def lies(self):
            time.sleep(BLOCK / ABTASTRATE)
            return (0.1 * self.zufall.standard_normal(BLOCK)).astype(np.float32)

        def schliessen(self):
            pass

    monkeypatch.setattr(quellen, "Eingang", Band)
    daten.einrichten(tmp_path / "d")
    show = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    try:
        show.audio_quelle_setzen({"art": "eingang", "geraet": 3, "kanaele": [15, 16]})
        ende = time.monotonic() + 5
        while show.audio.frisch() is None and time.monotonic() < ende:
            time.sleep(0.05)
        texte = " ".join(p["text"] for p in konzertcheck.pruefen(show) if p["thema"] == "Ton")
        assert "Noch kein Soundcheck gemerkt" in texte
        show.audio.bezuege["Eingang: X-USB | 15,16"] = -20.0
        texte = " ".join(p["text"] for p in konzertcheck.pruefen(show) if p["thema"] == "Ton")
        assert "Lautstärke der Band ist gemerkt" in texte
    finally:
        show.audio.stoppen()
