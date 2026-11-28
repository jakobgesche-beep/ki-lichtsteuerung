// Ansicht „Programmieren“: Geräte und Gruppen wählen, Werte geben (Dimmer, Position mit Kugel-Feld, Farbe,
// Gobo, Effekt mit Kurve), Encoder unten, Tastenfeld wie am grandMA mit Befehlszeile rechts.
// Speichern: Store drücken, dann einen Executor antippen (im Reiter Wing oder im Streifen unten).
import { befehl, stand, abonnieren } from "./verbindung.js";
import { el, t, tippen, erinnern, merken, meldung, FARBWERTE, FARBNAMEN } from "./hilfe.js";
import { effektEditor } from "./effekt.js";
import { buehne2d } from "./buehne2d.js";
import { zielWaehlen, zielEnde, zielGetroffen, ziel, eingabe, frage } from "./kontext.js";

const FEATURES = [["dimmer", "Dimmer"], ["position", "Position"], ["farbe", "Farbe"], ["gobo", "Gobo"], ["effekt", "Effekt"]];

function geraeteFarbe(id) {
  const g = (stand.z.buehne || []).find((x) => x.id === id);
  if (!g) return "#333";
  return `rgb(${g.farbe.map((f) => Math.round(30 + f * 225 * Math.max(0.2, g.hell))).join(",")})`;
}

// --- Encoder: waagerechtes Feld, Ziehen ändert den Wert relativ (wie Drehen am Encoder) -----------------
function encoder(titel, attribut, proPixel, einheit) {
  const wert = el("b.encoder-wert", {}, "–");
  const feld = el("div.encoder", {}, el("span.encoder-titel", {}, titel), wert, el("div.encoder-rillen"));
  let finger = null, letztesX = 0, offen = 0, uhr = null;
  const senden = () => {
    uhr = null;
    if (!offen) return;
    const delta = offen; offen = 0;
    befehl("encoder", { attribut, delta, fein: erinnern("fein", false) }, { still: true }).catch((e) => meldung(e.message, "fehler"));
  };
  feld.addEventListener("pointerdown", (e) => { finger = e.pointerId; letztesX = e.clientX; feld.setPointerCapture(e.pointerId); feld.classList.add("zieht"); });
  feld.addEventListener("pointermove", (e) => {
    if (e.pointerId !== finger) return;
    offen += (e.clientX - letztesX) * proPixel;
    letztesX = e.clientX;
    feld.querySelector(".encoder-rillen").style.backgroundPositionX = `${e.clientX}px`;
    if (!uhr) uhr = setTimeout(senden, 40);
  });
  const los = (e) => { if (e.pointerId === finger) { finger = null; feld.classList.remove("zieht"); senden(); } };
  for (const ereignis of ["pointerup", "pointercancel", "lostpointercapture"]) feld.addEventListener(ereignis, los);
  return { element: feld, zeigen(w) { wert.textContent = w === null || w === undefined ? "–" : `${Math.round(w * (einheit === "%" ? 100 : 1))}${einheit}`; } };
}

// --- XY-Feld wie die Kugel am Pult: relativ ziehen = Pan/Tilt der gewählten Köpfe -------------------------
function kugelFeld() {
  const punkt = el("div.kugel-punkt");
  const feld = el("div.kugel", {}, el("div.kugel-kreuz"), punkt, el("span.kugel-text", {}, "ziehen = Köpfe bewegen"));
  let finger = null, x0 = 0, y0 = 0, offenX = 0, offenY = 0, uhr = null;
  const senden = () => {
    uhr = null;
    if (!offenX && !offenY) return;
    const dx = Math.max(-90, Math.min(90, offenX)), dy = Math.max(-90, Math.min(90, offenY));
    offenX = 0; offenY = 0;
    befehl("xy", { dx, dy, fein: erinnern("fein", false) }, { still: true }).catch((e) => meldung(e.message, "fehler"));
  };
  feld.addEventListener("pointerdown", (e) => { finger = e.pointerId; x0 = e.clientX; y0 = e.clientY; feld.setPointerCapture(e.pointerId); feld.classList.add("zieht"); });
  feld.addEventListener("pointermove", (e) => {
    if (e.pointerId !== finger) return;
    offenX += (e.clientX - x0) * 0.35;
    offenY += (y0 - e.clientY) * 0.35;
    const r = feld.getBoundingClientRect();
    punkt.style.left = `${e.clientX - r.left}px`; punkt.style.top = `${e.clientY - r.top}px`;
    x0 = e.clientX; y0 = e.clientY;
    if (!uhr) uhr = setTimeout(senden, 40);
  });
  const los = (e) => { if (e.pointerId === finger) { finger = null; feld.classList.remove("zieht"); punkt.style.left = "50%"; punkt.style.top = "50%"; senden(); } };
  for (const ereignis of ["pointerup", "pointercancel", "lostpointercapture"]) feld.addEventListener(ereignis, los);
  return feld;
}

