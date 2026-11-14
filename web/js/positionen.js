// Setup → Positionen: benannte Stellen auf der Bühne (Sänger links, Rednerpult …) und Moving Heads einmessen,
// damit sie diese Stellen wirklich treffen.
import { api, senden, t, meldung } from "./api.js";

const zahl = (wert) => Math.round(Number(wert) * 100) / 100;

export function positionenSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div>
        <div class="kasten"><h2>Moving Head einmessen</h2>
          <p class="leise">Damit die Köpfe die Positionen genau treffen: Kopf wählen, Position wählen, „Hinfahren“.
            Jemand steht genau auf der Stelle (oder ein Klebeband liegt dort). Dann den Lichtkegel mit den Pfeilen genau
            darauf schieben und „Trifft: Punkt merken“. Mit 2 bis 3 Punkten an verschiedenen Stellen wird es genau.
            DMX muss an sein. Der Kopf leuchtet dabei weiß.</p>
          <div class="zeile">
            <label>Kopf <select id="em-kopf"></select></label>
            <button id="em-start">Einmessen starten</button>
            <button id="em-ende">Beenden</button>
          </div>
          <div id="em-bereich" hidden>
            <div class="zeile">
              <label>Position <select id="em-position"></select></label>
              <button id="em-hin" class="haupt">Hinfahren</button>
            </div>
            <div class="schubsen">
              <span class="leise">Pan</span>
              <button data-pan="-5">◀◀</button><button data-pan="-1">◀</button>
              <b id="em-pan">0°</b>
              <button data-pan="1">▶</button><button data-pan="5">▶▶</button>
              <span class="leise">Tilt</span>
              <button data-tilt="-5">▼▼</button><button data-tilt="-1">▼</button>
              <b id="em-tilt">0°</b>
              <button data-tilt="1">▲</button><button data-tilt="5">▲▲</button>
            </div>
            <p class="zeile"><button id="em-merken">Trifft: Punkt merken</button> <span id="em-punkte" class="leise"></span></p>
            <p class="zeile"><button id="em-rechnen">Ausrechnen</button> <button id="em-uebernehmen" class="haupt" disabled>Übernehmen</button></p>
            <p id="em-ergebnis"></p>
            <p class="leise" id="em-jetzt"></p>
          </div>
        </div>
      </div>
      <div>
        <div class="kasten"><h2>Benannte Positionen</h2>
          <p class="leise">Stellen auf der Bühne, die Cues, Look-Tasten und der Licht-Chat benutzen. Meter: x nach rechts
            (vom Publikum aus), y von der Bühnenkante nach hinten, z = Höhe (Kopfhöhe: Bühnenkante + 1,6 m).
            Eine Zeile wählen und in die Draufsicht tippen, dann liegt die Position dort.</p>
          <p id="pos-platzhalter" class="meldung gelb" hidden>Die Positionen sind noch geschätzt. Auf der Bühne nachmessen
            (zum Beispiel mit Klebeband-Marken) und hier eintragen.</p>
          <canvas id="pos-draufsicht" class="draufsicht" width="440" height="260"></canvas>
          <div class="tabelle-huelle"><table class="gt-tabelle" id="pos-tabelle"></table></div>
          <p class="zeile"><button id="pos-neu">+ Neue Position</button> <button id="pos-speichern" class="haupt">Speichern</button>
            <span id="pos-status" class="leise"></span></p>
        </div>
      </div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  let daten = null;
  let liste = [];              // [{name, x, y, z}] wie in der Tabelle
  let gewaehlt = 0;

  function tabelle() {
    feld("pos-tabelle").innerHTML = `<tr><th>Name</th><th>x</th><th>y</th><th>z</th><th></th></tr>` + liste.map((p, i) => `
      <tr class="${i === gewaehlt ? "lernt" : ""}" data-zeile="${i}">
        <td><input data-feld="name" data-i="${i}" value="${t(p.name)}"></td>
        ${["x", "y", "z"].map((k) => `<td><input type="number" step="0.1" data-feld="${k}" data-i="${i}" value="${p[k]}"></td>`).join("")}
        <td><button class="klein" data-weg="${i}" title="Position löschen">×</button></td></tr>`).join("");
    zeichnen();
  }

  function masstab(leinwand) {
    const b = daten.buehne;
    return Math.min((leinwand.width - 40) / b.breite_m, (leinwand.height - 50) / b.tiefe_m);
  }
  const zuPixel = (leinwand, x, y) => {
    const m = masstab(leinwand), b = daten.buehne;
    return [leinwand.width / 2 + x * m, 20 + (b.tiefe_m - y) * m];
  };
  const ausPixel = (leinwand, px, py) => {
    const m = masstab(leinwand), b = daten.buehne;
    return { x: zahl((px - leinwand.width / 2) / m), y: zahl(b.tiefe_m - (py - 20) / m) };
  };

  function zeichnen() {
    const leinwand = feld("pos-draufsicht");
    if (!leinwand || !daten) return;
    const z = leinwand.getContext("2d");
    const b = daten.buehne;
    z.fillStyle = "#070708"; z.fillRect(0, 0, leinwand.width, leinwand.height);
    const [lx, oy] = zuPixel(leinwand, -b.breite_m / 2, b.tiefe_m);
    const [rx, uy] = zuPixel(leinwand, b.breite_m / 2, 0);
    z.fillStyle = "#1c1d20"; z.fillRect(lx, oy, rx - lx, uy - oy);
    z.strokeStyle = "#34373b"; z.strokeRect(lx, oy, rx - lx, uy - oy);
    z.fillStyle = "#8d9196"; z.font = "11px sans-serif"; z.textAlign = "center";
    z.fillText("Publikum", leinwand.width / 2, leinwand.height - 8);
    liste.forEach((p, i) => {
      const [px, py] = zuPixel(leinwand, Number(p.x), Number(p.y));
      z.fillStyle = i === gewaehlt ? "#f2c200" : "#c9a227";
      z.beginPath(); z.arc(px, py, i === gewaehlt ? 6 : 4, 0, Math.PI * 2); z.fill();
      z.fillStyle = "#e3e3e3"; z.fillText(p.name, px, py - 9);
    });
  }

  async function laden() {
    daten = await api("/positionen");
    liste = Object.entries(daten.positionen).map(([name, p]) => ({ name, ...p }));
    feld("pos-platzhalter").hidden = !daten.platzhalter;
    gewaehlt = Math.min(gewaehlt, Math.max(0, liste.length - 1));
    tabelle();
    feld("em-kopf").innerHTML = daten.koepfe.map((k) => `<option value="${t(k.id)}">${t(k.name)}</option>`).join("")
      || `<option value="">kein Moving Head im Patch</option>`;
    feld("em-position").innerHTML = liste.map((p) => `<option>${t(p.name)}</option>`).join("");
    einmessenZeigen(daten.einmessen);
  }

  function einmessenZeigen(e) {
    feld("em-bereich").hidden = !e.geraet;
    if (e.geraet) feld("em-kopf").value = e.geraet;
    feld("em-pan").textContent = `${e.pan}°`;
    feld("em-tilt").textContent = `${e.tilt}°`;
    feld("em-punkte").textContent = e.punkte.length
      ? `Gemerkt: ${e.punkte.map((p) => p.name).join(", ")}${e.punkte.length < 2 ? " · noch mindestens einen Punkt an einer anderen Stelle" : ""}`
      : "noch kein Punkt";
    const r = e.ergebnis;
    feld("em-uebernehmen").disabled = !r;
    feld("em-ergebnis").innerHTML = r ? `Pan ${r.pan_versatz_grad > 0 ? "+" : ""}${r.pan_versatz_grad}°, Tilt ${r.tilt_versatz_grad > 0 ? "+" : ""}${r.tilt_versatz_grad}°
      ${r.pan_umkehren ? " · Pan umgekehrt" : ""}${r.tilt_umkehren ? " · Tilt umgekehrt" : ""}
      · passt im Mittel auf ${String(r.abweichung_grad).replace(".", ",")}° genau${r.abweichung_grad > 3 ? " <b>(ungenau: Ort des Kopfs im Patch prüfen)</b>" : ""}` : "";
    const j = e.jetzt;
    feld("em-jetzt").textContent = j && (j.pan_versatz_grad != null || j.pan_umkehren)
      ? `Bisher eingemessen: Pan ${j.pan_versatz_grad ?? 0}°, Tilt ${j.tilt_versatz_grad ?? 0}°${j.pan_umkehren ? ", Pan umgekehrt" : ""}${j.tilt_umkehren ? ", Tilt umgekehrt" : ""}.`
      : "Dieser Kopf ist noch nicht eingemessen.";
  }

  const einmessen = async (aktion, auftrag = {}) => {
    try { einmessenZeigen(await senden("/einmessen/" + aktion, auftrag)); } catch { /* Meldung kommt von senden() */ }
  };

  feld("pos-tabelle").addEventListener("input", (e) => {
    const { feld: name, i } = e.target.dataset;
    if (name === undefined) return;
    liste[Number(i)][name] = name === "name" ? e.target.value : e.target.value;
    gewaehlt = Number(i);
    zeichnen();
  });
  feld("pos-tabelle").addEventListener("click", (e) => {
    const weg = e.target.closest("[data-weg]");
    if (weg) { liste.splice(Number(weg.dataset.weg), 1); gewaehlt = 0; tabelle(); return; }
    const zeile = e.target.closest("[data-zeile]");
    if (zeile) { gewaehlt = Number(zeile.dataset.zeile); zeile.parentElement.querySelectorAll("tr").forEach((r) => r.classList.toggle("lernt", r === zeile)); zeichnen(); }
  });
  feld("pos-draufsicht").addEventListener("click", (e) => {
    if (!liste[gewaehlt]) return;
    const leinwand = feld("pos-draufsicht");
    const rand = leinwand.getBoundingClientRect();
    const punkt = ausPixel(leinwand, (e.clientX - rand.left) * leinwand.width / rand.width, (e.clientY - rand.top) * leinwand.height / rand.height);
    Object.assign(liste[gewaehlt], punkt);
    tabelle();
  });
  feld("pos-neu").onclick = () => {
    liste.push({ name: `Position ${liste.length + 1}`, x: 0, y: 1.5, z: zahl(daten.buehne.hoehe_kante_m + 1.6) });
    gewaehlt = liste.length - 1;
    tabelle();
  };
  feld("pos-speichern").onclick = async () => {
    const positionen = {};
    for (const p of liste) positionen[p.name.trim()] = { x: Number(p.x), y: Number(p.y), z: Number(p.z) };
    try {
      await senden("/positionen", { positionen });
      meldung("Positionen gespeichert.", "ok");
      laden();
    } catch { /* Meldung kommt von senden() */ }
  };
  feld("em-start").onclick = () => einmessen("start", { geraet: feld("em-kopf").value });
  feld("em-ende").onclick = () => einmessen("ende");
  feld("em-hin").onclick = () => einmessen("hinfahren", { position: feld("em-position").value });
  feld("em-merken").onclick = () => einmessen("merken");
  feld("em-rechnen").onclick = () => einmessen("ausrechnen");
  feld("em-uebernehmen").onclick = async () => {
    await einmessen("uebernehmen");
    meldung("Eingemessen. Ab jetzt rechnet jede Position damit.", "ok");
  };
  wurzel.querySelector(".schubsen").addEventListener("click", (e) => {
    const k = e.target.closest("button");
    if (!k) return;
    einmessen("schubsen", { pan: Number(k.dataset.pan ?? 0), tilt: Number(k.dataset.tilt ?? 0) });
  });

  laden().catch(() => {});
  return () => { senden("/einmessen/ende").catch(() => {}); };
}
