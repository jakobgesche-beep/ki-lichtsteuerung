# Annahmen im ersten Entwurf

Hier steht alles, was die Projektbeschreibung offen ließ, und wie es jetzt gelöst ist. Jeder Punkt lässt sich später ändern.

## Offene Fragen aus der Beschreibung

| Frage | Annahme | Ändern |
|---|---|---|
| Variante A oder B | **Variante B:** 1 Hero Spot 60 und Hazer, so wie im Aufbau-Bild. Für A im Patch den Hazer entfernen und einen zweiten Hero Spot patchen | Reiter Patch |
| DMX-Modi und Adressen | Jeweils der größte Modus, Adressen lückenlos: PARs 1–48 (8 Kanäle), MH-X25 49 und 61 (12), Hero Spot 73 (14), Hazer 87 (2) | Reiter Patch |
| Laptop | Entwickelt und getestet auf macOS. `start.bat` für Windows ist ungetestet, Raspberry Pi ebenso | |
| Open DMX oder USB Pro | Open DMX. Das Pro spricht ein anderes Protokoll und bräuchte eine eigene Klasse in `dmx_ausgabe.py` | |
| Bühne und Positionen | Platzhalter-Bühne 8 × 5 m, 0,8 m hoch, Publikum ab 2 m vor der Kante. Traverse auf der Bühne, also 3,9 m über dem Hallenboden | `stage.json`, `positions.json` |
| X32-Kanäle | Noch leer | `x32.json` |
| API-Kosten | Noch nicht nötig, die Claude-API kommt erst in Schritt 8 | |
| Strobo-Obergrenze | **3 Blitze/s, 5 s Dauer, danach 30 s Pause.** Geschätzt nach der üblichen Empfehlung zum Schutz von Menschen mit Epilepsie, muss die Lehrkraft festlegen | `sicherheit.json` |

## Geräte

- **Quad Par und Hero Spot 60** fehlen in der Open Fixture Library. Ihre Daten stammen aus der Gerätebibliothek von QLC+. Gewicht, Winkel, Modi und Pan/Tilt stimmen mit der Hardware-Tabelle überein.
- **Alle vier Geräte sind noch nicht mit dem Handbuch abgeglichen** und im Patch als „ungeprüft“ markiert. Nach dem Abgleich `handbuch_geprueft` im Katalog-Eintrag auf `true` setzen.
- **Der Quad Par hat laut Suche auch eine 45°-Version.** Wir nehmen 25° wie in der Tabelle.
- **Strobo-Tempo:** Für alle unsere Geräte steht in den Daten nur „langsam bis schnell“, ohne Hertz. Das Programm kann so nicht sicherstellen, dass die Grenze hält, und **sperrt ihr Strobo deshalb komplett**. Auch im Profil „Schulfest Abend“ blitzt also nichts. Zum Freischalten im Katalog-Eintrag beim Strobo-Bereich `hz_von` und `hz_bis` aus dem Handbuch eintragen.

## Aufbau und Verhalten

- **Reihenfolge der Ebenen:** Automatik, darüber Cues, darüber Fader, dann Profil-Grenzen, zuletzt Override-Tasten. Die Prüfung läuft danach über die fertigen DMX-Zahlen, egal woher sie kommen.
- **Profil-Grenzen für Cues:** Maximale Helligkeit und Strobo gelten auch für Cues. Palette und Bewegung gelten nur für die Engine, denn Cues sind von Menschen programmiert.
- **Automatik Pause** blendet aufs Grundlicht, sie friert das Bild nicht ein. Sonst könnte es mitten im Strobo stehen bleiben.
- **Warmweiß:** alle Geräte 70 %, Moving Heads ohne Ziel zeigen auf die Position „Mitte“.
- **Blackout** gilt auch für rohe Werte aus dem DMX-Test.
- **Strobo aus** bleibt an, bis man die Taste wieder drückt.
- **Sicherer Rückfall:** Keine frischen Messwerte seit 0,5 s, Fehler in der Analyse oder in den Regeln führen zum Grundlicht. Misslingt ein ganzes Bild, bleibt das letzte stehen.
- **Beim Neustart** kommen letztes Profil und letzte Cueliste zurück. Die Liste wird nur geladen, nicht gestartet, und DMX bleibt aus.
- **Wartezeit im Cue:** 0 heißt, der nächste Cue wartet auf „Weiter“. Sonst geht es nach Einblenden plus Wartezeit von allein weiter.
- **Überschneidende Adressen** werden rot markiert, aber nicht verboten, denn zwei Geräte auf gleicher Adresse können gewollt sein. Über 512 ist gesperrt.
- **Grundlicht** steht direkt im Profil und nicht als eigene Szene. So ist der Rückfall auch da, wenn jemand eine Szene löscht.
- **Der Hazer** bekommt nur Werte, wenn das Profil ihn erlaubt. Alle vier Profile verbieten ihn. Die Automatik benutzt ihn nie, nur eine Cue mit `nebel`.
- **Ein vergessener DMX-Test** endet nach 2 Minuten von selbst.
- **Acht Fader.** Gruppen-Fader begrenzen die Helligkeit, Szenen-Fader blenden eine Szene dazu. Die Belegung wird gespeichert, die Stellung nicht.
- **Kein Passwort** für die Oberfläche. Ohne `--netz` ist sie nur vom Laptop selbst erreichbar.

