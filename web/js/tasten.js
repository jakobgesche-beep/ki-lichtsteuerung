// Die festen Tasten für den Abend: immer sichtbar, groß, auch auf der Tastatur.
import { senden } from "./api.js";
import { abonnieren } from "./verbindung.js";

const TASTEN = [
  { id: "blackout", text: "Blackout", taste: "b" },
  { id: "warmweiss", text: "Warmweiß / Rede", taste: "w" },
  { id: "pause", text: "Automatik Pause", taste: "p" },
  { id: "strobo_aus", text: "Strobo aus", taste: "s" },
];

export function tastenLeiste(leiste) {
  for (const { id, text, taste } of TASTEN) {
    const knopf = document.createElement("button");
    knopf.id = "taste-" + id;
    knopf.innerHTML = `${text} <kbd>${taste.toUpperCase()}</kbd>`;
    knopf.onclick = () => senden("/override/" + id);
    leiste.append(knopf);
  }
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
    const texte = [];
    if (live.blitzt) texte.push(["rot", "Strobo läuft"]);
    if (live.strobo_erlaubt) texte.push(["gelb", "Dieses Profil erlaubt Strobo: Hinweisschild am Eingang aufhängen."]);
    if (live.hazer_erlaubt) texte.push(["gelb", "Hazer erlaubt: vorher mit dem Hausmeister klären (Brandmelder)."]);
    const inhalt = texte.map(([art, text]) => `<div class="meldung ${art}">${text}</div>`).join("");
    if (hinweis.dataset.inhalt !== inhalt) {
      hinweis.innerHTML = inhalt;
      hinweis.dataset.inhalt = inhalt;
    }
  });

  document.addEventListener("keydown", (ereignis) => {
    if (ereignis.target.closest("input, textarea, select") || ereignis.metaKey || ereignis.ctrlKey || ereignis.repeat) return;
    const treffer = TASTEN.find(({ taste }) => taste === ereignis.key.toLowerCase());
    if (treffer) {
      ereignis.preventDefault();
      senden("/override/" + treffer.id);
    }
  });
}
