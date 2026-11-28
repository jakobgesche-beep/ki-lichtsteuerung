// Master-Spalte rechts, immer sichtbar: GO+ / GO− / AUS für den gewählten Executor, Grand Master,
// die Not-Tasten (Blackout, Warmweiß, Automatik Pause, Strobo aus), Tap und der KI-Knopf.
import { befehl, faderSenden, stand, abonnieren } from "./verbindung.js";
import { el, t, tippen } from "./hilfe.js";
import { fader } from "./fader.js";
import { frage } from "./kontext.js";

const NOT = [["blackout", "BLACKOUT", "rot"], ["warmweiss", "WARMWEISS", "gelb"], ["pause", "AUTO PAUSE", "blau"], ["strobo_aus", "STROBO AUS", "grau"]];

export function masterSpalte(wurzel, { chatOeffnen }) {
  const hauptName = el("div.master-haupt");
  const go = tippen(el("button.taste.go.gross", {}, "GO+"), () => befehl("go_haupt", { richtung: "plus" }).catch(() => {}));
  const zurueck = tippen(el("button.taste.gross", {}, "GO−"), () => befehl("go_haupt", { richtung: "minus" }).catch(() => {}));
  const aus = tippen(el("button.taste.gross", {}, "AUS"), () => befehl("haupt_aus").catch(() => {}));
  const gm = fader({ art: "grand", beiAenderung: (wert) => faderSenden(0, wert, "grand") });
  const gmWert = el("div.gm-titel", {}, "GRAND");
  const notKnoepfe = Object.fromEntries(NOT.map(([art, text, farbe]) => [art, tippen(el(`button.taste.not.${farbe}`, { data: { art } }, text), async () => {
    const an = !stand.z.ov?.[art];
    if (art === "blackout" && !an && !(await frage("Blackout beenden?", "Das Licht geht wieder an.", "Licht an", "gruen"))) return;
    befehl("override", { taste: art, an }).catch(() => {});
  })]));
  const tap = tippen(el("button.taste.tap", {}, el("b", {}, "TAP"), el("span.tap-bpm", {}, "–")), () => befehl("tap").catch(() => {}));
  const ki = tippen(el("button.taste.ki", {}, "KI-Chat"), () => chatOeffnen());

  wurzel.replaceChildren(el("div.master", {},
    hauptName, el("div.master-go", {}, go, el("div.master-zwei", {}, zurueck, aus)),
    el("div.master-gm", {}, gmWert, gm.element),
    el("div.master-not", {}, ...Object.values(notKnoepfe)),
    el("div.master-zwei", {}, tap, ki)));

  return abonnieren((s, teile) => {
    if (teile.includes("master") || teile.includes("exec")) {
      const m = s.z.master || {};
      const h = s.z.exec[String(m.haupt)] || {};
      hauptName.innerHTML = `<span>Executor ${t(m.haupt || "")}</span><b>${t(h.label || h.name || "–")}</b>`;
      gm.setzen(m.grand ?? 1);
      gmWert.textContent = `GRAND ${Math.round((m.grand ?? 1) * 100)}`;
    }
    if (teile.includes("ov")) for (const [art, knopf] of Object.entries(notKnoepfe)) knopf.classList.toggle("an", Boolean(s.z.ov?.[art]));
    if (teile.includes("show") || teile.includes("musik")) tap.lastChild.textContent = s.z.show?.tap ? `${Math.round(s.z.show.tap)}` : `${Math.round(s.z.musik?.bpm || 0) || "–"}`;
    if (teile.includes("chat")) ki.classList.toggle("denkt", Boolean(s.z.chat?.denkt));
  });
}
