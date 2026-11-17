import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_flow import analyze_flow
from analyze_sync import analyze_sync


class FlowAnalyzerTests(unittest.TestCase):
    def test_correlates_two_threads_by_job_id(self):
        report = [
            'mixed_demo-36326 [001] 5670.100000: tracing_mark_write: LTI job=1 phase=send',
            'mixed_demo-36326 [001] 5670.100100: tracing_mark_write: LTI job=2 phase=send',
            'mixed_demo-36327 [007] 5670.100200: tracing_mark_write: LTI job=1 phase=receive',
            'mixed_demo-36327 [007] 5670.120200: tracing_mark_write: LTI job=1 phase=done',
            'mixed_demo-36327 [007] 5670.120300: tracing_mark_write: LTI job=2 phase=receive',
            'mixed_demo-36327 [007] 5670.140300: tracing_mark_write: LTI job=2 phase=done',
        ]
        rows, markers, incomplete = analyze_flow(report)
        self.assertEqual(markers, 6)
        self.assertEqual(incomplete, 0)
        self.assertEqual([row[0] for row in rows], [1, 2])
        self.assertEqual(rows[0][1:4], (36326, 36327, 36327))
        self.assertEqual(rows[0][7:10], ('0.200000', '20.000000', '20.200000'))
        self.assertEqual(rows[0][10:13], ('', '', ''))

    def test_compute_sleep_and_synchronization_intervals(self):
        report = [
            'mixed_demo-10 [001] 1.000000: tracing_mark_write: LTI job=7 phase=lock_wait',
            'mixed_demo-10 [001] 1.000010: tracing_mark_write: LTI job=7 phase=lock_acquired',
            'mixed_demo-10 [001] 1.000020: tracing_mark_write: LTI job=7 phase=send',
            'mixed_demo-10 [001] 1.000030: tracing_mark_write: LTI job=7 phase=lock_release',
            'mixed_demo-11 [002] 1.000100: tracing_mark_write: LTI job=7 phase=receive',
            'mixed_demo-11 [002] 1.000110: tracing_mark_write: LTI job=7 phase=compute_begin',
            'mixed_demo-11 [002] 1.003110: tracing_mark_write: LTI job=7 phase=compute_end',
            'mixed_demo-11 [002] 1.003120: tracing_mark_write: LTI job=7 phase=sleep_begin',
            'mixed_demo-11 [002] 1.023120: tracing_mark_write: LTI job=7 phase=sleep_end',
            'mixed_demo-11 [002] 1.023130: tracing_mark_write: LTI job=7 phase=done',
            'mixed_demo-11 [002] 1.023140: tracing_mark_write: LTI job=0 phase=cond_wait_begin',
            'mixed_demo-11 [002] 1.123140: tracing_mark_write: LTI job=0 phase=cond_wait_end',
        ]
        flows, _, incomplete = analyze_flow(report)
        self.assertEqual(incomplete, 0)
        self.assertEqual(flows[0][10:13], ('3.000000', '20.000000', '0.030000'))
        intervals, _, open_intervals = analyze_sync(report)
        self.assertEqual([row[3] for row in intervals],
                         ['mutex_wait', 'mutex_hold', 'cond_wait'])
        self.assertEqual([row[5] - row[4] for row in intervals],
                         [10_000, 20_000, 100_000_000])
        self.assertEqual(open_intervals, 0)

    def test_incomplete_job_is_excluded(self):
        rows, markers, incomplete = analyze_flow([
            'mixed_demo-1 [000] 1.000000: print: LTI job=3 phase=send',
        ])
        self.assertEqual((rows, markers, incomplete), ([], 1, 1))

    def test_worker_lock_hold_gets_job_id_when_dequeued(self):
        intervals, markers, open_intervals = analyze_sync([
            'mixed_demo-11 [002] 1.000000: print: LTI job=0 phase=lock_wait',
            'mixed_demo-11 [002] 1.000010: print: LTI job=0 phase=lock_acquired',
            'mixed_demo-11 [002] 1.000020: print: LTI job=7 phase=lock_release',
        ])
        self.assertEqual(markers, 3)
        self.assertEqual(open_intervals, 0)
        self.assertEqual([(row[1], row[3]) for row in intervals],
                         [(0, 'mutex_wait'), (7, 'mutex_hold')])

    def test_resource_ids_keep_two_mutexes_separate(self):
        report = [
            'app-11 [002] 1.000000: print: LTI job=4 phase=lock_wait v=1 resource=10',
            'app-11 [002] 1.000010: print: LTI job=4 phase=lock_acquired v=1 resource=10',
            'app-11 [002] 1.000020: print: LTI job=4 phase=lock_wait v=1 resource=20',
            'app-11 [002] 1.000030: print: LTI job=4 phase=lock_acquired v=1 resource=20',
            'app-11 [002] 1.000040: print: LTI job=4 phase=lock_release v=1 resource=20',
            'app-11 [002] 1.000050: print: LTI job=4 phase=lock_release v=1 resource=10',
        ]
        rows, _, open_intervals = analyze_sync(report)
        self.assertEqual(open_intervals, 0)
        self.assertEqual([(r[2], r[3]) for r in rows],
                         [(10, 'mutex_wait'), (10, 'mutex_hold'),
                          (20, 'mutex_wait'), (20, 'mutex_hold')])

    def test_same_job_id_in_two_processes_stays_separate(self):
        report = [
            'app-11 [000] 1.000000: print: LTI job=1 phase=send v=1 pid=100 resource=0',
            'app-21 [001] 1.000010: print: LTI job=1 phase=send v=1 pid=200 resource=0',
            'app-12 [000] 1.000020: print: LTI job=1 phase=receive v=1 pid=100 resource=0',
            'app-22 [001] 1.000030: print: LTI job=1 phase=receive v=1 pid=200 resource=0',
            'app-12 [000] 1.000040: print: LTI job=1 phase=done v=1 pid=100 resource=0',
            'app-22 [001] 1.000050: print: LTI job=1 phase=done v=1 pid=200 resource=0',
        ]
        rows, _, incomplete = analyze_flow(report)
        self.assertEqual(incomplete, 0)
        self.assertEqual([(row[0], row[13]) for row in rows], [(1, 100), (1, 200)])


if __name__ == '__main__':
    unittest.main()
