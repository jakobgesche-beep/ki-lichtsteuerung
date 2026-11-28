// Kleine Helfer für das iPad-Pult: Elemente bauen, Text sicher einsetzen, kurze Meldungen.

export function t(text) {
  return String(text ?? "").replace(/[&<>"']/g, (z) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[z]));
}

// el("button.taste.gross", { onclick }, "Text") – Klassen per Punkt, Kinder als Text oder Elemente
export function el(art, eigenschaften = {}, ...kinder) {
  const [tag, ...klassen] = art.split(".");
  const e = document.createElement(tag || "div");
  if (klassen.length) e.className = klassen.join(" ");
  for (const [k, v] of Object.entries(eigenschaften || {})) {
    if (k === "data") Object.assign(e.dataset, v);
    else if (k === "stil") Object.assign(e.style, v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "html") e.innerHTML = v;
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const kind of kinder.flat()) {
    if (kind === null || kind === undefined || kind === false) continue;
    e.append(kind instanceof Node ? kind : document.createTextNode(String(kind)));
  }
  return e;
}

const toasts = () => document.getElementById("toasts");
export function meldung(text, art = "info", dauer = 3500) {
  if (!text || !toasts()) return;
  const schon = [...toasts().children].find((k) => k.dataset.text === text);
  if (schon) return;
  const k = el(`div.toast.${art}`, { data: { text } }, text);
  toasts().append(k);
  setTimeout(() => k.classList.add("weg"), dauer);
  setTimeout(() => k.remove(), dauer + 400);
}

export const prozent = (wert) => `${Math.round((Number(wert) || 0) * 100)}`;

// Antippen: reagiert sofort beim Berühren (pointerdown), nicht erst beim Loslassen – wie eine echte Taste.
export function tippen(element, aktion) {
  element.addEventListener("pointerdown", (e) => {
    if (e.button > 0) return;
    e.preventDefault();
    element.classList.add("gedrueckt");
    aktion(e);
  });
  const los = () => element.classList.remove("gedrueckt");
  element.addEventListener("pointerup", los);
  element.addEventListener("pointercancel", los);
  element.addEventListener("pointerleave", los);
  return element;
}

// Halten: an beim Berühren, aus beim Loslassen (auch wenn der Finger wegrutscht oder die App weggeht)
export function halten(element, an, aus) {
  let gehalten = false;
  const loslassen = () => {
    if (!gehalten) return;
    gehalten = false;
    element.classList.remove("gedrueckt");
    aus();
  };
  element.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    element.setPointerCapture?.(e.pointerId);
    gehalten = true;
    element.classList.add("gedrueckt");
    an();
  });
  for (const ereignis of ["pointerup", "pointercancel", "lostpointercapture"]) element.addEventListener(ereignis, loslassen);
  document.addEventListener("visibilitychange", () => { if (document.hidden) loslassen(); });
  window.addEventListener("blur", loslassen);
  return element;
}

// Lange drücken (0,6 s): zum Beispiel Executor-Einstellungen öffnen
export function langDruecken(element, aktion, ms = 600) {
  let uhr = null;
  element.addEventListener("pointerdown", () => { uhr = setTimeout(() => { uhr = null; aktion(); }, ms); });
  for (const e of ["pointerup", "pointercancel", "pointerleave", "pointermove"]) {
    element.addEventListener(e, (ev) => {
      if (e === "pointermove" && Math.abs(ev.movementY) + Math.abs(ev.movementX) < 6) return;
      clearTimeout(uhr); uhr = null;
    });
  }
}

export function merken(schluessel, wert) { try { localStorage.setItem("pult-" + schluessel, JSON.stringify(wert)); } catch {} }
export function erinnern(schluessel, standard = null) {
  try { const w = localStorage.getItem("pult-" + schluessel); return w === null ? standard : JSON.parse(w); } catch { return standard; }
}

export const FARBNAMEN = { rot: "Rot", orange: "Orange", gold: "Gold", gelb: "Gelb", gruen: "Grün", cyan: "Cyan",
  hellblau: "Hellblau", blau: "Blau", lila: "Lila", pink: "Pink", weiss: "Weiß", warmweiss: "Warmweiß" };
// Anzeige-Farben (dieselben Namen versteht das MacBook, siehe lichtsteuerung/farben.py)
export const FARBWERTE = { rot: "#ff2a1f", orange: "#ff8a00", gold: "#ffb43a", gelb: "#ffe100", gruen: "#25d045", cyan: "#19d3e6",
  hellblau: "#80c0ff", blau: "#2a5cff", lila: "#8a3dff", pink: "#ff2fa8", weiss: "#ffffff", warmweiss: "#ffd9a0" };
