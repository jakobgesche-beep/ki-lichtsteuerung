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
- **Strobo ohne Namen:** eigener Gerätetyp mit 2 Kanälen (Tempo und Helligkeit, beide Reihenfolgen als Modus), Wert 0 heißt „blitzt nicht“. Gepatcht auf Adresse 110, Gruppe „Strobo“. Bis er eingemessen ist, bleibt er gesperrt.
- **Strobo einmessen (Setup → DMX-Test):** Nur mit bestätigtem Haken („Lehrkraft dabei, niemand reagiert empfindlich auf Blitzlicht“). Der Strobo blitzt je 3 Sekunden mit einem Wert, man zählt die Blitze (Zeitlupe vom Handy). Aus mindestens zwei Werten wird ein Tempo-Bereich berechnet. Nur der gemessene Bereich wird freigegeben, darüber und darunter bleibt gesperrt. „Strobo aus“ und Blackout gelten auch beim Einmessen. Das geht genauso für den Shutter der Moving Heads, deren übrige Bereiche (zu, offen) bleiben dabei unverändert.
- **Strobo in der Automatik:** nur beim Drop, nur wenn das Profil Strobo erlaubt, höchstens 4 Sekunden und höchstens 3 Blitze pro Sekunde.
- **Strobo-Tempo:** Für alle unsere Geräte steht in den Daten nur „langsam bis schnell“, ohne Hertz. Das Programm kann so nicht sicherstellen, dass die Grenze hält, und **sperrt ihr Strobo deshalb komplett**. Auch im Profil „Schulfest Abend“ blitzt also nichts. Zum Freischalten im Katalog-Eintrag beim Strobo-Bereich `hz_von` und `hz_bis` aus dem Handbuch eintragen.

## Aufbau und Verhalten

