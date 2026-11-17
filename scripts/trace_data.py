"""Normalized scheduler and SDK records shared by live and saved captures."""
import re
from analyze_flow import parse_marker
from analyze_sched import parse_event, seconds

TARGET_CPU = re.compile(r'\btarget_cpu=(\d+)\b')
CONTEXT_TID = re.compile(r'-([0-9]+)\s+\[\d+\]')


def scheduler_event(line):
    parsed = parse_event(line)
    if not parsed or parsed[2] not in ('sched_switch', 'sched_wakeup', 'sched_wakeup_new'):
        return None
    time_ns, cpu, kind, data = parsed
    result = {'time_s': seconds(time_ns), 'cpu': cpu, 'kind': kind}
    if kind == 'sched_switch':
        prev, next_task, state = data
        result.update(prev_tid=prev[0], prev_comm=prev[1],
                      next_tid=next_task[0], next_comm=next_task[1],
                      prev_state=state,
                      detail=f'{prev[1]}:{prev[0]} {state} → {next_task[1]}:{next_task[0]}')
    else:
        target_cpu = TARGET_CPU.search(line)
        context_tid = CONTEXT_TID.search(line)
        result.update(tid=data[0], comm=data[1],
                      target_cpu=int(target_cpu[1]) if target_cpu else None,
                      waker_tid=int(context_tid[1]) if context_tid else None,
                      detail=f'{data[1]}:{data[0]} wakes')
    return result


def application_event(line):
    marker = parse_marker(line)
    if not marker:
        return None
    time_ns, tid, cpu, job, phase, resource, pid = marker
    return {'time_s': seconds(time_ns), 'tid': tid, 'cpu': cpu,
            'pid': pid, 'job_id': job, 'phase': phase, 'resource_id': resource}
