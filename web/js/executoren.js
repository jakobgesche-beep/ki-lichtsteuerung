// Die Fader-Leiste wie an einem großen Pult: 10 Fader pro Seite, rechts Seiten und Grand Master.
//   Sequenz          Go+, Go−, Flash (solange gedrückt), Aus. Fader hoch startet, ganz runter schaltet aus.
//   Gruppen-Master   Fader = Helligkeit der Gruppe. Flash: voll. Aus: dunkel (nochmal: wieder an).
//   Tempo            Fader = Tempo aller Effekte (Mitte normal). Learn: im Takt tippen. 1×: zurück.
// Die Fader sind selbst gebaut (kein Browser-Schieberegler): So sehen sie auf Mac und Windows gleich aus.
import { senden, t } from "./api.js";

const ART_KURZ = { sequenz: "SEQ", gruppe: "GRP", tempo: "TEMPO" };

function prozent(wert) {
  return Math.round(wert * 100);
}

function faktorText(faktor) {
  if (!faktor) return "";
  if (Math.abs(faktor - 1) < 0.01) return "1×";
  if (faktor < 1) return `1/${Math.round(1 / faktor * 10) / 10}×`;
  return `${Math.round(faktor * 10) / 10}×`;
}

// Ein senkrechter Fader. Meldet Werte gedrosselt (alle 40 ms) und den letzten beim Loslassen.
export function senkrechterRegler(element, melden) {
  let ziehen = false;
  let wert = 0;
  let zuletzt = 0;
  let wartet = null;
  const fuellung = element.querySelector(".regler-fuellung");
  const griff = element.querySelector(".regler-griff");

  function zeichnen(neu) {
    wert = Math.max(0, Math.min(1, neu));
    fuellung.style.height = `${wert * 100}%`;
    griff.style.bottom = `calc(${wert * 100}% - 7px)`;
    element.setAttribute("aria-valuenow", String(prozent(wert)));
  }
  function schicken(sofort = false) {
    const jetzt = performance.now();
    clearTimeout(wartet);
    if (sofort || jetzt - zuletzt > 40) {
      zuletzt = jetzt;
      melden(wert);
    } else {
      wartet = setTimeout(() => schicken(true), 45);
    }
  }
  function ausZeiger(ereignis) {
    const rahmen = element.getBoundingClientRect();
    return 1 - (ereignis.clientY - rahmen.top - 7) / Math.max(1, rahmen.height - 14);
  }
  element.addEventListener("pointerdown", (ereignis) => {
    ziehen = true;
    element.setPointerCapture(ereignis.pointerId);
    element.classList.add("zieht");
    zeichnen(ausZeiger(ereignis));
    schicken();
    ereignis.preventDefault();
  });
  element.addEventListener("pointermove", (ereignis) => {
    if (!ziehen) return;
    zeichnen(ausZeiger(ereignis));
    schicken();
  });
  const loslassen = () => {
    if (!ziehen) return;
    ziehen = false;
    element.classList.remove("zieht");
    schicken(true);
  };
  element.addEventListener("pointerup", loslassen);
  element.addEventListener("pointercancel", loslassen);
  element.addEventListener("lostpointercapture", loslassen);
  element.addEventListener("wheel", (ereignis) => {
    ereignis.preventDefault();
    zeichnen(wert + (ereignis.deltaY < 0 ? 0.05 : -0.05));
    schicken();
  }, { passive: false });
  element.addEventListener("keydown", (ereignis) => {
    const schritte = { ArrowUp: 0.05, ArrowDown: -0.05, PageUp: 0.25, PageDown: -0.25, Home: 1, End: -1 };
    if (!(ereignis.key in schritte)) return;
    ereignis.preventDefault();
    ereignis.stopPropagation();
    zeichnen(wert + schritte[ereignis.key]);
    schicken(true);
  });
  return {
    setzen(neu) { if (!ziehen) zeichnen(neu); },
    get zieht() { return ziehen; },
  };
}

function reglerHtml(nummer) {
  return `<div class="regler" data-regler="${nummer}" tabindex="0" role="slider" aria-valuemin="0" aria-valuemax="100">
    <div class="regler-spur"></div><div class="regler-fuellung"></div><div class="regler-griff"></div></div>`;
}

