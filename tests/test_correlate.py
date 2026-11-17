import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from correlate import correlate
from analyze_flow import parse_marker


class CorrelationTests(unittest.TestCase):
    def test_scheduler_states_partition_worker_processing(self):
        flow = [{
            'pid': '100', 'job_id': '1', 'send_tid': '10', 'receive_tid': '11',
            'send_s': '1.000000000', 'receive_s': '1.001000000',
            'done_s': '1.011000000', 'compute_begin_s': '1.001000000',
            'compute_end_s': '1.006000000', 'sleep_ms': '5.0',
        }]
        timeline = [
            {'tid': '11', 'state': 'running', 'start_s': '1.001000000', 'end_s': '1.004000000'},
            {'tid': '11', 'state': 'runnable', 'start_s': '1.004000000', 'end_s': '1.006000000'},
            {'tid': '11', 'state': 'sleeping', 'start_s': '1.006000000', 'end_s': '1.011000000'},
        ]
        sync = [{
            'pid': '100', 'job_id': '1', 'kind': 'mutex_wait',
            'start_s': '1.002000000', 'end_s': '1.002500000',
        }]
        job = correlate(flow, timeline, sync)[0]
        self.assertEqual(job['status'], 'complete')
        self.assertEqual((job['queue_ms'], job['processing_ms']), (1.0, 10.0))
        self.assertEqual((job['worker_running_ms'], job['worker_runnable_ms'],
                          job['worker_sleeping_ms'], job['worker_unknown_ms']),
                         (3.0, 2.0, 5.0, 0.0))
        self.assertEqual((job['compute_running_ms'], job['compute_runnable_ms']),
                         (3.0, 2.0))
        self.assertEqual(job['mutex_wait_observed_ms'], 0.5)

    def test_missing_scheduler_interval_is_reported(self):
        flow = [{
            'pid': '100', 'job_id': '1', 'send_tid': '10', 'receive_tid': '11',
            'send_s': '1.000000000', 'receive_s': '1.001000000',
            'done_s': '1.011000000', 'compute_begin_s': '',
            'compute_end_s': '', 'sleep_ms': '',
        }]
        job = correlate(flow, [], [])[0]
        self.assertEqual(job['status'], 'partial_scheduler')
        self.assertEqual(job['worker_unknown_ms'], 10.0)

    def test_file_backend_marker_parses(self):
        marker = parse_marker(
            'LTI_EVENT mono_ns=1234567890 tid=12 pid=100 job=7 '
            'phase=send v=1 resource=0\n'
        )
        self.assertEqual(marker, (1234567890, 12, -1, 7, 'send', 0, 100))


if __name__ == '__main__':
    unittest.main()
