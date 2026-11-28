"""Der Patchplan: Was muss man an jedem Licht einstellen, damit es auf DMX hört?

Erzeugt eine eigene Seite zum Ausdrucken und Mitnehmen an die Traverse.
"""
from __future__ import annotations

from html import escape

from . import adressierung

DIP_SCHALTER = 10


def dip(adresse: int) -> list:
    """Welche DIP-Schalter an sind. Schalter 1 zählt 1, Schalter 2 zählt 2, Schalter 3 zählt 4 und so weiter."""
    return [bool(adresse >> stelle & 1) for stelle in range(DIP_SCHALTER)]


ORTE = {"traverse": "Traverse", "stativ": "Stativ", "boden": "Boden"}


def eintraege(show) -> list:
    """Alle Geräte, sortiert wie sie hängen: Traverse von links nach rechts (vom Publikum aus)."""
    liste = []
    for geraet in show.patch.geraete:
        typ = show.patch.typ(geraet)
        kanalzahl = show.patch.kanalzahl(geraet)
        ort = show.buehne.geraet(geraet["id"]) or {}
        liste.append({
            "name": geraet["name"], "typ": f"{typ.daten['hersteller']} {typ.daten['name']}",
            "modus": geraet["modus"], "kanaele": kanalzahl, "adresse": geraet["adresse"],
            "ende": geraet["adresse"] + kanalzahl - 1, "ort": ORTE.get(ort.get("ort"), "?"),
            "haengend": ort.get("montage") == "haengend", "x": ort.get("x", 0.0),
            "reihe": list(ORTE).index(ort["ort"]) if ort.get("ort") in ORTE else 9,
            "geprueft": typ.daten.get("handbuch_geprueft", False),
            "einstellen": adressierung.einstellen(geraet["adresse"], adressierung.info_fuer(typ.daten)),
            "beweglich": any(k["typ"] in ("pan", "tilt") for _, k in typ.kanaele_im_modus(geraet["modus"])),
        })
    return sorted(liste, key=lambda e: (e["reihe"], e["x"]))



def einstellen_html(einstellen: dict) -> str:
    """Schalterreihe (schwarz oben = an), Text, Display-Schreibweise und Hinweise für eine Zelle im Plan."""
    teile = []
    if einstellen["dip"]:
        teile.append("".join(
            '<span class="dip{an}{modus}" title="Schalter {nr}">{nr}</span>'.format(
                an=" an" if s["an"] else "", modus=" modus" if s["rolle"] == "modus" else "", nr=s["nr"])
            for s in einstellen["dip"]["schalter"]))
        teile.append("<small>" + escape(einstellen["dip"]["text"]) + "</small>")
    if einstellen["display"]:
        teile.append("Display: <b>" + escape(einstellen["display"]) + "</b>")
    if einstellen["hinweis"] and einstellen["art"] != "unbekannt":
        teile.append("<small>" + escape(einstellen["hinweis"]) + "</small>")
    if einstellen["warnung"]:
        teile.append('<b class="warnung">' + escape(einstellen["warnung"]) + "</b>")
    return "<br>".join(teile)

def seite(show) -> str:
    zeilen = []
    for e in eintraege(show):
        schalter = einstellen_html(e["einstellen"])
        zeilen.append(f"""
        <tr>
          <td><b>{escape(e['name'])}</b><br><small>{escape(e['typ'])}</small></td>
          <td>{escape(e['ort'])}{', hängend' if e['haengend'] else ''}{'<br><small>Am Gerät Display und Pan/Tilt umdrehen</small>' if e['haengend'] and e['beweglich'] else ''}</td>
          <td class="gross">{e['adresse']:03d}</td>
          <td>{e['kanaele']} Kanäle<br><small>Modus „{escape(e['modus'])}“</small></td>
          <td>{e['adresse']} bis {e['ende']}</td>
          <td class="dips">{schalter}</td>
        </tr>""")
    probleme = "".join(f"<p class='warnung'>{escape(p['text'])}</p>" for p in show.patch.probleme())
    ungeprueft = any(not e["geprueft"] for e in eintraege(show))
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>Patchplan</title>
<style>
  body {{ font: 14px/1.4 -apple-system, "Segoe UI", sans-serif; margin: 24px; color: #111; background: #fff; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
  th, td {{ border: 1px solid #bbb; padding: 8px; text-align: left; vertical-align: top; }}
  th {{ background: #eee; }}
  .gross {{ font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }}
  small {{ color: #555; }}
  .dip {{ display: inline-block; width: 18px; margin-right: 2px; text-align: center; font-size: 11px;
         border: 1px solid #888; padding-top: 14px; background: linear-gradient(#fff 50%, #888 50%); }}
  .dip.an {{ background: linear-gradient(#222 50%, #fff 50%); color: #000; }}
  .dip.modus {{ border-color: #c60; }}
  .dips {{ white-space: nowrap; }}
  .warnung {{ color: #b00; font-weight: 600; }}
  .hinweis {{ color: #444; }}
  @media print {{ .nicht-drucken {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<h1>Patchplan</h1>
<p class="hinweis">Ein Universum am Enttec. An jedem Gerät die <b>Startadresse</b> und den <b>Modus</b> einstellen.
Viele Displays zeigen die Adresse als <b>A001</b> oder <b>d001</b>. Geräte mit Schaltern: <b>DIP</b>-Schalter wie gezeigt,
schwarz oben heißt EIN.</p>
{probleme}
{'<p class="warnung">Einige Gerätedaten sind noch nicht mit dem Handbuch abgeglichen: Kanalzahl im Handbuch nachsehen.</p>' if ungeprueft else ''}
<table>
<tr><th>Gerät</th><th>Ort</th><th>Startadresse</th><th>Modus</th><th>belegt</th><th>Am Gerät einstellen (DIP-Schalter oder Display)</th></tr>
{''.join(zeilen)}
</table>
<p class="nicht-drucken"><button onclick="print()">Drucken</button></p>
</body></html>"""