// zielWahl(nummer) darf einen Klick auf einen Fader "abfangen" (Store/Assign/... im Pult-Tab).
export function executorLeiste(huelle, { zielWahl = null, seiteFest = null } = {}) {
  huelle.classList.add("faderleiste");
  huelle.innerHTML = `<div class="fader-reihe"></div>
    <div class="fader-rechts">
      <div class="seiten"></div>
      <div class="grand"><div class="ex-kopf"><span class="ex-name">Grand</span></div>
        ${reglerHtml("grand")}<div class="ex-wert" data-grand-wert>100</div></div>
    </div>`;
  const reihe = huelle.querySelector(".fader-reihe");
  const seiten = huelle.querySelector(".seiten");
  const regler = new Map();
  let seite = null;
  let stand = "";
  let pultStand = null;

  const grandRegler = senkrechterRegler(huelle.querySelector('[data-regler="grand"]'),
    (wert) => senden("/grand", { wert }).catch(() => {}));

  function aufbauen(pult) {
    const von = (seite - 1) * pult.pro_seite;
    reihe.innerHTML = pult.executoren.slice(von, von + pult.pro_seite).map((e) => `
      <div class="ex" data-ex="${e.nummer}">
        <div class="ex-kopf" data-ziel="${e.nummer}"><span class="ex-nr">${e.nummer}</span><span class="ex-name"></span><span class="ex-art"></span></div>
        <div class="ex-cue"></div>
        <div class="ex-next"></div>
        <div class="ex-mitte">${reglerHtml(e.nummer)}<div class="ex-wert"></div></div>
        <div class="ex-tasten">
          <button data-taste="go" data-nr="${e.nummer}">Go+</button>
          <button data-taste="zurueck" data-nr="${e.nummer}">Go−</button>
          <button data-taste="flash" data-nr="${e.nummer}" class="flash">Flash</button>
          <button data-taste="aus" data-nr="${e.nummer}">Aus</button>
        </div>
      </div>`).join("");
    regler.clear();
    reihe.querySelectorAll(".regler").forEach((element) => {
      const nummer = Number(element.dataset.regler);
      regler.set(nummer, senkrechterRegler(element, (wert) =>
        senden(`/executor/${nummer}/fader`, { wert }).catch(() => {})));
    });
    seiten.innerHTML = Array.from({ length: pult.seiten }, (_, i) =>
      `<button data-seite="${i + 1}" class="${i + 1 === seite ? "an" : ""}">Seite ${i + 1}</button>`).join("");
  }

  function streifen(e, pult) {
    const element = reihe.querySelector(`[data-ex="${e.nummer}"]`);
    if (!element) return;
    const sig = JSON.stringify([e.art, e.name, e.index, e.anzahl, e.cue, e.naechster, e.flash, e.stumm, e.song,
      e.faktor, pult.haupt === e.nummer]);
    if (element.dataset.sig !== sig) {
      element.dataset.sig = sig;
      element.className = `ex ${e.art ? "art-" + e.art : "frei"} ${e.index >= 0 ? "laeuft" : ""} ${pult.haupt === e.nummer ? "haupt" : ""} ${e.stumm ? "stumm" : ""}`;
      element.querySelector(".ex-name").textContent = e.name || "frei";
      element.querySelector(".ex-art").textContent = ART_KURZ[e.art] ?? "";
      let cue = "";
      let next = "";
      if (e.art === "sequenz") {
        cue = e.index >= 0 ? `${e.index + 1}/${e.anzahl} ${e.cue ?? ""}` : `aus · ${e.anzahl} Cues`;
        next = e.naechster ? `▸ ${e.naechster}` : "";
      } else if (e.art === "gruppe") {
        cue = e.stumm ? "Gruppe aus" : "Helligkeit";
      } else if (e.art === "tempo") {
        cue = "Tempo der Effekte";
      } else {
        cue = "Store oder Assign";
      }
      element.querySelector(".ex-cue").textContent = cue;
      element.querySelector(".ex-next").textContent = next;
      const [go, zurueck, flash, aus] = element.querySelectorAll(".ex-tasten button");
      const leer = !e.art;
      go.textContent = e.art === "tempo" ? "Learn" : e.art === "gruppe" ? "An" : "Go+";
      zurueck.textContent = e.art === "tempo" ? "" : "Go−";
      aus.textContent = e.art === "tempo" ? "1×" : e.art === "gruppe" ? (e.stumm ? "An" : "Aus") : "Aus";
      zurueck.hidden = e.art === "tempo" || e.art === "gruppe";
      go.hidden = e.art === "gruppe";
      flash.hidden = e.art === "tempo";
      [go, zurueck, flash, aus].forEach((knopf) => (knopf.disabled = leer));
      flash.classList.toggle("an", e.flash);
    }
    const wert = element.querySelector(".ex-wert");
    const text = e.art === "tempo" ? faktorText(e.faktor) : e.art ? String(prozent(e.fader)) : "";
    if (wert.textContent !== text) wert.textContent = text;
    regler.get(e.nummer)?.setzen(e.fader);
  }

  function zeigen(pult) {
    if (!pult) return;
    pultStand = pult;
    const neueSeite = seiteFest ?? pult.seite;
    if (neueSeite !== seite || stand !== `${pult.seiten}/${pult.pro_seite}`) {
      seite = neueSeite;
      stand = `${pult.seiten}/${pult.pro_seite}`;
      aufbauen(pult);
    }
    const von = (seite - 1) * pult.pro_seite;
    pult.executoren.slice(von, von + pult.pro_seite).forEach((e) => streifen(e, pult));
    grandRegler.setzen(pult.grand);
    const gw = huelle.querySelector("[data-grand-wert]");
    const gText = String(prozent(pult.grand));
    if (gw.textContent !== gText) gw.textContent = gText;
    huelle.querySelector(".grand").classList.toggle("warn", pult.grand < 0.999);
  }

  // Tasten: Flash nur solange gedrückt. Loslassen auch, wenn der Finger abrutscht oder das Fenster wechselt.
  let flashNummer = null;
  const flashLos = () => {
    if (flashNummer === null) return;
    senden(`/executor/${flashNummer}/flash`, { an: false }).catch(() => {});
    flashNummer = null;
  };
  huelle.addEventListener("pointerdown", (ereignis) => {
    const knopf = ereignis.target.closest("[data-taste]");
    if (!knopf || knopf.disabled) return;
    const nummer = Number(knopf.dataset.nr);
    if (zielWahl?.(nummer)) return;
    const taste = knopf.dataset.taste;
    if (taste === "flash") {
      knopf.setPointerCapture?.(ereignis.pointerId);
      flashNummer = nummer;
      senden(`/executor/${nummer}/flash`, { an: true }).catch(() => (flashNummer = null));
    } else {
      senden(`/executor/${nummer}/${taste}`).catch(() => {});
    }
  });
  huelle.addEventListener("pointerup", flashLos);
  huelle.addEventListener("pointercancel", flashLos);
  window.addEventListener("blur", flashLos);
  huelle.addEventListener("click", (ereignis) => {
    const seitenKnopf = ereignis.target.closest("[data-seite]");
    if (seitenKnopf) {
      senden("/pult/seite", { seite: Number(seitenKnopf.dataset.seite) }).then(zeigen).catch(() => {});
      return;
    }
    const ziel = ereignis.target.closest("[data-ziel], .ex-cue, .ex-next");
    const streifenElement = ereignis.target.closest("[data-ex]");
    if (ziel && streifenElement && !ereignis.target.closest("[data-taste]")) {
      const nummer = Number(streifenElement.dataset.ex);
      if (zielWahl?.(nummer)) return;
      if (pultStand?.executoren[nummer - 1]?.art === "sequenz") senden("/befehl", { text: `Fader ${nummer}` }).catch(() => {});
    }
  });

  return {
    zeigen,
    laden() {},              // früher: Sequenzen für die Auswahl; jetzt kommt alles über die Live-Daten
    abbauen() { window.removeEventListener("blur", flashLos); },
  };
}
