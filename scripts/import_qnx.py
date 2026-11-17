#!/usr/bin/env python3
"""Import QNX 7.1/8.0 traceprinter + SDK log into the shared dashboard format."""
import argparse
import csv
import json
import re
import shutil
from decimal import Decimal
from pathlib import Path

from analyze_flow import main as flow_main, parse_marker
from analyze_sync import main as sync_main
from correlate import main as correlate_main

EVENT = re.compile(r'cycles:0x([0-9a-fA-F]+)\s+cpu:(\d+)\s+THREAD\s*:\s*(TH\w+)\s+.*?\bpid:(\d+)\s+tid:(\d+)')
BLOCKED = {'THSEND','THRECEIVE','THREPLY','THNANOSLEEP','THMUTEX','THCONDVAR',
           'THJOIN','THSEM','THSIGSUSPEND','THSIGWAITINFO','THINTR','THWAITPAGE',
           'THWAITCTXN','THWAITTHREAD','THNET_SEND','THNET_REPLY','THSTACK'}


def seconds(ns):
    return f'{ns//1000000000}.{ns%1000000000:09d}'


def intervals(lines, clock, identities):
    frequency = int(clock['cycles_per_sec'])
    if frequency <= 0:
        raise ValueError('cycles_per_sec must be positive')
    anchor, monotonic = int(clock['cycles']), int(clock['mono_ns'])
    transitions=[]
    for line in lines:
        match=EVENT.search(line)
        if not match:
            continue
        cycles,cpu,state,pid,tid=match.groups()
        identity=(int(pid),int(tid))
        if identity not in identities:
            continue
        time_ns=monotonic+(int(cycles,16)-anchor)*1000000000//frequency
        transitions.append((time_ns,int(cpu),state,identity))
    current={};result=[]
    for time_ns,cpu,native,identity in sorted(transitions):
        if native in ('THCREATE','THCREATE_NAME'):
            continue
        state='running' if native=='THRUNNING' else 'runnable' if native=='THREADY' else 'sleeping' if native in BLOCKED else 'other'
        prior=current.pop(identity,None)
        if prior and time_ns>prior[0]:
            begin,kind,old_cpu,old_native=prior
            result.append(dict(pid=identity[0],tid=identity[1],comm=f'PID {identity[0]}',
                state=kind,start_s=seconds(begin),end_s=seconds(time_ns),
                duration_ms=f'{(time_ns-begin)/1000000:.6f}',cpu=old_cpu,
                native_state=old_native))
        if native not in ('THDESTROY','THDEAD'):
            current[identity]=(time_ns,state,cpu if state=='running' else '',native)
    # No invented end for a thread whose final state has not been observed.
    return result


def add_tracks(data):
    identities=set()
    for row in data['timeline']+data['events']+data['sync']:
        identities.add((int(row.get('pid') or 0),int(row['tid'])))
    for job in data['jobs']:
        identities.update([(int(job['pid']),int(job['send_tid'])),(int(job['pid']),int(job['worker_tid']))])
    mapping={identity:index+1 for index,identity in enumerate(sorted(identities))}
    for row in data['timeline']+data['events']+data['sync']:
        row['track_id']=mapping[(int(row.get('pid') or 0),int(row['tid']))]
    for job in data['jobs']:
        job['send_track_id']=mapping[(int(job['pid']),int(job['send_tid']))]
        job['worker_track_id']=mapping[(int(job['pid']),int(job['worker_tid']))]
    data['threads']=[dict(track_id=index,pid=pid,tid=tid) for (pid,tid),index in mapping.items()]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path,help="traceprinter -n -p 'cycles:0x%016c cpu:%C %Z:%z' output")
    parser.add_argument('--events',type=Path,help='SDK file log; omit to extract native user markers')
    parser.add_argument('--clock',type=Path,help='SDK .events.log.clock.json, detected by default')
    parser.add_argument('--output-prefix',type=Path,required=True)
    parser.add_argument('--collector-log',type=Path,help='tracelogger diagnostics; detected beside report')
    args=parser.parse_args(argv)
    prefix=args.output_prefix;prefix.parent.mkdir(parents=True,exist_ok=True)
    lines=args.report.read_text(errors='replace').splitlines()
    if args.events is None:
        pattern=re.compile(r'LTI_EVENT mono_ns=\d+ tid=\d+ pid=\d+ job=\d+ phase=[a-z_]+ v=\d+ resource=\d+')
        records=[match[0] for line in lines if (match:=pattern.search(line))]
        clocks=[]
        for line in lines:
            if 'LTI_CLOCK ' in line:
                text=line.split('LTI_CLOCK ',1)[1]
                begin=text.find('{');end=text.rfind('}')
                try:clocks.append(json.loads(text[begin:end+1]))
                except ValueError:continue
        if not records or not clocks:parser.error('native trace needs LTI_EVENT and LTI_CLOCK user records')
        args.events=Path(str(prefix)+'.events.log')
        args.events.write_text('\n'.join(records)+'\n')
        clock=min(clocks,key=lambda c:int(c['bracket_cycles']))
    else:
        clock_path=args.clock or Path(str(args.events)+'.clock.json')
        clock=json.loads(clock_path.read_text())
    identities=set()
    for line in args.events.read_text().splitlines():
        event=parse_marker(line)
        if event:identities.add((event[6],event[1]))
    if not identities:parser.error('no SDK identities; refusing to guess QNX thread ownership')
    rows=intervals(lines,clock,identities)
    if not rows:parser.error('no QNX state intervals with full 64-bit cycle timestamps')
    prefix=args.output_prefix;prefix.parent.mkdir(parents=True,exist_ok=True)
    event_path=Path(str(prefix)+'.events.log')
    if event_path.resolve()!=args.events.resolve():shutil.copyfile(args.events,event_path)
    report_path=Path(str(prefix)+'.txt')
    if report_path.resolve()!=args.report.resolve():shutil.copyfile(args.report,report_path)
    with Path(str(prefix)+'.timeline.csv').open('w',newline='') as destination:
        writer=csv.DictWriter(destination,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    flow_main([str(report_path),'--events',str(event_path),'-o',str(prefix)+'.flow.csv'])
    sync_main([str(report_path),'--events',str(event_path),'-o',str(prefix)+'.sync.csv'])
    correlate_main([str(prefix)])
    output=Path(str(prefix)+'.jobs.json');data=json.loads(output.read_text());add_tracks(data)
    data.update(platform='qnx',clock=clock,clock_resolution_ns=(1000000000+int(clock['cycles_per_sec'])-1)//int(clock['cycles_per_sec']),clock_alignment_bracket_ns=
                (int(clock['bracket_cycles'])*1000000000+int(clock['cycles_per_sec'])-1)//int(clock['cycles_per_sec']))
    diagnostics=args.collector_log or args.report.with_suffix('.collector.log')
    if diagnostics.is_file():
        text=diagnostics.read_text(errors='replace')
        lost='dropping buffers' in text
        data['collector_backlog_reported']='not keeping up' in text
        data['capture_integrity']='loss_reported' if lost else 'no_loss_reported'
        if lost:
            for job in data['jobs']:job['status']='event_loss_reported'
    else:data['capture_integrity']='collector_log_unavailable'
    temporary=output.with_name(output.name+'.tmp')
    temporary.write_text(json.dumps(data,separators=(',',':')))
    temporary.replace(output)
    print(f'{output}: QNX, {len(identities)} native PID/TID pairs; no Linux TID assumptions')


if __name__=='__main__':main()
