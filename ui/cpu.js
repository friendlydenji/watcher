/* Interactive thread/CPU timeline. Saved traces and live captures share a model. */
window.WatcherTimeline = (() => {
  const M=WatcherModel, NS='http://www.w3.org/2000/svg';
  const $=id=>document.getElementById(id);
  let data={timeline:[],events:[],scheduler:[]}, view='thread', selectedJob=null;
  let picked=null, focus=null, bounds=[0,1], start=0, duration=1, fit=true, initialized=false, drag=null;
  let followLive=false, liveOrigin=null;
  const left=142, width=910, top=38, rowHeight=48;
  function node(tag,attrs={},text) {
    const el=document.createElementNS(NS,tag);
    for(const [key,value] of Object.entries(attrs)) el.setAttribute(key,value);
    if(text!==undefined) el.textContent=text;
    return el;
  }
  function threadColor(tid) {
    // CPU view uses blue/purple identity colors; thread view uses state colors.
    const hash=Math.abs(Math.imul(Number(tid),2654435761))>>>0;
    return `hsl(${210+hash%88} ${47+(hash>>>8)%25}% ${51+(hash>>>16)%15}%)`;
  }
  function latestStart() {
    return data.active||followLive
      ? Math.max(bounds[0],M.livePageStart(liveOrigin??bounds[0],bounds[1],duration))
      : Math.max(bounds[0],bounds[1]-duration);
  }
  function clamp() {
    duration=Math.max(.000001,duration);
    if(followLive)return; // Keep the unfilled right side of the current live page.
    if(!data.active)duration=Math.min(duration,Math.max(.000001,bounds[1]-bounds[0]));
    start=Math.max(bounds[0],Math.min(start,latestStart()));
  }
  function follow() {
    followLive=true;fit=false;
    if(liveOrigin==null)liveOrigin=bounds[0];
    start=M.livePageStart(liveOrigin,bounds[1],duration);
    $('windowSelect').value=[10,100,500,2000,5000].includes(duration*1000)?String(duration*1000):'custom';
    render();
  }
  function calculateBounds() {
    let min=Infinity,max=-Infinity;
    const include=t=>{t=Number(t);if(Number.isFinite(t)){min=Math.min(min,t);max=Math.max(max,t);}};
    for(const s of data.timeline||[]){include(s.start_s);include(s.end_s);}
    for(const e of data.events||[])include(e.time_s);
    for(const e of data.scheduler||[])include(e.time_s);
    for(const j of data.jobs||[]){include(j.send_s);include(j.done_s);}
    if(!Number.isFinite(min)) return [0,1];
    return [min,Math.max(min+.000001,max)];
  }
  function segments() {
    if(data.timeline?.length) return data.timeline;
    const tids=M.threadIds(data,[]);
    const times=(data.scheduler||[]).map(e=>Number(e.time_s)).filter(Number.isFinite);
    return M.statesFromScheduler(data.scheduler||[],tids,data.active&&times.length?Math.max(...times):null);
  }
  function dispatch(detail) {
    window.dispatchEvent(new CustomEvent('watcher-slice',{detail}));
  }
  function render() {
    clamp();
    if(fit)$('windowSelect').value='fit';
    const chart=$('cpuChart'); chart.replaceChildren();
    const badge=$('liveBadge');
    badge.textContent=data.active?'● LIVE':data.name?'REPLAY':'CHỜ DỮ LIỆU';
    badge.classList.toggle('active',!!data.active);
    $('followLive').hidden=!data.active;
    $('followLive').disabled=followLive;
    $('followLive').textContent=followLive?'Đang vẽ sang phải →':'Theo dõi live →';
    const all=segments();
    const names=new Map();
    for(const s of all) if(s.comm) names.set(M.threadKey(s),s.comm);
    const nativeThreads=new Map((data.threads||[]).map(t=>[Number(t.track_id),t]));
    let tids=M.threadIds(data,all);
    const cpus=M.cpuIds(data,all,tids);
    if(focus!=null) tids=tids.filter(t=>t===focus);
    const end=start+duration;
    const shown=all.filter(s=>Number(s.end_s)>start && Number(s.start_s)<end && tids.includes(M.threadKey(s)));
    const lanes=view==='thread'?tids:cpus;
    $('cpuSubtitle').textContent=`${view==='thread'?'Mỗi hàng là một thread · màu = trạng thái':'Mỗi hàng là một CPU · màu = thread'} · ${tids.length} thread · ${(duration*1000).toFixed(2)} ms`;
    $('clearFocus').hidden=focus==null;
    $('threadLegend').replaceChildren();
    if(view==='cpu') for(const tid of tids) {
      const chip=document.createElement('button'); chip.type='button';chip.className='thread-chip';
      const dot=document.createElement('i');dot.style.background=threadColor(tid);
      chip.append(dot,document.createTextNode(`${names.get(tid)||'thread'} · TID ${nativeThreads.get(tid)?.tid??tid}`));
      chip.onclick=()=>{focus=tid;render();};$('threadLegend').append(chip);
    }
    const legend=$('stateLegend');legend.replaceChildren();
    const kinds=view==='thread'?['running','runnable','sleeping','other','unknown']:[];
    for(const kind of kinds) {
      const entry=document.createElement('span'),dot=document.createElement('i');dot.style.background=M.colors[kind];
      entry.append(dot,document.createTextNode(M.labels[kind]));legend.append(entry);
    }
    const flowKey=document.createElement('span');flowKey.textContent='↗ Chuyển job đã chọn';flowKey.style.color='#8162ae';legend.append(flowKey);
    const range=Math.max(0,latestStart()-bounds[0]);
    $('timeOffset').disabled=range<=.000001;
    $('timeOffset').value=range?Math.round((start-bounds[0])/range*1000):1000;
    $('offsetLabel').textContent=fit?'Toàn bộ trace':`${((start-bounds[0])*1000).toFixed(2)} → ${((end-bounds[0])*1000).toFixed(2)} ms`;
    if(!lanes.length) {
      const empty=document.createElement('p');empty.className='empty';
      empty.textContent=data.error?`Không đọc được scheduler: ${data.error}`:data.loading?'Đang nạp lịch sử scheduler của ứng dụng…':data.scheduler_missing?'Chưa có file scheduler cho capture này. Kiểm tra terminal chạy live-app.sh.':tids.length?'Đã nhận SDK events nhưng chưa có sched_switch của ứng dụng. Đang chờ scheduler; đây không phải số lượng CPU bằng 0.':'Chưa có dữ liệu ứng dụng. Chọn trace hoặc bắt đầu capture từ app đã gắn SDK.';
      chart.append(empty); return;
    }
    const height=top+lanes.length*rowHeight+15;
    const svg=node('svg',{viewBox:`0 0 1080 ${height}`,role:'group','aria-label':`Timeline theo ${view==='thread'?'thread':'CPU'}`});
    const defs=node('defs');
    for(const [id,color] of [['flow','#8162ae'],['wake','#5874b0']]) {
      const marker=node('marker',{id:`arrow-${id}`,viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:5,markerHeight:5,orient:'auto'});
      marker.append(node('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:color}));defs.append(marker);
    }
    const pattern=node('pattern',{id:'unknown-pattern',patternUnits:'userSpaceOnUse',width:7,height:7,patternTransform:'rotate(45)'});
    pattern.append(node('rect',{width:7,height:7,fill:'#f2f4f7'}),node('line',{x1:0,y1:0,x2:0,y2:7,stroke:'#dce2ea','stroke-width':2}));defs.append(pattern);svg.append(defs);
    const x=t=>left+(t-start)/duration*width;
    if(data.active&&bounds[1]>=start&&bounds[1]<=end) {
      svg.append(node('line',{x1:x(bounds[1]),y1:top-4,x2:x(bounds[1]),y2:height-12,stroke:'#188975','stroke-width':1.5,'stroke-dasharray':'4 3',class:'live-cursor'}));
    }
    const y=lane=>top+lanes.indexOf(lane)*rowHeight+rowHeight/2;
    for(let i=0;i<=5;i++) {
      const px=left+i*width/5;
      svg.append(node('line',{x1:px,y1:top-4,x2:px,y2:height-12,class:'grid'}));
      svg.append(node('text',{x:px,y:20,class:'axis','text-anchor':i===0?'start':i===5?'end':'middle'},`${((start-bounds[0]+i/5*duration)*1000).toFixed(duration<.01?3:1)} ms`));
    }
    for(const lane of lanes) {
      const cy=y(lane);
      svg.append(node('rect',{x:left,y:cy-12,width,height:24,rx:3,fill:view==='thread'?'url(#unknown-pattern)':'#f5f7fa',class:view==='cpu'?'lane':''}));
      const label=node('text',{x:5,y:cy-2},view==='thread'?(names.get(lane)||'thread').slice(0,19):`CPU ${lane}`);
      const sub=node('text',{x:5,y:cy+12,class:'axis'},view==='thread'?`TID ${nativeThreads.get(lane)?.tid??lane}`:'');
      if(view==='thread') {
        label.style.cursor='pointer';label.setAttribute('role','button');label.setAttribute('tabindex','0');
        const choose=()=>{focus=focus===lane?null:lane;render();};label.onclick=choose;
        label.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}};
      }
      svg.append(label,sub);
    }
    for(const s of shown) {
      if(view==='cpu' && (s.state!=='running'||s.cpu==null||s.cpu===''))continue;
      const tid=M.threadKey(s),nativeTid=nativeThreads.get(tid)?.tid??tid,lane=view==='thread'?tid:Number(s.cpu);
      const a=Math.max(start,Number(s.start_s)),b=Math.min(end,Number(s.end_s));
      const key=`${tid}:${s.start_s}:${s.end_s}:${s.state}`;
      const relevant=!selectedJob||[Number(selectedJob.send_track_id??selectedJob.send_tid),Number(selectedJob.worker_track_id??selectedJob.worker_tid)].includes(tid);
      const block=node('rect',{x:x(a),y:y(lane)-10,width:Math.max(.7,x(b)-x(a)),height:20,rx:3,
        fill:view==='thread'?(M.colors[s.state]||M.colors.other):threadColor(tid),
        class:`slice${relevant?'':' dim'}${picked===key?' selected':''}`,role:'button',tabindex:'0','aria-pressed':String(picked===key),
        'aria-label':`TID ${nativeTid}, ${M.labels[s.state]||s.state}, ${((b-a)*1000).toFixed(3)} ms`});
      const choose=()=>{picked=key;render();dispatch({type:'scheduler',...s,start_s:Number(s.start_s),end_s:Number(s.end_s)});};
      block.onclick=choose;block.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}};
      svg.append(block);
      if(x(b)-x(a)>70)svg.append(node('text',{x:x(a)+6,y:y(lane)+3,fill:'#fff','pointer-events':'none',style:'fill:white;font-size:9px'},view==='thread'?(M.labels[s.state]||s.state):`TID ${nativeTid}`));
    }
    const position=(tid,t)=>{
      if(view==='thread')return lanes.includes(Number(tid))?Number(tid):null;
      const s=all.find(s=>M.threadKey(s)===Number(tid)&&s.state==='running'&&Number(s.start_s)<=t&&Number(s.end_s)>=t&&s.cpu!==''&&s.cpu!=null);
      return s&&lanes.includes(Number(s.cpu))?Number(s.cpu):null;
    };
    if($('showFlows').checked) {
      let jobs=selectedJob?[selectedJob]:data.jobs||[];
      if(!jobs.length) {
        const sends=new Map();jobs=[];
        for(const e of data.events||[]) {
          const key=`${e.pid}:${e.job_id}`;
          if(e.phase==='send')sends.set(key,e);
          if(e.phase==='receive'&&sends.has(key)) {
            const send=sends.get(key);jobs.push({pid:e.pid,job_id:e.job_id,send_tid:send.tid,worker_tid:e.tid,send_s:send.time_s,receive_s:e.time_s});
          }
        }
      }
      for(const j of jobs.slice(-25)) {
        const a=Number(j.send_s),b=Number(j.receive_s);
        if(a<start||b>end)continue;
        const from=position(j.send_track_id??j.send_tid,a),to=position(j.worker_track_id??j.worker_tid,b);if(from==null||to==null)continue;
        const path=node('path',{d:`M ${x(a)} ${y(from)-11} C ${x(a)+15} ${y(from)-29}, ${x(b)-15} ${y(to)-29}, ${x(b)} ${y(to)-11}`,class:'flow','marker-end':'url(#arrow-flow)',role:'button',tabindex:'0','aria-label':`Chuyển job ${j.job_id}`});
        path.onclick=()=>dispatch({type:'handoff',...j});
        path.onkeydown=e=>{if(e.key==='Enter')dispatch({type:'handoff',...j});};svg.append(path);
      }
    }
    if($('showWakeups').checked) {
      let count=0;
      for(const e of data.scheduler||[]) {
        const t=Number(e.time_s);if(!e.kind.startsWith('sched_wakeup')||t<start||t>end)continue;
        if(selectedJob && ![Number(selectedJob.worker_tid),Number(selectedJob.send_tid)].includes(Number(e.tid)))continue;
        const from=view==='thread'?Number(e.waker_tid):Number(e.cpu),to=view==='thread'?Number(e.tid):e.target_cpu;
        if(!lanes.includes(from)||!lanes.includes(to)||++count>50)continue;
        const path=node('path',{d:`M ${x(t)-6} ${y(from)} Q ${x(t)+20} ${Math.min(y(from),y(to))-25} ${x(t)+3} ${y(to)}`,class:'wake','marker-end':'url(#arrow-wake)',role:'button',tabindex:'0','aria-label':`Wakeup TID ${e.tid}`});
        path.onclick=()=>dispatch({type:'wakeup',...e});svg.append(path);
      }
    }
    if(!all.length) for(const e of data.events||[]) {
      const t=Number(e.time_s),lane=position(M.threadKey(e),t);if(t<start||t>end||lane==null)continue;
      const dot=node('circle',{cx:x(t),cy:y(lane),r:3,fill:'#8162ae',role:'button',tabindex:'0','aria-label':`${e.phase}, TID ${e.tid}`});
      dot.onclick=()=>dispatch({type:'application',...e});svg.append(dot);
    }
    if(view==='cpu'&&!shown.some(s=>s.state==='running'&&s.cpu!==''&&s.cpu!=null)) {
      const note=document.createElement('p');note.className='empty';note.textContent='Không ghi nhận app chạy trong cửa sổ này. Các CPU đã quan sát vẫn được giữ; chọn “Vừa trace” để xem lịch sử.';chart.append(note);
    }
    chart.append(svg);
  }
  function setData(snapshot,reset=false) {
    reset=reset||!!(data.name&&snapshot.name&&data.name!==snapshot.name);
    const wasActive=!!data.active;
    data=snapshot;bounds=calculateBounds();
    if(reset){picked=null;focus=null;fit=true;selectedJob=null;initialized=false;followLive=false;liveOrigin=null;$('rangeSummary').hidden=true;}
    if(data.active&&(!wasActive||reset)) {followLive=true;fit=false;duration=5;liveOrigin=null;$('windowSelect').value='5000';}
    const hasData=(data.timeline?.length||data.events?.length||data.scheduler?.length||data.jobs?.length);
    if(followLive) {
      if(liveOrigin==null&&hasData)liveOrigin=bounds[0];
      start=liveOrigin==null?bounds[0]:M.livePageStart(liveOrigin,bounds[1],duration);
      initialized=true;
    } else if(fit||!initialized){start=bounds[0];duration=bounds[1]-bounds[0];initialized=true;}
    render();
  }
  function zoom(factor,anchor=.5) {
    followLive=false;fit=false;const point=start+duration*anchor;
    duration*=factor;start=point-duration*anchor;$('windowSelect').value='custom';render();
  }
  function fitAll(){followLive=false;fit=true;start=bounds[0];duration=bounds[1]-bounds[0];$('windowSelect').value='fit';render();}
  function setJob(job,move=true) {
    selectedJob=job;
    if(job&&move){followLive=false;fit=false;const span=Math.max(.000001,Number(job.done_s)-Number(job.send_s));duration=span*1.15;start=Number(job.send_s)-span*.075;$('windowSelect').value='custom';}
    render();
  }
  function relative(clientX) {
    const svg=$('cpuChart').querySelector('svg');if(!svg)return 0;
    const rect=svg.getBoundingClientRect();return Math.max(0,Math.min(1,((clientX-rect.left)/rect.width*1080-left)/width));
  }
  $('threadTab').onclick=()=>{view='thread';$('threadTab').setAttribute('aria-selected','true');$('cpuTab').setAttribute('aria-selected','false');render();};
  $('cpuTab').onclick=()=>{view='cpu';$('threadTab').setAttribute('aria-selected','false');$('cpuTab').setAttribute('aria-selected','true');render();};
  $('zoomIn').onclick=()=>zoom(.5);$('zoomOut').onclick=()=>zoom(2);$('fitTrace').onclick=fitAll;
  $('followLive').onclick=()=>{if(fit)duration=5;follow();};
  $('clearFocus').onclick=()=>{focus=null;render();};
  $('showFlows').onchange=render;$('showWakeups').onchange=render;
  $('windowSelect').onchange=e=>{if(e.target.value==='fit')fitAll();else{fit=false;duration=Number(e.target.value)/1000;if(data.active)follow();else{followLive=false;start=bounds[1]-duration;render();}}};
  $('timeOffset').oninput=e=>{fit=false;const ratio=Number(e.target.value)/1000;if(ratio===1&&data.active){follow();return;}followLive=false;start=bounds[0]+ratio*Math.max(0,latestStart()-bounds[0]);render();};
  $('cpuChart').addEventListener('wheel',e=>{if(e.ctrlKey){e.preventDefault();zoom(e.deltaY<0?.8:1.25,relative(e.clientX));}},{passive:false});
  $('cpuChart').addEventListener('keydown',e=>{
    if(e.ctrlKey||e.metaKey||e.altKey)return;
    const k=e.key.toLowerCase();
    if(!['w','s','a','d','home'].includes(k))return;e.preventDefault();
    if(k==='w')zoom(.5);else if(k==='s')zoom(2);else if(k==='home')fitAll();
    else{followLive=false;fit=false;start+=duration*(k==='a'?-.2:.2);render();}
  });
  const chart=$('cpuChart');
  chart.addEventListener('pointerdown',e=>{
    if(e.button!==0||!chart.querySelector('svg'))return;
    drag={client:e.clientX,ratio:relative(e.clientX),start,duration,pan:e.shiftKey,moved:false};
    chart.setPointerCapture(e.pointerId);
  });
  chart.addEventListener('pointermove',e=>{
    if(!drag)return;
    if(Math.abs(e.clientX-drag.client)>4)drag.moved=true;
    if(drag.pan){followLive=false;fit=false;start=drag.start+(drag.ratio-relative(e.clientX))*drag.duration;render();}
    else if(drag.moved){
      const svg=chart.querySelector('svg');if(!svg)return;
      let selection=svg.querySelector('#range-selection');
      if(!selection){selection=node('rect',{id:'range-selection',y:top,height:svg.viewBox.baseVal.height-top-10,fill:'#18897522',stroke:'#188975','pointer-events':'none'});svg.append(selection);}
      const ratio=relative(e.clientX);selection.setAttribute('x',left+Math.min(drag.ratio,ratio)*width);selection.setAttribute('width',Math.abs(ratio-drag.ratio)*width);
    }
  });
  chart.addEventListener('pointerup',e=>{
    if(!drag)return;
    if(drag.moved&&!drag.pan){
      const a=drag.start+Math.min(drag.ratio,relative(e.clientX))*drag.duration,b=drag.start+Math.max(drag.ratio,relative(e.clientX))*drag.duration;
      const totals={};
      for(const s of segments()) {
        if(focus!=null&&M.threadKey(s)!==focus)continue;
        const overlap=Math.max(0,Math.min(b,Number(s.end_s))-Math.max(a,Number(s.start_s)))*1000;
        totals[s.state]=(totals[s.state]||0)+overlap;
      }
      const text=Object.entries(totals).filter(([,v])=>v>0).map(([key,v])=>`${M.labels[key]||key}: ${v.toFixed(3)} ms`).join(' · ');
      $('rangeSummary').textContent=`Vùng chọn ${( (b-a)*1000).toFixed(3)} ms · Tổng thời gian các thread${focus?' đã lọc':''}: ${text||'chưa có scheduler'}. Tổng các thread có thể lớn hơn độ dài vùng chọn.`;
      $('rangeSummary').hidden=false;
    }
    chart.querySelector('#range-selection')?.remove();
    if(chart.hasPointerCapture(e.pointerId))chart.releasePointerCapture(e.pointerId);
    // Pointer capture retargets clicks; explicit selection works for mouse and touch.
    if(!drag.moved&&!drag.pan){const target=document.elementFromPoint(e.clientX,e.clientY);if(target?.closest('svg'))target.dispatchEvent(new MouseEvent('click',{bubbles:false}));}
    drag=null;
  });
  chart.addEventListener('pointercancel',()=>{drag=null;chart.querySelector('#range-selection')?.remove();});
  return {setData,setJob,fitAll};
})();
