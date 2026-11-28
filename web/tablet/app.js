// Das iPad-Pult: Rahmen mit Kopfleiste (Verbindung, Ansichten, Musik), Master-Spalte rechts,
// Ansichten Wing / Programmieren / Show / Bühne / Setup, KI-Chat zum Hereinschieben.
// Ohne Kopplung zuerst der Koppel-Bildschirm (PIN vom MacBook).
import { verbinden, koppeln, token, stand, abonnieren, befehl } from "./verbindung.js";
import { el, t, tippen, erinnern, merken, meldung } from "./hilfe.js";
import { wingAnsicht } from "./wing.js";
import { masterSpalte } from "./master.js";
import { programmierenAnsicht } from "./programmieren.js";
import { showAnsicht } from "./show.js";
import { setupAnsicht, groesseAnwenden } from "./setup.js";
import { chatLeiste } from "./chat.js";
import { buehne2d } from "./buehne2d.js";

const ANSICHTEN = [["wing", "Wing", wingAnsicht], ["programmieren", "Programmieren", programmierenAnsicht],
  ["show", "Show", showAnsicht], ["buehne", "Bühne", buehneAnsicht], ["setup", "Setup", setupAnsicht]];

function buehneAnsicht(wurzel) {
  const b = buehne2d({ beiTipp: (x, y) => befehl("followspot", { x, y }).catch(() => {}) });
  wurzel.replaceChildren(el("section.fenster.buehne-gross", {}, el("header", {}, "Bühne live · antippen = Follow-Spot (Köpfe zeigen dorthin)",
    tippen(el("button.taste.klein", {}, "Follow-Spot aus"), () => { b.punktZeigen(null); befehl("followspot", { aus: true }).catch(() => {}); })), b.element));
  b.aufbauSetzen(stand.fest?.aufbau);
  b.setzen(stand.z.buehne);
  const weg = abonnieren((s, teile) => {
    if (teile.includes("fest")) b.aufbauSetzen(s.fest?.aufbau);
    if (teile.includes("buehne")) b.setzen(s.z.buehne);
  });
  return () => { weg(); b.ende(); };
}

function koppelBildschirm() {
  const pin = new URLSearchParams(location.search).get("pin") || "";
  const pinFeld = el("input.eingabe.pin", { inputmode: "numeric", maxlength: 6, placeholder: "123456", value: pin, autocomplete: "one-time-code" });
  const name = el("input.eingabe", { value: erinnern("name", "iPad Licht"), maxlength: 40 });
  const text = el("p.leise");
  const knopf = tippen(el("button.taste.gruen.gross", {}, "Koppeln"), async () => {
    try {
      merken("name", name.value);
      await koppeln(pinFeld.value.trim(), name.value.trim());
      history.replaceState(null, "", "/pult/");
      start();
    } catch (e) { text.textContent = e.message; }
  });
  document.body.replaceChildren(el("main.koppeln", {},
    el("h1", {}, "Lichtpult koppeln"),
    el("p", {}, "Am MacBook in der Lichtsteuerung: Setup → iPad → „iPad koppeln“. Dort steht die PIN (5 Minuten gültig)."),
    el("label", {}, "PIN vom MacBook", pinFeld), el("label", {}, "Name dieses iPads", name), knopf, text,
    el("div.anleitung", {}, el("h2", {}, "Danach einmalig"),
      el("ol", {}, el("li", {}, "In Safari unten auf Teilen (□↑) → „Zum Home-Bildschirm“. Ab dann das Lichtpult über das neue Symbol öffnen."),
        el("li", {}, "Einstellungen → Anzeige & Helligkeit → Automatische Sperre → „Nie“."),
        el("li", {}, "Einstellungen → Multitasking & Gesten → Gesten aus (sonst wechseln 4 Finger auf 4 Fadern die App)."),
        el("li", {}, "Am Abend: Bedienungshilfen → Geführter Zugriff (dreimal Seitentaste), dann bleibt das Pult vorne.")))));
  if (pin) setTimeout(() => pinFeld.focus(), 100);
}

