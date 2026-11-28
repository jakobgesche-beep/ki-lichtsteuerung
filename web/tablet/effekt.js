// Effekt-Editor (wie der Phaser am grandMA): Form wählen, Größe/Tempo/Versatz einstellen.
// Die Kurve zeigt den Weg der Moving Heads (X = Pan, Y = Tilt); die Punkte laufen mit ihrem Versatz live mit.
import { befehl, stand } from "./verbindung.js";
import { el, tippen, FARBWERTE, FARBNAMEN } from "./hilfe.js";

export const EFFEKTE = {
  kreis: { name: "Kreis", art: "bewegung" }, acht: { name: "Acht", art: "bewegung" }, schwenk: { name: "Schwenk", art: "bewegung" },
  nicken: { name: "Nicken", art: "bewegung" }, publikum: { name: "Übers Publikum", art: "bewegung" },
  dimmer_welle: { name: "Dimmer-Welle", art: "dimmer" }, dimmer_puls: { name: "Puls", art: "dimmer" },
  farbwechsel: { name: "Farbwechsel", art: "farbe" },
};

// Weg der Bewegung über eine Runde (0..1) → x, y zwischen -1 und 1
export function weg(art, phase) {
  const w = phase * Math.PI * 2;
  if (art === "kreis") return [Math.cos(w), Math.sin(w)];
  if (art === "acht") return [Math.sin(w), Math.sin(2 * w) / 2];
  if (art === "schwenk") return [Math.sin(w), 0];
  if (art === "nicken") return [0, Math.sin(w)];
  if (art === "publikum") return [Math.sin(w), -0.6 + 0.25 * Math.cos(2 * w)];
  return [0, 0];
}

export function kurveZeichnen(leinwand, art, groesse = 0.5, punkte = []) {
  const v = window.devicePixelRatio || 1;
  const b = leinwand.clientWidth, h = leinwand.clientHeight;
  if (!b || !h) return;
  if (leinwand.width !== Math.round(b * v)) { leinwand.width = Math.round(b * v); leinwand.height = Math.round(h * v); }
  const c = leinwand.getContext("2d");
  c.setTransform(v, 0, 0, v, 0, 0);
  c.clearRect(0, 0, b, h);
  const mx = b / 2, my = h / 2, r = Math.min(b, h) * 0.42;
  c.strokeStyle = "#2a2c30"; c.lineWidth = 1;
  c.beginPath(); c.moveTo(0, my); c.lineTo(b, my); c.moveTo(mx, 0); c.lineTo(mx, h); c.stroke();
  c.fillStyle = "#5c6066"; c.font = "11px -apple-system, sans-serif"; c.fillText("Pan", b - 28, my - 6); c.fillText("Tilt", mx + 6, 14);
  const info = EFFEKTE[art];
  if (!info) return;
  if (info.art === "bewegung") {
    c.strokeStyle = "#f2c200"; c.lineWidth = 2; c.beginPath();
    for (let i = 0; i <= 120; i += 1) {
      const [x, y] = weg(art, i / 120);
      const px = mx + x * r * groesse, py = my - y * r * groesse;
      if (i === 0) c.moveTo(px, py); else c.lineTo(px, py);
    }
    c.stroke();
    for (const p of punkte) {
      const [x, y] = weg(art, p.phase);
      c.fillStyle = p.farbe || "#fff"; c.strokeStyle = "#000";
      c.beginPath(); c.arc(mx + x * r * groesse, my - y * r * groesse, 7, 0, Math.PI * 2); c.fill(); c.stroke();
    }
  } else if (info.art === "dimmer") {
    const breite = b / Math.max(1, punkte.length) * 0.7;
    punkte.forEach((p, i) => {
      const hell = art === "dimmer_puls" ? Math.max(0, 1 - ((p.phase * 4) % 1) * 1.6) : (Math.sin(p.phase * Math.PI * 2) + 1) / 2;
      const x = (i + 0.15) * (b / Math.max(1, punkte.length));
      c.fillStyle = `rgba(242,194,0,${0.15 + 0.85 * hell})`;
      c.fillRect(x, h - 10 - hell * (h - 30), breite, hell * (h - 30));
    });
  } else {
    punkte.forEach((p, i) => {
      c.fillStyle = p.farbe || "#fff";
      c.fillRect((i + 0.15) * (b / Math.max(1, punkte.length)), h * 0.25, b / Math.max(1, punkte.length) * 0.7, h * 0.5);
    });
  }
}

