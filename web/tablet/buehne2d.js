// Bühne von oben (Draufsicht): wo die Lichter hängen, wohin sie leuchten, in welcher Farbe und wie hell.
// Leicht genug fürs iPad (kein 3D). x nach rechts, y nach hinten in die Bühne, Publikum unten.
import { el } from "./hilfe.js";

export function buehne2d({ vorschau = false, beiTipp = null } = {}) {
  const leinwand = el("canvas.buehne2d");
  const huelle = el("div.buehne2d-huelle", {}, leinwand, el("div.buehne2d-schild"));
  const schild = huelle.lastChild;
  let aufbau = null, geraete = [], vorschauGeraete = null, zeigeVorschau = false, punkt = null;
  let bereich = { x0: -6, x1: 6, y0: -4, y1: 6 };

  function zuPixel(x, y, b, h) {
    const sx = b / (bereich.x1 - bereich.x0), sy = h / (bereich.y1 - bereich.y0), s = Math.min(sx, sy);
    const ox = (b - s * (bereich.x1 - bereich.x0)) / 2, oy = (h - s * (bereich.y1 - bereich.y0)) / 2;
    return [ox + (x - bereich.x0) * s, h - (oy + (y - bereich.y0) * s), s];
  }
  function zuMeter(px, py, b, h) {
    const sx = b / (bereich.x1 - bereich.x0), sy = h / (bereich.y1 - bereich.y0), s = Math.min(sx, sy);
    const ox = (b - s * (bereich.x1 - bereich.x0)) / 2, oy = (h - s * (bereich.y1 - bereich.y0)) / 2;
    return [bereich.x0 + (px - ox) / s, bereich.y0 + (h - py - oy) / s];
  }

  function zeichnen() {
    const verhaeltnis = window.devicePixelRatio || 1;
    const b = leinwand.clientWidth, h = leinwand.clientHeight;
    if (!b || !h) return;
    if (leinwand.width !== Math.round(b * verhaeltnis)) { leinwand.width = Math.round(b * verhaeltnis); leinwand.height = Math.round(h * verhaeltnis); }
    const c = leinwand.getContext("2d");
    c.setTransform(verhaeltnis, 0, 0, verhaeltnis, 0, 0);
    c.clearRect(0, 0, b, h);
    if (!aufbau) return;
    const kante = aufbau.buehne.hoehe_kante_m || 0;
    // Publikum und Bühne
    const pub = aufbau.publikum;
    let [ax, ay] = zuPixel(pub.x_von_m, pub.y_bis_m, b, h);
    let [bx, by] = zuPixel(pub.x_bis_m, Math.max(pub.y_von_m, bereich.y0), b, h);
    c.fillStyle = "#121315"; c.fillRect(ax, ay, bx - ax, by - ay);
    const breite = aufbau.buehne.breite_m, tiefe = aufbau.buehne.tiefe_m;
    [ax, ay] = zuPixel(-breite / 2, tiefe, b, h);
    [bx, by] = zuPixel(breite / 2, 0, b, h);
    c.fillStyle = "#1c1d21"; c.fillRect(ax, ay, bx - ax, by - ay);
    c.strokeStyle = "#3a3d42"; c.lineWidth = 1; c.strokeRect(ax + 0.5, ay + 0.5, bx - ax, by - ay);
    c.fillStyle = "#5c6066"; c.font = "11px -apple-system, sans-serif"; c.fillText("Bühne", ax + 6, ay + 14);
    c.fillText("Publikum", ax + 6, by + 16);
    // Lichtflecken
    const liste = zeigeVorschau && vorschauGeraete ? vorschauGeraete : geraete;
    const nachId = Object.fromEntries((aufbau.geraete || []).map((g) => [g.id, g]));
    c.globalCompositeOperation = "lighter";
    for (const g of liste) {
      const info = nachId[g.id];
      if (!info || !info.leuchtet || !g.richtung || g.hell <= 0.01) continue;
      const [x, y, z] = [info.ort.x, info.ort.y, info.ort.z];
      const [dx, dy, dz] = g.richtung;
      let ziel = null;
      if (dz < -0.05) {
        let t = (z - (y > 0 ? kante : 0)) / -dz;
        let tx = x + t * dx, ty = y + t * dy;
        if (ty < 0 && kante > 0) { t = z / -dz; tx = x + t * dx; ty = y + t * dy; }
        ziel = [tx, ty, t];
      }
      if (!ziel) continue;
      const [px, py, s] = zuPixel(ziel[0], ziel[1], b, h);
      const radius = Math.max(6, Math.tan(((info.kegel || 20) * Math.PI) / 360) * ziel[2] * s);
      const [r, gg, bb] = g.farbe.map((f) => Math.round(f * 255));
      const verlauf = c.createRadialGradient(px, py, 0, px, py, radius);
      verlauf.addColorStop(0, `rgba(${r},${gg},${bb},${Math.min(1, g.hell * 0.95)})`);
      verlauf.addColorStop(1, `rgba(${r},${gg},${bb},0)`);
      c.fillStyle = verlauf;
      c.beginPath(); c.arc(px, py, radius, 0, Math.PI * 2); c.fill();
      // Strahl vom Gerät zum Fleck
      const [qx, qy] = zuPixel(x, y, b, h);
      c.strokeStyle = `rgba(${r},${gg},${bb},${Math.min(0.5, g.hell * 0.5)})`; c.lineWidth = 2;
      c.beginPath(); c.moveTo(qx, qy); c.lineTo(px, py); c.stroke();
    }
    c.globalCompositeOperation = "source-over";
    // Geräte
    for (const info of aufbau.geraete || []) {
      if (!info.leuchtet) continue;
      const g = liste.find((x) => x.id === info.id);
      const [px, py] = zuPixel(info.ort.x, info.ort.y, b, h);
      const farbe = g ? `rgb(${g.farbe.map((f) => Math.round(40 + f * 215 * Math.max(0.25, g.hell))).join(",")})` : "#444";
      c.fillStyle = farbe; c.strokeStyle = "#000"; c.lineWidth = 1.5;
      c.beginPath();
      if (info.beweglich) c.arc(px, py, 7, 0, Math.PI * 2); else c.rect(px - 6, py - 6, 12, 12);
      c.fill(); c.stroke();
    }
    if (punkt) {
      const [px, py] = zuPixel(punkt[0], punkt[1], b, h);
      c.strokeStyle = "#f2c200"; c.lineWidth = 2;
      c.beginPath(); c.arc(px, py, 10, 0, Math.PI * 2); c.moveTo(px - 15, py); c.lineTo(px + 15, py); c.moveTo(px, py - 15); c.lineTo(px, py + 15); c.stroke();
    }
    schild.textContent = zeigeVorschau && vorschauGeraete ? "VORSCHAU (nicht live)" : "";
    huelle.classList.toggle("vorschau", Boolean(zeigeVorschau && vorschauGeraete));
  }

  if (beiTipp) {
    leinwand.addEventListener("pointerdown", (e) => {
      const r = leinwand.getBoundingClientRect();
      const [x, y] = zuMeter(e.clientX - r.left, e.clientY - r.top, r.width, r.height);
      punkt = [x, y];
      zeichnen();
      beiTipp(x, y);
    });
  }
  const beobachter = new ResizeObserver(() => zeichnen());
  beobachter.observe(leinwand);

  return {
    element: huelle,
    aufbauSetzen(neu) {
      aufbau = neu;
      if (neu) {
        const breite = neu.buehne.breite_m, tiefe = neu.buehne.tiefe_m;
        const xs = (neu.geraete || []).map((g) => g.ort.x);
        bereich = { x0: Math.min(-breite / 2 - 1, ...xs.map((x) => x - 1)), x1: Math.max(breite / 2 + 1, ...xs.map((x) => x + 1)), y0: -4, y1: tiefe + 1 };
      }
      zeichnen();
    },
    setzen(neueGeraete, neueVorschau, mitVorschau) {
      geraete = neueGeraete || geraete;
      vorschauGeraete = neueVorschau;
      zeigeVorschau = Boolean(mitVorschau);
      zeichnen();
    },
    punktZeigen(p) { punkt = p; zeichnen(); },
    ende() { beobachter.disconnect(); },
  };
}
