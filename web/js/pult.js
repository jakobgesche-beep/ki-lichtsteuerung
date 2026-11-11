// View "Pult": alles auf einem Bildschirm, aufgebaut wie ein großes Lichtpult (grandMA-Stil, nur kleiner).
//
//   oben links    Pools: Gruppen, Geräte, Sequenzen. Klick wählt aus (gelb), rot = steht im Programmer.
//   darunter      Feature-Leiste: Dimmer, Position, Farbe, Gobo, Strahl, Effekt, jeweils mit Presets und Encodern
//   Mitte         Bühne (live oder Vorschau) und die Cue-Liste des gewählten Faders (Sequence Sheet)
//   rechts        Licht-Chat: beschreiben, was man will, Vorschau ansehen, auf einen Fader legen
//   unten         Tasten wie am Pult und 10 Fader pro Seite, rechts Seiten und Grand Master
//
// Tasten wie am Pult: erst die Taste, dann das Ziel antippen.
//   Store → Fader            Programmer als neuen Cue speichern (leerer Fader: neue Sequenz)
//   Update → Fader           Programmer in den laufenden Cue einarbeiten
//   Assign → Sequenz/Gruppe/Tempo → Fader
//   Delete → Fader / Sequenz / Cue      Label → Fader      Edit → Fader (Cue-Liste bearbeiten)
//   Oops (Rückgängig), Clear (erst Auswahl, dann Programmer), Highlight, Blind
import { api, senden, t, meldung } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";
import { executorLeiste } from "./executoren.js";
import { lichtChat } from "./chat.js";

const FARBEN = {
  rot: "#ff0000", gruen: "#00ff00", blau: "#0000ff", weiss: "#ffffff", warmweiss: "#ffd9a0", gold: "#ffb030",
  orange: "#ff8000", gelb: "#ffff00", pink: "#ff00a0", lila: "#8000ff", cyan: "#00ffff", hellblau: "#80c0ff",
};
const FARB_NAMEN = { gruen: "Grün", weiss: "Weiß", warmweiss: "Warmweiß", hellblau: "Hellblau" };
const BEWEGUNG = ["kreis", "acht", "schwenk", "nicken", "publikum"];
const FEATURES = [["dimmer", "Dimmer"], ["position", "Position"], ["farbe", "Farbe"], ["gobo", "Gobo"],
  ["strahl", "Strahl"], ["effekt", "Effekt"]];
const TASTEN = [
  ["store", "Store"], ["update", "Update"], ["assign", "Assign"], ["delete", "Delete"], ["label", "Label"],
  ["edit", "Edit"], ["oops", "Oops"], ["clear", "Clear"], ["highlight", "Highlight"], ["blind", "Blind"],
];
const HINWEIS = {
  store: "Store: Fader antippen (leerer Fader = neue Sequenz) oder eine Sequenz im Pool.",
  update: "Update: Fader antippen. Der Programmer kommt in den laufenden Cue.",
  assign: "Assign: erst Sequenz, Gruppe oder Tempo antippen, dann den Fader.",
  delete: "Delete: Fader (wird frei), Sequenz im Pool oder Cue in der Liste antippen.",
  label: "Label: Fader antippen und Namen eingeben.",
  edit: "Edit: Fader antippen. Seine Cue-Liste lässt sich dann bearbeiten.",
};

const prozent = (w) => `${Math.round(w * 100)}`;
const farbName = (f) => FARB_NAMEN[f] ?? (f.charAt(0).toUpperCase() + f.slice(1));
const rgb = ([r, g, b], hell = 1) => `rgb(${r * hell * 255},${g * hell * 255},${b * hell * 255})`;
const hex = (zahl) => Math.round(zahl).toString(16).padStart(2, "0");

