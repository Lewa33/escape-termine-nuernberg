#!/usr/bin/env python3
"""
Zeigt alle freien Termine für den Escape Room
"Die Legenden der Zauberakademie Teil 1" (Finest Escape Nürnberg) an.
Der tägliche Lauf schreibt zusätzlich eine Seite mit allen Zimmern und einer
Zimmerauswahl. Per iMessage gemeldet wird weiterhin nur die Zauberakademie.

Fragt direkt die Buchungs-API (Quinbook) ab, mit der die Buchungsseiten
unter https://finest-escape.de/nuernberg/ arbeiten.
Kein Browser/Durchklicken nötig.

Nutzung:
    python3 escape_room_slots.py [--days 60]
    python3 escape_room_slots.py --year 2026   # ganzes Jahr ab heute bis 31.12.
    python3 escape_room_slots.py --taeglich    # täglicher Lauf (90 Tage), siehe README.md
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from itertools import groupby
from pathlib import Path

# Übersichts-Shop von Finest Escape Nürnberg: liefert alle Zimmer auf einmal.
SHOP_HASH = "ac73001b1d44f4925449ce09d9f5d5ca"
API = "https://api.quinbook.com/v2"
TZOFFSET = -120  # Europe/Berlin (CET/CEST-Angabe, wie vom Widget genutzt)
BUCHUNGSSEITE = "https://finest-escape.de/nuernberg/legenden-der-zauberakademie/"
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
PAUSE_SEKUNDEN = 0.2  # zwischen den Tagesabfragen, die API nicht unnötig belasten

# Nur dieses Zimmer (Die Legenden der Zauberakademie) löst eine iMessage aus.
UEBERWACHTES_ZIMMER = "12242"
WEBSITE = "https://finest-escape.de/nuernberg/"
ZIMMER_SEITEN = {
    UEBERWACHTES_ZIMMER: BUCHUNGSSEITE,
    "12098": WEBSITE + "der-henker/",
    "12146": WEBSITE + "der-puppenspieler/",
    "12200": WEBSITE + "geheimnis-der-moenche/",
    "12239": WEBSITE + "sherlock-holmes/",
    "12248": WEBSITE + "rueckkehr-des-dunklen-lords/",
    "12434": WEBSITE + "abenteuer-des-halblings/",
    "17163": WEBSITE + "vecnas-game/",
    "18792": WEBSITE + "aurora-nuernberg/",
    "19197": WEBSITE + "prestige/",
}

# Dateien für den täglichen Lauf liegen neben dem Skript (launchd startet in "/").
ORDNER = Path(__file__).resolve().parent
KONFIG_DATEI = ORDNER / "zauberakademie_config.json"
STAND_DATEI = ORDNER / "daten" / "zauberakademie_letzter_lauf.json"
HTML_DATEI = Path(os.environ.get("HTML_DATEI", ORDNER / "zauberakademie_freie_termine.html"))
# Auf GitHub gibt es kein iMessage: die Nachricht landet hier, der Workflow macht ein Issue daraus.
NACHRICHT_DATEI = os.environ.get("NACHRICHT_DATEI")
KONTAKT = "https://github.com/Lewa33/escape-termine-nuernberg/issues"
MAX_ZEILEN_NACHRICHT = 15


def api_request(path, method="GET", auth_token=None, body=None):
    url = f"{API}{path}"
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def get_auth_token():
    resp = api_request(
        "/shop/init",
        method="POST",
        body={
            "iShopConfig": SHOP_HASH,
            "language": "de",
            "clientId": uuid.uuid4().hex,
        },
    )
    return resp["authToken"]


def daterange_chunks(start, end, chunk_days=14):
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def get_candidate_days(token, start, end):
    """Tage, an denen laut Zähler-Endpunkt potenziell etwas frei ist."""
    candidates = set()
    for chunk_start, chunk_end in daterange_chunks(start, end):
        resp = api_request(
            f"/shop/getslotscounts?tzoffset={TZOFFSET}"
            f"&start={chunk_start.isoformat()}&end={chunk_end.isoformat()}",
            auth_token=token,
        )
        for day_str, info in resp.items():
            if info.get("available") or (info.get("count") or 0) > 0:
                candidates.add(day_str[:10])
    return sorted(candidates)


def get_slots_for_day(token, day_str, raum_infos=None):
    """Alle Zimmer des Tages als {id: name} und ihre freien Termine."""
    resp = api_request(f"/shop/slots/{day_str}?tzoffset={TZOFFSET}", auth_token=token)
    zimmer = {}
    free = []
    for event in resp.get("events", []):
        zimmer_id = str(event["id"])
        zimmer[zimmer_id] = event["name"].strip()
        if raum_infos is not None:
            raum_infos[zimmer_id] = raum_fakten(event)
        for slot in event.get("slots", []):
            if slot.get("available") and slot.get("free", 0) > 0:
                start = slot["start"][11:16]
                inner = (slot.get("slots") or [{}])[0]
                total = (inner.get("ticketPool") or {}).get("quantity", slot["free"])
                min_order = (inner.get("ticketPool") or {}).get("minOrder")
                free.append((zimmer_id, start, slot["free"], total, min_order))
    return zimmer, free


def alle_freien_termine(start, end, raum_infos=None):
    """Alle Zimmer als {id: name} und alle freien Termine, sortiert nach Datum und Uhrzeit."""
    token = get_auth_token()
    zimmer = {UEBERWACHTES_ZIMMER: "Die Legenden der Zauberakademie"}
    termine = []
    for day_str in get_candidate_days(token, start, end):
        zimmer_des_tages, freie = get_slots_for_day(token, day_str, raum_infos)
        zimmer.update(zimmer_des_tages)
        for zimmer_id, time_str, free, total, min_order in freie:
            termine.append({
                "zimmer_id": zimmer_id,
                "zimmer": zimmer[zimmer_id],
                "datum": day_str,
                "uhrzeit": time_str,
                "frei": free,
                "gesamt": total,
                "min_spieler": min_order,
            })
        time.sleep(PAUSE_SEKUNDEN)
    termine.sort(key=lambda t: (t["datum"], t["uhrzeit"], t["zimmer"]))
    return zimmer, termine


def termin_schluessel(t):
    # Stand-Dateien von vor der Zimmerauswahl kennen nur die Zauberakademie.
    return (t.get("zimmer_id", UEBERWACHTES_ZIMMER), t["datum"], t["uhrzeit"])


def termin_text(t):
    d = date.fromisoformat(t["datum"])
    return f"{WOCHENTAGE[d.weekday()]} {d.strftime('%d.%m.%Y')} {t['uhrzeit']} Uhr"


# ---------- täglicher Lauf ----------

def lade_json(pfad, standard):
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return standard


class FaktenText(HTMLParser):
    """API-HTML nur lesen; weder Markup noch Werbetexte veröffentlichen."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile = []

    def handle_data(self, data):
        self.teile.append(data)


