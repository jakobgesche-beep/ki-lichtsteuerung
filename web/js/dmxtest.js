// DMX-Test: jedes Gerät kurz einzeln an, oder einzelne Kanäle setzen.
import { api, senden, t } from "./api.js";

export function dmxTestSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div>
        <div class="kasten">
          <h2>DMX-Ausgabe</h2>
          <p id="status" class="leise"></p>
          <button id="ein" class="haupt">Einschalten</button>
          <button id="aus">Ausschalten</button>
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
    feld("status").textContent = dmx.fehler ?? (dmx.eingeschaltet && dmx.weg ? `An (${dmx.weg}), sendet laufend.` : dmx.eingeschaltet
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
