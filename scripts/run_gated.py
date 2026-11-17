#!/usr/bin/env python3
"""Wait for the private tracer, then exec the app without changing its PID."""
import os
import sys

if len(sys.argv) < 3:
    raise SystemExit('usage: run_gated.py <fifo> <program> [arguments...]')
with open(sys.argv[1], 'rb', buffering=0) as gate:
    if gate.read(1) != b'1':
        raise SystemExit('capture gate closed before tracing was ready')
os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
