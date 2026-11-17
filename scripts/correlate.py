#!/usr/bin/env python3
"""Join job flows with scheduler states and synchronization intervals."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from analyze_sched import input_lines
from analyze_flow import marker_lines
from trace_data import application_event, scheduler_event


STATES = ('running', 'runnable', 'sleeping', 'other')


def ns(value):
    return int(Decimal(value) * 1_000_000_000)


def ms(value):
    return round(value / 1_000_000, 6)


def overlap(start, end, other_start, other_end):
    return max(0, min(end, other_end) - max(start, other_start))


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as source:
        return list(csv.DictReader(source))


def state_totals(intervals, start, end):
    totals = Counter()
    for row in intervals:
        totals[row['state']] += overlap(start, end, ns(row['start_s']), ns(row['end_s']))
    covered = sum(totals.values())
    totals['unknown'] = max(0, end - start - covered)
    totals['overlap_error'] = max(0, covered - (end - start))
    return totals


def correlate(flows, timeline, sync):
    by_tid = defaultdict(list)
    for row in timeline:
        by_tid[(int(row.get('pid') or 0),int(row['tid']))].append(row)
    sync_by_job = defaultdict(list)
    for row in sync:
        if int(row['job_id']) > 0:
            sync_by_job[(int(row.get('pid') or 0), int(row['job_id']))].append(row)
    jobs = []
    for flow in flows:
        pid = int(flow.get('pid') or 0)
        job_id = int(flow['job_id'])
        send = ns(flow['send_s'])
        receive = ns(flow['receive_s'])
        done = ns(flow['done_s'])
        worker_tid = int(flow['receive_tid'])
        if not send <= receive <= done:
            continue
        worker_intervals = by_tid.get((pid, worker_tid), by_tid.get((0, worker_tid), []))
        worker = state_totals(worker_intervals, receive, done)
        compute = None
        if flow.get('compute_begin_s') and flow.get('compute_end_s'):
            begin = ns(flow['compute_begin_s'])
            end = ns(flow['compute_end_s'])
            if receive <= begin <= end <= done:
                compute = state_totals(worker_intervals, begin, end)
        sync_totals = Counter()
        observed_kinds = set()
        for row in sync_by_job[(pid, job_id)]:
            observed_kinds.add(row['kind'])
            sync_totals[row['kind']] += overlap(
                send, done, ns(row['start_s']), ns(row['end_s'])
            )
        status = ('overlapping_scheduler_intervals' if worker['overlap_error'] else
                  'partial_scheduler' if worker['unknown'] else 'complete')
        item = {
            'pid': pid, 'job_id': job_id,
            'send_tid': int(flow['send_tid']), 'worker_tid': worker_tid,
            'send_s': flow['send_s'], 'receive_s': flow['receive_s'],
            'done_s': flow['done_s'],
            'queue_ms': ms(receive - send),
            'processing_ms': ms(done - receive),
            'total_ms': ms(done - send),
            'worker_running_ms': ms(worker['running']),
            'worker_runnable_ms': ms(worker['runnable']),
            'worker_sleeping_ms': ms(worker['sleeping']),
            'worker_other_ms': ms(worker['other']),
            'worker_unknown_ms': ms(worker['unknown']),
            'compute_wall_ms': ms(ns(flow['compute_end_s']) - ns(flow['compute_begin_s']))
            if compute is not None else None,
            'compute_running_ms': ms(compute['running']) if compute is not None else None,
            'compute_runnable_ms': ms(compute['runnable']) if compute is not None else None,
            'compute_sleeping_ms': ms(compute['sleeping']) if compute is not None else None,
            'compute_unknown_ms': ms(compute['unknown']) if compute is not None else None,
            'app_sleep_ms': float(flow['sleep_ms']) if flow.get('sleep_ms') else None,
            'mutex_wait_observed_ms': ms(sync_totals['mutex_wait']) if 'mutex_wait' in observed_kinds else None,
            'cond_wait_observed_ms': ms(sync_totals['cond_wait']) if 'cond_wait' in observed_kinds else None,
            'status': status,
        }
        jobs.append(item)
    return jobs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path, help='.dat file or common CSV prefix')
    args = parser.parse_args(argv)
    prefix = args.trace.with_suffix('') if args.trace.suffix == '.dat' else args.trace
    flow_path = Path(f'{prefix}.flow.csv')
    timeline_path = Path(f'{prefix}.timeline.csv')
    sync_path = Path(f'{prefix}.sync.csv')
    for path in (flow_path, timeline_path):
        if not path.is_file():
            parser.error(f'missing input: {path}')
    flows = read_csv(flow_path)
    timeline = read_csv(timeline_path)
    sync = read_csv(sync_path) if sync_path.is_file() else []
    jobs = correlate(flows, timeline, sync)
    if not jobs:
        parser.exit(1, 'error: no complete jobs to correlate\n')
    breakdown_path = Path(f'{prefix}.job_breakdown.csv')
    with breakdown_path.open('w', newline='', encoding='utf-8') as destination:
        writer = csv.DictWriter(destination, fieldnames=list(jobs[0]))
        writer.writeheader()
        writer.writerows(jobs)
    json_path = Path(f'{prefix}.jobs.json')
    # Embed replay data once at analysis time, including trace-cmd .dat inputs.
    source = next((path for path in (Path(f'{prefix}.dat'), Path(f'{prefix}.txt'))
                   if path.is_file()), None)
    events, scheduler = [], []
    if source:
        try:
            events = [event for line in marker_lines(source)
                      if (event := application_event(line))]
            tids = {int(row['tid']) for row in timeline} | {e['tid'] for e in events}
            for line in input_lines(source):
                event = scheduler_event(line)
                if event and (event.get('prev_tid') in tids or event.get('next_tid') in tids
                              or event.get('tid') in tids):
                    scheduler.append(event)
        except RuntimeError as exc:
            parser.exit(1, f'error: {exc}\n')
    with json_path.open('w', encoding='utf-8') as destination:
        json.dump({'schema': 1, 'trace': prefix.name, 'jobs': jobs,
                   'timeline': timeline, 'sync': sync, 'events': events,
                   'scheduler': scheduler}, destination,
                  ensure_ascii=False, separators=(',', ':'))
    statuses = Counter(job['status'] for job in jobs)
    print(f'{breakdown_path}: {len(jobs)} jobs, {dict(statuses)}')
    print(f'{json_path}: dashboard data')


if __name__ == '__main__':
    main()
