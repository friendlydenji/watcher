const $=id=>document.getElementById(id), M=WatcherModel;
const n=M.n, fmt=value=>value==null?'—':`${n(value).toFixed(3)} ms`;
let traceData=null, selectedJob=null, selectedTrace=null, traceFiles=[];
let loadVersion=0, livePending=false, paused=false, liveWasActive=false, currentMtime=null;

function element(tag,className,text) {
  const el=document.createElement(tag);if(className)el.className=className;
  if(text!==undefined)el.textContent=text;return el;
}
async function getJSON(url) {
  const response=await fetch(url,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  return response.json();
}
function jobs(){return traceData?.jobs||[];}
function slowest(){return jobs().reduce((worst,j)=>!worst||n(j.total_ms)>n(worst.total_ms)?j:worst,null);}
function sameJob(a,b){return !!a&&!!b&&String(a.pid)===String(b.pid)&&String(a.job_id)===String(b.job_id);}
function stat(label,value,unit,note) {
  const el=element('div','stat');el.append(element('span','',label),element('strong','',value),element('small','',unit),element('div','stat-note',note));return el;
}
function renderOverview() {
  const list=jobs(),worst=slowest(),complete=list.filter(j=>j.status==='complete').length;
  $('stats').replaceChildren(stat('Job đã ghép',String(list.length),'job','Chỉ gồm luồng send → receive → done'),
    stat('Thời gian trung vị',M.percentile(list,.5).toFixed(3),'ms','50% job có thời gian không vượt mức này'),
    stat('Độ trễ p95',M.percentile(list).toFixed(3),'ms',list.length<20?'Ít hơn 20 job · chưa đánh dấu ngoại lai':'95% job có thời gian không vượt mức này'),
    stat('Scheduler đầy đủ',list.length?Math.round(complete/list.length*100).toString():'—','%',`${complete}/${list.length} job có đủ trạng thái worker`));
  $('insightTitle').textContent=worst?`Job #${worst.job_id} chậm nhất · ${fmt(worst.total_ms)}`:'Chưa có job để phân tích';
  $('insightText').textContent=worst?M.diagnosis(worst):selectedTrace==='__live__'?'Theo dõi scheduler và SDK trong lúc capture. Số liệu job có sau khi phân tích hoàn tất.':'Chạy scripts/capture-app.sh với ứng dụng đã gắn SDK, sau đó chọn trace ở trên.';
  $('selectSlowest').disabled=!worst;
}
function stacked(job) {
  const bar=element('div','stacked');
  bar.setAttribute('role','img');
  bar.setAttribute('aria-label',M.parts(job).filter(p=>p.ms>0).map(p=>`${M.labels[p.kind]} ${fmt(p.ms)}`).join(', '));
  for(const p of M.parts(job)) {
    if(p.ms<=0)continue;const part=element('span');part.style.width=`${n(job.total_ms)?p.ms/n(job.total_ms)*100:0}%`;part.style.background=M.colors[p.kind];bar.append(part);
  }
  return bar;
}
function renderJobs() {
  const search=$('jobSearch').value.trim().toLowerCase().replace(/^#/,'');
  const list=jobs().filter(j=>!search||`${j.job_id} ${j.pid} ${j.worker_tid}`.toLowerCase().includes(search));
  const sort=$('jobSort').value;
  list.sort((a,b)=>sort==='queue'?n(b.queue_ms)-n(a.queue_ms):sort==='recent'?n(b.send_s)-n(a.send_s):n(b.total_ms)-n(a.total_ms));
  const parent=$('jobsList');parent.replaceChildren();$('jobCount').textContent=String(list.length);
  const threshold=M.percentile(jobs());
  for(const job of list) {
    const button=element('button',`job-row${sameJob(job,selectedJob)?' active':''}`);button.type='button';
    button.setAttribute('aria-pressed',String(sameJob(job,selectedJob)));
    const top=element('div','job-top');top.append(element('strong','',`Job #${job.job_id}`));
    if(jobs().length>=20&&n(job.total_ms)>threshold)top.append(element('span','outlier','> p95'));
    const time=element('span','job-time',n(job.total_ms).toFixed(3));time.append(element('small','',' ms'));top.append(time);
    const meta=element('div','job-meta');meta.append(element('span','',`PID ${job.pid} · TID ${job.worker_tid}`),element('span','',job.status==='complete'?'Đủ dữ liệu':'Thiếu / lỗi scheduler'));
    button.append(top,meta,stacked(job));button.onclick=()=>selectJob(job);parent.append(button);
  }
  if(!list.length)parent.append(element('p','empty',jobs().length?'Không tìm thấy job phù hợp.':'Chưa có job đã phân tích.'));
}
function metric(label,value){const el=element('div','metric');el.append(element('span','',label),element('strong','',value));return el;}
function detailTrack(label,segments,start,end,color) {
  if(end<=start)return;
  const track=element('div','track'),heading=element('div','track-head');
  heading.append(element('span','',label),element('span','',`${((end-start)*1000).toFixed(3)} ms`));
  const bar=element('div',color?'bar annotation':'bar');
  for(const s of segments) {
    const a=Math.max(start,n(s.start_s)),b=Math.min(end,n(s.end_s));if(b<=a)continue;
    const part=element('button','segment');part.type='button';
    part.style.left=`${(a-start)/(end-start)*100}%`;part.style.width=`${(b-a)/(end-start)*100}%`;
    part.style.background=color||M.colors[s.state]||M.colors.other;
    part.setAttribute('aria-label',`${label}: ${M.labels[s.state]||s.kind||s.state}, ${((b-a)*1000).toFixed(3)} ms`);
    part.onclick=()=>showSlice({type:'interval',...s});bar.append(part);
  }
  track.append(heading,bar);$('timeline').append(track);
}
function renderDetail() {
  const j=selectedJob;$('metrics').replaceChildren();$('timeline').replaceChildren();$('sliceDetail').hidden=true;
  $('detailTitle').textContent=j?`Job #${j.job_id}`:'Chi tiết job';
  $('detailStatus').textContent=j?j.status==='complete'?'ĐỦ DỮ LIỆU':j.status==='partial_scheduler'?'THIẾU SCHEDULER':j.status==='event_loss_reported'?'MẤT SỰ KIỆN':'LỖI CHỒNG KHOẢNG':'CHƯA CHỌN';
  $('detailStatus').classList.toggle('active',j?.status==='complete');
  $('detailIdentity').textContent=j?`PID ${j.pid} · Gửi từ TID ${j.send_tid} → Worker TID ${j.worker_tid}`:'';
  $('jobDiagnosis').textContent=M.diagnosis(j);
  if(!j)return;
  $('metrics').append(metric('Tổng send → done',fmt(j.total_ms)),metric('Trong hàng đợi',fmt(j.queue_ms)),
    metric('Worker chạy trên CPU',fmt(j.worker_running_ms)),metric('Worker chờ CPU',fmt(j.worker_runnable_ms)),
    metric('Worker ngủ / bị chặn',fmt(j.worker_sleeping_ms)),metric('Worker chưa xác định',fmt(M.parts(j).find(p=>p.kind==='unknown')?.ms)),
    metric('Mutex wait (quan sát)',j.mutex_wait_observed_ms==null?'Chưa đo':fmt(j.mutex_wait_observed_ms)),metric('Condition wait (quan sát)',j.cond_wait_observed_ms==null?'Chưa đo':fmt(j.cond_wait_observed_ms)));
  const start=n(j.send_s),receive=n(j.receive_s),end=n(j.done_s);
  detailTrack('Hàng đợi → xử lý',[{start_s:start,end_s:receive,state:'queue'},{start_s:receive,end_s:end,state:'processing'}],start,end);
  detailTrack(`Scheduler worker · TID ${j.worker_tid}`,(traceData.timeline||[]).filter(s=>Number(s.tid)===Number(j.worker_tid)&&(s.pid==null||Number(s.pid)===Number(j.pid))),start,end);
  const sync=(traceData.sync||[]).filter(s=>Number(s.pid||0)===Number(j.pid)&&String(s.job_id)===String(j.job_id));
  // Each resource/kind gets its own row: overlapping waits are never painted over.
  const groups=new Map();
  for(const s of sync){const key=`${s.kind} · TID ${s.tid} · resource ${s.resource_id}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(s);}
  for(const [key,rows] of groups)detailTrack(key,rows,start,end,'#b48bba');
}
function selectJob(job,move=true) {selectedJob=job;renderJobs();renderDetail();WatcherTimeline.setJob(job,move);}
function showSlice(s) {
  const panel=$('sliceDetail');panel.hidden=false;panel.replaceChildren();
  const heading=element('strong','',s.type==='handoff'?`Chuyển job #${s.job_id}`:s.type==='wakeup'?`Wakeup TID ${s.tid}`:`${M.labels[s.state]||s.kind||s.phase||'Khoảng quan sát'} · TID ${s.tid}`);
  panel.append(heading,element('br'));
  if(s.start_s!=null&&s.end_s!=null)panel.append(document.createTextNode(`Bắt đầu ${Number(s.start_s).toFixed(9)} s · Kết thúc ${Number(s.end_s).toFixed(9)} s · ${((n(s.end_s)-n(s.start_s))*1000).toFixed(3)} ms`));
  else if(s.type==='handoff')panel.append(document.createTextNode(`PID ${s.pid} · TID ${s.send_tid} → ${s.worker_tid} · ${((n(s.receive_s)-n(s.send_s))*1000).toFixed(3)} ms trong hàng đợi`));
  else panel.append(document.createTextNode(`${n(s.time_s).toFixed(9)} s · ${s.detail||s.phase||''}`));
  if(s.cpu!=null&&s.cpu!=='')panel.append(document.createTextNode(` · CPU ${s.cpu}`));
  if(s.resource_id!=null)panel.append(document.createTextNode(` · resource ${s.resource_id}`));
  if(s.comm)panel.append(document.createTextNode(` · ${s.comm}`));
  const related=jobs().filter(j=>Number(j.worker_tid)===Number(s.tid)&&(s.pid==null||Number(s.pid)===Number(j.pid))&&n(j.receive_s)<n(s.end_s)&&n(j.done_s)>n(s.start_s));
  if(related.length)panel.append(element('div','',`Job giao với khoảng này: ${related.map(j=>`#${j.job_id} (PID ${j.pid})`).join(', ')}`));
}
window.addEventListener('watcher-slice',e=>showSlice(e.detail));
function renderRaw(data) {
  $('liveSource').textContent=data.name||data.trace||'';
  for(const [id,records] of [['liveEvents',data.events||[]],['liveScheduler',data.scheduler||[]]]) {
    const panel=$(id);panel.replaceChildren();
    for(const e of records.slice(-60).reverse()) {
      const row=element('div','raw-row');row.append(element('b','',e.phase||e.kind.replace('sched_','')),
        element('span','',`${n(e.time_s).toFixed(6)} s · ${e.detail||`PID ${e.pid} · TID ${e.tid} · job ${e.job_id}`}`));panel.append(row);
    }
    if(!records.length)panel.append(element('p','empty','Không có sự kiện gốc trong trace này.'));
  }
}
async function loadTrace(name,preserve=false) {
  const version=++loadVersion;selectedTrace=name;paused=false;$('pauseButton').textContent='Tạm dừng';$('pauseButton').hidden=name!=='__live__';
  $('traceSelect').value=name;$('traceStatus').textContent='Đang đọc trace…';
  const exportLink=$('exportButton');exportLink.removeAttribute('href');exportLink.setAttribute('aria-disabled','true');
  try {
    if(name==='__live__') {
      traceData=null;selectedJob=null;liveWasActive=false;WatcherTimeline.setData({name:null,timeline:[],events:[],scheduler:[]},true);
      renderOverview();renderJobs();renderDetail();renderRaw({});await refreshLive();return;
    }
    const data=await getJSON(`/api/data?name=${encodeURIComponent(name)}`);
    if(version!==loadVersion)return;
    const prior=selectedJob;traceData=data;
    selectedJob=preserve?jobs().find(j=>sameJob(j,prior))||slowest():slowest();
    currentMtime=traceFiles.find(t=>t.name===name)?.modified;
    $('traceStatus').textContent=`${data.synthetic?'DỮ LIỆU MINH HỌA · ':''}${data.jobs?.length||0} job · ${data.timeline?.length||0} khoảng scheduler · Đã tải`;
    $('exportButton').href=`/api/export?name=${encodeURIComponent(name)}`;$('exportButton').setAttribute('aria-disabled','false');
    WatcherTimeline.setData({...data,name:data.trace,active:false},!preserve);
    WatcherTimeline.setJob(selectedJob,false);renderOverview();renderJobs();renderDetail();renderRaw(data);
  } catch(error) {
    if(version!==loadVersion)return;
    traceData=null;selectedJob=null;WatcherTimeline.setData({name:null,timeline:[],events:[],scheduler:[]},true);
    renderOverview();renderJobs();renderDetail();renderRaw({});$('traceStatus').textContent=`Không tải được trace: ${error.message}`;
  }
}
async function refreshTraces() {
  try {
    traceFiles=await getJSON('/api/traces');
    const select=$('traceSelect'),names=['__live__',...traceFiles.map(t=>t.name)];
    if(names.join('|')!==[...select.options].map(o=>o.value).join('|')) {
      select.replaceChildren(new Option('Theo dõi capture trực tiếp','__live__'));
      for(const item of traceFiles)select.append(new Option(item.name.replace('.jobs.json',''),item.name));
    }
    if(selectedTrace===null||!names.includes(selectedTrace))await loadTrace(traceFiles[0]?.name||'__live__');
    else if(selectedTrace!=='__live__'&&traceFiles.find(t=>t.name===selectedTrace)?.modified!==currentMtime)await loadTrace(selectedTrace,true);
    select.value=selectedTrace;
  }catch(error){$('traceStatus').textContent=`Không kết nối được máy chủ: ${error.message}`;}
}
async function refreshLive() {
  if(selectedTrace!=='__live__'||paused||livePending)return;
  livePending=true;const version=loadVersion;
  try {
    const live=await getJSON('/api/live');if(version!==loadVersion)return;
    WatcherTimeline.setData(live);renderRaw(live);
    $('traceStatus').textContent=live.name?`${live.name} · ${live.loading?'Đang nạp lịch sử scheduler':live.phase==='draining'?'App đã kết thúc · đang hoàn tất capture':live.phase==='failed'?'Capture lỗi · xem terminal':live.active?'Đang nhận dữ liệu':'Capture đã dừng ghi'} · ${live.scheduler?.length||0} sự kiện scheduler${live.history_limited?' · lịch sử có giới hạn':''}`:'Đang chờ scripts/live-app.sh';
    const analyzed=live.name?.replace('.events.log','.jobs.json');
    if(liveWasActive&&!live.active&&traceFiles.some(t=>t.name===analyzed)){await loadTrace(analyzed);return;}
    liveWasActive=liveWasActive||live.active;
  } catch(error){$('traceStatus').textContent=`Không tải được capture trực tiếp: ${error.message}`;}
  finally{livePending=false;}
}
$('traceSelect').onchange=e=>loadTrace(e.target.value);
$('jobSearch').oninput=renderJobs;$('jobSort').onchange=renderJobs;
$('selectSlowest').onclick=()=>{const j=slowest();if(j)selectJob(j);};
$('pauseButton').onclick=()=>{paused=!paused;$('pauseButton').textContent=paused?'Tiếp tục':'Tạm dừng';if(paused)$('liveBadge').textContent='TẠM DỪNG';else refreshLive();};
renderOverview();refreshTraces();setInterval(refreshTraces,4000);setInterval(refreshLive,500);