def raum_fakten(event):
    parser = FaktenText()
    parser.feed(" ".join(str(event.get(k) or "") for k in ("additionalInfo", "metaDescription")))
    text = " ".join(" ".join(parser.teile).split())
    fakten = {}
    location = event.get("location") or {}
    if isinstance(location, dict) and location.get("locationAddress1"):
        fakten["Standort"] = str(location["locationAddress1"]).strip()
    seats = event.get("seats")
    if isinstance(seats, int) and not isinstance(seats, bool) and seats > 0:
        fakten["Spielerzahl"] = f"Bis {seats} Personen (Raumkapazität)"
    # Bewusst enge Muster: Begleitregeln niemals zu einem pauschalen Alter verkürzen.
    if re.search(r"ab 14 Jahren mit mindestens 2 volljährigen Begleitern", text, re.I):
        fakten["Alter"] = "Ab 14 mit mindestens 2 Volljährigen; ab 16 ohne Begleitung"
    elif re.search(r"14 Jahre in Begleitung eines Erwachsenen, 16 Jahre ohne Begleitung", text, re.I):
        fakten["Alter"] = "Ab 14 mit erwachsener Begleitung; ab 16 ohne Begleitung"
    elif re.search(r"unter 16 Jahren.*eine erwachsene Begleitperson", text, re.I):
        fakten["Begleitung"] = "Unter 16: mindestens 1 erwachsene Person"
        if re.search(r"unter 14 Jahren.*mindestens genau so viele Erwachsenen wie Kinder", text, re.I):
            fakten["Begleitung"] += "; unter 14: mindestens so viele Erwachsene wie Kinder"
    else:
        alter = re.search(r"(?:Mindestalter(?: ist)?|FSK)\s+(\d{1,2})(?: Jahre)?\b", text, re.I)
        if alter:
            fakten["Mindestalter"] = f"{int(alter[1])} Jahre"
    dauer = re.search(r"(?:Spieldauer|Dauer)\s*:?\s*(\d{1,3})\s*(?:Minuten|Min\b)", text, re.I)
    if dauer:
        fakten["Dauer"] = f"{int(dauer[1])} Minuten"
    if re.search(r"leicht bis mittleren Schwierigkeitsgrad", text, re.I):
        fakten["Schwierigkeit"] = "Leicht bis mittel"
    return fakten


def esc(wert):
    return html.escape(str(wert), quote=True)


