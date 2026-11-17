const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn,execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'watcher-service-'));
 const fixture=path.join(temp,'feed.txt'),binary=path.join(temp,'watcher-service');fs.writeFileSync(fixture,'');
 execFileSync('cc',['-O2','-std=c11','-Wall','-Wextra','-Wpedantic','-Werror','-pthread','service/watcher_service.c','-o',binary],{cwd:root});
 const server=spawn(binary,['--listen','127.0.0.1','--port','0','--ui',path.join(root,'ui'),'--capture-dir',temp,'--fixture',fixture]);
 let browser;
 try{
  const url=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('startup timeout')),10000);server.stdout.on('data',b=>{const m=String(b).match(/http:\/\/127.0.0.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});server.on('error',reject);});
  browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForFunction(()=>document.getElementById('traceSelect').value==='__live__');
  const m=(phase,t,tid)=>`LTI_EVENT mono_ns=${t} tid=${tid} pid=10 job=18446744073709551615 phase=${phase} v=1 resource=0\n`;
  fs.appendFileSync(fixture,m('send','100000000001',1)+m('receive','100001000001',2)+'STATE 100001000001 10 2 0 running\nSTATE 100002000001 10 2 0 runnable\n');
  await page.waitForFunction(()=>document.querySelectorAll('#cpuChart .slice').length>0);
  await page.locator('#cpuTab').click();assert.equal(await page.locator('#cpuChart .lane').count(),1);
  fs.appendFileSync(fixture,'STATE 100003000001 10 2 0 sleeping\nSTATE 100004000001 10 2 0 running\n'+m('done','100004000001',2));
  await page.waitForFunction(()=>document.getElementById('jobCount').textContent==='1');
  assert.match(await page.locator('#detailTitle').innerText(),/18446744073709551615/);
  assert.match(await page.locator('#detailStatus').innerText(),/ĐỦ DỮ LIỆU/);
  assert.match(await page.locator('#metrics').innerText(),/Chưa đo/);
  const download=page.waitForEvent('download');await page.locator('#exportButton').click();
  const exported=JSON.parse(fs.readFileSync(await (await download).path(),'utf8'));assert.ok(exported.traceEvents.some(e=>e.ph==='X'));
  assert.equal((await page.request.get(url+'/api/live')).status(),200);
  assert.equal((await page.request.get(url+'/%2e%2e/README.md')).status(),404);
  assert.equal((await page.request.post(url+'/api/live')).status(),405);
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(errors,[]);console.log('Native service + browser: incremental CPU, live jobs, uint64 IDs, export, HTTP guards and mobile passed');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(resolve=>{if(server.exitCode!==null)resolve();else server.on('exit',resolve);});fs.rmSync(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
