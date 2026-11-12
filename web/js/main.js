// Der Rahmen: Views oben wie am Pult, unter "Setup" die Einrichtungs-Seiten.
// Unten ist immer die Befehlszeile, oben immer die Not-Tasten.
import { showSeite } from "./show.js";
import { liveSeite } from "./live.js";
import { pultSeite } from "./pult.js";
import { probeSeite } from "./probe.js";
import { profileSeite } from "./profile.js";
import { patchSeite } from "./patch.js";
import { katalogSeite } from "./katalog.js";
import { dmxTestSeite } from "./dmxtest.js";
import { sicherungSeite } from "./sicherung.js";
import { midiSeite } from "./midi.js";
import { tastenLeiste } from "./tasten.js";
import { befehlszeile } from "./befehl.js";
import { abonnieren } from "./verbindung.js";

const views = [
  ["Show", showSeite],
  ["Pult", pultSeite],
  ["Live", liveSeite],
  ["Probe", probeSeite],
  ["Setup", null, [["Patch", patchSeite], ["Profile", profileSeite], ["Katalog", katalogSeite], ["DMX-Test", dmxTestSeite], ["MIDI", midiSeite], ["Sicherung", sicherungSeite]]],
];

const inhalt = document.getElementById("inhalt");
const reiter = document.getElementById("reiter");
const unterreiter = document.getElementById("unterreiter");
let aufraeumen = null;

function merken(schluessel, wert) {
  try { localStorage.setItem(schluessel, wert); } catch {}
}
function erinnern(schluessel) {
  try { return localStorage.getItem(schluessel); } catch { return null; }
}

function seiteZeigen(seite) {
  aufraeumen?.();
  inhalt.replaceChildren();
  aufraeumen = seite(inhalt);
}

function zeige(nummer, unter) {
  const [name, seite, unterseiten] = views[nummer];
  [...reiter.children].forEach((b, i) => b.classList.toggle("aktiv", i === nummer));
  merken("view", name);
  unterreiter.hidden = !unterseiten;
  if (!unterseiten) return seiteZeigen(seite);
  const start = Math.max(0, unterseiten.findIndex(([n]) => n === (unter ?? erinnern("setup"))));
  unterreiter.replaceChildren(...unterseiten.map(([n, s], i) => {
    const knopf = document.createElement("button");
    knopf.textContent = n;
    knopf.classList.toggle("aktiv", i === start);
    knopf.onclick = () => zeige(nummer, n);
    return knopf;
  }));
  merken("setup", unterseiten[start][0]);
  seiteZeigen(unterseiten[start][1]);
}

views.forEach(([name], nummer) => {
  const knopf = document.createElement("button");
  knopf.textContent = name;
  knopf.onclick = () => zeige(nummer);
  reiter.append(knopf);
});

tastenLeiste(document.getElementById("tasten"));
befehlszeile();

// Status oben rechts: DMX, Tempo, Profil
const status = document.getElementById("status");
abonnieren((live) => {
  if (!live) return (status.innerHTML = `<span class="chip warn">Keine Verbindung</span>`);
  const bpm = live.audio.werte ? Math.round(live.audio.werte.tempo_bpm) + " BPM" : "kein Ton";
  const inhalt_ = `
    ${live.dmx_ein && !live.dmx?.verbunden ? `<span class="chip warn" title="${live.dmx?.fehler ?? ""}">DMX: Enttec weg, sucht …</span>`
      : `<span class="chip ${live.dmx_ein ? "an" : ""}">DMX ${live.dmx_ein ? "an" : "aus"}</span>`}
    <span class="chip">${bpm}</span>
    <span class="chip">${live.automatik ? "Automatik" : "Automatik aus"}</span>
    <span class="chip ${live.pult.blind ? "warn" : ""}">${live.pult.blind ? "Blind" : "Programmer live"}</span>`;
  if (status.dataset.inhalt !== inhalt_) { status.innerHTML = inhalt_; status.dataset.inhalt = inhalt_; }
});

zeige(Math.max(0, views.findIndex(([n]) => n === erinnern("view"))));

// Fehler vom Programm zeigt api.js schon als Meldung an. Hier nicht noch einmal melden.
window.addEventListener("unhandledrejection", (ereignis) => ereignis.preventDefault());
