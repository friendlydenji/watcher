#!/usr/bin/env python3
"""Atomically publish live capture state for the local dashboard."""
import json
import os
import sys
import time
from pathlib import Path


def write_state(path, phase, pid):
    path = Path(path)
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {'started_s': time.monotonic(), 'pid': int(pid), 'filtered': True}
    state.update(phase=phase, updated_s=time.monotonic())
    if phase in ('draining', 'complete', 'failed'):
        state.setdefault('app_end_s', time.monotonic())
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(state), encoding='utf-8')
    temporary.replace(path)


if __name__ == '__main__':
    write_state(*sys.argv[1:])
