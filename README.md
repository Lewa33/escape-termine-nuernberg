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
Schriften, Bilder, Skripte, Tracking- oder API-Anfragen im Browser. Hell/Dunkel folgt
ausschließlich der Systemeinstellung. Ein eigener Modusschalter entfällt.
Suchoptionen und Terminbereich sind durch einen Suchkasten und eine Trennlinie voneinander abgesetzt. Die Gestaltung „Verbotene
Bibliothek“ kombiniert dunkle Holzfarben und Gold mit einem hellen Pergamentmodus. Eine kleine
selbst gezeichnete Tür aus Inline-SVG steht neben dem Seitentitel.
Die Buchschrift verwendet ausschließlich lokale Systemschriften. Ohne JavaScript bleiben alle
Termine und Raum-Infos lesbar. Die Zimmerauswahl verwendet weiterhin den bisherigen
localStorage-Schlüssel; blockierter Speicher verhindert die Filterung nicht.

Im Mittelpunkt stehen die Zimmerauswahl und die freien Uhrzeiten je Tag. „Ändern“
öffnet Schaltflächen für alle Räume mit den vier wichtigsten Eckdaten. Ohne gemerkte Auswahl startet die Seite mit Zauberakademie 2;
eine vorhandene Auswahl bleibt erhalten. Bei einem gewählten Zimmer werden Name und Adresse
nicht bei jedem Tag wiederholt. „Rauminfo“ öffnet Spielerzahl, Dauer, Schwierigkeit, Standort, Altersregeln und den offiziellen Link
in einem separaten Dialog. Ohne JavaScript stehen diese Angaben weiterhin unter den Terminen.

„Suche eingrenzen“ enthält Start-/Enddatum, Wochentag, Tageszeit und Spielerzahl und ist
zunächst geschlossen. Zurücksetzen löscht nur die Suchfilter und behält das Zimmer.
Beide Datumsgrenzen zählen einschließlich. Ein Enddatum vor dem Startdatum wird erklärt.
Der Spielerfilter prüft freie Plätze und bekannte Mindestbestellmenge je Termin.
Bei unbekannter Mindestbestellmenge erscheint ein Termin nur ohne Spielerfilter.
„NEU“ vergleicht weiterhin mit dem letzten Lauf. Zauberakademie `12248` wird als Teil 2
kenntlich gemacht; ausschließlich Teil 1 (`12242`) löst Meldungen aus.

Raum-Fakten werden während der bisherigen Tagesabfragen aus `location`, `seats`,
`additionalInfo` und `metaDescription` gelesen. Es gibt keine weiteren Requests je Raum.
API-HTML wird nur zur Faktenerkennung gelesen und niemals als Markup ausgegeben.
Alle dynamischen Werte werden beim Schreiben der HTML-Datei escaped.
Spielerzahl, Spieldauer, Schwierigkeit und Mindestalter werden für die zehn bekannten
Räume durch die am 05.11.2026 manuell geprüften Angaben der offiziellen Raumseiten
ergänzt (RAUMPROFILE). Diese Angaben haben bei Abweichungen Vorrang. Zum Beispiel
nennt Auroras Raumseite „einfach“ und die API „leicht bis mittel“. Begleitregeln
werden beim angegebenen Mindestalter berücksichtigt. Die Spielerzahl aus dem Raumprofil
ist unabhängig vom Spielerfilter für konkrete Termine.

Über „E-Mail-Hinweis“ lässt sich die Zustellung der GitHub-Meldungen für
Zauberakademie 1 einrichten. GitHub-Konto und aktivierte E-Mail-Zustellung sind
erforderlich. Ein Abo für Issues dieses Projekts umfasst auch andere Issues.
Die Terminseite erfasst keine E-Mail-Adressen.

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
  unter 16 bzw. unter 14, jedoch kein absolutes Mindestalter. Das Mindestalter
  steht auf den offiziellen Raumseiten.
- `additionalInfo` ist in dieser Stichprobe bei allen zehn Zimmern leer.

Von den offiziellen Seiten werden nur kurze sachliche Fakten und Namen übernommen. Bilder, vollständige Bedingungen und verbindliche Details sind
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
