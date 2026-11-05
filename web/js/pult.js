// Das Pult: Geräte wählen, Werte und Effekte einstellen, als Cue speichern.
// Ablauf wie bei grandMA: auswählen, einstellen, speichern, mit Go abspielen.
import { api, senden, t, meldung } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";
import { executorLeiste } from "./executoren.js";

const FARBEN_ANZEIGE = {
  rot: "#ff0000", gruen: "#00ff00", blau: "#0000ff", weiss: "#ffffff", warmweiss: "#ffd9a0", gold: "#ffb030",
  orange: "#ff8000", gelb: "#ffff00", pink: "#ff00a0", lila: "#8000ff", cyan: "#00ffff", hellblau: "#80c0ff",
};

export function pultSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="pult">
      <div class="kasten">
        <h2>1. Geräte wählen</h2>
        <div id="gruppen" class="knopfreihe"></div>
        <div id="geraete" class="knopfreihe"></div>
        <p class="leise" id="auswahl-text">Nichts gewählt</p>
      </div>
      <div class="kasten" id="werte">
        <h2>2. Einstellen</h2>
        <label>Helligkeit <span id="hell-zahl"></span><input id="hell" type="range" min="0" max="100" value="100"></label>
        <div class="unterteil"><span class="leise">Farbe</span><div id="farben" class="knopfreihe"></div></div>
        <div class="unterteil" id="teil-position">
          <span class="leise">Position: auf die Bühne tippen</span>
          <canvas id="grundriss" width="400" height="260"></canvas>
          <div id="positionen" class="knopfreihe"></div>
        </div>
        <div class="unterteil" id="teil-gobo"><span class="leise">Gobo</span><div id="gobos" class="knopfreihe"></div>
          <label>Gobo-Drehung <input id="drehung" type="range" min="-100" max="100" value="0"></label></div>
      </div>
      <div class="kasten">
        <h2>3. Effekt</h2>
        <div id="effekte" class="knopfreihe"></div>
        <div class="zeile">
          <label>Größe <input id="e-groesse" type="range" min="5" max="100" value="50"></label>
          <label>Beats pro Runde <select id="e-beats"><option>1</option><option>2</option><option selected>4</option><option>8</option><option>16</option></select></label>
          <label>Versatz <input id="e-verteilung" type="range" min="0" max="100" value="50"></label>
          <label>Tempo <select id="e-tempo"><option value="musik">wie die Musik</option><option>60</option><option>90</option><option>120</option><option>140</option></select></label>
        </div>
        <div id="laufende"></div>
      </div>
      <div class="kasten seite3d">
        <div class="zeile"><h2 style="flex:1">Vorschau</h2>
          <label class="schalter"><input type="checkbox" id="blind"> Blind</label>
          <button id="leeren" class="gefahr">Programmer leeren</button></div>
        <div class="drei-d klein" id="drei"></div>
        <p class="leise" id="blind-text"></p>
        <h2>4. Speichern</h2>
        <div class="zeile">
          <label style="flex:1">Sequenz <select id="sequenz"></select></label>
          <label style="flex:1">Cue-Name <input id="cue-name" placeholder="zum Beispiel Rot dreht"></label>
          <label>Zeit (s) <input id="cue-zeit" type="number" min="0" step="0.5" value="2"></label>
        </div>
        <p class="zeile"><button id="speichern" class="haupt">Als neuen Cue speichern</button>
          <button id="neue-sequenz">Neue Sequenz</button></p>
        <div id="cueliste"></div>
      </div>
    </div>
    <div class="kasten"><h2>Executoren <span class="leise">Leertaste oder → = Go+, ← = Go−</span></h2><div id="executoren"></div></div>`;

  const feld = (id) => wurzel.querySelector("#" + id);
  let info = null;
  let auswahl = [];
  let buehne = null;
  let beendet = false;
  const leiste = executorLeiste(feld("executoren"));

  const gewaehlt = () => info.geraete.filter((g) => auswahl.includes(g.id));
  const setzen = (werte) => {
    if (!auswahl.length) return meldung("Zuerst oben Geräte wählen.");
    return senden("/programmer/werte", { geraete: auswahl, werte }).then(zeigeProgrammer);
  };

  function knopf(text, daten, klasse = "") {
    return `<button class="${klasse}" ${Object.entries(daten).map(([k, v]) => `data-${k}="${t(v)}"`).join(" ")}>${t(text)}</button>`;
  }

  function auswahlZeigen() {
    wurzel.querySelectorAll("[data-geraet]").forEach((k) => k.classList.toggle("an", auswahl.includes(k.dataset.geraet)));
    const geraete = gewaehlt();
    feld("auswahl-text").textContent = geraete.length ? `Gewählt: ${geraete.map((g) => g.name).join(", ")}` : "Nichts gewählt";
    // Nur anbieten, was die gewählten Geräte auch können.
    const beweglich = geraete.some((g) => g.beweglich);
    feld("teil-position").hidden = !beweglich;
    const gobos = [...new Set(geraete.flatMap((g) => g.gobos))]
      .sort((a, b) => (a === "Offen" ? -1 : b === "Offen" ? 1 : a.localeCompare(b, "de", { numeric: true })));
    feld("teil-gobo").hidden = !gobos.length;
    feld("gobos").innerHTML = gobos.map((g) => knopf(g, { gobo: g })).join("");
    feld("drehung").disabled = !geraete.some((g) => g.drehung);
    feld("effekte").innerHTML = Object.entries(info.effekte)
      .filter(([art]) => beweglich || !["kreis", "acht", "schwenk", "nicken", "publikum"].includes(art))
      .map(([art, text]) => knopf(text, { effekt: art })).join("");
  }

  function zeigeProgrammer(status) {
    const p = status.programmer;
    const anzahl = Object.keys(p.werte).length;
    feld("laufende").innerHTML = p.effekte.map((e, i) =>
      `<div class="meldung zeile">${t(info.effekte[e.art])} auf ${t(e.ziel.gruppe ?? e.ziel.geraete.length + " Geräten")}
       <button data-effekt-weg="${i}">Stopp</button></div>`).join("");
    feld("blind").checked = status.blind;
    feld("blind-text").textContent = status.blind
      ? "Blind: Der Programmer ist nur hier zu sehen, nicht auf der Bühne."
      : anzahl || p.effekte.length ? `Live: ${anzahl} Geräte im Programmer.` : "Programmer ist leer.";
  }

  async function sequenzenZeigen(name) {
    const { sequenzen } = await api("/pult");
    const wahl = name ?? feld("sequenz").value;
    feld("sequenz").innerHTML = sequenzen.map((s) => `<option ${s === wahl ? "selected" : ""}>${t(s)}</option>`).join("")
      || `<option value="">(noch keine)</option>`;
    leiste.laden();
    cuesZeigen();
  }

  async function cuesZeigen() {
    const name = feld("sequenz").value;
    if (!name) return (feld("cueliste").innerHTML = "");
    const sequenz = await api("/sequenzen/" + encodeURIComponent(name));
    feld("cueliste").innerHTML = `<div class="tabelle-huelle"><table>
      <tr><th>#</th><th>Cue</th><th>Zeit</th><th></th></tr>
      ${sequenz.cues.map((c, i) => `<tr><td>${i + 1}</td><td>${t(c.name)}</td><td>${c.zeit_s ?? 0} s</td>
        <td><button data-cue-laden="${i + 1}">Bearbeiten</button> <button data-cue-ueber="${i + 1}">Überschreiben</button>
        <button data-cue-weg="${i}" class="gefahr">×</button></td></tr>`).join("")}</table></div>`;
    feld("cueliste").dataset.sequenz = JSON.stringify(sequenz);
  }

  // Grundriss: von oben auf die Bühne, Publikum unten. Tippen setzt die Position.
  function grundrissZeichnen() {
    const leinwand = feld("grundriss");
    const z = leinwand.getContext("2d");
    const { buehne: m } = info.aufbau;
    z.fillStyle = "#101113"; z.fillRect(0, 0, leinwand.width, leinwand.height);
    const [px, py] = zuPixel(-m.breite_m / 2, m.tiefe_m);
    const [qx, qy] = zuPixel(m.breite_m / 2, 0);
    z.fillStyle = "#34373b"; z.fillRect(px, py, qx - px, qy - py);
    z.fillStyle = "rgba(192,69,58,.25)"; z.fillRect(0, qy + 12, leinwand.width, leinwand.height - qy - 12);
    z.fillStyle = "#9a9ea3"; z.font = "12px sans-serif"; z.fillText("Publikum", 8, leinwand.height - 8);
    for (const [name, p] of Object.entries(info.aufbau.positionen)) {
      const [x, y] = zuPixel(p.x, p.y);
      z.fillStyle = "#4a7fb5"; z.beginPath(); z.arc(x, y, 4, 0, 7); z.fill();
      z.fillStyle = "#e6e6e6"; z.fillText(name, x + 6, y - 6);
    }
  }
  function zuPixel(x, y) {
    const m = info.aufbau.buehne;
    const masstab = Math.min(380 / m.breite_m, 200 / m.tiefe_m);
    return [200 + x * masstab, 20 + (m.tiefe_m - y) * masstab];
  }
  function ausPixel(px, py) {
    const m = info.aufbau.buehne;
    const masstab = Math.min(380 / m.breite_m, 200 / m.tiefe_m);
    return { x: (px - 200) / masstab, y: m.tiefe_m - (py - 20) / masstab };
  }

  wurzel.addEventListener("click", async (ereignis) => {
    const k = ereignis.target.closest("button");
    if (!k) return;
    const d = k.dataset;
    if (d.geraet) {
      auswahl = auswahl.includes(d.geraet) ? auswahl.filter((i) => i !== d.geraet) : [...auswahl, d.geraet];
      auswahlZeigen();
    } else if (d.gruppe) {
      const ids = info.geraete.filter((g) => g.gruppen.includes(d.gruppe)).map((g) => g.id);
      auswahl = ids.every((i) => auswahl.includes(i)) ? auswahl.filter((i) => !ids.includes(i)) : [...new Set([...auswahl, ...ids])];
      auswahlZeigen();
    } else if (d.farbe) setzen({ farbe: d.farbe });
    else if (d.gobo) setzen({ gobo: d.gobo });
    else if (d.position) setzen({ position: d.position });
    else if (d.effekt) {
      if (!auswahl.length) return meldung("Zuerst oben Geräte wählen.");
      const tempo = feld("e-tempo").value;
      const effekt = {
        art: d.effekt, ziel: { geraete: auswahl }, groesse: Number(feld("e-groesse").value) / 100,
        beats: Number(feld("e-beats").value), verteilung: Number(feld("e-verteilung").value) / 100,
        tempo: tempo === "musik" ? "musik" : Number(tempo),
      };
      if (d.effekt === "farbwechsel") effekt.farben = ["rot", "blau", "gruen", "lila"];
      zeigeProgrammer(await senden("/programmer/effekt", effekt));
    } else if (d.effektWeg !== undefined) {
      zeigeProgrammer(await api("/programmer/effekt/" + d.effektWeg, { method: "DELETE" }));
    } else if (k.id === "leeren") zeigeProgrammer(await senden("/programmer/leeren"));
    else if (k.id === "speichern" || d.cueUeber) {
      let name = feld("sequenz").value;
      if (!name) {
        name = prompt("Name der neuen Sequenz:", "Weihnachtsmarkt");
        if (!name) return;
      }
      const auftrag = { cue_name: feld("cue-name").value || "Cue", zeit_s: Number(feld("cue-zeit").value) };
      if (d.cueUeber) auftrag.nummer = Number(d.cueUeber);
      await senden(`/sequenzen/${encodeURIComponent(name)}/speichern`, auftrag);
      feld("cue-name").value = "";
      sequenzenZeigen(name);
    } else if (k.id === "neue-sequenz") {
      const name = prompt("Name der neuen Sequenz:", "Weihnachtsmarkt");
      if (name) {
        await senden("/sequenzen", { name, cues: [] });
        sequenzenZeigen(name);
      }
    } else if (d.cueLaden) {
      zeigeProgrammer(await senden(`/sequenzen/${encodeURIComponent(feld("sequenz").value)}/cue/${d.cueLaden}/laden`));
    } else if (d.cueWeg !== undefined) {
      const sequenz = JSON.parse(feld("cueliste").dataset.sequenz);
      if (!confirm(`Cue „${sequenz.cues[d.cueWeg].name}“ löschen?`)) return;
      sequenz.cues.splice(Number(d.cueWeg), 1);
      await senden("/sequenzen", sequenz);
      cuesZeigen();
    }
  });

  feld("hell").oninput = () => (feld("hell-zahl").textContent = feld("hell").value + " %");
  feld("hell").onchange = () => setzen({ helligkeit: Number(feld("hell").value) / 100 });
  feld("drehung").onchange = () => setzen({ gobo_drehung: Number(feld("drehung").value) / 100 });
  feld("blind").onchange = async () => zeigeProgrammer(await senden("/programmer/blind", { an: feld("blind").checked }));
  feld("sequenz").onchange = cuesZeigen;
  feld("grundriss").onclick = (ereignis) => {
    const rahmen = feld("grundriss").getBoundingClientRect();
    const p = ausPixel((ereignis.clientX - rahmen.left) * 400 / rahmen.width, (ereignis.clientY - rahmen.top) * 260 / rahmen.height);
    setzen({ punkt: { x: Math.round(p.x * 100) / 100, y: Math.round(p.y * 100) / 100, z: info.aufbau.buehne.hoehe_kante_m + 1.6 } });
  };

  (async () => {
    const [pult, aufbau] = await Promise.all([api("/pult"), api("/buehne")]);
    if (beendet) return;
    info = { ...pult, aufbau };
    feld("gruppen").innerHTML = info.gruppen.map((g) => knopf(g, { gruppe: g }, "gruppe")).join("");
    feld("geraete").innerHTML = info.geraete.map((g) => knopf(g.name, { geraet: g.id })).join("");
    feld("farben").innerHTML = info.farben.map((f) =>
      `<button data-farbe="${f}" class="farbknopf" style="--f:${FARBEN_ANZEIGE[f] ?? "#888"}" title="${f}"></button>`).join("");
    feld("positionen").innerHTML = info.positionen.map((p) => knopf(p, { position: p })).join("");
    auswahlZeigen();
    zeigeProgrammer(pult.status);
    grundrissZeichnen();
    sequenzenZeigen();
    buehne = new Buehne3D(feld("drei"), aufbau, { nah: true });
  })();

  const abmelden = abonnieren((live) => {
    if (!live) return;
    buehne?.setzeWerte(live.vorschau.geraete ?? live.geraete);
    leiste.zeigen(live.pult);
  });

  return () => {
    beendet = true;
    abmelden();
    buehne?.beenden();
  };
}
