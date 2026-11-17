#!/usr/bin/env python3
"""Drain one private trace_pipe with a deadline, without a blocking cat process."""
import os
import select
import sys
import time


def stream(path, seconds, output):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    deadline = time.monotonic() + float(seconds)
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], min(0.1, max(0, deadline - time.monotonic())))
            if not ready:
                continue
            try:
                block = os.read(fd, 1024 * 1024)
            except BlockingIOError:
                continue
            if not block:
                break
            output.write(block)
            output.flush()
    finally:
        os.close(fd)


if __name__ == '__main__':
    stream(sys.argv[1], sys.argv[2], sys.stdout.buffer)
