// Setup → MIDI: echte Fader und Tasten (zum Beispiel Akai APC mini) und der Takt vom Schlagzeug (MIDI-Clock).
import { api, senden, t } from "./api.js";

// "cc:*:48" -> "Regler 48", "note:1:5" -> "Taste 5 (Kanal 1)"
function reglerText(regler) {
  const [art, kanal, nummer] = regler.split(":");
  const name = art === "cc" ? "Regler" : "Taste";
  return `${name} ${nummer}${kanal === "*" ? "" : ` (Kanal ${kanal})`}`;
}

export function midiSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div>
        <div class="kasten"><h2>MIDI-Gerät</h2>
          <p class="leise">Ein MIDI-Controller am USB, zum Beispiel ein Akai APC mini (etwa 70 €): echte Fader und Tasten.
            Im Dunkeln ist das sicherer als die Maus.</p>
          <label>Gerät <select id="midi-geraet"></select></label>
          <p id="midi-status" class="leise"></p>
          <p class="leise">Zuletzt am Gerät: <b id="midi-zuletzt">–</b></p>
        </div>
        <div class="kasten"><h2>Fertige Belegung</h2>
          <p class="leise">Für diese Geräte gibt es eine Belegung zum Anfangen. Sie ist ohne Gerät gebaut: einmal alles
            ausprobieren und was nicht passt neu lernen.</p>
          <p class="zeile"><select id="midi-vorlage"></select> <button id="midi-vorlage-laden">Laden</button>
            <button id="midi-alles-weg" class="gefahr">Alles löschen</button></p>
          <p class="leise">APC mini: Fader 1–8 und rechts der Grand Master. Raster unten: Go+, darüber Flash, darüber Aus.
            Oben: Looks 1–8, darunter Look 9, Look aus, Weiß voll, Strobo, Dunkel, Blackout, Tap, Go+.</p>
        </div>
        <div class="kasten"><h2>Takt vom Schlagzeug (MIDI-Clock)</h2>
          <label class="schalter"><input type="checkbox" id="midi-clock"> MIDI-Clock benutzen</label>
          <p id="midi-clock-status" class="leise"></p>
          <p class="leise">Schickt die Band einen Click über MIDI (zum Beispiel aus dem Laptop am Schlagzeug), laufen alle
            Effekte genau in diesem Tempo und auf diesen Schlägen. Tap geht trotzdem immer vor.</p>
        </div>
      </div>
      <div>
        <div class="kasten"><h2>Belegung</h2>
          <p class="leise">„Lernen“ drücken, dann am Gerät den Regler bewegen oder die Taste drücken. Ein echter Fader
            übernimmt erst, wenn er am Wert der Software vorbeikommt: So springt nach einem Seitenwechsel nichts.</p>
          <div class="tabelle-huelle"><table class="midi-tabelle" id="midi-tabelle"></table></div>
        </div>
      </div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  let stand = "";
  let geraeteStand = "";

  function zeigen(z) {
    const geraete = JSON.stringify([z.geraete, z.geraet]);
    if (geraete !== geraeteStand && !feld("midi-geraet").matches(":focus")) {
      geraeteStand = geraete;
      const namen = [...new Set([...(z.geraet ? [z.geraet] : []), ...z.geraete])];
      feld("midi-geraet").innerHTML = `<option value="">Kein MIDI-Gerät</option>` +
        namen.map((n) => `<option value="${t(n)}" ${n === z.geraet ? "selected" : ""}>${t(n)}</option>`).join("");
    }
    if (!feld("midi-vorlage").options.length) {
      feld("midi-vorlage").innerHTML = z.vorlagen.map((v) => `<option value="${t(v.id)}">${t(v.name)}</option>`).join("");
    }
    const status = !z.verfuegbar ? "MIDI geht in diesem Programm nicht (Bibliothek fehlt)."
      : z.verbunden ? `Verbunden mit „${z.verbunden}“ ✓`
      : z.fehler ? z.fehler
      : z.geraete.length ? "Kein Gerät gewählt." : "Kein MIDI-Gerät gefunden. Gerät anstecken, es erscheint dann hier.";
    feld("midi-status").textContent = status;
    feld("midi-status").className = z.verbunden ? "ok-text" : "leise";
    feld("midi-zuletzt").textContent = z.zuletzt ? z.zuletzt.text : "–";
    if (!feld("midi-clock").matches(":focus")) feld("midi-clock").checked = z.clock.an;
    feld("midi-clock-status").textContent = !z.clock.an ? "Aus." : z.clock.bpm ? `Clock kommt an: ${z.clock.bpm} BPM ✓` : "Kein Clock da (dann gilt das gehörte Tempo).";
    const neu = JSON.stringify([z.belegung, z.lernen]);
    if (neu === stand) return;
    stand = neu;
    const belegt = new Map();
    for (const b of z.belegung) belegt.set(b.aufgabe, [...(belegt.get(b.aufgabe) ?? []), b.regler]);
    feld("midi-tabelle").innerHTML = `<tr><th>Aufgabe</th><th>am Gerät</th><th></th></tr>` + z.aufgaben.map((a) => {
      const regler = belegt.get(a.schluessel) ?? [];
      const lernt = z.lernen === a.schluessel;
      return `<tr class="${lernt ? "lernt" : ""}"><td>${t(a.name)}</td>
        <td>${lernt ? "<b>Jetzt am Gerät bewegen oder drücken …</b>" : regler.map(reglerText).join(", ") || `<span class="leise">–</span>`}</td>
        <td class="zeile" style="flex-wrap:nowrap"><button class="klein ${lernt ? "an" : ""}" data-lernen="${t(a.schluessel)}">${lernt ? "Abbrechen" : "Lernen"}</button>
          ${regler.length ? `<button class="klein" data-weg="${t(a.schluessel)}" title="Belegung löschen">×</button>` : ""}</td></tr>`;
    }).join("");
  }

  async function laden() {
    try { zeigen(await api("/midi")); } catch { /* Meldung kommt von api() */ }
  }

  feld("midi-geraet").onchange = async () => zeigen(await senden("/midi/geraet", { name: feld("midi-geraet").value }));
  feld("midi-vorlage-laden").onclick = async () => {
    if (!confirm("Die fertige Belegung ersetzt die jetzige. Weiter?")) return;
    zeigen(await senden("/midi/vorlage", { id: feld("midi-vorlage").value }));
  };
  feld("midi-alles-weg").onclick = async () => {
    if (confirm("Die ganze MIDI-Belegung löschen?")) zeigen(await senden("/midi/loeschen", { alles: true }));
  };
  feld("midi-clock").onchange = async () => zeigen(await senden("/midi/clock", { an: feld("midi-clock").checked }));
  feld("midi-tabelle").addEventListener("click", async (ereignis) => {
    const knopf = ereignis.target.closest("button");
    if (!knopf) return;
    if (knopf.dataset.lernen) {
      const abbrechen = knopf.classList.contains("an");
      zeigen(await senden("/midi/lernen", { aufgabe: abbrechen ? null : knopf.dataset.lernen }));
    }
    if (knopf.dataset.weg) zeigen(await senden("/midi/loeschen", { aufgabe: knopf.dataset.weg }));
  });

  laden();
  const uhr = setInterval(laden, 700);
  return () => {
    clearInterval(uhr);
    senden("/midi/lernen", { aufgabe: null }).catch(() => {});
  };
}
