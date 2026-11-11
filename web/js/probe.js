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
          <button data-editor="${t(p.name)}" class="${offen.has(p.name) ? "an" : ""}">Teile richtigstellen</button>
          <button data-weg="${t(p.name)}" class="gefahr">Löschen</button></p>
        ${offen.has(p.name) ? editor(p) : ""}
        <p class="leise">Die Show liegt als Sequenz „${t(p.name)}“ im Pult. Dort kannst du jeden Cue ändern.
          Live: auf der Seite „Show“ einmal Start drücken, wenn die Band anfängt. Der Song läuft dann von selbst durch.</p>
      </div>`).join("") || `<p class="leise">Noch keine Songs aufgenommen.</p>`;
  }

  // Teile von Hand richtigstellen: Name, Stärke, Grenzen auf Takt-Einsen, deine D-Marken als Grenzen
  function editor(p) {
    const n = t(p.name);
    return `<div class="teile-editor">
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

  feld("songs").addEventListener("change", (ereignis) => {
    const d = ereignis.target.dataset;
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
        const { analyse } = await senden("/proben/stopp");
        meldung(`Fertig: ${analyse.teile.length} Songteile erkannt, ${analyse.tempo_bpm} BPM.`, "ok");
        feld("name").value = "";
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