export function effektEditor() {
  let art = "kreis";
  const werte = { groesse: 0.5, beats: 4, verteilung: 0.5, tiefe: 0.7, musik: true, bpm: 120, farben: ["rot", "blau", "gruen"] };
  const leinwand = el("canvas.effekt-kurve");
  const formen = el("div.effekt-formen", {}, Object.entries(EFFEKTE).map(([id, e]) => tippen(el("button.taste.klein", { data: { form: id } }, e.name), () => { art = id; formenZeigen(); regler(); })));
  const reglerFeld = el("div.effekt-regler");
  function formenZeigen() { for (const b of formen.children) b.classList.toggle("an", b.dataset.form === art); }

  function schieber(feld, titel, min, max, schritt, format) {
    const wert = el("b", {}, format(werte[feld]));
    const s = el("input", { type: "range", min, max, step: schritt, value: werte[feld] });
    s.oninput = () => { werte[feld] = Number(s.value); wert.textContent = format(werte[feld]); };
    return el("label.schieber", {}, el("span", {}, titel, " ", wert), s);
  }
  function regler() {
    const info = EFFEKTE[art];
    const teile = [];
    if (info.art === "bewegung") teile.push(schieber("groesse", "Größe", 0.05, 1, 0.05, (w) => `${Math.round(w * 100)} %`));
    if (info.art === "dimmer") teile.push(schieber("tiefe", "Tiefe", 0.1, 1, 0.05, (w) => `${Math.round(w * 100)} %`));
    teile.push(el("div.zeile", {}, el("span", {}, "Beats pro Runde"), ...[0.5, 1, 2, 4, 8, 16, 32].map((b) =>
      tippen(el(`button.taste.klein${werte.beats === b ? ".an" : ""}`, {}, String(b)), () => { werte.beats = b; regler(); }))));
    teile.push(schieber("verteilung", "Versatz zwischen den Geräten", 0, 1, 0.05, (w) => w === 0 ? "alle gleich" : w >= 0.99 ? "ganz verteilt" : `${Math.round(w * 100)} %`));
    teile.push(el("div.zeile", {}, tippen(el(`button.taste.klein${werte.musik ? ".an" : ""}`, {}, "im Takt der Musik"), () => { werte.musik = !werte.musik; regler(); }),
      werte.musik ? null : schieber("bpm", "BPM", 20, 240, 1, (w) => `${w}`)));
    if (info.art === "farbe") {
      teile.push(el("div.farb-reihe", {}, Object.keys(FARBWERTE).filter((f) => FARBNAMEN[f]).map((f) => tippen(el(`button.farb-knopf${werte.farben.includes(f) ? ".an" : ""}`, { stil: { background: FARBWERTE[f] }, title: FARBNAMEN[f] }),
        () => { werte.farben = werte.farben.includes(f) ? werte.farben.filter((x) => x !== f) : [...werte.farben, f]; regler(); }))));
    }
    reglerFeld.replaceChildren(...teile);
  }

  const knopf = tippen(el("button.taste.gruen", {}, "In den Programmer"), () => {
    const effekt = { art, beats: werte.beats, verteilung: werte.verteilung };
    if (EFFEKTE[art].art === "bewegung") effekt.groesse = werte.groesse;
    if (EFFEKTE[art].art === "dimmer") effekt.tiefe = werte.tiefe;
    if (EFFEKTE[art].art === "farbe") effekt.farben = werte.farben.length >= 2 ? werte.farben : ["rot", "blau"];
    if (!werte.musik) effekt.tempo = werte.bpm;
    befehl("effekt", { effekt }).catch(() => {});
  });

  let start = performance.now(), laeuft = true;
  function bild() {
    if (!laeuft) return;
    const bpm = werte.musik ? (stand.z.musik?.bpm || 120) : werte.bpm;
    const runden = ((performance.now() - start) / 60000) * bpm / werte.beats;
    const auswahl = stand.z.prog?.auswahl?.length ? stand.z.prog.auswahl : (stand.fest?.geraete || []).filter((g) => g.beweglich).map((g) => g.id);
    const punkte = auswahl.map((id, i) => {
      const phase = (runden + werte.verteilung * i / Math.max(1, auswahl.length)) % 1;
      const farbe = EFFEKTE[art].art === "farbe" ? (FARBWERTE[werte.farben[Math.floor(runden * werte.farben.length + i * werte.verteilung * werte.farben.length) % Math.max(1, werte.farben.length)]] || "#fff") : "#fff";
      return { phase, farbe };
    });
    kurveZeichnen(leinwand, art, werte.groesse, punkte);
    requestAnimationFrame(bild);
  }
  formenZeigen(); regler(); requestAnimationFrame(bild);
  return { element: el("div.effekt-editor", {}, formen, el("div.effekt-mitte", {}, leinwand, el("div", {}, reglerFeld, knopf))), ende: () => { laeuft = false; } };
}