- **Reihenfolge der Ebenen:** Automatik, darüber Cues, darüber Fader, dann Profil-Grenzen, zuletzt Override-Tasten. Die Prüfung läuft danach über die fertigen DMX-Zahlen, egal woher sie kommen.
- **Profil-Grenzen für Cues:** Maximale Helligkeit und Strobo gelten auch für Cues. Palette und Bewegung gelten nur für die Engine, denn Cues sind von Menschen programmiert.
- **Automatik Pause** blendet aufs Grundlicht, sie friert das Bild nicht ein. Sonst könnte es mitten im Strobo stehen bleiben.
- **Warmweiß:** alle Geräte 70 %, Moving Heads ohne Ziel zeigen auf die Position „Mitte“.
- **Blackout** gilt auch für rohe Werte aus dem DMX-Test.
- **Strobo aus** bleibt an, bis man die Taste wieder drückt.
- **Beim allerersten Start** ist „Schulfest Abend“ aktiv, damit das Licht sofort auf Musik reagiert. Das Profil „Ruhe“ gilt nur, wenn gar keins geladen werden kann.
- **Passt das Grundlicht zu keinem gepatchten Gerät**, leuchten alle Geräte warmweiß mit 50 %. Die Bühne bleibt nie dunkel, weil Gruppen nicht passen.
- **Geräte ohne Gruppe** zählen nach ihren Fähigkeiten: Pan oder Tilt als Spots, Nebel als Dunst, alles andere als Farb-PARs.
- **Moving Heads hängen an der Traverse** (Vorgabe des Nutzers, abweichend von der Projektbeschreibung). Mit 6 PARs, 2 MH-X25 und Hero Spot sind das 9 Geräte, die Traverse trägt 8: Das Programm warnt dann.
- **Die Automatik arbeitet mit Looks** (Wunsch des Nutzers: ruhiger, „auf den Punkt“). Ein Look (Farbe, Gobo, Stand oder Bewegung, Art des Pulses) bleibt mindestens 16 Beats stehen und wechselt am Ende einer Phrase, wenn die Musik stärker oder ruhiger wird, sonst nach 32 Beats. Ein Drop (von ruhig/mittel direkt auf Höhepunkt) wechselt sofort, mit einem Akzent „doppelt hell“.
- **Drop-Erkennung:** Ein Drop braucht einen Aufbau (Höhen steigen 4 Sekunden stetig, deutlich hörbar, der Bass-Anteil sinkt) oder einen Break (mindestens 2 Sekunden 13 dB leiser als sonst). Dann muss der „Wumms“ (40 bis 300 Hz, so hört man ihn auch über kleine Lautsprecher) laut einschlagen, und der Klang wird so bass-lastig wie an den bass-lastigsten Stellen des Songs. Eine Snare im Wirbel erfüllt das nicht. Danach 15 Sekunden kein zweiter Drop.
- **Getestet** nur mit künstlichen Songs: voller Bass bei 100, 128 und 174 BPM auf 10 bis 70 ms genau; wie über einen Handy-Lautsprecher bis 100 ms genau, ohne Pause bis zu einem Beat zu spät; kein Fehlalarm bei Strophe zu Refrain, Becken-Crescendo, Klavier. Eine fast stille Bridge mit danach voller Band zählt absichtlich als Drop.
- **Abstimmen auf echte Songs:** In der Probe während der Aufnahme Taste D drücken, wenn der Drop kommt. Die Probe speichert Ton, erkannte Drops und markierte Stellen. Damit lässt sich die Erkennung nachträglich anpassen.
- **Stärke der Musik** misst die Automatik im Vergleich zur letzten Minute (Intensität), nicht absolut. So kommt der lauteste Teil auch über ein leises Mikrofon auf „Höhepunkt“.
- **Aufbau** wird erkannt, sobald er deutlich steigt, im Test 3 bis 4 Sekunden vor dem Drop, nicht schon ganz am Anfang.
- **Licht beim Drop:** Aufbau: Strahlen zur Mitte, heller und weißer, tieferer Puls. Pause: fast dunkel. Drop: 0,25 s weiß und voll, dann zwei kräftige Farben, jeder Beat ein harter Schlag (unter 3 Blitzen pro Sekunde, auch bei 174 BPM), große schnelle Bewegung, drehende Gobos, 32 Beats lang. Danach ein starker Look. Nur in Profilen mit `beat_reaktion` ab 0,5.
- **Schnelleres Flackern im Aufbau** gibt es bewusst nicht: Mehr als ein Puls pro Beat läge über der Epilepsie-Grenze von 3 pro Sekunde.
- **Lebendigkeit zwischen „zu viel“ und „zu wenig“:** Ruhige Looks schwenken langsam, starke bewegen sich in 4 bis 8 Beats pro Runde mit einem kleinen Schub auf dem Beat, höchstens 220° pro Sekunde. Starke Looks wechseln nach 16 Beats, ruhige nach 32, jeder bleibt mindestens 8 Beats. Gemessen am Test-Song: etwa 25 Farbwechsel pro Minute und 75 % der Zeit Bewegung (Version 1.3: 55 und 100 %, Version 1.4: 12 und 23 %).
- **Gobos und Drehung** nutzt die Engine ab `beat_reaktion` 0,3 (Drehung ab 0,5), ein Gobo pro Look. Die Bilder in der 3D-Ansicht sind Beispiele, die echten Motive stehen nicht in den Gerätedaten.
- **Sicherer Rückfall:** Keine frischen Messwerte seit 0,5 s, Fehler in der Analyse oder in den Regeln führen zum Grundlicht. Misslingt ein ganzes Bild, bleibt das letzte stehen.
- **Beim Neustart** kommen letztes Profil und letzte Cueliste zurück. Die Liste wird nur geladen, nicht gestartet, und DMX bleibt aus.
- **Aussehen wie ein Lichtpult** (Wunsch: wie grandMA3 und ChamSys), ohne deren Namen oder Logos zu übernehmen. Die Auswahl liegt im Programm, nicht im Browser: Befehlszeile, Bildschirm und später die KI sehen dieselbe Auswahl.
- **Gerätenummern** in der Befehlszeile sind die Reihenfolge im Patch (1, 2, 3 …).
- **Pult wie grandMA, aber kleiner:** Programmer, 8 Executoren mit Fader, Go+, Go− und Aus, Sequenzen mit Tracking. Die alten Cuelisten und Fader sind dadurch ersetzt.
- **Reihenfolge der Ebenen:** Automatik, darüber die Executoren (der zuletzt gestartete oben), darüber der Programmer, zuletzt die Not-Tasten. Der Executor-Fader blendet seine Sequenz über das, was darunter liegt.
- **Folgezeit im Cue (`folgen_s`):** leer heißt, der nächste Cue wartet auf Go+. Sonst geht es nach Überblenden plus Folgezeit von allein weiter. Nach dem letzten Cue fängt Go+ wieder beim ersten an.
- **Ein Cue ohne `effekte`** lässt laufende Effekte weiterlaufen (Tracking). Mit `"effekte": []` hält er sie an.
- **Programmer ist live,** wie am echten Pult. „Blind“ zeigt ihn nur in der Vorschau. Die KI soll später nur im Blind-Modus arbeiten dürfen.
- **Die maximale Helligkeit des Profils** gilt auch für Programmer und Executoren.
- **„Über das Publikum“** zielt deutlich über die Köpfe. Die Sperrzone prüft auch hier jeden Wert.
- **Wege durchs Publikum:** Springt ein Kopf so, dass er auf dem Weg durch die Kopfhöhe schwenken würde, bleibt er dunkel, bis er angekommen ist (geschätzt mit 150° pro Sekunde). Das Pult blendet solche Wechsel nicht weich über, sondern fährt direkt hin und blendet dort auf.
- **Probe:** Die Show aus der Probe folgt live nicht der Uhr, denn eine Band spielt nie genau gleich. Go+ wechselt zum nächsten Songteil, die Effekte laufen im Live-Tempo. Nur „Probe ansehen“ folgt der Aufnahme genau.
- **Show aus der Probe** (seit 1.8): nur zwei Song-Farben (die ersten zwei der Profil-Palette) plus Weiß für Akzente. Ruhige Teile stehen und atmen, mittlere stehen auf der Band und pulsieren, starke schwenken, Höhepunkte kreisen, tauschen die zwei Farben und lassen den Strobo blitzen (so weit die Prüfung es erlaubt). Der Puls geht nie ganz aus („tiefe“ 0,3 bis 0,35). Gemessen am echten Song „Boulevard of Broken Dreams“: Spots im Schnitt etwa 70 % hell statt vorher 20 %.
- **Markierungen (Taste D) und erkannte Drops** werden Akzente: ein weißer Schlag mit Strobo, nach 0,4 Sekunden geht es von selbst im Songteil weiter. Live drückt man dafür Go+.
- **Songteile** erkennt das Programm am Klang: Lautstärke, Bass, Höhen und Unruhe. Namen wie „Refrain“ sind geschätzt. Gleich klingende Teile bekommen denselben Buchstaben und dasselbe Licht. Strobo baut die Probe nie ein.
- **Songerkennung und „offizielle Lichtshows“:** Eine offizielle Lichtshow zum Herunterladen gibt es nicht, und Erkennungsdienste kennen nur Originalaufnahmen, keine Schulband. Der Songname wird deshalb eingetippt. Farben und Stil passend zum Song soll später die KI vorschlagen (braucht den API-Key).
- **Patchplan:** DIP-Schalter rechnen mit Schalter 1 = 1, 2 = 2, 3 = 4 und so weiter. Das ist bei den meisten Geräten so, bitte trotzdem im Handbuch prüfen.
- **Überschneidende Adressen** werden rot markiert, aber nicht verboten, denn zwei Geräte auf gleicher Adresse können gewollt sein. Über 512 ist gesperrt.
- **Grundlicht** steht direkt im Profil und nicht als eigene Szene. So ist der Rückfall auch da, wenn jemand eine Szene löscht.
- **Der Hazer** bekommt nur Werte, wenn das Profil ihn erlaubt. Alle vier Profile verbieten ihn. Die Automatik benutzt ihn nie, nur eine Cue mit `nebel`.
- **Ein vergessener DMX-Test** endet nach 2 Minuten von selbst.
- **Executor-Belegung** wird gespeichert, die Stellung der Fader und der laufende Cue nicht. Nach einem Neustart ist alles aus.
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

