// Probe: Songs aufnehmen oder als Datei laden, daraus baut das Programm eine Lichtshow.
import { api, senden, t, meldung } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";

const setzeText = (element, text) => { if (element.textContent !== text) element.textContent = text; };
const NAMEN = ["Intro", "Strophe", "Überleitung", "Refrain", "Bridge", "Solo", "Zwischenteil", "Aufbau", "Drop", "Finale", "Schluss"];
const KLASSEN = [["ruhig", "ruhig"], ["mittel", "mittel"], ["stark", "stark"], ["hoehepunkt", "Höhepunkt"]];
const genau = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
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
    <div class="kasten" id="laeuft-kasten" hidden><h2>Probe ansehen läuft</h2>
      <p class="zeile"><span id="laeuft"></span> <button id="ansehen-stopp" class="gefahr">Stopp</button></p>
      <p class="leise">Stopp beendet das Licht der Probe und öffnet wieder deine eigentliche Tonquelle (zum Beispiel das X32).</p></div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  let buehne = null;
  let beendet = false;
  let nimmtAuf = false;
  const offen = new Set();          // bei diesen Songs ist der Teile-Editor offen
  const geaendert = new Set();      // hier wurde etwas richtiggestellt, die Show ist noch die alte

  // --- Zeitleiste mit Wellenform: Grenzen ziehen, Akzente aus/an/verschieben/neu --------------------
  const wellen = new Map();          // Name -> {dauer_s, punkte}
  const probenDaten = new Map();     // Name -> Probe (Teile, Akzente)
  const KLASSE_FARBE = { ruhig: "63,127,192", mittel: "141,145,150", stark: "201,162,39", hoehepunkt: "200,55,45" };
  let zug = null;

  async function welleHolen(name) {
    if (!wellen.has(name)) wellen.set(name, await api(`/proben/${encodeURIComponent(name)}/welle`));
    return wellen.get(name);
  }

  function welleZeichnen(leinwand, p, welle) {
    const z = leinwand.getContext("2d"), B = leinwand.width, H = leinwand.height, dauer = welle.dauer_s || 1;
    const x = (zeit) => (zeit / dauer) * B;
    z.fillStyle = "#0d0e10"; z.fillRect(0, 0, B, H);
    z.font = "12px sans-serif"; z.textBaseline = "top";
    for (const teil of p.teile) {
      z.fillStyle = `rgba(${KLASSE_FARBE[teil.klasse] ?? KLASSE_FARBE.mittel},.22)`;
      z.fillRect(x(teil.start), 0, x(teil.ende) - x(teil.start), H);
      z.fillStyle = "#e3e3e3"; z.fillText(`${teil.name} ${teil.gruppe ?? ""}`.trim(), x(teil.start) + 4, 4);
    }
    z.fillStyle = "#8d9196";
    const mitte = H * 0.5, hoehe = H * 0.32;
    welle.punkte.forEach((w, i) => {
      const px = (i / welle.punkte.length) * B;
      z.fillRect(px, mitte - w * hoehe, Math.max(1, B / welle.punkte.length), Math.max(1, 2 * w * hoehe));
    });
    p.teile.slice(1).forEach((teil, i) => {
      const gezogen = zug?.art === "grenze" && zug.index === i + 1 && zug.bewegt;
      const px = x(gezogen ? zug.zeit : teil.start);
      z.fillStyle = gezogen ? "#f2c200" : "#e3e3e3"; z.fillRect(px - 1, 0, 2, H);
      z.fillRect(px - 5, 18, 10, 10);
    });
    z.fillStyle = "#f2c200";
    for (const m of p.markiert_s ?? []) z.fillRect(x(m) - 1, 0, 3, 8);
    for (const a of p.akzente ?? []) {
      const gezogen = zug?.art === "akzent" && Math.abs(zug.alt - a.zeit) < 0.01 && zug.bewegt;
      const px = x(gezogen ? zug.zeit : a.zeit), py = H - 14;
      z.fillStyle = a.aus ? "#4a4d52" : gezogen ? "#f2c200" : "#ffffff";
      z.beginPath();
      if (a.art === "akzent") { z.moveTo(px, py - 8); z.lineTo(px + 7, py); z.lineTo(px, py + 8); z.lineTo(px - 7, py); }
      else { z.moveTo(px, py - 8); z.lineTo(px + 7, py + 6); z.lineTo(px - 7, py + 6); }
      z.closePath(); z.fill();
      if (a.aus) { z.strokeStyle = "#ff8a80"; z.beginPath(); z.moveTo(px - 6, py - 6); z.lineTo(px + 6, py + 6); z.stroke(); }
    }
  }

  async function wellenZeigen() {
    for (const leinwand of feld("songs").querySelectorAll("canvas[data-welle]")) {
      const name = leinwand.dataset.welle;
      try { welleZeichnen(leinwand, probenDaten.get(name), await welleHolen(name)); } catch { /* keine Aufnahme */ }
    }
  }

  function zeitAus(leinwand, e) {
    const rand = leinwand.getBoundingClientRect(), welle = wellen.get(leinwand.dataset.welle);
    const px = (e.clientX - rand.left) * leinwand.width / rand.width, py = (e.clientY - rand.top) * leinwand.height / rand.height;
    return { px, py, zeit: Math.max(0, Math.min(welle.dauer_s, (px / leinwand.width) * welle.dauer_s)), proPixel: welle.dauer_s / leinwand.width };
  }

  feld("songs").addEventListener("pointerdown", (e) => {
    const leinwand = e.target.closest("canvas[data-welle]");
    if (!leinwand || !wellen.has(leinwand.dataset.welle)) return;
    const p = probenDaten.get(leinwand.dataset.welle);
    const { px, py, zeit, proPixel } = zeitAus(leinwand, e);
    const nah = 7 * proPixel;
    const grenze = p.teile.findIndex((t, i) => i > 0 && Math.abs(t.start - zeit) <= nah);
    const akzent = py > leinwand.height - 34 ? (p.akzente ?? []).find((a) => Math.abs(a.zeit - zeit) <= nah) : null;
    if (akzent) zug = { art: "akzent", alt: akzent.zeit, aus: akzent.aus, zeit, start: px, bewegt: false, leinwand, p };
    else if (grenze > 0) zug = { art: "grenze", index: grenze, zeit, start: px, bewegt: false, leinwand, p };
    else return;
    leinwand.setPointerCapture?.(e.pointerId);
  });
  feld("songs").addEventListener("pointermove", (e) => {
    const leinwand = e.target.closest("canvas[data-welle]");
    if (!leinwand || !wellen.has(leinwand.dataset.welle)) return;
    const { px, zeit } = zeitAus(leinwand, e);
    const info = feld("songs").querySelector(`[data-welle-info="${CSS.escape(leinwand.dataset.welle)}"]`);
    if (info && !zug) info.dataset.text ??= info.textContent;
    if (zug && zug.leinwand === leinwand) {
      zug.zeit = zeit;
      zug.bewegt ||= Math.abs(px - zug.start) > 4;
      welleZeichnen(leinwand, zug.p, wellen.get(leinwand.dataset.welle));
    }
    if (info) info.textContent = `${genau(zeit)}${zug?.bewegt ? " · loslassen zum Übernehmen" : ""}`;
  });
  feld("songs").addEventListener("pointerleave", (e) => {
    const info = e.target.closest?.("[data-welle-info]");
    if (info?.dataset.text) info.textContent = info.dataset.text;
  }, true);
  async function zugEnde() {
    if (!zug) return;
    const z = zug;
    zug = null;
    const name = z.leinwand.dataset.welle;
    try {
      if (z.art === "grenze" && z.bewegt) {
        await senden(`/proben/${encodeURIComponent(name)}/teile`, { aktion: "grenze", index: z.index, wert: z.zeit });
      } else if (z.art === "akzent") {
        await senden(`/proben/${encodeURIComponent(name)}/akzente`, z.bewegt
          ? { aktion: "verschieben", zeit: z.alt, wert: z.zeit } : { aktion: z.aus ? "an" : "aus", zeit: z.alt });
      } else { return; }
      geaendert.add(name);
    } catch { /* Meldung kam schon */ }
    songsZeigen();
  }
  // Loslassen: direkt an der Zeitleiste (mit Pointer-Capture kommt es dort an), nur einmal pro Zug
  feld("songs").addEventListener("pointerup", (e) => { if (zug && e.target.closest("canvas[data-welle]")) zugEnde(); });
  feld("songs").addEventListener("pointercancel", () => { zug = null; wellenZeigen(); });
  feld("songs").addEventListener("lostpointercapture", (e) => { if (zug && e.target.closest?.("canvas[data-welle]")) zugEnde(); }, true);
  feld("songs").addEventListener("dblclick", async (e) => {
    const leinwand = e.target.closest("canvas[data-welle]");
    if (!leinwand || !wellen.has(leinwand.dataset.welle)) return;
    const { py, zeit } = zeitAus(leinwand, e);
    if (py < leinwand.height * 0.6) return;
    const name = leinwand.dataset.welle;
    try {
      await senden(`/proben/${encodeURIComponent(name)}/akzente`, { aktion: "neu", zeit, art: "schlag" });
      geaendert.add(name);
    } catch { return; }
    songsZeigen();
  });

  async function songsZeigen() {
    const { proben } = await api("/proben");
    proben.forEach((p) => probenDaten.set(p.name, p));
    feld("songs").innerHTML = proben.map((p) => `
      <div class="kasten">
        <h2>${t(p.name)} <span class="leise">${p.tempo_bpm} BPM · ${minuten(p.dauer_s)}</span></h2>
        <div class="zeitleiste">${p.teile.map((teil) => `<div class="${teil.klasse}" style="flex:${teil.ende - teil.start}"
          title="${t(teil.name)} ${teil.gruppe}: ${minuten(teil.start)} bis ${minuten(teil.ende)}">${t(teil.name)} ${teil.gruppe}</div>`).join("")}</div>
        ${(p.version ?? 1) < 2 ? `<div class="meldung gelb">Neue Song-Erkennung: „Show neu bauen“ drücken, dann wird diese Aufnahme neu analysiert (Tempo, Takte, Teile).</div>` : ""}
        ${(p.drops_s?.length || p.markiert_s?.length) ? `<p class="leise">Drops erkannt: ${(p.drops_s ?? []).map(minuten).join(", ") || "keiner"}
          ${p.markiert_s?.length ? ` · von dir markiert: ${p.markiert_s.map(minuten).join(", ")}` : ""}</p>` : ""}
        ${weitereZeigen(p)}
        <p class="zeile">
          <button data-ansehen="${t(p.name)}" class="haupt">Probe ansehen</button>
          <button data-neu="${t(p.name)}">Show neu bauen</button>
          <button data-editor="${t(p.name)}" class="${offen.has(p.name) ? "an" : ""}">Teile richtigstellen</button>
          <button data-weg="${t(p.name)}" class="gefahr">Löschen</button></p>
        ${offen.has(p.name) ? editor(p) : ""}
        <p class="leise">Die Show liegt als Sequenz „${t(p.name)}“ im Pult. Dort kannst du jeden Cue ändern.
          Live: auf der Seite „Show“ einmal Start drücken, wenn die Band anfängt. Der Song läuft dann von selbst durch.</p>
      </div>`).join("") || `<p class="leise">Noch keine Songs aufgenommen.</p>`;
    wellenZeigen();
  }

  // Weitere Aufnahmen (Konzert-Mitschnitte, weitere Proben): helfen der Song-Erkennung
  function weitereZeigen(p) {
    const n = t(p.name);
    const liste = (p.weitere ?? []).map((w) => `<span class="chip weitere-chip ${w.zugeordnet ? "an" : ""}"
        title="${w.zugeordnet ? `zugeordnet, ${Math.round(w.sicher * 100)} % sicher mitgehört` : "wird zugeordnet, sobald gerade kein Song läuft"}">
        ${t(w.quelle)} ${t(w.zeit)}${w.zugeordnet ? "" : " · wird zugeordnet …"}
        <button class="klein" data-weitere-weg="${n}" data-datei="${t(w.datei)}" title="Diese Aufnahme löschen">×</button></span>`).join(" ");
    return `<div class="weitere zeile"><span class="leise">Weitere Aufnahmen (helfen der Song-Erkennung):</span>
      ${liste || `<span class="leise">noch keine</span>`}
      <button class="klein" data-weitere-auf="${n}" title="Den Song noch einmal aufnehmen, zum Beispiel in der Aula">● Weitere Aufnahme</button>
      <label class="klein datei-knopf" title="Zum Beispiel ein Handy-Mitschnitt vom Konzert">Aus Datei …
        <input type="file" accept="audio/*" data-weitere-datei="${n}" hidden></label></div>`;
  }

  // Teile von Hand richtigstellen: Name, Stärke, Grenzen auf Takt-Einsen, deine D-Marken als Grenzen
  function editor(p) {
    const n = t(p.name);
    return `<div class="teile-editor">
      <canvas class="welle" data-welle="${n}" width="1200" height="150"></canvas>
      <p class="leise welle-info" data-welle-info="${n}">Zeitleiste: Grenze zwischen zwei Teilen ziehen = verschieben (landet auf der Takt-Eins).
        Akzent unten antippen = aus/an, ziehen = verschieben. Doppelklick unten = neuer Schlag (kurz weiß).
        ◆ Blitz-Akzent · ▲ Schlag · gelb oben = deine D-Marken.</p>
      <p class="leise">Hör dir die Stellen an („▶ ab hier“) und stell die Teile richtig. Grenzen liegen immer auf einer Takt-Eins.
        Danach <b>Show neu bauen</b>, dann gilt es für Song-Start und Probe ansehen.${p.von_hand ? " · <b>Von Hand richtiggestellt.</b>" : ""}</p>
      ${geaendert.has(p.name) ? `<div class="meldung gelb zeile">Geändert. Damit es für den Song gilt:
        <button data-neu="${n}" class="haupt">Show neu bauen</button></div>` : ""}
      ${p.markiert_s?.length ? `<p><button data-teile="${n}" data-aktion="marken" data-index="0">Deine ${p.markiert_s.length} D-Marken als Teilgrenzen nehmen</button></p>` : ""}
      <div class="tabelle-huelle"><table>
        <tr><th>#</th><th>Start</th><th>Takte</th><th>Name</th><th>Stärke</th><th></th></tr>
        ${p.teile.map((teil, i) => `<tr>
          <td>${i + 1}</td><td style="white-space:nowrap">${genau(teil.start)}</td><td>${teil.takte ?? ""}</td>
          <td><select data-teil-name="${n}" data-index="${i}">${[...new Set([teil.name, ...NAMEN])].map((x) =>
            `<option ${x === teil.name ? "selected" : ""}>${t(x)}</option>`).join("")}</select> <span class="leise">${t(teil.gruppe ?? "")}</span></td>
          <td><select data-teil-klasse="${n}" data-index="${i}">${KLASSEN.map(([k, text]) =>
            `<option value="${k}" ${k === teil.klasse ? "selected" : ""}>${text}</option>`).join("")}</select></td>
          <td class="zeile" style="flex-wrap:nowrap">
            <button class="klein" data-hoeren="${n}" data-ab="${teil.start}" title="Aufnahme ab diesem Teil abspielen, das Licht läuft mit">▶ ab hier</button>
            ${i > 0 ? `<button class="klein" data-teile="${n}" data-aktion="verschieben" data-index="${i}" data-wert="-1" title="Anfang einen Takt früher">◀ Takt</button>
              <button class="klein" data-teile="${n}" data-aktion="verschieben" data-index="${i}" data-wert="1" title="Anfang einen Takt später">Takt ▶</button>` : ""}
            <button class="klein" data-teile="${n}" data-aktion="teilen" data-index="${i}" title="In der Mitte teilen">Teilen</button>
            ${i + 1 < p.teile.length ? `<button class="klein" data-teile="${n}" data-aktion="verbinden" data-index="${i}" title="Mit dem nächsten Teil zusammenlegen">+ nächster</button>` : ""}
          </td></tr>`).join("")}
      </table></div></div>`;
  }

  async function teileAendern(name, aktion, index, wert) {
    await senden(`/proben/${encodeURIComponent(name)}/teile`, { aktion, index: Number(index), wert });
    geaendert.add(name);
    songsZeigen();
  }

  feld("songs").addEventListener("change", async (ereignis) => {
    const d = ereignis.target.dataset;
    if (d.weitereDatei) {
      const datei = ereignis.target.files[0];
      if (!datei) return;
      meldung("Lade die Aufnahme …", "ok");
      try {
        await api(`/proben/${encodeURIComponent(d.weitereDatei)}/weitere?datei=${encodeURIComponent(datei.name)}`, { method: "POST", body: datei });
        meldung("Gespeichert. Sie wird zugeordnet, sobald gerade kein Song läuft.", "ok");
      } finally { ereignis.target.value = ""; songsZeigen(); }
      return;
    }
    if (d.teilName) teileAendern(d.teilName, "name", d.index, ereignis.target.value).catch(() => {});
    if (d.teilKlasse) teileAendern(d.teilKlasse, "klasse", d.index, ereignis.target.value).catch(() => {});
  });

  feld("aufnahme").onclick = async () => {
    if (!nimmtAuf) {
      await senden("/proben/aufnahme", { name: feld("name").value.trim() });
    } else {
      feld("aufnahme").disabled = true;
      feld("aufnahme").textContent = "Analysiere …";
      try {
        const antwort = await senden("/proben/stopp");
        if (antwort.weitere) {
          meldung("Weitere Aufnahme gespeichert. Sie wird zugeordnet, sobald gerade kein Song läuft.", "ok");
        } else {
          meldung(`Fertig: ${antwort.analyse.teile.length} Songteile erkannt, ${antwort.analyse.tempo_bpm} BPM.`, "ok");
          feld("name").value = "";
        }
      } finally { feld("aufnahme").disabled = false; }
      songsZeigen();
    }
  };

  feld("datei").onchange = async () => {
    const datei = feld("datei").files[0];
    if (!datei) return;
    const name = feld("name").value.trim() || datei.name.replace(/\.[^.]+$/, "");
    meldung("Analysiere „" + name + "“ …", "ok");
    await api(`/proben/datei?name=${encodeURIComponent(name)}&datei=${encodeURIComponent(datei.name)}`, { method: "POST", body: datei });
    feld("datei").value = "";
    songsZeigen();
  };

  feld("ansehen-stopp").onclick = () => senden("/proben/ansehen/stopp");

  wurzel.addEventListener("click", async (ereignis) => {
    const d = ereignis.target.dataset;
    if (d.ansehen) await senden(`/proben/${encodeURIComponent(d.ansehen)}/abspielen`);
    if (d.hoeren) await senden(`/proben/${encodeURIComponent(d.hoeren)}/abspielen`, { ab_s: Number(d.ab) });
    if (d.editor) { offen.has(d.editor) ? offen.delete(d.editor) : offen.add(d.editor); songsZeigen(); }
    if (d.teile) await teileAendern(d.teile, d.aktion, d.index, d.wert !== undefined ? Number(d.wert) : undefined);
    if (d.neu) {
      meldung("Baue die Show neu …", "ok");
      await senden(`/proben/${encodeURIComponent(d.neu)}/neu`);
      geaendert.delete(d.neu);
      meldung("Show neu gebaut.", "ok");
      songsZeigen();
    }
    if (d.weitereAuf) {
      await senden("/proben/aufnahme", { name: d.weitereAuf, weitere: true });
      meldung(`Nimmt „${d.weitereAuf}“ noch einmal auf. Zum Beenden oben „Aufnahme beenden“ drücken.`, "ok");
    }
    if (d.weitereWeg && confirm("Diese weitere Aufnahme löschen?")) {
      await api(`/proben/${encodeURIComponent(d.weitereWeg)}/weitere/${encodeURIComponent(d.datei)}`, { method: "DELETE" });
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
    const platz = live.pult.song_platz;
    const ansehen = live.audio.quelle?.startsWith("Probe:") && platz.sequenz && !platz.song;
    feld("laeuft-kasten").hidden = !ansehen;
    if (ansehen) setzeText(feld("laeuft"), `${platz.sequenz}: Cue ${platz.index + 1}/${platz.anzahl} ${platz.cue ?? ""}`);
    nimmtAuf = Boolean(live.aufnahme.name);
    // Nur ändern, wenn sich etwas ändert: Wird ein Knopf beim Drücken neu beschriftet,
    // verwirft der Browser den Klick. Das war der Grund, warum "Aufnahme starten" nicht ging.
    const text = nimmtAuf ? "Aufnahme beenden und auswerten" : "Aufnahme starten";
    if (!feld("aufnahme").disabled && feld("aufnahme").textContent !== text) {
      feld("aufnahme").textContent = text;
      feld("aufnahme").classList.toggle("aufnahme-an", nimmtAuf);
    }
    setzeText(feld("zeit"), nimmtAuf ? `● ${live.aufnahme.name}${live.aufnahme.weitere ? " (weitere Aufnahme)" : ""} ${minuten(live.aufnahme.sekunden)}` +
      (live.aufnahme.markierungen ? ` · ${live.aufnahme.markierungen}× Drop markiert` : "") : "");
    setzeText(feld("quelle"), live.audio.quelle === "aus"
      ? "Keine Tonquelle: auf der Live-Seite den Eingang (zum Beispiel X32 oder Mikrofon) wählen."
      : `Tonquelle: ${live.audio.quelle}`);
  });

  songsZeigen();
  api("/buehne").then((aufbau) => { if (!beendet) buehne = new Buehne3D(feld("drei"), aufbau, { nah: true }); });
  return () => { beendet = true; abmelden(); buehne?.beenden(); };
}