# Kein API-Zugriff im Browser. Ohne JS bleiben sämtliche Termine und Raumdaten sichtbar.
AUSWAHL_SKRIPT = r"""
(function () {
  const ids = ['wochentag', 'tageszeit', 'spieler', 'ab', 'bis'];
  const controls = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
  const days = Array.from(document.querySelectorAll('.tag'));
  const rows = Array.from(document.querySelectorAll('.raum-termine'));
  const slots = Array.from(document.querySelectorAll('.slot'));
  const storage = 'finest-escape-zimmer';
  const count = document.getElementById('anzahl');
  const empty = document.getElementById('leer');
  const next = document.getElementById('naechste');
  const roomButtons = Array.from(document.querySelectorAll('.room-choice'));
  let selectedRoom = 'alle';
  function show() {
    const invalidRange = controls.ab.value && controls.bis.value && controls.ab.value > controls.bis.value;
    document.getElementById('datum-fehler').hidden = !invalidRange;
    let total = 0;
    slots.forEach(slot => {
      const row = slot.closest('.raum-termine');
      const day = row.closest('.tag');
      const hour = Number(slot.dataset.stunde);
      const period = hour < 12 ? 'vormittag' : hour < 18 ? 'nachmittag' : 'abend';
      const people = Number(controls.spieler.value);
      const fits = (selectedRoom === 'alle' || row.dataset.zimmer === selectedRoom)
        && (!controls.wochentag.value || day.dataset.wochentag === controls.wochentag.value)
        && (!controls.tageszeit.value || period === controls.tageszeit.value)
        && (!controls.ab.value || day.dataset.datum >= controls.ab.value)
        && (!controls.bis.value || day.dataset.datum <= controls.bis.value)
        && (!people || (Number(slot.dataset.frei) >= people && slot.dataset.min !== '' && Number(slot.dataset.min) <= people));
      slot.hidden = !fits;
      if (fits) total++;
    });
    rows.forEach(row => { row.hidden = !row.querySelector('.slot:not([hidden])'); });
    days.forEach(day => {
      const n = day.querySelectorAll('.slot:not([hidden])').length;
      day.hidden = !n;
      day.querySelector('.tag-anzahl').textContent = n + (n === 1 ? ' Termin' : ' Termine');
    });
    document.querySelectorAll('.raum-info').forEach(card => {
      card.hidden = selectedRoom !== 'alle' && card.dataset.zimmer !== selectedRoom;
    });
    empty.hidden = total > 0;
    empty.textContent = invalidRange
      ? 'Das Enddatum liegt vor dem Startdatum. Bitte passt den Zeitraum an.'
      : 'Keine freien Termine für diese Auswahl im abgefragten Zeitraum. Wählt ein anderes Zimmer oder setzt die Filter zurück.';
    count.textContent = total.toLocaleString('de-DE') + (total === 1 ? ' freier Termin' : ' freie Termine');
    next.hidden = !total;
    const first = days.find(day => !day.hidden);
    next.href = first ? '#' + first.id : '#termine';
    roomButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.room === selectedRoom)));
    document.getElementById('selected-room').textContent = roomButtons.find(button => button.dataset.room === selectedRoom).dataset.label;
    try { localStorage.setItem(storage, selectedRoom); } catch (e) {}
  }
  try {
    const saved = localStorage.getItem(storage);
    if (roomButtons.some(button => button.dataset.room === saved)) selectedRoom = saved;
  } catch (e) {}
  roomButtons.forEach(button => button.addEventListener('click', () => {
    selectedRoom = button.dataset.room;
    document.getElementById('room-picker').open = false;
    show();
  }));
  document.querySelectorAll('.raum-name a, .search-actions a').forEach(link => link.addEventListener('click', () => { document.getElementById('room-details').open = true; }));
  ids.forEach(id => controls[id].addEventListener('change', show));
  document.getElementById('zuruecksetzen').addEventListener('click', () => {
    selectedRoom = 'alle';
    ids.forEach(id => { controls[id].value = ''; });
    show();
  });
  document.getElementById('modus').addEventListener('change', event => {
    document.documentElement.dataset.theme = event.target.value;
  });
  document.querySelectorAll('.js-only').forEach(element => { element.hidden = false; });
  show();
})();
"""


