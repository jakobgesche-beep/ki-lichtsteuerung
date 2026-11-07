"""Strobo ohne Namen: Platzhalter, Einmessen, danach hält die Grenze."""
import pytest
from fastapi.testclient import TestClient

from lichtsteuerung import daten
from lichtsteuerung.pruefung import Vorgaben, bereich_von, hz_von
from lichtsteuerung.server import erstelle_app
from lichtsteuerung.show import Show

TEMPO, HELL = 0, 1      # Kanäle des Strobos ab Adresse 110 (Modus "Tempo, Helligkeit")


@pytest.fixture
def show(tmp_path):
    daten.einrichten(tmp_path / "d")
    s = Show(daten.Pfade(tmp_path / "d", daten.PROJEKT / "catalog"))
    s.patch.hinzufuegen("technik-ag/strobo-ohne-namen", "2 Kanäle: Tempo, Helligkeit", 1, "Strobo", start=110)
    s.aufbauen()
    s.automatik_an = False
    return s


def kanal(bild, n):
    return bild[109 + n]


def test_platzhalter_bleibt_gesperrt(show):
    show.test_setzen(None, {110: 200, 111: 255})
    bild = show.baue_bild(0.0)
    assert kanal(bild, TEMPO) == 0 and not show.blitzt
    assert show.patch.gruppen_von(show.patch.geraet("strobo")) == ["Strobo"]


def test_einmessen_blitzt_nur_3_sekunden(show):
    show.strobo_einmessen("strobo", 60, jetzt=10.0)
    bild = show.baue_bild(10.5)
    assert kanal(bild, TEMPO) == 60 and kanal(bild, HELL) == 255 and show.blitzt
    bild = show.baue_bild(13.1)
    assert kanal(bild, TEMPO) == 0 and not show.blitzt


def test_strobo_aus_und_blackout_gewinnen_auch_beim_einmessen(show):
    show.strobo_einmessen("strobo", 60, jetzt=0.0)
    show.overrides.strobo_aus = True
    assert kanal(show.baue_bild(0.5), TEMPO) == 0
    show.overrides.strobo_aus, show.overrides.blackout = False, True
    bild = show.baue_bild(0.6)
    assert kanal(bild, HELL) == 0


def test_auswerten_macht_die_grenze_wirksam(show):
    ergebnis = show.strobo_auswerten("strobo", [{"wert": 10, "blitze": 3, "sekunden": 3},
                                                {"wert": 30, "blitze": 9, "sekunden": 3},
                                                {"wert": 60, "blitze": 21, "sekunden": 3}])
    assert ergebnis["nutzbar"] and ergebnis["von"] == 10 and ergebnis["bis"] == 60
    # Jetzt soll er wild blitzen: Die Prüfung deckelt auf die Grenze.
    show.profil = {**show.profil, "strobo": {"max_blitze_pro_sekunde": 3, "max_dauer_s": 5}}
    show.test_setzen(None, {110: 60, 111: 255})
    bild = show.baue_bild(0.0)
    kanal_daten = next(k for _, k in show.patch.typ(show.patch.geraet("strobo")).kanaele_im_modus(
        "2 Kanäle: Tempo, Helligkeit") if k["typ"] == "strobo")
    hz = hz_von(bereich_von(kanal_daten, kanal(bild, TEMPO)), kanal(bild, TEMPO))
    assert hz <= 3.0 + 1e-9 and show.blitzt
    # Über dem gemessenen Bereich bleibt es gesperrt.
    show.test_setzen(None, {110: 200, 111: 255})
    assert kanal(show.baue_bild(0.1), TEMPO) == 0


def test_messung_die_nicht_passt_wird_abgelehnt(show):
    with pytest.raises(ValueError, match="höherer Wert"):
        show.strobo_auswerten("strobo", [{"wert": 10, "blitze": 9}, {"wert": 60, "blitze": 3}])
    with pytest.raises(ValueError, match="zwei"):
        show.strobo_auswerten("strobo", [{"wert": 10, "blitze": 3}])


def test_zu_schnell_schon_beim_kleinsten_wert(show):
    ergebnis = show.strobo_auswerten("strobo", [{"wert": 20, "blitze": 15}, {"wert": 40, "blitze": 30}])
    assert not ergebnis["nutzbar"] and "kleineren Wert" in ergebnis["text"]


