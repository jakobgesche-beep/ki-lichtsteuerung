# Projektbeschreibung: KI-Lichtsteuerung der Technik-AG

Oct 30, 2026 · @jakob

Unser eigenes Programm steuert das Bühnenlicht: Es reagiert live und ohne Internet auf die Musik vom X32, hält sich an ein vorher gewähltes Veranstaltungsprofil und lässt sich über einen Licht-Chat und eine 3D-Bühne programmieren. Diese Beschreibung ist die Vorgabe für Claude Code.

## Auftrag an Claude Code

Dieses Dokument ist dein Auftrag, ohne weitere Nachricht. Baue daraus den ersten lauffähigen Entwurf des Programms. Das Programm wird von der Technik-AG einer Schule benutzt und weiterentwickelt, Schüler lesen deinen Code.

**So gehst du vor**

1. Lies das ganze Dokument, bevor du anfängst. Die Grundregeln gelten für jede Zeile Code. Bei Widersprüchen gewinnen die Grundregeln.
2. Stelle keine Rückfragen, bevor der Entwurf steht. Wo etwas offen ist (siehe Offene Fragen), triff eine sinnvolle Annahme und schreibe sie in `ANNAHMEN.md`.
3. Arbeite die Bau-Reihenfolge ab. Der erste Entwurf umfasst die **Schritte 1 bis 7** (Projekt bis Szenen, Cues, Fader). Baue so, dass die Schritte 8 bis 12 später ohne Umbau dazukommen.
4. Teste jeden Schritt, bevor du den nächsten beginnst. Lege ein Git-Repository an, speichere dieses Dokument dort als CLAUDE.md und committe nach jedem Schritt.

**Rahmenbedingungen für den ersten Entwurf**

- **Keine Hardware vorhanden:** Alles muss im Simulator-Modus laufen, ohne Enttec, ohne X32 und ohne Internet. Audio kommt testweise vom Laptop-Mikrofon oder aus einer Audiodatei.
- **DMX-Ausgabe ist beim Start aus.** Sie wird nur per Knopf eingeschaltet, sobald ein Enttec gefunden wird.
- **Technik:** Python für Engine und Server, Oberfläche im Browser (Three.js für 3D), Daten als JSON-Dateien. Die Oberfläche ist auf Deutsch.
- **Beispieldaten:** Patche unsere Geräte aus der Hardware-Tabelle mit ihren Standard-Modi und nimm für `stage.json` eine Platzhalter-Bühne. Alles, was geschätzt ist, wird in den Dateien als Platzhalter markiert.
- **Katalog:** Importiere die Open Fixture Library. Klappt der Import nicht, starte mit unseren Geräten als handgeschriebenen Katalogeinträgen und baue den Importer trotzdem.
- **Tests:** automatische Tests mindestens für Adressprüfung, Strobo-Grenze, Sperrzone Publikum und die Pan/Tilt-Rechnung.

**Am Ende lieferst du**

- eine `README.md` auf Deutsch: Installation und Start in wenigen Schritten, so dass ein Schüler es ohne Hilfe schafft;
- `ANNAHMEN.md` mit allen Annahmen;
- einen kurzen Bericht im Chat: was funktioniert, wie man es startet, was als Nächstes kommt und welche offenen Fragen jetzt wirklich beantwortet werden müssen.

## Grundregeln

Live läuft alles lokal auf dem Laptop, ohne Internet. Diese Regeln gelten für jedes Modul:

- **Offline zuerst:** Die Claude-API wird nur vor der Veranstaltung (Profile) und in der Probe (Licht-Chat) benutzt. Fällt das Internet aus, läuft die Show unverändert weiter.
- **Mensch vor Automatik:** Die Override-Tasten (Blackout, Warmweiß, Automatik-Pause) haben immer Vorrang vor Automatik und KI.
- **Nichts von der KI geht direkt live:** Was der Licht-Chat oder ein Profil erzeugt, erscheint erst in der Vorschau. Gespeichert wird es erst nach „Übernehmen“.
- **Alles wird geprüft:** Jeder DMX-Wert wird vor dem Senden gegen die Gerätedatei geprüft: gültiger Bereich, Strobo-Obergrenze, Sperrzone Publikum.
- **Sicherer Rückfall:** Fällt die Audioanalyse aus, geht die Engine auf das ruhige Grundlicht des aktiven Profils, nicht auf Blackout.
- **Eine Quelle für alles:** Geräte, Bühne, Positionen, Profile und Cues liegen als JSON-Dateien im Projekt. Alle Module lesen dieselben Dateien.