STIL = """
:root { color-scheme:light dark; --bg:#f0e6d0;--surface:#faf3e2;--text:#30251e;--muted:#6e5d49;--line:#cdbb96;--accent:#775121;--soft:#e8dabe;--new:#f1d18e;--newtext:#5d3416;--glow:#9e682d19;--chip:#fffbf0; }
@media(prefers-color-scheme:dark) { :root:not([data-theme=light]) { --bg:#181311;--surface:#251f1a;--text:#f0e6d2;--muted:#c2b298;--line:#51412f;--accent:#dfbb78;--soft:#32281e;--new:#593d21;--newtext:#ffe6ad;--glow:#b67b3020;--chip:#2a231c; } }
:root[data-theme=dark] { color-scheme:dark; --bg:#181311;--surface:#251f1a;--text:#f0e6d2;--muted:#c2b298;--line:#51412f;--accent:#dfbb78;--soft:#32281e;--new:#593d21;--newtext:#ffe6ad;--glow:#b67b3020;--chip:#2a231c; }
:root[data-theme=light] { color-scheme:light; }
* { box-sizing:border-box; } [hidden] { display:none !important; }
html { scroll-padding-top:1rem; } body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,-apple-system,sans-serif; }
a { color:var(--accent); text-underline-offset:3px; } button,select,input { font:inherit; } button,a,select,input,summary { touch-action:manipulation; }
:focus-visible { outline:3px solid var(--accent); outline-offset:3px; }
.wrap { max-width:1160px; margin:auto; padding:0 28px; } .top { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:22px 0; border-bottom:1px solid var(--line); }
.wordmark { font-weight:750; letter-spacing:.06em; font-size:.8rem; } .mode { width:auto; max-width:130px; font-size:.8rem; }
header { padding:38px 0 24px; } .eyebrow { color:var(--accent); font-size:.75rem; font-weight:750; letter-spacing:.15em; text-transform:uppercase; margin:0 0 10px; }
h1 { font-size:clamp(2rem,5vw,3.5rem); line-height:1.08; letter-spacing:-.05em; max-width:760px; margin:0 0 18px; } h1 span { color:var(--accent); } .intro { max-width:720px; color:var(--muted); margin:0 0 18px; }
.notice { padding:14px 18px; border-left:3px solid var(--accent); background:var(--soft); font-size:.85rem; } .notice a { white-space:normal; } .stamp { color:var(--muted); font-size:.8rem; margin:18px 0 24px; }
.layout:has(aside[hidden]) { grid-template-columns:minmax(0,1fr); } .quick { display:flex; flex-wrap:wrap; gap:18px; margin:18px 0; font-size:.85rem; font-weight:650; } .raum-name a { color:inherit; text-decoration:none; } .raum-name a:hover { text-decoration:underline; } .layout { display:grid; grid-template-columns:285px minmax(0,1fr); gap:28px; align-items:start; } .panel { background:var(--surface); border:1px solid var(--line); border-radius:18px; padding:20px; } aside { position:sticky; top:18px; }
h2 { font-size:1.2rem; margin:0; letter-spacing:-.02em; } .panel h2 { margin-bottom:16px; } label { display:block; font-size:.8rem; font-weight:650; margin:14px 0 6px; }
select,input { width:100%; min-width:0; max-width:100%; padding:10px 9px; min-height:44px; color:var(--text); background:var(--bg); border:1px solid var(--line); border-radius:8px; } button { cursor:pointer; border:1px solid var(--line); color:var(--accent); background:var(--surface); padding:10px 14px; border-radius:8px; min-height:44px; }
.date-range { min-width:0; margin:18px 0 4px; padding:12px; border:1px solid var(--accent); border-radius:10px; background:var(--soft); } .date-range legend { padding:0 5px; font-size:.85rem; font-weight:750; } .date-grid { display:grid; gap:10px; } .date-range label { margin-top:0; } .date-range input { background:var(--surface); } .date-error { color:var(--text); font-size:.8rem; margin:10px 0 0; } .reset { width:100%; margin-top:18px; } .hint { font-size:.75rem; color:var(--muted); margin-bottom:0; } .results-head { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin:0 0 16px; } .results-head p { color:var(--muted); font-size:.8rem; margin:4px 0 0; }
.jump { display:inline-block; background:var(--accent); color:var(--bg); text-decoration:none; border-radius:8px; padding:10px 14px; font-size:.8rem; font-weight:700; } .tag { margin-bottom:16px; background:var(--surface); border:1px solid var(--line); border-radius:16px; overflow:hidden; }
.tag-kopf { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:4px; background:var(--soft); padding:13px 18px; } .tag-kopf h3 { margin:0; font-size:.95rem; } .tag-anzahl { color:var(--muted); font-size:.75rem; }
.raum-termine { display:grid; grid-template-columns:minmax(0,180px) minmax(0,1fr); gap:14px; padding:15px 18px; border-top:1px solid var(--line); } .raum-name { font-size:.85rem; font-weight:650; } .adresse { display:block; color:var(--muted); font-size:.7rem; font-weight:400; margin-top:4px; } .zeiten { display:flex; flex-wrap:wrap; gap:7px; align-content:start; }
.slot { display:inline-flex; align-items:center; gap:5px; padding:9px 11px; min-height:44px; border:1px solid var(--line); border-radius:8px; font-size:.85rem; font-variant-numeric:tabular-nums; text-decoration:none; } .slot:hover { background:var(--soft); border-color:var(--accent); } .slot b { font-size:.55rem; border-radius:3px; padding:2px 4px; background:var(--new); color:var(--newtext); } .platz { color:var(--muted); font-size:.7rem; }
.room-section { margin:32px 0; border-top:1px solid var(--line); padding-top:22px; } summary { cursor:pointer; padding:8px 0; font-weight:700; } .room-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin-top:16px; } .raum-info { min-width:0; } .raum-info h3 { font-size:1rem; margin:0 0 12px; } dl { margin:0 0 18px; font-size:.8rem; } dt { color:var(--muted); margin-top:10px; } dd { margin:1px 0 0; } .raum-info a { font-size:.8rem; } .muted { color:var(--muted); font-size:.8rem; } footer { padding:22px 0 30px; border-top:1px solid var(--line); font-size:.8rem; color:var(--muted); } .empty { padding:24px; background:var(--soft); border-radius:12px; }
@media(max-width:760px) { .wrap { padding:0 16px; } .top { padding:14px 0; } header { padding-top:26px; } .layout { grid-template-columns:minmax(0,1fr); gap:24px; } aside { position:static; } .filter-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 12px; } .wide { grid-column:1/-1; } .date-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .panel { padding:16px; } .panel h2 { margin-bottom:8px; } .raum-termine { grid-template-columns:minmax(0,1fr); gap:10px; padding:14px; } .adresse { margin-top:2px; } .tag-kopf { padding:12px 14px; } .room-grid { grid-template-columns:minmax(0,1fr); } .jump { width:100%; text-align:center; } .results-head { gap:14px; } }

/* Verbotene Bibliothek: lokale Systemschriften und originale Inline-Grafik. */

body { background-color:var(--bg); background-image:radial-gradient(ellipse at 80% 6%,var(--glow),transparent 48%); background-attachment:fixed; }
.wrap { position:relative; } .top { border-bottom:1px solid var(--line); } .wordmark { letter-spacing:.15em; font-size:.73rem; }

.hero { display:grid; grid-template-columns:minmax(0,1fr) 290px; align-items:center; gap:24px; margin:4px 0 20px; } .hero-copy { min-width:0; } header { padding-top:22px; } .eyebrow { font-size:.68rem; letter-spacing:.16em; }
h1 { font-family:Georgia,'Times New Roman',serif; font-weight:400; font-size:clamp(2.5rem,5.3vw,4.6rem); line-height:1.03; letter-spacing:-.045em; margin-bottom:20px; } h1 span { font-style:italic; } .intro { max-width:580px; font-size:.92rem; margin-bottom:0; }
.hero-art { height:285px; width:100%; color:var(--accent); position:relative; } .hero-art svg { height:100%; width:100%; overflow:visible; } .hero-art:after { content:''; position:absolute; inset:70% -8% -5%; background:radial-gradient(ellipse,var(--glow),transparent 67%); pointer-events:none; }
.panel,.tag { border-radius:4px; box-shadow:0 8px 28px #0000000a; }  .panel h2, .room-section summary { font-family:Georgia,'Times New Roman',serif; font-weight:400; font-size:1.35rem; letter-spacing:-.02em; } .notice { border-left-width:2px; border-top:1px solid var(--line); border-bottom:1px solid var(--line); background:var(--soft); } .quick { font-weight:500; } .stamp { font-size:.73rem; margin:14px 0 22px; }
select,input,button,.slot { border-radius:3px; } .date-range { border-radius:3px; } .date-range legend { letter-spacing:.03em; } .tag-kopf { background:var(--soft); } .tag-kopf h3 { font-family:Georgia,'Times New Roman',serif; font-size:1.05rem; font-weight:400; } .slot { background:var(--chip); border-color:var(--line); } .slot:hover { background:var(--soft); box-shadow:inset 0 0 0 1px var(--accent); } .jump { border-radius:3px; text-transform:uppercase; letter-spacing:.07em; font-size:.7rem; padding:13px 16px; } .raum-info h3 { font-family:Georgia,'Times New Roman',serif; font-size:1.2rem; font-weight:400; } .room-section { border-top:1px solid var(--accent); } .results-head h2 { font-weight:500; }
@media(max-width:760px) {   header { padding-top:24px; } .hero { position:relative; grid-template-columns:minmax(0,1fr); min-height:250px; margin:0 0 22px; } .hero-copy { position:relative; z-index:1; } .hero-art { position:absolute; right:-2px; top:12px; width:145px; height:225px; opacity:.15; } h1 { font-size:2.65rem; line-height:1.06; max-width:340px; } .intro { max-width:310px; } .eyebrow { max-width:230px; } .panel { border-radius:4px; } .notice { font-size:.8rem; } .stamp { font-size:.72rem; } }
/* Kompakte Übersicht: Termine vor Dekoration. */
.wrap { max-width:1000px; } .top { padding:10px 0; } .compact-header { padding:18px 0 0; }
.compact-header h1 { font-size:1.65rem; line-height:1.15; margin:0 0 10px; max-width:none; letter-spacing:-.03em; }
.compact-header h1 span { font-style:normal; } .notice { padding:8px 10px; margin:0; font-size:.75rem; }
.stamp { margin:8px 0 14px; font-size:.7rem; } .quick-search { padding:14px; margin-bottom:18px; }
.room-picker>summary { font-family:inherit; font-size:.85rem; padding:8px 0; min-height:44px; }
#selected-room { display:inline-block; color:var(--accent); margin-left:8px; }
.room-buttons { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:10px 0; }
.room-choice { text-align:left; color:var(--text); min-width:0; padding:10px; line-height:1.3; }
.room-choice strong { display:block; font-size:.8rem; } .room-choice span { display:block; font-size:.67rem; color:var(--muted); margin-top:4px; }
.room-choice .room-count { color:var(--accent); } .room-choice[aria-pressed=true] { border-color:var(--accent); background:var(--soft); box-shadow:inset 0 0 0 1px var(--accent); }
.all-rooms { grid-column:1/-1; } .all-rooms strong,.all-rooms span { display:inline; margin-right:10px; }
.date-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; } .date-grid label { margin:8px 0 4px; }
.advanced { margin-top:8px; } .advanced>summary { font:500 .8rem/1.5 system-ui,sans-serif; min-height:44px; padding:12px 0; color:var(--accent); }
.advanced-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.search-actions { display:flex; justify-content:space-between; align-items:center; gap:12px; font-size:.75rem; } .search-actions button { font-size:.75rem; padding:5px 10px; }
.results-head { margin-bottom:10px; } .results-head h2 { font-size:1.05rem; } .results-head p { font-size:.7rem; }
.results-head .jump { font-size:.65rem; padding:10px; } .room-section { margin-top:24px; }
@media(max-width:760px) { .wrap { padding:0 12px; } .compact-header { padding-top:14px; } .compact-header h1 { font-size:1.5rem; } .quick-search { padding:12px; } .room-buttons { grid-template-columns:repeat(2,minmax(0,1fr)); } .advanced-grid { grid-template-columns:1fr; gap:0; } .results-head { gap:8px; } .jump { width:auto; } }

"""