## Song-Erkennung, Song-Start und Show-Tasten (ab 1.9.0)

- **Gemessen statt geraten:** 12 künstliche Songs (Pop, Rock, Ballade, EDM, Punk, Swing, Weihnachtslied ohne Schlagzeug), jeweils als „Probe“ und als „Live“-Fassung (4 % schneller, zum Ende 3 % schneller, ungenaues Timing, Handy-Lautsprecher, Raum, Publikum). Tempo: 24 von 24 richtig, Beats: 97 % getroffen, Takt-Eins: 24 von 24. Die alte Erkennung hatte auf den ersten 16 dieser Aufnahmen 3 Tempi richtig und 67 % der Beats.
- **Songteile sind schwerer:** Die Grenzen kommen aus Lautstärke und Klang, die Buchstaben aus dem Vergleich der Akkordfolgen. Auf den künstlichen Songs werden gut ein Drittel der Teil-Wechsel exakt gefunden, die gefundenen stimmen zu 84 %. Kurze Überleitungen (4 Takte) gehen oft im Nachbarteil auf. Beim echten Song „Hh“ lagen die gefundenen Wechsel bei 69, 119, 144 und 181 s, die D-Markierungen bei 69, 120, 144 und 181 s.
- **Halbes oder doppeltes Tempo** ist bei schnellen Songs Geschmackssache (Boulevard of Broken Dreams: 83 oder 167 BPM). Das Programm entscheidet nach der Snare. Fürs Licht ist beides brauchbar.
- **Song-Folger:** in 2.0.0 neu gebaut, siehe „Song-Folger 2.0“ unten.
- **Leise Intros:** Der Musikanfang wird gegen das Rauschen der ersten Sekunde der Aufnahme gemessen. Darum vor dem Song kurz Stille aufnehmen.
- **Show-Tasten** bauen ihre Looks aus den Gruppen Spots, Farb-PARs und Strobo. Der Strobo blitzt nur, wenn er eingemessen ist und die Prüfung es erlaubt. Halte-Tasten gehen nach 20 s von selbst aus, falls das Loslassen nicht ankommt.
- **Effekte rasten auf den Beat ein:** Jeder gehörte Schlag zieht die Effekt-Uhr ein Stück nach, so liegt der Puls auf dem Beat. Welcher der Schläge die Takt-Eins ist, weiß live nur der Song-Start.