function kopfleiste(wechseln) {
  const verbindungPunkt = el("span.punkt", { title: "Verbindung zum MacBook" });
  const internetPunkt = el("span.punkt.klein", { title: "Internet (für den KI-Chat)" });
  const reiter = el("nav.reiter", {}, ANSICHTEN.map(([id, name]) => tippen(el("button", { data: { ansicht: id } }, name), () => wechseln(id))));
  const modus = el("div.modus", {}, ...[["automatik", "Automatik"], ["selbst", "Selbst"]].map(([id, name]) =>
    tippen(el("button", { data: { modus: id } }, name), () => befehl("automatik", { an: id === "automatik" }).catch(() => {}))));
  const bpm = el("span.bpm", {}, "– BPM");
  const beat = el("span.beat-led");
  const eins = el("span.beat-led.eins");
  const stufe = el("span.stufe", {}, el("i"), el("i"), el("i"));
  const lage = el("span.lage");
  const dmx = el("span.chip");
  const uhr = el("span.uhr");
  const kopf = el("header.kopf", {}, el("div.kopf-links", {}, verbindungPunkt, internetPunkt, el("b.marke", {}, "Lichtpult")), reiter,
    el("div.kopf-musik", {}, beat, eins, bpm, stufe, lage), modus, dmx, uhr);
  let letzterBeat = 0, letzteEins = 0;
  setInterval(() => { uhr.textContent = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }); }, 1000);
  abonnieren((s, teile) => {
    verbindungPunkt.classList.toggle("an", s.verbunden);
    verbindungPunkt.title = s.verbunden ? `Verbunden (${s.rtt ?? "?"} ms)` : "Keine Verbindung";
    const internet = s.z.netz?.internet;
    internetPunkt.classList.toggle("an", internet === true);
    internetPunkt.classList.toggle("aus", internet === false);
    if (teile.includes("musik")) {
      const m = s.z.musik || {};
      bpm.textContent = m.bpm ? `${Math.round(m.bpm)} BPM` : "– BPM";
      if (m.beats !== letzterBeat) { letzterBeat = m.beats; beat.classList.remove("blitz"); void beat.offsetWidth; beat.classList.add("blitz"); }
      if (m.eins !== letzteEins) { letzteEins = m.eins; eins.classList.remove("blitz"); void eins.offsetWidth; eins.classList.add("blitz"); }
      [...stufe.children].forEach((i, n) => i.classList.toggle("an", (m.stufe ?? 0) > n));
      const text = m.ton === "weg" ? "TON WEG" : m.ton === "aus" ? "kein Ton" : m.rede ? "REDE" : m.applaus ? "APPLAUS" : m.drop ? "DROP" : m.leise ? "leise" : (m.look || "");
      lage.textContent = text;
      lage.className = `lage ${m.ton === "weg" ? "rot" : m.rede || m.applaus ? "gelb" : m.drop ? "rot" : ""}`;
    }
    if (teile.includes("show")) for (const b of modus.children) b.classList.toggle("an", (b.dataset.modus === "automatik") === Boolean(s.z.show?.automatik));
    if (teile.includes("dmx")) {
      const d = s.z.dmx || {};
      dmx.textContent = d.an ? (d.verbunden ? "DMX an" : "DMX: Enttec weg!") : "DMX aus";
      dmx.className = `chip ${d.an ? (d.verbunden ? "an" : "rot") : "warn"}`;
    }
  });
  return { element: kopf, aktiv: (id) => { for (const b of reiter.children) b.classList.toggle("an", b.dataset.ansicht === id); } };
}

function start() {
  groesseAnwenden(erinnern("groesse", "auto"));
  const inhalt = el("div.inhalt");
  const master = el("aside.master-huelle");
  const chat = el("aside.chat-huelle");
  const banner = el("div.banner", {}, "Keine Verbindung zum MacBook – das Licht läuft dort weiter. Verbinde neu …");
  const quer = el("div.quer-hinweis", {}, "Bitte das iPad quer halten.");
  let aufraeumen = null;
  const kopf = kopfleiste(wechseln);
  function wechseln(id) {
    const eintrag = ANSICHTEN.find(([i]) => i === id) || ANSICHTEN[0];
    aufraeumen?.();
    inhalt.replaceChildren();
    merken("ansicht", eintrag[0]);
    kopf.aktiv(eintrag[0]);
    aufraeumen = eintrag[2](inhalt);
  }
  const chatSteuerung = chatLeiste(chat);
  document.body.replaceChildren(el("div.rahmen", {}, kopf.element, el("div.mitte", {}, inhalt, master), banner),
    chat, el("div.toasts", { id: "toasts" }), quer);
  masterSpalte(master, { chatOeffnen: () => chatSteuerung.oeffnen() });
  wechseln(erinnern("ansicht", "wing"));
  abonnieren((s, teile) => {
    if (teile.includes("verbunden")) document.body.classList.toggle("getrennt", !s.verbunden);
    if (teile.includes("meld")) for (const text of s.z.meld || []) meldung(text, "hinweis");
  });
  document.body.classList.add("getrennt");
  verbinden();
}

// Zoomen, Lupe und Kontextmenü aus: Das ist ein Pult, keine Webseite.
for (const art of ["gesturestart", "gesturechange", "contextmenu"]) document.addEventListener(art, (e) => e.preventDefault());
document.addEventListener("dblclick", (e) => e.preventDefault(), { passive: false });

if (token()) start(); else koppelBildschirm();
