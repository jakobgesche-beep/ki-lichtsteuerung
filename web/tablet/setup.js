// Ansicht „Setup“ (schlank): Größe des iPads, Geräte mit Adresse und DIP-Schaltern, DMX, Ton, Verbindung.
import { befehl, stand, abonnieren, abmelden } from "./verbindung.js";
import { el, t, tippen, halten, erinnern, merken } from "./hilfe.js";
import { frage } from "./kontext.js";
import { dipHtml } from "/gemeinsam/dip.js";

const GROESSEN = { auto: "Automatisch", mini: "iPad mini", "11": "iPad 11 Zoll", "13": "iPad 13 Zoll" };

export function groesseAnwenden(groesse) {
  let masz = 1;
  if (groesse === "mini") masz = 0.86;
  else if (groesse === "13") masz = 1.12;
  else if (groesse === "auto") masz = Math.max(0.82, Math.min(1.15, Math.min(window.innerWidth / 1180, window.innerHeight / 820)));
  document.documentElement.style.setProperty("--masz", masz.toFixed(3));
}
window.addEventListener("resize", () => { if (erinnern("groesse", "auto") === "auto") groesseAnwenden("auto"); });

export function setupAnsicht(wurzel) {
  const groessen = el("div.zeile", {}, Object.entries(GROESSEN).map(([id, name]) => tippen(el("button.taste", { data: { groesse: id } }, name), () => {
    merken("groesse", id); groesseAnwenden(id); for (const b of groessen.children) b.classList.toggle("an", b.dataset.groesse === id);
  })));
  for (const b of groessen.children) b.classList.toggle("an", b.dataset.groesse === erinnern("groesse", "auto"));
  const liste = el("div.geraete-liste");
  const dmx = el("div.zeile");
  const ton = el("div.ton-info");
  const verbindung = el("div.leise");

  function bauen() {
    liste.replaceChildren(...(stand.fest?.geraete || []).map((g) => el("div.geraet-zeile", {},
      el("div", {}, el("b", {}, g.name), el("small", {}, `${g.typ} · ${g.modus}`)),
      el("div.adresse", {}, el("b", {}, String(g.adresse).padStart(3, "0")), el("small", {}, `${g.kanaele} Kanäle`)),
      el("div", { html: dipHtml(g.adresse, g.einstellen, { gross: true, ohneHinweis: g.einstellen?.art === "unbekannt" }) }),
      halten(el("button.taste.klein", {}, "Aufblitzen"), () => befehl("aufblitzen", { geraet: g.id, an: true }).catch(() => {}),
        () => befehl("aufblitzen", { geraet: g.id, an: false }).catch(() => {})))));
    zeigen();
  }
  function zeigen() {
    const d = stand.z.dmx || {};
    dmx.replaceChildren(el("span", {}, d.an ? (d.verbunden ? "DMX ist an." : "DMX ist an, aber das Enttec antwortet nicht.") : "DMX ist aus (Lichter bekommen nichts)."),
      tippen(el(`button.taste${d.an ? ".warnung" : ".gruen"}`, {}, d.an ? "DMX aus" : "DMX an"), async () => {
        if (!(await frage(d.an ? "DMX ausschalten?" : "DMX einschalten?", d.an ? "Alle Lichter gehen aus." : "Die Lichter bekommen ab jetzt Werte.", d.an ? "Ausschalten" : "Einschalten", d.an ? "warnung" : "gruen"))) return;
        befehl("dmx", { an: !d.an, bestaetigt: true }).catch(() => {});
      }));
    const m = stand.z.musik || {};
    ton.innerHTML = `Ton: <b>${t(m.quelle || "aus")}</b> – ${t(m.ton === "ok" ? "kommt an" : m.ton === "weg" ? "WEG" : m.ton === "gehalten" ? "stockt" : "kein Ton")}.
      Quelle und Kanäle (X32-USB) stellt man am MacBook ein (Reiter Live).`;
    verbindung.textContent = `Verbunden mit ${location.host} · Antwortzeit ${stand.rtt ?? "?"} ms · Version ${stand.version || "?"}`;
  }

  wurzel.replaceChildren(el("div.setupseite", {},
    el("section.fenster", {}, el("header", {}, "Größe der Bedienung"), groessen,
      el("header", {}, "Geräte, Adressen und DIP-Schalter"), el("p.leise", {}, "So stellt man jedes Gerät ein: DIP-Schalter (Hebel oben = an) oder Display. Bei Geräten ohne Eintrag steht beides – was dein Gerät hat, steht in seinem Handbuch. „Aufblitzen“ (halten) zeigt, welches Licht es ist."), liste),
    el("section.fenster", {}, el("header", {}, "DMX"), dmx, el("header", {}, "Ton"), ton,
      el("header", {}, "Verbindung"), verbindung,
      el("div.anleitung", {}, el("h3", {}, "Damit das iPad nicht ausgeht"), el("ol", {},
        el("li", {}, "Einstellungen → Anzeige & Helligkeit → Automatische Sperre → Nie"),
        el("li", {}, "Einstellungen → Multitasking & Gesten → Gesten aus"),
        el("li", {}, "Am Abend: Geführter Zugriff (Bedienungshilfen), Ladekabel dran"))),
      tippen(el("button.taste.warnung.klein", {}, "Dieses iPad abmelden"), async () => { if (await frage("Abmelden?", "Danach muss das iPad mit einer neuen PIN vom MacBook gekoppelt werden.", "Abmelden")) abmelden(); }))));
  bauen();
  return abonnieren((s, teile) => { if (teile.includes("fest")) bauen(); else if (teile.includes("dmx") || teile.includes("musik")) zeigen(); });
}
