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
      <section class="fenster songfenster"><header>Song-Start <span class="zeile"><span id="folger" class="chip"></span>
        <button id="gp-knopf" class="chip check-knopf" title="Generalprobe: Die Setlist mit veränderten Probe-Aufnahmen durchspielen">Generalprobe …</button>
        <button id="check-knopf" class="chip check-knopf" title="Ist alles bereit fürs Konzert?">Konzert-Check …</button></span></header>
        <div id="check-liste" class="check-liste" hidden></div>
        <div id="gp-liste" class="check-liste gp-liste" hidden></div>
        <div class="inhalt">
          <div class="erkennung zeile" id="erkennung">
            <span class="leise">Song-Erkennung</span>
            <span class="segment" id="modus">
              <button data-modus="automatisch" title="Der nächste Song der Setlist startet von selbst, sobald er erkannt ist">Automatisch</button>
              <button data-modus="vorschlagen" title="Erkannte Songs erscheinen nur als Knopf">Vorschlagen</button>
              <button data-modus="aus">Aus</button></span>
            <span id="erwartet" class="leise"></span>
            <button id="reihenfolge" class="klein" title="Setlist: Reihenfolge der Songs fürs Konzert">Reihenfolge ändern</button>
            <label class="schalter" title="Nach dem Song hell und warm für den Applaus, danach ruhig bis zum nächsten Song">
              <input type="checkbox" id="zwischenlicht"> Applaus- und Pausenlicht</label>
          </div>
          <div id="vorschlag" class="vorschlag" hidden></div>
          <div id="erkennung-text" class="leise erkennung-text"></div>
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
  let ordnen = false;              // Reihenfolge der Setlist ändern
  let setlistStand = "";
  let letzterLive = null;
  let buehne = null;
  let beendet = false;

  async function laden() {
    const daten = await api("/show");
    songs = daten.songs;
    looks = daten.looks;
    songsZeigen(letzterLive?.erkennung?.setlist);
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
    if (live.zwischenlicht?.zustand === "applaus") return "Applaus-Licht (Song zu Ende)";
    if (live.zwischenlicht?.zustand === "pause") return "Pausenlicht (bis der nächste Song kommt)";
    if (live.song?.laeuft) return `Song: ${live.song.name} · ${live.song.jetzt.name} ${live.song.jetzt.gruppe}`.trim();
    return live.automatik ? "Automatik: " + live.engine : "Grundlicht";
  }

  // Songs in der Reihenfolge der Setlist, mit Nummer. Beim Ordnen: Pfeile zum Verschieben.
  function songsZeigen(setlist) {
    const reihenfolge = setlist?.length ? setlist : songs.map((s) => s.name);
    const nachName = new Map(songs.map((s) => [s.name, s]));
    const geordnet = reihenfolge.map((n) => nachName.get(n)).filter(Boolean)
      .concat(songs.filter((s) => !reihenfolge.includes(s.name)));
    const stand = JSON.stringify([geordnet.map((s) => s.name), ordnen, songs.map((s) => s.alte_analyse)]);
    if (stand === setlistStand) return;
    setlistStand = stand;
    feld("songliste").innerHTML = geordnet.map((s, i) => `
      <div class="songplatz">
        <button class="songknopf" data-song="${t(s.name)}"><span><span class="setlist-nr">${i + 1}</span> ▶ <b>${t(s.name)}</b></span>
          <span class="leise">${s.dauer_s ? minuten(s.dauer_s) : ""} · ${s.tempo_bpm ? Math.round(s.tempo_bpm) + " BPM" : ""} · ${s.teile.length} Teile</span>
          ${s.alte_analyse ? `<span class="alt-hinweis">Alte Erkennung: in der Probe „Show neu bauen“ drücken</span>` : ""}</button>
        ${ordnen ? `<span class="ordnen"><button class="klein" data-hoch="${i}" ${i === 0 ? "disabled" : ""}>↑</button>
          <button class="klein" data-runter="${i}" ${i === geordnet.length - 1 ? "disabled" : ""}>↓</button></span>` : ""}
      </div>`).join("")
      || `<p class="leise">Noch keine Songs. In der Probe einen Song aufnehmen, dann erscheint er hier.</p>`;
    feld("songliste").dataset.reihenfolge = JSON.stringify(geordnet.map((s) => s.name));
  }

  function erkennungZeigen(e) {
    if (!e) return;
    songsZeigen(e.setlist);
    for (const knopf of feld("modus").querySelectorAll("[data-modus]")) knopf.classList.toggle("an", knopf.dataset.modus === e.modus);
    if (!feld("zwischenlicht").matches(":focus")) feld("zwischenlicht").checked = e.zwischenlicht !== false;
    setze(feld("erwartet"), e.modus === "aus" ? "" : e.erwartet ? `Als Nächstes: ${e.erwartet}` : "Setlist durch");
    const text = e.modus === "aus" ? "Songs nur von Hand starten (antippen, wenn die Band anfängt)."
      : e.kandidat ? `Erkennt gerade: ${e.kandidat} …`
      : e.meldung ? e.meldung
      : e.hoert ? "Hört zu …" : "Wartet auf Musik. Sobald die Band einen geprobten Song spielt, wird er erkannt.";
    setze(feld("erkennung-text"), text);
    const v = e.vorschlag;
    feld("vorschlag").hidden = !v;
    const html = v ? `<button class="vorschlag-knopf" id="vorschlag-start">Klingt nach „${t(v.name)}“${v.laeuft_anderer ? " (ein anderer Song läuft gerade)" : ""} · jetzt starten</button>` : "";
    if (feld("vorschlag").dataset.inhalt !== html) { feld("vorschlag").innerHTML = html; feld("vorschlag").dataset.inhalt = html; }
  }

  function zeigen(live) {
    letzterLive = live;
    erkennungZeigen(live.erkennung);
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

  // --- Konzert-Check: läuft mit, sagt, was fehlt ------------------------------
  const STUFE = { ok: "✓", hinweis: "!", problem: "✗" };
  async function checkLaden() {
    let punkte;
    try { punkte = (await api("/check")).punkte; } catch { return; }
    const probleme = punkte.filter((p) => p.stufe === "problem").length;
    const hinweise = punkte.filter((p) => p.stufe === "hinweis").length;
    const knopf = feld("check-knopf");
    const text = probleme ? `Check: ${probleme} Problem${probleme > 1 ? "e" : ""}` : hinweise ? `Check: ${hinweise} Hinweis${hinweise > 1 ? "e" : ""}` : "Check: alles bereit ✓";
    setze(knopf, text);
    knopf.className = `chip check-knopf ${probleme ? "warn" : hinweise ? "gelb" : "an"}`;
    const html = punkte.map((p) => `<div class="check-punkt ${p.stufe}"><span class="check-zeichen">${STUFE[p.stufe]}</span>
      <span><b>${t(p.thema)}</b> ${t(p.text)}</span>${p.aktion === "dmx_ein" ? `<button class="klein haupt" data-check="dmx_ein">DMX einschalten</button>` : ""}</div>`).join("");
    if (feld("check-liste").dataset.inhalt !== html) {
      feld("check-liste").innerHTML = html;
      feld("check-liste").dataset.inhalt = html;
    }
  }
  feld("check-knopf").onclick = () => { feld("check-liste").hidden = !feld("check-liste").hidden; checkLaden(); };
  feld("check-liste").addEventListener("click", async (ereignis) => {
    if (ereignis.target.dataset.check === "dmx_ein") { await senden("/dmx/ein").catch(() => {}); checkLaden(); }
  });
  checkLaden();
  const checkUhr = setInterval(checkLaden, 3000);

  // --- Generalprobe: die Setlist mit veränderten Probe-Aufnahmen durchspielen ---------
  let gpUhr = null;
  const gpUhrAn = () => { if (!gpUhr) gpUhr = setInterval(gpLaden, 1000); };
  async function gpLaden() {
    let zustand;
    try { zustand = await api("/generalprobe"); } catch { return; }
    gpZeigen(zustand);
    if (!zustand.laeuft && feld("gp-liste").hidden && gpUhr) { clearInterval(gpUhr); gpUhr = null; }
  }
  function gpZeigen(z) {
    const e = z.ergebnis;
    const minuten = Math.max(1, Math.round((z.dauer_schaetzung_s || 60) / 60));
    let html = `<div class="gp-kopf"><b>Generalprobe</b> <span class="leise">Das Programm spielt alle Songs der Setlist mit
      veränderten Probe-Aufnahmen durch (schneller oder langsamer, anderer Klang, Publikum) und zeigt, wo es unsicher ist.
      Nicht während des Konzerts starten: Es braucht viel Rechenzeit.</span></div>`;
    html += z.laeuft
      ? `<div class="gp-lauf"><div class="gp-balken"><i style="width:${Math.round(z.fortschritt * 100)}%"></i></div>
          <span class="leise">${t(z.schritt)}</span><button class="klein" data-gp="stopp">Abbrechen</button></div>`
      : `<div class="gp-lauf"><button class="haupt" data-gp="start">Generalprobe starten</button>
          <span class="leise">dauert etwa ${minuten} Minute${minuten > 1 ? "n" : ""}</span></div>`;
    if (z.fehler) html += `<div class="check-punkt hinweis"><span class="check-zeichen">!</span><span>${t(z.fehler)}</span></div>`;
    if (e) {
      const geaendert = z.veraltet?.length ? ` · seitdem neu oder geändert: ${z.veraltet.map(t).join(", ")}` : "";
      html += `<div class="leise gp-zeit">Letzte Generalprobe: ${t(e.zeit)}${geaendert}</div>`;
      html += e.songs.map((s) => `<div class="check-punkt ${s.stufe}"><span class="check-zeichen">${STUFE[s.stufe]}</span>
        <span><b>${t(s.name)}</b><br><span class="gp-zeile">Erkennung: ${t(s.erkennung.text)}</span><br>
        <span class="gp-zeile">Licht: ${t(s.licht.text)}</span></span></div>`).join("");
      if (e.rechner?.text) {
        html += `<div class="check-punkt ${e.rechner.stufe}"><span class="check-zeichen">${STUFE[e.rechner.stufe]}</span><span>${t(e.rechner.text)}</span></div>`;
      }
      html += `<div class="leise gp-zeit">Grün heißt: gute Chancen. Eine echte Band spielt noch etwas anders als die veränderte Aufnahme.</div>`;
    }
    if (feld("gp-liste").dataset.inhalt !== html) {
      feld("gp-liste").innerHTML = html;
      feld("gp-liste").dataset.inhalt = html;
    }
    const rot = e ? e.songs.filter((s) => s.stufe === "problem").length : 0;
    const gelb = e ? e.songs.filter((s) => s.stufe === "hinweis").length : 0;
    setze(feld("gp-knopf"), z.laeuft ? `Generalprobe ${Math.round(z.fortschritt * 100)} %` : "Generalprobe …");
    feld("gp-knopf").className = `chip check-knopf ${z.laeuft ? "gelb" : !e ? "" : rot ? "warn" : gelb ? "gelb" : "an"}`;
  }
  feld("gp-knopf").onclick = () => {
    feld("gp-liste").hidden = !feld("gp-liste").hidden;
    if (!feld("gp-liste").hidden) {
      feld("check-liste").hidden = true;
      gpLaden();
      gpUhrAn();
    }
  };
  feld("check-knopf").addEventListener("click", () => { feld("gp-liste").hidden = true; });
  feld("gp-liste").addEventListener("click", async (ereignis) => {
    const knopf = ereignis.target.closest("[data-gp]");
    if (!knopf) return;
    try { gpZeigen(await senden("/generalprobe/" + knopf.dataset.gp)); } catch { return; }
    gpUhrAn();
  });
  gpLaden().then(() => { if (feld("gp-knopf").textContent.includes("%")) gpUhrAn(); });

  // --- Bedienen ------------------------------------------------------------
  wurzel.addEventListener("click", async (ereignis) => {
    const ziel = ereignis.target.closest("button, [data-teil]");
    if (!ziel) return;
    const d = ziel.dataset;
    if (d.modus) { await senden("/setlist", { modus: d.modus }); return; }
    if (ziel.id === "reihenfolge") { ordnen = !ordnen; ziel.classList.toggle("an", ordnen); setlistStand = ""; songsZeigen(letzterLive?.erkennung?.setlist); return; }
    if (ziel.id === "vorschlag-start") { await senden("/song/vorschlag"); return; }
    if (d.hoch !== undefined || d.runter !== undefined) {
      const liste = JSON.parse(feld("songliste").dataset.reihenfolge || "[]");
      const i = Number(d.hoch ?? d.runter);
      const j = d.hoch !== undefined ? i - 1 : i + 1;
      [liste[i], liste[j]] = [liste[j], liste[i]];
      const neu = await senden("/setlist", { reihenfolge: liste });
      setlistStand = "";
      songsZeigen(neu.setlist);
      return;
    }
    if (d.song) {
      // Aus Versehen auf den laufenden Song getippt? Dann nicht einfach von vorn anfangen.
      const song = letzterLive?.song;
      const laeuftSchon = song?.laeuft && song.name === d.song && song.folger?.art !== "bereit";
      if (laeuftSchon && !confirm(`„${d.song}“ läuft gerade. Von vorn beginnen?`)) return;
      await senden("/song/start", { name: d.song });
    }
    if (d.look) await senden("/look/" + d.look);
    if (d.farbe) await senden("/farben", { ["farbe_" + d.nummer]: d.farbe });
    if (d.teil !== undefined) await senden("/song/teil", { index: Number(d.teil) });
  });
  feld("zwischenlicht").onchange = () => senden("/setlist", { zwischenlicht: feld("zwischenlicht").checked });
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
    clearInterval(checkUhr);
    clearInterval(gpUhr);
    beendet = true;
    buehne?.beenden();
    abmelden();
    allesLoslassen();
    window.removeEventListener("blur", allesLoslassen);
    document.removeEventListener("keydown", tasteRunter, true);
    document.removeEventListener("keyup", tasteHoch, true);
  };
}
