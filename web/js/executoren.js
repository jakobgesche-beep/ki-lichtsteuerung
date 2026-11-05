// Die Executor-Leiste: pro Platz ein Fader und die Tasten Go-, Go+ und Aus.
// Sie steht auf der Live-Seite und im Pult, gleich aufgebaut wie an einem echten Pult.
import { api, senden, t } from "./api.js";

export function executorLeiste(huelle) {
  huelle.classList.add("executoren");
  let sequenzen = [];
  let stand = "";

  async function laden() {
    sequenzen = (await api("/pult")).sequenzen;
    stand = "";
  }

  function zeigen(pult) {
    const neu = JSON.stringify(pult.executoren.map((e) => [e.sequenz, e.cues, e.index])) + pult.haupt + sequenzen;
    if (neu === stand) {
      // Nur die Fader nachziehen, damit man beim Schieben nicht gestört wird.
      pult.executoren.forEach((e) => {
        const regler = huelle.querySelector(`[data-fader="${e.nummer}"]`);
        if (regler && document.activeElement !== regler) regler.value = e.fader;
      });
      return;
    }
    stand = neu;
    huelle.innerHTML = pult.executoren.map((e) => `
      <div class="executor ${e.nummer === pult.haupt ? "haupt" : ""} ${e.index >= 0 ? "laeuft" : ""}">
        <select data-belegen="${e.nummer}" title="Sequenz auf diesen Executor legen">
          <option value="">${e.nummer}: frei</option>
          ${sequenzen.map((s) => `<option ${s === e.sequenz ? "selected" : ""}>${t(s)}</option>`).join("")}
        </select>
        <div class="cue-name">${e.index >= 0 ? `${e.index + 1}/${e.cues.length} ${t(e.cues[e.index])}` : e.sequenz ? `0/${e.cues.length}` : "&nbsp;"}</div>
        <input type="range" min="0" max="1" step="0.01" value="${e.fader}" data-fader="${e.nummer}" ${e.sequenz ? "" : "disabled"}>
        <div class="tasten3">
          <button data-aktion="zurueck" data-nr="${e.nummer}" ${e.sequenz ? "" : "disabled"}>Go−</button>
          <button data-aktion="go" data-nr="${e.nummer}" class="haupt" ${e.sequenz ? "" : "disabled"}>Go+</button>
          <button data-aktion="aus" data-nr="${e.nummer}" ${e.sequenz ? "" : "disabled"}>Aus</button>
        </div>
      </div>`).join("");
  }

  huelle.addEventListener("click", (ereignis) => {
    const knopf = ereignis.target.closest("[data-aktion]");
    if (knopf) senden(`/executor/${knopf.dataset.nr}/${knopf.dataset.aktion}`);
  });
  huelle.addEventListener("input", (ereignis) => {
    const regler = ereignis.target.closest("[data-fader]");
    if (regler) senden(`/executor/${regler.dataset.fader}/fader`, { wert: Number(regler.value) });
  });
  huelle.addEventListener("change", (ereignis) => {
    const auswahl = ereignis.target.closest("[data-belegen]");
    if (auswahl) senden(`/executor/${auswahl.dataset.belegen}/belegen`, { sequenz: auswahl.value || null });
  });

  laden();
  return { zeigen, laden };
}
