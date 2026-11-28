"""Aufbau-Checkliste zum Ausdrucken: Schritt für Schritt am Veranstaltungsort, mit den eigenen Geräten und Adressen.

Erzeugt aus dem aktuellen Stand (Patch, Ton-Eingang, iPad, gemerkter Soundcheck), damit auf dem Papier steht, was
an diesem Abend wirklich gilt. Ein Kästchen pro Schritt zum Abhaken.
"""
from __future__ import annotations

import datetime
from html import escape

from . import patchplan
from .audio.rollen import ROLLEN, ist_x32_usb
from .version import VERSION


def _schritt(text: str, klein: str = "") -> str:
    return f'<li class="schritt"><span class="kasten"></span><span>{text}{f"<small>{klein}</small>" if klein else ""}</span></li>'


def _ton_stand(show) -> list:
    """Was das Programm über den Ton schon weiß (steht auf dem Papier als Hinweis)."""
    auftrag = show.audio_auftrag or {}
    teile = []
    if auftrag.get("art") == "eingang":
        name = auftrag.get("name") or "?"
        teile.append(f"Gewählt: <b>Eingang {escape(name)}</b>, Summe auf Kanal "
                     f"{escape('+'.join(str(k) for k in auftrag.get('kanaele') or [1]))}.")
        rollen = auftrag.get("rollen") or {}
        if rollen:
            teile.append("Rollen: " + escape(", ".join(f"{ROLLEN.get(r, r)} {'+'.join(str(k) for k in ks)}"
                                                      for r, ks in rollen.items())) + ".")
        if not ist_x32_usb(name):
            teile.append("Das ist nicht das X32 (X-USB). Am Abend den X32-Eingang wählen.")
    else:
        teile.append("Noch kein Ton-Eingang gewählt.")
    gemerkt = [n for n in show.audio.bezuege if ist_x32_usb(n)]
    teile.append("Lautstärke der Band ist gemerkt (Soundcheck)." if gemerkt else
                 "Lautstärke der Band ist noch nicht gemerkt: beim Soundcheck mindestens 1 Minute spielen lassen.")
    return teile


