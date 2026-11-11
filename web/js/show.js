// View "Show": Hier wird live gefahren.
//   Oben: Song-Start. Einmal drücken, wenn die Band anfängt, dann läuft der ganze Song.
//   Darunter: Look-Tasten, Farben, Halte-Tasten und Tap-Tempo. Die gehen immer, auch ohne Ton.
import { api, senden, t } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";

const FARBWERT = {
  rot: "#ff2020", orange: "#ff8000", gelb: "#ffe000", gruen: "#20d040", cyan: "#00e0e0", blau: "#2050ff",
  lila: "#9030ff", pink: "#ff30b0", weiss: "#ffffff", warmweiss: "#ffd9a0",
};
const FARBNAME = {
  rot: "Rot", orange: "Orange", gelb: "Gelb", gruen: "Grün", cyan: "Cyan", blau: "Blau", lila: "Lila",
  pink: "Pink", weiss: "Weiß", warmweiss: "Warmweiß",
};
const FOLGER = {
  bereit: ["warn", "wartet auf die Band … (Song nochmal drücken = jetzt los)"],
  sucht: ["warn", "sucht die Stelle im Song … (Song nochmal drücken = jetzt los)"],
  hoert: ["an", "hört mit ✓"],
  unsicher: ["", "hört mit, noch unsicher"],
  uhr: ["warn", "kein Ton: läuft nach Uhr"],
  wartet: ["warn", "Band spielt nicht: wartet"],
};
const HALTE_TASTEN = { flash: "f" };
const minuten = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const setze = (element, text) => { if (element.textContent !== text) element.textContent = text; };