## Zusätzliche Sicherheit, die nicht in der Beschreibung stand

- **Blitz-Wächter:** Auch schnelles Hell-Dunkel und Farbsprünge im Takt können Anfälle auslösen. Die Strobo-Grenze gilt deshalb auch für Helligkeits-Sprünge und Farbschritte der Engine.
- **Unbekanntes Strobo ist verboten.** Das gilt auch für Strobo in Effekt-Kanälen.
- **Programm- und Reset-Kanäle** bleiben immer auf ihrem Standardwert.
- **Ein Moving Head ohne Ort in `stage.json`** bleibt dunkel, weil die Sperrzone für ihn nicht prüfbar ist.

## Rechnung und Sperrzone

- **Nullstellung:** Die Mitte des DMX-Bereichs gilt als Pan 0°, Tilt 0°: stehend nach oben, hängend nach unten. Das muss am echten Gerät geprüft werden. Falls Pan oder Tilt falsch herum läuft, gibt es in `stage.json` pro Gerät `pan_umkehren` und `tilt_umkehren`. Am Gerät umgedrehtes Pan/Tilt wird dort genauso eingetragen.
- **Sperrzone:** ein Kasten über dem Publikum bis 2 m Höhe, 0,5 m Sicherheitsabstand. Geprüft werden die Strahlmitte und vier Punkte am Kegelrand. Zielt ein Kopf hinein, bleibt er auf der letzten sicheren Stellung. Gibt es keine, bleibt er dunkel.
- **Grenze der Sperrzone:** Geprüft wird die Zielstellung. Springt ein Kopf zwischen zwei erlaubten Zielen, kann er auf dem Weg kurz durch die Zone schwenken. Die Bewegungen der Engine bleiben auf der Bühne, in Cues muss man darauf achten.

## Technik

- **aubio** braucht auf neuen Macs eine Compiler-Einstellung, die `start.command` setzt. Klappt es nicht, springt die eigene Beat-Erkennung ein. Sie ist einfacher und liegt bei Musik ohne klaren Takt öfter daneben.
- **Beat-Uhr:** aubio lässt auch bei klarem Takt einzelne Schläge aus. Eine kleine Uhr läuft deshalb im erkannten Tempo weiter, höchstens 6 s lang.
- **Rede-Erkennung** aus dem Ton ist eine grobe Schätzung. Zuverlässig wird das erst mit dem X32 in Schritt 10.
- **Enttec:** Der Code folgt pyopendmx und ist nur gegen ein nachgebautes Gerät getestet. pyftdi braucht `libusb` (Mac) oder einen WinUSB-Treiber (Windows). Solange der fehlt, meldet das Programm „Kein Enttec gefunden“.
- **Die Enttec-Suche** erkennt jeden FTDI-Chip mit dieser Kennung, also auch ein USB Pro oder andere USB-Kabel.
- **Open Fixture Library:** 645 Geräte sind importiert, 8 Sonderfälle mit ungewöhnlichem Aufbau fehlen. Schaltbare Kanäle gelten in ihrer ersten Stellung.
- **GDTF:** nur gegen eine selbst gebaute Beispieldatei getestet. QLC+-Import gegen die echte Datei des Hero Spot 60.
- **Die genaue Lage** eines Geräts (x, y, z, Drehung, Neigung) trägt man in `stage.json` ein, solange es die Klick-Oberfläche aus Schritt 11 nicht gibt.

## Vorbereitet für die Schritte 8 bis 12

| Schritt | Wo es andockt |
|---|---|
| 8 Licht-Chat | Die Werkzeuge rufen `show.vorschau.entwurf_setzen("szene", ...)` und `uebernehmen()` auf, dazu `FaderBank.belegen` und `pruefe_cueliste`. Der Key gehört in `lokal.json`, die Git ignoriert |
| 9 Profile per API | `entwurf_setzen("profil", ...)` samt Prüfung und Speichern gibt es schon und ist getestet |
| 10 X32 | Das Modul setzt `show.overrides` oder einen eigenen Rede-Eingang und liest `x32.json`. Audio vom X32 läuft schon über `audio.quellen.Eingang` mit Kanalwahl |
| 11 Klick-Positionen | `pantilt.py`, `szenen.zeige_auf` und die Versatz-Felder in `stage.json` sind fertig und getestet. Es fehlt nur die Oberfläche |
| 12 Generalprobe | Handbuch-Abgleich, Einmessen, Enttec testen |
