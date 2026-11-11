// Probe: Songs aufnehmen oder als Datei laden, daraus baut das Programm eine Lichtshow.
import { api, senden, t, meldung } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";
import { executorLeiste } from "./executoren.js";

const setzeText = (element, text) => { if (element.textContent !== text) element.textContent = text; };
const minuten = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export function probeSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div>
        <div class="kasten">
          <h2>Song aufnehmen</h2>
          <p class="leise" id="quelle"></p>
          <label>Name des Songs <input id="name" placeholder="zum Beispiel Last Christmas"></label>
          <p class="zeile"><button id="aufnahme" class="haupt">Aufnahme starten</button> <span id="zeit" class="leise"></span></p>
          <p class="leise">Die Band spielt den Song einmal ganz durch. Danach erkennt das Programm Tempo und Songteile und baut die Lichtshow.</p>
          <p class="leise"><b>Taste D</b> während der Aufnahme: „Hier war der Drop“. So lässt sich die Drop-Erkennung auf deinen Song abstimmen.</p>
        </div>
        <div class="kasten">
          <h2>Oder: Song als Datei</h2>
          <p class="leise">Zum Beispiel das Original, um schon vor der Probe zu programmieren.</p>
          <input id="datei" type="file" accept="audio/*">
        </div>
      </div>
      <div>
        <div class="drei-d klein" id="drei"></div>
        <div id="songs"></div>
      </div>
    </div>
    <div class="kasten"><h2>Executoren</h2><div id="executoren"></div></div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  const leiste = executorLeiste(feld("executoren"));
  let buehne = null;
  let beendet = false;
  let nimmtAuf = false;

  async function songsZeigen() {
    const { proben } = await api("/proben");
    feld("songs").innerHTML = proben.map((p) => `
      <div class="kasten">
        <h2>${t(p.name)} <span class="leise">${p.tempo_bpm} BPM · ${minuten(p.dauer_s)}</span></h2>
        <div class="zeitleiste">${p.teile.map((teil) => `<div class="${teil.klasse}" style="flex:${teil.ende - teil.start}"
          title="${t(teil.name)} ${teil.gruppe}: ${minuten(teil.start)} bis ${minuten(teil.ende)}">${t(teil.name)} ${teil.gruppe}</div>`).join("")}</div>
        ${(p.version ?? 1) < 2 ? `<div class="meldung gelb">Neue Song-Erkennung: „Show neu bauen“ drücken, dann wird diese Aufnahme neu analysiert (Tempo, Takte, Teile).</div>` : ""}
        ${(p.drops_s?.length || p.markiert_s?.length) ? `<p class="leise">Drops erkannt: ${(p.drops_s ?? []).map(minuten).join(", ") || "keiner"}
          ${p.markiert_s?.length ? ` · von dir markiert: ${p.markiert_s.map(minuten).join(", ")}` : ""}</p>` : ""}
        <p class="zeile">
          <button data-ansehen="${t(p.name)}" class="haupt">Probe ansehen</button>
          <button data-neu="${t(p.name)}">Show neu bauen</button>
          <button data-weg="${t(p.name)}" class="gefahr">Löschen</button></p>
        <p class="leise">Die Show liegt als Sequenz „${t(p.name)}“ im Pult. Dort kannst du jeden Cue ändern.
          Live: auf der Seite „Show“ einmal Start drücken, wenn die Band anfängt. Der Song läuft dann von selbst durch.</p>
      </div>`).join("") || `<p class="leise">Noch keine Songs aufgenommen.</p>`;
  }

  feld("aufnahme").onclick = async () => {
    if (!nimmtAuf) {
      await senden("/proben/aufnahme", { name: feld("name").value.trim() });
    } else {
      feld("aufnahme").disabled = true;
      feld("aufnahme").textContent = "Analysiere …";
      try {
        const { analyse } = await senden("/proben/stopp");
        meldung(`Fertig: ${analyse.teile.length} Songteile erkannt, ${analyse.tempo_bpm} BPM.`);
        feld("name").value = "";
      } finally { feld("aufnahme").disabled = false; }
      songsZeigen();
      leiste.laden();
    }
  };

  feld("datei").onchange = async () => {
    const datei = feld("datei").files[0];
    if (!datei) return;
    const name = feld("name").value.trim() || datei.name.replace(/\.[^.]+$/, "");
    meldung("Analysiere „" + name + "“ …");
    await api(`/proben/datei?name=${encodeURIComponent(name)}&datei=${encodeURIComponent(datei.name)}`, { method: "POST", body: datei });
    feld("datei").value = "";
    songsZeigen();
    leiste.laden();
  };

  wurzel.addEventListener("click", async (ereignis) => {
    const d = ereignis.target.dataset;
    if (d.ansehen) await senden(`/proben/${encodeURIComponent(d.ansehen)}/abspielen`);
    if (d.neu) {
      meldung("Baue die Show neu …");
      await senden(`/proben/${encodeURIComponent(d.neu)}/neu`);
      meldung("Show neu gebaut.");
      songsZeigen();
    }
    if (d.weg && confirm(`Aufnahme „${d.weg}“ löschen? Die Sequenz im Pult bleibt.`)) {
      await api(`/proben/${encodeURIComponent(d.weg)}`, { method: "DELETE" });
      songsZeigen();
    }
  });

  const abmelden = abonnieren((live) => {
    if (!live) return;
    buehne?.setzeWerte(live.geraete);
    leiste.zeigen(live.pult);
    nimmtAuf = Boolean(live.aufnahme.name);
    // Nur ändern, wenn sich etwas ändert: Wird ein Knopf beim Drücken neu beschriftet,
    // verwirft der Browser den Klick. Das war der Grund, warum "Aufnahme starten" nicht ging.
    const text = nimmtAuf ? "Aufnahme beenden und auswerten" : "Aufnahme starten";
    if (!feld("aufnahme").disabled && feld("aufnahme").textContent !== text) {
      feld("aufnahme").textContent = text;
      feld("aufnahme").classList.toggle("aufnahme-an", nimmtAuf);
    }
    setzeText(feld("zeit"), nimmtAuf ? `● ${live.aufnahme.name} ${minuten(live.aufnahme.sekunden)}` +
      (live.aufnahme.markierungen ? ` · ${live.aufnahme.markierungen}× Drop markiert` : "") : "");
    setzeText(feld("quelle"), live.audio.quelle === "aus"
      ? "Keine Tonquelle: auf der Live-Seite den Eingang (zum Beispiel X32 oder Mikrofon) wählen."
      : `Tonquelle: ${live.audio.quelle}`);
  });

  songsZeigen();
  api("/buehne").then((aufbau) => { if (!beendet) buehne = new Buehne3D(feld("drei"), aufbau, { nah: true }); });
  return () => { beendet = true; abmelden(); buehne?.beenden(); };
}
