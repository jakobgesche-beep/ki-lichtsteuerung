# Lichtsteuerung der Technik-AG

Unser eigenes Programm für das Bühnenlicht. Es reagiert live und ohne Internet auf die Musik, folgt der Band durch geprobte Songs, hat ein Pult im Stil großer Lichtpulte (10 Fader pro Seite) und einen Licht-Chat, der auf Zuruf Looks programmiert. Alles ist auf einer 3D-Bühne im Browser zu sehen.

Ohne Hardware läuft alles im **Simulator**. Die DMX-Ausgabe ist beim Start immer aus.

## App für Mac und Windows

Die fertige App gibt es auf der [Website](https://jakobgesche-beep.github.io/ki-lichtsteuerung/), für den Mac (Apple-Chip und Intel) und für Windows 10/11. Sie braucht kein Python und aktualisiert sich selbst (nur per Knopf, nie von allein). Die Show-Daten liegen getrennt vom Programm, ein Update fasst sie nicht an:

- Mac: `~/Library/Application Support/Lichtsteuerung`
- Windows: `%APPDATA%\Lichtsteuerung` (das Programm selbst liegt in `%LOCALAPPDATA%\Programs\Lichtsteuerung`)

**Enttec unter Windows:** Einstecken genügt meistens, Windows lädt den FTDI-Treiber selbst. Findet das Programm das Enttec nicht, den Treiber von [ftdichip.com](https://ftdichip.com/drivers/vcp-drivers/) installieren („setup executable“) und das Enttec neu einstecken. Zadig ist nicht mehr nötig (geht aber weiterhin).
**Enttec am Mac:** einstecken, fertig. Blockiert der eingebaute Apple-Treiber den direkten Weg, nimmt das Programm von selbst den seriellen Port.
Das Enttec **DMX USB Pro** wird erkannt und geht genauso.

**Von einem Rechner zum anderen:** Setup → Sicherung → „Show sichern“ schreibt eine Datei in den Downloads-Ordner. Auf dem anderen Rechner Setup → Sicherung → „Show laden“, Programm schließen und neu öffnen. Der Claude-Schlüssel und der Ton-Eingang bleiben auf jedem Rechner für sich.

## Aus dem Quellcode starten

Du brauchst Python 3.9 oder neuer und für den ersten Start einmal Internet. Hol dir den Projektordner, dann:

**Mac oder Linux:** Doppelklick auf `start.command` (oder im Terminal `./start.command`).

**Windows:** Doppelklick auf `start.bat`.

Beim ersten Mal dauert es ein paar Minuten, danach geht der Browser von selbst auf. Falls nicht: <http://localhost:8000> öffnen. Beenden mit `Strg+C` im Terminalfenster.

> Fehlt Python: auf dem Mac im Terminal `xcode-select --install`, unter Windows von [python.org](https://www.python.org/downloads/) installieren (Haken bei „Add to PATH“ setzen).

## Erste Schritte ohne Hardware

1. View **Live**: Profil wählen, zum Beispiel „Schulfest Abend“. Bei „Quelle“ das Testsignal wählen. Die PARs wechseln jetzt im Takt die Farbe.
2. Tasten ausprobieren: `B` Blackout, `W` Warmweiß, `P` Automatik-Pause, `S` Strobo aus, Leertaste oder `→` Go+, `←` Go−.
3. View **Pult**: eine Gruppe antippen, Farbe und Dimmer wählen, **Store** drücken und einen leeren Fader antippen. Fader hochschieben, fertig.

## Die Reiter

| View | Wofür |
|---|---|
| Show | **Live fahren:** Song-Start, Konzert-Check, **Generalprobe**, **Rückblick**, **Handy-Fernbedienung**, Bühne live, Look-Tasten 1–9, Farben, Halte-Tasten, Tap-Tempo |
| Pult | **Programmieren wie an einem großen Pult:** Pools, Encoder, Cue-Liste, Pult-Tasten, 10 Fader pro Seite, Licht-Chat |
| Live | Profil, Musik-Automatik, Ton-Quelle, Cue-Liste, Fader |
| Probe | Songs aufnehmen, Teile erkennen und **von Hand richtigstellen**, Lichtshow bauen, „Probe ansehen“ |
| Setup | Patch (mit Patchplan), Profile, Katalog, DMX-Test (mit **Ein Gerät testen**), **MIDI**, **Sicherung** |

### Pult (wie MA, nur kleiner)

- **Pools** oben links: Gruppen, Geräte, Sequenzen. Gelb heißt ausgewählt, Rot heißt: steht im Programmer.
- **Feature-Leiste:** Dimmer, Position (auf den Grundriss tippen oder benannte Positionen), Farbe (Farben oder mischen), Gobo, Strahl (Strobo, höchstens 3 Blitze pro Sekunde), Effekt (Kreis, Acht, Schwenk, Welle, Puls, Farbwechsel …).
- **Pult-Tasten:** erst die Taste, dann das Ziel antippen.
  - **Store** → Fader: Programmer als neuer Cue (leerer Fader bekommt eine neue Sequenz). Store → Sequenz im Pool geht auch.
  - **Update** → Fader: Programmer in den laufenden Cue einarbeiten.
  - **Assign** → Sequenz, Gruppe oder „Tempo-Fader“ → Fader.
  - **Delete** → Fader (wird frei), Sequenz im Pool oder Cue in der Liste.
  - **Label** → Fader: beschriften. **Edit** → Fader: Cue-Liste bearbeiten (Namen, Zeiten, Reihenfolge).
  - **Oops** nimmt den letzten Schritt zurück. **Clear**: erst Auswahl, dann Programmer leeren. **Highlight** und **Blind** wie gewohnt.
- **Fader:** 10 pro Seite, 4 Seiten. Fader hoch startet die Sequenz, ganz runter schaltet sie aus. Go+, Go−, Flash (solange gedrückt), Aus. Fader-Arten: Sequenz, **Gruppen-Master** (Helligkeit einer Gruppe) und **Tempo** (alle Effekte langsamer oder schneller, Learn = im Takt tippen). Rechts der **Grand Master**.
- **Befehlszeile** (unten, immer da), deutsch oder englisch: `Group 2 At Full` · `Farbe Rot` · `Store Exec 5` · `Assign Sequence Intro At Exec 3` · `Exec 3 At 50` · `Go Exec 3` · `Off Exec 3` · `Delete Exec 3` · `Label Exec 3 Intro` · `Update` · `Page 2` · `Grandmaster At 80` · `Oops`.

### Licht-Chat (im Pult, rechts)

Schreib, was du sehen willst, zum Beispiel: „Spots langsam blau kreisen, PARs warmweiß atmen, auf Fader 3“. Der Vorschlag läuft erst nur in der **Vorschau** (Bühne zeigt „Vorschau Licht-Chat“), nichts geht live. Mit **Übernehmen** wird er gespeichert und auf den gewählten Fader gelegt, **Oops** nimmt beides zurück.

- **Mit Claude** (freie Sätze, auch Abläufe und Änderungen an vorhandenen Sequenzen): unten im Chat den Schlüssel aus der [Claude Console](https://console.anthropic.com) eintragen (API Keys). Er liegt nur auf diesem Rechner (`lokal.json` im Datenordner) und kommt nie in eine Sicherung. In der Claude Console ein **Ausgabenlimit** setzen. Der Chat zeigt ungefähr, was er bisher gekostet hat. Benutzt wird `claude-opus-5-5`; lehnt Claude eine Anfrage ab, springt automatisch ein anderes Claude-Modell ein (Rückfall-Einstellung der Schnittstelle).
- **Ohne Schlüssel oder ohne Internet** versteht der Chat einfache Sätze selbst und verzeiht Tippfehler: Gruppen („alle Lichter“), Farben, Helligkeit, Positionen, Effekte, Stile (Pop, Rock, Party, Ballade, Weihnachten, Jazz), „wirbeln/durcheinander“, Strobo, „langsam/schnell“, „in 3 Sekunden“, „auf Fader 4“.
- Claude bekommt nur Lichtdaten (Geräte, Gruppen, Positionen, Sequenzen), nie Ton oder Bilder. Jeder Vorschlag läuft durch dieselbe Prüfung wie alles andere (Strobo-Grenze, Publikum, Gobos).

### Probe und Song-Start

1. **Probe:** Name eingeben, „Aufnahme starten“, die Band spielt den Song einmal ganz (Ton-Quelle auf Live: Eingang vom X32). Taste **D** während der Aufnahme markiert Teilwechsel.
2. Das Programm erkennt Tempo, Takte und Teile und baut eine Sequenz mit einem Cue pro Teil.
3. **„Teile richtigstellen“:** jeden Teil anhören (▶ ab hier, das Licht läuft mit), umbenennen, Stärke ändern, Grenze um einen Takt verschieben, teilen, verbinden – oder mit einem Klick **deine D-Marken als Grenzen** nehmen. Danach „Show neu bauen“. Von Hand Richtiggestelltes bleibt.
4. **Show → Song-Start:** den Song antippen, wenn die Band anfängt. Etwas zu früh ist egal (die Uhr wartet auf die Band), etwas zu spät auch (sie holt auf). Fängt die Band sehr leise an: den Song **nochmal antippen** = jetzt geht es los.
5. Das Programm hört mit und vergleicht mit der Probe: Es folgt, wenn die Band schneller oder langsamer spielt, anders klingt oder das Publikum laut ist. Lässt die Band einen Teil aus oder wiederholt einen, springt es nach rund 2 Sekunden an die richtige Stelle. Fällt der Ton aus, läuft der Song im Tempo der Probe weiter. Hört die Band mitten im Song auf, wartet es.
6. Korrigieren geht immer: „Nächster Teil jetzt“ (Leertaste), „Teil zurück“ (←) oder auf einen Teil in der Zeitleiste klicken.

Song-Start und „Probe ansehen“ laufen auf einem eigenen Platz: Deine Fader im Pult bleiben, wie sie sind.

**Song-Erkennung (Show-Seite):** Das Programm hört auch zwischen den Songs zu und erkennt, welcher geprobte Song gerade gespielt wird, meistens nach 6 bis 10 Sekunden Musik. Dann springt das Licht an genau die Stelle, an der die Band ist.

- **Setlist:** „Reihenfolge ändern“ und mit den Pfeilen die Songs so ordnen, wie ihr sie spielt. Oben steht „Als Nächstes: …“.
- **Automatisch:** Der Song, der laut Setlist als Nächstes dran ist, startet von selbst, sobald er sicher erkannt ist. Spielt die Band einen anderen geprobten Song, erscheint nur ein großer Knopf „Klingt nach …, jetzt starten“ (ein falscher Song startet nie von selbst).
- **Vorschlagen:** Jeder erkannte Song erscheint nur als Knopf. **Aus:** nur von Hand.
- Von Hand starten (Song antippen) geht immer und ist sofort da.

**Akzente:** Die Probe findet die großen Schläge der Band (Crash-Becken, gemeinsame Schläge, Einsätze nach einer Pause). Dort blitzt das Licht kurz weiß auf, nicht in ruhigen Teilen. Auch die freie Musik-Automatik antwortet live auf große Schläge mit einem kurzen Aufleuchten. Ältere Proben bekommen die Schläge mit „Show neu bauen“.

### Show (live fahren)

- **Konzert-Check** (oben im Song-Start): grün = bereit, gelb = ansehen, rot = so geht es nicht. Er prüft Enttec und DMX, Ton-Signal, alle Songs, Profil und Strobo-Schild, Not-Tasten, Grand Master, Programmer, Ruhezustand und die heutige Sicherung.
- **Look-Tasten 1–9**, **Farben**, **Halten** (Weiß voll F, Strobo, Dunkel – nur solange gedrückt), **Tap** (T). Sie gehen immer, auch ganz ohne Musik-Erkennung. 0 = Look aus.
- Die großen Tasten oben (Blackout, Warmweiß, Pause, Strobo aus) gelten auf jeder Seite und haben immer Vorrang.
- **Applaus- und Pausenlicht** (Haken auf der Show-Seite): Ist ein Song zu Ende und das Publikum klatscht, wird die Bühne hell und warm. Hört das Klatschen auf, kommt ein ruhiges Pausenlicht, bis der nächste Song startet. Jede Look-Taste beendet es sofort.
- **Songs mitschneiden** (Haken auf der Show-Seite): Jeder Song, der mit Song-Start läuft, wird mitgeschnitten (bleibt auf dem Laptop). Wenn gerade kein Song läuft, ordnet das Programm den Mitschnitt der Probe zu. Danach erkennt es den Song noch sicherer. Weitere Aufnahmen gehen auch in der Probe („Weitere Aufnahme“, „Aus Datei“).

### Generalprobe, Rückblick, Handy (Show-Seite, oben)

- **Generalprobe:** spielt jeden Song der Setlist zweimal so durch, wie er live klingen könnte (etwas schneller, anderer Mix, Publikum; dann langsamer, mit Hall und lautem Publikum). Für jeden Song gibt es eine Ampel: Wurde er erkannt und wie schnell, kamen die Teilwechsel pünktlich? Dauert etwa 15 Sekunden pro Song-Minute, nicht während des Konzerts starten. Der Konzert-Check zeigt das Ergebnis.
- **Rückblick:** Logbuch des Abends: welcher Song wann lief und wie er gestartet wurde, wie sicher das Programm mitgehört hat, wo von Hand korrigiert wurde, Ton weg, DMX weg. Dazu Hinweise, was man in der Probe üben sollte.
- **Handy …:** Fernbedienung einschalten, QR-Code mit dem Handy scannen (oder Adresse und 6-stellige PIN eintippen). Das Handy kann Looks, Farben, Halte-Tasten, Tap, Blackout, Song-Teile und die Songs der Setlist. Patch und Einstellungen sind von dort nie erreichbar. Handy und Laptop müssen im selben WLAN sein. Nach jedem Start ist die Fernbedienung aus.

### MIDI (Setup → MIDI)

- **MIDI-Controller** (zum Beispiel Akai APC mini) am USB: Gerät wählen, dann pro Aufgabe „Lernen“ drücken und am Gerät den Regler bewegen oder die Taste drücken. Fertige Belegungen gibt es für APC mini, Korg nanoKONTROL2 und Behringer X-Touch Mini (ohne Gerät gebaut, darum einmal ausprobieren). Ein echter Fader übernimmt erst, wenn er am Wert der Software vorbeikommt.
- **MIDI-Clock:** Schickt die Band einen Click über MIDI, laufen alle Effekte genau in diesem Tempo. Tap geht trotzdem vor.

### Ein Gerät testen (Setup → DMX-Test)

Für den ersten Test mit einem neuen Gerät: Startadresse und Kanal-Anzahl (aus der Anleitung) eingeben, „Test starten“. Nur dieses Gerät bekommt Werte, alle anderen Kanäle bleiben auf 0. Pro Kanal eintragen, was er macht (Pan, Tilt, Dimmer, Rot …), dann helfen die Knöpfe Licht an, Rot, Grün, Blau, Mitte, Bewegen. „Speichern und patchen“ legt das Gerät als eigenen Typ an und patcht es auf die nächste freie Adresse. Reagiert gar nichts: am Gerät die Adresse („A001“) und den DMX-Betrieb prüfen, Kabel/Adapter (5-polig auf 3-polig) prüfen, oder oben die andere **Enttec-Art** (Open DMX oder DMX USB Pro) wählen.

## Ablauf vor jeder Veranstaltung

1. Laptop ans **Netzteil**, Deckel offen lassen (das Programm verhindert den Ruhezustand, solange es läuft).
2. Laptop per USB mit X32 und Enttec verbinden. Programm starten, Profil laden, auf **Live** den X32-Eingang als Quelle wählen (wird gemerkt).
3. **Show → Konzert-Check** öffnen, bis alles grün ist (DMX einschalten geht dort mit einem Knopf). Nach der letzten Probe einmal die **Generalprobe** laufen lassen.
4. **Setup → DMX-Test**: jedes Licht kurz einzeln an. Override-Tasten einmal ausprobieren.
5. **Setup → Sicherung → Show sichern** auf einen USB-Stick. Dann geht es los.

## Wie das Programm aufgebaut ist

Der beste Einstieg ist [show.py](lichtsteuerung/show.py). Dort steht, wie ein DMX-Bild entsteht, 40-mal pro Sekunde:

```
Automatik (Engine) → Fader und Song → Programmer → Gruppen-Master → Halten → Grand Master → Profil-Grenzen → Override-Tasten → DMX-Zahlen → Prüfung → Ausgabe
```

| Datei | Aufgabe |
|---|---|
| `katalog.py`, `patch.py`, `buehne.py` | Geräte, Adressen, Bühne |
| `render.py` | Eigenschaften („Rot, 80 %“) werden DMX-Zahlen. Nur hier kommen Kanäle vor |
| `pruefung.py`, `sicherheit.py`, `sperrzone.py` | Jeder Wert wird geprüft |
| `pantilt.py` | Rechnung für die Moving Heads |
| `audio/`, `engine.py` | Musik analysieren, Regeln fürs Licht; `audio/folgen.py` folgt der Band durch einen Song |
| `pult.py` | Programmer, Effekte, Sequenzen, Fader (Seiten, Arten, Flash, Oops) |
| `befehle.py` | die Befehlszeile |
| `licht_chat.py` | Licht-Chat (Claude und einfache Sätze ohne Internet) |
| `probe.py`, `songspieler.py` | Probe, Teile richtigstellen, Song-Start |
| `sicherung.py`, `konzertcheck.py`, `wachhalten.py` | Show sichern und laden, Konzert-Check, kein Ruhezustand |
| `szenen.py`, `profile.py`, `overrides.py`, `vorschau.py` | Werte auflösen, Profile, feste Tasten, Entwürfe |
| `dmx_ausgabe.py`, `simulator.py` | Enttec (drei Wege, wiederverbinden) und 3D-Vorschau |
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

Am besten die **Handy-Fernbedienung** auf der Show-Seite benutzen (mit PIN, nur die Show-Tasten). `./start.command --netz` macht dagegen die ganze Oberfläche im Netzwerk erreichbar, ohne Passwort: Jeder im selben Netz kann dann alles bedienen. Also nur im eigenen Netz der Technik-AG und nur zum Entwickeln benutzen.

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
