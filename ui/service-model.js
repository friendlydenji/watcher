/* Browser-side QNX correlation. The target streams bounded native observations;
 * this module closes only observed state intervals and never invents idle time. */
(function(root){
  const ns=value=>{const [s,f='']=String(value).split('.');return BigInt(s)*1000000000n+BigInt(f.padEnd(9,'0').slice(0,9));};
  const ms=value=>Number(value)/1e6;
  const compare=(a,b)=>{const x=ns(a.time_s),y=ns(b.time_s);return x<y?-1:x>y?1:0;};
  const overlap=(a,b,c,d)=>{const start=a>c?a:c,end=b<d?b:d;return end>start?end-start:0n;};
  function normalize(snapshot){
    const pids=new Set((snapshot.events||[]).map(e=>Number(e.pid)));
    const observed=(snapshot.transitions||[]).filter(t=>pids.has(Number(t.pid)));
    const threads=(snapshot.threads||[]).filter(t=>pids.has(Number(t.pid)));
    const timeline=[],current=new Map(),byTrack=new Map();
    for(const row of [...observed].sort(compare)){
      const previous=current.get(row.track_id);
      if(previous&&ns(row.time_s)>ns(previous.time_s)){
        const interval={...previous,start_s:previous.time_s,end_s:row.time_s,comm:`PID ${row.pid}`,cpu:previous.state==='running'?previous.cpu:null};
        timeline.push(interval);
        if(!byTrack.has(row.track_id))byTrack.set(row.track_id,[]);
        byTrack.get(row.track_id).push({...interval,a:ns(interval.start_s),b:ns(interval.end_s)});
      }
      if(row.state==='ended')current.delete(row.track_id);else current.set(row.track_id,row);
    }
    const events=[...snapshot.events||[]].sort(compare),flows=new Map(),pending=new Map(),sync=[];
    const begins={lock_wait:'mutex_wait',cond_wait_begin:'cond_wait'};
    function close(event,kind){
      const key=`${event.pid}:${event.tid}:${event.resource_id}:${kind}`,start=pending.get(key);pending.delete(key);
      if(start&&ns(event.time_s)>=ns(start.time_s))sync.push({...start,kind,job_id:kind==='mutex_hold'&&event.job_id!=='0'?event.job_id:start.job_id,start_s:start.time_s,end_s:event.time_s});
    }
    for(const event of events){
      const key=`${event.pid}:${event.job_id}`;
      if(event.job_id!=='0'){
        if(!flows.has(key))flows.set(key,{});
        const flow=flows.get(key);
        if(['send','receive','done','compute_begin','compute_end'].includes(event.phase)&&!flow[event.phase])flow[event.phase]=event;
      }
      if(begins[event.phase])pending.set(`${event.pid}:${event.tid}:${event.resource_id}:${begins[event.phase]}`,event);
      if(event.phase==='lock_acquired'){close(event,'mutex_wait');pending.set(`${event.pid}:${event.tid}:${event.resource_id}:mutex_hold`,event);}
      if(event.phase==='lock_release')close(event,'mutex_hold');
      if(event.phase==='cond_wait_end')close(event,'cond_wait');
    }
    const syncByJob=new Map();
    for(const row of sync){const key=`${row.pid}:${row.job_id}`;if(!syncByJob.has(key))syncByJob.set(key,[]);syncByJob.get(key).push(row);}
    const jobs=[];
    for(const [key,flow] of flows){
      const {send,receive,done}=flow;if(!send||!receive||!done)continue;
      const a=ns(send.time_s),b=ns(receive.time_s),c=ns(done.time_s);if(a>b||b>c||receive.track_id!==done.track_id)continue;
      const totals={running:0n,runnable:0n,sleeping:0n,other:0n};
      const intervals=byTrack.get(receive.track_id)||[];
      // Binary search skips earlier jobs on this worker.
      let lo=0,hi=intervals.length;while(lo<hi){const mid=(lo+hi)>>1;if(intervals[mid].b<=b)lo=mid+1;else hi=mid;}
      for(let i=lo;i<intervals.length&&intervals[i].a<c;i++){
        const row=intervals[i];totals[row.state]=(totals[row.state]||0n)+overlap(b,c,row.a,row.b);
      }
      const covered=Object.values(totals).reduce((sum,n)=>sum+n,0n),unknown=c-b>covered?c-b-covered:0n;
      const syncTotals={};for(const row of syncByJob.get(key)||[])syncTotals[row.kind]=(syncTotals[row.kind]||0n)+overlap(a,c,ns(row.start_s),ns(row.end_s));
      const job={pid:send.pid,job_id:send.job_id,send_tid:send.tid,worker_tid:receive.tid,
        send_track_id:send.track_id,worker_track_id:receive.track_id,send_s:send.time_s,receive_s:receive.time_s,done_s:done.time_s,
        queue_ms:ms(b-a),processing_ms:ms(c-b),total_ms:ms(c-a),worker_unknown_ms:ms(unknown),
        mutex_wait_observed_ms:syncTotals.mutex_wait==null?null:ms(syncTotals.mutex_wait),cond_wait_observed_ms:syncTotals.cond_wait==null?null:ms(syncTotals.cond_wait),
        status:snapshot.event_loss_reported?'event_loss_reported':covered>c-b?'overlapping_scheduler_intervals':unknown?'partial_scheduler':'complete'};
      for(const [state,value] of Object.entries(totals))job[`worker_${state}_ms`]=ms(value);
      jobs.push(job);
    }
    return {...snapshot,threads,thread_ids:threads.map(t=>t.track_id),cpus:[...new Set(observed.filter(t=>t.state==='running').map(t=>t.cpu))].sort((a,b)=>a-b),timeline,jobs,sync};
  }
  function perfetto(data){
    const traceEvents=[];
    for(const t of data.threads||[])traceEvents.push({ph:'M',name:'thread_name',pid:t.pid,tid:t.tid,args:{name:`PID ${t.pid} · TID ${t.tid}`}});
    for(const s of data.timeline||[])traceEvents.push({ph:'X',cat:'scheduler',name:s.state,pid:s.pid,tid:s.tid,ts:Number(ns(s.start_s))/1000,dur:Number(ns(s.end_s)-ns(s.start_s))/1000,args:{cpu:s.cpu}});
    for(const e of data.events||[])traceEvents.push({ph:'i',s:'t',cat:'sdk',name:e.phase,pid:e.pid,tid:e.tid,ts:Number(ns(e.time_s))/1000,args:{job_id:e.job_id,resource_id:e.resource_id}});
    return {traceEvents,displayTimeUnit:'ms',watcher:{history_limited:!!data.history_limited,event_loss_reported:!!data.event_loss_reported}};
  }
  const api={normalize,perfetto};if(typeof module!=='undefined')module.exports=api;else root.WatcherServiceModel=api;
})(typeof window!=='undefined'?window:globalThis);
