#!/usr/bin/env python3
"""Export observed mutex and condition-wait intervals from demo trace markers."""

import argparse
import csv
from pathlib import Path

from analyze_flow import marker_lines, parse_marker
from analyze_sched import seconds


def analyze_sync(lines):
    pending = {}  # (pid, tid, resource_id, interval kind) -> (start_ns, job_id)
    rows = []
    markers = 0
    starts = {'lock_wait': 'mutex_wait', 'cond_wait_begin': 'cond_wait'}
    for line in lines:
        marker = parse_marker(line)
        if not marker:
            continue
        time_ns, tid, _cpu, job_id, phase, resource_id, pid = marker
        if phase not in ('lock_wait', 'lock_acquired', 'lock_release',
                         'cond_wait_begin', 'cond_wait_end'):
            continue
        markers += 1
        if phase in starts:
            pending[(pid, tid, resource_id, starts[phase])] = (time_ns, job_id)
        elif phase == 'lock_acquired':
            start = pending.pop((pid, tid, resource_id, 'mutex_wait'), None)
            if start and time_ns >= start[0]:
                rows.append((tid, start[1], resource_id, 'mutex_wait', start[0], time_ns, pid))
            pending[(pid, tid, resource_id, 'mutex_hold')] = (time_ns, job_id)
        elif phase == 'lock_release':
            start = pending.pop((pid, tid, resource_id, 'mutex_hold'), None)
            if start and time_ns >= start[0]:
                rows.append((tid, job_id or start[1], resource_id,
                             'mutex_hold', start[0], time_ns, pid))
        elif phase == 'cond_wait_end':
            start = pending.pop((pid, tid, resource_id, 'cond_wait'), None)
            if start and time_ns >= start[0]:
                rows.append((tid, start[1], resource_id, 'cond_wait', start[0], time_ns, pid))
    rows.sort(key=lambda row: (row[4], row[0], row[3]))
    return rows, markers, len(pending)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='trace-cmd .dat or report .txt')
    parser.add_argument('-o', '--output', type=Path,
                        help='CSV path (default: input name.sync.csv)')
    parser.add_argument('--events', type=Path, help='SDK event log (auto-detected when present)')
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f'input file does not exist: {args.input}')
    try:
        rows, markers, open_intervals = analyze_sync(marker_lines(args.input, args.events))
    except RuntimeError as exc:
        parser.exit(1, f'error: {exc}\n')
    output = args.output or Path(f'{args.input.with_suffix("")}.sync.csv')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='', encoding='utf-8') as destination:
        writer = csv.writer(destination)
        writer.writerow(['tid', 'job_id', 'resource_id', 'kind', 'start_s', 'end_s', 'duration_ms', 'pid'])
        for tid, job_id, resource_id, kind, start, end, pid in rows:
            writer.writerow((tid, job_id, resource_id, kind, seconds(start), seconds(end),
                             f'{(end - start) / 1_000_000:.6f}', pid))
    print(f'{output}: {len(rows)} intervals; {open_intervals} open')


if __name__ == '__main__':
    main()
