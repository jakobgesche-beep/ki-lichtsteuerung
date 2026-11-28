// Gemeinsames für alle Ansichten: Ziel wählen (Store, Szene auf Fader legen …), Blätter (statt Pop-ups).
import { el, tippen } from "./hilfe.js";

const zielHoerer = new Set();
export const ziel = { aktiv: false, text: "", rueckruf: null };

// Ein Executor soll gewählt werden: Die Fader-Köpfe leuchten, der nächste Tipp darauf ruft `rueckruf(nr)`.
export function zielWaehlen(text, rueckruf) {
  Object.assign(ziel, { aktiv: true, text, rueckruf });
  for (const f of zielHoerer) f(ziel);
}
export function zielEnde() {
  Object.assign(ziel, { aktiv: false, text: "", rueckruf: null });
  for (const f of zielHoerer) f(ziel);
}
export function zielAbonnieren(f) { zielHoerer.add(f); return () => zielHoerer.delete(f); }
export function zielGetroffen(nr) {
  if (!ziel.aktiv) return false;
  const r = ziel.rueckruf;
  zielEnde();
  r?.(nr);
  return true;
}

// Ein Blatt von unten (statt confirm/prompt, die auf dem iPad stören). Gibt eine Funktion zum Schließen zurück.
export function blatt(titel, inhalt, knoepfe = [{ text: "Schließen" }]) {
  const schliessen = () => huelle.remove();
  const leiste = el("div.blatt-knoepfe", {}, knoepfe.map((k) => tippen(el(`button.taste${k.art ? "." + k.art : ""}`, {}, k.text), async () => {
    if (k.aktion) { const weiter = await k.aktion(); if (weiter === false) return; }
    schliessen();
  })));
  const fenster = el("div.blatt", {}, el("h2", {}, titel), inhalt, leiste);
  const huelle = el("div.blatt-huelle", {}, fenster);
  huelle.addEventListener("pointerdown", (e) => { if (e.target === huelle) schliessen(); });
  document.body.append(huelle);
  return schliessen;
}

export function frage(titel, text, jaText = "Ja", art = "warnung") {
  return new Promise((fertig) => {
    blatt(titel, el("p", {}, text), [{ text: "Abbrechen", aktion: () => fertig(false) }, { text: jaText, art, aktion: () => fertig(true) }]);
  });
}

export function eingabe(titel, wert = "", hinweis = "") {
  return new Promise((fertig) => {
    const feld = el("input.eingabe", { value: wert, maxlength: 40, autocomplete: "off", enterkeyhint: "done" });
    const zu = blatt(titel, el("div", {}, hinweis ? el("p.leise", {}, hinweis) : null, feld),
      [{ text: "Abbrechen", aktion: () => fertig(null) }, { text: "OK", art: "gruen", aktion: () => fertig(feld.value.trim()) }]);
    feld.addEventListener("keydown", (e) => { if (e.key === "Enter") { fertig(feld.value.trim()); zu(); } });
    setTimeout(() => feld.focus(), 50);
  });
}
