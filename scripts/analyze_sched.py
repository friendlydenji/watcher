#!/usr/bin/env python3
"""Turn trace-cmd scheduler events into per-thread timeline and latency CSVs."""

import argparse
import csv
import re
import subprocess
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


EVENT = re.compile(
    r"^\s*(?P<context>.*?)\s+(?P<time>\d+(?:\.\d+)?):\s+"
    r"(?P<event>sched_(?:switch|wakeup|waking|wakeup_new)):\s*(?P<body>.*)$"
)
CPU = re.compile(r"\[(\d+)\]")
TASK = re.compile(r"(?P<comm>.+):(?P<tid>\d+)\s+\[\s*\d+\s*\]")
SWITCH = re.compile(
    r"^\s*(?P<prev>.+?:\d+\s+\[\s*\d+\s*\])\s+"
    r"(?P<state>\S+)\s+==>\s+"
    r"(?P<next>.+?:\d+\s+\[\s*\d+\s*\])"
)
FIELD = re.compile(r"\b([a-z_]+)=([^\s]+)")


def timestamp_ns(value):
    try:
        return int(Decimal(value) * 1_000_000_000)
    except InvalidOperation as exc:
        raise ValueError(f"bad timestamp: {value}") from exc


def seconds(ns):
    return f"{ns // 1_000_000_000}.{ns % 1_000_000_000:09d}"


def parse_task(value):
    match = TASK.fullmatch(value.strip())
    if not match:
        return None
    return int(match['tid']), match['comm']


def parse_event(line):
    match = EVENT.match(line)
    if not match:
        return None
    cpu = CPU.search(match['context'])
    if not cpu:
        return None
    event = match['event']
    body = match['body']
    fields = dict(FIELD.findall(body))
    if event == 'sched_switch':
        switch = SWITCH.match(body)
        if switch:
            prev = parse_task(switch['prev'])
            next_task = parse_task(switch['next'])
            state = switch['state']
        else:
            try:
                prev = int(fields['prev_pid']), fields.get('prev_comm', '')
                next_task = int(fields['next_pid']), fields.get('next_comm', '')
                state = fields['prev_state']
            except (KeyError, ValueError):
                return None
        if not prev or not next_task:
            return None
        data = (prev, next_task, state)
    else:
        task_match = TASK.match(body.strip())
        if task_match:
            data = (int(task_match['tid']), task_match['comm'])
        else:
            try:
                data = (int(fields['pid']), fields.get('comm', ''))
            except (KeyError, ValueError):
                return None
    return timestamp_ns(match['time']), int(cpu[1]), event, data


def classify_switch_state(value):
    # R and R+ mean preempted/runnable. S and D are sleeping states.
    if value.startswith('R'):
        return 'runnable'
    if value.startswith(('S', 'D')):
        return 'sleeping'
    return 'other'


def analyze(lines, selected_tids=None, selected_comms=None):
    """Return closed state intervals, wakeup latencies, and diagnostics."""
    selected_tids = set(selected_tids or [])
    selected_comms = set(selected_comms or [])
    current = {}  # tid -> (state, start_ns, cpu, runnable_origin)
    names = {}
    intervals = []
    latencies = []
    counts = Counter()
    last_time = None

    def selected(tid):
        return (not selected_tids and not selected_comms or
                tid in selected_tids or names.get(tid) in selected_comms)

    def close(tid, end_ns):
        prior = current.pop(tid, None)
        if prior is None:
            return None
        state, start_ns, cpu, _origin = prior
        if end_ns < start_ns:
            counts['out_of_order'] += 1
            return None
        if selected(tid):
            intervals.append((tid, names.get(tid, ''), state, start_ns, end_ns, cpu))
        return prior

    for line in lines:
        parsed = parse_event(line)
        if parsed is None:
            if 'sched_switch:' in line or 'sched_wakeup:' in line or 'sched_waking:' in line:
                counts['unparsed_scheduler_lines'] += 1
            continue
        time_ns, cpu, event, data = parsed
        counts[event] += 1
        if last_time is not None and time_ns < last_time:
            counts['out_of_order'] += 1
        last_time = time_ns
        if event == 'sched_waking':
            # sched_waking precedes the actual runnable transition; do not use it
            # to calculate wakeup latency when sched_wakeup is also captured.
            continue
        if event in ('sched_wakeup', 'sched_wakeup_new'):
            tid, comm = data
            names[tid] = comm or names.get(tid, '')
            prior = current.get(tid)
            if prior and prior[0] == 'running':
                counts['wakeup_while_running'] += 1
            elif not prior or prior[0] != 'runnable':
                close(tid, time_ns)
                current[tid] = ('runnable', time_ns, None, 'wakeup')
            else:
                counts['duplicate_wakeups'] += 1
            continue

        (prev_tid, prev_comm), (next_tid, next_comm), prev_state = data
        names[prev_tid] = prev_comm or names.get(prev_tid, '')
        names[next_tid] = next_comm or names.get(next_tid, '')
        prior_next = close(next_tid, time_ns)
        if prior_next and prior_next[0] == 'runnable' and prior_next[3] == 'wakeup':
            if selected(next_tid):
                latencies.append((next_tid, names[next_tid], prior_next[1], time_ns, cpu))
        # A switch from a thread to itself is possible in synthetic traces;
        # the incoming running state takes precedence.
        if prev_tid != next_tid:
            close(prev_tid, time_ns)
            state = classify_switch_state(prev_state)
            current[prev_tid] = (state, time_ns, None,
                                 'preempted' if state == 'runnable' else None)
        current[next_tid] = ('running', time_ns, cpu, None)

    counts['open_intervals'] = sum(
        1 for tid in current if selected(tid)
    )
    return intervals, latencies, counts


