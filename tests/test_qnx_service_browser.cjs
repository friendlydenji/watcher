/* Explicit target integration: run a service with --wait-client and a finite
 * demo on the target first, then set WATCHER_QNX_URL to its address. */
const {chromium}=require('playwright');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const url=process.env.WATCHER_QNX_URL;if(!url)throw Error('Set WATCHER_QNX_URL for an explicitly started target service');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const snapshots=[];page.on('response',async r=>{if(r.url().endsWith('/api/live')&&r.ok())try{snapshots.push(await r.json());}catch{}});
  await page.goto(url);await page.locator('#cpuTab').click();
  let liveCPU=0,liveJobs=0,done;
  for(let i=0;i<45;i++){
   await page.waitForTimeout(400);
   const latest=snapshots.at(-1);
   if(latest?.active&&(await page.locator('#cpuChart .lane').count())>0)liveCPU++;
   if(latest?.active&&Number(await page.locator('#jobCount').innerText())>0)liveJobs++;
   if(liveCPU===3&&process.env.WATCHER_SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.WATCHER_SCREENSHOT_DIR,'watcher-qnx-service-live.png'),fullPage:true});
   if(latest?.phase==='failed')throw Error(latest.error);
   if(latest?.phase==='complete'){done=latest;break;}
  }
  assert.ok(liveCPU>=2,'CPU was not observed while target app was running');
  assert.ok(liveJobs>=2,'Jobs were not updated while target app was running');assert.ok(done,'target capture did not finish');
  const S=require('../ui/service-model.js'),data=S.normalize(done);
  assert.ok(data.jobs.length>0);assert.equal(data.jobs.filter(j=>j.status==='complete').length,data.jobs.length);
  assert.ok(data.threads.length<=4,'unrelated process threads leaked into the UI');assert.equal(done.error,null);
  assert.equal(await page.locator('.job-row').count(),data.jobs.length);
  const download=page.waitForEvent('download');await page.locator('#exportButton').click();
  assert.ok(JSON.parse(fs.readFileSync(await (await download).path(),'utf8')).traceEvents.length>0);
  assert.deepEqual(errors,[]);
  if(process.env.WATCHER_SCREENSHOT_DIR){await page.screenshot({path:path.join(process.env.WATCHER_SCREENSHOT_DIR,'watcher-qnx-service-complete.png'),fullPage:true});fs.writeFileSync(path.join(process.env.WATCHER_SCREENSHOT_DIR,'qnx-service-live-final.json'),JSON.stringify(done));}
  console.log(JSON.stringify({live_cpu_samples:liveCPU,live_job_samples:liveJobs,jobs:data.jobs.length,complete:data.jobs.filter(j=>j.status==='complete').length,events:done.events.length,transitions:done.transitions.length,threads:data.threads,cpus:data.cpus,phase:done.phase,js_errors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
