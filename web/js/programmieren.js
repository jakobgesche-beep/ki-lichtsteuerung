// View "Programmieren": wie an einem Lichtpult.
//   Pools (Kacheln) für Gruppen, Geräte, Farben, Positionen, Gobos und Effekte,
//   ein Fixture-Sheet mit den aktuellen Werten, Encoder für Dimmer, Pan und Tilt.
// Gelb ist ausgewählt, Rot steht im Programmer. Die Auswahl liegt im Programm selbst,
// darum sieht die Befehlszeile (und später die KI) dieselbe Auswahl.
import { api, senden, t, meldung } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";
import { executorLeiste } from "./executoren.js";

const FARBEN = {
  rot: "#ff0000", gruen: "#00ff00", blau: "#0000ff", weiss: "#ffffff", warmweiss: "#ffd9a0", gold: "#ffb030",
  orange: "#ff8000", gelb: "#ffff00", pink: "#ff00a0", lila: "#8000ff", cyan: "#00ffff", hellblau: "#80c0ff",
};
const BEWEGUNG = ["kreis", "acht", "schwenk", "nicken", "publikum"];
const prozent = (w) => `${Math.round(w * 100)}`;
const rgb = ([r, g, b], hell = 1) => `rgb(${r * hell * 255},${g * hell * 255},${b * hell * 255})`;

