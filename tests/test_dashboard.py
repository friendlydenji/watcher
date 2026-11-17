import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dashboard import scheduler_event


class LiveDashboardTests(unittest.TestCase):
    def test_switch_exposes_both_threads_and_cpu(self):
        line = ('worker-11 [003] d..2. 12.000001: sched_switch: '
                'prev_comm=worker prev_pid=11 prev_prio=120 prev_state=S ==> '
                'next_comm=app next_pid=12 next_prio=120')
        event = scheduler_event(line)
        self.assertEqual((event['cpu'], event['prev_tid'], event['next_tid']),
                         (3, 11, 12))
        self.assertEqual(event['prev_state'], 'S')

    def test_wakeup_exposes_source_and_target_cpu(self):
        line = ('app-12 [003] d..2. 12.000002: sched_wakeup: '
                'comm=worker pid=11 prio=120 target_cpu=006')
        event = scheduler_event(line)
        self.assertEqual((event['waker_tid'], event['cpu'], event['tid'],
                          event['target_cpu']), (12, 3, 11, 6))
