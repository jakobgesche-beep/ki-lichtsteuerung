// Die Befehlszeile unten, wie bei grandMA. Pfeil hoch holt frühere Befehle zurück.
import { senden } from "./api.js";

export function befehlszeile() {
  const eingabe = document.getElementById("befehl");
  const antwort = document.getElementById("antwort");
  const verlauf = [];
  let stelle = 0;

  async function ausfuehren(text) {
    const sequenz = (() => { try { return localStorage.getItem("sequenz"); } catch { return null; } })();
    const roh = await fetch("/api/befehl", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, sequenz }),
    });
    const daten = await roh.json();
    antwort.textContent = daten.antwort ?? daten.fehler;
    antwort.classList.toggle("fehler", !roh.ok);
    document.dispatchEvent(new CustomEvent("pult-geaendert", { detail: daten.status }));
  }

  eingabe.addEventListener("keydown", (ereignis) => {
    if (ereignis.key === "Enter" && eingabe.value.trim()) {
      verlauf.push(eingabe.value);
      stelle = verlauf.length;
      ausfuehren(eingabe.value);
      eingabe.value = "";
    } else if (ereignis.key === "ArrowUp" && verlauf.length) {
      stelle = Math.max(0, stelle - 1);
      eingabe.value = verlauf[stelle];
      ereignis.preventDefault();
    } else if (ereignis.key === "ArrowDown") {
      stelle = Math.min(verlauf.length, stelle + 1);
      eingabe.value = verlauf[stelle] ?? "";
    } else if (ereignis.key === "Escape") {
      eingabe.blur();
    }
  });

  document.getElementById("go-plus").onclick = () => senden("/go/plus");
  document.getElementById("go-minus").onclick = () => senden("/go/minus");
}