export function pultSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="pultplatz" id="platz">
      <div class="pp-oben">
        <div class="pp-links">
          <section class="fenster pp-pools">
            <div class="pool-zeile"><span class="pool-titel">Gruppen</span><div class="pool klein" id="gruppen"></div></div>
            <div class="pool-zeile"><span class="pool-titel">Geräte <span class="leise" id="auswahl-text"></span></span><div class="pool klein" id="geraete"></div></div>
            <div class="pool-zeile"><span class="pool-titel">Sequenzen</span><div class="pool klein" id="sequenzen"></div></div>
          </section>
          <section class="fenster pp-feature">
            <header><span class="feature-reiter" id="features"></span>
              <span class="leise" id="feature-hinweis"></span></header>
            <div class="inhalt" id="feature"></div>
          </section>
        </div>
        <div class="pp-mitte">
          <section class="fenster pp-buehne"><header><span id="buehne-titel">Bühne live</span>
              <span class="zeile"><span class="leise" id="programmer-text"></span></span></header>
            <div class="drei-d pp-drei" id="drei"></div></section>
          <section class="fenster pp-sheet"><header><span id="sheet-titel">Cue-Liste</span>
              <span class="leise" id="sheet-hinweis">Klick = Goto</span></header>
            <div class="inhalt tabelle-huelle" id="sheet"></div></section>
        </div>
        <section class="fenster pp-chat" id="chat-fenster"></section>
      </div>
      <div class="pp-tasten" id="tasten"></div>
      <div class="pp-fader" id="fader"></div>
    </div>`;

  const feld = (id) => wurzel.querySelector("#" + id);
  const zuletzt = new Map();
  const html = (id, inhalt) => {
    if (zuletzt.get(id) === inhalt) return;
    zuletzt.set(id, inhalt);
    feld(id).innerHTML = inhalt;
  };
  let info = null;
  let pult = null;
  let live = null;
  let pool = [];
  let buehne = null;
  let beendet = false;
  let feature = "dimmer";
  let modus = null;              // gedrückte Pult-Taste, die auf ein Ziel wartet
  let assignQuelle = null;       // bei Assign: was zugewiesen wird
  let sheetSequenz = null;       // diese Sequenz zeigt die Cue-Liste (sonst die des gewählten Faders)
  let sheetBearbeiten = false;
  let sheetDaten = null;
  let sheetStand = "";

  // --- Tasten wie am Pult -------------------------------------------------------

  feld("tasten").innerHTML = TASTEN.map(([id, text]) => `<button data-pulttaste="${id}">${text}</button>`).join("")
    + `<span class="pp-modus" id="modus-text"></span>`;

  function modusSetzen(neu) {
    modus = neu;
    assignQuelle = null;
    wurzel.querySelectorAll("[data-pulttaste]").forEach((k) => k.classList.toggle("wartet", k.dataset.pulttaste === modus));
    feld("platz").classList.toggle("zielwahl", Boolean(modus));
    feld("modus-text").textContent = modus ? HINWEIS[modus] + "  (Esc = abbrechen)" : "";
    const befehl = document.getElementById("befehl");
    if (befehl) befehl.placeholder = modus ? HINWEIS[modus] : "zum Beispiel: Gruppe Spots auf 80 Farbe Rot";
  }

  async function befehl(text) {
    const antwort = await senden("/befehl", { text, sequenz: sheetSequenz });
    if (antwort.status) pultAnnehmen(antwort.status);
    const zeile = document.getElementById("antwort");
    if (zeile) { zeile.textContent = antwort.antwort; zeile.classList.remove("fehler"); }
    return antwort;
  }

  async function pultTaste(id) {
    if (["store", "update", "assign", "delete", "label", "edit"].includes(id)) {
      return modusSetzen(modus === id ? null : id);
    }
    modusSetzen(null);
    if (id === "oops") {
      const antwort = await senden("/oops");
      pultAnnehmen(antwort.status);
      meldungLeise(antwort.antwort);
      poolLaden();
      sheetStand = "";
    } else if (id === "clear") {
      await befehl("Clear");
    } else if (id === "highlight") {
      pultAnnehmen(await senden("/highlight", { an: !pult?.highlight }));
    } else if (id === "blind") {
      pultAnnehmen(await senden("/programmer/blind", { an: !pult?.blind }));
    }
  }

  function meldungLeise(text) {
    const zeile = document.getElementById("antwort");
    if (zeile) { zeile.textContent = text; zeile.classList.remove("fehler"); }
  }

  // Ein Fader wurde angetippt, während eine Taste wartet. true heißt: Klick ist verbraucht.
  function faderZiel(nummer) {
    if (!modus) return false;
    const aktion = modus;
    const executor = pult?.executoren[nummer - 1];
    modusSetzen(null);
    (async () => {
      if (aktion === "store") {
        const antwort = await senden(`/executor/${nummer}/speichern`, {});
        pultAnnehmen(antwort.status);
        meldungLeise(`Gespeichert: Fader ${nummer}, ${antwort.sequenz}, Cue ${antwort.cues}`);
        poolLaden();
        sheetSequenz = null;
        sheetStand = "";
      } else if (aktion === "update") {
        const antwort = await senden(`/executor/${nummer}/update`);
        pultAnnehmen(antwort.status);
        meldungLeise(`Update: ${antwort.sequenz}`);
        sheetStand = "";
      } else if (aktion === "assign") {
        meldung("Assign: zuerst eine Sequenz, Gruppe oder Tempo antippen, dann den Fader.");
      } else if (aktion === "delete") {
        if (!executor?.art) return;
        pultAnnehmen(await senden(`/executor/${nummer}/belegen`, {}));
        meldungLeise(`Fader ${nummer} ist frei (die Sequenz bleibt im Pool). Oops holt ihn zurück.`);
        poolLaden();
      } else if (aktion === "label") {
        if (!executor?.art) return meldung("Auf diesem Fader liegt nichts.");
        const name = prompt(`Name für Fader ${nummer}:`, executor.name);
        if (name !== null) pultAnnehmen(await senden(`/executor/${nummer}/label`, { label: name }));
      } else if (aktion === "edit") {
        if (executor?.art !== "sequenz") return meldung("Edit geht auf einen Fader mit Sequenz.");
        await befehl(`Fader ${nummer}`);
        sheetSequenz = null;
        sheetBearbeiten = true;
        sheetStand = "";
      }
    })().catch(() => {});
    return true;
  }

  // Assign hat zwei Schritte: Quelle, dann Fader.
  function assignFader(nummer) {
    if (modus !== "assign" || !assignQuelle) return faderZiel(nummer);
    const quelle = assignQuelle;
    modusSetzen(null);
    senden(`/executor/${nummer}/belegen`, quelle).then((status) => {
      pultAnnehmen(status);
      meldungLeise(`Fader ${nummer}: ${quelle.sequenz ?? quelle.gruppe ?? "Tempo"}`);
      poolLaden();
    }).catch(() => {});
    return true;
  }

  const fader = executorLeiste(feld("fader"), { zielWahl: assignFader });

  // --- Pools --------------------------------------------------------------------

  const kachel = (nr, text, daten, klasse = "", stil = "", extra = "") =>
    `<button class="kachel ${klasse}" style="${stil}" ${Object.entries(daten).map(([k, v]) => `data-${k}="${t(v)}"`).join(" ")}>
      <span class="nr">${nr}</span>${t(text)}${extra}</button>`;

  const gewaehlt = () => info.geraete.filter((g) => pult.auswahl.includes(g.id));

  async function poolLaden() {
    pool = (await api("/sequenzen")).sequenzen;
    zuletzt.delete("sequenzen");
    poolsZeigen();
  }

  function poolsZeigen() {
    if (!info || !pult) return;
    const prog = pult.programmer.werte;
    html("gruppen", info.gruppen.map((g, i) => {
      const ids = info.geraete.filter((x) => x.gruppen.includes(g)).map((x) => x.id);
      const an = ids.length && ids.every((id) => pult.auswahl.includes(id));
      const quelle = modus === "assign" && assignQuelle?.gruppe === g;
      return kachel(i + 1, g, { gruppe: g }, `${an ? "gewaehlt" : ""} ${quelle ? "quelle" : ""}`);
    }).join("") + kachel("", "Alle", { alle: 1 }, info.geraete.every((g) => pult.auswahl.includes(g.id)) ? "gewaehlt" : ""));
    html("geraete", info.geraete.map((g) => kachel(g.nummer, g.name, { geraet: g.id },
      `${pult.auswahl.includes(g.id) ? "gewaehlt" : ""} ${prog[g.id] ? "programmer" : ""}`, "",
      `<span class="licht" data-licht="${t(g.id)}"></span>`)).join(""));
    for (const wert of live?.geraete ?? []) {
      const balken = feld("geraete").querySelector(`[data-licht="${wert.id}"]`);
      if (balken) balken.style.background = rgb(wert.farbe, Math.max(0.15, wert.hell));
    }
    const anzahl = gewaehlt().length;
    feld("auswahl-text").textContent = anzahl ? `${anzahl} gewählt` : "";
    const haupt = pult.haupt_info?.sequenz;
    html("sequenzen", pool.map((s, i) => kachel(i + 1, s.name, { sequenz: s.name },
      `${s.name === (sheetSequenz ?? haupt) ? "aktiv" : ""} ${modus === "assign" && assignQuelle?.sequenz === s.name ? "quelle" : ""}`, "",
      `<span class="unten">${s.song ? "♪ " : ""}${s.cues} Cues${s.fader.length ? " · F" + s.fader.join(",") : ""}</span>`)).join("")
      + kachel("", "Tempo-Fader", { tempo: 1 }, modus === "assign" && assignQuelle?.art === "tempo" ? "quelle" : "", "", `<span class="unten">für Effekte</span>`));
    const titel = pult.blind ? "Vorschau (Blind)" : live?.chat_vorschau ? "Vorschau Licht-Chat" : "Bühne live";
    if (feld("buehne-titel").textContent !== titel) feld("buehne-titel").textContent = titel;
    feld("buehne-titel").classList.toggle("vorschau-titel", titel !== "Bühne live");
    const progAnzahl = Object.keys(prog).length + pult.programmer.effekte.length;
    const progText = progAnzahl ? `Programmer: ${Object.keys(prog).length} Geräte${pult.programmer.effekte.length ? `, ${pult.programmer.effekte.length} Effekte` : ""}` : "Programmer leer";
    if (feld("programmer-text").textContent !== progText) feld("programmer-text").textContent = progText;
    feld("programmer-text").classList.toggle("prog-an", progAnzahl > 0);
    wurzel.querySelector('[data-pulttaste="highlight"]').classList.toggle("an", pult.highlight);
    wurzel.querySelector('[data-pulttaste="blind"]').classList.toggle("an", pult.blind);
    wurzel.querySelector('[data-pulttaste="oops"]').disabled = !pult.oops;
  }

  // --- Feature-Leiste: Presets und Encoder für die Auswahl ---------------------------

  html("features", FEATURES.map(([id, text]) => `<button data-feature="${id}" class="${id === feature ? "an" : ""}">${text}</button>`).join(""));

  function erster() {
    return gewaehlt()[0];
  }

  function encoder(id, text, min, max, wert, schritt = 1, einheit = "") {
    return `<label class="enc">${text} <span class="wert" id="w-${id}">${wert == null ? "–" : wert + einheit}</span>
      <input type="range" id="e-${id}" min="${min}" max="${max}" step="${schritt}" value="${wert ?? (min < 0 ? 0 : max)}"></label>`;
  }

  function featureZeigen(neu = false) {
    if (!info || !pult) return;
    const g = erster();
    const prog = g ? pult.programmer.werte[g.id] ?? {} : {};
    const geraete = gewaehlt();
    const beweglich = geraete.some((x) => x.beweglich);
    let inhalt = "";
    let hinweis = geraete.length ? "" : "Erst Geräte oder eine Gruppe wählen";
    if (feature === "dimmer") {
      inhalt = `<div class="feature-zeile">
        ${[0, 25, 50, 75, 100].map((w) => `<button class="kachel mini" data-dimmer="${w}">${w === 100 ? "Voll" : w === 0 ? "Aus" : w + " %"}</button>`).join("")}
        ${encoder("hell", "Dimmer", 0, 100, prog.helligkeit == null ? null : Math.round(prog.helligkeit * 100), 1, " %")}</div>`;
    } else if (feature === "position") {
      if (geraete.length && !beweglich) hinweis = "Die gewählten Geräte bewegen sich nicht";
      const pan = g?.pan_grad ?? 540;
      const tilt = g?.tilt_grad ?? 270;
      inhalt = `<div class="feature-zeile">
        <canvas id="grundriss" width="300" height="150" title="Tippen: Köpfe zeigen dorthin (Kopfhöhe)"></canvas>
        <div class="feature-spalte"><div class="pool klein">${info.positionen.map((p, i) => kachel(i + 1, p, { position: p },
          prog.position === p ? "gewaehlt" : "")).join("")}</div>
        <div class="feature-zeile">${encoder("pan", "Pan", -pan / 2, pan / 2, prog.pan == null ? null : Math.round(prog.pan), 1, "°")}
        ${encoder("tilt", "Tilt", -tilt / 2, tilt / 2, prog.tilt == null ? null : Math.round(prog.tilt), 1, "°")}</div></div></div>`;
    } else if (feature === "farbe") {
      const farbe = typeof prog.farbe === "string" ? prog.farbe : null;
      const mix = farbe?.startsWith("#") ? [1, 3, 5].map((i) => parseInt(farbe.slice(i, i + 2), 16)) : [255, 255, 255];
      inhalt = `<div class="feature-zeile"><div class="pool farben">${info.farben.map((f, i) =>
        kachel(i + 1, farbName(f), { farbe: f }, `farbe ${farbe === f ? "gewaehlt" : ""}`, `background:${FARBEN[f] ?? "#888"}`)).join("")}</div>
        <div class="feature-spalte mischer"><span class="leise">Mischen</span>
          ${["R", "G", "B"].map((k, i) => encoder("mix-" + k, k, 0, 255, mix[i])).join("")}
          <span class="mischfarbe" id="mischfarbe" style="background:rgb(${mix.join(",")})"></span></div></div>`;
    } else if (feature === "gobo") {
      const gobos = [...new Set(geraete.flatMap((x) => x.gobos))]
        .sort((a, b) => (a === "Offen" ? -1 : b === "Offen" ? 1 : a.localeCompare(b, "de", { numeric: true })));
      if (geraete.length && !gobos.length) hinweis = "Die gewählten Geräte haben kein Goborad";
      inhalt = `<div class="feature-zeile"><div class="pool klein">${gobos.map((x, i) => kachel(i + 1, x, { gobo: x },
        prog.gobo === x ? "gewaehlt" : "")).join("")}</div>
        ${encoder("drehung", "Gobo-Drehung", -100, 100, prog.gobo_drehung == null ? null : Math.round(prog.gobo_drehung * 100), 1, " %")}</div>`;
    } else if (feature === "strahl") {
      inhalt = `<div class="feature-zeile">
        ${encoder("strobo", "Strobo (Blitze pro Sekunde, höchstens 3)", 0, 3, prog.strobo_hz ?? 0, 0.5)}
        <p class="leise">Die Strobo-Grenze aus der Sicherheit gilt immer. Strobo aus (Taste S) hat Vorrang.</p></div>`;
    } else if (feature === "effekt") {
      inhalt = `<div class="feature-zeile"><div class="pool klein">${Object.entries(info.effekte).map(([art, text], i) =>
        kachel(i + 1, text, { effekt: art }, pult.programmer.effekte.some((e) => e.art === art) ? "aktiv" : "",
          !beweglich && BEWEGUNG.includes(art) ? "opacity:.35" : "")).join("")}</div>
        <div class="feature-spalte">
          ${encoder("groesse", "Größe", 5, 100, 50, 1, " %")}${encoder("verteilung", "Versatz", 0, 100, 50, 1, " %")}
          <label class="enc">Beats pro Runde <select id="e-beats">${[1, 2, 4, 8, 16].map((b) => `<option ${b === 4 ? "selected" : ""}>${b}</option>`).join("")}</select></label>
          <label class="enc">Tempo <select id="e-tempo"><option value="musik">wie die Musik</option><option>60</option><option>90</option><option>120</option><option>140</option></select></label>
        </div>
        <div class="feature-spalte" id="laufende">${pult.programmer.effekte.map((e, i) =>
          `<div class="zeile laufend">${t(info.effekte[e.art])} · ${t(e.ziel.gruppe ?? e.ziel.geraete.length + " Geräte")}
           <button class="klein" data-effekt-weg="${i}">Stopp</button></div>`).join("")}</div></div>`;
    }
    const sig = JSON.stringify([feature, pult.auswahl, prog, pult.programmer.effekte.map((e) => e.art)]);
    if (!neu && feld("feature").dataset.sig === sig) return;
    if (feld("feature").contains(document.activeElement) && document.activeElement.type === "range") return;
    feld("feature").dataset.sig = sig;
    feld("feature").innerHTML = inhalt;
    feld("feature-hinweis").textContent = hinweis;
    if (feature === "position") grundrissZeichnen();
  }

  async function setzen(werte) {
    if (!pult.auswahl.length) return meldung("Zuerst Geräte oder eine Gruppe wählen.");
    pultAnnehmen(await senden("/programmer/werte", { werte }));
  }

  // Grundriss von oben, Publikum unten. Tippen setzt die Position auf Kopfhöhe.
  function masstab() {
    const m = info.aufbau.buehne;
    return Math.min(280 / m.breite_m, 110 / m.tiefe_m);
  }
  const zuPixel = (x, y) => [150 + x * masstab(), 10 + (info.aufbau.buehne.tiefe_m - y) * masstab()];
  const ausPixel = (px, py) => ({ x: (px - 150) / masstab(), y: info.aufbau.buehne.tiefe_m - (py - 10) / masstab() });
  function grundrissZeichnen() {
    const leinwand = feld("grundriss");
    if (!leinwand || !info.aufbau) return;
    const z = leinwand.getContext("2d");
    const m = info.aufbau.buehne;
    z.fillStyle = "#070708"; z.fillRect(0, 0, leinwand.width, leinwand.height);
    const [px, py] = zuPixel(-m.breite_m / 2, m.tiefe_m);
    const [qx, qy] = zuPixel(m.breite_m / 2, 0);
    z.fillStyle = "#2a2c30"; z.fillRect(px, py, qx - px, qy - py);
    z.fillStyle = "rgba(200,55,45,.25)"; z.fillRect(0, qy + 6, leinwand.width, leinwand.height - qy - 6);
    z.fillStyle = "#8d9196"; z.font = "10px sans-serif"; z.fillText("PUBLIKUM", 6, leinwand.height - 4);
    for (const [name, p] of Object.entries(info.aufbau.positionen)) {
      const [x, y] = zuPixel(p.x, p.y);
      z.fillStyle = "#f2c200"; z.beginPath(); z.arc(x, y, 3, 0, 7); z.fill();
      z.fillStyle = "#e3e3e3"; z.fillText(name, x + 5, y - 4);
    }
  }

  // --- Cue-Liste (Sequence Sheet) ------------------------------------------------------

  async function sheetZeigen() {
    if (!pult) return;
    const haupt = pult.haupt_info;
    const name = sheetSequenz ?? haupt?.sequenz;
    const index = !sheetSequenz || sheetSequenz === haupt?.sequenz ? haupt?.index ?? -1 : -1;
    const stand = JSON.stringify([name, index, sheetBearbeiten, pult.haupt_cues]);
    if (stand === sheetStand) return;
    sheetStand = stand;
    if (!name) {
      sheetDaten = null;
      feld("sheet-titel").textContent = "Cue-Liste";
      feld("sheet").innerHTML = `<p class="leise">Noch nichts gewählt. Fader antippen oder eine Sequenz im Pool.
        Neu programmieren: Gruppe wählen, Farbe und Dimmer setzen, dann <b>Store</b> und einen leeren Fader antippen.</p>`;
      return;
    }
    try { sheetDaten = await api("/sequenzen/" + encodeURIComponent(name)); } catch { sheetDaten = null; return; }
    const platz = !sheetSequenz && haupt ? (haupt.song ? "Song" : `Fader ${haupt.nummer}`) : "Pool";
    feld("sheet-titel").textContent = `${platz}: ${name}`;
    feld("sheet-hinweis").innerHTML = sheetBearbeiten
      ? `Bearbeiten · <button class="klein" data-sheet-fertig>Fertig</button>`
      : `Klick = Goto · <button class="klein" data-sheet-bearbeiten>Bearbeiten</button>`;
    const song = Boolean(sheetDaten.zeitcode);
    feld("sheet").innerHTML = `<table class="cueliste sheet-tabelle">
      <tr><th>#</th><th>Cue</th><th>Zeit</th><th>Folgen</th>${sheetBearbeiten ? "<th></th>" : ""}</tr>
      ${sheetDaten.cues.map((c, i) => `<tr data-cue="${i}" class="${i === index ? "aktiv" : ""} ${i === index + 1 ? "naechster" : ""}">
        <td>${i + 1}</td>
        <td>${sheetBearbeiten ? `<input data-cue-name="${i + 1}" value="${t(c.name)}">` : t(c.name)}</td>
        <td>${sheetBearbeiten ? `<input type="number" min="0" step="0.5" data-cue-zeit="${i + 1}" value="${c.zeit_s ?? 0}">` : `${c.zeit_s ?? 0} s`}</td>
        <td>${sheetBearbeiten ? `<input type="number" min="0" step="0.1" data-cue-folgen="${i + 1}" value="${c.folgen_s ?? ""}" placeholder="Go">` : c.folgen_s == null ? "Go" : `nach ${c.folgen_s} s`}</td>
        ${sheetBearbeiten ? `<td class="zeile">${song ? "" : `<button class="klein" data-cue-hoch="${i + 1}">↑</button><button class="klein" data-cue-runter="${i + 1}">↓</button>`}
          <button class="klein" data-cue-laden="${i + 1}" title="In den Programmer holen">Laden</button>
          ${song ? "" : `<button class="klein gefahr" data-cue-weg="${i + 1}">×</button>`}</td>` : ""}
      </tr>`).join("")}</table>`;
  }

  async function cueFeld(element) {
    const name = sheetDaten?.name;
    if (!name) return;
    const d = element.dataset;
    const nummer = Number(d.cueName ?? d.cueZeit ?? d.cueFolgen);
    const felder = d.cueName ? { name: element.value } : d.cueZeit ? { zeit_s: Number(element.value) } : { folgen_s: element.value };
    await senden(`/sequenzen/${encodeURIComponent(name)}/cue/${nummer}/aendern`, felder);
    sheetStand = "";
  }

  // --- Klicks -------------------------------------------------------------------

  wurzel.addEventListener("click", async (ereignis) => {
    const k = ereignis.target.closest("button");
    if (!k || !wurzel.contains(k)) return;
    const d = k.dataset;
    try {
      if (d.pulttaste) return pultTaste(d.pulttaste);
      if (d.feature) {
        feature = d.feature;
        wurzel.querySelectorAll("[data-feature]").forEach((b) => b.classList.toggle("an", b.dataset.feature === feature));
        return featureZeigen(true);
      }
      // Assign: erst die Quelle
      if (modus === "assign" && (d.sequenz || d.gruppe || d.tempo)) {
        assignQuelle = d.sequenz ? { sequenz: d.sequenz } : d.gruppe ? { gruppe: d.gruppe } : { art: "tempo" };
        feld("modus-text").textContent = `Assign ${d.sequenz ?? d.gruppe ?? "Tempo"} → jetzt den Fader antippen.  (Esc = abbrechen)`;
        zuletzt.delete("sequenzen"); zuletzt.delete("gruppen");
        return poolsZeigen();
      }
      if (modus === "store" && d.sequenz) {
        modusSetzen(null);
        const sequenz = await senden(`/sequenzen/${encodeURIComponent(d.sequenz)}/speichern`, { cue_name: "", zeit_s: 2 });
        meldungLeise(`Gespeichert in ${d.sequenz}, Cue ${sequenz.cues.length}`);
        poolLaden();
        sheetStand = "";
        return;
      }
      if (modus === "delete" && d.sequenz) {
        modusSetzen(null);
        if (!confirm(`Sequenz „${d.sequenz}“ ganz löschen? (Oops holt sie zurück.)`)) return;
        await api(`/sequenzen/${encodeURIComponent(d.sequenz)}`, { method: "DELETE" });
        if (sheetSequenz === d.sequenz) sheetSequenz = null;
        poolLaden();
        sheetStand = "";
        return;
      }
      if (d.geraet) return pultAnnehmen(await senden("/auswahl", { geraete: [d.geraet], art: "umschalten" }));
      if (d.gruppe) return pultAnnehmen(await senden("/auswahl", { gruppe: d.gruppe, art: "umschalten" }));
      if (d.alle) {
        const alle = info.geraete.every((g) => pult.auswahl.includes(g.id));
        return pultAnnehmen(await senden("/auswahl", { geraete: alle ? [] : info.geraete.map((g) => g.id), art: "setzen" }));
      }
      if (d.sequenz) {
        sheetSequenz = sheetSequenz === d.sequenz ? null : d.sequenz;
        sheetBearbeiten = false;
        sheetStand = "";
        zuletzt.delete("sequenzen");
        poolsZeigen();
        return sheetZeigen();
      }
      if (d.tempo) return;
      if (d.dimmer !== undefined) return setzen({ helligkeit: Number(d.dimmer) / 100 });
      if (d.farbe) return setzen({ farbe: d.farbe });
      if (d.gobo) return setzen({ gobo: d.gobo });
      if (d.position) return setzen({ position: d.position });
      if (d.effekt) {
        if (!pult.auswahl.length) return meldung("Zuerst Geräte oder eine Gruppe wählen.");
        const tempo = feld("e-tempo")?.value ?? "musik";
        const effekt = {
          art: d.effekt, groesse: Number(feld("e-groesse")?.value ?? 50) / 100,
          beats: Number(feld("e-beats")?.value ?? 4), verteilung: Number(feld("e-verteilung")?.value ?? 50) / 100,
          tempo: tempo === "musik" ? "musik" : Number(tempo),
        };
        if (d.effekt === "farbwechsel") effekt.farben = ["rot", "blau", "gruen", "lila"];
        return pultAnnehmen(await senden("/programmer/effekt", effekt));
      }
      if (d.effektWeg !== undefined) return pultAnnehmen(await api("/programmer/effekt/" + d.effektWeg, { method: "DELETE" }));
      if (d.sheetBearbeiten !== undefined) { sheetBearbeiten = true; sheetStand = ""; return sheetZeigen(); }
      if (d.sheetFertig !== undefined) { sheetBearbeiten = false; sheetStand = ""; return sheetZeigen(); }
      const sequenzName = sheetDaten?.name;
      if (sequenzName && (d.cueHoch || d.cueRunter)) {
        await senden(`/sequenzen/${encodeURIComponent(sequenzName)}/cue/${d.cueHoch ?? d.cueRunter}/verschieben`, { richtung: d.cueHoch ? -1 : 1 });
        sheetStand = "";
        return sheetZeigen();
      }
      if (sequenzName && d.cueWeg) {
        await api(`/sequenzen/${encodeURIComponent(sequenzName)}/cue/${d.cueWeg}`, { method: "DELETE" });
        sheetStand = "";
        poolLaden();
        return sheetZeigen();
      }
      if (sequenzName && d.cueLaden) {
        pultAnnehmen(await senden(`/sequenzen/${encodeURIComponent(sequenzName)}/cue/${d.cueLaden}/laden`));
        return meldungLeise(`Cue ${d.cueLaden} ist im Programmer. Ändern, dann Store oder Update.`);
      }
    } catch { /* Meldung kam schon */ }
  });

  // Zeile in der Cue-Liste: Goto (oder Delete, wenn die Taste wartet)
  feld("sheet").addEventListener("click", async (ereignis) => {
    const zeile = ereignis.target.closest("tr[data-cue]");
    if (!zeile || ereignis.target.closest("input, button") || !sheetDaten) return;
    const index = Number(zeile.dataset.cue);
    try {
      if (modus === "delete") {
        modusSetzen(null);
        await api(`/sequenzen/${encodeURIComponent(sheetDaten.name)}/cue/${index + 1}`, { method: "DELETE" });
        sheetStand = "";
        return sheetZeigen();
      }
      if (sheetBearbeiten) return;
      const haupt = pult.haupt_info;
      if (!sheetSequenz || sheetSequenz === haupt?.sequenz) {
        pultAnnehmen(await senden(`/executor/${haupt.nummer}/goto`, { index }));
      } else {
        meldung("Diese Sequenz liegt auf keinem gewählten Fader. Erst mit Assign auf einen Fader legen.");
      }
    } catch { /* Meldung kam schon */ }
  });
  feld("sheet").addEventListener("change", (ereignis) => {
    if (ereignis.target.matches("[data-cue-name], [data-cue-zeit], [data-cue-folgen]")) cueFeld(ereignis.target).catch(() => {});
  });

  // Encoder: beim Ziehen nur die Zahl, beim Loslassen setzen
  feld("feature").addEventListener("input", (ereignis) => {
    const element = ereignis.target;
    if (!element.id?.startsWith("e-")) return;
    const id = element.id.slice(2);
    const anzeige = feld("w-" + id);
    const einheit = { hell: " %", pan: "°", tilt: "°", drehung: " %", groesse: " %", verteilung: " %" }[id] ?? "";
    if (anzeige) anzeige.textContent = element.value + einheit;
    if (id.startsWith("mix-")) {
      const [r, g, b] = ["R", "G", "B"].map((k) => Number(feld("e-mix-" + k).value));
      feld("mischfarbe").style.background = `rgb(${r},${g},${b})`;
    }
  });
  feld("feature").addEventListener("change", (ereignis) => {
    const element = ereignis.target;
    const id = element.id?.slice(2);
    if (!id) return;
    const wert = Number(element.value);
    const werte = {
      hell: { helligkeit: wert / 100 }, drehung: { gobo_drehung: wert / 100 }, strobo: { strobo_hz: wert },
      pan: { pan: wert, tilt: Number(feld("e-tilt")?.value ?? 0) }, tilt: { tilt: wert, pan: Number(feld("e-pan")?.value ?? 0) },
    }[id];
    if (werte) return setzen(werte).catch(() => {});
    if (id.startsWith("mix-")) {
      const farbe = "#" + ["R", "G", "B"].map((k) => hex(Number(feld("e-mix-" + k).value))).join("");
      setzen({ farbe }).catch(() => {});
    }
  });
  feld("feature").addEventListener("click", (ereignis) => {
    if (ereignis.target.id !== "grundriss") return;
    const leinwand = ereignis.target;
    const rahmen = leinwand.getBoundingClientRect();
    const p = ausPixel((ereignis.clientX - rahmen.left) * leinwand.width / rahmen.width,
      (ereignis.clientY - rahmen.top) * leinwand.height / rahmen.height);
    setzen({ punkt: { x: Math.round(p.x * 100) / 100, y: Math.round(p.y * 100) / 100, z: info.aufbau.buehne.hoehe_kante_m + 1.6 } })
      .catch(() => {});
  });

  // Tastatur: Esc bricht eine wartende Taste ab
  const tasten = (ereignis) => {
    if (ereignis.key === "Escape" && modus) { modusSetzen(null); ereignis.preventDefault(); }
  };
  document.addEventListener("keydown", tasten);

  // --- Live ---------------------------------------------------------------------

  function pultAnnehmen(neu) {
    if (!neu) return;
    pult = neu;
    poolsZeigen();
    featureZeigen();
    sheetZeigen();
  }

  // Platz genau so hoch wie das Fenster: nichts muss gescrollt werden
  function hoeheSetzen() {
    const oben = feld("platz").getBoundingClientRect().top;
    const fuss = document.querySelector(".befehlsleiste")?.offsetHeight ?? 54;
    feld("platz").style.height = `${Math.max(560, window.innerHeight - oben - fuss - 10)}px`;
  }
  window.addEventListener("resize", hoeheSetzen);
  const beobachter = new ResizeObserver(hoeheSetzen);
  const hinweise = document.getElementById("hinweise");
  if (hinweise) beobachter.observe(hinweise);
  hoeheSetzen();

  const chat = lichtChat(feld("chat-fenster"), {
    nachUebernehmen: () => { poolLaden(); sheetStand = ""; },
  });

  (async () => {
    const [daten, aufbau] = await Promise.all([api("/pult"), api("/buehne")]);
    if (beendet) return;
    info = { ...daten, aufbau };
    await poolLaden();
    pultAnnehmen(daten.status);
    buehne = new Buehne3D(feld("drei"), aufbau, { nah: true });
  })().catch(() => {});

  let letzteZeichnung = 0;
  const abmelden = abonnieren((neu) => {
    if (!neu) return;
    live = neu;
    buehne?.setzeWerte(neu.chat_vorschau?.geraete ?? neu.vorschau.geraete ?? neu.geraete);
    fader.zeigen(neu.pult);
    chat.live(neu);
    pult = neu.pult;
    // Pools und Listen nur ein paarmal pro Sekunde neu zeichnen: das reicht und schont den Rechner.
    if (performance.now() - letzteZeichnung > 250) {
      letzteZeichnung = performance.now();
      poolsZeigen();
      featureZeigen();
      sheetZeigen();
    }
  });

  return () => {
    beendet = true;
    abmelden();
    fader.abbauen();
    chat.abbauen();
    document.removeEventListener("keydown", tasten);
    window.removeEventListener("resize", hoeheSetzen);
    beobachter.disconnect();
    modusSetzen(null);
    buehne?.beenden();
  };
}