## Strobo ohne Einmessen (ab 1.10.0)

- **Ein reiner Strobo ohne bekanntes Tempo blitzt trotzdem:** Das Programm lässt sein eigenes Tempo auf 0 und schaltet die Helligkeit selbst kurz an (50 ms), auf dem Beat, höchstens 3-mal pro Sekunde, nach 5 s Pause. Das Tempo bestimmt so das Programm. Ohne Blitz-Wunsch bleibt er dunkel, ein weißes Dauerlicht gibt es nicht.
- **Annahme:** Der Strobo leuchtet bei Tempo 0 mit der eingestellten Helligkeit (so machen es LED-Strobos). Ein alter Xenon-Strobo blitzt bei Tempo 0 gar nicht. Dann bleibt er dunkel, und nur Einmessen hilft.
- **Einmessen** zeigt jetzt den echten Strobo zuerst, und groß, welches Gerät gerade blitzt. Am 07.11. war aus Versehen Front 1 (MH-X25) eingemessen worden. Das lässt sich mit „Einmessung zurücknehmen“ rückgängig machen.

## Windows-Version (ab 1.10.0)

- **Getestet nur automatisch** auf einem Windows-Server bei GitHub: alle Tests, Bau, stille Installation, Selbsttest der installierten App, das Update-Skript. Nicht getestet: ein echter Windows-Laptop, das Fenster selbst (Edge WebView2), Mikrofon, Enttec.
- **Das Fenster** nutzt Edge WebView2 (in Windows 10/11 meist schon drin). Fehlt es, öffnet sich die Oberfläche im Browser.
- **Nicht signiert:** Windows warnt beim ersten Start („Weitere Informationen“, „Trotzdem ausführen“).
- **Enttec:** Ab 2.0.0 geht es über den normalen FTDI-Treiber (ftd2xx.dll), Zadig ist nicht mehr nötig. Siehe „Konzert-Sicherheit“.
- **Updates** laden den neuen Installer, prüfen die Prüfsumme und installieren ihn still, sobald die App geschlossen ist.