def test_server_verlangt_bestaetigung(show):
    with TestClient(erstelle_app(show)) as client:
        strobo = lambda: next(g for g in client.get("/api/strobos").json()["strobos"] if g["id"] == "strobo")
        assert strobo()["eingemessen"] is False
        assert client.post("/api/strobos/strobo/blitzen", json={"wert": 30}).status_code == 400
        assert client.post("/api/strobos/strobo/blitzen", json={"wert": 30, "bestaetigt": True}).status_code == 200
        antwort = client.post("/api/strobos/strobo/auswerten", json={"messungen": [
            {"wert": 10, "blitze": 3, "sekunden": 3}, {"wert": 40, "blitze": 12, "sekunden": 3}]}).json()
        assert antwort["nutzbar"]
        assert strobo()["eingemessen"] is True


def test_drop_laesst_den_eingemessenen_strobo_blitzen(show):
    from lichtsteuerung.audio.analyse import Messwerte
    show.strobo_auswerten("strobo", [{"wert": 10, "blitze": 3}, {"wert": 40, "blitze": 12}])
    profil = {**show.profil, "strobo": {"max_blitze_pro_sekunde": 3, "max_dauer_s": 5}, "beat_reaktion": 0.9}
    zustand = show.engine.bewerte(Messwerte(beat=True, drop=True, tempo_bpm=128, energie=0.9, leise=False), profil, 0.0)
    assert zustand["strobo"].strobo_hz == 3


def test_moving_head_shutter_bleibt_beim_einmessen_heil(show):
    """Beim MH-X25 liegt Strobo zwischen "zu" und "offen". Diese Bereiche müssen bleiben."""
    ergebnis = show.strobo_auswerten("front-1", [{"wert": 20, "blitze": 3}, {"wert": 60, "blitze": 9}])
    assert ergebnis["nutzbar"]
    kanal = next(k for _, k in show.patch.typ(show.patch.geraet("front-1")).kanaele_im_modus("12-channel")
                 if k["typ"] == "strobo")
    arten = [(b["von"], b["bis"], b["typ"], b.get("hz_bis")) for b in kanal["bereiche"]]
    assert (0, 3, "zu", None) in arten and (4, 7, "offen", None) in arten and (216, 255, "offen", None) in arten
    assert (20, 60, "strobo", 9 / 3) in [(v, b, t, round(h, 2) if h else h) for v, b, t, h in arten]
    with pytest.raises(ValueError, match="Strobo-Bereich"):
        show.strobo_auswerten("front-2", [{"wert": 2, "blitze": 1}, {"wert": 60, "blitze": 9}])


def test_gesperrter_strobo_leuchtet_nicht_dauerhaft(show):
    """Helligkeit voll, Tempo gesperrt: Er darf nicht als weißes Dauerlicht ins Publikum strahlen."""
    show.automatik_an = True
    show.pult.programmer.setzen(["strobo"], {"helligkeit": 1.0, "strobo_hz": 3})
    an = 0
    for i in range(40):                                   # eine Sekunde
        bild = show.baue_bild(i * 0.025)
        assert kanal(bild, TEMPO) == 0                    # das unbekannte eigene Tempo bleibt gesperrt
        an += kanal(bild, HELL) > 0
    assert an <= 3 * 2                                    # nur kurze Blitze (je 50 ms), kein Dauerlicht
    show.pult.programmer.leeren()
    show.strobo_auswerten("strobo", [{"wert": 10, "blitze": 3}, {"wert": 40, "blitze": 12}])
    show.profil = {**show.profil, "strobo": {"max_blitze_pro_sekunde": 3, "max_dauer_s": 5}}
    show.pult.programmer.setzen(["strobo"], {"helligkeit": 1.0, "strobo_hz": 3})
    bild = show.baue_bild(1.0)
    assert kanal(bild, HELL) == 255 and kanal(bild, TEMPO) > 0 and show.blitzt


# --- Software-Blitz: Strobo ohne Einmessen blitzt über die Helligkeit -------------------

def strobo_halten(show, an=True, jetzt=0.0):
    show.pult.halten_setzen("strobo", an, jetzt)


