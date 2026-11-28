// Die Live-Verbindung zum MacBook (WebSocket). Hält den Stand aktuell, schickt Befehle, verbindet sich selbst neu.
// Ohne Verbindung ändert das iPad nie das Licht: Tasten sind dann grau, das Licht läuft am MacBook weiter.
import { erinnern, merken, meldung } from "./hilfe.js";

const zuhoerer = new Set();
export const stand = { fest: null, z: { exec: {} }, verbunden: false, rtt: null, version: null };
let ws = null;
let seq = 0;
const offen = new Map();          // seq -> {fertig, fehler, uhr}
let warten = 250;
let pingUhr = null;
let neuUhr = null;

export function abonnieren(f) { zuhoerer.add(f); return () => zuhoerer.delete(f); }
function melden(teile) { for (const f of zuhoerer) { try { f(stand, teile); } catch (e) { console.error(e); } } }

export function token() { return erinnern("token"); }
export function abmelden() { merken("token", null); location.reload(); }

export async function koppeln(pin, name) {
  const antwort = await fetch("/pult/koppeln", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin, name }) });
  const daten = await antwort.json().catch(() => ({}));
  if (!antwort.ok) throw new Error(daten.fehler || "Koppeln ging nicht.");
  merken("token", daten.token);
  return daten.token;
}

export function verbinden() {
  clearTimeout(neuUhr);
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const adresse = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/pult/ws`;
  ws = new WebSocket(adresse);
  ws.onopen = () => ws.send(JSON.stringify({ typ: "hallo", token: token(), protokoll: 1, version: window.PULT_VERSION }));
  ws.onmessage = (e) => {
    let n;
    try { n = JSON.parse(e.data); } catch { return; }
    if (n.typ === "fest") {
      if (window.PULT_VERSION && n.version && n.version !== window.PULT_VERSION) { location.reload(); return; }
      stand.fest = n;
      stand.version = n.version;
      if (!stand.verbunden) { stand.verbunden = true; warten = 250; }
      melden(["fest", "verbunden"]);
    } else if (n.typ === "zustand") {
      const teile = Object.keys(n).filter((k) => k !== "typ" && k !== "voll");
      for (const k of teile) {
        if (k === "exec") Object.assign(stand.z.exec, n.exec);
        else stand.z[k] = n[k];
      }
      melden(teile);
    } else if (n.typ === "antwort") {
      const warte = offen.get(n.seq);
      if (!warte) return;
      offen.delete(n.seq);
      clearTimeout(warte.uhr);
      if (n.ok) warte.fertig(n.ergebnis); else warte.fehler(new Error(n.fehler || "Ging nicht."));
    } else if (n.typ === "pong") {
      stand.rtt = Math.round(performance.now() - n.t);
    }
  };
  ws.onclose = (e) => {
    const warVerbunden = stand.verbunden;
    stand.verbunden = false;
    clearInterval(pingUhr);
    for (const [, w] of offen) { clearTimeout(w.uhr); w.fehler(new Error("Keine Verbindung zum MacBook.")); }
    offen.clear();
    melden(["verbunden"]);
    if (e.code === 4401) { meldung("Dieses iPad ist nicht (mehr) gekoppelt. Bitte neu koppeln.", "fehler", 8000); merken("token", null); setTimeout(() => location.reload(), 2500); return; }
    if (warVerbunden) meldung("Verbindung zum MacBook weg – das Licht läuft dort weiter. Verbinde neu …", "fehler");
    neuUhr = setTimeout(verbinden, warten);
    warten = Math.min(2000, warten * 2);
  };
  ws.onerror = () => {};
  clearInterval(pingUhr);
  pingUhr = setInterval(() => { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ typ: "ping", t: performance.now() })); }, 1000);
}

// Befehl schicken. Gibt ein Promise zurück (Ergebnis oder Fehler mit Text vom MacBook).
export function befehl(was, felder = {}, { still = false } = {}) {
  return new Promise((fertig, fehler) => {
    if (!ws || ws.readyState !== WebSocket.OPEN || !stand.verbunden) {
      const f = new Error("Keine Verbindung zum MacBook.");
      if (!still) meldung(f.message, "fehler");
      return fehler(f);
    }
    seq += 1;
    const nummer = seq;
    const uhr = setTimeout(() => { offen.delete(nummer); fehler(new Error("Keine Antwort vom MacBook.")); }, was.startsWith("chat") ? 120000 : 8000);
    offen.set(nummer, { fertig, fehler: (e) => { if (!still) meldung(e.message, "fehler"); fehler(e); }, uhr });
    ws.send(JSON.stringify({ typ: "befehl", seq: nummer, was, ...felder }));
  });
}

// Fader: höchstens alle 30 ms senden, der letzte Wert kommt immer an (ohne Antwort abzuwarten)
const faderZeit = new Map();
const faderUhr = new Map();
export function faderSenden(nr, wert, art = "fader") {
  const jetzt = performance.now();
  clearTimeout(faderUhr.get(art + nr));
  const los = () => { faderZeit.set(art + nr, performance.now()); befehl(art, art === "grand" ? { wert } : { nr, wert }, { still: true }).catch(() => {}); };
  if (jetzt - (faderZeit.get(art + nr) || 0) > 30) los();
  else faderUhr.set(art + nr, setTimeout(los, 35));
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && (!ws || ws.readyState !== WebSocket.OPEN)) { warten = 250; verbinden(); }
});
