// Ansicht „Wing“: 10 Executoren pro Seite wie am grandMA (Kopf, Taste oben, Fader, zwei Tasten unten),
// darüber die Bühne live, die Cue-Liste des gewählten Executors und die Look-Tasten.
import { befehl, faderSenden, stand, abonnieren } from "./verbindung.js";
import { el, t, tippen, halten, langDruecken, erinnern, merken, meldung } from "./hilfe.js";
import { fader } from "./fader.js";
import { buehne2d } from "./buehne2d.js";
import { ziel, zielAbonnieren, zielGetroffen, blatt, eingabe, frage } from "./kontext.js";

const TASTE_TEXT = { go: "GO+", zurueck: "GO−", toggle: "AN / AUS", flash: "FLASH", aus: "AUS" };
const ART_FARBE = { sequenz: "#3f7fc0", gruppe: "#c9a227", tempo: "#9b6bd6" };

function executorSpalte(nr) {
  const kopfName = el("div.exec-name");
  const kopfCue = el("div.exec-cue");
  const balken = el("div.exec-blende", {}, el("i"));
  const kopf = el("div.exec-kopf", {}, el("span.exec-nr", {}, String(nr)), el("span.exec-led"), kopfName, kopfCue, balken);
  const tasten = { oben: el("button.taste.exec-taste"), mitte: el("button.taste.exec-taste"), unten: el("button.taste.exec-taste") };
  const f = fader({ beiAenderung: (wert) => faderSenden(nr, wert) });
  const spalte = el("div.exec", { data: { nr } }, kopf, tasten.oben, f.element, tasten.mitte, tasten.unten);
  let info = null;

  function tasteDruecken(platz, an = true) {
    if (!info || !info.art) return;
    const art = info.tasten?.[platz];
    if (art === "flash") return befehl("taste", { nr, taste: "flash", an }).catch(() => {});
    if (!an) return;
    if (art === "toggle") return befehl("taste", { nr, taste: "toggle", erwartet: !info.laeuft }).catch(() => {});
    return befehl("taste", { nr, taste: art }).catch(() => {});
  }
  for (const platz of ["oben", "mitte", "unten"]) {
    const knopf = tasten[platz];
    halten(knopf, () => {
      if (zielGetroffen(nr)) return;
      if (!info?.art) return leerAntippen();
      tasteDruecken(platz, true);
    }, () => { if (info?.tasten?.[platz] === "flash") tasteDruecken(platz, false); });
  }

  function leerAntippen() {
    zuweisenBlatt(nr);
  }

  tippen(kopf, () => {
    if (zielGetroffen(nr)) return;
    if (!info?.art) return leerAntippen();
    befehl("haupt_waehlen", { nr }, { still: true }).catch(() => {});
  });
  langDruecken(kopf, () => { if (info?.art) einstellungenBlatt(nr, info); else zuweisenBlatt(nr); });

  function aktualisieren(neu) {
    info = neu;
    const leer = !neu || !neu.art;
    spalte.classList.toggle("leer", leer);
    spalte.classList.toggle("laeuft", Boolean(neu?.laeuft) && !leer);
    spalte.classList.toggle("flash", Boolean(neu?.flash));
    spalte.classList.toggle("fader-null", !leer && neu.laeuft && neu.fader <= 0.02);
    spalte.style.setProperty("--exec-farbe", neu?.farbe || ART_FARBE[neu?.art] || "#3a3d42");
    kopfName.textContent = leer ? "leer" : (neu.label || neu.name || neu.sequenz || neu.gruppe || "Tempo");
    kopfCue.textContent = leer ? "" : neu.art === "sequenz"
      ? (neu.index >= 0 ? `${neu.index + 1}/${neu.anzahl} ${neu.cue || ""}` : `${neu.anzahl} Cue${neu.anzahl === 1 ? "" : "s"}`)
      : neu.art === "gruppe" ? `Gruppe${neu.stumm ? " · aus" : ""}` : `Tempo ×${neu.faktor ?? 1}`;
    balken.firstChild.style.width = `${Math.round((neu?.blende ?? 0) * 100)}%`;
    balken.hidden = !(neu?.laeuft && neu?.art === "sequenz" && (neu.blende ?? 1) < 1);
    for (const platz of ["oben", "mitte", "unten"]) {
      const art = neu?.tasten?.[platz];
      tasten[platz].textContent = leer ? "" : neu.art === "tempo" && art !== "aus" ? "TAP" : (TASTE_TEXT[art] || "");
      tasten[platz].classList.toggle("an", !leer && ((art === "toggle" && neu.laeuft) || (art === "flash" && neu.flash)));
      tasten[platz].disabled = leer;
    }
    f.sperren(leer);
    if (!leer) f.setzen(neu.fader);
  }
  return { element: spalte, aktualisieren, nr };
}

