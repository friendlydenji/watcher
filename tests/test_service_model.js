const {test}=require('node:test');
const assert=require('node:assert/strict');
const S=require('../ui/service-model.js');
const mark=(phase,t,tid=1,track=1)=>({pid:10,tid,track_id:track,phase,time_s:t,job_id:'18446744073709551615',resource_id:'0'});
const state=(t,kind,tid=2,track=2)=>({pid:10,tid,track_id:track,time_s:t,state:kind,cpu:0});
const input={events:[mark('send','1.000000001'),mark('receive','1.001000001',2,2),mark('done','1.004000001',2,2)],
  transitions:[state('1.001000001','running'),state('1.002000001','runnable'),state('1.003000001','sleeping'),state('1.004000001','running')],threads:[]};
test('target correlation preserves uint64 IDs and partitions observed CPU states',()=>{
  const d=S.normalize(input);assert.equal(d.jobs.length,1);const j=d.jobs[0];
  assert.equal(j.job_id,'18446744073709551615');assert.equal(j.queue_ms,1);assert.equal(j.processing_ms,3);
  assert.equal(j.worker_running_ms,1);assert.equal(j.worker_runnable_ms,1);assert.equal(j.worker_sleeping_ms,1);
  assert.equal(j.status,'complete');assert.equal(j.mutex_wait_observed_ms,null);assert.equal(j.cond_wait_observed_ms,null);
  assert.equal(d.timeline.length,3);assert.equal(d.timeline[0].cpu,0);
});
test('open tails and collector loss remain unknown',()=>{
  const d=S.normalize({...input,transitions:input.transitions.slice(0,2)});
  assert.equal(d.jobs[0].status,'partial_scheduler');assert.equal(d.jobs[0].worker_unknown_ms,2);
  assert.equal(S.normalize({...input,event_loss_reported:true}).jobs[0].status,'event_loss_reported');
});
test('QNX PID/TID collisions never merge worker state',()=>{
  const d=S.normalize({...input,transitions:[...input.transitions,{...state('1.001','running',2,3),pid:20},{...state('1.004','ended',2,3),pid:20}]});
  assert.equal(d.jobs[0].worker_running_ms,1);assert.equal(d.timeline.filter(s=>s.pid===20).length,0);
});
test('synchronization waits are optional overlapping measurements',()=>{
  const lock={...mark('lock_wait','1.001500001',2,2),resource_id:'7'};
  const d=S.normalize({...input,events:[...input.events,lock,{...lock,phase:'lock_acquired',time_s:'1.002500001'}]});
  assert.equal(d.jobs[0].mutex_wait_observed_ms,1);assert.equal(d.jobs[0].total_ms,4);assert.equal(d.sync.length,1);
});
test('Perfetto export contains real scheduler slices and original IDs',()=>{
  const d=S.perfetto(S.normalize(input));assert.equal(d.traceEvents.filter(e=>e.ph==='X').length,3);
  assert.equal(d.traceEvents.find(e=>e.cat==='sdk').args.job_id,'18446744073709551615');
});
