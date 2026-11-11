// View "Live": 3D-Bühne, Cue-Liste des Haupt-Executors, Ton, Profil und Executoren.
import { api, senden, t } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";
import { executorLeiste } from "./executoren.js";

export function liveSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="live">
      <section class="fenster"><header>Bühne <span class="leise" id="engine"></span></header>
        <div class="drei-d" id="drei"></div></section>
      <div>
        <section class="fenster"><header><span id="cue-titel">Cue-Liste</span><span class="leise">Klick = Goto</span></header>
          <div class="inhalt tabelle-huelle"><table class="cueliste" id="cues"></table></div></section>
        <section class="fenster"><header>Ton <span id="beat" class="beat"></span></header>
          <div class="inhalt">
            <label>Quelle <select id="quelle"></select></label>
            <input id="datei" type="file" accept="audio/*" hidden>
            <div class="leise" id="ton"></div>
            <div class="pegel"><span>Bass</span><i id="m-bass"></i></div>
            <div class="pegel"><span>Energie</span><i id="m-energie"></i></div>
          </div></section>
        <section class="fenster"><header>Profil
          <label class="schalter"><input type="checkbox" id="automatik"> Musik-Automatik</label></header>
          <div class="inhalt">
            <select id="profil" style="width:100%"></select>
            <div id="ton-hinweis"></div>
            <p class="leise" id="version" style="margin:8px 0 0"></p>
          </div></section>
        <div id="meldungen"></div>
      </div>
    </div>
    <section class="fenster"><header>Executoren</header><div class="inhalt"><div id="executoren"></div></div></section>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  const leiste = executorLeiste(feld("executoren"));
  let buehne = null;
  let beendet = false;
  let letzterBeat = 0;
  let cueStand = "";

  async function quellenLaden() {
    const { eingaenge, dateien } = await api("/audio");
    feld("quelle").innerHTML = `
      <option value="aus">Aus</option>
      <option value="test">Testsignal (120 BPM)</option>
      <option value="test_drop">Testsong mit Aufbau und Drop</option>
      ${eingaenge.map((e) => `<option value="eingang:${e.nummer}" data-name="${t(e.name).replace(/"/g, "&quot;")}">Eingang: ${t(e.name)}</option>`).join("")}
      ${dateien.map((d) => `<option value="datei:${t(d)}">Datei: ${t(d)}</option>`).join("")}
      <option value="neu">Audiodatei wählen …</option>`;
  }

  async function quelleWaehlen() {
    const [art, wert] = feld("quelle").value.split(/:(.*)/s);
    if (art === "neu") return feld("datei").click();
    const auftrag = { art };
    if (art === "datei") auftrag.name = wert;
    if (art === "eingang") auftrag.geraet = Number(wert);
    try { await senden("/audio/quelle", auftrag); } catch { feld("quelle").value = "aus"; }
  }

  async function dateiHochladen() {
    const datei = feld("datei").files[0];
    if (!datei) return;
    await fetch("/api/audio/hochladen?name=" + encodeURIComponent(datei.name), { method: "POST", body: datei });
    await quellenLaden();
    feld("quelle").value = "datei:" + datei.name;
    quelleWaehlen();
  }

  function cuesZeigen(pult) {
    const executor = pult.haupt_info;
    const cues = pult.haupt_cues;
    const stand = JSON.stringify([executor.nummer, executor.sequenz, cues, executor.index]);
    if (stand === cueStand) return;
    cueStand = stand;
    const platz = executor.song ? "Song" : `Fader ${executor.nummer}`;
    feld("cue-titel").textContent = executor.sequenz ? `${platz}: ${executor.sequenz}` : `${platz}: frei`;
    feld("cues").innerHTML = cues.map((name, i) => `
      <tr data-goto="${i}" class="${i === executor.index ? "aktiv" : ""} ${i === executor.index + 1 ? "naechster" : ""}">
        <td style="width:34px">${i + 1}</td><td>${t(name)}</td></tr>`).join("")
      || `<tr><td class="leise">Eine Sequenz unten auf einen Executor legen, dann Go+.</td></tr>`;
    feld("cues").dataset.executor = executor.nummer;
  }

  function zeigen(live) {
    if (!live) return;
    buehne?.setzeWerte(live.geraete);
    leiste.zeigen(live.pult);
    cuesZeigen(live.pult);
    feld("engine").textContent = live.automatik ? live.engine : "Automatik aus";
    if (!feld("automatik").matches(":focus")) feld("automatik").checked = live.automatik;
    if (feld("profil").value !== live.profil && !feld("profil").matches(":focus")) feld("profil").value = live.profil;
    const hinweis = live.audio.werte && !live.reagiert
      ? `<div class="meldung gelb" style="margin:8px 0 0">Dieses Profil reagiert nicht auf Musik.</div>` : "";
    if (feld("ton-hinweis").innerHTML !== hinweis) feld("ton-hinweis").innerHTML = hinweis;
    if (!feld("version").firstChild) {
      feld("version").innerHTML = `Version ${t(live.version)} · <button data-update-suchen class="klein">Nach Update suchen</button> <span></span>`;
    }
    const updateText = live.update.zustand === "sucht" ? "sucht …" : live.update.zustand === "laedt" ? `lädt ${live.update.neu} …` : live.update.text;
    const span = feld("version").querySelector("span");
    if (span.textContent !== updateText) span.textContent = updateText;
    const ton = live.audio;
    const werte = ton.werte;
    if (!feld("quelle").matches(":focus")) {
      // Die Auswahl zeigt, was wirklich läuft (auch nach einem Neustart, wenn der Eingang von selbst aufging)
      const laeuft = ton.quelle?.startsWith("Eingang: ")
        ? [...feld("quelle").options].find((o) => o.dataset.name === ton.quelle.slice(9))?.value
        : ton.quelle === "Testsignal" ? "test" : ton.quelle === "aus" ? "aus" : null;
      if (laeuft && feld("quelle").value !== laeuft) feld("quelle").value = laeuft;
    }
    feld("ton").textContent = ton.fehler ?? (werte ? `${Math.round(werte.tempo_bpm)} BPM · ${ton.quelle}` : "Kein Ton");
    feld("m-bass").style.width = `${(werte?.bass ?? 0) * 100}%`;
    feld("m-energie").style.width = `${(werte?.energie ?? 0) * 100}%`;
    if (ton.beats !== letzterBeat) {
      letzterBeat = ton.beats;
      feld("beat").animate([{ opacity: 1 }, { opacity: 0.15 }], 180);
    }
    const meldungen = live.meldungen.map((m) => `<div class="meldung gelb">${t(m)}</div>`).join("");
    if (feld("meldungen").dataset.inhalt !== meldungen) {
      feld("meldungen").innerHTML = meldungen;
      feld("meldungen").dataset.inhalt = meldungen;
    }
  }

  wurzel.addEventListener("click", (ereignis) => {
    if (ereignis.target.matches("[data-update-suchen]")) senden("/update/suchen");
    const zeile = ereignis.target.closest("[data-goto]");
    if (zeile) senden(`/executor/${feld("cues").dataset.executor}/goto`, { index: Number(zeile.dataset.goto) });
  });
  feld("automatik").onchange = () => senden("/automatik", { an: feld("automatik").checked });
  feld("quelle").onchange = quelleWaehlen;
  feld("datei").onchange = dateiHochladen;
  feld("profil").onchange = () => senden(`/profile/${encodeURIComponent(feld("profil").value)}/laden`);
  api("/profile").then(({ namen, aktiv }) => {
    feld("profil").innerHTML = [...new Set([aktiv, ...namen])].map((n) => `<option>${t(n)}</option>`).join("");
    feld("profil").value = aktiv;
  });
  quellenLaden();
  api("/buehne").then((aufbau) => { if (!beendet) buehne = new Buehne3D(feld("drei"), aufbau); });

  const abmelden = abonnieren(zeigen);
  return () => { beendet = true; abmelden(); buehne?.beenden(); };
}
