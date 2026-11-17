import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from import_qnx import intervals,add_tracks
from correlate import correlate

class QNXTests(unittest.TestCase):
    def test_pid_tid_identity_and_clock_epoch_mapping(self):
        clock={'cycles':1000,'mono_ns':9000000000,'cycles_per_sec':1000000,'bracket_cycles':2}
        lines=['cycles:0x00000000000003e8 cpu:0 THREAD:THRUNNING pid:10 tid:1',
               'cycles:0x000000000000044c cpu:1 THREAD:THRUNNING pid:20 tid:1',
               'cycles:0x00000000000004b0 cpu:0 THREAD:THMUTEX pid:10 tid:1',
               'cycles:0x0000000000000514 cpu:1 THREAD:THREADY pid:20 tid:1',
               'cycles:0x0000000000000578 cpu:0 THREAD:THREADY pid:10 tid:1']
        rows=intervals(lines,clock,{(10,1),(20,1)})
        self.assertEqual(rows[0]['start_s'],'9.000000000')
        self.assertEqual([(r['pid'],r['tid'],r['state']) for r in rows],[(10,1,'running'),(20,1,'running'),(10,1,'sleeping')])
        flows=[{'pid':10,'job_id':1,'send_tid':1,'receive_tid':1,'send_s':'9.000','receive_s':'9.000','done_s':'9.0004'}]
        job=correlate(flows,rows,[])[0]
        self.assertEqual(job['worker_running_ms'],0.2)
        self.assertEqual(job['worker_sleeping_ms'],0.2)
        self.assertEqual(job['status'],'complete')
        self.assertIsNone(job['mutex_wait_observed_ms'])
        data={'jobs':[],'timeline':rows,'events':[],'sync':[]};add_tracks(data)
        self.assertNotEqual(rows[0]['track_id'],rows[1]['track_id'])
        self.assertEqual(rows[0]['tid'],rows[1]['tid'])
