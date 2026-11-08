# Lichtsteuerung der Technik-AG

Unser eigenes Programm für das Bühnenlicht. Es reagiert live und ohne Internet auf die Musik, hält sich an ein gewähltes Veranstaltungsprofil und zeigt alles auf einer 3D-Bühne im Browser.

Der erste Entwurf läuft komplett **ohne Hardware** im Simulator. Die DMX-Ausgabe ist beim Start immer aus.

## App für Mac und Windows

Die fertige App gibt es auf der [Website](https://jakobgesche-beep.github.io/ki-lichtsteuerung/), für den Mac (Apple-Chip und Intel) und für Windows 10/11. Sie braucht kein Python und aktualisiert sich selbst. Die Show-Daten liegen getrennt vom Programm, ein Update fasst sie nicht an:

- Mac: `~/Library/Application Support/Lichtsteuerung`
- Windows: `%APPDATA%\Lichtsteuerung` (das Programm selbst liegt in `%LOCALAPPDATA%\Programs\Lichtsteuerung`)

Unter Windows braucht das Enttec Open DMX einmal den WinUSB-Treiber: [Zadig](https://zadig.akeo.ie/) öffnen, „FT232R USB UART“ wählen, WinUSB installieren.

## Aus dem Quellcode starten

Du brauchst Python 3.9 oder neuer und für den ersten Start einmal Internet. Hol dir den Projektordner, dann:

**Mac oder Linux:** Doppelklick auf `start.command` (oder im Terminal `./start.command`).

**Windows:** Doppelklick auf `start.bat`.

Beim ersten Mal dauert es ein paar Minuten, danach geht der Browser von selbst auf. Falls nicht: <http://localhost:8000> öffnen. Beenden mit `Strg+C` im Terminalfenster.

> Fehlt Python: auf dem Mac im Terminal `xcode-select --install`, unter Windows von [python.org](https://www.python.org/downloads/) installieren (Haken bei „Add to PATH“ setzen).

## Erste Schritte ohne Hardware

1. View **Live**: Profil wählen, zum Beispiel „Schulfest Abend“.
2. Ebenfalls auf **Live**: Bei „Quelle“ das Testsignal wählen oder eine Audiodatei. Die PARs wechseln jetzt im Takt die Farbe.
3. Tasten ausprobieren: `B` Blackout, `W` Warmweiß, `P` Automatik-Pause, `S` Strobo aus, Leertaste oder `→` Go+, `←` Go−.
4. View **Programmieren**: eine Show programmieren, siehe unten.

## Die Reiter

Oben wählst du die **View**, wie an einem Lichtpult:

| View | Wofür |
|---|---|
| Show | **Live fahren:** Song-Start (ein Druck, dann läuft der ganze Song), Bühne live in 3D, Look-Tasten, Farben, Halte-Tasten, Tap-Tempo |
| Live | 3D-Bühne, Cue-Liste (Klick springt zum Cue), Ton, Profil, Musik-Automatik, Executoren |
| Programmieren | Pools mit Gruppen, Geräten, Farben, Positionen, Gobos und Effekten, Fixture-Sheet, Encoder, Speichern |
| Probe | Song aufnehmen oder als Datei laden: Tempo und Songteile erkennen, Lichtshow bauen |
| Setup | Patch (mit Patchplan zum Ausdrucken), Profile, Katalog, DMX-Test |

Gelb heißt ausgewählt, Rot heißt: steht im Programmer. Unten ist immer die **Befehlszeile**, zum Beispiel:
`Gerät 1 bis 3 auf 80` · `Gruppe Spots Farbe Rot Gobo 3 Effekt Kreis` · `Speichern` · `Speichern Cue 2` · `Leeren` · `Go`.
Englisch geht auch: `Fixture 1 Thru 3 At Full`. Zahlen tippen springt direkt in die Befehlszeile.

**So programmierst du eine Show (wie bei grandMA):**

1. View **Programmieren**: Geräte oder eine Gruppe antippen.
2. Farbe, Position (auf den Grundriss tippen), Gobo und Effekt wählen. Mit „Blind“ siehst du es nur in der Vorschau.
3. Cue-Namen eingeben, „Als neuen Cue speichern“. Danach den nächsten Cue einstellen und speichern.
4. „Programmer leeren“, die Sequenz unten auf einen Executor legen und mit **Go+** (Leertaste oder →) und **Go−** (←) abspielen.

**Show aus der Probe:** In der View **Probe** einen Namen eingeben und „Aufnahme starten“, während die Band den Song spielt (Tonquelle auf der Live-Seite: Eingang vom X32). Danach erkennt das Programm Tempo, Takte und Songteile (Intro, Strophe, Refrain, Bridge …) und legt eine Sequenz mit einem Cue pro Teil an. „Probe ansehen“ spielt die Aufnahme ab, und das Licht wechselt genau an den erkannten Stellen. Ältere Aufnahmen: „Show neu bauen“ analysiert sie mit der neuen Erkennung noch einmal.

**Live fahren (View Show):**

- **Song-Start:** Den Song antippen, wenn die Band anfängt. Dann läuft der ganze Song von selbst durch. Das Programm hört mit und vergleicht mit der Probe-Aufnahme, so bleibt es auch dran, wenn die Band schneller oder langsamer spielt. Groß angezeigt: welcher Teil jetzt läuft, wie viele Takte und Sekunden noch, was danach kommt. Fällt der Ton aus, läuft der Song im Tempo der Probe weiter. Hört die Band mitten im Song auf, wartet das Programm.
- **Korrigieren:** „Nächster Teil jetzt“ (Leertaste), „Teil zurück“ (←) oder einfach auf einen Teil in der Zeitleiste klicken. Der Song läuft von dort weiter.
- **Bühne live:** Oben rechts zeigt die 3D-Bühne, was die Lichter gerade tun. Darüber steht, was das Licht steuert: gehaltene Taste, Look, Song oder Automatik.
- **Look-Tasten 1 bis 9:** Ruhig, Strophe, Aufbau, Refrain, Höhepunkt, Drop!, Solo, Ballade, Schluss. Sie gehen immer, auch ganz ohne Musik-Erkennung. 0 = Look aus, dann ist wieder der Song oder die Automatik zu sehen.
- **Farben:** Farbe 1 und Farbe 2 gelten für alle Looks, ein Druck ändert den laufenden Look mit.
- **Halten:** Weiß voll (Taste F), Strobo und Dunkel gelten nur, solange du drückst.
- **Tap:** Ein paar Mal im Takt auf TAP (Taste T) tippen, dann laufen alle Effekte in diesem Tempo. „Tempo vom Ton“ schaltet zurück.

Ein Cue speichert nur, was du geändert hast. Alles andere bleibt aus dem vorigen Cue stehen, wie bei grandMA („Tracking“). Der Fader eines Executors blendet seine Sequenz über die Musik-Automatik.

Die großen Tasten oben gelten auf jeder Seite und haben immer Vorrang vor Automatik und Cues.

## Ablauf vor jeder Veranstaltung

1. Laptop per USB mit X32 und Enttec verbinden, LAN-Kabel zum X32 stecken.
2. Programm starten und Profil laden.
3. **Setup → DMX-Test**: Ausgabe einschalten, jedes Licht kurz einzeln an.
4. Override-Tasten einmal ausprobieren, dann geht es los.

## Wie das Programm aufgebaut ist

Der beste Einstieg ist [show.py](lichtsteuerung/show.py). Dort steht, wie ein DMX-Bild entsteht, 40-mal pro Sekunde:

```
Automatik (Engine) → Executoren → Programmer → Profil-Grenzen → Override-Tasten → DMX-Zahlen → Prüfung → Ausgabe
```

| Datei | Aufgabe |
|---|---|
| `katalog.py`, `patch.py`, `buehne.py` | Geräte, Adressen, Bühne |
| `render.py` | Eigenschaften („Rot, 80 %“) werden DMX-Zahlen. Nur hier kommen Kanäle vor |
| `pruefung.py`, `sicherheit.py`, `sperrzone.py` | Jeder Wert wird geprüft |
| `pantilt.py` | Rechnung für die Moving Heads |
| `audio/`, `engine.py` | Musik analysieren, Regeln fürs Licht |
| `pult.py` | Programmer, Auswahl, Effekte, Sequenzen und Executoren |
| `befehle.py` | die Befehlszeile |
| `probe.py`, `patchplan.py` | Probe und Patchplan |
| `szenen.py`, `profile.py` | Werte auflösen, Profile |
| `overrides.py` | die festen Tasten |
| `vorschau.py` | Entwürfe erst zeigen, dann übernehmen |
| `dmx_ausgabe.py`, `simulator.py` | Enttec und 3D-Vorschau |
| `server.py`, `web/` | Oberfläche im Browser |

Die Show-Daten liegen als JSON-Dateien im Projekt: `fixtures.json` (Patch), `stage.json` (Bühne), `positions.json`, `x32.json`, `sicherheit.json`, `catalog/`, `profile/`, `cues/`. Was geschätzt ist, trägt den Vermerk `platzhalter` oder `_hinweis`. Wer eine Datei von Hand ändert, beendet vorher das Programm.

## Tests

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Die Tests laufen ohne Hardware und ohne Internet.

## Katalog aktualisieren

```sh
.venv/bin/python -m lichtsteuerung.importe.ofl
```

Das braucht Internet und läuft nie während einer Show.

## Für das Tablet

`./start.command --netz` macht die Oberfläche im Netzwerk erreichbar. Es gibt kein Passwort: Jeder im selben Netz kann das Licht bedienen. Also nur im eigenen Netz der Technik-AG benutzen.

## Neue Version veröffentlichen

1. In `lichtsteuerung/version.py` die Nummer erhöhen, zum Beispiel auf `1.1.0`, und committen.
2. `git tag v1.1.0` und `git push origin main v1.1.0`.

GitHub testet und baut dann alles selbst (Mac auf macOS, Windows auf einem Windows-Rechner samt stiller Installation und Selbsttest) und legt das Release an. Jede installierte App findet es beim nächsten Start. Nur Windows ausprobieren, ohne Release: den Stand auf den Zweig `win-probe` pushen. Die Website im Ordner `site/` geht bei jedem Push auf `main` von selbst online.

## Website auf Cloudflare

Die `wrangler.toml` liegt bereit. Einmal im Cloudflare-Konto unter Workers & Pages → Create → Import a repository das Repo `ki-lichtsteuerung` wählen. Danach baut Cloudflare bei jedem Push von selbst.

## Quellen und Lizenzen

- Gerätedaten: [Open Fixture Library](https://github.com/OpenLightingProject/open-fixture-library) (MIT) und [QLC+](https://github.com/mcallegari/qlcplus) (Apache-2.0). Die Lizenztexte liegen in `catalog/`.
- 3D: [three.js](https://threejs.org) (MIT), liegt in `web/vendor/`, damit alles offline läuft.
- Beat-Erkennung: [aubio](https://aubio.org) steht unter der GPL. Es wird nur beim Start aus dem Quellcode nachinstalliert. Die fertige Mac-App enthält es nicht und nimmt die eigene Beat-Erkennung. Soll es mit in die App, muss das Projekt selbst unter die GPL.

Annahmen und offene Punkte stehen in [ANNAHMEN.md](ANNAHMEN.md), die vollständige Vorgabe in [CLAUDE.md](CLAUDE.md).
