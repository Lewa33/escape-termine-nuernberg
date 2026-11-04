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
  const booking = document.getElementById('buchung');
  const roomButtons = Array.from(document.querySelectorAll('.room-choice'));
  let selectedRoom = roomButtons.some(button => button.dataset.room === '12248') ? '12248' : 'alle';
  const dialog = document.getElementById('raum-dialog');
  document.getElementById('dialog-inhalt').append(document.querySelector('#raeume .room-grid'));
  document.getElementById('raeume').hidden = true;
  function openInfo(room) {
    document.querySelectorAll('.raum-info').forEach(card => { card.hidden = room !== 'alle' && card.dataset.zimmer !== room; });
    dialog.showModal();
  }
  document.getElementById('rauminfo').addEventListener('click', () => openInfo(selectedRoom));
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
    const hasFilters = ids.some(id => controls[id].value);
    document.getElementById('search-label').textContent = hasFilters ? 'Suche eingrenzen · aktiv' : 'Suche eingrenzen';
    document.getElementById('zuruecksetzen').hidden = !hasFilters;
    empty.textContent = invalidRange ? 'Das Enddatum liegt vor dem Startdatum.'
      : hasFilters ? 'Keine Termine für diese Suche.' : 'Bis ' + empty.dataset.bis + ' sind keine Termine frei.';
    count.textContent = total ? total.toLocaleString('de-DE') + (total === 1 ? ' freier Termin' : ' freie Termine') : 'Freie Termine';
    const selectedButton = roomButtons.find(button => button.dataset.room === selectedRoom);
    booking.href = selectedButton.dataset.seite;
    booking.hidden = total > 0;
    document.body.classList.toggle('single-room', selectedRoom !== 'alle');
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
  document.querySelectorAll('.raum-name a').forEach(link => link.addEventListener('click', event => {
    event.preventDefault(); openInfo(link.closest('.raum-termine').dataset.zimmer);
  }));
  ids.forEach(id => controls[id].addEventListener('change', show));
  document.getElementById('zuruecksetzen').addEventListener('click', () => {
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
:root { color-scheme:light dark; --bg:#f0e6d0; --surface:#faf3e2; --text:#30251e; --muted:#6e5d49; --line:#cdbb96; --accent:#775121; --soft:#e8dabe; --new:#f1d18e; --newtext:#5d3416; }
@media(prefers-color-scheme:dark) { :root:not([data-theme=light]) { --bg:#181311; --surface:#251f1a; --text:#f0e6d2; --muted:#c2b298; --line:#51412f; --accent:#dfbb78; --soft:#32281e; --new:#593d21; --newtext:#ffe6ad; } }
:root[data-theme=dark] { color-scheme:dark; --bg:#181311; --surface:#251f1a; --text:#f0e6d2; --muted:#c2b298; --line:#51412f; --accent:#dfbb78; --soft:#32281e; --new:#593d21; --newtext:#ffe6ad; }
:root[data-theme=light] { color-scheme:light; }
* { box-sizing:border-box; } [hidden] { display:none !important; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.45 system-ui,-apple-system,sans-serif; }
.wrap { max-width:850px; margin:auto; padding:0 18px; } a { color:var(--accent); text-underline-offset:3px; }
button,input,select { font:inherit; color:var(--text); background:var(--surface); border:1px solid var(--line); border-radius:5px; min-height:44px; padding:9px; max-width:100%; }
button,summary { cursor:pointer; } button:hover { border-color:var(--accent); } :focus-visible { outline:3px solid var(--accent); outline-offset:3px; }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
.top { display:flex; justify-content:space-between; align-items:center; gap:10px; padding:14px 0 8px; }
h1 { font:400 1.4rem/1.15 Georgia,serif; margin:0; } h1 span { color:var(--accent); } .mode { font-size:.75rem; min-height:36px; padding:5px; }
.notice { margin:0 0 18px; color:var(--muted); font-size:.67rem; line-height:1.5; }
.quick-search { margin-bottom:18px; } .room-bar { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; align-items:start; }
.room-picker { min-width:0; } .room-picker>summary { display:flex; justify-content:space-between; align-items:center; gap:10px; min-height:56px; background:var(--surface); border:1px solid var(--accent); border-radius:6px; padding:10px 12px; list-style:none; }
.room-picker>summary::-webkit-details-marker { display:none; } #selected-room { font-size:1.05rem; font-weight:650; overflow-wrap:anywhere; }
.change-label { font-size:.7rem; color:var(--accent); white-space:nowrap; } .change-label:after { content:' ▾'; }
#rauminfo { font-size:.75rem; min-height:56px; padding:10px; border-color:transparent; background:transparent; color:var(--accent); }
.room-bar:has(.room-picker[open]) { grid-template-columns:minmax(0,1fr); } .room-bar:has(.room-picker[open]) #rauminfo { display:none; }
.room-buttons { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:8px 0; }
.room-choice { min-width:0; text-align:left; padding:10px; overflow-wrap:anywhere; } .room-choice strong { display:block; font-size:.8rem; } .room-choice span { display:block; margin-top:4px; font-size:.7rem; color:var(--muted); }
.room-choice[aria-pressed=true] { border-color:var(--accent); background:var(--soft); box-shadow:inset 0 0 0 1px var(--accent); } .all-rooms { grid-column:1/-1; } .all-rooms strong,.all-rooms span { display:inline; margin-right:8px; }
.search-options { margin-top:4px; } .search-options>summary { font-size:.75rem; color:var(--accent); padding:10px 0; min-height:40px; }
.date-grid,.advanced-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; } .advanced-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }
label { display:block; margin:8px 0 4px; font-size:.75rem; } input,select { width:100%; min-width:0; } .date-error,.hint { font-size:.75rem; } .hint { color:var(--muted); } #zuruecksetzen { font-size:.75rem; margin:8px 0; }
.results-head { display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:8px; } h2 { font-size:1rem; font-weight:600; margin:0; } .stamp { font-size:.65rem; color:var(--muted); white-space:nowrap; }
.empty { margin:0; padding:18px 0 12px; color:var(--muted); font-size:.9rem; } .booking-link { display:inline-block; padding:10px 0; font-size:.8rem; }
.tag { border:1px solid var(--line); background:var(--surface); border-radius:6px; margin-bottom:12px; overflow:hidden; } .tag-kopf { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:10px 12px; background:var(--soft); }
.tag-kopf h3 { font:400 1rem Georgia,serif; margin:0; } .tag-anzahl { color:var(--muted); font-size:.65rem; }
.raum-termine { padding:12px; border-top:1px solid var(--line); } .raum-name { font-size:.8rem; margin-bottom:8px; } .adresse { display:block; font-size:.65rem; color:var(--muted); }
.zeiten { display:flex; flex-wrap:wrap; gap:8px; } .slot { display:inline-flex; align-items:center; gap:5px; border:1px solid var(--line); padding:10px 11px; min-height:44px; border-radius:4px; text-decoration:none; font-size:.9rem; font-variant-numeric:tabular-nums; }
.slot:hover { background:var(--soft); border-color:var(--accent); } .platz { color:var(--muted); font-size:.65rem; } .slot b { padding:2px 3px; border-radius:2px; color:var(--newtext); background:var(--new); font-size:.55rem; }
.single-room .raum-name { display:none; } .single-room .tag-anzahl { display:none; }
.room-grid { display:grid; gap:12px; margin:10px 0; } .raum-info { min-width:0; padding:12px 0; } .raum-info h3 { font:400 1.25rem Georgia,serif; margin:0 0 10px; } .raum-info p { font-size:.8rem; color:var(--muted); } dl { font-size:.85rem; } dt { color:var(--muted); margin-top:10px; } dd { margin:2px 0; } .raum-info a { font-size:.8rem; }
dialog { color:var(--text); background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:18px; width:min(550px,calc(100% - 24px)); max-height:85vh; overflow:auto; } dialog::backdrop { background:#0009; } .dialog-bar { display:flex; justify-content:space-between; align-items:center; gap:12px; } .dialog-bar button { font-size:.8rem; }
footer { border-top:1px solid var(--line); margin-top:24px; padding:12px 0 24px; color:var(--muted); font-size:.72rem; } footer summary { padding:8px 0; } .room-section { margin-top:20px; }
@media(max-width:600px) { .wrap { padding:0 12px; } h1 { font-size:1.15rem; } .room-buttons { grid-template-columns:repeat(2,minmax(0,1fr)); } .advanced-grid { grid-template-columns:1fr; gap:0; } #selected-room { font-size:.95rem; } .room-picker>summary { padding:10px; } .change-label { font-size:.62rem; } .results-head { flex-wrap:wrap; gap:3px; } }
"""


def schreibe_html(zimmer, termine, neue_schluessel, abgefragt_um, start, end, raum_infos=None):
    """Eine eigenständige HTML-Datei, ausschließlich mit escapten API-Fakten."""
    raum_infos = raum_infos or {}
    # Teil 2 heißt in der API nur „Die Rückkehr des Dunklen Lords“.
    # Nur die HTML-Anzeige ergänzen; IDs, API-Namen im Stand und Meldungen bleiben gleich.
    teile = {"12242": 1, "12248": 2}
    zimmer = {zid: f"Zauberakademie – Teil {teile[zid]} · {name}" if zid in teile else name
              for zid, name in zimmer.items()}
    anzahl = Counter(t["zimmer_id"] for t in termine)
    raum_buttons = []
    karten = []
    for zid, name in sorted(zimmer.items(), key=lambda item: (0 if item[0] == "12248" else 1 if item[0] == "12242" else 2, item[1].casefold())):
        stand = f"{anzahl[zid]} frei" if anzahl[zid] else "nichts frei"
        fakten = raum_infos.get(zid, {})
        standort = fakten.get("Standort", "")
        kurzname = f"Zauberakademie {teile[zid]}" if zid in teile else name
        raum_buttons.append(f'<button type="button" class="room-choice" data-room="{esc(zid)}" data-label="{esc(kurzname)}" data-seite="{esc(ZIMMER_SEITEN.get(zid, WEBSITE))}" aria-pressed="false" aria-label="{esc(name)} ({esc(stand)})"><strong>{esc(kurzname)}</strong><span class="room-count">{esc(stand)}</span></button>')
        daten = ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in fakten.items())
        karten.append(f'''<article class="raum-info panel" id="raum-{esc(zid)}" data-zimmer="{esc(zid)}" data-standort="{esc(standort)}">
<h3>{esc(name)}</h3><p class="muted">{esc(stand)}</p><dl>{daten}</dl>
<a href="{esc(ZIMMER_SEITEN.get(zid, WEBSITE))}">Offizielle Raumseite · Bilder &amp; Details ↗</a></article>''')
    raum_buttons.append(f'<button type="button" class="room-choice all-rooms" data-room="alle" data-label="Alle Zimmer" data-seite="{esc(WEBSITE)}" aria-pressed="false"><strong>Alle Zimmer</strong><span>{len(termine)} frei</span></button>')
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
<body><div class="wrap"><header class="top"><h1>Escape-Termine <span>Nürnberg</span></h1><div class="js-only" hidden><label class="sr-only" for="modus">Ansicht</label><select class="mode" id="modus"><option value="auto">Auto</option><option value="light">Hell</option><option value="dark">Dunkel</option></select></div></header>
<p class="notice">Inoffizielle private Übersicht, ohne Gewähr. <a href="{esc(KONTAKT)}">Fehler oder Einwände melden</a></p>
<section id="filter" class="quick-search js-only" aria-label="Terminsuche" hidden>
<div class="room-bar"><details id="room-picker" class="room-picker"><summary><span class="sr-only">Raum wählen: </span><strong id="selected-room">Zimmer wählen</strong><span class="change-label">Zimmer ändern</span></summary><div class="room-buttons" role="group" aria-label="Zimmerauswahl">{''.join(raum_buttons)}</div></details><button id="rauminfo" type="button">Rauminfo</button></div>
<details class="search-options"><summary id="search-label">Suche eingrenzen</summary>
<div class="date-grid"><div><label for="ab">Ab Datum</label><input id="ab" type="date" min="{start.isoformat()}" max="{end.isoformat()}" aria-describedby="datum-fehler"></div><div><label for="bis">Bis Datum</label><input id="bis" type="date" min="{start.isoformat()}" max="{end.isoformat()}" aria-describedby="datum-fehler"></div></div><p class="date-error" id="datum-fehler" role="status" hidden>Das Enddatum liegt vor dem Startdatum.</p>
<div class="advanced-grid"><div><label for="wochentag">Wochentag</label><select id="wochentag"><option value="">Alle Tage</option>{wochen_optionen}</select></div><div><label for="tageszeit">Tageszeit</label><select id="tageszeit"><option value="">Jederzeit</option><option value="vormittag">Vor 12 Uhr</option><option value="nachmittag">12–18 Uhr</option><option value="abend">Ab 18 Uhr</option></select></div><div><label for="spieler">Spieleranzahl</label><select id="spieler"><option value="">Alle Größen</option>{spieler_optionen}</select></div></div><p class="hint">Spielerfilter: freie Plätze und bekannte Mindestbestellmenge je Termin.</p><button id="zuruecksetzen" type="button">Suchfilter zurücksetzen</button></details></section>
<main id="termine"><div class="results-head"><h2 id="anzahl" aria-live="polite">{len(termine)} freie Termine</h2><span class="stamp">Stand {esc(abgefragt_um)}</span></div>
<noscript><p>Filter benötigen JavaScript. Alle Termine und Raum-Infos sind unten sichtbar.</p></noscript><p class="empty" id="leer" data-bis="{end.strftime('%d.%m.%Y')}" {'hidden' if termine else ''}>Keine freien Termine für diese Auswahl im abgefragten Zeitraum. </p><a id="buchung" class="booking-link" href="{esc(WEBSITE)}">Beim Anbieter prüfen ↗</a>{''.join(tage)}</main>
<section class="room-section" id="raeume"><details id="room-details"><summary>Raum-Infos &amp; Altersregeln</summary><p class="muted">Sachliche Angaben aus den Buchungsdaten. Fehlende Angaben werden weggelassen. Bilder, vollständige Teilnahmebedingungen und verbindliche Details findet ihr auf der offiziellen Raumseite.</p><div class="room-grid">{''.join(karten)}</div></details></section>
<dialog id="raum-dialog" aria-labelledby="dialog-title"><div class="dialog-bar"><h2 id="dialog-title">Rauminfo</h2><form method="dialog"><button>Schließen</button></form></div><div id="dialog-inhalt"></div></dialog>
<footer><details><summary>Hinweise zur Übersicht</summary><p>Aktualisierung zweimal täglich, gegen 10:17 und 16:17 Uhr. Verbindlich ist die Buchung beim Anbieter.</p><p>P. = freie Plätze. NEU = seit dem letzten Lauf erstmals oder wieder frei. Abgefragter Zeitraum: {start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')}.</p><p>Keine Werbung, kein Tracking. Raumangaben sind sachliche Auszüge aus den Buchungsdaten. Fehlende Angaben bleiben weg.</p></details></footer></div><script>{AUSWAHL_SKRIPT}</script></body></html>''', encoding="utf-8")


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