# Originale dekorative Vektorgrafik, ohne externe Ressourcen.


def schreibe_html(zimmer, termine, neue_schluessel, abgefragt_um, start, end, raum_infos=None):
    """Eine eigenständige HTML-Datei, ausschließlich mit escapten API-Fakten."""
    raum_infos = raum_infos or {}
    # Teil 2 heißt in der API nur „Die Rückkehr des Dunklen Lords“.
    # Nur die HTML-Anzeige ergänzen; IDs, API-Namen im Stand und Meldungen bleiben gleich.
    teile = {"12242": 1, "12248": 2}
    zimmer = {zid: f"Zauberakademie – Teil {teile[zid]} · {name}" if zid in teile else name
              for zid, name in zimmer.items()}
    anzahl = Counter(t["zimmer_id"] for t in termine)
    raum_buttons = [f'<button type="button" class="room-choice all-rooms" data-room="alle" data-label="Alle Zimmer" aria-pressed="true"><strong>Alle Zimmer</strong><span>{len(termine)} frei</span></button>']
    karten = []
    for zid, name in sorted(zimmer.items(), key=lambda item: item[1].casefold()):
        stand = f"{anzahl[zid]} frei" if anzahl[zid] else "nichts frei"
        fakten = raum_infos.get(zid, {})
        standort = fakten.get("Standort", "")
        kurzname = f"Zauberakademie {teile[zid]}" if zid in teile else name
        raum_buttons.append(f'<button type="button" class="room-choice" data-room="{esc(zid)}" data-label="{esc(kurzname)}" aria-pressed="false" aria-label="{esc(name)} ({esc(stand)})"><strong>{esc(kurzname)}</strong><span>{esc(standort)}</span><span class="room-count">{esc(stand)}</span></button>')
        daten = ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in fakten.items())
        karten.append(f'''<article class="raum-info panel" id="raum-{esc(zid)}" data-zimmer="{esc(zid)}" data-standort="{esc(standort)}">
<h3>{esc(name)}</h3><p class="muted">{esc(stand)}</p><dl>{daten}</dl>
<a href="{esc(ZIMMER_SEITEN.get(zid, WEBSITE))}">Offizielle Raumseite · Bilder &amp; Details ↗</a></article>''')
    tage = []
    # Nach Raum bündeln: pro Tag nur ein Raumname, kompakte Zeit-Chips statt 2.500 Textzeilen.
    for datum, gruppe in groupby(termine, key=lambda t: t["datum"]):
        d = date.fromisoformat(datum)
        liste = list(gruppe)
        zeilen = []
        for zid in sorted({t["zimmer_id"] for t in liste}, key=lambda z: zimmer[z].casefold()):
            ort = raum_infos.get(zid, {}).get("Standort", "")
            chips = []
            for t in (t for t in liste if t["zimmer_id"] == zid):
                neu = '<b>NEU</b>' if termin_schluessel(t) in neue_schluessel else ''
                minimum = t.get("min_spieler")
                mindest_text = f", mindestens {minimum} Spieler" if minimum else ""
                beschreibung = f'{t["uhrzeit"]} Uhr, {t["frei"]} von {t["gesamt"]} Plätzen frei{mindest_text}'
                chips.append(f'''<a class="slot" href="{esc(ZIMMER_SEITEN.get(zid, WEBSITE))}" data-stunde="{esc(t['uhrzeit'][:2])}" data-frei="{esc(t['frei'])}" data-min="{esc(minimum or '')}" aria-label="{esc(beschreibung)}" title="{esc(beschreibung)}"><span>{esc(t['uhrzeit'])}</span><span class="platz">{esc(t['frei'])} P.</span>{neu}</a>''')
            zeilen.append(f'<div class="raum-termine" data-zimmer="{esc(zid)}" data-standort="{esc(ort)}"><div class="raum-name"><a href="#raum-{esc(zid)}">{esc(zimmer[zid])}</a><span class="adresse">{esc(ort)}</span></div><div class="zeiten">{"".join(chips)}</div></div>')
        tage.append(f'''<section class="tag" id="tag-{esc(datum)}" data-datum="{esc(datum)}" data-wochentag="{d.weekday()}"><div class="tag-kopf"><h3>{WOCHENTAGE[d.weekday()]} · {d.strftime('%d.%m.%Y')}</h3><span class="tag-anzahl">{len(liste)} Termine</span></div>{''.join(zeilen)}</section>''')
    wochen_optionen = ''.join(f'<option value="{i}">{tag}</option>' for i, tag in enumerate(WOCHENTAGE))
    max_spieler = max((t["frei"] for t in termine if isinstance(t["frei"], int)), default=8)
    spieler_optionen = ''.join(f'<option value="{i}">{i} Person{"en" if i != 1 else ""}</option>' for i in range(1, max_spieler + 1))
    HTML_DATEI.parent.mkdir(parents=True, exist_ok=True)
    HTML_DATEI.write_text(f'''<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Freie Escape-Room-Termine Nürnberg</title><style>{STIL}</style></head>
<body><div class="wrap"><div class="top"><span class="wordmark">ESCAPE · NÜRNBERG</span><div class="js-only" hidden><label for="modus" style="display:inline">Ansicht </label><select class="mode" id="modus"><option value="auto">Automatisch</option><option value="light">Hell</option><option value="dark">Dunkel</option></select></div></div>
<header class="compact-header"><h1>Freie Escape-Termine <span>Nürnberg</span></h1><p class="notice">Inoffizielle private Übersicht, ohne Gewähr. <a href="{esc(KONTAKT)}">Fehler oder Einwände melden</a></p><p class="stamp">Stand: {esc(abgefragt_um)} · 2× täglich aktualisiert</p></header>
<section id="filter" class="panel quick-search js-only" aria-label="Terminsuche" hidden>
<details id="room-picker" class="room-picker"><summary>Raum wählen <strong id="selected-room">Alle Zimmer</strong></summary><div class="room-buttons" role="group" aria-label="Zimmerauswahl">{''.join(raum_buttons)}</div></details>
<div class="date-grid"><div><label for="ab">Ab Datum</label><input id="ab" type="date" min="{start.isoformat()}" max="{end.isoformat()}" aria-describedby="datum-fehler"></div><div><label for="bis">Bis Datum</label><input id="bis" type="date" min="{start.isoformat()}" max="{end.isoformat()}" aria-describedby="datum-fehler"></div></div><p class="date-error" id="datum-fehler" role="status" hidden>Das Enddatum liegt vor dem Startdatum.</p>
<details class="advanced"><summary>Erweiterte Suche</summary><div class="advanced-grid"><div><label for="wochentag">Wochentag</label><select id="wochentag"><option value="">Alle Tage</option>{wochen_optionen}</select></div><div><label for="tageszeit">Tageszeit</label><select id="tageszeit"><option value="">Jederzeit</option><option value="vormittag">Vor 12 Uhr</option><option value="nachmittag">12–18 Uhr</option><option value="abend">Ab 18 Uhr</option></select></div><div><label for="spieler">Spieleranzahl</label><select id="spieler"><option value="">Alle Größen</option>{spieler_optionen}</select></div></div><p class="hint">Spielerfilter: freie Plätze und bekannte Mindestbestellmenge je Termin.</p></details>
<div class="search-actions"><a href="#raeume">Raum-Infos &amp; Altersregeln</a><button id="zuruecksetzen" type="button">Zurücksetzen</button></div></section>
<main id="termine"><div class="results-head"><div><h2 id="anzahl" aria-live="polite">{len(termine)} freie Termine</h2><p>Uhrzeit anklicken zum Anbieter · P. = freie Plätze · NEU = seit letztem Lauf</p></div><a class="jump js-only" id="naechste" href="#termine" hidden>Nächste freie Termine ↓</a></div>
<noscript><p>Filter benötigen JavaScript. Alle Termine und Raum-Infos sind unten sichtbar.</p></noscript><p class="empty" id="leer" {'hidden' if termine else ''}>Keine freien Termine für diese Auswahl im abgefragten Zeitraum. Wählt ein anderes Zimmer oder setzt die Filter zurück.</p>{''.join(tage)}</main>
<section class="room-section" id="raeume"><details id="room-details"><summary>Raum-Infos &amp; Altersregeln</summary><p class="muted">Sachliche Angaben aus den Buchungsdaten. Fehlende Angaben werden weggelassen. Bilder, vollständige Teilnahmebedingungen und verbindliche Details findet ihr auf der offiziellen Raumseite.</p><div class="room-grid">{''.join(karten)}</div></details></section>
<footer>Inoffizielle private Übersicht, ohne Gewähr · <a href="{esc(KONTAKT)}">Fehler oder Einwände melden</a><br>Keine Werbung · Kein Tracking · Buchung direkt beim Anbieter</footer></div><script>{AUSWAHL_SKRIPT}</script></body></html>''', encoding="utf-8")