def blitze_zaehlen(show, von, bis, schritt=0.025):
    """Wie oft springt die Helligkeit des Strobos von aus auf an? Tempo-Kanal muss 0 bleiben."""
    anzahl, vorher, an_zeiten = 0, 0, []
    t = von
    while t < bis:
        bild = show.baue_bild(t)
        assert kanal(bild, TEMPO) == 0                     # das unbekannte eigene Tempo wird nie benutzt
        hell = kanal(bild, HELL)
        if hell > 0 and vorher == 0:
            anzahl += 1
            an_zeiten.append(t)
        vorher = hell
        t += schritt
    return anzahl, an_zeiten


def test_strobo_ohne_einmessen_blitzt_selbst_hoechstens_dreimal_pro_sekunde(show):
    show.profil = dict(show.profil, strobo={"max_blitze_pro_sekunde": 3, "max_dauer_s": 5})
    assert show.software_strobos == {"strobo"}
    strobo_halten(show)
    anzahl, zeiten = blitze_zaehlen(show, 0.0, 4.0)
    assert 4 <= anzahl <= 12
    abstaende = [b - a for a, b in zip(zeiten, zeiten[1:])]
    assert min(abstaende) >= 1 / 3 - 0.01                  # nie schneller als 3 Blitze pro Sekunde
    assert show.blitzt or anzahl


def test_strobo_ohne_einmessen_pausiert_nach_der_hoechstdauer(show):
    show.profil = dict(show.profil, strobo={"max_blitze_pro_sekunde": 3, "max_dauer_s": 5})
    strobo_halten(show, jetzt=0.0)
    blitze_zaehlen(show, 0.0, 5.2)
    for t in (5.3, 6.0):
        show.pult.halten_setzen("strobo", True, t)         # weiter gedrückt (die Taste hält höchstens 20 s)
    anzahl, _ = blitze_zaehlen(show, 5.3, 15.0)
    assert anzahl == 0                                     # Pause: 30 s kein Blitz


def test_strobo_ohne_einmessen_kein_dauerlicht_und_strobo_aus_gilt(show):
    show.profil = dict(show.profil, strobo={"max_blitze_pro_sekunde": 3, "max_dauer_s": 5})
    show.pult.programmer.setzen(["strobo"], {"helligkeit": 1.0})   # Helligkeit ohne Blitz-Wunsch
    anzahl, _ = blitze_zaehlen(show, 0.0, 1.0)
    assert anzahl == 0                                     # bleibt dunkel, kein grelles Dauerlicht
    show.pult.programmer.leeren()
    show.overrides.strobo_aus = True
    strobo_halten(show)
    anzahl, _ = blitze_zaehlen(show, 1.0, 3.0)
    assert anzahl == 0


def test_profil_ohne_strobo_blitzt_nicht(show):
    show.profil = dict(show.profil, strobo="aus")
    strobo_halten(show)
    anzahl, _ = blitze_zaehlen(show, 0.0, 2.0)
    assert anzahl == 0


def test_einmess_liste_zeigt_echten_strobo_zuerst_und_zuruecknehmen(show):
    client = TestClient(erstelle_app(show))
    strobos = client.get("/api/strobos").json()["strobos"]
    assert strobos[0]["id"] == "strobo" and strobos[0]["art"] == "software"
    kopf = next(g for g in strobos if not g["rein"])
    messungen = [{"wert": 10, "blitze": 5, "sekunden": 3}, {"wert": 60, "blitze": 30, "sekunden": 3}]
    assert client.post(f"/api/strobos/{kopf['id']}/auswerten", json={"messungen": messungen}).status_code == 200
    eintrag = next(g for g in client.get("/api/strobos").json()["strobos"] if g["id"] == kopf["id"])
    assert eintrag["eingemessen"] and eintrag["zuruecknehmbar"]
    antwort = client.post(f"/api/strobos/{kopf['id']}/zuruecksetzen")
    assert antwort.status_code == 200 and not antwort.json()["typ"].endswith("-eingemessen")
    eintrag = next(g for g in client.get("/api/strobos").json()["strobos"] if g["id"] == kopf["id"])
    assert not eintrag["eingemessen"]
    assert client.post("/api/strobos/strobo/zuruecksetzen").status_code == 400