// --- Tastenfeld wie am Pult ------------------------------------------------------------------------------
function tastenfeld(zeile) {
  let puffer = "";
  const zeigen = (antwort = "") => { zeile.querySelector(".befehl-text").textContent = puffer || " "; if (antwort) zeile.querySelector(".befehl-antwort").textContent = antwort; };
  const dazu = (text) => { puffer = (puffer + text).replace(/\s+/g, " "); zeigen(); };
  const ausfuehren = async () => {
    const text = puffer.trim();
    if (!text) return;
    try {
      const e = await befehl("kommando", { text });
      puffer = ""; zeigen(e?.antwort || "OK");
    } catch (e) { zeigen(e.message); }
  };
  const zielTaste = (name, text, was, felder = () => ({})) => [name, async () => {
    zielWaehlen(text, async (nr) => {
      try {
        if (was === "label") { const n = await eingabe(`Executor ${nr} beschriften`); if (n === null) return; await befehl("label", { nr, text: n }); }
        else if (was === "frei") { if (!(await frage(`Executor ${nr} frei machen?`, "Die Sequenz bleibt gespeichert.", "Frei machen"))) return; await befehl("zuweisen", { nr, frei: true }); }
        else { const e = await befehl(was, { nr, ...felder() }); if (e?.sequenz) meldung(`Gespeichert auf Executor ${nr}: „${e.sequenz}“`, "ok"); }
      } catch {}
    });
  }];
  const knoepfe = [
    zielTaste("Store", "Store: Executor antippen (Wing oder Streifen unten)", "speichern"),
    zielTaste("Update", "Update: Executor mit laufendem Cue antippen", "update"),
    zielTaste("Label", "Label: Executor antippen", "label"),
    zielTaste("Delete", "Delete: Executor antippen (wird frei)", "frei"),
    ["Oops", () => befehl("oops").then((e) => meldung(e?.text || "Rückgängig", "ok")).catch(() => {})],
    ["Clear", () => befehl("leeren").catch(() => {})],
    ["Highlt", () => befehl("highlight", { an: !stand.z.prog?.highlight }).catch(() => {})],
    ["Blind", () => befehl("blind", { an: !stand.z.prog?.blind }).catch(() => {})],
    ["Fixture", () => dazu("Fixture ")], ["Group", () => dazu("Group ")], ["Sequ", () => dazu("Sequenz ")], ["Exec", () => dazu("Fader ")],
    ["7", () => dazu("7")], ["8", () => dazu("8")], ["9", () => dazu("9")], ["Thru", () => dazu(" Thru ")],
    ["4", () => dazu("4")], ["5", () => dazu("5")], ["6", () => dazu("6")], ["+", () => dazu(" + ")],
    ["1", () => dazu("1")], ["2", () => dazu("2")], ["3", () => dazu("3")], ["At", () => dazu(" At ")],
    ["0", () => dazu("0")], [".", () => dazu(".")], ["Full", () => dazu(" Full")], ["Esc", () => { puffer = ""; zielEnde(); zeigen(""); }],
    ["Please", ausfuehren],
  ];
  const feld = el("div.tastenfeld", {}, knoepfe.map(([name, aktion]) => tippen(el(`button.taste.pultkey${name === "Please" ? ".please" : ""}${["Store", "Update", "Label", "Delete"].includes(name) ? ".gelbtaste" : ""}`, { data: { taste: name } }, name), aktion)));
  return { feld, zeigen };
}

