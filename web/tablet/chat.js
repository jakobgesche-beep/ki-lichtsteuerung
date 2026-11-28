// KI-Chat zum Hereinschieben: Szene beschreiben (tippen oder diktieren), Vorschlag ansehen (nur Vorschau,
// nie live), „Auf Fader legen“ → Executor antippen → fertig, sofort drückbar.
import { befehl, stand, abonnieren } from "./verbindung.js";
import { el, t, tippen, merken, erinnern, meldung } from "./hilfe.js";
import { zielWaehlen } from "./kontext.js";

export function chatLeiste(wurzel) {
  const verlauf = el("div.chat-verlauf");
  const feld = el("textarea.chat-eingabe", { rows: 2, placeholder: "z. B. „Moving Heads drehen sich wild und wechseln die ganze Zeit die Farbe“", enterkeyhint: "send" });
  const status = el("div.chat-status");
  const karte = el("div.chat-karte");
  let offen = false;

  const senden = async () => {
    const text = feld.value.trim();
    if (!text) return;
    feld.value = "";
    try { await befehl("chat", { text }); } catch {}
  };
  feld.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); senden(); } });

  function zeigen() {
    const c = stand.z.chat || {};
    const internet = stand.z.netz?.internet;
    status.textContent = c.denkt ? "Claude denkt …" : !c.bereit ? "Ohne Claude-Schlüssel: einfache Sätze" : internet === false ? "Kein Internet: einfache Sätze" : "Claude bereit";
    status.className = `chat-status ${c.denkt ? "denkt" : !c.bereit || internet === false ? "offline" : "bereit"}`;
    verlauf.replaceChildren(...(c.zeilen || []).map((z) => el(`div.chat-zeile.${z.rolle || "hinweis"}`, {}, z.text || "")));
    verlauf.scrollTop = verlauf.scrollHeight;
    const e = c.entwurf;
    if (!e) { karte.replaceChildren(); karte.hidden = true; return; }
    karte.hidden = false;
    const zeigeVorschau = erinnern("vorschau-zeigen", true);
    karte.replaceChildren(
      el("div.karte-kopf", {}, el("b", {}, e.name || "Vorschlag"), el("small", {}, e.art === "fader" ? "Fader belegen" : e.art === "profil" ? "Profil" : e.art === "song" ? "Song-Show" : "Szene")),
      el("p", {}, e.erklaerung || ""),
      el("div.karte-cues", {}, (e.cues || []).map((cue, i) => tippen(el(`button.taste.klein${i === e.cue ? ".an" : ""}`, {}, `${i + 1}. ${cue.name}`), () => befehl("chat_vorschau", { cue: i }).catch(() => {})))),
      el("div.zeile", {},
        tippen(el(`button.taste.klein${zeigeVorschau ? ".an" : ""}`, {}, "Vorschau auf der Bühne"), () => { merken("vorschau-zeigen", !zeigeVorschau); zeigen(); }),
        tippen(el("button.taste.klein", {}, "Verwerfen"), () => befehl("chat_verwerfen").catch(() => {}))),
      e.art === "profil" || e.art === "song"
        ? tippen(el("button.taste.gruen.gross", {}, "Übernehmen"), () => befehl("chat_uebernehmen", {}).catch(() => {}))
        : tippen(el("button.taste.gruen.gross", {}, "Auf Fader legen …"), () => {
          schliessen();
          zielWaehlen("Szene auf welchen Fader? Executor antippen", async (nr) => {
            try {
              await befehl("chat_uebernehmen", { fader: nr });
              meldung(`Liegt auf Executor ${nr} (Fader 100 %). Zum Starten die Taste drücken.`, "ok", 5000);
            } catch {}
          });
        }));
  }
  function oeffnen() { offen = true; wurzel.classList.add("offen"); zeigen(); setTimeout(() => feld.focus(), 200); }
  function schliessen() { offen = false; wurzel.classList.remove("offen"); feld.blur(); }

  wurzel.replaceChildren(el("div.chat", {},
    el("header.chat-kopf", {}, el("b", {}, "KI-Licht-Chat"), status,
      tippen(el("button.taste.klein", {}, "Neu"), () => befehl("chat_neu").catch(() => {})),
      tippen(el("button.taste.klein", {}, "✕"), schliessen)),
    verlauf, karte,
    el("div.chat-senden", {}, feld, tippen(el("button.taste.gruen", {}, "Senden"), senden)),
    el("p.leise.klein", {}, "Tipp: Mit dem Mikrofon auf der Tastatur diktieren. Nichts geht live, bevor du es auf einen Fader legst.")));
  abonnieren((s, teile) => { if (teile.includes("chat") || teile.includes("netz")) zeigen(); });
  return { oeffnen, schliessen, get offen() { return offen; } };
}