def write_csv(path, headings, rows):
    with path.open('w', newline='', encoding='utf-8') as output:
        writer = csv.writer(output)
        writer.writerow(headings)
        writer.writerows(rows)


def input_lines(path):
    if path.suffix != '.dat':
        with path.open(encoding='utf-8', errors='replace') as source:
            yield from source
        return
    try:
        process = subprocess.Popen(
            ['trace-cmd', 'report', '-i', str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors='replace',
        )
    except FileNotFoundError as exc:
        raise RuntimeError('trace-cmd is required to read .dat files') from exc
    assert process.stdout is not None
    yield from process.stdout
    stderr = process.stderr.read() if process.stderr else ''
    if process.wait() != 0:
        raise RuntimeError(f'trace-cmd report failed: {stderr.strip()}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='trace-cmd .dat or saved report .txt')
    parser.add_argument('-o', '--output-prefix', type=Path,
                        help='output prefix (default: input name without suffix)')
    parser.add_argument('--tid', type=int, action='append',
                        help='only export this TID (repeat for multiple threads)')
    parser.add_argument('--comm', action='append',
                        help='export threads with this exact comm (repeatable)')
    parser.add_argument('--events', type=Path,
                        help='select actual SDK TIDs from this event log, not comm names')
    args = parser.parse_args(argv)
    if args.events:
        # Local import avoids the parser module's dependency cycle.
        from analyze_flow import parse_marker
        if not args.events.is_file():
            parser.error(f'event log does not exist: {args.events}')
        tids = set()
        for line in args.events.read_text(encoding='utf-8').splitlines():
            marker = parse_marker(line)
            if marker:
                tids.add(marker[1])
        if not tids:
            parser.error('event log contains no SDK TIDs')
        args.tid = sorted(tids | set(args.tid or []))
    if not args.input.is_file():
        parser.error(f'input file does not exist: {args.input}')
    prefix = args.output_prefix or args.input.with_suffix('')
    try:
        intervals, latencies, counts = analyze(input_lines(args.input), args.tid,
                                               args.comm)
    except RuntimeError as exc:
        parser.exit(1, f'error: {exc}\n')
    if not counts['sched_switch'] and not counts['sched_wakeup'] and not counts['sched_wakeup_new']:
        parser.exit(1, 'error: no parseable sched_switch or sched_wakeup events\n')
    prefix.parent.mkdir(parents=True, exist_ok=True)
    timeline_path = Path(f'{prefix}.timeline.csv')
    latency_path = Path(f'{prefix}.latency.csv')
    summary_path = Path(f'{prefix}.summary.csv')
    write_csv(timeline_path,
              ['tid', 'comm', 'state', 'start_s', 'end_s', 'duration_ms', 'cpu'],
              ((tid, comm, state, seconds(start), seconds(end),
                f'{(end - start) / 1_000_000:.6f}', '' if cpu is None else cpu)
               for tid, comm, state, start, end, cpu in intervals))
    write_csv(latency_path,
              ['tid', 'comm', 'wakeup_s', 'scheduled_s', 'latency_ms', 'cpu'],
              ((tid, comm, seconds(wakeup), seconds(scheduled),
                f'{(scheduled - wakeup) / 1_000_000:.6f}', cpu)
               for tid, comm, wakeup, scheduled, cpu in latencies))
    totals = defaultdict(Counter)
    names = {}
    for tid, comm, state, start, end, _cpu in intervals:
        names[tid] = comm
        totals[tid][state] += end - start
    per_tid_latencies = defaultdict(list)
    for tid, comm, wakeup, scheduled, _cpu in latencies:
        names[tid] = comm
        per_tid_latencies[tid].append(scheduled - wakeup)
    write_csv(summary_path,
              ['tid', 'comm', 'running_ms', 'runnable_ms', 'sleeping_ms',
               'other_ms', 'wakeup_count', 'avg_latency_ms', 'max_latency_ms'],
              ((tid, names[tid],
                *(f'{totals[tid][state] / 1_000_000:.6f}' for state in
                  ('running', 'runnable', 'sleeping', 'other')),
                len(per_tid_latencies[tid]),
                (f'{sum(per_tid_latencies[tid]) / len(per_tid_latencies[tid]) / 1_000_000:.6f}'
                 if per_tid_latencies[tid] else ''),
                (f'{max(per_tid_latencies[tid]) / 1_000_000:.6f}'
                 if per_tid_latencies[tid] else ''))
               for tid in sorted(names)))
    print(f'{timeline_path}: {len(intervals)} closed intervals')
    print(f'{latency_path}: {len(latencies)} wakeup latencies')
    print(f'{summary_path}: {len(names)} threads')
    print('Events:', ', '.join(f'{key}={counts[key]}' for key in
          ('sched_switch', 'sched_wakeup', 'sched_wakeup_new', 'sched_waking')))
    for key in ('unparsed_scheduler_lines', 'out_of_order', 'open_intervals'):
        if counts[key]:
            print(f'{key}: {counts[key]}', file=sys.stderr)


if __name__ == '__main__':
    main()
