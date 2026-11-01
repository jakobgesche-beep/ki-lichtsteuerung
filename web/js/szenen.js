// Szenen bauen, in der Vorschau ansehen, übernehmen. Dazu Cuelisten und Fader.
import { api, senden, t, meldung } from "./api.js";
import { Buehne3D } from "./buehne3d.js";
import { abonnieren } from "./verbindung.js";

const optionen = (liste, gewaehlt) => liste.map((w) => {
  const [wert, text] = Array.isArray(w) ? w : [w, w];
  return `<option value="${t(wert)}" ${wert === gewaehlt ? "selected" : ""}>${t(text)}</option>`;
}).join("");

export function szenenSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="live">
      <div>
        <div class="kasten">
          <h2>Szene</h2>
          <div class="zeile">
            <label style="flex:1">Name <input id="s-name" placeholder="zum Beispiel Bühne blau"></label>
            <label style="flex:1">Vorhandene Szene <select id="s-liste"></select></label>
          </div>
          <div class="tabelle-huelle"><table id="s-werte"></table></div>
          <p class="zeile">
            <button id="s-zeile">Zeile hinzufügen</button>
            <button id="s-vorschau">In Vorschau zeigen</button>
            <button id="s-uebernehmen" class="haupt" disabled>Übernehmen</button>
            <button id="s-verwerfen" disabled>Verwerfen</button>
            <button id="s-loeschen" class="gefahr">Szene löschen</button>
          </p>
          <div id="s-hinweise"></div>
        </div>
        <div class="kasten">
          <h2>Cueliste</h2>
          <div class="zeile">
            <label style="flex:1">Name <input id="c-name"></label>
            <label style="flex:1">Vorhandene Liste <select id="c-liste"></select></label>
          </div>
          <div class="tabelle-huelle"><table id="c-tabelle"></table></div>
          <p class="zeile"><button id="c-zeile">Cue hinzufügen</button>
          <button id="c-speichern" class="haupt">Liste speichern</button></p>
          <p class="leise">Wartezeit 0: Der nächste Cue kommt erst mit „Weiter“. Sonst geht es nach Einblenden plus Wartezeit von allein weiter.</p>
        </div>
      </div>
      <div>
        <div class="drei-d klein" id="drei"></div>
        <p class="leise">Vorschau: Das hier geht nicht an die Lichter.</p>
        <div class="kasten"><h2>Fader belegen</h2><div id="f-liste"></div></div>
      </div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  let info = null;
  let buehne = null;
  let beendet = false;
  let vorschauDa = false;

  function wertZeile(w = { gruppe: info.gruppen[0], helligkeit: 1 }) {
    const ziel = w.geraet ? "g:" + w.geraet : "z:" + w.gruppe;
    const ziele = [
      ...info.gruppen.map((g) => ["z:" + g, "Gruppe " + g]),
      ...info.geraete.map((g) => ["g:" + g.id, g.name]),
    ];
    return `<tr>
      <td><select data-k="ziel">${optionen(ziele, ziel)}</select></td>
      <td><select data-k="farbe"><option value="">-</option>${optionen(info.farben, w.farbe)}</select></td>
      <td><input data-k="helligkeit" type="number" min="0" max="100" step="5" value="${Math.round((w.helligkeit ?? 1) * 100)}"> %</td>
      <td><select data-k="position"><option value="">-</option>${optionen(info.positionen, w.position)}</select></td>
      <td><select data-k="gobo"><option value="">-</option>${optionen(info.gobos, w.gobo)}</select></td>
      <td><button data-weg>×</button></td></tr>`;
  }

  function werteZeigen(werte) {
    feld("s-werte").innerHTML = `<tr><th>Ziel</th><th>Farbe</th><th>Helligkeit</th><th>Position</th><th>Gobo</th><th></th></tr>` +
      werte.map(wertZeile).join("");
  }

  function szeneLesen() {
    const werte = [...wurzel.querySelectorAll("#s-werte tr:not(:first-child)")].map((zeile) => {
      const wert = (k) => zeile.querySelector(`[data-k=${k}]`).value;
      const eintrag = wert("ziel").startsWith("g:") ? { geraet: wert("ziel").slice(2) } : { gruppe: wert("ziel").slice(2) };
      eintrag.helligkeit = Number(wert("helligkeit")) / 100;
      for (const feldName of ["farbe", "position", "gobo"]) if (wert(feldName)) eintrag[feldName] = wert(feldName);
      return eintrag;
    });
    return { name: feld("s-name").value.trim(), werte };
  }

  async function szenenListe() {
    info = await api("/szenen");
    feld("s-liste").innerHTML = `<option value="">(neu)</option>` + optionen(info.namen);
    wurzel.querySelectorAll("[data-c=szene]").forEach((auswahl) => {
      const wert = auswahl.value;
      auswahl.innerHTML = optionen(info.namen, wert);
    });
    faderZeigen();
  }

  function setzeEntwurf(da) {
    vorschauDa = da;
    feld("s-uebernehmen").disabled = !da;
    feld("s-verwerfen").disabled = !da;
  }

  function cueZeile(c = {}) {
    return `<tr>
      <td><input data-c="name" value="${t(c.name ?? "")}"></td>
      <td><select data-c="szene">${optionen(info.namen, c.szene)}</select></td>
      <td><input data-c="einblenden_s" type="number" min="0" step="0.5" value="${c.einblenden_s ?? 2}"></td>
      <td><input data-c="ausblenden_s" type="number" min="0" step="0.5" value="${c.ausblenden_s ?? 2}"></td>
      <td><input data-c="warten_s" type="number" min="0" step="0.5" value="${c.warten_s ?? 0}"></td>
      <td><button data-hoch>↑</button> <button data-weg>×</button></td></tr>`;
  }

  function cuesZeigen(cues) {
    feld("c-tabelle").innerHTML = `<tr><th>Cue</th><th>Szene</th><th>Ein (s)</th><th>Aus (s)</th><th>Warten (s)</th><th></th></tr>` +
      cues.map(cueZeile).join("");
  }

  function cuesLesen() {
    return [...wurzel.querySelectorAll("#c-tabelle tr:not(:first-child)")].map((zeile) => {
      const wert = (k) => zeile.querySelector(`[data-c=${k}]`).value;
      return { name: wert("name"), szene: wert("szene"), einblenden_s: Number(wert("einblenden_s")),
        ausblenden_s: Number(wert("ausblenden_s")), warten_s: Number(wert("warten_s")) };
    });
  }

  async function listenLaden() {
    const { namen } = await api("/cuelisten");
    feld("c-liste").innerHTML = `<option value="">(neu)</option>` + optionen(namen);
  }

  let faderStand = [];
  function faderZeigen() {
    const wahl = [["frei", "frei"],
      ...info.gruppen.map((g) => ["gruppe:" + g, "Gruppe " + g]),
      ...info.namen.map((n) => ["szene:" + n, "Szene " + n])];
    feld("f-liste").innerHTML = faderStand.map((f, i) => {
      const wert = f.art === "frei" ? "frei" : `${f.art}:${f.ziel}`;
      return `<label>Fader ${i + 1} <select data-f="${i}">${optionen(wahl, wert)}</select></label>`;
    }).join("");
    wurzel.querySelectorAll("[data-f]").forEach((auswahl) => {
      auswahl.onchange = async () => {
        const [art, ziel] = auswahl.value.split(/:(.*)/s);
        const antwort = await senden(`/fader/${auswahl.dataset.f}/belegen`, { art, ziel });
        faderStand = antwort.fader;
      };
    });
  }

  // Tabellen-Knöpfe an einer Stelle: Sie gehören zu Zeilen, die neu entstehen.
  wurzel.addEventListener("click", (ereignis) => {
    const zeile = ereignis.target.closest("tr");
    if (ereignis.target.matches("[data-weg]")) zeile.remove();
    if (ereignis.target.matches("[data-hoch]") && zeile.previousElementSibling?.previousElementSibling) {
      zeile.previousElementSibling.before(zeile);
    }
  });

  feld("s-zeile").onclick = () => feld("s-werte").tBodies[0].insertAdjacentHTML("beforeend", wertZeile());
  feld("s-liste").onchange = async () => {
    const name = feld("s-liste").value;
    if (!name) return;
    const szene = await api("/szenen/" + encodeURIComponent(name));
    feld("s-name").value = szene.name;
    werteZeigen(szene.werte);
  };
  feld("s-vorschau").onclick = async () => {
    const antwort = await senden("/vorschau", { art: "szene", inhalt: szeneLesen() });
    feld("s-hinweise").innerHTML = antwort.meldungen.map((m) => `<div class="meldung gelb">${t(m)}</div>`).join("");
    setzeEntwurf(true);
  };
  feld("s-uebernehmen").onclick = async () => {
    const { name } = await senden("/vorschau/uebernehmen");
    setzeEntwurf(false);
    feld("s-hinweise").innerHTML = "";
    await szenenListe();
    feld("s-liste").value = name;
  };
  feld("s-verwerfen").onclick = async () => {
    await api("/vorschau", { method: "DELETE" });
    setzeEntwurf(false);
    feld("s-hinweise").innerHTML = "";
  };
  feld("s-loeschen").onclick = async () => {
    const name = feld("s-liste").value;
    if (!name) return meldung("Erst oben eine vorhandene Szene wählen.");
    if (confirm(`Szene „${name}“ löschen?`)) {
      await api("/szenen/" + encodeURIComponent(name), { method: "DELETE" });
      await szenenListe();
    }
  };
  feld("c-zeile").onclick = () => {
    if (!info.namen.length) return meldung("Zuerst eine Szene übernehmen.");
    feld("c-tabelle").tBodies[0].insertAdjacentHTML("beforeend", cueZeile());
  };
  feld("c-liste").onchange = async () => {
    const name = feld("c-liste").value;
    if (!name) return;
    const liste = await api("/cuelisten/" + encodeURIComponent(name));
    feld("c-name").value = liste.name;
    cuesZeigen(liste.cues);
  };
  feld("c-speichern").onclick = async () => {
    await senden("/cuelisten", { name: feld("c-name").value.trim(), cues: cuesLesen() });
    await listenLaden();
    feld("c-liste").value = feld("c-name").value.trim();
  };

  const abmelden = abonnieren((live) => {
    if (!live) return;
    faderNeu(live.fader);
    buehne?.setzeWerte(live.vorschau.geraete ?? live.geraete);
  });
  function faderNeu(fader) {
    if (faderStand.length === 0 && info) {
      faderStand = fader;
      faderZeigen();
    }
  }

  (async () => {
    await szenenListe();
    werteZeigen([{ gruppe: info.gruppen[0], farbe: "blau", helligkeit: 0.8 }]);
    cuesZeigen([]);
    listenLaden();
    const aufbau = await api("/buehne");
    if (!beendet) buehne = new Buehne3D(feld("drei"), aufbau);
  })();

  return () => {
    beendet = true;
    abmelden();
    buehne?.beenden();
    if (vorschauDa) api("/vorschau", { method: "DELETE" });
  };
}