export function showSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="show">
      <div class="show-oben">
      <section class="fenster songfenster"><header>Song-Start <span id="folger" class="chip"></span></header>
        <div class="inhalt">
          <div id="songliste" class="songliste"></div>
          <div id="songlauf" class="songlauf" hidden>
            <div class="jetzt-zeile">
              <div><div class="leise klein-titel">Jetzt</div><div id="jetzt" class="jetzt"></div></div>
              <div class="rest"><div class="leise klein-titel">noch</div><div id="rest" class="restzahl"></div></div>
              <div class="danach-box"><div class="leise klein-titel">Danach</div><div id="danach" class="danach"></div></div>
            </div>
            <div class="songleiste" id="leiste"><i id="kopf" class="abspielkopf"></i></div>
            <div class="zeile songknoepfe">
              <button id="zurueck">◀ Teil zurück <kbd>←</kbd></button>
              <button id="vor" class="haupt">Nächster Teil jetzt ▶ <kbd>Leertaste</kbd></button>
              <button id="stopp" class="gefahr">■ Stopp</button>
              <span id="songinfo" class="leise"></span>
            </div>
          </div>
          <p class="leise" id="songhinweis">Start drücken, wenn die Band anfängt. Das Programm hört mit und schaltet
            die Teile von selbst weiter. Fällt der Ton aus, läuft der Song im Tempo der Probe weiter.</p>
        </div>
      </section>
      <section class="fenster buehnenfenster"><header>Bühne live <span id="quelle" class="leise"></span></header>
        <div class="drei-d show-buehne" id="drei"></div></section>
      </div>
      <div class="show-unten">
        <section class="fenster"><header>Looks <span class="leise">Tasten 1–9 · 0 = Look aus</span></header>
          <div class="inhalt"><div class="looks" id="looks"></div></div></section>
        <div class="show-rechts">
          <section class="fenster"><header>Farben</header>
            <div class="inhalt"><div class="leise klein-titel">Farbe 1</div><div class="farbreihe" id="farbe_1"></div>
              <div class="leise klein-titel">Farbe 2</div><div class="farbreihe" id="farbe_2"></div></div></section>
          <section class="fenster"><header>Halten · Tempo <span class="leise">gedrückt halten</span></header>
            <div class="inhalt">
              <div class="halten"><span id="halten" class="halten-tasten"></span>
                <button id="tap" class="tap">TAP<kbd>T</kbd></button></div>
              <div class="tempo-box"><span id="bpm" class="bpm">–</span> <span class="leise">BPM</span>
                <span id="tquelle" class="leise"></span>
                <button id="vom-ton" class="klein">Tempo vom Ton</button></div>
            </div></section>
        </div>
      </div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  let songs = [];
  let looks = [];
  let leistenStand = "";
  let letzterLive = null;
  let buehne = null;
  let beendet = false;

  async function laden() {
    const daten = await api("/show");
    songs = daten.songs;
    looks = daten.looks;
    feld("songliste").innerHTML = songs.map((s) => `
      <button class="songknopf" data-song="${t(s.name)}">▶ <b>${t(s.name)}</b>
        <span class="leise">${s.dauer_s ? minuten(s.dauer_s) : ""} · ${s.tempo_bpm ? Math.round(s.tempo_bpm) + " BPM" : ""} · ${s.teile.length} Teile</span>
        ${s.alte_analyse ? `<span class="alt-hinweis">Alte Erkennung: in der Probe „Show neu bauen“ drücken</span>` : ""}</button>`).join("")
      || `<p class="leise">Noch keine Songs. In der Probe einen Song aufnehmen, dann erscheint er hier.</p>`;
    feld("looks").innerHTML = looks.map((l) => `
      <button class="look" data-look="${l.id}"><span class="look-name">${t(l.name)}</span>
        <span class="look-text">${t(l.text)}</span><kbd>${l.taste}</kbd></button>`).join("")
      + `<button class="look aus" data-look="aus"><span class="look-name">Look aus</span>
        <span class="look-text">zurück zu Song und Automatik</span><kbd>0</kbd></button>`;
    for (const nummer of [1, 2]) {
      feld("farbe_" + nummer).innerHTML = daten.farben.map((f) => `
        <button class="farbe" data-farbe="${f}" data-nummer="${nummer}" title="${FARBNAME[f] ?? f}"
          style="--farbe:${FARBWERT[f] ?? "#888"}"></button>`).join("");
    }
    feld("halten").innerHTML = Object.entries(daten.halten).map(([art, name]) => `
      <button class="halte" data-halten="${art}">${t(name)}${HALTE_TASTEN[art] ? `<kbd>${HALTE_TASTEN[art].toUpperCase()}</kbd>` : ""}</button>`).join("");
    if (letzterLive) zeigen(letzterLive);
  }

  function leisteZeigen(song) {
    const stand = JSON.stringify([song.name, song.teile]);
    if (stand === leistenStand) return;
    leistenStand = stand;
    const dauer = song.dauer_s || (song.teile.at(-1)?.ende ?? 1);
    feld("leiste").innerHTML = song.teile.map((teil, i) => `
      <div class="${teil.klasse}" data-teil="${i}" style="left:${(teil.start / dauer) * 100}%;width:${((teil.ende - teil.start) / dauer) * 100}%"
        title="${t(teil.name)} ${t(teil.gruppe)}: ${minuten(teil.start)} bis ${minuten(teil.ende)}">${t(teil.name)} ${t(teil.gruppe)}</div>`).join("")
      + `<i id="kopf" class="abspielkopf"></i>`;
  }

  // Was steuert das Licht gerade? So sieht man, warum die Bühne so aussieht.
  function quelleText(live) {
    const tasten = live.pult.tasten;
    const gehalten = Object.entries(tasten.halten).filter(([, an]) => an).map(([art]) => ({ flash: "Weiß voll", strobo: "Strobo", dunkel: "Dunkel" })[art]);
    if (live.overrides.blackout) return "Blackout";
    if (gehalten.length) return gehalten.join(" + ") + " (gehalten)";
    if (tasten.look) return "Look: " + (looks.find((l) => l.id === tasten.look)?.name ?? tasten.look);
    if (live.song?.laeuft) return `Song: ${live.song.name} · ${live.song.jetzt.name} ${live.song.jetzt.gruppe}`.trim();
    return live.automatik ? "Automatik: " + live.engine : "Grundlicht";
  }

  function zeigen(live) {
    letzterLive = live;
    buehne?.setzeWerte(live.geraete);
    setze(feld("quelle"), quelleText(live));
    const song = live.song;
    const laeuft = Boolean(song?.laeuft);
    feld("songlauf").hidden = !laeuft;
    feld("songhinweis").hidden = laeuft;
    for (const knopf of feld("songliste").querySelectorAll("[data-song]")) {
      knopf.classList.toggle("an", laeuft && knopf.dataset.song === song.name);
    }
    if (laeuft) {
      leisteZeigen(song);
      const jetzt = song.jetzt;
      setze(feld("jetzt"), `${jetzt.name} ${jetzt.gruppe}`.trim());
      feld("jetzt").className = "jetzt " + jetzt.klasse;
      setze(feld("rest"), jetzt.rest_takte != null ? `${jetzt.rest_takte} Takte · ${Math.round(jetzt.rest_s)} s` : "");
      setze(feld("danach"), song.naechster ? `${song.naechster.name} ${song.naechster.gruppe}`.trim() : "Ende");
      const dauer = song.dauer_s || 1;
      feld("leiste").querySelector("#kopf").style.left = `${Math.min(100, (song.stelle / dauer) * 100)}%`;
      for (const teil of feld("leiste").querySelectorAll("[data-teil]")) {
        teil.classList.toggle("aktiv", Number(teil.dataset.teil) === song.teil);
      }
      const [art, text] = FOLGER[song.folger.art] ?? ["", ""];
      const prozent = Math.round((song.folger.rate - 1) * 100);
      setze(feld("folger"), text);
      feld("folger").className = "chip " + art;
      setze(feld("songinfo"), `${t(song.name)} · ${minuten(song.stelle)} von ${minuten(dauer)}` +
        (Math.abs(prozent) >= 2 ? ` · Band ${Math.abs(prozent)} % ${prozent > 0 ? "schneller" : "langsamer"} als in der Probe` : ""));
    } else {
      setze(feld("folger"), "");
      feld("folger").className = "chip";
    }
    const tasten = live.pult.tasten;
    for (const knopf of feld("looks").querySelectorAll("[data-look]")) {
      knopf.classList.toggle("an", knopf.dataset.look === tasten.look);
    }
    for (const knopf of wurzel.querySelectorAll("[data-farbe]")) {
      knopf.classList.toggle("an", tasten["farbe_" + knopf.dataset.nummer] === knopf.dataset.farbe);
    }
    for (const knopf of feld("halten").querySelectorAll("[data-halten]")) {
      knopf.classList.toggle("an", Boolean(tasten.halten[knopf.dataset.halten]));
    }
    setze(feld("bpm"), live.tempo ? String(Math.round(live.tempo)) : "–");
    const quelle = tasten.tempo_quelle === "tap" ? "getippt" : laeuft ? "vom Song" : live.audio.werte ? "vom Ton" : "ohne Ton: letztes Tempo";
    setze(feld("tquelle"), quelle);
    feld("vom-ton").hidden = tasten.tempo_quelle !== "tap";
  }

  // --- Bedienen ------------------------------------------------------------
  wurzel.addEventListener("click", async (ereignis) => {
    const ziel = ereignis.target.closest("button, [data-teil]");
    if (!ziel) return;
    const d = ziel.dataset;
    if (d.song) await senden("/song/start", { name: d.song });
    if (d.look) await senden("/look/" + d.look);
    if (d.farbe) await senden("/farben", { ["farbe_" + d.nummer]: d.farbe });
    if (d.teil !== undefined) await senden("/song/teil", { index: Number(d.teil) });
  });
  feld("vor").onclick = () => senden("/song/vor");
  feld("zurueck").onclick = () => senden("/song/zurueck");
  feld("stopp").onclick = () => senden("/song/stopp");
  feld("tap").onpointerdown = () => senden("/tap");
  feld("vom-ton").onclick = () => senden("/tempo/quelle", { quelle: "ton" });

  // Halte-Tasten: an beim Drücken, aus beim Loslassen (auch wenn die Maus wegrutscht)
  const gehalten = new Set();
  const halten = (art, an) => {
    if (an === gehalten.has(art)) return;
    an ? gehalten.add(art) : gehalten.delete(art);
    senden("/halten/" + art, { an });
  };
  feld("halten").addEventListener("pointerdown", (e) => {
    const knopf = e.target.closest("[data-halten]");
    if (!knopf) return;
    knopf.setPointerCapture?.(e.pointerId);
    halten(knopf.dataset.halten, true);
  });
  for (const art of ["pointerup", "pointercancel", "lostpointercapture"]) {
    feld("halten").addEventListener(art, (e) => {
      const knopf = e.target.closest("[data-halten]");
      if (knopf) halten(knopf.dataset.halten, false);
    });
  }
  const allesLoslassen = () => [...gehalten].forEach((art) => halten(art, false));
  window.addEventListener("blur", allesLoslassen);

  // Tastatur auf dieser Seite: 1–9 Looks, 0 aus, T Tap, F Weiß voll (halten)
  function tasteRunter(e) {
    if (e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
    const taste = e.key.toLowerCase();
    const look = looks.find((l) => l.taste === taste);
    if (look || taste === "0") {
      e.preventDefault(); e.stopImmediatePropagation();
      if (!e.repeat) senden("/look/" + (look ? look.id : "aus"));
    } else if (taste === "t") {
      e.preventDefault(); e.stopImmediatePropagation();
      if (!e.repeat) senden("/tap");
    } else if (taste === "f") {
      e.preventDefault(); e.stopImmediatePropagation();
      if (!e.repeat) halten("flash", true);
    }
  }
  function tasteHoch(e) {
    if (e.key.toLowerCase() === "f") halten("flash", false);
  }
  document.addEventListener("keydown", tasteRunter, true);
  document.addEventListener("keyup", tasteHoch, true);

  const abmelden = abonnieren((live) => { if (live) zeigen(live); });
  laden();
  api("/buehne").then((aufbau) => { if (!beendet) buehne = new Buehne3D(feld("drei"), aufbau, { nah: true }); });
  return () => {
    beendet = true;
    buehne?.beenden();
    abmelden();
    allesLoslassen();
    window.removeEventListener("blur", allesLoslassen);
    document.removeEventListener("keydown", tasteRunter, true);
    document.removeEventListener("keyup", tasteHoch, true);
  };
}
