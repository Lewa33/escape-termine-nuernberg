# Freie Escape-Room-Termine Nürnberg

Inoffizielle private Übersicht der freien Termine von Finest Escape Nürnberg, kein Angebot des Anbieters.

Zwei geplante GitHub-Actions-Läufe pro Tag fragen die öffentliche Buchungsseite ab und veröffentlichen daraus eine
statische Seite. Geplant sind 10:17 und 16:17 Uhr in `Europe/Berlin` (einschließlich Sommer-/Winterzeit).
GitHub kann geplante Läufe verzögert starten. Die Zeiten sind eine praktische Verteilung;
wann der Anbieter Termine tatsächlich ändert, ist nicht bekannt. Besucher der Seite lösen keine Abfragen beim Anbieter aus. Die Daten sind ohne Gewähr,
verbindlich ist nur die Buchung beim Anbieter.

Fehler oder Einwände, auch vom Anbieter: bitte als [Issue](https://github.com/Lewa33/escape-termine-nuernberg/issues) melden.
Die Seite wird dann umgehend angepasst oder abgeschaltet.

## Oberfläche und Raumdaten

Die Datei bleibt vollständig statisch: CSS und JavaScript sind inline, es gibt keine externen
Schriften, Bilder, Skripte, Tracking- oder API-Anfragen im Browser. Hell/Dunkel folgt zunächst
der Systemeinstellung und lässt sich über „Ansicht“ umschalten. Die Gestaltung „Verbotene
Bibliothek“ kombiniert dunkle Holzfarben und Gold mit einem hellen Pergamentmodus.
Die Buchschrift verwendet ausschließlich lokale Systemschriften. Ohne JavaScript bleiben alle
Termine und Raum-Infos lesbar. Die Zimmerauswahl verwendet weiterhin den bisherigen
localStorage-Schlüssel; blockierter Speicher verhindert die Filterung nicht.

Die Termine sind je Tag und Zimmer gebündelt. „Raum wählen“ öffnet eine Übersicht mit
anklickbaren Raumkarten samt Standort und Anzahl freier Termine. Nach der Auswahl klappt
sie wieder zu. Start- und Enddatum stehen direkt darunter. Wochentag, Tageszeit und Spielerzahl
sind unter „Erweiterte Suche“ eingeklappt; Raum-Infos und Altersregeln sind ebenfalls einklappbar.
Ein zusätzlicher Standortfilter entfällt. Die Bibliotheksfarben und die Buchschrift bleiben,
der große Einführungsteil und die Illustration entfallen zugunsten schneller sichtbarer Termine.
Beide Datumsgrenzen zählen einschließlich. Ein Enddatum vor dem Startdatum wird erklärt.
Der Spielerfilter prüft freie Plätze und bekannte Mindestbestellmenge je Termin.
Bei unbekannter Mindestbestellmenge erscheint ein Termin nur ohne Spielerfilter.
„NEU“ vergleicht weiterhin mit dem letzten Lauf. Zauberakademie `12248` wird als Teil 2
kenntlich gemacht; ausschließlich Teil 1 (`12242`) löst Meldungen aus.

Raum-Fakten werden während der bisherigen Tagesabfragen aus `location`, `seats`,
`additionalInfo` und `metaDescription` gelesen. Es gibt keine weiteren Requests je Raum.
API-HTML wird nur zur Faktenerkennung gelesen und niemals als Markup ausgegeben.
Alle dynamischen Werte werden beim Schreiben der HTML-Datei escaped.
Altersbedingungen mit Begleitpersonen bleiben als Bedingungen erhalten.

### Tatsächlich fehlende Angaben (API-Stichprobe vom 04.11.2026)

- **Dauer:** In den genannten Event-Feldern bei allen zehn Zimmern nicht angegeben.
  Die Differenz zwischen Slot-Start und -Ende wird bewusst nicht als Spieldauer ausgegeben.
- **Spielerzahl:** `seats` ist nur bei „Der Henker der Lochgefängnisse“ und „Sherlock Holmes“
  befüllt (je 6). Bei den übrigen acht Zimmern fehlt die Raumkapazität. Eine allgemeine
  Mindestspielerzahl oder empfohlene Teamgröße liefert keines dieser Event-Felder.
  Terminbezogene Platzanzahlen bleiben separat sichtbar und filterbar.
- **Schwierigkeit:** Nur bei „Auroras Magischer Würfel“ ist „leicht bis mittel“ erkennbar;
  bei den anderen neun Zimmern fehlt eine Angabe.
- **Mindestalter:** Bei „Auroras Magischer Würfel“ fehlt es. „Steampunk Puppenspieler“,
  „Das Geheimnis der toten Mönche“ und „Die Abenteuer des Halbling“ nennen Begleitregeln
  unter 16 bzw. unter 14, jedoch kein absolutes Mindestalter. Deshalb werden dort nur die
  Begleitregeln angezeigt.
- `additionalInfo` ist in dieser Stichprobe bei allen zehn Zimmern leer.

Es werden nur kurze sachliche Fakten und die Namen ausgegeben, keine Werbebeschreibungen,
Fotos, Cover oder Logos. Bilder, vollständige Bedingungen und verbindliche Details sind
über die jeweilige offizielle Raumseite in `ZIMMER_SEITEN` erreichbar.

## Prüfen

Offline, nur Python-Standardbibliothek:

```sh
python3 -m unittest discover -s tests -v
```

Ein echter Abruf (sparsam verwenden; sendet nichts und speichert den Vergleichsstand nicht):

```sh
HTML_DATEI=site/index.html python3 escape_room_slots.py --taeglich --nicht-senden --days 120
```

Am Workflow wurde nur der Zeitplan auf zwei tägliche Läufe umgestellt. API-Pausen,
Meldedatei, Issue-Zuweisung/-Erwähnung, Push-Wiederholungen und das Format des Vergleichsstands bleiben unverändert.
