"""Check private tracing lifecycle with fake privileged commands, never tracefs."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

@unittest.skipIf(os.geteuid() == 0, 'mock sudo path exercises non-root capture')
class LiveScriptTests(unittest.TestCase):
    def test_private_instance_cleanup_on_success_and_start_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); scripts=root/'scripts'; scripts.mkdir()
                for source in (ROOT/'scripts').glob('*.py'):
                    (scripts/source.name).symlink_to(source)
                shutil.copyfile(ROOT/'scripts/live-app.sh', scripts/'live-app.sh')
                binary=root/'bin';binary.mkdir()
                sudo=binary/'sudo'
                sudo.write_text('''#!/usr/bin/env bash
case "$1" in
 test) [[ "$2" = -d ]];;
 python3)
   if [[ "$2" = scripts/read_trace.py ]]; then /bin/cat "$MOCK_REPORT"; /bin/sleep 0.5; else exec "$@"; fi;;
 *) exec "$@";;
esac
''');sudo.chmod(0o755)
                command=binary/'trace-cmd'
                command.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$MOCK_COMMANDS"
if [[ "$1" = start && "$MOCK_FAIL_START" = 1 ]]; then exit 1; fi
''');command.chmod(0o755)
                app=root/'program-with-a-long-name'
                app.write_text('''#!/usr/bin/env bash
cat > "$LTI_EVENT_FILE" <<'LOG'
LTI_EVENT mono_ns=1000000000 tid=11 pid=10 job=7 phase=send v=1 resource=0
LTI_EVENT mono_ns=1001000000 tid=12 pid=10 job=7 phase=receive v=1 resource=0
LTI_EVENT mono_ns=1001100000 tid=12 pid=10 job=7 phase=lock_wait v=1 resource=1
LTI_EVENT mono_ns=1001200000 tid=12 pid=10 job=7 phase=lock_acquired v=1 resource=1
LTI_EVENT mono_ns=1001300000 tid=12 pid=10 job=7 phase=lock_release v=1 resource=1
LTI_EVENT mono_ns=1003000000 tid=12 pid=10 job=7 phase=done v=1 resource=0
LOG
''');app.chmod(0o755)
                report=root/'scheduler.txt'
                report.write_text('worker-11 [003] 1.001000: sched_switch: '
                                  'worker:11 [120] S ==> renamed:12 [120]\n'
                                  'renamed-12 [003] 1.003000: sched_switch: '
                                  'renamed:12 [120] S ==> worker:11 [120]\n')
                commands=root/'commands.log'
                env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],
                     'MOCK_REPORT':str(report),'MOCK_COMMANDS':str(commands),
                     'MOCK_FAIL_START':'1' if fail else '0'}
                result=subprocess.run(['bash',str(scripts/'live-app.sh'),'1',str(app)],
                                      env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,1 if fail else 0,result.stderr)
                lines=commands.read_text().splitlines()
                self.assertEqual(len(lines),3,lines)
                self.assertIn('start -B watcher-',lines[0])
                instance=lines[0].split()[2]
                self.assertEqual(lines[1],f'stop -B {instance}')
                self.assertEqual(lines[2],f'reset -B {instance} -d')
                self.assertNotIn('--comm',lines[0])
                self.assertIn('-P ',lines[0])
                self.assertIn(' -c ',lines[0])
                if not fail:
                    self.assertEqual(len(list((root/'traces').glob('*.jobs.json'))),1)
