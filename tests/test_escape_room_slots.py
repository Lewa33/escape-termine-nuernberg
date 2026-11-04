import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import escape_room_slots as app


class RoomOverviewTests(unittest.TestCase):
    def test_facts_extract_only_facts(self):
        facts = app.raum_fakten({
            'location': {'locationAddress1': 'Bucher Straße 76'}, 'seats': 6,
            'additionalInfo': '',
            'metaDescription': '<p>Mindestalter ist <b>16 Jahre</b></p><p>Werbetext</p>',
        })
        self.assertEqual(facts, {'Standort': 'Bucher Straße 76',
                                'Spielerzahl': 'Bis 6 Personen (Raumkapazität)',
                                'Mindestalter': '16 Jahre'})
        self.assertEqual(app.raum_fakten({'seats': None, 'metaDescription': ''}), {})

    def test_age_conditions_are_preserved(self):
        for text, expected in [
            ('Mindestalter ab 16 Jahre ohne volljährige Begleitung '
             'ab 14 Jahren mit mindestens 2 volljährigen Begleitern', 'mindestens 2 Volljährigen'),
            ('Mindestalter 14 Jahre in Begleitung eines Erwachsenen, '
             '16 Jahre ohne Begleitung eines Erwachsenen.', 'Ab 14 mit erwachsener Begleitung'),
            ('Bei Jugendlichen unter 16 Jahren, muss mindestens eine erwachsene Begleitperson '
             'mit im Spiel sein. Bei Jugendlichen unter 14 Jahren, mindestens genau so viele '
             'Erwachsenen wie Kinder!', 'mindestens so viele Erwachsene wie Kinder'),
            ('FSK 16', '16 Jahre'),
        ]:
            with self.subTest(text=text):
                self.assertIn(expected, ' '.join(app.raum_fakten({'metaDescription': text}).values()))

    def test_duration_not_inferred_from_slot_length(self):
        self.assertNotIn('Dauer', app.raum_fakten({'slots': [
            {'start': '2026-11-05T16:00:00', 'end': '2026-11-05T17:00:00'}]}))
        self.assertEqual(app.raum_fakten({'additionalInfo': 'Dauer: 60 Minuten'})['Dauer'], '60 Minuten')

    def test_metadata_uses_existing_day_request_including_sold_out(self):
        event = {'id': 12242, 'name': 'Zauberakademie', 'seats': None,
                 'location': {'locationAddress1': 'Bucher Straße 76'}, 'slots': []}
        facts = {}
        with patch.object(app, 'api_request', return_value={'events': [event]}) as request:
            rooms, free = app.get_slots_for_day('token', '2026-11-05', facts)
        request.assert_called_once()
        self.assertEqual(rooms, {'12242': 'Zauberakademie'})
        self.assertEqual(free, [])
        self.assertEqual(facts['12242']['Standort'], 'Bucher Straße 76')

    def test_renderer_escapes_every_api_value_and_keeps_new_badge(self):
        unsafe = '\"><img src=x onerror=alert(1)>'
        slot = {'zimmer_id': unsafe, 'zimmer': unsafe, 'datum': '2026-11-05',
                'uhrzeit': '16:00', 'frei': unsafe, 'gesamt': unsafe, 'min_spieler': unsafe}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'HTML_DATEI', Path(tmp)/'index.html'):
            app.schreibe_html({unsafe: unsafe, '12242': 'Zauberakademie'}, [slot],
                             {app.termin_schluessel(slot)}, unsafe, date(2026, 11, 4),
                             date(2026, 11, 6), {unsafe: {'Standort': unsafe, 'Alter': unsafe}})
            page = app.HTML_DATEI.read_text()
        self.assertNotIn('<img', page)
        self.assertIn('&lt;img', page)
        self.assertIn('<b>NEU</b>', page)
        self.assertIn('Zauberakademie (nichts frei)', page)
        self.assertIn('name="robots" content="noindex"', page)
        self.assertNotIn('<script src=', page)
        self.assertNotIn('fetch(', page)
        self.assertNotIn('api.quinbook.com', page)
        self.assertNotIn('XMLHttpRequest', page)

    def test_legacy_state_keys(self):
        self.assertEqual(app.termin_schluessel({'datum':'2026-11-05', 'uhrzeit':'16:00'}),
                         ('12242', '2026-11-05', '16:00'))

    def test_only_monitored_room_notifies_and_state_stays_compatible(self):
        slots = [dict(zimmer_id=zid, zimmer=zid, datum='2026-11-05', uhrzeit='16:00',
                      frei=6, gesamt=6, min_spieler=2) for zid in ['12242', '17163']]
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)/'state.json'
            message = Path(tmp)/'message.txt'
            state.write_text(json.dumps({'termine': [{'datum':'2026-11-04', 'uhrzeit':'16:00'}]}))
            original = state.read_bytes()
            with patch.object(app, 'STAND_DATEI', state), patch.object(app, 'NACHRICHT_DATEI', str(message)), \
                 patch.object(app, 'alle_freien_termine', return_value=({'12242':'Zauberakademie', '17163':'Vecnas Game'}, slots)), \
                 patch.object(app, 'schreibe_html'), patch.object(app, 'nachricht_text', return_value='message') as notification:
                app.taeglicher_lauf(120, senden=False)
                self.assertEqual(state.read_bytes(), original)
                self.assertFalse(message.exists())
                notification.reset_mock()
                app.taeglicher_lauf(120, senden=True)
                self.assertEqual([t['zimmer_id'] for t in notification.call_args.args[0]], ['12242'])
            saved = json.loads(state.read_text())
            self.assertEqual(set(saved), {'abgefragt_um', 'zimmer', 'termine'})
            self.assertEqual(saved['termine'], slots)


if __name__ == '__main__':
    unittest.main()
