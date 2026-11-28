// Ansicht „Show“: Musik-Automatik oder Selbst fahren, Song-Start aus der Setlist, Looks, Farben, Halten, Tap.
import { befehl, stand, abonnieren } from "./verbindung.js";
import { el, t, tippen, halten, FARBWERTE, FARBNAMEN } from "./hilfe.js";

export function showAnsicht(wurzel) {
  const fest = () => stand.fest || {};
  const profile = el("div.pool");
  const regie = tippen(el("button.taste"), () => befehl("regie", { an: !stand.z.show?.regie }).catch(() => {}));
  const musik = el("div.show-musik");
  const looks = el("div.look-raster.gross");
  const farben1 = el("div.farb-reihe"), farben2 = el("div.farb-reihe");
  const haltenFeld = el("div.knopf-raster");
  const songs = el("div.song-liste");
  const songJetzt = el("div.song-jetzt");

  function bauen() {
    profile.replaceChildren(...(fest().profile || []).map((p) => tippen(el("button.kachel", { data: { profil: p } }, p), () => befehl("profil", { name: p }).catch(() => {}))));
    looks.replaceChildren(...(fest().looks || []).map((l) => tippen(el("button.taste.look", { data: { look: l.id } }, el("b", {}, l.taste || ""), el("span", {}, l.name)),
      () => befehl("look", { id: stand.z.show?.look === l.id ? "aus" : l.id }).catch(() => {}))));
    const farbKnopf = (nr, f) => tippen(el("button.farb-knopf", { data: { farbe: f }, stil: { background: FARBWERTE[f] || f }, title: FARBNAMEN[f] || f }),
      () => befehl("farben", nr === 1 ? { farbe_1: f } : { farbe_2: f }).catch(() => {}));
    const liste = (fest().farben || Object.keys(FARBNAMEN)).filter((f) => typeof f === "string");
    farben1.replaceChildren(...liste.map((f) => farbKnopf(1, f)));
    farben2.replaceChildren(...liste.map((f) => farbKnopf(2, f)));
    haltenFeld.replaceChildren(...Object.entries(fest().halten || {}).map(([art, text]) =>
      halten(el("button.taste.gross.halten", { data: { art } }, typeof text === "string" ? text : (text.name || art)),
        () => befehl("halten", { art, an: true }).catch(() => {}), () => befehl("halten", { art, an: false }).catch(() => {}))),
      tippen(el("button.taste.gross", {}, "TAP"), () => befehl("tap").catch(() => {})));
    songs.replaceChildren(...(fest().setlist || []).map((name) => el("div.song-zeile", {}, el("span", {}, name),
      tippen(el("button.taste.gruen.klein", {}, "Start"), () => befehl("song", { aktion: "start", name }).catch(() => {})))));
    if (!(fest().setlist || []).length) songs.append(el("p.leise", {}, "Keine Songs mit Probe-Aufnahme in der Setlist (am MacBook: Reiter Probe)."));
    zeigen();
  }
  function zeigen() {
    const s = stand.z.show || {}, m = stand.z.musik || {};
    for (const k of profile.children) k.classList.toggle("gewaehlt", k.dataset.profil === s.profil);
    regie.textContent = s.regie ? "KI-Regie: an" : "KI-Regie: aus";
    regie.classList.toggle("an", Boolean(s.regie));
    for (const k of looks.children) k.classList.toggle("an", k.dataset.look === s.look);
    for (const k of farben1.children) k.classList.toggle("an", k.dataset.farbe === s.farbe_1);
    for (const k of farben2.children) k.classList.toggle("an", k.dataset.farbe === s.farbe_2);
    for (const k of haltenFeld.children) if (k.dataset.art) k.classList.toggle("an", Boolean(s.halten?.[k.dataset.art]));
    musik.innerHTML = `<div><b>${t(m.bpm ? Math.round(m.bpm) : "–")}</b><span>BPM</span></div>
      <div><b>${t(["ruhig", "mittel", "stark", "Höhepunkt"][m.stufe ?? 0] || "–")}</b><span>Stärke</span></div>
      <div><b>${t(m.look || (s.automatik ? "…" : "aus"))}</b><span>Look der Automatik</span></div>
      <div><b>${t(m.ton === "ok" ? "Ton da" : m.ton === "gehalten" ? "Ton stockt" : m.ton === "weg" ? "TON WEG" : "kein Ton")}</b><span>${t(m.quelle || "")}</span></div>`;
    const song = s.song;
    songJetzt.replaceChildren(song ? el("div.song-laeuft", {},
      el("div", {}, el("small", {}, "Jetzt"), el("b", {}, `${song.jetzt?.name || ""} ${song.jetzt?.gruppe || ""}`)),
      el("div", {}, el("small", {}, "Danach"), el("b", {}, song.naechster ? `${song.naechster.name} ${song.naechster.gruppe || ""}` : "Ende")),
      el("div", {}, el("small", {}, "noch"), el("b", {}, song.teile?.[song.teil] ? `${Math.max(0, Math.round(song.teile[song.teil].ende - song.stelle))} s` : "")),
      el("div.zeile", {}, tippen(el("button.taste", {}, "◀ Teil"), () => befehl("song", { aktion: "zurueck" }).catch(() => {})),
        tippen(el("button.taste", {}, "Teil ▶"), () => befehl("song", { aktion: "vor" }).catch(() => {})),
        tippen(el("button.taste.warnung", {}, "Song stopp"), () => befehl("song", { aktion: "stopp" }).catch(() => {})))) : el("p.leise", {}, "Kein Song läuft."));
  }

  wurzel.replaceChildren(el("div.showseite", {},
    el("section.fenster", {}, el("header", {}, "Musik"), musik, el("header", {}, "Profil"), profile, el("div.zeile", {}, regie)),
    el("section.fenster", {}, el("header", {}, "Looks (liegen über der Automatik)"), looks, el("header", {}, "Farbe 1"), farben1, el("header", {}, "Farbe 2"), farben2),
    el("section.fenster", {}, el("header", {}, "Halten (solange gedrückt)"), haltenFeld, el("header", {}, "Song"), songJetzt, songs)));
  bauen();
  return abonnieren((s, teile) => {
    if (teile.includes("fest")) bauen();
    else if (teile.includes("show") || teile.includes("musik")) zeigen();
  });
}
