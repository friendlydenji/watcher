/* Data semantics shared by the dashboard and dependency-free regression tests. */
(function(root) {
  const labels = {processing:'Xử lý (wall time)', queue:'Trong hàng đợi', running:'Đang chạy', runnable:'Chờ CPU',
    sleeping:'Ngủ / bị chặn', other:'Trạng thái khác', unknown:'Chưa xác định'};
  const colors = {processing:'#bfd9d3',queue:'#a078c6', running:'#188975', runnable:'#d49a2b',
    sleeping:'#91a2b7', other:'#cb7f85', unknown:'#d5dbe4'};
  const n = value => Number(value) || 0;
  function parts(job) {
    const processing = Math.max(0, n(job.processing_ms));
    const stateKeys = ['running','runnable','sleeping','other'];
    const observed = stateKeys.reduce((sum,key) => sum + Math.max(0,n(job[`worker_${key}_ms`])),0);
    if (['overlapping_scheduler_intervals','event_loss_reported'].includes(job.status) || observed > processing + 0.00001) {
      return [{kind:'queue',ms:Math.max(0,n(job.queue_ms))}, {kind:'unknown',ms:processing}];
    }
    return [{kind:'queue',ms:Math.max(0,n(job.queue_ms))},
      ...stateKeys.map(kind=>({kind,ms:Math.max(0,n(job[`worker_${kind}_ms`]))})),
      {kind:'unknown',ms:Math.max(0,processing-observed)}];
  }
  function diagnosis(job) {
    if (!job) return 'Chọn một job để xem thời gian được sử dụng ở đâu.';
    const items = parts(job).sort((a,b)=>b.ms-a.ms);
    const main = items[0];
    const total = n(job.total_ms);
    if (!total) return 'Job có thời lượng bằng 0; chưa đủ dữ liệu để so sánh.';
    const percent = Math.round(main.ms/total*100);
    const messages = {
      queue:'Đây là thời gian trước khi worker nhận job.',
      running:'Đây là thời gian worker thực sự được chạy trên CPU.',
      runnable:'Worker sẵn sàng chạy nhưng đang chờ CPU.',
      sleeping:'Scheduler ghi nhận ngủ hoặc bị chặn; xem mutex và condition bên dưới.',
      other:'Scheduler ghi nhận trạng thái khác trong khoảng này.',
      unknown:'Dữ liệu scheduler chưa đủ để xác định thành phần chiếm nhiều nhất.'
    };
    return `${labels[main.kind]} chiếm ${percent}% tổng thời gian. ${messages[main.kind]}${job.status !== 'complete' && main.kind !== 'unknown' ? ' Kết quả còn thiếu hoặc có lỗi dữ liệu scheduler.' : ''}`;
  }
  function percentile(jobs, ratio=.95) {
    const values = jobs.map(j=>n(j.total_ms)).sort((a,b)=>a-b);
    return values.length ? values[Math.max(0,Math.ceil(values.length*ratio)-1)] : 0;
  }
  function statesFromScheduler(scheduler, tids, end) {
    const current = new Map(), result = [];
    const wanted = new Set(tids.map(Number));
    const names = new Map();
    const close = (tid,time) => {
      const prior = current.get(tid);
      if (prior && time > prior.start_s && wanted.has(tid)) result.push({...prior,tid,comm:names.get(tid)||'',end_s:time});
      current.delete(tid);
      return prior;
    };
    for (const e of [...scheduler].sort((a,b)=>n(a.time_s)-n(b.time_s))) {
      const t=n(e.time_s);
      if (e.kind === 'sched_switch') {
        const prev=n(e.prev_tid), next=n(e.next_tid);
        names.set(prev,e.prev_comm); names.set(next,e.next_comm);
        close(next,t);
        if (prev!==next) {
          close(prev,t);
          const state = e.prev_state.startsWith('R')?'runnable':/^[SD]/.test(e.prev_state)?'sleeping':'other';
          current.set(prev,{state,start_s:t,cpu:null});
        }
        current.set(next,{state:'running',start_s:t,cpu:n(e.cpu)});
      } else if (e.kind === 'sched_wakeup' || e.kind === 'sched_wakeup_new') {
        const tid=n(e.tid); names.set(tid,e.comm);
        const state=current.get(tid)?.state;
        if (state!=='running' && state!=='runnable') {
          close(tid,t); current.set(tid,{state:'runnable',start_s:t,cpu:null});
        }
      }
    }
    // Only live observations extend open states. Replay leaves the tail unknown.
    if (end != null) for (const tid of [...current.keys()]) close(tid,end);
    return result;
  }
  function threadKey(record) { return Number(record.track_id ?? record.tid); }
  function threadIds(snapshot, states) {
    return [...new Set([...(snapshot.thread_ids || []),
      ...(snapshot.events || []).map(threadKey), ...states.map(threadKey)]
      .map(Number).filter(tid=>Number.isInteger(tid)&&tid>0))].sort((a,b)=>a-b);
  }
  function cpuIds(snapshot, states, tids) {
    const wanted=new Set(tids);
    const cpus=[...(snapshot.cpus || [])];
    for(const state of states) {
      if(state.state==='running' && state.cpu!=='' && state.cpu!=null)cpus.push(state.cpu);
    }
    for(const event of snapshot.scheduler || []) {
      if(event.kind==='sched_switch' && (wanted.has(Number(event.prev_tid)) || wanted.has(Number(event.next_tid))))cpus.push(event.cpu);
    }
    return [...new Set(cpus.map(Number).filter(cpu=>Number.isInteger(cpu)&&cpu>=0))].sort((a,b)=>a-b);
  }
  // A fixed time page fills left to right; incoming data never scrolls old slices left.
  function livePageStart(origin, latest, duration) {
    return origin + Math.max(0, Math.floor((latest-origin)/duration)) * duration;
  }
  const api = {livePageStart,labels,colors,n,parts,diagnosis,percentile,statesFromScheduler,threadIds,cpuIds,threadKey};
  if (typeof module !== 'undefined') module.exports=api;
  else root.WatcherModel=api;
})(typeof window !== 'undefined' ? window : globalThis);
