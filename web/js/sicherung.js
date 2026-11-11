// Setup → Sicherung: die ganze Show als eine Datei. So kommt sie vom MacBook auf den Windows-Laptop
// (und zurück). Der Claude-Schlüssel und die Ton-Einstellung bleiben auf jedem Rechner für sich.
import { api, senden, t, meldung } from "./api.js";

export function sicherungSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div>
        <div class="kasten"><h2>Show sichern</h2>
          <p class="leise">Schreibt eine Datei in deinen Downloads-Ordner. Die nimmst du mit (USB-Stick, Cloud) und lädst sie auf dem anderen Rechner.</p>
          <label class="schalter"><input type="checkbox" id="mit-proben" checked> mit den Proben-Aufnahmen (nötig für Song-Start, braucht mehr Platz)</label>
          <p><button id="sichern" class="haupt">Show sichern</button></p>
          <div id="gesichert"></div>
        </div>
        <div class="kasten"><h2>Show laden</h2>
          <p class="leise">Eine Show-Datei von einem anderen Rechner. Übernommen wird sie beim nächsten Start.
            Vorher sichert das Programm den jetzigen Stand im Ordner „sicherungen“.</p>
          <input type="file" id="datei" accept=".zip,application/zip">
          <div id="geladen"></div>
        </div>
      </div>
      <div>
        <div class="kasten"><h2>Was drin ist</h2>
          <p>Patch und Geräte (auch eigene und eingemessene), Bühne, Positionen, Profile, alle Sequenzen,
            die Fader-Belegung und die Proben mit ihren Teilen.</p>
          <p class="leise">Nicht drin: der Claude-Schlüssel (bleibt auf diesem Rechner) und der gewählte Ton-Eingang
            (heißt auf jedem Rechner anders). DMX ist nach dem Laden wie immer aus.</p>
        </div>
        <div class="kasten"><h2>Automatische Sicherungen</h2>
          <p class="leise">Bei jedem Start sichert das Programm die Show selbst (ohne Aufnahmen, die letzten 10 bleiben).</p>
          <div id="liste" class="leise"></div>
        </div>
      </div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);

  async function status() {
    const stand = await api("/sicherung");
    feld("liste").innerHTML = stand.sicherungen.length
      ? `<p>${t(stand.ordner)}</p><ul>${stand.sicherungen.map((n) => `<li>${t(n)}</li>`).join("")}</ul>` : "Noch keine.";
    if (stand.vorgemerkt) zeigeVorgemerkt("Eine Show-Datei liegt bereit und wird beim nächsten Start geladen.");
  }

  function zeigeVorgemerkt(text) {
    feld("geladen").innerHTML = `<div class="meldung gelb">${t(text)}</div>
      <p><button id="beenden" class="haupt">Programm jetzt schließen</button>
      <span class="leise">Dann einfach wieder öffnen.</span></p>`;
  }

  feld("sichern").onclick = async () => {
    feld("sichern").disabled = true;
    feld("sichern").textContent = "Sichere …";
    try {
      const ergebnis = await senden("/sicherung/export", { mit_proben: feld("mit-proben").checked });
      feld("gesichert").innerHTML = `<div class="meldung">Gesichert (${ergebnis.groesse_mb} MB):<br><code>${t(ergebnis.pfad)}</code></div>
        <p><button id="zeigen" data-pfad="${t(ergebnis.pfad).replace(/"/g, "&quot;")}">Im Ordner zeigen</button></p>`;
      status();
    } finally {
      feld("sichern").disabled = false;
      feld("sichern").textContent = "Show sichern";
    }
  };

  feld("datei").onchange = async () => {
    const datei = feld("datei").files[0];
    if (!datei) return;
    meldung(`Lade „${datei.name}“ hoch …`, "ok");
    const antwort = await fetch("/api/sicherung/import", { method: "POST", body: datei });
    const inhalt = await antwort.json();
    feld("datei").value = "";
    if (!antwort.ok) return meldung(inhalt.fehler ?? "Das hat nicht geklappt.");
    zeigeVorgemerkt(`${inhalt.sequenzen} Sequenzen, ${inhalt.proben} Proben-Aufnahmen. ${inhalt.text}`);
  };

  wurzel.addEventListener("click", async (ereignis) => {
    if (ereignis.target.id === "zeigen") senden("/sicherung/zeigen", { pfad: ereignis.target.dataset.pfad });
    if (ereignis.target.id === "beenden" && confirm("Programm jetzt schließen? Die Lichter gehen aus.")) senden("/beenden");
  });

  status();
  return () => {};
}
