// Die festen Tasten für den Abend: immer sichtbar, groß, auch auf der Tastatur.
import { senden } from "./api.js";
import { abonnieren } from "./verbindung.js";

const TASTEN = [
  { id: "blackout", text: "Blackout", taste: "b" },
  { id: "warmweiss", text: "Warmweiß / Rede", taste: "w" },
  { id: "pause", text: "Automatik Pause", taste: "p" },
  { id: "strobo_aus", text: "Strobo aus", taste: "s" },
];
const WEITER = () => senden("/go/plus");
const ZURUECK = () => senden("/go/minus");

// Ein Update startet nie von selbst: Es könnte gerade eine Show laufen.
function updateHinweis(live) {
  const update = live.update;
  if (update.zustand === "bereit") {
    const knopf = update.gesperrt
      ? `<span class="leise">${update.gesperrt}</span>`
      : `<button data-update>Jetzt aktualisieren und neu starten</button>`;
    return `<div class="meldung gelb zeile">Version ${update.neu} ist bereit. ${knopf}</div>`;
  }
  if (update.zustand === "fehler") return `<div class="meldung gelb">${update.text}</div>`;
  return "";
}

document.addEventListener("click", (ereignis) => {
  if (ereignis.target.matches("[data-update]")) senden("/update/installieren");
});

export function tastenLeiste(leiste) {
  for (const { id, text, taste } of TASTEN) {
    const knopf = document.createElement("button");
    knopf.id = "taste-" + id;
    knopf.innerHTML = `${text} <kbd>${taste.toUpperCase()}</kbd>`;
    knopf.onclick = () => senden("/override/" + id);
    leiste.append(knopf);
  }
  const weiter = document.createElement("button");
  weiter.id = "taste-weiter";
  weiter.innerHTML = `Go+ <kbd>Leertaste</kbd>`;
  weiter.onclick = WEITER;
  leiste.append(weiter);

  const hinweis = document.createElement("div");
  hinweis.id = "hinweise";
  leiste.after(hinweis);

  abonnieren((live) => {
    leiste.classList.toggle("getrennt", !live);
    if (!live) {
      hinweis.innerHTML = `<div class="meldung rot">Verbindung zum Programm unterbrochen. Das Licht läuft weiter.</div>`;
      return;
    }
    for (const { id } of TASTEN) {
      document.getElementById("taste-" + id).classList.toggle("an", live.overrides[id]);
    }
    const haupt = live.pult.executoren[live.pult.haupt - 1];
    weiter.title = haupt.sequenz ? `Executor ${haupt.nummer}: ${haupt.sequenz}` : "Executor ohne Sequenz";
    const texte = [];
    if (live.blitzt) texte.push(["rot", "Strobo läuft"]);
    if (live.test_laeuft) texte.push(["gelb", "DMX-Test läuft: Die Automatik ruht, solange der Test läuft."]);
    if (live.strobo_erlaubt) texte.push(["gelb", "Dieses Profil erlaubt Strobo: Hinweisschild am Eingang aufhängen."]);
    if (live.hazer_erlaubt) texte.push(["gelb", "Hazer erlaubt: vorher mit dem Hausmeister klären (Brandmelder)."]);
    const inhalt = texte.map(([art, text]) => `<div class="meldung ${art}">${text}</div>`).join("") + updateHinweis(live);
    if (hinweis.dataset.inhalt !== inhalt) {
      hinweis.innerHTML = inhalt;
      hinweis.dataset.inhalt = inhalt;
    }
  });

  document.addEventListener("keydown", (ereignis) => {
    if (ereignis.target.closest("input, textarea, select") || ereignis.metaKey || ereignis.ctrlKey || ereignis.repeat) return;
    if (ereignis.key === " " || ereignis.key === "ArrowRight") {
      ereignis.preventDefault();
      if (!ereignis.target.closest("button")) WEITER();
      return;
    }
    if (ereignis.key === "ArrowLeft") {
      ereignis.preventDefault();
      ZURUECK();
      return;
    }
    const treffer = TASTEN.find(({ taste }) => taste === ereignis.key.toLowerCase());
    if (treffer) {
      ereignis.preventDefault();
      senden("/override/" + treffer.id);
    }
  });
}
