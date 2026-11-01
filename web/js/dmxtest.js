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
      <div class="kasten tabelle-huelle">
        <h2>Jedes Gerät kurz einzeln an</h2>
        <table id="geraete"></table>
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
    feld("status").textContent = dmx.fehler ?? (dmx.eingeschaltet
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
