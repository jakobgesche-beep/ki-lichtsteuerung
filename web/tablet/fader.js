// Ein senkrechter Fader wie am Pult – für Executoren, Grand Master und Tempo.
// Relativ ziehen: Beim Antippen springt nichts, der Fader bewegt sich so weit wie der Finger.
// Mehrere Finger auf mehreren Fadern gleichzeitig gehen (jeder Fader merkt sich seinen eigenen Finger).
// Bewegt jemand am MacBook denselben Fader, fährt er hier sichtbar mit (wie ein Motorfader).
import { el } from "./hilfe.js";

const RUHE_MS = 400;     // so lange nach dem eigenen Ziehen gelten Werte vom MacBook nicht

export function fader({ wert = 0, beiAenderung = () => {}, art = "" } = {}) {
  const fuellung = el("div.fader-fuellung");
  const kappe = el("div.fader-kappe", {}, el("i"));
  const spur = el("div.fader-spur", {}, fuellung, ...[0.25, 0.5, 0.75].map((m) => el("b.fader-marke", { stil: { bottom: `${m * 100}%` } })), kappe);
  const anzeige = el("div.fader-wert");
  const element = el(`div.fader${art ? "." + art : ""}`, { role: "slider", "aria-valuemin": 0, "aria-valuemax": 100 }, spur, anzeige);
  let aktuell = wert, finger = null, startY = 0, startWert = 0, zuletztSelbst = -Infinity, aus = false;

  function zeichnen(neu, sanft = false) {
    aktuell = Math.max(0, Math.min(1, neu));
    element.classList.toggle("sanft", sanft);
    kappe.style.bottom = `calc(${aktuell * 100}% - ${aktuell * 34}px)`;
    fuellung.style.height = `${aktuell * 100}%`;
    anzeige.textContent = aktuell >= 0.995 ? "FL" : `${Math.round(aktuell * 100)}`;
    element.setAttribute("aria-valuenow", Math.round(aktuell * 100));
  }

  element.addEventListener("pointerdown", (e) => {
    if (aus || finger !== null) return;
    e.preventDefault();
    finger = e.pointerId;
    element.setPointerCapture(e.pointerId);
    startY = e.clientY;
    startWert = aktuell;
    element.classList.add("zieht");
  });
  element.addEventListener("pointermove", (e) => {
    if (e.pointerId !== finger) return;
    const hoehe = Math.max(40, spur.getBoundingClientRect().height - 34);
    zeichnen(startWert + (startY - e.clientY) / hoehe);
    zuletztSelbst = performance.now();
    beiAenderung(aktuell, false);
  });
  const loslassen = (e) => {
    if (e.pointerId !== finger) return;
    finger = null;
    element.classList.remove("zieht");
    zuletztSelbst = performance.now();
    beiAenderung(aktuell, true);
  };
  for (const ereignis of ["pointerup", "pointercancel", "lostpointercapture"]) element.addEventListener(ereignis, loslassen);
  zeichnen(wert);

  return {
    element,
    // Wert vom MacBook: nur übernehmen, wenn hier gerade niemand zieht
    setzen(neu) {
      if (finger !== null || performance.now() - zuletztSelbst < RUHE_MS) return;
      if (Math.abs(neu - aktuell) > 0.001) zeichnen(neu, true);
    },
    sperren(an) { aus = an; element.classList.toggle("gesperrt", an); },
    get wert() { return aktuell; },
  };
}