export async function zuweisenBlatt(nr) {
  const fest = stand.fest || {};
  const liste = el("div.auswahl-liste");
  const zu = blatt(`Executor ${nr} belegen`, el("div", {},
    el("p.leise", {}, "Was soll auf diesen Fader? Neue Szenen baust du im KI-Chat oder im Reiter „Programmieren“ (Store)."),
    el("h3", {}, "Sequenzen"), liste,
    el("h3", {}, "Gruppen-Master (Fader regelt die Helligkeit einer Gruppe)"),
    el("div.auswahl-liste", {}, (fest.gruppen || []).map((g) => tippen(el("button.taste.klein", {}, g), () => { befehl("zuweisen", { nr, gruppe: g }).then(() => zu()).catch(() => {}); }))),
    el("h3", {}, "Sonstiges"),
    el("div.auswahl-liste", {}, tippen(el("button.taste.klein", {}, "Tempo-Fader"), () => { befehl("zuweisen", { nr, art: "tempo" }).then(() => zu()).catch(() => {}); }))));
  for (const name of fest.sequenzen || []) {
    liste.append(tippen(el("button.taste.klein", {}, name), () => { befehl("zuweisen", { nr, sequenz: name }).then(() => zu()).catch(() => {}); }));
  }
}

function einstellungenBlatt(nr, info) {
  const fest = stand.fest || {};
  const farben = el("div.farb-reihe", {}, (fest.exec_farben || []).map((f) => tippen(el("button.farb-knopf", { stil: { background: f }, "aria-label": f }), () => befehl("exec_farbe", { nr, farbe: f }).catch(() => {}))),
    tippen(el("button.taste.klein", {}, "Standard"), () => befehl("exec_farbe", { nr, farbe: null }).catch(() => {})));
  const wahl = (platz) => {
    const auswahl = el("select.eingabe", {}, Object.entries(fest.tasten_arten || {}).map(([art, text]) => el("option", { value: art, selected: info.tasten?.[platz] === art }, text)));
    auswahl.onchange = () => befehl("tasten", { nr, tasten: { ...info.tasten, [platz]: auswahl.value } }).catch(() => {});
    return el("label.zeile", {}, el("span", {}, platz === "oben" ? "Taste oben" : platz === "mitte" ? "Taste Mitte" : "Taste unten"), auswahl);
  };
  blatt(`Executor ${nr}: ${info.label || info.name || ""}`, el("div", {},
    el("h3", {}, "Name"),
    tippen(el("button.taste.klein", {}, "Umbenennen …"), async () => { const n = await eingabe("Neuer Name", info.label || info.name || ""); if (n !== null) befehl("label", { nr, text: n }).catch(() => {}); }),
    el("h3", {}, "Farbe"), farben,
    el("h3", {}, "Tasten"), wahl("oben"), wahl("mitte"), wahl("unten"),
    el("h3", {}, "Belegung"),
    el("div.auswahl-liste", {},
      tippen(el("button.taste.klein", {}, "Anders belegen …"), () => zuweisenBlatt(nr)),
      tippen(el("button.taste.klein.warnung", {}, "Fader frei machen"), async () => { if (await frage("Fader frei machen?", "Die Sequenz bleibt gespeichert, sie liegt nur nicht mehr auf diesem Fader.", "Frei machen")) befehl("zuweisen", { nr, frei: true }).catch(() => {}); }))));
}

