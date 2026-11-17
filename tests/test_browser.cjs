/* Optional end-to-end checks: npm install; npm run test:browser. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..');
(async()=>{
  const traces=fs.mkdtempSync(path.join(os.tmpdir(),'watcher-browser-'));
  fs.copyFileSync(path.join(root,'examples/traces/synthetic.jobs.json'),path.join(traces,'sample.jobs.json'));
  const qnxFixture=path.join(root,'traces/qnx71-final-native.jobs.json');
  if(fs.existsSync(qnxFixture))fs.copyFileSync(qnxFixture,path.join(traces,'qnx-real.jobs.json'));
  const server=spawn('python3',['-u','-c',
    'import sys; from pathlib import Path; sys.path.insert(0,"scripts"); import dashboard; dashboard.TRACES=Path(sys.argv[1]); dashboard.main(["--port","0"])',traces],{cwd:root});
  let browser;
  try {
    const url=await new Promise((resolve,reject)=>{
      let output='';const timer=setTimeout(()=>reject(new Error('server startup timed out')),10000);
      server.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127.0.0.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
      server.on('error',reject);server.on('exit',code=>reject(new Error(`server exited ${code}`)));
      server.stderr.on('data',data=>process.stderr.write(data));
    });
    const options={headless:true};
    if(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE)options.executablePath=process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
    browser=await chromium.launch(options);
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);await page.waitForSelector('.job-row');
    await page.locator('#traceSelect').selectOption('sample.jobs.json');
    await page.waitForFunction(()=>document.getElementById('jobCount').textContent==='24');
    assert.equal(await page.locator('.job-row').count(),24);
    assert.match(await page.locator('#traceStatus').innerText(),/MINH HỌA/);
    assert.equal(await page.locator('#rawPanel').getAttribute('open'),null);
    await page.locator('#selectSlowest').click();assert.equal(await page.locator('#detailTitle').innerText(),'Job #7');
    await page.locator('#cpuChart .slice').first().click();assert.equal(await page.locator('#sliceDetail').isVisible(),true);assert.equal(await page.locator('#cpuChart .slice.selected').count(),1);
    await page.locator('#cpuTab').click();assert.ok(await page.locator('#cpuChart .slice').count()>0);
    await page.locator('#threadTab').click();
    const previous=await page.locator('#offsetLabel').innerText();
    await page.locator('#cpuChart').focus();await page.keyboard.press('w');assert.notEqual(await page.locator('#offsetLabel').innerText(),previous);
    await page.locator('#fitTrace').click();
    const box=await page.locator('#cpuChart svg').boundingBox();
    await page.mouse.move(box.x+box.width*.3,box.y+55);await page.mouse.down();await page.mouse.move(box.x+box.width*.5,box.y+55,{steps:5});await page.mouse.up();
    assert.equal(await page.locator('#rangeSummary').isVisible(),true);
    await page.locator('#zoomIn').click();const beforePan=await page.locator('#offsetLabel').innerText();
    await page.keyboard.down('Shift');await page.mouse.move(box.x+box.width*.6,box.y+55);await page.mouse.down();await page.mouse.move(box.x+box.width*.4,box.y+55,{steps:5});await page.mouse.up();await page.keyboard.up('Shift');
    assert.notEqual(await page.locator('#offsetLabel').innerText(),beforePan);
    await page.locator('#fitTrace').click();
    await page.mouse.move(box.x+box.width*.6,box.y+55);await page.keyboard.down('Control');await page.mouse.wheel(0,-150);await page.keyboard.up('Control');
    assert.doesNotMatch(await page.locator('#offsetLabel').innerText(),/Toàn bộ/);
    await page.locator('#jobSearch').fill('3103');assert.equal(await page.locator('.job-row').count(),12);
    await page.locator('#jobSearch').fill('no-such-job');assert.equal(await page.locator('.job-row').count(),0);
    await page.locator('#jobSearch').fill('');
    const download=page.waitForEvent('download');await page.locator('#exportButton').click();
    const downloaded=await download;const exported=JSON.parse(fs.readFileSync(await downloaded.path(),'utf8'));assert.ok(exported.traceEvents.length>0);
    await page.locator('#traceSelect').selectOption('__live__');
    await page.waitForTimeout(600);assert.equal(await page.locator('.job-row').count(),0);
    assert.equal(await page.locator('#pauseButton').isVisible(),true);
    await page.locator('#traceSelect').selectOption('sample.jobs.json');await page.waitForSelector('.job-row');
    assert.equal(await page.locator('#windowSelect').inputValue(),'fit');
    // Fixed live pages: old slices keep their x position; new events fill to the right.
    const liveSlice=(a,b)=>({tid:12,comm:'test-worker',state:'running',cpu:0,start_s:a,end_s:b});
    let live={name:'direction.events.log',active:true,events:[],scheduler:[],thread_ids:[12],cpus:[0],
      timeline:[liveSlice(100,100.02),liveSlice(100.05,100.10)],jobs:[]};
    await page.route('**/api/live',route=>route.fulfill({json:live}));
    await page.locator('#traceSelect').selectOption('__live__');
    await page.waitForFunction(()=>document.querySelectorAll('#cpuChart .slice').length===2);
    assert.equal(await page.locator('#windowSelect').inputValue(),'5000');
    const oldX=Number(await page.locator('#cpuChart .slice').first().getAttribute('x'));
    live={...live,timeline:[...live.timeline,liveSlice(100.4,100.45)]};
    await page.waitForFunction(()=>document.querySelectorAll('#cpuChart .slice').length===3);
    assert.equal(Number(await page.locator('#cpuChart .slice').first().getAttribute('x')),oldX);
    assert.ok(Number(await page.locator('#cpuChart .slice').last().getAttribute('x'))>oldX);
    await page.locator('#cpuTab').click();
    assert.equal(await page.locator('#cpuChart .lane').count(),1);
    live={...live,timeline:[...live.timeline,liveSlice(105.15,105.2)]};
    await page.waitForFunction(()=>document.querySelectorAll('#cpuChart .slice').length===1);
    assert.match(await page.locator('#offsetLabel').innerText(),/5000.00 → 10000.00/);
    assert.equal(await page.locator('#cpuChart .lane').count(),1);
    await page.locator('#timeOffset').fill('0');
    assert.equal(await page.locator('#cpuChart .slice').count(),3);
    assert.equal(await page.locator('#followLive').isEnabled(),true);
    live={...live,timeline:[...live.timeline,liveSlice(106,106.1)]};
    await page.waitForTimeout(650);
    assert.equal(Number(await page.locator('#cpuChart .slice').first().getAttribute('x')),oldX);
    await page.locator('#timeOffset').fill('1000');
    assert.equal(await page.locator('#cpuChart .slice').count(),2);
    assert.equal(await page.locator('#followLive').isEnabled(),false);
    await page.locator('#timeOffset').fill('0');
    await page.locator('#followLive').click();
    assert.equal(await page.locator('#cpuChart .slice').count(),2);
    // A requested live window keeps its full width even before that much data exists.
    await page.locator('#windowSelect').selectOption('2000');
    assert.match(await page.locator('#cpuSubtitle').innerText(),/2000.00 ms/);
    await page.locator('#traceSelect').selectOption('sample.jobs.json');
    await page.waitForSelector('.job-row');
    await page.locator('#threadTab').click();
    const output=process.env.WATCHER_SCREENSHOT_DIR;
    if(output){fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,'watcher-ui-desktop.png'),fullPage:true});}
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    if(output)await page.screenshot({path:path.join(output,'watcher-ui-mobile.png'),fullPage:true});
    if(fs.existsSync(qnxFixture)){
      await page.locator('#traceSelect').selectOption('qnx-real.jobs.json');
      await page.waitForFunction(()=>document.getElementById('jobCount').textContent==='20');
      await page.locator('#cpuTab').click();
      assert.ok(await page.locator('#cpuChart .slice').count()>0);
      assert.match(await page.locator('#metrics').innerText(),/Chưa đo/);
      assert.match(await page.locator('#detailIdentity').innerText(),/Worker TID 2/);
      if(output)await page.screenshot({path:path.join(output,'watcher-qnx-real.png'),fullPage:true});
    }
    assert.deepEqual(errors,[]);
    // Endpoint regression checks: selected source isolation and traversal guard.
    for(const endpoint of ['data','export'])assert.equal((await page.request.get(`${url}/api/${endpoint}?name=..%2Fsecret.jobs.json`)).status(),400);
    assert.equal((await page.request.get(`${url}/api/data?name=missing.jobs.json`)).status(),404);
    console.log('Browser: selection, source isolation, search, thread/CPU, details, keyboard/mouse zoom, pan, range, export, mobile, left-to-right live pages/history, API guards passed');
  } finally {
    if(browser)await browser.close();server.kill('SIGTERM');fs.rmSync(traces,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
