#!/usr/bin/env python3
"""Correlate demo send/receive/done markers into per-job flow CSV."""

import argparse
import csv
import re
from pathlib import Path

from analyze_sched import input_lines, seconds, timestamp_ns


MARKER = re.compile(
    r"^\s*.*?-(?P<tid>\d+)\s+\[(?P<cpu>\d+)\].*?\s+"
    r"(?P<time>\d+(?:\.\d+)?):.*?\bLTI job=(?P<job>\d+) "
    r"phase=(?P<phase>[a-z_]+)\b"
)
FILE_MARKER = re.compile(
    r"^LTI_EVENT mono_ns=(?P<time>\d+) tid=(?P<tid>\d+) "
    r"pid=(?P<pid>\d+) job=(?P<job>\d+) "
    r"phase=(?P<phase>[a-z_]+) v=(?P<version>\d+) "
    r"resource=(?P<resource>\d+)\s*$"
)
RESOURCE = re.compile(r"\bresource=(\d+)\b")
VERSION = re.compile(r"\bv=(\d+)\b")
PID = re.compile(r"\bpid=(\d+)\b")

FLOW_PHASES = {
    'send', 'receive', 'done', 'compute_begin', 'compute_end',
    'sleep_begin', 'sleep_end',
}


def parse_marker(line):
    file_match = FILE_MARKER.match(line)
    if file_match:
        if int(file_match['version']) != 1:
            return None
        return (int(file_match['time']), int(file_match['tid']), -1,
                int(file_match['job']), file_match['phase'],
                int(file_match['resource']), int(file_match['pid']))
    match = MARKER.match(line)
    if not match:
        return None
    rest = line[match.end():]
    version = VERSION.search(rest)
    if version and int(version[1]) != 1:
        return None
    resource = RESOURCE.search(rest)
    pid = PID.search(rest)
    return (timestamp_ns(match['time']), int(match['tid']), int(match['cpu']),
            int(match['job']), match['phase'], int(resource[1]) if resource else 0,
            int(pid[1]) if pid else 0)


def marker_lines(path, events=None):
    event_path = events or Path(f'{path.with_suffix("")}.events.log')
    if event_path.is_file():
        with event_path.open(encoding='utf-8', errors='replace') as source:
            yield from source
    else:
        if events is not None:
            raise RuntimeError(f'event log does not exist: {events}')
        yield from input_lines(path)


def analyze_flow(lines):
    jobs = {}
    markers = 0
    for line in lines:
        marker = parse_marker(line)
        if not marker:
            continue
        time_ns, tid, cpu, job_id, phase, _resource_id, pid = marker
        if job_id == 0 or phase not in FLOW_PHASES:
            continue
        markers += 1
        jobs.setdefault((pid, job_id), {})[phase] = (time_ns, tid, cpu)
    rows = []
    incomplete = 0
    for (pid, job_id), phases in sorted(jobs.items()):
        if not all(phase in phases for phase in ('send', 'receive', 'done')):
            incomplete += 1
            continue
        send, receive, done = (phases[phase] for phase in ('send', 'receive', 'done'))
        if not send[0] <= receive[0] <= done[0]:
            incomplete += 1
            continue
        compute_begin = phases.get('compute_begin')
        compute_end = phases.get('compute_end')
        sleep_begin = phases.get('sleep_begin')
        sleep_end = phases.get('sleep_end')
        compute_ns = (compute_end[0] - compute_begin[0]
                      if compute_begin and compute_end and
                      receive[0] <= compute_begin[0] <= compute_end[0] <= done[0]
                      else None)
        sleep_ns = (sleep_end[0] - sleep_begin[0]
                    if sleep_begin and sleep_end and
                    receive[0] <= sleep_begin[0] <= sleep_end[0] <= done[0]
                    else None)
        other_ns = (done[0] - receive[0] - compute_ns - sleep_ns
                    if compute_ns is not None and sleep_ns is not None else None)
        rows.append((
            job_id, send[1], receive[1], done[1],
            seconds(send[0]), seconds(receive[0]), seconds(done[0]),
            f'{(receive[0] - send[0]) / 1_000_000:.6f}',
            f'{(done[0] - receive[0]) / 1_000_000:.6f}',
            f'{(done[0] - send[0]) / 1_000_000:.6f}',
            f'{compute_ns / 1_000_000:.6f}' if compute_ns is not None else '',
            f'{sleep_ns / 1_000_000:.6f}' if sleep_ns is not None else '',
            f'{other_ns / 1_000_000:.6f}' if other_ns is not None else '',
            pid,
            seconds(compute_begin[0]) if compute_ns is not None else '',
            seconds(compute_end[0]) if compute_ns is not None else '',
            seconds(sleep_begin[0]) if sleep_ns is not None else '',
            seconds(sleep_end[0]) if sleep_ns is not None else '',
        ))
    return rows, markers, incomplete


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='trace-cmd .dat or report .txt')
    parser.add_argument('-o', '--output', type=Path,
                        help='CSV path (default: input name.flow.csv)')
    parser.add_argument('--events', type=Path, help='SDK event log (auto-detected when present)')
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f'input file does not exist: {args.input}')
    try:
        rows, markers, incomplete = analyze_flow(marker_lines(args.input, args.events))
    except RuntimeError as exc:
        parser.exit(1, f'error: {exc}\n')
    if not markers:
        parser.exit(1, 'error: no LTI events found; check SDK event capture\n')
    output = args.output or Path(f'{args.input.with_suffix("")}.flow.csv')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='', encoding='utf-8') as destination:
        writer = csv.writer(destination)
        writer.writerow([
            'job_id', 'send_tid', 'receive_tid', 'done_tid',
            'send_s', 'receive_s', 'done_s', 'queue_ms', 'processing_ms', 'total_ms',
            'compute_ms', 'sleep_ms', 'other_processing_ms',
            'pid',
            'compute_begin_s', 'compute_end_s', 'sleep_begin_s', 'sleep_end_s',
        ])
        writer.writerows(rows)
    print(f'{output}: {len(rows)} complete job flows; {incomplete} incomplete')


if __name__ == '__main__':
    main()
