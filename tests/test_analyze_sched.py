import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_sched import analyze, parse_event

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'analyze_sched.py'


SAMPLE = """\
mixed_demo-189735 [001] d..2 123.000000: sched_wakeup: mixed_demo:189736 [120]
mixed_demo-189735 [001] d..2 123.000005: sched_waking: mixed_demo:189736 [120]
mixed_demo-189735 [001] d..2 123.000010: sched_switch: mixed_demo:189735 [120] S ==> mixed_demo:189736 [120]
mixed_demo-189736 [001] d..2 123.000020: sched_switch: mixed_demo:189736 [120] R+ ==> other:42 [120]
other-42 [001] d..2 123.000030: sched_switch: other:42 [120] S ==> mixed_demo:189736 [120]
mixed_demo-189736 [001] d..2 123.000040: sched_switch: mixed_demo:189736 [120] S ==> swapper:0 [120]
mixed_demo-189735 [002] d..2 123.000050: sched_wakeup: mixed_demo:189736 [120]
other-42 [002] d..2 123.000060: sched_switch: other:42 [120] R ==> mixed_demo:189736 [120]
"""


class SchedulerAnalyzerTests(unittest.TestCase):
    def test_trace_cmd_296_style_and_timeline(self):
        intervals, latencies, counts = analyze(SAMPLE.splitlines(), [189736])
        self.assertEqual([row[2] for row in intervals],
                         ['runnable', 'running', 'runnable', 'running',
                          'sleeping', 'runnable'])
        self.assertEqual([row[3] - row[2] for row in latencies],
                         [10_000, 10_000])
        self.assertEqual(counts['sched_waking'], 1)
        self.assertEqual(counts['unparsed_scheduler_lines'], 0)

    def test_key_value_report_style(self):
        line = ('app-10 [003] .... 9.123456: sched_switch: '
                'prev_comm=app prev_pid=10 prev_prio=120 prev_state=S ==> '
                'next_comm=worker next_pid=11 next_prio=120')
        self.assertEqual(parse_event(line),
                         (9_123_456_000, 3, 'sched_switch',
                          ((10, 'app'), (11, 'worker'), 'S')))

    def test_cli_writes_csv_and_rejects_unrecognized_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / 'report.txt'
            report.write_text(SAMPLE, encoding='utf-8')
            process = subprocess.run(
                [sys.executable, str(SCRIPT), str(report), '--comm', 'mixed_demo'],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            with (root / 'report.latency.csv').open(newline='') as source:
                rows = list(csv.DictReader(source))
            self.assertEqual([row['latency_ms'] for row in rows],
                             ['0.010000', '0.010000'])
            with (root / 'report.summary.csv').open(newline='') as source:
                summary = list(csv.DictReader(source))
            self.assertEqual(len(summary), 1)
            self.assertEqual(summary[0]['tid'], '189736')
            self.assertEqual(summary[0]['running_ms'], '0.020000')
            self.assertEqual(summary[0]['sleeping_ms'], '0.010000')
            report.write_text('not a trace\n', encoding='utf-8')
            process = subprocess.run(
                [sys.executable, str(SCRIPT), str(report)],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(process.returncode, 0)


if __name__ == '__main__':
    unittest.main()