def normalisiere_nummer(empfaenger):
    """iMessage findet Handynummern nur im internationalen Format: 0157… -> +49157…"""
    if "@" in empfaenger:  # Apple-ID als E-Mail-Adresse
        return empfaenger
    nummer = empfaenger.replace(" ", "").replace("-", "").replace("/", "")
    if nummer.startswith("00"):
        return "+" + nummer[2:]
    if nummer.startswith("0"):
        return "+49" + nummer[1:]
    return nummer


def sende_imessage(empfaenger, text):
    # Text und Empfänger gehen als Argumente rein, damit Anführungszeichen nichts kaputt machen.
    skript = """
on run argv
    tell application "Messages"
        set dienst to 1st account whose service type = iMessage
        send (item 2 of argv) to participant (item 1 of argv) of dienst
    end tell
end run
"""
    subprocess.run(["osascript", "-e", skript, empfaenger, text], check=True,
                   capture_output=True, text=True)


def nachricht_text(neue, erster_lauf):
    kopf = ("Zauberakademie: Überwachung gestartet, aktuell frei:" if erster_lauf
            else f"Zauberakademie: {len(neue)} neue{'r' if len(neue) == 1 else ''} freie{'r' if len(neue) == 1 else ''} Termin{'' if len(neue) == 1 else 'e'}:")
    zeilen = [kopf]
    for t in neue[:MAX_ZEILEN_NACHRICHT]:
        zeilen.append(f"• {termin_text(t)} ({t['frei']} Plätze)")
    if len(neue) > MAX_ZEILEN_NACHRICHT:
        zeilen.append(f"… und {len(neue) - MAX_ZEILEN_NACHRICHT} weitere")
    zeilen.append(f"Buchen: {BUCHUNGSSEITE}")
    return "\n".join(zeilen)


