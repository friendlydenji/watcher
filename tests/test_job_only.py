import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class JobOnlyTests(unittest.TestCase):
    def test_no_sync_markers_exports_header_and_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix=Path(directory)/'job-only';report=prefix.with_suffix('.txt');report.write_text('')
            prefix.with_suffix('.events.log').write_text(
                'LTI_EVENT mono_ns=1000000000 tid=1 pid=10 job=7 phase=send v=1 resource=0\n'
                'LTI_EVENT mono_ns=1001000000 tid=2 pid=10 job=7 phase=receive v=1 resource=0\n'
                'LTI_EVENT mono_ns=1002000000 tid=2 pid=10 job=7 phase=done v=1 resource=0\n')
            prefix.with_suffix('.timeline.csv').write_text('pid,tid,state,start_s,end_s,cpu\n10,2,running,1.001,1.002,0\n')
            for script in ('analyze_flow.py','analyze_sync.py','correlate.py'):
                argument=str(prefix) if script=='correlate.py' else str(report)
                process=subprocess.run([sys.executable,str(ROOT/'scripts'/script),argument],capture_output=True,text=True)
                self.assertEqual(process.returncode,0,process.stderr)
            with prefix.with_suffix('.sync.csv').open() as source:self.assertEqual(list(csv.DictReader(source)),[])
            data=json.loads(prefix.with_suffix('.jobs.json').read_text())
            self.assertEqual(len(data['jobs']),1)
            self.assertIsNone(data['jobs'][0]['mutex_wait_observed_ms'])
            self.assertIsNone(data['jobs'][0]['cond_wait_observed_ms'])
            prefix.with_suffix('.sync.csv').unlink()
            process=subprocess.run([sys.executable,str(ROOT/'scripts/correlate.py'),str(prefix)],capture_output=True,text=True)
            self.assertEqual(process.returncode,0,process.stderr)