## Pult im Stil großer Lichtpulte (ab 2.0.0)

- **Kleiner als grandMA3, gleiche Arbeitsweise:** Pools, Feature-Leiste mit Encodern, Programmer (live oder Blind), Store/Update/Assign/Delete/Label/Edit, Oops, Clear, Highlight, Befehlszeile. Nicht nachgebaut: eigene Gruppen speichern (die Gruppen kommen aus dem Patch), Preset-Pools zum Speichern (Farben, Positionen und Gobos gibt es als feste Pools), Makros, Timecode-Fenster, mehrere Bildschirme.
- **40 Fader auf 4 Seiten** (je 10). Fader-Arten: Sequenz, Gruppen-Master, Tempo. Wechselt man die Seite, laufen die Fader der anderen Seite weiter.
- **Fader hoch startet, ganz runter schaltet aus** (wie AutoStart/AutoStop). Flash schaltet ohne Überblendzeit ein und beim Loslassen wieder aus; eine hängende Flash-Taste geht nach 20 s von selbst aus.
- **Grand Master** wirkt auf alles außer den Not-Tasten (Warmweiß bei einer Rede bleibt hell). Er wird gespeichert, damit er nach einem Neustart gleich steht; der Konzert-Check warnt, wenn er nicht auf 100 % steht.
- **Tempo-Fader:** Mitte normal, unten ein Viertel, oben das Vierfache. Es gibt nur einen. Er wirkt auf alle Effekte (auch die der Show-Tasten), nicht auf den Software-Strobo.
- **Oops** merkt sich die letzten 50 Schritte (Speichern, Löschen, Zuweisen, Programmer). Speichern auf einen leeren Fader ist ein Schritt.
- **Song-Sequenzen** (aus der Probe) lassen im Pult keine Cues löschen oder verschieben, weil sonst die Zeiten nicht mehr zu den Cues passen. Namen und Zeiten ändern geht, die Teile stellt man in der Probe richtig.

## Licht-Chat (ab 2.0.0, Schritt 8)