def taeglicher_lauf(tage, senden):
    start = date.today()
    end = start + timedelta(days=tage)
    abgefragt_um = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"[{abgefragt_um}] Täglicher Lauf: {start} bis {end}")

    raum_infos = {}
    zimmer, termine = alle_freien_termine(start, end, raum_infos)  # Fehler hier -> Abbruch, alter Stand bleibt erhalten

    vorher = lade_json(STAND_DATEI, None)
    erster_lauf = vorher is None
    alte_schluessel = set() if erster_lauf else {termin_schluessel(t) for t in vorher["termine"]}
    neue = [t for t in termine if termin_schluessel(t) not in alte_schluessel]
    zu_melden = [t for t in neue if t["zimmer_id"] == UEBERWACHTES_ZIMMER]
    # Zimmer ohne Vergleichsstand nicht komplett als NEU markieren.
    bekannte_zimmer = set() if erster_lauf else set(vorher.get("zimmer", [UEBERWACHTES_ZIMMER]))
    neue_schluessel = {termin_schluessel(t) for t in neue if t["zimmer_id"] in bekannte_zimmer}

    schreibe_html(zimmer, termine, neue_schluessel, abgefragt_um, start, end, raum_infos)
    print(f"{len(zimmer)} Zimmer, {len(termine)} freie Termine, davon {len(neue)} neu, "
          f"{len(zu_melden)} zu melden. HTML: {HTML_DATEI}")

    if not senden:
        # Testlauf: Stand nicht speichern, damit der echte Lauf dieselben Termine noch meldet.
        if zu_melden:
            print("--- Nachricht (nicht gesendet, --nicht-senden) ---\n" + nachricht_text(zu_melden, erster_lauf))
        return

    if zu_melden and NACHRICHT_DATEI:
        Path(NACHRICHT_DATEI).write_text(nachricht_text(zu_melden, erster_lauf), encoding="utf-8")
    elif zu_melden:
        text = nachricht_text(zu_melden, erster_lauf)
        empfaenger = lade_json(KONFIG_DATEI, {}).get("imessage_empfaenger", "").strip()
        if not empfaenger:
            # Stand nicht speichern, sonst gelten die Termine als gemeldet, obwohl niemand sie bekam.
            print(f"Kein Empfänger in {KONFIG_DATEI.name} eingetragen, nichts gesendet.")
            return
        else:
            try:
                sende_imessage(normalisiere_nummer(empfaenger), text)
                print("iMessage gesendet.")
            except subprocess.CalledProcessError as e:
                # Stand trotzdem nicht speichern, damit die Termine morgen erneut gemeldet werden.
                print(f"iMessage fehlgeschlagen: {e.stderr.strip()}", file=sys.stderr)
                sys.exit(1)

    STAND_DATEI.parent.mkdir(exist_ok=True)
    STAND_DATEI.write_text(json.dumps(
        {"abgefragt_um": abgefragt_um, "zimmer": sorted(zimmer), "termine": termine},
        ensure_ascii=False, indent=2
    ), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=None,
        help="Wie viele Tage ab heute prüfen (Standard: 60, bei --taeglich 90)",
    )
    parser.add_argument(
        "--year", type=int, default=None,
        help="Statt --days: gesamtes Jahr ab heute (oder 1.1.) bis 31.12. dieses Jahres prüfen",
    )
    parser.add_argument(
        "--taeglich", action="store_true",
        help="Täglicher Lauf: Ergebnis speichern, mit letztem Lauf vergleichen, "
             "neue Termine per iMessage melden",
    )
    parser.add_argument(
        "--nicht-senden", action="store_true",
        help="Bei --taeglich: Nachricht nur anzeigen statt senden (zum Testen)",
    )
    args = parser.parse_args()

    if args.taeglich:
        taeglicher_lauf(args.days or 90, senden=not args.nicht_senden)
        return

    today = date.today()
    if args.year:
        start = date(args.year, 1, 1) if args.year > today.year else today
        end = date(args.year, 12, 31)
    else:
        start = today
        end = today + timedelta(days=args.days or 60)

    print(f"Suche freie Termine vom {start.strftime('%d.%m.%Y')} bis {end.strftime('%d.%m.%Y')} ...\n")

    _, termine = alle_freien_termine(start, end)
    termine = [t for t in termine if t["zimmer_id"] == UEBERWACHTES_ZIMMER]
    if not termine:
        print("Keine freien Termine im gewählten Zeitraum gefunden.")
        return

    letzter_tag = None
    for t in termine:
        if t["datum"] != letzter_tag:
            d = date.fromisoformat(t["datum"])
            print(f"{WOCHENTAGE[d.weekday()]} {d.strftime('%d.%m.%Y')}:")
            letzter_tag = t["datum"]
        extra = f", mind. {t['min_spieler']} Spieler" if t["min_spieler"] else ""
        print(f"    {t['uhrzeit']} Uhr  –  {t['frei']} von {t['gesamt']} Plätzen frei{extra}")


if __name__ == "__main__":
    main()
