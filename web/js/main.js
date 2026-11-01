// Der Rahmen: Reiter oben, die Seiten liegen jeweils in einer eigenen Datei.
import { liveSeite } from "./live.js";
import { patchSeite } from "./patch.js";
import { katalogSeite } from "./katalog.js";
import { dmxTestSeite } from "./dmxtest.js";

const seiten = [
  ["Live", liveSeite],
  ["Patch", patchSeite],
  ["Katalog", katalogSeite],
  ["DMX-Test", dmxTestSeite],
];

const inhalt = document.getElementById("inhalt");
const reiter = document.getElementById("reiter");
let aufraeumen = null;

function zeige(nummer) {
  aufraeumen?.();
  inhalt.replaceChildren();
  [...reiter.children].forEach((b, i) => b.classList.toggle("aktiv", i === nummer));
  try { localStorage.setItem("reiter", seiten[nummer][0]); } catch {}
  aufraeumen = seiten[nummer][1](inhalt);
}

seiten.forEach(([name], nummer) => {
  const knopf = document.createElement("button");
  knopf.textContent = name;
  knopf.onclick = () => zeige(nummer);
  reiter.append(knopf);
});

let start = 0;
try { start = Math.max(0, seiten.findIndex(([n]) => n === localStorage.getItem("reiter"))); } catch {}
zeige(start);
