// Katalog durchsuchen und eigene Gerätetypen anlegen oder kopieren.
import { api, senden, t, meldung } from "./api.js";

const TYPEN = ["dimmer", "rot", "gruen", "blau", "weiss", "warmweiss", "kaltweiss", "amber", "uv", "cyan", "magenta", "gelb",
  "pan", "tilt", "pan_fein", "tilt_fein", "fein", "strobo", "farbrad", "gobo", "gobo_rotation", "prisma",
  "fokus", "zoom", "iris", "tempo", "nebel", "luefter", "makro", "sonstiges"];

const LEER = {
  hersteller: "", name: "", physik: { gewicht_kg: null, abstrahlwinkel_grad: null },
  kanaele: { Dimmer: { typ: "dimmer", standard: 0 } }, modi: [{ name: "1-Kanal", kanaele: ["Dimmer"] }],
};

export function katalogSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div class="kasten">
        <h2>Katalog <span class="leise" id="gesamt"></span></h2>
        <label>Suchen <input id="suche"></label>
        <div class="liste" id="treffer" style="max-height:60vh"></div>
        <p class="zeile"><button id="neu">Neuen Gerätetyp anlegen</button>
        <button id="importieren">.qxf / .gdtf importieren</button></p>
        <input id="importdatei" type="file" accept=".qxf,.gdtf" hidden>
      </div>
      <div id="detail"></div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);

  async function suchen() {
    const { geraete, gesamt } = await api("/katalog?suche=" + encodeURIComponent(feld("suche").value));
    feld("gesamt").textContent = `${gesamt} Gerätetypen`;
    feld("treffer").innerHTML = "";
    for (const geraet of geraete) {
      const zeile = document.createElement("div");
      zeile.textContent = `${geraet.hersteller} ${geraet.name}`;
      zeile.onclick = () => anzeigen(geraet.id);
      feld("treffer").append(zeile);
    }
  }

  async function anzeigen(id) {
    const eintrag = await api("/katalog/" + id);
    const quelle = eintrag.quelle ?? {};
    feld("detail").innerHTML = `
      <div class="kasten">
        <h2>${t(eintrag.hersteller)} ${t(eintrag.name)}</h2>
        ${eintrag.platzhalter ? `<div class="meldung gelb">${t(eintrag._hinweis ?? "Platzhalter")}</div>` : ""}
        <p class="leise">Quelle: ${t(quelle.name ?? quelle.art)}${quelle.lizenz ? ` (${t(quelle.lizenz)}-Lizenz)` : ""} ·
          ${eintrag.handbuch_geprueft ? "mit Handbuch geprüft" : "noch nicht mit dem Handbuch geprüft"} ·
          Gewicht ${t(eintrag.physik?.gewicht_kg ?? "?")} kg · Abstrahlwinkel ${t(eintrag.physik?.abstrahlwinkel_grad ?? "?")}°</p>
        ${eintrag.modi.map((m) => `
          <h2>${t(m.name)}</h2>
          <div class="tabelle-huelle"><table><tr><th>Kanal</th><th>Name</th><th>Typ</th></tr>
          ${m.kanaele.map((k, i) => `<tr><td>${i + 1}</td><td>${t(k ?? "(leer)")}</td><td>${t(eintrag.kanaele[k]?.typ ?? "")}${eintrag.kanaele[k]?.grad ? ` ${eintrag.kanaele[k].grad}°` : ""}</td></tr>`).join("")}
          </table></div>`).join("")}
        <p><button id="kopieren" class="haupt">Kopieren und ändern</button></p>
      </div>`;
    feld("kopieren").onclick = () => editor({ ...structuredClone(eintrag), name: eintrag.name + " Kopie" });
  }

  function kanalZeile(name, kanal) {
    return `<tr>
      <td><input data-k="name" value="${t(name)}"></td>
      <td><select data-k="typ">${TYPEN.map((x) => `<option ${x === kanal.typ ? "selected" : ""}>${x}</option>`).join("")}</select></td>
      <td><input data-k="standard" type="number" min="0" max="255" value="${kanal.standard ?? 0}"></td>
      <td><input data-k="grad" type="number" value="${kanal.grad ?? ""}"></td>
      <td><input data-k="bereiche" style="width:220px" value='${t(kanal.bereiche ? JSON.stringify(kanal.bereiche) : "").replaceAll("'", "&#39;")}'></td>
    </tr>`;
  }

  function editor(eintrag) {
    feld("detail").innerHTML = `
      <div class="kasten">
        <h2>Eigener Gerätetyp</h2>
        <div class="zeile">
          <label>Hersteller <input id="e-hersteller" value="${t(eintrag.hersteller)}"></label>
          <label>Name <input id="e-name" value="${t(eintrag.name)}"></label>
          <label>Gewicht (kg) <input id="e-gewicht" type="number" step="0.1" value="${eintrag.physik?.gewicht_kg ?? ""}"></label>
          <label>Abstrahlwinkel (°) <input id="e-winkel" type="number" value="${eintrag.physik?.abstrahlwinkel_grad ?? ""}"></label>
        </div>
        <h2>Kanäle</h2>
        <div class="tabelle-huelle"><table id="e-kanaele">
          <tr><th>Name</th><th>Typ</th><th>Standard</th><th>Grad</th><th>Bereiche (JSON, optional)</th></tr>
          ${Object.entries(eintrag.kanaele).map(([n, k]) => kanalZeile(n, k)).join("")}
        </table></div>
        <p><button id="e-kanal">Kanal hinzufügen</button></p>
        <h2>Modi</h2>
        <p class="leise">Eine Zeile pro Modus: Name, dann ein Doppelpunkt, dann die Kanalnamen mit Komma getrennt.</p>
        <textarea id="e-modi" rows="4" style="width:100%">${t(eintrag.modi.map((m) => `${m.name}: ${m.kanaele.map((k) => k ?? "-").join(", ")}`).join("\n"))}</textarea>
        <p><button id="e-speichern" class="haupt">Speichern</button></p>
      </div>`;
    feld("e-kanal").onclick = () => feld("e-kanaele").tBodies[0].insertAdjacentHTML("beforeend", kanalZeile("", { typ: "sonstiges" }));
    feld("e-speichern").onclick = async () => {
      const kanaele = {};
      for (const zeile of wurzel.querySelectorAll("#e-kanaele tr:not(:first-child)")) {
        const wert = (k) => zeile.querySelector(`[data-k=${k}]`).value.trim();
        if (!wert("name")) continue;
        const kanal = { ...(eintrag.kanaele[wert("name")] ?? {}), typ: wert("typ"), standard: Number(wert("standard")) };
        if (wert("grad")) kanal.grad = Number(wert("grad"));
        delete kanal.bereiche;
        if (wert("bereiche")) {
          try { kanal.bereiche = JSON.parse(wert("bereiche")); }
          catch { return meldung(`Bereiche von ${wert("name")} sind kein gültiges JSON.`); }
        }
        kanaele[wert("name")] = kanal;
      }
      const modi = feld("e-modi").value.split("\n").filter((z) => z.includes(":")).map((zeile) => {
        const [name, liste] = zeile.split(/:(.*)/s);
        return { name: name.trim(), kanaele: liste.split(",").map((k) => k.trim()).map((k) => (k === "-" ? null : k)) };
      });
      const hersteller = feld("e-hersteller").value.trim();
      const name = feld("e-name").value.trim();
      const zahl = (id) => (feld(id).value === "" ? null : Number(feld(id).value));
      const fertig = await senden("/katalog", {
        ...eintrag, id: `${hersteller}/${name}`, hersteller, name, kanaele, modi,
        physik: { gewicht_kg: zahl("e-gewicht"), abstrahlwinkel_grad: zahl("e-winkel") },
      });
      await suchen();
      anzeigen(fertig.id);
    };
  }

  feld("suche").oninput = suchen;
  feld("neu").onclick = () => editor(structuredClone(LEER));
  feld("importieren").onclick = () => feld("importdatei").click();
  feld("importdatei").onchange = async () => {
    const datei = feld("importdatei").files[0];
    if (!datei) return;
    const { id } = await api("/katalog/importieren?name=" + encodeURIComponent(datei.name), { method: "POST", body: datei });
    await suchen();
    anzeigen(id);
  };
  suchen();
}
