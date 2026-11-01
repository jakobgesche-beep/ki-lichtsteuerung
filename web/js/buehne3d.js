// Die 3D-Bühne. Zeigt, was der Simulator aus den DMX-Werten gelesen hat.
// Bühnen-Koordinaten: x rechts, y nach hinten, z oben. In three.js ist y oben,
// deshalb rechnet punkt() um. Winkel rechnet hier niemand: Die Richtung kommt
// fertig vom Server, damit es nur eine einzige Rechnung gibt.
import * as THREE from "three";
import { OrbitControls } from "../vendor/OrbitControls.js";

const punkt = (x, y, z) => new THREE.Vector3(x, z, -y);
const LICHT_REICHWEITE = 12;

export class Buehne3D {
  constructor(huelle, aufbau) {
    this.huelle = huelle;
    this.szene = new THREE.Scene();
    this.szene.background = new THREE.Color(0x101113);
    this.kamera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    this.kamera.position.copy(punkt(0, -13, 6));
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    huelle.append(this.renderer.domElement);
    this.steuerung = new OrbitControls(this.kamera, this.renderer.domElement);
    this.steuerung.target.copy(punkt(0, 1, 1.2));
    this.steuerung.update();
    this.szene.add(new THREE.AmbientLight(0xffffff, 1.2));
    this.lichter = new Map();
    this.masse = aufbau.buehne;
    this.baueBuehne(aufbau);
    for (const geraet of aufbau.geraete) this.baueLicht(geraet);
    this.groesse = new ResizeObserver(() => this.passeGroesseAn());
    this.groesse.observe(huelle);
    this.passeGroesseAn();
    this.laeuft = true;
    this.zeichne();
  }

  kasten(breite, hoehe, tiefe, farbe, mitte, deckkraft = 1) {
    const material = new THREE.MeshLambertMaterial({ color: farbe, transparent: deckkraft < 1, opacity: deckkraft });
    const netz = new THREE.Mesh(new THREE.BoxGeometry(breite, hoehe, tiefe), material);
    netz.position.copy(mitte);
    if (deckkraft < 1) netz.material.depthWrite = false;
    this.szene.add(netz);
    return netz;
  }

  baueBuehne({ buehne, publikum, traverse }) {
    const boden = new THREE.GridHelper(40, 40, 0x2a2c2f, 0x222427);
    this.szene.add(boden);
    const kante = buehne.hoehe_kante_m;
    this.kasten(buehne.breite_m, kante, buehne.tiefe_m, 0x34373b, punkt(0, buehne.tiefe_m / 2, kante / 2));
    // Sperrzone Publikum bis Kopfhöhe
    const breite = publikum.x_bis_m - publikum.x_von_m;
    const tiefe = publikum.y_bis_m - publikum.y_von_m;
    this.kasten(breite, publikum.kopfhoehe_m, tiefe, 0xc0453a,
      punkt((publikum.x_von_m + publikum.x_bis_m) / 2, (publikum.y_von_m + publikum.y_bis_m) / 2, publikum.kopfhoehe_m / 2), 0.1);
    // Traverse mit zwei Stativen
    const stange = traverse.x_bis_m - traverse.x_von_m;
    this.kasten(stange, 0.05, 0.05, 0x77797c, punkt((traverse.x_von_m + traverse.x_bis_m) / 2, traverse.y_m, traverse.hoehe_m));
    for (const x of [traverse.x_von_m, traverse.x_bis_m]) {
      const hoehe = traverse.hoehe_m - kante;
      this.kasten(0.05, hoehe, 0.05, 0x77797c, punkt(x, traverse.y_m, kante + hoehe / 2));
    }
  }

  baueLicht(geraet) {
    const { ort, kegel } = geraet;
    const ankerPunkt = punkt(ort.x, ort.y, ort.z);
    const koerper = this.kasten(0.28, 0.28, 0.28, 0x55585c, ankerPunkt);
    if (ort.ort === "stativ") {
      this.kasten(0.05, ort.z, 0.05, 0x55585c, punkt(ort.x, ort.y, ort.z / 2));
    }
    if (!geraet.leuchtet) return;

    // Ein Kegel mit der Spitze im Ursprung, der nach unten (-y) zeigt.
    const form = new THREE.ConeGeometry(1, 1, 32, 1, true);
    form.translate(0, -0.5, 0);
    const strahl = new THREE.Mesh(form, new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    }));
    strahl.position.copy(ankerPunkt);
    this.szene.add(strahl);

    const fleck = new THREE.Mesh(new THREE.CircleGeometry(1, 32), new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    }));
    fleck.rotation.x = -Math.PI / 2;
    this.szene.add(fleck);
    this.lichter.set(geraet.id, { strahl, fleck, koerper, ort, tangens: Math.tan((kegel / 2) * Math.PI / 180), wert: null });
  }

  // Bekommt pro Gerät {hell, farbe, richtung, strobo_hz}.
  setzeWerte(geraete) {
    for (const wert of geraete) {
      const licht = this.lichter.get(wert.id);
      if (licht) licht.wert = wert;
    }
  }

  bodenHoehe(ort, [rx, ry, rz]) {
    const { breite_m, tiefe_m, hoehe_kante_m: kante } = this.masse;
    if (rz >= -0.05 || ort.z <= kante) return 0;
    const weg = (ort.z - kante) / -rz;
    const x = ort.x + rx * weg;
    const y = ort.y + ry * weg;
    return Math.abs(x) <= breite_m / 2 && y >= 0 && y <= tiefe_m ? kante : 0;
  }

  aktualisiereLichter(zeit) {
    const unten = new THREE.Vector3(0, -1, 0);
    for (const licht of this.lichter.values()) {
      const wert = licht.wert;
      if (!wert) continue;
      let hell = wert.hell;
      if (wert.strobo_hz > 0 && (zeit * wert.strobo_hz) % 1 > 0.3) hell = 0;
      const [rx, ry, rz] = wert.richtung;
      const richtung = punkt(rx, ry, rz);
      // Der Strahl endet auf der Bühne oder am Hallenboden, sonst nach der Reichweite.
      const boden = this.bodenHoehe(licht.ort, wert.richtung);
      const laenge = rz < -0.05 ? Math.min((licht.ort.z - boden) / -rz, LICHT_REICHWEITE) : LICHT_REICHWEITE;
      const radius = Math.max(licht.tangens * laenge, 0.02);
      licht.strahl.quaternion.setFromUnitVectors(unten, richtung);
      licht.strahl.scale.set(radius, laenge, radius);
      licht.strahl.material.color.setRGB(...wert.farbe);
      licht.strahl.material.opacity = 0.22 * hell;
      licht.fleck.position.copy(punkt(licht.ort.x + rx * laenge, licht.ort.y + ry * laenge, boden + 0.02));
      licht.fleck.scale.set(radius, radius, 1);
      licht.fleck.material.color.setRGB(...wert.farbe);
      licht.fleck.material.opacity = rz < -0.05 ? 0.5 * hell : 0;
    }
  }

  passeGroesseAn() {
    const { clientWidth: breite, clientHeight: hoehe } = this.huelle;
    if (!breite || !hoehe) return;
    this.renderer.setSize(breite, hoehe);
    this.kamera.aspect = breite / hoehe;
    this.kamera.updateProjectionMatrix();
  }

  zeichne() {
    if (!this.laeuft) return;
    requestAnimationFrame(() => this.zeichne());
    this.aktualisiereLichter(performance.now() / 1000);
    this.renderer.render(this.szene, this.kamera);
  }

  beenden() {
    this.laeuft = false;
    this.groesse.disconnect();
    this.steuerung.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}