export function wingAnsicht(wurzel) {
  const fest = () => stand.fest || {};
  let seite = erinnern("seite", 1);
  const spalten = [];
  const reihe = el("div.exec-reihe");
  const seitenLeiste = el("div.seiten");
  const buehne = buehne2d();
  const cueListe = el("div.cue-liste");
  const hauptTitel = el("div.haupt-titel");
  const looks = el("div.look-raster");
  const zielSchild = el("div.ziel-schild", { hidden: true });

  function seitenZeigen() {
    seitenLeiste.replaceChildren(el("div.seiten-titel", {}, "Seite"), ...Array.from({ length: fest().seiten || 4 }, (_, i) =>
      tippen(el(`button.taste.seite${i + 1 === seite ? ".an" : ""}`, {}, String(i + 1)), () => { seite = i + 1; merken("seite", seite); bauen(); })));
  }
  function bauen() {
    seitenZeigen();
    reihe.replaceChildren();
    spalten.length = 0;
    const pro = fest().pro_seite || 10;
    for (let i = 1; i <= pro; i += 1) {
      const s = executorSpalte((seite - 1) * pro + i);
      spalten.push(s);
      reihe.append(s.element);
      s.aktualisieren(stand.z.exec[String(s.nr)]);
    }
  }
  function looksBauen() {
    looks.replaceChildren(...(fest().looks || []).map((l) => tippen(el("button.taste.look", { data: { look: l.id } }, el("b", {}, l.taste || ""), el("span", {}, l.name)),
      () => befehl("look", { id: stand.z.show?.look === l.id ? "aus" : l.id }).catch(() => {}))));
  }
  function oben() {
    const m = stand.z.master || {};
    const haupt = stand.z.exec[String(m.haupt)] || {};
    hauptTitel.innerHTML = `<b>${t(m.haupt || "")}</b> ${t(haupt.label || haupt.name || "–")}`;
    cueListe.replaceChildren(...(m.haupt_cues || []).map((name, i) => tippen(el(`button.cue${i === m.haupt_index ? ".aktiv" : ""}`, {}, el("b", {}, String(i + 1)), name),
      () => befehl("goto", { nr: m.haupt, index: i }).catch(() => {}))));
    for (const knopf of looks.children) knopf.classList.toggle("an", knopf.dataset.look === stand.z.show?.look);
  }

  wurzel.replaceChildren(el("div.wing", {},
    el("div.wing-oben", {}, el("section.fenster.wing-buehne", {}, el("header", {}, "Bühne live"), buehne.element),
      el("section.fenster.wing-cues", {}, el("header", {}, hauptTitel, el("span.leise", {}, "Tipp = Goto")), cueListe),
      el("section.fenster.wing-looks", {}, el("header", {}, "Looks"), looks)),
    el("div.wing-unten", {}, seitenLeiste, reihe), zielSchild));
  bauen();
  looksBauen();
  buehne.aufbauSetzen(fest().aufbau);
  oben();

  const weg1 = abonnieren((s, teile) => {
    if (teile.includes("fest")) { bauen(); looksBauen(); buehne.aufbauSetzen(fest().aufbau); }
    if (teile.includes("exec")) for (const sp of spalten) sp.aktualisieren(s.z.exec[String(sp.nr)]);
    if (teile.includes("buehne") || teile.includes("vorschau")) buehne.setzen(s.z.buehne, s.z.vorschau, s.z.chat?.entwurf && erinnern("vorschau-zeigen", true));
    if (teile.includes("master") || teile.includes("exec") || teile.includes("show")) oben();
    if (teile.includes("verbunden")) wurzel.classList.toggle("getrennt", !s.verbunden);
  });
  const weg2 = zielAbonnieren((z) => {
    wurzel.querySelector(".wing")?.classList.toggle("ziel-modus", z.aktiv);
    zielSchild.hidden = !z.aktiv;
    zielSchild.textContent = z.text;
  });
  return () => { weg1(); weg2(); buehne.ende(); };
}
