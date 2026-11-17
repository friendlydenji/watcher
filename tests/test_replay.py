import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class ReplayTests(unittest.TestCase):
    def test_report_and_dat_both_embed_scheduler_and_sdk_events(self):
        for kind in ('txt', 'dat'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                prefix = root / 'capture-test'
                report = ('worker-11 [003] 1.001000: sched_switch: '
                          'worker:11 [120] R ==> worker:12 [120]\n'
                          'worker-12 [003] 1.003000: sched_switch: '
                          'worker:12 [120] S ==> worker:11 [120]\n')
                source = prefix.with_suffix('.'+kind)
                env = os.environ.copy()
                if kind == 'dat':
                    source.write_bytes(b'placeholder-dat')
                    # Exercise the actual .dat subprocess-report path without root.
                    command = root / 'trace-cmd'
                    command.write_text('#!/usr/bin/env python3\nprint('+repr(report)+')\n')
                    command.chmod(0o755)
                    env['PATH'] = str(root)+os.pathsep+env['PATH']
                else:
                    source.write_text(report)
                prefix.with_suffix('.events.log').write_text(
                    'LTI_EVENT mono_ns=1000000000 tid=11 pid=10 job=7 phase=send v=1 resource=0\n'
                    'LTI_EVENT mono_ns=1001000000 tid=12 pid=10 job=7 phase=receive v=1 resource=0\n'
                    'LTI_EVENT mono_ns=1003000000 tid=12 pid=10 job=7 phase=done v=1 resource=0\n')
                rows = {
                    'flow': [{'pid':10,'job_id':7,'send_tid':11,'receive_tid':12,
                              'send_s':'1.000','receive_s':'1.001','done_s':'1.003'}],
                    'timeline': [{'tid':12,'comm':'worker','state':'running','cpu':3,
                                  'start_s':'1.001','end_s':'1.003'}],
                    'sync': [{'pid':10,'tid':12,'job_id':7,'resource_id':1,
                              'kind':'mutex_wait','start_s':'1.001','end_s':'1.002'}]}
                for suffix, values in rows.items():
                    with prefix.with_suffix('.'+suffix+'.csv').open('w') as output:
                        writer=csv.DictWriter(output,fieldnames=values[0].keys())
                        writer.writeheader(); writer.writerows(values)
                result=subprocess.run([sys.executable,str(ROOT/'scripts/correlate.py'),str(prefix)],
                                      env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                data=json.loads(prefix.with_suffix('.jobs.json').read_text())
                self.assertEqual(len(data['scheduler']),2)
                self.assertEqual(len(data['events']),3)
                self.assertEqual(data['jobs'][0]['status'],'complete')