## Hardware

Die **Funktion** jedes Geräts steht fest, das **genaue Modell** kann sich bis zum Kauf noch ändern. Beispiel: Statt der Quad Pars kommen vielleicht andere RGBW-PARs, aber es bleiben 6 Farb-PARs. Das Programm darf deshalb nie fest mit einem Modell rechnen. Cues, Profile und Engine sprechen Gruppen nach Funktion an (z. B. „Farb-PARs“, „Spots“, „Frontlicht“), nie einzelne Modelle. Ein Modellwechsel heißt nur: neuen Gerätetyp im Patch auswählen. Modus und Startadresse tragen wir ein, sobald die Geräte da sind.

| Funktion (fest) | Geplantes Modell (kann sich ändern) | Anzahl | Was es kann | DMX-Modus | Startadresse |
|---|---|---|---|---|---|
| Farblicht (RGBW-Wash) | [Stairville Quad Par Profile 5x8W RGBW](https://thomann.de/lu/thomanntv_video_stairville_quad_par_profile_5x8w_rgbw_3010.html) | 6 | RGBW-Farbmischung, 25°, DMX mit 4, 6 oder 8 Kanälen | eintragen | eintragen |
| Frontlicht (Spot-Moving-Head) | [Stairville MH-X25](https://www.bonedo.de/artikel/stairville-mh-x25/) (vorhanden) | 2 | LED-Spot-Moving-Head, Pan 540° / Tilt 270°, DMX mit 6 oder 12 Kanälen | eintragen | eintragen |
| Effektlicht (Spot-Moving-Head) | [Varytec Hero Spot 60](https://www.thomann.dk/varytec_hero_spot_60_b_stock.htm) | 1 oder 2 | 60-W-LED-Spot, Pan 540° / Tilt 190° (16 bit), Farbrad, Gobos, Prisma | eintragen | eintragen |
| Dunst (nur Variante B) | [Stairville Hz-200 Compact Hazer DMX](https://www.thomann.ie/stairville_hz_200_compact_hazer_dmx.htm) | 0 oder 1 | per DMX oder Timer-Fernbedienung | eintragen | eintragen |
| DMX-Interface (USB) | [Enttec Open DMX USB](https://www.thomann.fr/enttec_open_dmx_usb_interface_reviews.htm?rating=5) | 1 | 1 DMX-Universum; der Rechner muss die DMX-Daten selbst ständig senden; 5-pol. Ausgang, Adapter auf 3-pol. nötig | | |
| Mischpult | [Behringer X32 Compact](https://thomann.co.uk/behringer_x_32_compact.htm) (vorhanden) | 1 | USB-Audiointerface 32×32, Fernsteuerung übers Netzwerk, MIDI, 6 Matrix | | |
| Traverse mit Stativen | [Stageworx LB-3s](https://www.thomann.de/be/stairville_lb_3s_lighting_stand_set_3m_si.htm) | 1 | 3 m breit, 1,5–3,1 m hoch, bis 8 Scheinwerfer, max. 60 kg gleichmäßig verteilt | | |
| Steuerrechner | Laptop | 1 | Betriebssystem noch offen | | |

Adressen dürfen sich nicht überschneiden: nächste Startadresse = Startadresse + Kanalzahl. Bei 8 Kanälen pro PAR also 1, 9, 17, 25, 33, 41. Das rechnet später der Patch-Assistent aus (siehe Gerätekatalog und Patch).

**Montage an der Traverse**

- **Haken:** Doughty T20301 für 20-mm-Rohre, bis 15 kg. Die Rohre vom LB-3s sind 18 mm dick, Haken für 16 mm oder 50 mm passen nicht. 1 Haken pro PAR, 2 pro Moving Head am Omega-Bügel.
- **Sicherungsseil an jedem Gerät**, Tragfähigkeit über dem Gerätegewicht: PARs (2,1 kg) mit 3 mm / 5 kg, Hero Spot 60 (4,6 kg) mit 4 mm / 10 kg.
- **Platz:** Die Traverse trägt bis zu 8 Geräte. Die MH-X25 (rund 10 kg) stehen deshalb auf eigenen Stativen vor der Bühne, als Frontlicht.
- **Moving Heads nah an die Stative.** Hängen sie kopfüber, werden am Gerät Display und Pan/Tilt umgedreht und in `stage.json` wird „hängend“ eingetragen.
- Alles in 1,5 m Höhe montieren, dann die Traverse hochfahren.

## Gerätekatalog und Patch

Wie bei grandMA3 gibt es einen Katalog mit sehr vielen Gerätetypen, aus dem man Lichter in die Show patcht. Neue oder geliehene Geräte sind damit in Minuten eingebunden.

**Katalog (`catalog/`)**

- **Grundstock:** die [Open Fixture Library](https://github.com/OpenLightingProject/open-fixture-library). Sie sammelt Gerätedefinitionen in einem eigenen JSON-Format und wandelt sie in Formate anderer Lichtprogramme um, z. B. QLC+. Claude Code importiert sie einmal in unser Format und kann sie später aktualisieren.
- **Weitere Quellen:** Import von QLC+-Dateien (.qxf) und GDTF-Dateien (.gdtf). GDTF ist das Format, das grandMA3 einliest. Viele Geräte gibt es auf gdtf-share.com, mit kostenlosem Konto.
- **Eintrag pro Gerätetyp:** Hersteller, Name, Modi mit Kanalliste, was jeder Kanal kann (Dimmer, Farbe, Pan/Tilt mit Gradbereich, Gobo, Strobo) und physische Daten für die 3D-Bühne (Gewicht, Abstrahlwinkel).
- **Editor:** Fehlt ein Gerät, legt man es selbst an oder kopiert ein ähnliches und ändert es.
- **Unsere Geräte** (Quad Par, MH-X25, Hero Spot 60, Hz-200) werden beim ersten Patch mit dem Handbuch abgeglichen.
- Lizenz der Bibliothek prüfen und die Quelle im Programm nennen.

**Patch-Assistent (`fixtures.json`), Ablauf wie bei grandMA3**

1. Gerätetyp im Katalog suchen.
2. Modus wählen.
3. Anzahl und Name eingeben, z. B. „PAR 1–6“.
4. Startadresse eingeben oder „nächste freie“ nehmen, das Programm zählt weiter.
5. Ort auf der 3D-Bühne setzen: Traverse, Stativ oder Boden, hängend oder stehend.

- **Prüfungen:** Überschneidende Adressen werden rot markiert, Adressen über 512 sind gesperrt. Eine Warnung kommt, wenn die Traverse mehr als 8 Geräte oder 60 kg tragen müsste.
- **Gerät tauschen:** Cues speichern Eigenschaften wie „Farbe Rot, 80 %“ statt roher DMX-Werte. Wird ein Gerät gegen einen anderen Typ getauscht, laufen die Cues weiter.
- Engine, 3D-Bühne und Licht-Chat lesen nur Katalog und Patch. Dadurch weiß die KI immer genau, was jedes Licht kann.

## Aufbau

Live läuft alles lokal, jeder Wert geht durch die Prüfung. Gestrichelt (nur mit Internet, vor der Veranstaltung oder in der Probe): die Claude-API mit Profilen aus Freitext und Licht-Chat, die erst nach „Übernehmen“ in die Show-Daten schreibt.

```
                        ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
                          Claude-API (nur vorher
                          und in der Probe)
                        └ ─ ─ ─ ─ ┬ ─ ─ ─ ─ ─ ┘
                                  ┆ nach „Übernehmen“
            ┌─ Laptop, läuft offline ┆ ────────────────┐
X32 Compact │  ┌─────────────┐  ┌────┴──────────┐      │
USB + LAN ─────▶ Musik-Engine│  │ Show-Daten    │◀────────▶ 3D-Vorschau
            │  │ Beat,Energie│  │ Profile, Cues,│      │    Browser, Tablet
            │  │ laut/leise  │  │ Patch, Pos.   │      │    Punkte klicken
            │  └──────┬──────┘  └───────┬───────┘      │
            │  ┌──────▼─────────────────▼───────┐      │
            │  │ Prüfung und Override           │      │
            │  │ Grenzen, Sperrzone, Strobo-Limit│     │
            │  │ Override-Tasten: immer Vorrang │      │
            │  └──────────────┬─────────────────┘      │
            │  ┌──────────────▼─────────────────┐      │
            │  │ DMX-Ausgabe, 30–40 Bilder/s    │─── Enttec ──▶ Lichter
            │  └────────────────────────────────┘      │      6 PARs, 2 MH-X25,
            └──────────────────────────────────────────┘      Hero Spot 60
```

Die Claude-API schreibt nur gespeicherte Show-Daten. Live laufen Engine, Prüfung und DMX-Ausgabe auf dem Laptop, ohne Internet.

## Musik-Engine

Die Engine läuft immer lokal und reagiert innerhalb von Millisekunden auf die Musik. Sie braucht kein Internet.

- **Audio rein:** Die Summe vom X32 kommt über USB als zwei Kanäle in den Laptop (siehe X32-Anbindung).
- **Analyse:** Python mit [aubio](https://sources.debian.org/src/aubio/0.4.9-5/README.md) für Beat, Tempo und laute/leise Stellen. Dazu eine eigene FFT mit numpy für Bass, Mitten und Höhen. Daraus entsteht ein geglätteter Energiewert von 0 bis 1.
- **Regeln:** Beat → Farbschritt der PARs. Bass → Helligkeit. Hohe Energie → Bewegung der Moving Heads. Leise Stelle oder Rede → ruhiges Grundlicht. Wie stark jede Regel wirkt, gibt das aktive Profil vor.
- **DMX raus:** Ein eigener Thread sendet 30–40 Bilder pro Sekunde, auch wenn sich nichts ändert. Das Open DMX braucht das, weil der Rechner das Senden selbst übernehmen muss.
- **Vorlage:** [pyopendmx](https://github.com/maximecb/pyopendmx) macht genau das mit einem Enttec OpenDMX, pyftdi und aubio und läuft auch auf einem Raspberry Pi 4. Gut zum Abschauen.
- **Simulator-Modus:** Statt an das Enttec gehen die Werte an die 3D-Vorschau. So lässt sich alles ohne Lichter testen.

## Veranstaltungsprofile

Vor jeder Veranstaltung wird ein Profil gewählt. Es legt die Grenzen fest, in denen die Engine live arbeitet, egal wie poppig die Musik ist.

| Profil | Farben | Bewegung | Reaktion auf Beat | Strobo |
|---|---|---|---|---|
| Weihnachten | Gold, Rot, Warmweiß, fest | kaum | nur sanftes „Atmen“ | aus |
| Schulfest Nachmittag | Warmweiß, wenige Farben | aus | gering | aus |
| Schulfest Abend | volle Palette | voll | stark | erlaubt, mit Obergrenze |
| Theater / Reden | Warmweiß | aus | Automatik aus | aus |

**So entsteht ein Profil (vorher, nicht live):**

1. Jemand beschreibt die Veranstaltung in einem Satz, z. B. „Weihnachtskonzert, besinnlich, warme Farben, Gold und Rot“.
2. Die Claude-API macht daraus ein Profil als JSON nach festem Schema.
3. Das Programm prüft die Werte und zeigt das Profil in der Vorschau.
4. Nach „Übernehmen“ wird es als Datei gespeichert. Am Abend wird es nur noch geladen.

**Felder im Schema (Vorschlag):** `name`, `palette` (Liste von Farben), `max_helligkeit`, `bewegung` (aus / langsam / voll), `beat_reaktion` (0–1), `strobo` (aus oder max. Blitze pro Sekunde und max. Dauer), `grundlicht` (Szene für leise Stellen), `hazer` (erlaubt ja/nein).

**Version 2 (optional): Live-Regisseur.** Alle 30–60 Sekunden bekommt die API ein paar Zahlen (Tempo, Energie, Rede ja/nein) und darf innerhalb der Profilgrenzen nachjustieren. Kommt keine Antwort, bleibt alles, wie es ist. Die API bekommt nie die Musik selbst.

## X32-Anbindung

Das X32 Compact liefert zwei Dinge: den Ton für die Analyse und die Info, was gerade auf der Bühne passiert.

**Audio per USB**

- Das X32 Compact hat ein eingebautes USB-Audiointerface mit 32 Ein- und Ausgängen. Ein USB-Kabel zum Laptop reicht.
- Im Routing-Menü unter „Card Out“ wird festgelegt, was über USB zum Computer geht. Das geht in 8er-Blöcken.
- Quelle ist eine eigene Matrix, die von der Summe (Main L/R) gespeist wird. Dann ändert sich die Analyse nicht, wenn jemand die Hauptlautstärke verstellt. Die genauen Kanäle prüfen wir beim Einrichten am Pult.

**Bühnen-Status übers Netzwerk**

- Das X32 lässt sich übers Netzwerk fernsteuern. Das Programm verbindet sich per LAN und liest Mute, Fader und Pegel ausgewählter Kanäle (Protokoll OSC; Claude Code schlägt die Befehle nach).
- Regeln, die Kanäle stehen in `x32.json`:
  - Rednerpult-Mikro offen und mit Signal → Modus „Rede“: Warmweiß, Automatik pausiert.
  - Band-Kanäle aktiv → Konzertlicht nach Profil.
  - Nur Musik vom Zuspieler → Party-Regeln nach Profil.
- Das Programm liest nur und ändert nie etwas am Mischpult.

Später möglich: Das X32 hat MIDI, damit könnte die Person am Ton Licht-Cues direkt vom Pult starten.

## Licht-Chat

Ein eigenes Chatfenster im Programm, in dem man mit Claude Szenen, Cues und Fader programmiert. Es kann nur Licht.

**Datenmodell**

- **Szene:** Werte pro Gerät (Farbe, Helligkeit, Position, Gobo).
- **Cue:** eine Szene plus Einblendzeit, Ausblendzeit und Wartezeit.
- **Cueliste:** Cues in fester Reihenfolge, mit „Weiter“-Taste.
- **Fader:** steuert eine Gerätegruppe oder eine Szene stufenlos.

**Schutzschicht 1: Systemprompt.** Bei jedem Aufruf gehen der Systemprompt, `fixtures.json`, die Katalogeinträge der gepatchten Geräte, die benannten Positionen und die aktuelle Cueliste mit:

```
Du bist der Licht-Assistent der Technik-AG.
Du hilfst nur beim Programmieren von Szenen, Cues und Fadern
für die Geräte in fixtures.json.
Bei allen anderen Themen antwortest du:
"Da kann ich nicht helfen, ich mache nur Licht."
```

**Schutzschicht 2: Werkzeuge.** Claude kann nur über feste Funktionen handeln: `szene_erstellen`, `cue_einfuegen`, `cue_aendern`, `fader_belegen`, `position_verwenden`, `vorschau_zeigen`. Es gibt kein Werkzeug, das direkt live sendet. Auch wenn jemand den Prompt austrickst, kann die KI nur chatten.

**Ablauf**

1. Eingabe, z. B. „Neue Szene: Bühne blau, Moving Heads aufs Rednerpult, in 3 Sekunden einblenden.“
2. Claude ruft die Werkzeuge auf, das Programm prüft alle Werte gegen `fixtures.json`.
3. Die Szene erscheint in der 3D-Vorschau.
4. Erst nach „Übernehmen“ wird sie gespeichert.

**API-Key und Kosten:** Der Key steht nicht im Code, sondern in einer lokalen Konfigurationsdatei oder Umgebungsvariable, die nicht ins Repository kommt. In der Claude Console wird ein Ausgabenlimit gesetzt. Der Chat braucht Internet, aber nur in der Probe.

## 3D-Bühne

Weil das Bühnendesign immer gleich ist, wird die Bühne einmal genau eingemessen. Danach klickt man in der Vorschau auf einen Punkt, und die Moving Heads richten sich dorthin.

**Einmessen (`stage.json`)**

- Bühne: Breite, Tiefe, Höhe der Bühnenkante und der Bereich des Publikums.
- Jedes Licht: Position x, y, z in Metern, Montage (hängend oder stehend) und Drehung.
- Nullpunkt: z. B. Bühnenmitte vorne auf dem Boden.

**Oberfläche**

- Läuft im Browser (z. B. mit Three.js), damit sie auch auf dem Tablet geht.
- Draufsicht zum Klicken: wie ein Grundriss. Der angeklickte Punkt bekommt eine Zielhöhe, z. B. Kopfhöhe 1,6 m.
- 3D-Ansicht zur Vorschau: Lichtkegel in Farbe. Zeigt live, was die Lichter machen würden, auch im Simulator-Modus.

**Rechnung**

- Aus Lichtposition, Montage und Zielpunkt die Richtung berechnen, daraus die Pan- und Tilt-Winkel.
- Winkel in DMX-Werte umrechnen, mit dem Bereich aus `fixtures.json` (z. B. Hero Spot 60: Pan 540°, Tilt 190°), 16 bit, wo das Gerät es kann.
- Liegt ein Ziel außerhalb des Bereichs, kommt eine Meldung statt einer falschen Bewegung.

**Kalibrierung:** Die Lichter hängen nie exakt. 2–3 markierte Bodenpunkte werden von Hand angefahren, der Versatz pro Gerät wird gespeichert.

**Benannte Positionen:** Angeklickte Punkte bekommen Namen („Rednerpult“, „Mitte“, „Sänger links“) und stehen in `positions.json`. Cues und der Licht-Chat benutzen nur diese Namen.

**Sperrzone Publikum:** Kein Moving Head darf auf Kopfhöhe in den Publikumsbereich zielen. Das prüft das Programm bei jedem Wert.

**Live folgen:** Ein Punkt lässt sich in der Draufsicht mit dem Finger ziehen, die Moving Heads folgen. Automatisches Folgen per Infrarot-Kamera ist Version 2.

## Sicherheit und Bedienung am Abend

Am Abend muss auch jemand das Licht bedienen können, der nichts programmiert hat.

- **Feste Tasten**, groß in der Oberfläche und auf der Tastatur: Blackout, Warmweiß/Rede, Automatik Pause/Weiter, Strobo aus, nächster Cue.
- **Strobo-Grenze:** Schnelles Blitzen kann bei Menschen mit Epilepsie Anfälle auslösen. Maximale Blitze pro Sekunde und maximale Dauer sind feste Einstellungen, die kein Profil und keine KI überschreiben kann. Wenn Strobo läuft, hängt ein Hinweisschild am Eingang.
- **Sperrzone Publikum:** siehe 3D-Bühne.
- **Rückfall:** Hängt die Analyse, geht das Licht auf das Grundlicht des Profils. Nach einem Neustart lädt das Programm das letzte Profil und die letzte Cueliste.
- **Hazer:** vor jedem Einsatz mit dem Hausmeister klären, wegen der Brandmelder.
- **Kamera:** In Version 1 gibt es keine. Vorher klären wir den Datenschutz mit der Schulleitung. Bilder gehen nie an eine externe API.
- **Aufhängen:** Was über Köpfen hängt, bekommt ein Sicherungsseil und wird nur mit einer Lehrkraft aufgehängt, die sich damit auskennt.

**Ablauf vor jeder Veranstaltung**

1. Laptop per USB mit X32 und Enttec verbinden, LAN-Kabel zum X32 stecken.
2. Programm starten und Profil laden.
3. DMX-Test: jedes Licht kurz einzeln an.
4. Override-Tasten einmal ausprobieren, dann geht es los.

## Bau-Reihenfolge für Claude Code

Jeder Schritt lässt sich einzeln testen. Erst wenn er läuft, kommt der nächste. Dieses Dokument geht als Markdown direkt als erste Nachricht an Claude Code. Claude Code legt es selbst als CLAUDE.md ins Projekt, damit es bei jeder späteren Aufgabe mitgelesen wird.

1. **Projekt anlegen:** Python-Projekt mit `catalog/`, `fixtures.json` (Patch), `stage.json`, `positions.json`, `x32.json` und Ordnern für Profile und Cues.
2. **Katalog und Patch:** Open Fixture Library importieren, Editor für eigene Gerätetypen, Patch-Assistent mit Adressprüfung. Dann unsere Geräte patchen.
3. **DMX-Test:** ein kleines Werkzeug, das einzelne Kanäle über das Enttec setzt. Damit jedes Gerät einmal prüfen.
4. **Simulator und 3D-Vorschau:** zeigt die DMX-Werte als Lichtkegel. Ab hier geht alles auch ohne echte Lichter.
5. **Musik-Engine:** Audio einlesen, Beat und Energie erkennen, einfache Regeln, Ausgabe an Simulator oder Enttec.
6. **Profile und Override-Tasten:** Profil laden, Grenzen durchsetzen, Blackout, Warmweiß und Pause.
7. **Szenen, Cues, Fader:** Datenmodell, Bedienoberfläche, Cueliste mit „Weiter“.
8. **Licht-Chat:** Systemprompt, Werkzeuge, Prüfung, Vorschau, „Übernehmen“.
9. **Profile per API:** Freitext → Profil-JSON → Prüfung → Vorschau.
10. **X32 übers Netzwerk:** Kanalstatus lesen, zwischen Rede und Konzert umschalten.
11. **Klick-Positionen:** Pan/Tilt-Rechnung, Kalibrierung, Sperrzone, Ziehen mit dem Finger.
12. **Generalprobe** auf der echten Bühne mit allen Geräten.

## Offene Fragen

- [ ] Variante A (2× Hero Spot 60) oder B (1× Hero Spot 60 und Hazer)?
- [ ] DMX-Modus und Startadresse für jedes Gerät festlegen
- [ ] Laptop: Windows, macOS oder Linux? Oder ein Raspberry Pi?
- [ ] Enttec Open DMX USB reicht, oder lieber das DMX USB Pro mit eigenem Prozessor?
- [ ] Bühne und Lichtpositionen ausmessen
- [ ] Welche X32-Kanäle sind Rednerpult, Band und Zuspieler?
- [ ] Wer zahlt die API-Kosten (Schule oder Förderverein), und wer verwaltet den Key?
- [ ] Strobo-Obergrenze mit der Lehrkraft festlegen

## Quellen

- [Stairville Quad Par Profile 5x8W RGBW – Thomann](https://thomann.de/lu/thomanntv_video_stairville_quad_par_profile_5x8w_rgbw_3010.html)
- [Stairville MH-X25 – Test bei bonedo](https://www.bonedo.de/artikel/stairville-mh-x25/)
- [Varytec Hero Spot 60 – Thomann](https://www.thomann.dk/varytec_hero_spot_60_b_stock.htm)
- [Stairville Hz-200 Compact Hazer DMX – Thomann](https://www.thomann.ie/stairville_hz_200_compact_hazer_dmx.htm)
- [Enttec Open DMX USB – Thomann](https://www.thomann.fr/enttec_open_dmx_usb_interface_reviews.htm?rating=5)
- [Enttec DMX USB Pro – Thomann](https://www.thomann.de/be/enttec_dmx_usb_pro_interface_b_stock_2.htm)
- [Behringer X32 Compact – Thomann](https://thomann.co.uk/behringer_x_32_compact.htm)
- [Stageworx LB-3s Lighting Stand Set – Thomann](https://www.thomann.de/be/stairville_lb_3s_lighting_stand_set_3m_si.htm)
- [LB-3s im Paket mit 4× Doughty T20301 – Thomann](https://www.thomann.fi/stairville_lb_3s_lighting_stand_se_bundle.htm)
- [Doughty T20301 Hook Clamp 20 mm – Thomann](https://www.thomann.de/gr/doughty_t20301_hookclamp_reviews.htm)
- [Stairville Safety 60cm/3mm 5kg – Thomann](https://www.thomann.de/gr/stairville_fangseil_60cm_20_mm.htm)
- [X32 Card Out: was über USB zum Computer geht – Forum](https://thefretboard.co.uk/discussion/comment/787819/)
- [pyopendmx – musikgesteuertes DMX in Python (GitHub)](https://github.com/maximecb/pyopendmx)
- [aubio – README](https://sources.debian.org/src/aubio/0.4.9-5/README.md)
- [OpenDMX: der Rechner muss das DMX-Paket selbst senden – KNX-User-Forum](https://knx-user-forum.de/forum/supportforen/smarthome-py/30142-plugin-ola-dmx)
- [DMX mit Raspberry Pi und OLA – Tom’s Hardware](https://www.tomshardware.com/uk/how-to/control-dmx-lights-raspberry-pi)
- [Open Fixture Library (GitHub)](https://github.com/OpenLightingProject/open-fixture-library)
- [grandMA3: Geräte zur Show hinzufügen (Patch) – Handbuch](https://help2.malighting.com/grandMA3/2.4/HTML/patch_add_fixtures.html)
- [grandMA3: GDTF importieren – Handbuch](https://help.malighting.com/grandMA3/2.3/HTML/ft_import_gdtf.html)
