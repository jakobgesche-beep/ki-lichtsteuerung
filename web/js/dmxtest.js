// DMX-Test: jedes Gerät kurz einzeln an, oder einzelne Kanäle setzen.
import { api, senden, t } from "./api.js";

export function dmxTestSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div>
        <div class="kasten">
          <h2>DMX-Ausgabe</h2>
          <p id="dmx-status" class="leise"></p>
          <button id="ein" class="haupt">Einschalten</button>
          <button id="aus">Ausschalten</button>
          <label>Enttec-Art <select id="dmx-art">
            <option value="auto">Automatisch erkennen</option>
            <option value="open">Open DMX USB (ohne eigenen Prozessor)</option>
            <option value="pro">DMX USB Pro (mit eigenem Prozessor)</option></select></label>
          <p class="leise">Sendet das Programm, aber kein Gerät reagiert: die andere Enttec-Art wählen. Steht auf dem
            Enttec „Pro“, ist es die Pro-Art.</p>
        </div>
        <div class="kasten">
          <h2>Einzelner Kanal</h2>
          <div class="zeile">
            <label>Kanal <input id="kanal" type="number" min="1" max="512" value="1"></label>
            <label>Wert <input id="wert" type="number" min="0" max="255" value="255"></label>
          </div>
          <input id="regler" type="range" min="0" max="255" value="255" style="width:100%">
          <p class="zeile"><button id="setzen">Setzen</button> <button id="ende">Test beenden</button></p>
          <div id="pruefung"></div>
          <p class="leise" id="ergebnis"></p>
        </div>
      </div>
      <div>
        <div class="kasten" id="gt-kasten">
        <h2>Ein Gerät testen (nur dieses Gerät)</h2>
        <p class="leise">Zum Ausprobieren, ob Enttec, Kabel und Gerät zusammen gehen. Nur dieses eine Gerät bekommt Werte,
          alle anderen Kanäle bleiben auf 0. Am Gerät im Menü die Adresse einstellen (meist „A001“ oder „d001“ = 1) und den
          DMX-Betrieb wählen (nicht Auto, Sound oder Slave). Die Kanal-Anzahl steht in der Anleitung (zum Beispiel 7CH, 9CH).</p>
        <div class="zeile">
          <label>Startadresse <input id="gt-adresse" type="number" min="1" max="512" value="1"></label>
          <label>Kanäle <input id="gt-anzahl" type="number" min="1" max="32" value="9"></label>
        </div>
        <p class="zeile"><button id="gt-start" class="haupt">Test starten</button>
          <button id="gt-ende">Test beenden</button> <span id="gt-status" class="leise"></span></p>
        <div id="gt-bereich" hidden>
          <p class="leise">Für jeden Kanal aus der Anleitung eintragen, was er macht. Dann helfen die Knöpfe.
            Kanäle für Strobo, Auto/Programm und Reset unten lassen.</p>
          <div class="tabelle-huelle"><table class="gt-tabelle" id="gt-kanaele"></table></div>
          <p class="zeile">
            <button data-gt="null">Alles auf 0</button>
            <button data-gt="licht">Licht an (weiß)</button>
            <button data-gt="rot">Rot</button><button data-gt="gruen">Grün</button><button data-gt="blau">Blau</button>
            <button data-gt="mitte">Mitte</button>
            <button data-gt="bewegen">Bewegen</button></p>
          <p class="leise" id="gt-hilfe"></p>
          <h3>Als Gerät speichern und in den Patch legen</h3>
          <div class="zeile">
            <label>Name <input id="gt-name" placeholder="zum Beispiel Moving Head Amazon"></label>
            <button id="gt-speichern">Speichern und patchen</button>
          </div>
          <p class="leise" id="gt-frei"></p>
        </div>
      </div>
      <div class="kasten" id="einmessen-kasten">
        <h2>Strobo einmessen</h2>
        <p class="leise">Damit das Programm die Grenze von 3 Blitzen pro Sekunde einhalten kann, muss es wissen,
          wie schnell der Strobo bei welchem Wert blitzt. Der Strobo blitzt dafür je 3 Sekunden.
          Filme ihn mit der Zeitlupe vom Handy und zähle die Blitze.</p>
        <label>Welches Gerät? <select id="e-geraet"></select></label>
        <div class="meldung" id="e-auswahl"></div>
        <p class="leise" id="e-hinweis"></p>
        <p class="zeile"><button id="e-zurueck" class="gefahr" hidden>Einmessung zurücknehmen</button></p>
        <label class="schalter"><input type="checkbox" id="e-ok"> Lehrkraft ist dabei, und niemand im Raum reagiert empfindlich auf Blitzlicht.</label>
        <div class="tabelle-huelle"><table id="e-tabelle">
          <tr><th>Tempo-Wert</th><th></th><th>gezählte Blitze in 3 s</th></tr>
          ${[10, 30, 60].map((w) => `<tr><td><input type="number" min="1" max="255" value="${w}" data-wert></td>
            <td><button data-blitzen>3 s blitzen</button></td><td><input type="number" min="0" step="1" data-blitze></td></tr>`).join("")}
        </table></div>
        <p class="zeile"><button id="e-auswerten" class="haupt">Auswerten</button></p>
        <div id="e-ergebnis"></div>
      </div>
      <div class="kasten tabelle-huelle">
        <h2>Jedes Gerät kurz einzeln an</h2>
        <table id="geraete"></table>
      </div>
      </div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  const kanal = () => Number(feld("kanal").value);

  async function testen(auftrag) {
    const antwort = await senden("/dmxtest", auftrag);
    feld("pruefung").innerHTML = antwort.meldungen.map((m) => `<div class="meldung gelb">${t(m)}</div>`).join("");
    if (auftrag.kanaele) feld("ergebnis").textContent = `Nach der Prüfung liegt auf Kanal ${kanal()} der Wert ${antwort.bild[kanal() - 1]}.`;
  }

  async function status() {
    const dmx = await api("/dmx");
    if (!feld("dmx-art").matches(":focus")) feld("dmx-art").value = dmx.art ?? "auto";
    feld("dmx-status").textContent = dmx.fehler ?? (dmx.eingeschaltet && dmx.weg ? `An (${dmx.weg}, ${dmx.protokoll}), sendet laufend.` : dmx.eingeschaltet
      ? "Eingeschaltet: Die Werte gehen an die Lichter."
      : dmx.enttec_gefunden ? "Aus. Enttec gefunden." : "Aus. Kein Enttec gefunden, alles läuft im Simulator.");
    feld("ein").disabled = dmx.eingeschaltet || !dmx.enttec_gefunden;
    feld("aus").disabled = !dmx.eingeschaltet;
  }

  feld("regler").oninput = () => {
    feld("wert").value = feld("regler").value;
    testen({ kanaele: { [kanal()]: Number(feld("regler").value) } });
  };
  feld("setzen").onclick = () => testen({ kanaele: { [kanal()]: Number(feld("wert").value) } });
  feld("ende").onclick = () => { feld("ergebnis").textContent = ""; testen({}); };
  feld("ein").onclick = async () => { await senden("/dmx/ein"); status(); };
  feld("aus").onclick = async () => { await senden("/dmx/aus"); status(); };
  feld("dmx-art").onchange = async () => { await senden("/dmx/art", { art: feld("dmx-art").value }).catch(() => {}); status(); };

  // --- Ein Gerät testen: nur dieses Gerät, Regler pro Kanal, Knöpfe nach Kanal-Art --------------------
  const ARTEN = [["", "?"], ["pan", "Pan"], ["pan_fein", "Pan fein"], ["tilt", "Tilt"], ["tilt_fein", "Tilt fein"],
    ["dimmer", "Dimmer"], ["rot", "Rot"], ["gruen", "Grün"], ["blau", "Blau"], ["weiss", "Weiß"], ["strobo", "Strobo / Shutter"],
    ["tempo", "Tempo (Bewegung)"], ["farbrad", "Farbrad / Farbmakro"], ["gobo", "Gobo"], ["makro", "Auto / Programm / Reset"],
    ["sonstiges", "Sonstiges"]];
  const gt = { werte: [], arten: [], bewegen: false, laeuft: false };
  const adresse = () => Math.max(1, Math.min(512, Number(feld("gt-adresse").value) || 1));
  const anzahl = () => Math.max(1, Math.min(32, Number(feld("gt-anzahl").value) || 1));
  const kanalVon = (art) => gt.arten.findIndex((a) => a === art);

  function gtTabelle() {
    const n = anzahl();
    gt.werte = Array.from({ length: n }, (_, i) => gt.werte[i] ?? 0);
    gt.arten = Array.from({ length: n }, (_, i) => gt.arten[i] ?? "");
    feld("gt-kanaele").innerHTML = `<tr><th>Kanal</th><th>DMX</th><th>macht</th><th>Wert</th><th></th></tr>` + gt.werte.map((w, i) => `
      <tr><td>${i + 1}</td><td>${adresse() + i}</td>
        <td><select data-gt-art="${i}">${ARTEN.map(([a, name]) => `<option value="${a}" ${a === gt.arten[i] ? "selected" : ""}>${name}</option>`).join("")}</select></td>
        <td><input type="range" min="0" max="255" value="${w}" data-gt-wert="${i}"></td>
        <td><span data-gt-zahl="${i}">${w}</span></td></tr>`).join("");
  }

  async function gtSenden() {
    if (!gt.laeuft) return;
    const kanaele = {};
    gt.werte.forEach((w, i) => { if (adresse() + i <= 512) kanaele[adresse() + i] = w; });
    const pan = kanalVon("pan"), tilt = kanalVon("tilt");
    const bewegen = gt.bewegen && (pan >= 0 || tilt >= 0) ? [pan >= 0 ? adresse() + pan : 0, tilt >= 0 ? adresse() + tilt : 0] : null;
    await senden("/dmxtest", { kanaele, nur: true, bewegen }).catch(() => {});
  }

  function gtZeigen() {
    gt.werte.forEach((w, i) => {
      const regler = wurzel.querySelector(`[data-gt-wert="${i}"]`);
      if (regler) regler.value = w;
      const zahl = wurzel.querySelector(`[data-gt-zahl="${i}"]`);
      if (zahl) zahl.textContent = w;
    });
    feld("gt-status").textContent = gt.laeuft ? `läuft · Kanäle ${adresse()} bis ${adresse() + anzahl() - 1}${gt.bewegen ? " · bewegt sich" : ""}` : "";
  }

  async function gtFrei() {
    try {
      const { adresse: frei } = await api(`/patch/naechste_freie?kanaele=${anzahl()}`);
      feld("gt-frei").textContent = frei
        ? `Im Patch ist ab Adresse ${frei} Platz (Kanäle ${frei} bis ${frei + anzahl() - 1}). Dort wird das Gerät gepatcht. Danach am Gerät die Adresse ${frei} einstellen (im Menü „A${String(frei).padStart(3, "0")}“).`
        : "Im Patch ist kein Platz mehr für so viele Kanäle.";
    } catch { feld("gt-frei").textContent = ""; }
  }

  function setzeArt(art, wert, nur = false) {
    gt.arten.forEach((a, i) => { if (a === art) gt.werte[i] = wert; else if (nur && ["rot", "gruen", "blau", "weiss"].includes(a)) gt.werte[i] = 0; });
  }

  feld("gt-start").onclick = async () => {
    gt.laeuft = true;
    gtTabelle();
    feld("gt-bereich").hidden = false;
    gtZeigen();
    await gtSenden();
    gtFrei();
  };
  feld("gt-ende").onclick = async () => {
    gt.laeuft = false; gt.bewegen = false;
    gtZeigen();
    await senden("/dmxtest", {}).catch(() => {});
  };
  for (const id of ["gt-adresse", "gt-anzahl"]) {
    feld(id).onchange = () => { if (gt.laeuft) { gtTabelle(); gtZeigen(); gtSenden(); gtFrei(); } };
  }
  feld("gt-kanaele").addEventListener("input", (e) => {
    const i = e.target.dataset.gtWert;
    if (i === undefined) return;
    gt.werte[Number(i)] = Number(e.target.value);
    gtZeigen();
    gtSenden();
  });
  feld("gt-kanaele").addEventListener("change", (e) => {
    const i = e.target.dataset.gtArt;
    if (i !== undefined) gt.arten[Number(i)] = e.target.value;
  });
  feld("gt-bereich").addEventListener("click", (e) => {
    const was = e.target.closest("[data-gt]")?.dataset.gt;
    if (!was) return;
    const hilfe = [];
    if (was === "null") { gt.werte = gt.werte.map(() => 0); gt.bewegen = false; }
    if (["licht", "rot", "gruen", "blau"].includes(was)) {
      if (kanalVon("dimmer") < 0) hilfe.push("Tipp: Keinen Kanal als „Dimmer“ eingetragen. Ohne Dimmer bleiben viele Geräte dunkel.");
      setzeArt("dimmer", 255);
      if (was === "licht") ["rot", "gruen", "blau", "weiss"].forEach((a) => setzeArt(a, 255));
      else setzeArt(was, 255, true);
      if (!["rot", "gruen", "blau", "weiss"].some((a) => kanalVon(a) >= 0)) hilfe.push("Tipp: Keine Farbkanäle eingetragen (Rot, Grün, Blau).");
      hilfe.push("Bleibt es dunkel: den Kanal „Strobo / Shutter“ langsam hochziehen. Manche Geräte lassen erst dann Licht raus.");
    }
    if (was === "mitte") { setzeArt("pan", 128); setzeArt("tilt", 128); setzeArt("pan_fein", 0); setzeArt("tilt_fein", 0); }
    if (was === "bewegen") {
      gt.bewegen = !gt.bewegen;
      if (kanalVon("pan") < 0 && kanalVon("tilt") < 0) { gt.bewegen = false; hilfe.push("Erst bei „macht“ eintragen, welcher Kanal Pan und welcher Tilt ist."); }
    }
    feld("gt-hilfe").textContent = hilfe.join(" ");
    gtZeigen();
    gtSenden();
  });
  feld("gt-speichern").onclick = async () => {
    const name = feld("gt-name").value.trim();
    if (!name) { feld("gt-hilfe").textContent = "Bitte einen Namen für das Gerät eingeben."; return; }
    if (gt.arten.some((a) => !a)) { feld("gt-hilfe").textContent = "Bitte bei jedem Kanal eintragen, was er macht (sonst „Sonstiges“)."; return; }
    const kanaele = {}, reihe = [];
    gt.arten.forEach((art, i) => {
      const kname = `Kanal ${i + 1} ${ARTEN.find(([a]) => a === art)[1]}`;
      const eintrag = { typ: art, standard: ["pan", "tilt"].includes(art) ? 128 : 0 };
      if (art === "pan") eintrag.grad = 540;
      if (art === "tilt") eintrag.grad = 270;
      if (art === "strobo") {
        // Der Wert, bei dem beim Testen Licht kam, ist "offen". Blitzen bleibt gesperrt (Tempo unbekannt).
        eintrag.standard = gt.werte[i];
        eintrag.bereiche = [{ von: gt.werte[i], bis: gt.werte[i], typ: "offen", name: "Licht an (beim Testen gefunden)" }];
      }
      kanaele[kname] = eintrag;
      reihe.push(kname);
    });
    const bewegt = gt.arten.includes("pan") || gt.arten.includes("tilt");
    const id = "eigene/" + name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    try {
      await senden("/katalog", { id, hersteller: "Eigene", name, kategorien: [bewegt ? "Moving Head" : "Color Changer"],
        physik: { gewicht_kg: null, abstrahlwinkel_grad: null }, kanaele,
        modi: [{ name: `${reihe.length} Kanäle`, kanaele: reihe }],
        quelle: { art: "eigener Eintrag", name: "Technik-AG (Ein Gerät testen)" }, handbuch_geprueft: false,
        _hinweis: "Mit „Ein Gerät testen“ angelegt. Pan 540°, Tilt 270° angenommen: mit der Anleitung vergleichen." });
      const { adresse: frei } = await api(`/patch/naechste_freie?kanaele=${reihe.length}`);
      await senden("/patch", { typ: id, modus: `${reihe.length} Kanäle`, anzahl: 1, name, start: frei,
        gruppen: [bewegt ? "Spots" : "Farb-PARs"], ort: "traverse" });
      feld("gt-hilfe").textContent = `Gespeichert und gepatcht auf Adresse ${frei}. Jetzt am Gerät die Adresse ${frei} einstellen. Im Patch (Setup → Patch) kannst du Ort und Gruppe ändern.`;
    } catch { /* die Meldung kommt von senden() */ }
  };

  const ART = {
    software: "noch nicht eingemessen. Blitzt trotzdem schon: Das Programm schaltet seine Helligkeit selbst, höchstens 3-mal pro Sekunde.",
    gesperrt: "noch nicht eingemessen. Sein Strobo ist gesperrt.",
    eingemessen: "eingemessen. Er blitzt mit seinem eigenen Tempo, höchstens 3-mal pro Sekunde.",
  };
  let strobos = [];
  async function strobosLaden(auswahl) {
    ({ strobos } = await api("/strobos"));
    feld("einmessen-kasten").hidden = !strobos.length;
    feld("e-geraet").innerHTML = strobos.map((g) =>
      `<option value="${t(g.id)}">${t(g.name)} · Adresse ${g.adresse}${g.rein ? "" : " (Scheinwerfer mit Shutter-Strobo)"}</option>`).join("");
    if (auswahl && strobos.some((g) => g.id === auswahl)) feld("e-geraet").value = auswahl;
    zeigeAuswahl();
  }
  function zeigeAuswahl() {
    const g = strobos.find((x) => x.id === feld("e-geraet").value);
    if (!g) return;
    feld("e-auswahl").innerHTML = `Ausgewählt: <b>${t(g.name)}</b>, DMX-Adresse <b>${g.adresse}</b>: ${t(ART[g.art] ?? "")}`;
    feld("e-hinweis").textContent = g.hinweis ?? "";
    feld("e-zurueck").hidden = !g.zuruecknehmbar;
    for (const knopf of wurzel.querySelectorAll("[data-blitzen]")) knopf.textContent = `${g.name} 3 s blitzen`;
  }
  feld("e-geraet").onchange = zeigeAuswahl;
  feld("e-zurueck").onclick = async () => {
    const g = strobos.find((x) => x.id === feld("e-geraet").value);
    if (!g || !confirm(`Einmessung von „${g.name}“ zurücknehmen? Sein Strobo ist danach wieder gesperrt.`)) return;
    const ergebnis = await senden(`/strobos/${encodeURIComponent(g.id)}/zuruecksetzen`);
    feld("e-ergebnis").innerHTML = `<div class="meldung">${t(ergebnis.text)}</div>`;
    strobosLaden(g.id);
  };
  feld("einmessen-kasten").addEventListener("click", async (ereignis) => {
    const knopf = ereignis.target.closest("[data-blitzen]");
    if (!knopf) return;
    const wert = Number(knopf.closest("tr").querySelector("[data-wert]").value);
    await senden(`/strobos/${encodeURIComponent(feld("e-geraet").value)}/blitzen`, { wert, bestaetigt: feld("e-ok").checked });
    knopf.disabled = true;
    setTimeout(() => (knopf.disabled = false), 3200);
  });
  feld("e-auswerten").onclick = async () => {
    const messungen = [...wurzel.querySelectorAll("#e-tabelle tr")].slice(1)
      .map((zeile) => ({ wert: Number(zeile.querySelector("[data-wert]").value), blitze: zeile.querySelector("[data-blitze]").value, sekunden: 3 }))
      .filter((m) => m.blitze !== "").map((m) => ({ ...m, blitze: Number(m.blitze) }));
    const ergebnis = await senden(`/strobos/${encodeURIComponent(feld("e-geraet").value)}/auswerten`, { messungen });
    feld("e-ergebnis").innerHTML = `<div class="meldung ${ergebnis.nutzbar ? "" : "gelb"}">${t(ergebnis.text)}
      <br><span class="leise">Wert ${ergebnis.von} ≈ ${ergebnis.hz_von} Blitze/s, Wert ${ergebnis.bis} ≈ ${ergebnis.hz_bis} Blitze/s.</span></div>`;
    strobosLaden(feld("e-geraet").value);
  };
  strobosLaden();

  api("/patch").then((patch) => {
    feld("geraete").innerHTML = `<tr><th>Name</th><th>Adresse</th><th></th></tr>` + patch.geraete.map((g) => `
      <tr><td>${t(g.name)}</td><td>${g.adresse}</td><td><button data-id="${t(g.id)}">An</button></td></tr>`).join("");
    wurzel.querySelectorAll("[data-id]").forEach((knopf) => {
      knopf.onclick = () => testen({ geraet: knopf.dataset.id });
    });
  });
  status();
  const zeitgeber = setInterval(status, 3000);
  return () => { clearInterval(zeitgeber); senden("/dmxtest", {}); };
}
