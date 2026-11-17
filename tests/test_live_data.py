"""Regression: the app is not the system trace's most recent event."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from live_data import LiveFeed


def marker(tid, phase='send', time=1000000000):
    return f'LTI_EVENT mono_ns={time} tid={tid} pid=10 job=7 phase={phase} v=1 resource=0\n'


def switch(time, prev, next_tid, cpu=3):
    return (f'app-{prev} [{cpu:03}]  {time}: sched_switch: prev_comm=app '
            f'prev_pid={prev} prev_prio=120 prev_state=S ==> '
            f'next_comm=app next_pid={next_tid} next_prio=120\n')


class LiveFeedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'live-test.events.log'
        self.path.write_text(marker(11)+marker(12, 'receive', 1001000000))
        self.report = self.path.with_name('live-test.txt')

    def tearDown(self):
        self.directory.cleanup()

    def drain(self, feed):
        for _ in range(50):
            feed.update()
            if not feed.loading():
                return
        self.fail('feed did not catch up')

    def test_unrelated_tail_does_not_evict_app_and_idle_poll_keeps_history(self):
        related = switch('1.001000', 11, 12)+switch('1.003000', 12, 11)
        unrelated = switch('1.004000', 500, 600)*6000  # > old 512 KiB tail
        self.report.write_text(related+unrelated)
        feed = LiveFeed(self.path)
        self.drain(feed)
        first = feed.snapshot()
        self.assertEqual(len(first['scheduler']), 2)
        self.assertEqual(first['cpus'], [3])
        with self.report.open('a') as out:
            out.write(unrelated)
        self.drain(feed)
        self.assertEqual(feed.snapshot()['scheduler'], first['scheduler'])
        self.assertEqual(feed.snapshot()['thread_ids'], [11, 12])

    def test_tid_remains_known_after_sdk_events_roll_out_of_response(self):
        self.report.write_text(switch('1.001000', 11, 12))
        feed = LiveFeed(self.path, max_events=1)
        feed.update()
        with self.path.open('a') as out:
            out.write(marker(11, 'done', 1004000000))
        with self.report.open('a') as out:
            out.write(switch('1.005000', 12, 0))
        feed.update()
        self.assertEqual(feed.snapshot()['thread_ids'], [11, 12])
        self.assertEqual(len(feed.snapshot()['scheduler']), 2)

    def test_thread_discovered_late_replays_overlap_without_duplicate_events(self):
        self.path.write_text(marker(11))
        self.report.write_text(switch('1.001000', 0, 12)+switch('1.002000', 11, 0))
        feed = LiveFeed(self.path);feed.update()
        self.assertEqual(len(feed.snapshot()['scheduler']), 1)
        with self.path.open('a') as out:
            out.write(marker(12, 'receive', 1001000000))
        feed.update()
        self.assertEqual(len(feed.snapshot()['scheduler']), 2)
        feed.update()
        self.assertEqual(len(feed.snapshot()['scheduler']), 2)

    def test_partial_line_is_consumed_only_once_complete(self):
        complete = switch('1.001000', 11, 12)
        self.report.write_text(complete[:-8])
        feed = LiveFeed(self.path);feed.update()
        self.assertEqual(feed.snapshot()['scheduler'], [])
        with self.report.open('a') as out:
            out.write(complete[-8:])
        feed.update()
        self.assertEqual(len(feed.snapshot()['scheduler']), 1)

    def test_explicit_app_end_overrides_recent_file_mtime(self):
        self.report.write_text(switch('1.001000', 11, 12))
        self.path.with_name('live-test.session.json').write_text(json.dumps(
            {'phase':'draining','app_end_s':1.01}))
        feed = LiveFeed(self.path);feed.update()
        self.assertFalse(feed.snapshot()['active'])
        self.assertEqual(feed.snapshot()['app_end_s'], 1.01)