def seite(show) -> str:
    geraete = patchplan.eintraege(show)
    zeilen = "".join(f"""
        <tr><td><span class="kasten"></span></td><td><b>{escape(e['name'])}</b><br><small>{escape(e['typ'])}</small></td>
          <td class="gross">{e['adresse']:03d}</td><td>{e['kanaele']} Kanäle<br><small>„{escape(e['modus'])}“</small></td>
          <td class="dips">{patchplan.einstellen_html(e['einstellen'])}</td></tr>""" for e in geraete)
    ipads = len([g for g in show.fernbedienung.kopplung.liste() if g["rolle"] == "ipad"])
    heute = datetime.date.today().strftime("%d.%m.%Y")
    ton = "".join(f"<p class='hinweis'>{t}</p>" for t in _ton_stand(show))
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Aufbau-Checkliste</title>
<style>
  body {{ font: 14px/1.45 -apple-system, "Segoe UI", sans-serif; margin: 24px; color: #111; background: #fff; max-width: 900px; }}
  h1 {{ font-size: 22px; margin: 0 0 2px; }}
  h2 {{ font-size: 16px; margin: 18px 0 6px; border-bottom: 2px solid #222; padding-bottom: 2px; }}
  ol {{ list-style: none; padding: 0; margin: 0; }}
  li.schritt {{ display: flex; gap: 10px; margin: 5px 0; }}
  .not ol {{ list-style: disc; padding-left: 20px; }}
  .not li {{ margin: 4px 0; }}
  li small, td small {{ display: block; color: #555; }}
  .kasten {{ flex: none; width: 15px; height: 15px; border: 2px solid #222; border-radius: 2px; margin-top: 1px; display: inline-block; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #bbb; padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #eee; }}
  .gross {{ font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }}
  .dip {{ display: inline-block; width: 18px; margin-right: 2px; text-align: center; font-size: 11px;
         border: 1px solid #888; padding-top: 14px; background: linear-gradient(#fff 50%, #888 50%); }}
  .dip.an {{ background: linear-gradient(#222 50%, #fff 50%); color: #000; }}
  .dip.modus {{ border-color: #c60; }}
  .dips {{ white-space: nowrap; }}
  .warnung {{ color: #b00; font-weight: 600; }}
  .hinweis {{ color: #444; margin: 4px 0; }}
  .not {{ border: 2px solid #b00; padding: 8px 12px; margin-top: 16px; }}
  @media print {{ .nicht-drucken {{ display: none; }} body {{ margin: 0; }} h2 {{ break-after: avoid; }}
                  tr, li, .not {{ break-inside: avoid; }} }}
</style></head><body>
<h1>Aufbau-Checkliste Licht</h1>
<p class="hinweis">Lichtsteuerung {escape(VERSION)} · gedruckt am {heute} · Kästchen abhaken. Licht läuft auch ohne iPad und
ohne Internet; das MacBook kann immer alles.</p>

<h2>1. Vor dem Losfahren</h2>
<ol>
{_schritt("Update installiert (Seite Live → „Nach Update suchen“, braucht Internet, notfalls Handy-Hotspot).")}
{_schritt("Sicherung der Show auf einen USB-Stick (Setup → Sicherung → Show sichern).")}
{_schritt("Mitnehmen: MacBook-Netzteil, Enttec, DMX-Kabel (+ 5-auf-3-Pol-Adapter), USB-Kabel X32, iPad + Ladekabel, Klebeband, Stift.")}
</ol>

<h2>2. Strom, MacBook, DMX</h2>
<ol>
{_schritt("MacBook am Netzteil, Deckel offen lassen (Bildschirm darf dunkel sein).", "Zugeklappt schläft der Mac ein, und das Licht reagiert nicht mehr auf die Musik.")}
{_schritt("Enttec per USB am MacBook. DMX-Kette: Enttec → erstes Gerät → nächstes Gerät …")}
{_schritt("Programm starten, Seite Show: Konzert-Check öffnen.")}
</ol>

<h2>3. Geräte adressieren und prüfen</h2>
<p class="hinweis">An jedem Gerät Startadresse und Modus einstellen. DIP-Schalter: schwarz oben heißt EIN.</p>
{''.join(f"<p class='warnung'>{escape(p['text'])}</p>" for p in show.patch.probleme())}
<table>
<tr><th></th><th>Gerät</th><th>Adresse</th><th>Modus</th><th>Am Gerät einstellen</th></tr>
{zeilen}
</table>
<ol>
{_schritt("DMX einschalten (Konzert-Check: „DMX einschalten“).")}
{_schritt("Jedes Gerät einzeln prüfen: Setup → DMX-Test (oder am iPad: Setup → Geräte → „Aufblitzen“ halten).", "Bewegt sich ein Kopf falsch herum: Setup → Positionen → „Kopf zeigt falsch herum?“.")}
</ol>

<h2>4. Ton vom X32</h2>
{ton}
<ol>
{_schritt("USB-Kabel vom X32 (Rückseite, Karte X-USB) zum MacBook.")}
{_schritt("Am X32: Routing → Card Out. Die Mikros liegen meist auf USB 1–16.", "Summe für die Musik-Erkennung, z. B.: Routing → Out 15/16 = Main L/R und Card Out 9–16 = „Out 9–16“, dann liegt die Summe auf USB 15 und 16.")}
{_schritt("MacBook, Seite Live: Quelle „Eingang: X-USB“ wählen.")}
{_schritt("„Kanäle vom X32 …“: Summe, Bassdrum, Snare, Gesang/Rednerpult zuweisen (die Pegel zeigen, welcher Kanal was ist).")}
{_schritt("Soundcheck: Band mindestens 1 Minute laut spielen lassen. Danach weiß das Programm, was leise und was laut ist.")}
{_schritt("Konzert-Check: Alle Kanal-Rollen haben etwas gehört.")}
</ol>

<h2>5. iPad-Pult</h2>
<p class="hinweis">Gekoppelte iPads: {ipads}. Fällt das iPad aus, läuft das Licht weiter; dann alles am MacBook.</p>
<ol>
{_schritt("MacBook und iPad im selben WLAN (Router der Technik-AG, ohne Gast-Netz).")}
{_schritt("Nur falls noch nicht gekoppelt: Setup → iPad → „iPad koppeln“, QR-Code scannen, auf dem iPad Teilen → „Zum Home-Bildschirm“.")}
{_schritt("iPad-Einstellungen: Automatische Sperre <b>Nie</b>, Multitasking & Gesten: <b>Gesten aus</b>, iPad am Ladekabel.")}
{_schritt("Lichtpult-Symbol öffnen. Der Konzert-Check zeigt „iPad-Pult verbunden“.")}
{_schritt("Am Abend: Geführter Zugriff an, dann kann niemand aus Versehen die App verlassen.", "Einmalig: Einstellungen → Bedienungshilfen → Geführter Zugriff einschalten. Starten: im Lichtpult dreimal die Seitentaste (oder Home-Taste) drücken.")}
</ol>

<h2>6. Durchspielen</h2>
<ol>
{_schritt("Profil „Weihnachtszauber“ wählen, Musik-Automatik an.")}
{_schritt("Zwei Songs mit Automatik: Wird der Refrain stärker, bleiben ruhige Stellen ruhig?")}
{_schritt("Fader und Tasten am iPad, Not-Tasten (Blackout, Warmweiß) einmal drücken und wieder lösen.")}
{_schritt("KI-Chat (nur mit Internet): eine Szene bauen, auf einen Fader legen, drücken.")}
{_schritt("Rede am Rednerpult: Licht geht auf ruhiges Grundlicht.")}
{_schritt("Internet da? Ja / Nein (ohne Internet: kein KI-Chat und keine KI-Regie, alles andere geht).")}
{_schritt("Konzert-Check: keine roten Punkte.")}
</ol>

<div class="not"><b>Notfall am Abend</b>
<ol>
<li>iPad geht nicht: am MacBook weiter bedienen (gleiche Tasten, Seite Show oder Pult).</li>
<li>Licht soll sofort dunkel: Taste <b>B</b> (Blackout). Nur helles Licht: Taste <b>W</b> (Warmweiß). Automatik anhalten: <b>P</b>.</li>
<li>Kein Ton (Kabel raus): Das Licht hält kurz die Musik und geht dann aufs Grundlicht. Kabel wieder einstecken, der Ton kommt von selbst zurück.</li>
<li>Programm hängt: Programm beenden und neu starten. Patch, Profil, Ton-Eingang und iPad sind danach wieder da; DMX neu einschalten.</li>
</ol></div>
<p class="nicht-drucken"><button onclick="print()">Drucken</button></p>
</body></html>"""