export function programmierenAnsicht(wurzel) {
  const fest = () => stand.fest || {};
  let feature = erinnern("feature", "dimmer");
  const gruppen = el("div.pool");
  const geraete = el("div.pool");
  const presets = el("div.pool");
  const featureReiter = el("div.feature-reiter");
  const featureInhalt = el("div.feature-inhalt");
  const streifen = el("div.ziel-streifen");
  const befehlsZeile = el("div.befehlszeile", {}, el("span.befehl-prompt", {}, "Befehl"), el("span.befehl-text", {}, " "), el("span.befehl-antwort"));
  const tasten = tastenfeld(befehlsZeile);
  const encoderListe = [encoder("Dimmer", "helligkeit", 0.003, "%"), encoder("Pan", "pan", 0.4, "°"), encoder("Tilt", "tilt", 0.4, "°")];
  const fein = tippen(el("button.taste.klein", {}, "Fein"), () => { merken("fein", !erinnern("fein", false)); fein.classList.toggle("an", erinnern("fein", false)); });
  fein.classList.toggle("an", erinnern("fein", false));
  let editor = null, buehne = null;

  function poolsBauen() {
    gruppen.replaceChildren(...(fest().gruppen || []).map((g) => tippen(el("button.kachel", { data: { gruppe: g } }, g), () => befehl("auswahl", { gruppe: g, art: "setzen" }).catch(() => {}))),
      tippen(el("button.kachel.leise", {}, "Alle"), () => befehl("auswahl", { geraete: (fest().geraete || []).filter((g) => g.dimmer || g.farbe).map((g) => g.id) }).catch(() => {})),
      tippen(el("button.kachel.leise", {}, "Keine"), () => befehl("auswahl", { geraete: [] }).catch(() => {})));
    geraete.replaceChildren(...(fest().geraete || []).filter((g) => g.dimmer || g.farbe || g.beweglich).map((g) =>
      tippen(el("button.kachel.geraet", { data: { id: g.id } }, el("i.lampe"), el("span", {}, g.name), el("small", {}, g.beweglich ? "Moving Head" : g.farbe ? "Farbe" : "")),
        () => befehl("auswahl", { geraete: [g.id], art: "umschalten" }).catch(() => {}))));
    presets.replaceChildren(...(fest().presets || []).map((p) => tippen(el("button.kachel.preset", {}, el("small", {}, p.art), p.name), () => befehl("preset", { nummer: p.nummer }).catch(() => {}))),
      tippen(el("button.kachel.leise", {}, "+ Preset"), async () => {
        const name = await eingabe("Preset speichern", "", "Speichert die Werte der gewählten Geräte für das gerade offene Feature (Dimmer, Position, Farbe, Gobo).");
        if (name) befehl("preset_speichern", { name, art: feature === "effekt" ? "farbe" : feature }).catch(() => {});
      }));
    auswahlZeigen();
  }
  function auswahlZeigen() {
    const auswahl = new Set(stand.z.prog?.auswahl || []);
    const imProgrammer = new Set(Object.keys(stand.z.prog?.werte || {}));
    for (const k of geraete.children) {
      k.classList.toggle("gewaehlt", auswahl.has(k.dataset.id));
      k.classList.toggle("programmer", imProgrammer.has(k.dataset.id));
      k.querySelector(".lampe").style.background = geraeteFarbe(k.dataset.id);
    }
    const erster = [...auswahl][0];
    const w = (stand.z.prog?.werte || {})[erster] || {};
    encoderListe[0].zeigen(w.helligkeit); encoderListe[1].zeigen(w.pan); encoderListe[2].zeigen(w.tilt);
    wurzel.querySelector(".prog-blind")?.classList.toggle("an", Boolean(stand.z.prog?.blind));
  }
  function streifenBauen() {
    const seite = erinnern("seite", 1), pro = fest().pro_seite || 10;
    streifen.replaceChildren(el("span.leise", {}, `Seite ${seite}:`), ...Array.from({ length: pro }, (_, i) => {
      const nr = (seite - 1) * pro + i + 1;
      const info = stand.z.exec[String(nr)] || {};
      return tippen(el(`button.streifen-exec${info.art ? "" : ".leer"}`, {}, el("b", {}, String(nr)), el("span", {}, info.label || info.name || "leer")), () => zielGetroffen(nr));
    }));
  }

  function featureZeigen() {
    merken("feature", feature);
    for (const b of featureReiter.children) b.classList.toggle("an", b.dataset.feature === feature);
    editor?.ende?.(); buehne?.ende?.(); editor = null; buehne = null;
    if (feature === "dimmer") {
      featureInhalt.replaceChildren(el("div.knopf-raster", {}, [0, 0.25, 0.5, 0.75, 1].map((w) =>
        tippen(el("button.taste.gross", {}, w === 1 ? "Voll" : w === 0 ? "Aus" : `${w * 100} %`), () => befehl("werte", { werte: { helligkeit: w } }).catch(() => {})))),
        el("p.leise", {}, "Feinstufig: Encoder „Dimmer“ unten waagerecht ziehen."));
    } else if (feature === "position") {
      buehne = buehne2d({ beiTipp: (x, y) => befehl("punkt", { x, y }).catch(() => {}) });
      buehne.aufbauSetzen(fest().aufbau);
      buehne.setzen(stand.z.buehne);
      featureInhalt.replaceChildren(el("div.position", {},
        el("div", {}, el("h3", {}, "Kugel"), kugelFeld(), el("div.zeile", {}, fein, tippen(el("button.taste.klein", {}, "Mitte"), () => befehl("werte", { werte: { pan: 0, tilt: 0 } }).catch(() => {})))),
        el("div", {}, el("h3", {}, "Punkt auf der Bühne antippen"), buehne.element),
        el("div", {}, el("h3", {}, "Positionen"), el("div.pool", {}, (fest().positionen || []).map((p) => tippen(el("button.kachel", {}, p), () => befehl("werte", { werte: { position: p } }).catch(() => {})))))));
    } else if (feature === "farbe") {
      const rad = el("input", { type: "color", value: "#ff0000" });
      rad.onchange = () => befehl("werte", { werte: { farbe: rad.value } }).catch(() => {});
      featureInhalt.replaceChildren(el("div.farb-raster", {}, Object.entries(FARBNAMEN).map(([id, name]) =>
        tippen(el("button.farb-kachel", { stil: { "--f": FARBWERTE[id] } }, el("i"), name), () => befehl("werte", { werte: { farbe: id } }).catch(() => {})))),
        el("label.zeile", {}, "Eigene Farbe ", rad), el("p.leise", {}, "Köpfe mit Farbrad nehmen die nächste Farbe auf ihrem Rad."));
    } else if (feature === "gobo") {
      const auswahl = new Set(stand.z.prog?.auswahl || []);
      const namen = [...new Set((fest().geraete || []).filter((g) => auswahl.has(g.id)).flatMap((g) => g.gobos || []))];
      featureInhalt.replaceChildren(el("div.pool", {}, ["Offen", ...namen].map((n) => tippen(el("button.kachel", {}, n), () => befehl("werte", { werte: { gobo: n } }).catch(() => {})))),
        el("div.zeile", {}, el("span", {}, "Drehen"), ...[-1, -0.4, 0, 0.4, 1].map((d) => tippen(el("button.taste.klein", {}, d === 0 ? "Stopp" : d > 0 ? (d === 1 ? "→→" : "→") : (d === -1 ? "←←" : "←")),
          () => befehl("werte", { werte: { gobo_drehung: d } }).catch(() => {})))),
        namen.length ? null : el("p.leise", {}, "Zuerst Moving Heads wählen: Dann stehen hier ihre Gobos."));
    } else {
      editor = effektEditor();
      featureInhalt.replaceChildren(editor.element);
    }
  }

  featureReiter.replaceChildren(...FEATURES.map(([id, name]) => tippen(el("button", { data: { feature: id } }, name), () => { feature = id; featureZeigen(); })));
  wurzel.replaceChildren(el("div.prog", {},
    el("section.fenster.prog-pools", {}, el("header", {}, "Gruppen"), gruppen, el("header", {}, "Geräte"), geraete, el("header", {}, "Presets"), presets),
    el("section.fenster.prog-mitte", {}, el("header.feature-kopf", {}, featureReiter,
      tippen(el("button.taste.klein.prog-blind", {}, "Blind"), () => befehl("blind", { an: !stand.z.prog?.blind }).catch(() => {}))), featureInhalt,
      el("div.encoder-leiste", {}, ...encoderListe.map((e) => e.element))),
    el("section.fenster.prog-tasten", {}, el("header", {}, "Tastenfeld"), tasten.feld),
    el("div.prog-unten", {}, befehlsZeile, streifen)));
  poolsBauen(); featureZeigen(); streifenBauen();

  const weg = abonnieren((s, teile) => {
    if (teile.includes("fest")) { poolsBauen(); featureZeigen(); }
    if (teile.includes("prog") || teile.includes("buehne")) auswahlZeigen();
    if (teile.includes("buehne") && buehne) buehne.setzen(s.z.buehne);
    if (teile.includes("exec")) streifenBauen();
  });
  return () => { weg(); editor?.ende?.(); buehne?.ende?.(); zielEnde(); };
}
