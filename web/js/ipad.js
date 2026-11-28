// Setup → iPad: das iPad-Pult koppeln (QR-Code und PIN), gekoppelte Geräte verwalten.
// Das iPad bedient dann übers WLAN alles wie ein Pult. Patch, Profile bearbeiten, Ton, Schlüssel und
// Sicherung bleiben beim MacBook.
import { api, senden, t, meldung } from "./api.js";

export function ipadSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div>
        <div class="kasten"><h2>iPad koppeln</h2>
          <p class="leise">MacBook und iPad müssen im selben WLAN sein (am besten der Router der Technik-AG, nicht das Schul-WLAN).
            „iPad koppeln“ drücken, dann auf dem iPad mit der Kamera den QR-Code scannen (oder die Adresse in Safari eintippen
            und die PIN eingeben). Die PIN gilt 5 Minuten und für genau ein iPad.</p>
          <p><button id="koppeln" class="haupt">iPad koppeln</button> <button id="zu" hidden>Abbrechen</button></p>
          <div id="fenster"></div>
        </div>
        <div class="kasten"><h2>Gekoppelte iPads</h2>
          <div id="geraete" class="leise">Noch keins.</div>
          <label class="schalter"><input type="checkbox" id="beim-start"> iPad-Pult beim Start der Lichtsteuerung einschalten
            (wenn ein iPad gekoppelt ist)</label>
          <p><button id="an">Netz-Server einschalten</button> <button id="aus">Ausschalten</button> <span id="status" class="leise"></span></p>
        </div>
      </div>
      <div>
        <div class="kasten"><h2>Auf dem iPad, einmalig</h2>
          <ol>
            <li>Nach dem Koppeln in Safari unten auf <b>Teilen</b> → <b>„Zum Home-Bildschirm“</b>. Ab dann das Lichtpult über das Symbol öffnen.</li>
            <li>Einstellungen → Anzeige &amp; Helligkeit → <b>Automatische Sperre: Nie</b>.</li>
            <li>Einstellungen → Multitasking &amp; Gesten → <b>Gesten aus</b> (sonst wechseln vier Finger auf vier Fadern die App).</li>
            <li>Am Abend: Bedienungshilfen → <b>Geführter Zugriff</b> (dreimal Seitentaste), Ladekabel dran.</li>
          </ol>
          <p class="leise">Fällt das iPad oder das WLAN aus, läuft das Licht am MacBook einfach weiter (Automatik, laufende Fader).
            Gehaltene Tasten (Flash, Weiß voll) lässt das MacBook nach 4 Sekunden ohne Verbindung von selbst los.</p>
          <p class="leise">Die Verbindung ist nicht verschlüsselt: nur im eigenen WLAN benutzen. Ohne Kopplung kann niemand etwas schalten.</p>
        </div>
      </div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);
  let uhr = null;

  function zeigen(z) {
    feld("status").textContent = z.an ? `an (Port ${z.port}), ${z.verbunden} iPad${z.verbunden === 1 ? "" : "s"} verbunden` : "aus";
    feld("beim-start").checked = z.beim_start;
    feld("zu").hidden = !z.fenster.offen;
    feld("fenster").innerHTML = z.fenster.offen ? `
      <div class="ipad-koppeln">
        <div class="qr">${z.qr || ""}</div>
        <div>
          <p>PIN: <b class="pin">${t(z.fenster.pin)}</b> <span class="leise">(noch ${Math.floor(z.fenster.rest_s / 60)}:${String(z.fenster.rest_s % 60).padStart(2, "0")})</span></p>
          ${z.links.map((l) => `<p><span class="leise">${l.art === "name" ? "Adresse (bleibt gleich):" : "oder über die IP:"}</span><br><code>${t(l.link.replace(/\?pin=\d+/, ""))}</code></p>`).join("")}
        </div>
      </div>` : (z.links.length ? `<p class="leise">Adresse fürs iPad: <code>${t(z.links[0].link)}</code></p>` : "");
    feld("geraete").innerHTML = z.geraete.length ? `<table><tr><th>Name</th><th>gekoppelt</th><th>zuletzt</th><th></th></tr>${z.geraete.map((g) => `
      <tr><td>${t(g.name)}</td><td>${t(g.seit)}</td><td>${t(g.zuletzt)}</td><td><button class="gefahr" data-weg="${g.nummer}">Entfernen</button></td></tr>`).join("")}</table>` : "Noch keins.";
    wurzel.querySelectorAll("[data-weg]").forEach((knopf) => {
      knopf.onclick = async () => { if (confirm("Dieses iPad entfernen? Es muss danach neu gekoppelt werden.")) zeigen(await senden("/netz/entfernen", { nummer: Number(knopf.dataset.weg) })); };
    });
  }
  async function laden() { try { zeigen(await api("/netz")); } catch {} }

  feld("koppeln").onclick = async () => { try { zeigen(await senden("/netz/koppeln")); meldung("Kopplungsfenster offen: QR-Code mit dem iPad scannen.", "ok"); } catch {} };
  feld("zu").onclick = async () => zeigen(await senden("/netz/fenster_zu"));
  feld("beim-start").onchange = async () => zeigen(await senden("/netz/beim_start", { an: feld("beim-start").checked }));
  feld("an").onclick = async () => zeigen(await senden("/netz/an"));
  feld("aus").onclick = async () => zeigen(await senden("/netz/aus"));
  laden();
  uhr = setInterval(laden, 1000);
  return () => clearInterval(uhr);
}
