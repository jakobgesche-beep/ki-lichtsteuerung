// Live-Seite: 3D-Bühne und Bedienung am Abend.
import { api, senden, t } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";
import { executorLeiste } from "./executoren.js";

export function liveSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="live">
      <div class="drei-d" id="drei"></div>
      <div id="seite">
        <div class="kasten">
          <h2>Profil</h2>
          <select id="profil" style="width:100%"></select>
          <div id="status" class="leise" style="margin-top:8px"></div>
        </div>
        <div class="kasten">
          <h2>Ton <span id="beat" class="beat"></span></h2>
          <label>Quelle <select id="quelle"></select></label>
          <input id="datei" type="file" accept="audio/*" hidden>
          <div class="leise" id="ton"></div>
          <div id="ton-hinweis"></div>
          <div class="pegel"><span>Bass</span><i id="m-bass"></i></div>
          <div class="pegel"><span>Energie</span><i id="m-energie"></i></div>
        </div>
        <div id="meldungen"></div>
      </div>
    </div>
    <div class="kasten"><h2 class="zeile" style="justify-content:space-between">Executoren
      <label class="schalter"><input type="checkbox" id="automatik"> Musik-Automatik</label></h2>
      <div id="executoren"></div></div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  let buehne = null;
  let beendet = false;
  let letzterBeat = 0;
  const leiste = executorLeiste(feld("executoren"));

  async function quellenLaden() {
    const { eingaenge, dateien } = await api("/audio");
    feld("quelle").innerHTML = `
      <option value="aus">Aus</option>
      <option value="test">Testsignal (120 BPM)</option>
      ${eingaenge.map((e) => `<option value="eingang:${e.nummer}">Eingang: ${t(e.name)}</option>`).join("")}
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

  function zeigen(live) {
    if (!live) return;
    buehne?.setzeWerte(live.geraete);
    feld("status").innerHTML = `${live.dmx_ein ? "DMX-Ausgabe: eingeschaltet" : "DMX-Ausgabe: aus (Simulator)"}<br>
      ${t(live.engine)}<br>Version ${t(live.version)}`;
    if (feld("profil").value !== live.profil && !feld("profil").matches(":focus")) feld("profil").value = live.profil;
    feld("ton-hinweis").innerHTML = live.audio.werte && !live.reagiert
      ? `<div class="meldung gelb" style="margin-top:8px">Dieses Profil reagiert nicht auf Musik. Oben ein anderes wählen.</div>` : "";
    leiste.zeigen(live.pult);
    if (!feld("automatik").matches(":focus")) feld("automatik").checked = live.automatik;
    const ton = live.audio;
    if (ton.quelle === "Testsignal" && feld("quelle").value === "aus") feld("quelle").value = "test";
    const werte = ton.werte;
    feld("ton").textContent = ton.fehler ?? (werte
      ? `${Math.round(werte.tempo_bpm)} BPM · Beat-Erkennung: ${ton.erkennung}`
      : "Kein Ton");
    feld("m-bass").style.width = `${(werte?.bass ?? 0) * 100}%`;
    feld("m-energie").style.width = `${(werte?.energie ?? 0) * 100}%`;
    if (ton.beats !== letzterBeat) {
      letzterBeat = ton.beats;
      feld("beat").animate([{ opacity: 1 }, { opacity: 0.15 }], 180);
    }
    feld("meldungen").innerHTML = live.meldungen.map((m) => `<div class="meldung gelb">${t(m)}</div>`).join("");
  }

  api("/profile").then(({ namen, aktiv }) => {
    feld("profil").innerHTML = [...new Set([aktiv, ...namen])].map((n) => `<option>${t(n)}</option>`).join("");
    feld("profil").value = aktiv;
  });
  feld("profil").onchange = () => senden(`/profile/${encodeURIComponent(feld("profil").value)}/laden`);
  feld("quelle").onchange = quelleWaehlen;
  feld("datei").onchange = dateiHochladen;
  feld("automatik").onchange = () => senden("/automatik", { an: feld("automatik").checked });
  quellenLaden();

  api("/buehne").then((aufbau) => {
    if (beendet) return;
    buehne = new Buehne3D(feld("drei"), aufbau);
  });

  const abmelden = abonnieren(zeigen);

  return () => {
    beendet = true;
    abmelden();
    buehne?.beenden();
  };
}
