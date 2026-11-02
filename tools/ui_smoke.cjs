'use strict';
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'borrowcheck-ui-'));
 const server=spawn(process.env.PYTHON || 'python',['-m','borrowcheck','serve','--port','0','--audit-db',path.join(temp,'audit.sqlite')],{stdio:['ignore','pipe','pipe']});
 let browser;
 try {
  const url=await new Promise((resolve,reject)=>{
   const timeout=setTimeout(()=>reject(new Error('Local server startup timed out')),10000);
   server.once('error',reject);server.once('exit',code=>reject(new Error(`Server exited ${code}`)));
   server.stdout.on('data',chunk=>{const match=chunk.toString().match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timeout);resolve(match[0]);}});
  });
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1080}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForSelector('#invoice-rows tr');
  if(!(await page.locator('#metrics').innerText()).includes('$478,000.00'))throw Error('Wrong base');
  fs.mkdirSync('outputs/ui',{recursive:true});
  await page.screenshot({path:'outputs/ui/reconciliation.png',fullPage:true});
  await page.locator('[data-tab="evidence"]').click();
  await page.locator('.source-button').first().click();
  if(!(await page.locator('#source-text mark').innerText()).length)throw Error('Source not highlighted');
  await page.locator('#close-source').click();
  await page.screenshot({path:'outputs/ui/evidence.png',fullPage:true});
  await page.locator('[data-tab="tests"]').click();
  await page.waitForFunction(()=>document.querySelector('#test-summary').textContent.includes('10 / 10'));
  await page.locator('[data-tab="overview"]').click();
  await page.locator('#case-select').selectOption('09_missing_reserve');
  await page.waitForFunction(()=>document.querySelector('#metrics').textContent.includes('Withheld'));
  if(!(await page.locator('#signoff').isDisabled()))throw Error('Blocked review enabled');
  await page.locator('#case-select').selectOption('04_worked');
  await page.waitForFunction(()=>!document.querySelector('#signoff').disabled);
  await page.locator('#run').click();
  await page.waitForFunction(()=>!document.querySelector('#run').disabled);
  await page.locator('#reviewer').fill('Demo reviewer');
  await page.locator('#review-note').fill('Synthetic UI verification: compared source terms and totals.');
  await page.locator('#signoff').click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Local review recorded'));
  await page.locator('[data-tab="audit"]').click();
  await page.waitForFunction(()=>document.querySelector('#audit-events').textContent.includes('LOCAL_DEMO_SIGNOFF'));
  await page.setViewportSize({width:390,height:844});
  await page.locator('[data-tab="overview"]').click();
  await page.screenshot({path:'outputs/ui/mobile.png',fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  const report={desktop:true,mobile:true,source_highlight:true,blocked_review:true,signoff:true,acceptance_cases:10,console_errors:errors,horizontal_page_overflow:overflow};
  fs.writeFileSync('outputs/ui/report.json',JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
  if(errors.length||overflow)throw Error('Browser smoke checks failed');
 } finally {
  if(browser)await browser.close();
  server.kill();await new Promise(resolve=>server.once('exit',resolve));
  fs.rmSync(temp,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
