const {test}=require('node:test');
const assert=require('node:assert/strict');
const M=require('../ui/model.js');
const job={pid:1,job_id:7,processing_ms:10,total_ms:12,queue_ms:2,
  worker_running_ms:3,worker_runnable_ms:5,worker_sleeping_ms:2,status:'complete',mutex_wait_observed_ms:4};
test('time bar partitions total without adding overlapping mutex waits',()=>{
  const parts=M.parts(job);assert.equal(parts.reduce((a,p)=>a+p.ms,0),12);
  assert.equal(parts.find(p=>p.kind==='unknown').ms,0);assert.equal(parts.some(p=>p.kind==='mutex_wait'),false);
  assert.match(M.diagnosis(job),/Chờ CPU chiếm 42%/);
});
test('missing scheduler remains unknown and is never diagnosed as sleep',()=>{
  const partial={...job,status:'partial_scheduler',worker_running_ms:0,worker_runnable_ms:0,worker_sleeping_ms:0};
  assert.equal(M.parts(partial).find(p=>p.kind==='unknown').ms,10);
  assert.match(M.diagnosis(partial),/chưa đủ/);
});
test('overlapping scheduler data does not create a bar over 100%',()=>{
  const invalid={...job,status:'overlapping_scheduler_intervals',worker_running_ms:20};
  assert.equal(M.parts(invalid).reduce((a,p)=>a+p.ms,0),12);
  assert.match(M.diagnosis(invalid),/chưa đủ/);
});
test('p95 uses nearest rank and handles an empty trace',()=>{
  assert.equal(M.percentile([]),0);
  assert.equal(M.percentile(Array.from({length:20},(_,i)=>({total_ms:i+1}))),19);
});
test('live scheduler preserves preemption, migration and unknown open replay tail',()=>{
  const events=[
    {time_s:'1.000',kind:'sched_switch',cpu:0,prev_tid:1,prev_comm:'a',prev_state:'S',next_tid:2,next_comm:'b'},
    {time_s:'1.002',kind:'sched_switch',cpu:0,prev_tid:2,prev_comm:'b',prev_state:'R+',next_tid:1,next_comm:'a'},
    {time_s:'1.003',kind:'sched_switch',cpu:1,prev_tid:3,prev_comm:'c',prev_state:'S',next_tid:2,next_comm:'b'},
    {time_s:'1.004',kind:'sched_switch',cpu:1,prev_tid:2,prev_comm:'b',prev_state:'S',next_tid:3,next_comm:'c'},
    {time_s:'1.005',kind:'sched_wakeup',cpu:0,tid:2,comm:'b'}
  ];
  const replay=M.statesFromScheduler(events,[2]);
  assert.deepEqual(replay.map(s=>s.state),['running','runnable','running','sleeping']);
  assert.deepEqual(replay.filter(s=>s.state==='running').map(s=>s.cpu),[0,1]);
  const live=M.statesFromScheduler(events,[2],1.006);
  assert.equal(live.at(-1).state,'runnable');assert.equal(live.at(-1).end_s,1.006);
});
test('CPU rows survive a window containing only sleeps or no running slices',()=>{
  const all=[{tid:12,state:'running',start_s:1,end_s:1.001,cpu:0},
    {tid:12,state:'sleeping',start_s:1.001,end_s:1.1,cpu:null}];
  assert.deepEqual(M.cpuIds({},all,[12]),[0]);
  assert.deepEqual(M.cpuIds({cpus:[0,3]},[],[12]),[0,3]);
  assert.deepEqual(M.threadIds({thread_ids:[11,12],events:[{tid:11}]},[]),[11,12]);
});
test('QNX per-process TID collisions have distinct track identities',()=>{
  const rows=[{pid:10,tid:1,track_id:1,state:'running',cpu:0},{pid:20,tid:1,track_id:2,state:'running',cpu:1}];
  assert.deepEqual(M.threadIds({events:[]},rows),[1,2]);
  assert.deepEqual(M.cpuIds({},rows,[1,2]),[0,1]);
  const lost={...job,status:'event_loss_reported'};
  assert.equal(M.parts(lost).find(p=>p.kind==='unknown').ms,10);
});

test('live pages keep their origin while events arrive, then advance by whole pages',()=>{
  assert.equal(M.livePageStart(100,100.1,5),100);
  assert.equal(M.livePageStart(100,104.99,5),100);
  assert.equal(M.livePageStart(100,105,5),105);
  assert.equal(M.livePageStart(100,116,5),115);
  assert.equal(M.livePageStart(100,99,5),100);
});