- **Modell:** `claude-opus-5-5`, Denken adaptiv mit `effort: medium`, Werkzeuge mit festem Schema (`strict`), Zwischenspeicher für den gleichbleibenden Anfang, und der Rückfall `fallbacks: "default"`: Lehnt das Modell eine Anfrage ab, beantwortet sie die Schnittstelle mit einem anderen Claude-Modell. In `lokal.json` lässt sich mit `"modell"` ein anderes Modell eintragen.
- **Nur zwei Werkzeuge** statt der sechs aus der Beschreibung: `vorschlag_machen` (Sequenz mit Cues und gewünschtem Fader, deckt Szene, Cue, Cue ändern und Fader belegen ab) und `sequenz_lesen`. Die Vorschau zeigt das Programm selbst. Keins der Werkzeuge kann etwas live schalten oder speichern.
- **Prüfung:** Jeder Vorschlag geht durch `pruefe_sequenz` und zusätzlich durch Strobo-Grenze, Gobo-Namen, Positionen und Bewegung nur für bewegliche Gruppen. Fehler gehen an Claude zurück, höchstens 4 Anfragen pro Nachricht.
- **Sparsam:** Nach einem gültigen Vorschlag wird keine weitere Anfrage gestellt. Ein Gespräch beginnt nach 40 Nachrichten neu (der Verlauf wird nie gekürzt oder verändert). Die Kosten-Anzeige rechnet mit den Preisen von Claude Opus 5.5 und ist nur ungefähr.
- **Ohne Internet** versteht ein eingebauter, einfacher Leser kurze Sätze (Gruppen, Farben, Helligkeit, Positionen, Effekte, langsam/schnell, Zeit, Fader). Er ist bewusst einfach und sagt, wenn er etwas nicht versteht.
- **Nicht getestet:** eine echte Anfrage an Claude (es gab beim Bau keinen Schlüssel). Geprüft ist der ganze Ablauf mit nachgebauten Antworten, auch Fehler, Ablehnung und kein Internet.

## Song-Folger 2.0 (ab 2.0.0)

- **Warum neu:** Gemessen an der echten Aufnahme „Hh“ (Probe vom 07.11.) mit daraus gebauten Live-Fassungen lag der alte Folger schon bei 5 % schnellerer Band 3 bis 4 s daneben (Teilwechsel im Mittel 3,9 s), bei 4 % langsamer 3 s. Ursache: Sein Vergleich mittelte über den ganzen bisherigen Weg und konnte einen frühen Fehler nicht mehr loswerden; außerdem kam jede Messung 0,1 s zu spät.
- **Wie er jetzt hört:** Die letzten 4 s der Band werden mit allen Stellen der Probe in der Nähe verglichen, in sieben Tempi (±6 % um das zuletzt gemessene). Alle 0,5 s wird zusätzlich im ganzen Song gesucht; gesprungen wird nur, wenn die jetzige Stelle deutlich schlechter passt als sonst und eine andere so gut wie beim normalen Mithören, 2 s lang.
- **Gemessen** (Teilwechsel, Mittel der Abweichung, Start pünktlich / 1,5 s zu spät / 3 s zu früh): gleiches Spiel 0,03 / 0,08 / 0,01 s; 5 % schneller 0,03 / 0,12 / 0,02 s; 4 % langsamer 0,05 / 0,06 / 0,03 s; Tempo steigt ab der Mitte um 7 % 0,03 / 0,08 / 0,01 s; anderer Klang (Bass, Hall, Publikum 10 dB unter der Band, 3 % schneller) 0,16 / 0,20 / 0,54 s; sehr lautes Publikum (nur 3 dB unter der Band) 0,45 / 0,41 / 2,1 s; Teil ausgelassen: alle Wechsel genau, nur der Wechsel am ausgelassenen Teil rund 5 s spät; Refrain wiederholt: rund 2 s Bridge-Licht, dann zurück im Refrain. Über alles: 85 % der Teilwechsel auf 0,5 s genau, 94 % auf 1 s. Das Werkzeug dafür (Live-Fassungen mit bekannter Zeitzuordnung) lag im Arbeitsordner und ist nicht Teil des Programms.
- **Grenzen:** Sehr lautes Publikum (nur 3 dB leiser als die Band) und Start, bevor die Band spielt, kann den Anfang verfehlen; dann „Nächster Teil“ oder auf den Teil klicken. Mit einer echten Band live ist das weiter nicht ausprobiert. Die künstlichen Live-Fassungen ändern die Akkorde nicht; spielt die Band ein Solo, das es in der Probe nicht gab, läuft die Uhr weiter.
- **Start:** Ein klarer Einsatz (10 dB lauter als vorher) startet die Uhr genau dort. Ist es beim Drücken schon laut, läuft die Uhr ab 0,7 s vor dem Drücken, und in den ersten 15 s wird am Inhalt nachgeprüft (springt, wenn eine andere Stelle am Song-Anfang 1,5 s lang eindeutig passt). Song nochmal drücken heißt „jetzt los“. Kommt gar kein Ton an, läuft die Uhr ab dem Drücken.
- **Rechenzeit:** im Mittel unter 1 ms pro Tonblock, Spitzen (Suche im ganzen Song) um 20 ms; der Puffer des Eingangs fängt das auf.

