// Licht-Chat im Pult-Tab: beschreiben, was man sehen will. Der Vorschlag läuft erst nur in der Vorschau
// (Bühne zeigt "Vorschau Licht-Chat"). Übernehmen speichert ihn und legt ihn auf den gewählten Fader.
// Ohne Claude-Schlüssel oder ohne Internet versteht der Chat einfache Sätze selbst.
import { api, senden, t, meldung } from "./api.js";

export function lichtChat(huelle, { nachUebernehmen } = {}) {
  huelle.innerHTML = `
    <header><span>Licht-Chat <span class="chat-art" id="chat-art"></span></span>
      <span class="zeile"><button class="klein" id="chat-neu" title="Neues Gespräch">Neu</button>
      <button class="klein" id="chat-zu" title="Chat einklappen">⟩</button></span></header>
    <div class="chat-verlauf" id="chat-verlauf"></div>
    <div class="chat-entwurf" id="chat-entwurf" hidden></div>
    <form class="chat-eingabe" id="chat-form">
      <textarea id="chat-text" rows="2" placeholder="Was willst du sehen? Zum Beispiel: Spots langsam blau kreisen, PARs warmweiß atmen, auf Fader 3"></textarea>
      <button class="haupt" id="chat-senden">Senden</button>
    </form>
    <details class="chat-schluessel" id="chat-schluessel"><summary id="chat-schluessel-titel">Claude-Schlüssel</summary>
      <div id="chat-schluessel-inhalt"></div></details>`;
  const feld = (id) => huelle.querySelector("#" + id);
  let stand = null;
  let stempel = "";
  let liveDaten = null;
  let beendet = false;
  let laedt = false;
  let wartet = false;           // eigene Nachricht unterwegs

  function zeichnen(neu) {
    if (!neu) return;
    stand = neu;
    const sig = JSON.stringify([neu.anzeige, neu.entwurf, neu.denkt, neu.ki, neu.kosten_cent, liveDaten?.pult?.seite]);
    if (sig === stempel) return;
    stempel = sig;
    feld("chat-art").textContent = neu.ki.bereit ? "mit Claude" : "ohne Internet";
    feld("chat-art").className = `chat-art ${neu.ki.bereit ? "an" : ""}`;
    const zeilen = neu.anzeige.map((z) => `<div class="chat-zeile ${z.rolle}">${t(z.text)}</div>`).join("");
    feld("chat-verlauf").innerHTML = (zeilen || `<div class="chat-zeile hinweis">Beschreib einen Look, zum Beispiel:
      ${t(neu.beispiele)}. Der Vorschlag läuft erst nur in der Vorschau. Mit „Übernehmen“ landet er auf einem Fader.</div>`)
      + (neu.denkt ? `<div class="chat-zeile denkt">Denkt nach …</div>` : "");
    feld("chat-verlauf").scrollTop = feld("chat-verlauf").scrollHeight;
    feld("chat-text").disabled = neu.denkt;
    feld("chat-senden").disabled = neu.denkt;
    entwurfZeigen(neu.entwurf);
    feld("chat-schluessel-titel").textContent = neu.ki.bereit
      ? `Claude-Schlüssel: ${neu.ki.maskiert}${neu.kosten_cent ? ` · bisher ca. ${neu.kosten_cent.toLocaleString("de-DE")} Cent` : ""}`
      : "Claude-Schlüssel eintragen (für freie Sätze)";
    feld("chat-schluessel-inhalt").innerHTML = neu.ki.bereit
      ? `<p class="leise">Modell: ${t(neu.ki.modell)}. ${neu.ki.quelle === "umgebung" ? "Kommt aus der Umgebungsvariable ANTHROPIC_API_KEY." : "Liegt nur auf diesem Rechner (lokal.json im Datenordner)."}
         Ein Ausgabenlimit stellt ihr in der Claude Console ein.</p>
         ${neu.ki.quelle === "datei" ? `<button class="klein gefahr" id="chat-schluessel-weg">Schlüssel entfernen</button>` : ""}`
      : `<p class="leise">Den Schlüssel gibt es in der Claude Console (console.anthropic.com → API Keys). Er bleibt nur auf diesem Rechner.
           Der Chat braucht Internet nur zum Programmieren, nie für die Show.</p>
         <div class="zeile"><input type="password" id="chat-schluessel-wert" placeholder="sk-ant-…" autocomplete="off" style="flex:1">
         <button class="klein" id="chat-schluessel-speichern">Speichern</button></div>`;
  }

  function freierFader() {
    const pult = liveDaten?.pult;
    if (!pult) return 1;
    const von = (pult.seite - 1) * pult.pro_seite;
    const frei = pult.executoren.slice(von, von + pult.pro_seite).find((e) => !e.art)
      ?? pult.executoren.find((e) => !e.art);
    return frei?.nummer ?? 1;
  }

  function entwurfZeigen(entwurf) {
    const kasten = feld("chat-entwurf");
    kasten.hidden = !entwurf;
    if (!entwurf) return;
    const vorschlag = entwurf.fader ?? freierFader();
    const fader = liveDaten?.pult?.executoren ?? [];
    kasten.innerHTML = `
      <div class="entwurf-kopf"><b>${t(entwurf.name)}</b> <span class="vorschau-schild">Vorschau, nicht live</span></div>
      ${entwurf.cues.length > 1 ? `<div class="entwurf-cues">${entwurf.cues.map((c, i) =>
        `<button class="klein ${i === entwurf.cue ? "an" : ""}" data-entwurf-cue="${i}" title="${t(c.name)}">${i + 1}. ${t(c.name)}</button>`).join("")}</div>` : ""}
      ${entwurf.vorhanden && !entwurf.ersetzt ? `<p class="leise">Eine Sequenz mit diesem Namen gibt es schon. Sie bleibt, der Vorschlag bekommt eine Nummer dazu.</p>` : ""}
      ${entwurf.vorhanden && entwurf.ersetzt ? `<p class="leise">Ersetzt die vorhandene Sequenz „${t(entwurf.name)}“ (Oops holt sie zurück).</p>` : ""}
      <div class="zeile">
        <label class="schalter">auf Fader <select id="entwurf-fader">
          <option value="">keinen (nur in den Pool)</option>
          ${fader.map((e) => `<option value="${e.nummer}" ${e.nummer === vorschlag ? "selected" : ""}>${e.nummer}${e.art ? " – " + t(e.name) : " (frei)"}</option>`).join("")}
        </select></label>
        <button class="haupt" id="entwurf-ok">Übernehmen</button>
        <button id="entwurf-weg">Verwerfen</button>
      </div>`;
  }

  async function absenden() {
    const text = feld("chat-text").value.trim();
    if (!text || stand?.denkt) return;
    feld("chat-text").value = "";
    zeichnen({ ...stand, anzeige: [...(stand?.anzeige ?? []), { rolle: "du", text }], denkt: true });
    wartet = true;
    try {
      zeichnen(await senden("/chat", { text }));
    } catch {
      feld("chat-text").value = text;
      zeichnen(await api("/chat").catch(() => stand));
    } finally {
      wartet = false;
    }
  }

  feld("chat-form").addEventListener("submit", (ereignis) => { ereignis.preventDefault(); absenden(); });
  feld("chat-text").addEventListener("keydown", (ereignis) => {
    if (ereignis.key === "Enter" && !ereignis.shiftKey) { ereignis.preventDefault(); absenden(); }
  });
  huelle.addEventListener("click", async (ereignis) => {
    const k = ereignis.target.closest("button");
    if (!k) return;
    try {
      if (k.id === "chat-neu") zeichnen(await senden("/chat/neu"));
      else if (k.id === "chat-zu") huelle.classList.toggle("zu");
      else if (k.dataset.entwurfCue !== undefined) zeichnen(await senden("/chat/vorschau", { cue: Number(k.dataset.entwurfCue) }));
      else if (k.id === "entwurf-weg") zeichnen(await senden("/chat/verwerfen"));
      else if (k.id === "entwurf-ok") {
        const fader = Number(feld("entwurf-fader").value) || null;
        const antwort = await senden("/chat/uebernehmen", { fader });
        zeichnen(antwort);
        meldung(fader ? `Liegt jetzt auf Fader ${fader}. Fader hoch oder Go+ drücken.` : "Liegt jetzt im Sequenzen-Pool.");
        nachUebernehmen?.(antwort);
      } else if (k.id === "chat-schluessel-speichern") {
        zeichnen(await senden("/ki/schluessel", { schluessel: feld("chat-schluessel-wert").value }));
        feld("chat-schluessel").open = false;
      } else if (k.id === "chat-schluessel-weg") {
        if (confirm("Den Claude-Schlüssel von diesem Rechner entfernen?")) zeichnen(await api("/ki/schluessel", { method: "DELETE" }));
      }
    } catch { /* Meldung kam schon */ }
  });

  api("/chat").then((neu) => { if (!beendet) zeichnen(neu); }).catch(() => {});

  return {
    live(neu) {
      liveDaten = neu;
      // Hat jemand anders (zum Beispiel am Tablet) den Chat benutzt: nachladen, sobald er fertig ist
      if (stand && !laedt && !wartet && stand.denkt && !neu.chat_denkt) {
        laedt = true;
        api("/chat").then(zeichnen).catch(() => {}).finally(() => (laedt = false));
      }
    },
    abbauen() { beendet = true; },
  };
}
