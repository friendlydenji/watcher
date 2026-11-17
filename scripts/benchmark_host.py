#!/usr/bin/env python3
"""Paired wall-time throughput measurements; raw results are retained."""
import argparse
import json
import statistics
import subprocess
import tempfile
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('optimized',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
records=[]
with tempfile.TemporaryDirectory(prefix='watcher-bench-') as directory:
    for mode,threads,count in [('disabled',1,500000),('devnull',1,300000),('devnull',4,100000),('regular-file',1,50000),('regular-file',4,20000)]:
        for repeat in range(5):
            for label,binary in [('baseline',a.baseline),('optimized',a.optimized)]:
                output='-' if mode=='disabled' else '/dev/null' if mode=='devnull' else str(Path(directory)/f'{mode}-{threads}-{repeat}-{label}.log')
                result=subprocess.run([str(binary.resolve()),str(count),str(threads),output],capture_output=True,text=True,check=True)
                item=json.loads(result.stdout);item.update(mode=mode,repeat=repeat,version=label);records.append(item)
summary=[]
for mode,threads in dict.fromkeys((r['mode'],r['threads']) for r in records):
    row={'mode':mode,'threads':threads}
    for label in ('baseline','optimized'):
        values=[r['ns_per_event'] for r in records if r['mode']==mode and r['threads']==threads and r['version']==label]
        row[label+'_median_ns_per_event']=statistics.median(values)
        row[label+'_range_ns_per_event']=[min(values),max(values)]
    row['reduction_percent']=100*(1-row['optimized_median_ns_per_event']/row['baseline_median_ns_per_event'])
    summary.append(row)
a.output.write_text(json.dumps({'method':'five interleaved repetitions, O2, wall elapsed / total events; concurrency number is reciprocal aggregate throughput, not per-call latency','records':records,'summary':summary},indent=2)+'\n')
print(json.dumps(summary,indent=2))
