// DIP-Schalter (Binärcode) und Display-Schreibweise für eine DMX-Adresse.
// Gleiche Rechnung wie lichtsteuerung/adressierung.py: Schalter 1 zählt 1, Schalter 2 zählt 2, Schalter 3 zählt 4 …
// Adresse 28 = 16 + 8 + 4 → Schalter 5, 4 und 3 an. Wird am Mac (Patch, Gerät testen) und auf dem iPad benutzt.

export const STANDARD = {
  art: "unbekannt", dip: { anzahl: 9, adresse: 9, aus: [], an: [] }, display: "A{:03d}",
  hinweis: "Wie dieses Gerät eingestellt wird, steht in seinem Handbuch: entweder DIP-Schalter wie gezeigt oder am Display.",
};

function displayText(format, adresse) {
  if (!format) return null;
  return format.replace(/\{:0?(\d*)d\}|\{\}/g, (_, breite) => String(adresse).padStart(Number(breite || 0), "0"));
}

export function einstellen(adresse, info = STANDARD) {
  adresse = Math.max(0, Math.round(Number(adresse) || 0));
  const ergebnis = { adresse, art: info.art, dip: null, display: null, hinweis: info.hinweis || "", warnung: "" };
  const dip = info.dip;
  if (dip) {
    const schalter = [];
    for (let nr = 1; nr <= dip.anzahl; nr += 1) {
      if (nr <= dip.adresse) schalter.push({ nr, an: Boolean((adresse >> (nr - 1)) & 1), rolle: "adresse" });
      else schalter.push({ nr, an: (dip.an || []).includes(nr), rolle: "modus" });
    }
    const an = schalter.filter((s) => s.an && s.rolle === "adresse").map((s) => s.nr);
    if (adresse >= 2 ** dip.adresse) {
      ergebnis.warnung = `Adresse ${adresse} lässt sich mit ${dip.adresse} Adress-Schaltern nicht einstellen (höchstens ${2 ** dip.adresse - 1}).`;
    }
    const teile = [an.length ? `Schalter ${an.join(" + ")} an` : "alle Adress-Schalter aus"];
    if ((dip.aus || []).length) teile.push(`${dip.aus.join(", ")} aus`);
    if ((dip.an || []).length) teile.push(`${dip.an.join(", ")} an`);
    ergebnis.dip = { schalter, an, text: teile.join(", ") };
  }
  ergebnis.display = displayText(info.display, adresse);
  return ergebnis;
}

let stilDa = false;
function stil() {
  if (stilDa) return;
  stilDa = true;
  const s = document.createElement("style");
  s.textContent = `
  .dip-anzeige{display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;vertical-align:middle}
  .dip-reihe{display:inline-flex;gap:2px;padding:3px 4px;border-radius:4px;background:#b8141c}
  .dip-s{display:flex;flex-direction:column;align-items:center;gap:1px}
  .dip-s i{display:block;width:11px;height:20px;border-radius:2px;background:#f2f2f2;position:relative}
  .dip-s i::after{content:"";position:absolute;left:1px;right:1px;height:9px;border-radius:1px;background:#222;bottom:1px}
  .dip-s.an i::after{top:1px;bottom:auto}
  .dip-s b{font:600 9px/1 -apple-system,"Segoe UI",sans-serif;color:#fff}
  .dip-s.modus i{background:#ffd9a8}
  .dip-text{font-size:12px;color:var(--text,#ddd)}
  .dip-display{font:700 13px ui-monospace,Menlo,monospace;color:#ff5a4a;background:#140404;border:1px solid #3a1010;
    padding:2px 6px;border-radius:3px;letter-spacing:1px}
  .dip-warnung{color:#ff6b5a;font-size:12px}
  .dip-anzeige.gross .dip-s i{width:16px;height:30px}.dip-anzeige.gross .dip-s i::after{height:13px}
  .dip-anzeige.gross .dip-s b{font-size:11px}.dip-anzeige.gross .dip-text{font-size:15px}`;
  document.head.append(s);
}

function t(text) {
  return String(text ?? "").replace(/[&<>"]/g, (z) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[z]));
}

// HTML für die Anzeige. Optionen: gross (iPad), ohneText (nur Schalter), ohneHinweis.
export function dipHtml(adresse, info = STANDARD, { gross = false, ohneText = false, ohneHinweis = true } = {}) {
  stil();
  const e = einstellen(adresse, info || STANDARD);
  const teile = [];
  if (e.dip) {
    const schalter = e.dip.schalter.map((s) => `<span class="dip-s ${s.an ? "an" : ""} ${s.rolle === "modus" ? "modus" : ""}"
      title="Schalter ${s.nr}: ${s.an ? "AN (oben)" : "aus (unten)"}${s.rolle === "modus" ? " – Modus" : ` – zählt ${2 ** (s.nr - 1)}`}"><i></i><b>${s.nr}</b></span>`).join("");
    teile.push(`<span class="dip-reihe" aria-label="DIP: ${t(e.dip.text)}">${schalter}</span>`);
    if (!ohneText) teile.push(`<span class="dip-text">${t(e.dip.text)}</span>`);
  }
  if (e.display) teile.push(`<span class="dip-display" title="So steht die Adresse auf dem Display">${t(e.display)}</span>`);
  if (e.warnung) teile.push(`<span class="dip-warnung">${t(e.warnung)}</span>`);
  if (!ohneHinweis && e.hinweis) teile.push(`<span class="dip-text">${t(e.hinweis)}</span>`);
  return `<span class="dip-anzeige ${gross ? "gross" : ""}">${teile.join("")}</span>`;
}