## Song-Erkennung und Akzente (ab 2.1.0)

- **Erkennung:** Die letzten 10 s werden mit allen Probe-Aufnahmen verglichen (gleiche Merkmale wie der Song-Folger, jeder zweite Messpunkt, Tempi ±6 %). Erkannt ist ein Song erst, wenn er um 0,04 besser passt als der zweitbeste Song, seine Stelle um 0,12 besser als der Durchschnitt des restlichen Songs, und das 3 s lang gleichmäßig weiterläuft. Bei Stille, Reden oder Klatschen (unter 75 % Musik im Fenster) wird nicht verglichen.
- **Gemessen** an 10 Kunstsongs und „Hh“ (je gleich und 4 % schneller, Start nach 1 s oder mitten im Song): 86 % richtig, im Mittel nach 9 s, nie ein falscher Song. 4 fremde Kunstsongs, die mit ähnlichen Akkorden in derselben Tonart und im selben Tempo gebaut waren: kein Fehlalarm. Mit 6 s Fenster und 2 s Bestätigung gab es dagegen 3 Fehlalarme in 8 Versuchen.
- **Grenzen:** Sehr viel Hall und Publikum (Raum-Mikrofon statt X32-Summe) verhindern das Erkennen meist (dann einfach von Hand starten). Zwei Songs mit denselben Akkorden in derselben Tonart und im selben Tempo kann die Erkennung verwechseln. Darum startet „Automatisch“ nur den Song, der laut Setlist als Nächstes dran ist; jeder andere erscheint nur als Knopf.
- **Setlist** liegt in `cues/setlist.json` (kommt in jede Sicherung). Songs, die nicht drinstehen, kommen hinten dran. Nach einem Song ist der nächste in der Liste „erwartet“.
- **Rechenzeit:** Die Erkennung läuft in einem eigenen Thread alle 0,5 s, rund 5 ms pro Song; bei Stille fast nichts.
- **Schläge in der Probe:** ein Einsatz mindestens doppelt so stark wie die üblichen in den 4 s drumherum, dabei 4 dB lauter oder oben ein Scheppern (Becken). Höchstens einer pro 6 s und einer pro 15 s Song, auf den nächsten Beat gelegt. In „Hh“ lagen 7 von 16 gefundenen Schlägen auf deinen D-Marken (Teilwechsel).
- **Schläge live:** Mitten und Höhen 2,5-mal stärker als die normalen Schläge der letzten 4 s, höchstens einer pro 2 s. Gleichmäßiger Takt allein gibt keinen Schlag.
- **Fehler bis 2.0.0:** Ein Akzent im Song-Modus konnte „nächster Teil“ auslösen, wenn die Band langsamer als in der Probe spielte. Behoben, mit Test.

## Konzert-Sicherheit (ab 2.0.0)

