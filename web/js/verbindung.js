// Eine einzige Live-Verbindung zum Programm. Jede Seite kann sich dranhängen.
const hoerer = new Set();

function verbinden() {
  const adresse = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live`;
  const leitung = new WebSocket(adresse);
  leitung.onmessage = (nachricht) => {
    const live = JSON.parse(nachricht.data);
    hoerer.forEach((hoerer) => hoerer(live));
  };
  leitung.onclose = () => {
    hoerer.forEach((hoerer) => hoerer(null));
    setTimeout(verbinden, 1000);
  };
}

export function abonnieren(hoerer_) {
  hoerer.add(hoerer_);
  return () => hoerer.delete(hoerer_);
}

verbinden();