export function programmierenSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="programmieren">
      <div class="spalte">
        <section class="fenster"><header>Gruppen</header><div class="inhalt pool" id="gruppen"></div></section>
        <section class="fenster"><header>Geräte <span class="leise" id="auswahl-text"></span></header><div class="inhalt pool" id="geraete"></div></section>
        <section class="fenster"><header>Fixture-Sheet</header><div class="inhalt tabelle-huelle"><table class="sheet" id="sheet"></table></div></section>
      </div>
      <div class="spalte">
        <section class="fenster"><header>Farben</header><div class="inhalt pool" id="farben"></div></section>
        <section class="fenster" id="f-position"><header>Positionen <span class="leise">oder auf die Bühne tippen</span></header>
          <div class="inhalt"><canvas id="grundriss" width="400" height="230"></canvas><div class="pool" id="positionen"></div></div></section>
        <section class="fenster" id="f-gobo"><header>Gobos</header><div class="inhalt pool" id="gobos"></div></section>
        <section class="fenster"><header>Effekte</header><div class="inhalt">
          <div class="pool" id="effekte"></div>
          <div class="encoder" style="margin-top:6px">
            <label>Größe <span class="wert" id="w-groesse">50</span><input id="e-groesse" type="range" min="5" max="100" value="50"></label>
            <label>Versatz <span class="wert" id="w-verteilung">50</span><input id="e-verteilung" type="range" min="0" max="100" value="50"></label>
            <label>Beats pro Runde <select id="e-beats"><option>1</option><option>2</option><option selected>4</option><option>8</option><option>16</option></select></label>
            <label>Tempo <select id="e-tempo"><option value="musik">wie die Musik</option><option>60</option><option>90</option><option>120</option><option>140</option></select></label>
          </div>
          <div id="laufende" style="margin-top:6px"></div></div></section>
      </div>
      <div class="spalte rechts">
        <section class="fenster"><header>Vorschau
          <span class="zeile"><label class="schalter"><input type="checkbox" id="blind"> Blind</label>
          <button id="leeren" class="gefahr klein">Programmer leeren</button></span></header>
          <div class="drei-d klein" id="drei"></div></section>
        <section class="fenster"><header>Encoder <span class="leise">für die Auswahl</span></header><div class="inhalt encoder">
          <label>Dimmer <span class="wert" id="w-hell">–</span><input id="hell" type="range" min="0" max="100" value="100"></label>
          <label>Pan <span class="wert" id="w-pan">–</span><input id="pan" type="range" min="-270" max="270" value="0"></label>
          <label>Tilt <span class="wert" id="w-tilt">–</span><input id="tilt" type="range" min="-135" max="135" value="0"></label>
          <label>Gobo-Drehung <span class="wert" id="w-drehung">0</span><input id="drehung" type="range" min="-100" max="100" value="0"></label>
        </div></section>
        <section class="fenster"><header>Speichern</header><div class="inhalt">
          <div class="zeile">
            <label style="flex:1">Sequenz <select id="sequenz"></select></label>
            <label style="flex:1">Cue-Name <input id="cue-name" placeholder="zum Beispiel Rot dreht"></label>
            <label>Zeit (s) <input id="cue-zeit" type="number" min="0" step="0.5" value="2"></label>
          </div>
          <p class="zeile" style="margin:4px 0"><button id="speichern" class="haupt">Als neuen Cue speichern</button>
            <button id="neue-sequenz">Neue Sequenz</button></p>
          <div id="cueliste"></div></div></section>
      </div>
    </div>
    <section class="fenster"><header>Executoren <span class="leise">Leertaste oder → = Go+, ← = Go−</span></header>
      <div class="inhalt"><div id="executoren"></div></div></section>`;

  const feld = (id) => wurzel.querySelector("#" + id);
  const leiste = executorLeiste(feld("executoren"));
  let info = null;
  let buehne = null;
  let beendet = false;
  let pult = { auswahl: [], programmer: { werte: {}, effekte: [] } };
  let live = null;

  const gewaehlt = () => info.geraete.filter((g) => pult.auswahl.includes(g.id));
  // Nur neu zeichnen, wenn sich etwas geändert hat. Sonst gehen Klicks verloren.
  const zuletzt = new Map();
  const html = (id, inhalt) => {
    if (zuletzt.get(id) === inhalt) return;
    zuletzt.set(id, inhalt);
    feld(id).innerHTML = inhalt;
  };
  const kachel = (nr, text, daten, klasse = "", stil = "") =>
    `<button class="kachel ${klasse}" style="${stil}" ${Object.entries(daten).map(([k, v]) => `data-${k}="${t(v)}"`).join(" ")}>
      <span class="nr">${nr}</span>${t(text)}</button>`;

  async function setzen(werte) {
    if (!pult.auswahl.length) return meldung("Zuerst Geräte oder eine Gruppe wählen.");
    pult = await senden("/programmer/werte", { werte });
    allesZeigen();
  }

  async function waehlen(auftrag) {
    pult = await senden("/auswahl", auftrag);
    allesZeigen();
  }

  function poolsZeigen() {
    const geraete = gewaehlt();
    const prog = pult.programmer.werte;
    html("gruppen", info.gruppen.map((g, i) => {
      const ids = info.geraete.filter((x) => x.gruppen.includes(g)).map((x) => x.id);
      const an = ids.length && ids.every((id) => pult.auswahl.includes(id));
      return kachel(i + 1, g, { gruppe: g }, an ? "gewaehlt" : "");
    }).join(""));
    html("geraete", info.geraete.map((g) => kachel(g.nummer, g.name, { geraet: g.id },
      `${pult.auswahl.includes(g.id) ? "gewaehlt" : ""} ${prog[g.id] ? "programmer" : ""}`)
      .replace("</button>", `<span class="licht" data-licht="${t(g.id)}"></span></button>`)).join(""));
    for (const wert of live?.geraete ?? []) {
      const balken = feld("geraete").querySelector(`[data-licht="${wert.id}"]`);
      if (balken) balken.style.background = rgb(wert.farbe, wert.hell);
    }
    feld("auswahl-text").textContent = geraete.length ? `${geraete.length} gewählt` : "";
    html("farben", info.farben.map((f, i) =>
      kachel(i + 1, f, { farbe: f }, "farbe", `background:${FARBEN[f] ?? "#888"}`)).join(""));
    html("positionen", info.positionen.map((p, i) => kachel(i + 1, p, { position: p })).join(""));
    const gobos = [...new Set(geraete.flatMap((g) => g.gobos))]
      .sort((a, b) => (a === "Offen" ? -1 : b === "Offen" ? 1 : a.localeCompare(b, "de", { numeric: true })));
    html("gobos", gobos.map((g, i) => kachel(i + 1, g, { gobo: g })).join("") || `<span class="leise">Gewählte Geräte haben kein Goborad.</span>`);
    const beweglich = geraete.some((g) => g.beweglich);
    html("effekte", Object.entries(info.effekte)
      .map(([art, text], i) => kachel(i + 1, text, { effekt: art },
        pult.programmer.effekte.some((e) => e.art === art) ? "aktiv" : "",
        !beweglich && BEWEGUNG.includes(art) ? "opacity:.35" : "")).join(""));
    html("laufende", pult.programmer.effekte.map((e, i) =>
      `<div class="meldung zeile" style="justify-content:space-between">${t(info.effekte[e.art])} · ${e.ziel.gruppe ?? e.ziel.geraete.length + " Geräte"}
       <button class="klein" data-effekt-weg="${i}">Stopp</button></div>`).join(""));
  }

  function encoderZeigen() {
    const erster = gewaehlt()[0];
    const prog = erster ? pult.programmer.werte[erster.id] ?? {} : {};
    for (const [name, wert] of [["hell", prog.helligkeit], ["drehung", prog.gobo_drehung]]) {
      if (document.activeElement !== feld(name)) {
        feld(name).value = wert == null ? (name === "hell" ? 100 : 0) : Math.round(wert * 100);
        feld("w-" + name).textContent = wert == null ? "–" : prozent(wert);
      }
    }
    for (const achse of ["pan", "tilt"]) {
      const grad = erster?.[achse + "_grad"];
      feld(achse).disabled = !grad;
      if (grad) { feld(achse).min = -grad / 2; feld(achse).max = grad / 2; }
      if (document.activeElement !== feld(achse)) {
        feld(achse).value = prog[achse] ?? 0;
        feld("w-" + achse).textContent = prog[achse] == null ? "–" : `${Math.round(prog[achse])}°`;
      }
    }
    feld("f-position").hidden = !gewaehlt().some((g) => g.beweglich) && pult.auswahl.length > 0;
    feld("blind").checked = pult.blind;
  }

  function sheetZeigen() {
    const prog = pult.programmer.werte;
    html("sheet", `<tr><th>Nr</th><th>Gerät</th><th>Dim</th><th>Farbe</th><th>Position</th><th>Gobo</th></tr>` +
      info.geraete.map((g) => {
        const wert = live?.geraete.find((x) => x.id === g.id);
        const p = prog[g.id] ?? {};
        const zelle = (programmiert, text) => `<td class="${programmiert ? "prog" : ""}">${t(text)}</td>`;
        const position = p.position ?? (p.punkt ? "Punkt" : p.pan != null ? `${Math.round(p.pan)}°/${Math.round(p.tilt ?? 0)}°` : g.beweglich ? "·" : "");
        return `<tr data-geraet="${t(g.id)}" class="${pult.auswahl.includes(g.id) ? "gewaehlt" : ""}">
          <td>${g.nummer}</td><td>${t(g.name)}</td>
          ${zelle(p.helligkeit != null, wert ? prozent(p.helligkeit ?? wert.hell) : "")}
          <td class="${p.farbe ? "prog" : ""}">${wert ? `<span class="farbfleck" style="background:${rgb(wert.farbe)}"></span> ` : ""}${t(p.farbe ?? "")}</td>
          ${zelle(p.position || p.punkt || p.pan != null, position)}
          ${zelle(p.gobo, p.gobo ?? wert?.gobo ?? "")}</tr>`;
      }).join(""));
  }

  function allesZeigen() {
    if (!info) return;
    poolsZeigen();
    encoderZeigen();
    sheetZeigen();
  }

  async function sequenzenZeigen(name) {
    const { sequenzen } = await api("/pult");
    let wahl = name ?? feld("sequenz").value;
    if (!wahl) { try { wahl = localStorage.getItem("sequenz"); } catch {} }
    feld("sequenz").innerHTML = sequenzen.map((s) => `<option ${s === wahl ? "selected" : ""}>${t(s)}</option>`).join("")
      || `<option value="">(noch keine)</option>`;
    try { localStorage.setItem("sequenz", feld("sequenz").value); } catch {}
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
        <td style="white-space:nowrap"><button class="klein" data-cue-laden="${i + 1}">Bearbeiten</button>
        <button class="klein" data-cue-ueber="${i + 1}">Überschreiben</button>
        <button class="klein gefahr" data-cue-weg="${i}">×</button></td></tr>`).join("")}</table></div>`;
    feld("cueliste").dataset.sequenz = JSON.stringify(sequenz);
  }

  // Grundriss von oben, Publikum unten. Tippen setzt die Position auf Kopfhöhe.
  function masstab() {
    const m = info.aufbau.buehne;
    return Math.min(380 / m.breite_m, 175 / m.tiefe_m);
  }
  const zuPixel = (x, y) => [200 + x * masstab(), 15 + (info.aufbau.buehne.tiefe_m - y) * masstab()];
  const ausPixel = (px, py) => ({ x: (px - 200) / masstab(), y: info.aufbau.buehne.tiefe_m - (py - 15) / masstab() });
  function grundrissZeichnen() {
    const leinwand = feld("grundriss");
    const z = leinwand.getContext("2d");
    const m = info.aufbau.buehne;
    z.fillStyle = "#070708"; z.fillRect(0, 0, leinwand.width, leinwand.height);
    const [px, py] = zuPixel(-m.breite_m / 2, m.tiefe_m);
    const [qx, qy] = zuPixel(m.breite_m / 2, 0);
    z.fillStyle = "#2a2c30"; z.fillRect(px, py, qx - px, qy - py);
    z.fillStyle = "rgba(200,55,45,.25)"; z.fillRect(0, qy + 10, leinwand.width, leinwand.height - qy - 10);
    z.fillStyle = "#8d9196"; z.font = "11px sans-serif"; z.fillText("PUBLIKUM", 8, leinwand.height - 6);
    for (const [name, p] of Object.entries(info.aufbau.positionen)) {
      const [x, y] = zuPixel(p.x, p.y);
      z.fillStyle = "#f2c200"; z.beginPath(); z.arc(x, y, 3.5, 0, 7); z.fill();
      z.fillStyle = "#e3e3e3"; z.fillText(name, x + 6, y - 5);
    }
  }

  feld("sheet").addEventListener("pointerdown", (ereignis) => {
    const zeile = ereignis.target.closest("tr[data-geraet]");
    if (zeile) waehlen({ geraete: [zeile.dataset.geraet], art: "umschalten" });
  });
  wurzel.addEventListener("click", async (ereignis) => {
    const k = ereignis.target.closest("button");
    if (!k) return;
    const d = k.dataset;
    if (d.geraet) waehlen({ geraete: [d.geraet], art: "umschalten" });
    else if (d.gruppe) waehlen({ gruppe: d.gruppe, art: "umschalten" });
    else if (d.farbe) setzen({ farbe: d.farbe });
    else if (d.gobo) setzen({ gobo: d.gobo });
    else if (d.position) setzen({ position: d.position });
    else if (d.effekt) {
      if (!pult.auswahl.length) return meldung("Zuerst Geräte oder eine Gruppe wählen.");
      const tempo = feld("e-tempo").value;
      const effekt = {
        art: d.effekt, groesse: Number(feld("e-groesse").value) / 100,
        beats: Number(feld("e-beats").value), verteilung: Number(feld("e-verteilung").value) / 100,
        tempo: tempo === "musik" ? "musik" : Number(tempo),
      };
      if (d.effekt === "farbwechsel") effekt.farben = ["rot", "blau", "gruen", "lila"];
      pult = await senden("/programmer/effekt", effekt);
      allesZeigen();
    } else if (d.effektWeg !== undefined) {
      pult = await api("/programmer/effekt/" + d.effektWeg, { method: "DELETE" });
      allesZeigen();
    } else if (k.id === "leeren") { pult = await senden("/programmer/leeren"); allesZeigen(); }
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
      if (name) { await senden("/sequenzen", { name, cues: [] }); sequenzenZeigen(name); }
    } else if (d.cueLaden) {
      pult = await senden(`/sequenzen/${encodeURIComponent(feld("sequenz").value)}/cue/${d.cueLaden}/laden`);
      allesZeigen();
    } else if (d.cueWeg !== undefined) {
      const sequenz = JSON.parse(feld("cueliste").dataset.sequenz);
      if (!confirm(`Cue „${sequenz.cues[d.cueWeg].name}“ löschen?`)) return;
      sequenz.cues.splice(Number(d.cueWeg), 1);
      await senden("/sequenzen", sequenz);
      cuesZeigen();
    }
  });

  const encoder = (id, umrechnen, werte) => {
    feld(id).oninput = () => (feld("w-" + id).textContent = umrechnen(feld(id).value));
    feld(id).onchange = () => setzen(werte(Number(feld(id).value)));
  };
  encoder("hell", (w) => w, (w) => ({ helligkeit: w / 100 }));
  encoder("drehung", (w) => w, (w) => ({ gobo_drehung: w / 100 }));
  encoder("pan", (w) => w + "°", (w) => ({ pan: w, tilt: Number(feld("tilt").value) }));
  encoder("tilt", (w) => w + "°", (w) => ({ tilt: w, pan: Number(feld("pan").value) }));
  for (const id of ["groesse", "verteilung"]) feld("e-" + id).oninput = () => (feld("w-" + id).textContent = feld("e-" + id).value);
  feld("blind").onchange = async () => { pult = await senden("/programmer/blind", { an: feld("blind").checked }); allesZeigen(); };
  feld("sequenz").onchange = () => { try { localStorage.setItem("sequenz", feld("sequenz").value); } catch {} cuesZeigen(); };
  feld("grundriss").onclick = (ereignis) => {
    const rahmen = feld("grundriss").getBoundingClientRect();
    const p = ausPixel((ereignis.clientX - rahmen.left) * 400 / rahmen.width, (ereignis.clientY - rahmen.top) * 230 / rahmen.height);
    setzen({ punkt: { x: Math.round(p.x * 100) / 100, y: Math.round(p.y * 100) / 100, z: info.aufbau.buehne.hoehe_kante_m + 1.6 } });
  };
  const neuerStand = (ereignis) => { if (ereignis.detail) { pult = ereignis.detail; allesZeigen(); } };
  document.addEventListener("pult-geaendert", neuerStand);

  (async () => {
    const [daten, aufbau] = await Promise.all([api("/pult"), api("/buehne")]);
    if (beendet) return;
    info = { ...daten, aufbau };
    pult = daten.status;
    allesZeigen();
    grundrissZeichnen();
    sequenzenZeigen();
    buehne = new Buehne3D(feld("drei"), aufbau, { nah: true });
  })();

  let letzteZeichnung = 0;
  const abmelden = abonnieren((neu) => {
    if (!neu) return;
    live = neu;
    buehne?.setzeWerte(neu.vorschau.geraete ?? neu.geraete);
    leiste.zeigen(neu.pult);
    pult = neu.pult;
    // Pools und Sheet nur ein paarmal pro Sekunde neu zeichnen, das reicht und schont den Rechner.
    if (performance.now() - letzteZeichnung > 250) { letzteZeichnung = performance.now(); allesZeigen(); }
  });

  return () => {
    beendet = true;
    abmelden();
    document.removeEventListener("pult-geaendert", neuerStand);
    buehne?.beenden();
  };
}