- **Enttec, drei Wege:** FTDI-Treiber (Windows, ftd2xx.dll per ctypes), USB direkt (pyftdi/libusb, Mac oder Windows mit Zadig), serieller Port des eingebauten Treibers (Mac `/dev/cu.usbserial-…`, Windows COM). Der erste, der klappt, wird benutzt. Das Enttec DMX USB Pro wird am Namen erkannt und bekommt fertige Pakete. Alles nur gegen nachgebaute Treiber getestet, kein echtes Enttec.
- **30 DMX-Pakete pro Sekunde** (vorher 40): 512 Kanäle brauchen 23 ms auf der Leitung, und vor jedem Break muss das vorige Paket draußen sein. Die Show rechnet weiter 40 Bilder pro Sekunde.
- **Wackelkontakt:** Reißt die Verbindung ab, läuft die Show im Simulator weiter und die Ausgabe sucht jede Sekunde neu; danach sendet sie von selbst weiter. Der Knopf bleibt dabei auf „an“.
- **Ton-Eingang:** Unter Windows erscheint jedes Gerät nur einmal (WASAPI mit automatischer Umrechnung, sonst MME, nie WDM-KS). Kann ein Gerät 44,1 kHz nicht, wird umgerechnet. Reißt der Eingang ab, wird er alle 2 s neu geöffnet (Geräteliste neu einlesen, Gerät am Namen wiederfinden). Die gewählte Quelle wird gemerkt und nach einem Neustart von selbst wieder geöffnet; DMX bleibt nach einem Neustart trotzdem aus.
- **Ruhezustand:** Solange das Programm läuft, schlafen Rechner und Bildschirm nicht ein. Ein zugeklapptes MacBook schläft trotzdem.
- **Sicherung:** bei jedem Start eine kleine Sicherung (ohne Aufnahmen, die letzten 10), „Show sichern“ mit allem. Laden geht beim nächsten Start, vorher wird gesichert. Kaputte Sequenz-, Proben- oder Gerätedateien werden übersprungen und stehen im Logbuch, statt den Start zu verhindern. JSON wird mit fsync geschrieben.
- **Konzert-Check** schaltet nie etwas selbst (außer dem DMX-Knopf, wenn man ihn drückt).

## Mac-App, Website und Updates

- **Die Website** ist für GitHub Pages vorbereitet. Cloudflare muss einmal im eigenen Konto mit dem Repo verbunden werden.
- **Das Repo muss öffentlich sein,** denn Downloads aus privaten Repos gehen nicht ohne Anmeldung.
- **Keine Lizenz vergeben:** Es wurde noch keine Lizenz für den eigenen Code gewählt.
- **Die Mac-App enthält aubio nicht,** wegen der GPL. Sie nutzt die eigene Beat-Erkennung, die bei Musik ohne klaren Takt öfter daneben liegt.
- **Die App ist nicht von Apple beglaubigt** (kein bezahltes Konto). Beim ersten Start braucht es „Dennoch öffnen“. Nach Updates kann macOS erneut nach dem Mikrofon fragen.
- **Updates:** Beim Start wird einmal gesucht, die Datei lädt im Hintergrund. Installiert wird nur auf Klick und nie bei laufender DMX-Ausgabe. Geprüft wird die Prüfsumme aus dem Release. Eine eigene digitale Unterschrift gibt es nicht, die Sicherheit hängt also am GitHub-Konto.
- **Beispieldaten** kommen nur beim allerersten Start in den Datenordner. Neue Beispielprofile aus Updates erscheinen daher nicht von selbst. Der Gerätekatalog kommt dagegen mit jedem Update neu.
- **Tablet:** Die App selbst hat noch keinen `--netz`-Knopf, das geht nur aus dem Quellcode.

## Vorbereitet für die Schritte 8 bis 12

| Schritt | Wo es andockt |
|---|---|
| 8 Licht-Chat | **Fertig in 2.0.0** (`licht_chat.py`), siehe oben |
| 9 Profile per API | `entwurf_setzen("profil", ...)` samt Prüfung und Speichern gibt es schon und ist getestet |
| 10 X32 | Das Modul setzt `show.overrides` oder einen eigenen Rede-Eingang und liest `x32.json`. Audio vom X32 läuft schon über `audio.quellen.Eingang` mit Kanalwahl |
| 11 Klick-Positionen | `pantilt.py`, `szenen.zeige_auf` und die Versatz-Felder in `stage.json` sind fertig und getestet. Es fehlt nur die Oberfläche |
| 12 Generalprobe | Handbuch-Abgleich, Einmessen, Enttec testen |
