// Live-Seite: 3D-Bühne und Bedienung am Abend.
import { api, t } from "./api.js";
import { Buehne3D } from "./buehne3d.js";

export function liveSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="live">
      <div class="drei-d" id="drei"></div>
      <div id="seite">
        <div class="kasten"><h2>Status</h2><div id="status" class="leise"></div></div>
        <div id="meldungen"></div>
      </div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  let buehne = null;
  let leitung = null;
  let beendet = false;

  function verbinden() {
    const adresse = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live`;
    leitung = new WebSocket(adresse);
    leitung.onmessage = (nachricht) => zeigen(JSON.parse(nachricht.data));
    leitung.onclose = () => {
      if (beendet) return;
      feld("status").textContent = "Verbindung zum Programm unterbrochen …";
      setTimeout(verbinden, 1000);
    };
  }

  function zeigen(live) {
    buehne?.setzeWerte(live.geraete);
    feld("status").textContent = live.dmx_ein ? "DMX-Ausgabe: eingeschaltet" : "DMX-Ausgabe: aus (Simulator)";
    feld("meldungen").innerHTML = live.meldungen.map((m) => `<div class="meldung gelb">${t(m)}</div>`).join("");
  }

  api("/buehne").then((aufbau) => {
    if (beendet) return;
    buehne = new Buehne3D(feld("drei"), aufbau);
    verbinden();
  });

  return () => {
    beendet = true;
    leitung?.close();
    buehne?.beenden();
  };
}
