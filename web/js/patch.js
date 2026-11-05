// Patch-Assistent: Ablauf wie bei grandMA3, in fünf Schritten.
import { api, senden, t } from "./api.js";

export function patchSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div class="kasten">
        <h2>Gerät patchen</h2>
        <label>1. Gerätetyp suchen <input id="suche" placeholder="zum Beispiel mh-x25"></label>
        <div class="liste" id="treffer"></div>
        <label>2. Modus <select id="modus"></select></label>
        <div class="zeile">
          <label>3. Anzahl <input id="anzahl" type="number" min="1" value="1"></label>
          <label style="flex:1">Name <input id="name" placeholder="PAR 1–6"></label>
        </div>
        <label>Gruppen nach Funktion <select id="gruppen" multiple size="5"></select></label>
        <label>4. Startadresse (leer = nächste freie) <input id="start" type="number" min="1" max="512"></label>
        <div class="zeile">
          <label>5. Ort <select id="ort">
            <option value="traverse">Traverse</option><option value="stativ">Stativ</option><option value="boden">Boden</option>
          </select></label>
          <label>Montage <select id="montage">
            <option value="">Standard</option><option value="haengend">hängend</option><option value="stehend">stehend</option>
          </select></label>
        </div>
        <button class="haupt" id="hinzu" disabled>Patchen</button>
      </div>
      <div>
        <div id="meldungen"></div>
        <div class="kasten tabelle-huelle">
          <h2 class="zeile" style="justify-content:space-between">Gepatchte Geräte
            <span><button id="plan-zeigen">Patchplan</button> <button id="plan-drucken">Drucken</button></span></h2>
          <div id="plan" hidden></div>
          <table id="tabelle"></table>
        </div>
      </div>
    </div>`;

  const feld = (id) => wurzel.querySelector("#" + id);
  let gewaehlt = null;

  async function suchen() {
    const { geraete } = await api("/katalog?suche=" + encodeURIComponent(feld("suche").value));
    feld("treffer").innerHTML = "";
    for (const geraet of geraete) {
      const zeile = document.createElement("div");
      zeile.textContent = `${geraet.hersteller} ${geraet.name}`;
      zeile.onclick = () => waehlen(geraet, zeile);
      feld("treffer").append(zeile);
    }
  }

  function waehlen(geraet, zeile) {
    gewaehlt = geraet;
    wurzel.querySelectorAll("#treffer div").forEach((d) => d.classList.remove("gewaehlt"));
    zeile.classList.add("gewaehlt");
    feld("modus").innerHTML = geraet.modi
      .map((m) => `<option value="${t(m.name)}">${t(m.name)} (${m.kanaele} Kanäle)</option>`).join("");
    feld("name").value = feld("name").value || geraet.name;
    feld("hinzu").disabled = false;
  }

  function zeigen(patch) {
    feld("gruppen").innerHTML = patch.gruppen.map((g) => `<option>${t(g)}</option>`).join("");
    feld("meldungen").innerHTML =
      patch.probleme.map((p) => `<div class="meldung rot">${t(p.text)}</div>`).join("") +
      patch.warnungen.map((w) => `<div class="meldung gelb">${t(w)}</div>`).join("");
    feld("tabelle").innerHTML = `
      <tr><th>Name</th><th>Gerätetyp</th><th>Modus</th><th>Adresse</th><th>Gruppen</th><th>Ort</th><th></th></tr>` +
      patch.geraete.map((g) => `
      <tr class="${g.problem ? "rot" : ""}">
        <td>${t(g.name)}</td>
        <td>${t(g.typ_name)}${g.handbuch_geprueft ? "" : ` <span class="leise" title="Noch nicht mit dem Handbuch abgeglichen">(ungeprüft)</span>`}</td>
        <td>${t(g.modus)}</td>
        <td><input type="number" min="1" max="512" value="${g.adresse}" data-adresse="${t(g.id)}"> <span class="leise">bis ${g.letzte_adresse}</span></td>
        <td>${t(g.gruppen.join(", "))}</td>
        <td><select data-ort="${t(g.id)}">${["traverse", "stativ", "boden"].map((o) =>
          `<option value="${o}" ${o === g.ort.ort ? "selected" : ""}>${{ traverse: "Traverse (hängend)", stativ: "Stativ", boden: "Boden" }[o]}</option>`).join("")}</select></td>
        <td><button data-tausch="${t(g.id)}">Tauschen</button> <button class="gefahr" data-weg="${t(g.id)}">Entfernen</button></td>
      </tr>`).join("");
    wurzel.querySelectorAll("[data-adresse]").forEach((eingabe) => {
      eingabe.onchange = async () => {
        try { zeigen(await api("/patch/" + eingabe.dataset.adresse, { method: "PATCH", daten: { adresse: Number(eingabe.value) } })); }
        catch { laden(); }
      };
    });
    wurzel.querySelectorAll("[data-ort]").forEach((auswahl) => {
      auswahl.onchange = async () => {
        zeigen(await api("/patch/" + auswahl.dataset.ort, { method: "PATCH", daten: { ort: auswahl.value } }));
      };
    });
    wurzel.querySelectorAll("[data-weg]").forEach((knopf) => {
      knopf.onclick = async () => {
        if (confirm("Gerät aus dem Patch entfernen?")) zeigen(await api("/patch/" + knopf.dataset.weg, { method: "DELETE" }));
      };
    });
    wurzel.querySelectorAll("[data-tausch]").forEach((knopf) => {
      knopf.onclick = async () => {
        if (!gewaehlt) return alert("Links zuerst den neuen Gerätetyp und Modus auswählen.");
        zeigen(await senden(`/patch/${knopf.dataset.tausch}/tausch`, { typ: gewaehlt.id, modus: feld("modus").value }));
      };
    });
  }

  const laden = async () => zeigen(await api("/patch"));

  feld("plan-zeigen").onclick = async () => {
    const plan = feld("plan");
    plan.hidden = !plan.hidden;
    if (plan.hidden) return;
    const html = await (await fetch("/patchplan")).text();
    const dokument = new DOMParser().parseFromString(html, "text/html");
    plan.innerHTML = `<div class="patchplan">${dokument.querySelector("style").outerHTML}${dokument.body.innerHTML}</div>`;
    plan.querySelector(".nicht-drucken")?.remove();
  };
  // In der App gibt es keinen Druckdialog, deshalb öffnet sich der Plan im Browser.
  feld("plan-drucken").onclick = () => senden("/patchplan/oeffnen");

  feld("suche").oninput = suchen;
  feld("hinzu").onclick = async () => {
    const start = feld("start").value;
    zeigen(await senden("/patch", {
      typ: gewaehlt.id, modus: feld("modus").value, anzahl: Number(feld("anzahl").value),
      name: feld("name").value, start: start ? Number(start) : null,
      gruppen: [...feld("gruppen").selectedOptions].map((o) => o.value),
      ort: feld("ort").value, montage: feld("montage").value,
    }));
    feld("start").value = "";
  };

  suchen();
  laden();
}
