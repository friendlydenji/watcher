/* Explicit real-kernel integration check; never part of make test or CI. */
if(process.env.WATCHER_RUN_KERNEL_TESTS!=='1')throw new Error('Set WATCHER_RUN_KERNEL_TESTS=1 to authorize a private kernel trace');
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
(async()=>{
  const server=spawn('python3',['-u','scripts/dashboard.py','--port','0'],{cwd:root});
  let browser,capture;
  try {
    const url=await new Promise((resolve,reject)=>{
      server.stdout.on('data',b=>{const match=String(b).match(/http:\/\/127.0.0.1:\d+/);if(match)resolve(match[0]);});server.on('error',reject);
    });
    browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);await page.locator('#traceSelect').selectOption('__live__');await page.locator('#cpuTab').click();
    capture=spawn('./scripts/live-app.sh',['6','./demo/mixed_demo','4'],{cwd:root});
    let captureOutput='',captureError='';capture.stdout.on('data',b=>captureOutput+=b);capture.stderr.on('data',b=>captureError+=b);
    const done=new Promise((resolve,reject)=>{capture.on('exit',code=>code===0?resolve():reject(new Error(captureOutput+'\n'+captureError)));capture.on('error',reject);});
    done.catch(()=>{});
    let populated=false,samples=0;
    for(let i=0;i<22;i++) {
      await page.waitForTimeout(400);
      const status=await page.locator('#traceStatus').innerText();
      const cpuRows=await page.locator('#cpuChart text').filter({hasText:/^CPU \d+$/}).count();
      if((await page.locator('#liveBadge').getAttribute('class')).includes('active') && cpuRows>0){populated=true;samples++;}
      if(populated)assert.ok(cpuRows>0,'CPU rows disappeared after first live data');
      if(populated && samples===3 && process.env.WATCHER_SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.WATCHER_SCREENSHOT_DIR,'watcher-live-real.png'),fullPage:true});
    }
    await done;
    assert.ok(populated && samples>=2,'did not observe live CPU rows while app was running');
    await page.waitForFunction(()=>document.getElementById('traceSelect').value!=='__live__',{timeout:15000});
    await page.waitForSelector('.job-row',{timeout:15000});
    const completed=Number(captureOutput.match(/main submitted=(\d+)/)?.[1]);
    assert.ok(completed>0);assert.equal(await page.locator('.job-row').count(),completed);
    assert.ok(await page.locator('#cpuChart .slice').count()>0);
    assert.deepEqual(errors,[]);
    console.log('REAL KERNEL + BROWSER: live CPU rows present on',samples,'polls; retained after app end; replay matches the app job count; no JS errors');
    console.log(captureOutput.trim());
  } finally {
    if(capture && capture.exitCode===null)capture.kill('SIGTERM');
    if(browser)await browser.close();server.kill('SIGTERM');
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
