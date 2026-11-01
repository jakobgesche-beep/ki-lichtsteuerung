// Kleine Helfer, die alle Seiten benutzen.

export async function api(pfad, optionen = {}) {
  const anfrage = { ...optionen };
  if (optionen.daten !== undefined) {
    anfrage.body = JSON.stringify(optionen.daten);
    anfrage.headers = { "Content-Type": "application/json" };
  }
  const antwort = await fetch("/api" + pfad, anfrage);
  const inhalt = await antwort.json();
  if (!antwort.ok) {
    meldung(inhalt.fehler || "Das hat nicht geklappt.");
    throw new Error(inhalt.fehler);
  }
  return inhalt;
}

export const senden = (pfad, daten = {}) => api(pfad, { method: "POST", daten });

// Baut HTML-Text sicher zusammen: Werte aus Dateien werden nie als HTML gelesen.
export function t(text) {
  const element = document.createElement("span");
  element.textContent = text ?? "";
  return element.innerHTML;
}

export function meldung(text) {
  document.getElementById("toast")?.remove();
  const element = document.createElement("div");
  element.id = "toast";
  element.textContent = text;
  document.body.append(element);
  setTimeout(() => element.remove(), 6000);
}
