import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from threading import Event
from unittest.mock import patch

import badminton_bot as bot
import watcher
import notifications


class WatchTests(unittest.TestCase):
    def test_explicit_date_survives_midnight(self):
        cfg = {'schedule': {'days_ahead': 7}, 'target': {'date': '2026-11-06'}, 'site': {'booking_url': 'x', 'login_url': 'x'}}
        result = bot.build_variables(cfg, datetime(2026, 11, 5, 0, 1))
        self.assertEqual(result['target_date'], '2026-11-06')

    def test_released_slot_is_attempted_until_confirmed_once(self):
        attempts = []
        notices = []
        def attempt():
            attempts.append(1)
            return 'unavailable' if len(attempts) < 3 else 'confirmed'
        result = watcher.monitor(attempt, lambda: True, Event(), lambda seconds: None, notices.append, 5)
        self.assertEqual(result, 'confirmed')
        self.assertEqual(len(attempts), 3)
        self.assertEqual(notices, ['confirmed'])

    def test_unknown_submit_never_retries(self):
        attempts = []
        result = watcher.monitor(lambda: attempts.append(1) or 'unknown', lambda: True,
                                 Event(), lambda seconds: None, lambda x: None, 5)
        self.assertEqual((result, len(attempts)), ('unknown', 1))

    def test_deadline_does_not_attempt(self):
        with patch('watcher.logging.info'):
            result = watcher.monitor(lambda: self.fail('past deadline'), lambda: False,
                                     Event(), lambda seconds: None, lambda x: None, 5)
        self.assertEqual(result, 'expired')

    def test_cancel_does_not_attempt(self):
        stop = Event(); stop.set()
        self.assertEqual(watcher.monitor(lambda: self.fail(), lambda: True, stop,
                                         lambda x: None, lambda x: None, 5), 'cancelled')

    def test_cutoff_cannot_outlive_earliest_slot(self):
        end = watcher.cutoff('2026-11-06', [['19:00-20:00'], ['18:00-19:00']], '20:00')
        self.assertEqual(end.isoformat(), '2026-11-06T18:00:00+08:00')

    def test_bad_notification_key_is_rejected(self):
        with self.assertRaises(ValueError):
            notifications.send('title', 'body', 'not-a-key')

    def test_notification_retry_does_not_change_booking_result(self):
        import io
        with patch('notifications.urlopen', side_effect=[OSError('offline'), io.BytesIO(b'{"code":0}')]), \
             patch('notifications.time.sleep'):
            self.assertTrue(notifications.send('title', 'body', 'SCT123test'))

    def test_notification_failure_is_bounded(self):
        with patch('notifications.urlopen', side_effect=OSError('offline')) as request, \
             patch('notifications.time.sleep'):
            self.assertFalse(notifications.send('title', 'body', 'SCT123test'))
            self.assertEqual(request.call_count, 3)

    def test_submission_click_timeout_is_never_retried(self):
        from types import SimpleNamespace
        cfg = {'target': {'date': '2026-11-06'}, 'schedule': {'days_ahead': 7},
               'site': {'booking_url': 'x', 'login_url': 'x', 'detail_url': 'x'},
               'booking_steps': [{'action': 'sjtu_select_slot'}, {'action': 'click', 'final_submit': True}]}
        page = unittest.mock.MagicMock()
        page.evaluate.return_value = {'code': 0, 'data': {'id': 'user'}}
        context = unittest.mock.MagicMock()
        attempt = watcher.BookingAttempt(page, context, cfg, True, lambda x: None, lambda: True)
        def select(*args):
            attempt.rt.variables.update(selected_court='场地1', selected_time_slot='19:00-20:00')
        with patch('watcher.bot.pause_for_captcha'), patch('watcher.bot.wait_for_sjtu_detail'), \
             patch('watcher.select_date'), patch('watcher.bot.select_sjtu_slot', side_effect=select), \
             patch('watcher.matching_order_cards', return_value=[]), patch('watcher.bot.screenshot'), \
             patch('watcher.bot.perform_step', side_effect=bot.PlaywrightTimeoutError('lost response')) as click:
            self.assertEqual(attempt(), 'unknown')
            self.assertEqual(attempt(), 'unknown')
            self.assertEqual(click.call_count, 1)

    def test_continuous_mode_does_not_submit_a_partial_selection(self):
        cfg = {'target': {'date':'2026-11-06'}, 'schedule':{'days_ahead':7},
               'site':{'booking_url':'x','login_url':'x','detail_url':'x'},
               'booking_steps':[{'action':'sjtu_select_slot'},{'action':'click','final_submit':True}]}
        page=unittest.mock.MagicMock()
        page.evaluate.return_value={'code':0,'data':{'id':'user'}}
        page.locator.return_value.count.return_value=1
        attempt=watcher.BookingAttempt(page,unittest.mock.MagicMock(),cfg,True,lambda x:None,lambda:True)
        def select(*args):
            attempt.rt.variables.update(selected_court='场地1',selected_time_slot='20:00-22:00',selected_slot_count='2')
        with patch('watcher.bot.pause_for_captcha'), patch('watcher.bot.wait_for_sjtu_detail'), \
             patch('watcher.bot.select_sjtu_sport'), patch('watcher.select_date'), \
             patch('watcher.bot.select_sjtu_slot',side_effect=select), patch('watcher.bot.perform_step') as submit:
            self.assertEqual(attempt(),'unavailable')
            submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
