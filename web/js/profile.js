// Veranstaltungsprofile: wählen, ansehen, ändern.
import { api, senden, t } from "./api.js";

export function profileSeite(wurzel) {
  wurzel.innerHTML = `
    <div class="spalten">
      <div class="kasten">
        <h2>Profil für heute</h2>
        <div id="liste"></div>
      </div>
      <div class="kasten" id="detail"></div>
    </div>`;
  const feld = (id) => wurzel.querySelector("#" + id);

  async function laden() {
    const { namen, aktiv } = await api("/profile");
    feld("liste").innerHTML = namen.map((n) => `
      <p class="zeile"><button data-laden="${t(n)}" class="${n === aktiv ? "haupt" : ""}">${t(n)}</button>
      <button data-zeigen="${t(n)}">Ansehen</button></p>`).join("") ||
      `<p class="leise">Noch keine Profile vorhanden.</p>`;
    wurzel.querySelectorAll("[data-laden]").forEach((k) => {
      k.onclick = async () => { await senden(`/profile/${encodeURIComponent(k.dataset.laden)}/laden`); laden(); };
    });
    wurzel.querySelectorAll("[data-zeigen]").forEach((k) => {
      k.onclick = () => zeigen(k.dataset.zeigen);
    });
  }

  async function zeigen(name) {
    const p = await api("/profile/" + encodeURIComponent(name));
    const strobo = p.strobo === "aus" ? {} : p.strobo;
    feld("detail").innerHTML = `
      <h2>${t(p.name)}</h2>
      <label>Palette (Farben mit Komma) <input id="p-palette" value="${t(p.palette.join(", "))}"></label>
      <div class="zeile">
        <label>Max. Helligkeit (0 bis 1) <input id="p-hell" type="number" step="0.05" min="0" max="1" value="${p.max_helligkeit}"></label>
        <label>Beat-Reaktion (0 bis 1) <input id="p-beat" type="number" step="0.05" min="0" max="1" value="${p.beat_reaktion}"></label>
        <label>Bewegung <select id="p-bewegung">
          ${["aus", "langsam", "voll"].map((b) => `<option ${b === p.bewegung ? "selected" : ""}>${b}</option>`).join("")}
        </select></label>
      </div>
      <div class="zeile">
        <label>Strobo: Blitze/s (leer = aus) <input id="p-hz" type="number" step="0.5" min="0" value="${strobo.max_blitze_pro_sekunde ?? ""}"></label>
        <label>Strobo: Dauer in s <input id="p-dauer" type="number" step="1" min="0" value="${strobo.max_dauer_s ?? ""}"></label>
        <label><input id="p-hazer" type="checkbox" ${p.hazer ? "checked" : ""}> Hazer erlaubt</label>
      </div>
      <p class="leise">Die festen Grenzen aus sicherheit.json gelten immer, auch wenn hier mehr steht.</p>
      <button class="haupt" id="p-speichern">Speichern</button>`;
    feld("p-speichern").onclick = async () => {
      const hz = Number(feld("p-hz").value);
      await senden("/profile", {
        ...p, palette: feld("p-palette").value.split(",").map((f) => f.trim()).filter(Boolean),
        max_helligkeit: Number(feld("p-hell").value), beat_reaktion: Number(feld("p-beat").value),
        bewegung: feld("p-bewegung").value, hazer: feld("p-hazer").checked,
        strobo: hz > 0 ? { max_blitze_pro_sekunde: hz, max_dauer_s: Number(feld("p-dauer").value) } : "aus",
      });
      laden();
    };
  }

  laden();
}
