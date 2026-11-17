import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from export_perfetto import export_trace

class PerfettoTests(unittest.TestCase):
    def test_microseconds_flows_and_separate_overlapping_tracks(self):
        data = {'trace': 'test', 'jobs': [
            {'pid': pid, 'job_id': 7, 'send_tid': pid+1, 'worker_tid': pid+2,
             'send_s': '1.000001', 'receive_s': '1.002001', 'done_s': '1.004001'}
            for pid in (100, 200)],
            'timeline': [{'tid': 102, 'comm': 'worker', 'state': 'running',
                          'start_s': '1.002001', 'end_s': '1.004001', 'cpu': 3}],
            'sync': [{'pid': 100, 'tid': 102, 'job_id': 7, 'resource_id': 5,
                      'kind': 'mutex_wait', 'start_s': '1.001001', 'end_s': '1.003001'}]}
        trace = export_trace(data)['traceEvents']
        slices = [e for e in trace if e['ph'] == 'X']
        self.assertEqual(slices[0]['ts'], 1002001)
        self.assertEqual(slices[0]['dur'], 2000)
        self.assertNotEqual(slices[0]['tid'], slices[1]['tid'])
        starts = [e for e in trace if e['ph'] == 's']
        ends = [e for e in trace if e['ph'] == 'f']
        self.assertEqual(len(starts), 2)
        self.assertNotEqual(starts[0]['id'], starts[1]['id'])
        self.assertEqual([e['id'] for e in starts], [e['id'] for e in ends])
