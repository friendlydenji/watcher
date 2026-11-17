#!/usr/bin/env python3
"""Export analyzed Watcher data as Chrome trace JSON for ui.perfetto.dev."""
import argparse
import json
from decimal import Decimal
from pathlib import Path


def micros(value):
    return float(Decimal(str(value)) * 1_000_000)


def export_trace(data):
    events = []
    tracks = {}
    owners = {int(e['tid']): int(e.get('pid') or 0) for e in data.get('events', [])}
    for job in data.get('jobs', []):
        owners[int(job['worker_tid'])] = int(job['pid'])
        owners[int(job['send_tid'])] = int(job['pid'])

    def track(pid, key, label):
        identity = (pid, key)
        if identity not in tracks:
            # Dedicated lanes keep scheduler, job and resource slices from
            # forming non-nested overlapping X events on the same track.
            tracks[identity] = len(tracks) + 1
            events.append({'ph': 'M', 'name': 'thread_name', 'pid': pid,
                           'tid': tracks[identity], 'args': {'name': label}})
        return tracks[identity]

    def slice_event(pid, tid, name, start, end, category, args):
        start_us, end_us = micros(start), micros(end)
        if end_us >= start_us:
            events.append({'ph': 'X', 'name': name, 'cat': category, 'pid': pid,
                           'tid': tid, 'ts': start_us, 'dur': end_us - start_us,
                           'args': args})

    for row in data.get('timeline', []):
        tid = int(row['tid'])
        pid = int(row['pid']) if row.get('pid') is not None else owners.get(tid, 0)
        lane = track(pid, ('state', tid), f"{row.get('comm', 'Thread')} · TID {tid} · scheduler")
        slice_event(pid, lane, row['state'], row['start_s'], row['end_s'],
                    'scheduler', {'linux_tid': tid, 'cpu': row.get('cpu')})
    for row in data.get('sync', []):
        pid, tid = int(row.get('pid') or 0), int(row['tid'])
        resource, kind = row['resource_id'], row['kind']
        lane = track(pid, ('sync', tid, resource, kind), f'TID {tid} · resource {resource} · {kind}')
        slice_event(pid, lane, kind, row['start_s'], row['end_s'],
                    'synchronization', {'linux_tid': tid, 'resource_id': resource,
                                        'job_id': row['job_id']})
    for flow_index, job in enumerate(data.get('jobs', []), 1):
        pid, job_id = int(job['pid']), job['job_id']
        lane = track(pid, ('job', str(job_id)), f'Job #{job_id}')
        for name, start, end in [('Queue', job['send_s'], job['receive_s']),
                                 ('Processing', job['receive_s'], job['done_s'])]:
            slice_event(pid, lane, name, start, end, 'job', job)
        flow_id = flow_index
        for phase, when, tid in [('s', job['send_s'], job['send_tid']),
                                  ('f', job['receive_s'], job['worker_tid'])]:
            app_lane = track(pid, ('app', int(tid)), f'TID {tid} · application')
            events.append({'ph': 'i', 's': 't', 'name': f'Job #{job_id} {phase}',
                           'cat': 'job', 'pid': pid, 'tid': app_lane, 'ts': micros(when)})
            events.append({'ph': phase, 'name': 'Job handoff', 'cat': 'flow',
                           'id': flow_id, 'pid': pid, 'tid': app_lane, 'ts': micros(when)})
    for row in data.get('events', []):
        pid, tid = int(row.get('pid') or 0), int(row['tid'])
        lane = track(pid, ('app', tid), f'TID {tid} · application')
        events.append({'ph': 'i', 's': 't', 'name': row['phase'], 'cat': 'sdk',
                       'pid': pid, 'tid': lane, 'ts': micros(row['time_s']), 'args': row})
    return {'traceEvents': events, 'displayTimeUnit': 'ms',
            'metadata': {'source': data.get('trace'), 'format': 'Watcher Chrome trace JSON'}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='analyzed .jobs.json')
    parser.add_argument('-o', '--output', type=Path)
    args = parser.parse_args(argv)
    output = args.output or args.input.with_name(args.input.name.replace('.jobs.json', '') + '.perfetto.json')
    if output.resolve() == args.input.resolve():
        parser.error('output must differ from input')
    output.write_text(json.dumps(export_trace(json.loads(args.input.read_text(encoding='utf-8'))),
                                 ensure_ascii=False), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
