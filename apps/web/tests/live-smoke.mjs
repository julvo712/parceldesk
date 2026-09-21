import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
const origin=process.env.PARCELDESK_URL || 'http://127.0.0.1:3100';
const control=process.env.PARCELDESK_CONTROL_URL || 'http://127.0.0.1:3101';
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const context=await browser.newContext({viewport:{width:1440,height:900}});
const page=await context.newPage();
const evidence={timestamp:new Date().toISOString(),run_id:null,traceparent_requests:[],collector_responses:[],errors:[],confirmed:false,refresh_confirmed:false};
page.on('request',r=>{if(r.url().includes('/api/')&&r.headers().traceparent)evidence.traceparent_requests.push({path:new URL(r.url()).pathname,traceparent:r.headers().traceparent});});
page.on('response',r=>{if(r.url().includes('/collect'))evidence.collector_responses.push(r.status());});
page.on('pageerror',e=>evidence.errors.push(e.message));
await mkdir('verification/live',{recursive:true});
try {
  const run=await context.request.post(`${control}/control/runs`,{data:{fixture_revision:'v1'}});
  if(!run.ok())throw new Error(`Create run: HTTP ${run.status()}`);
  const data=await run.json();evidence.run_id=data.run_id;
  await page.goto(`${origin}/?run=${encodeURIComponent(data.run_id)}`);
  await page.getByRole('button',{name:'View headphones order',exact:true}).click({timeout:20000});
  await page.getByRole('textbox',{name:'Message'}).fill('My headphones arrived damaged. Can you arrange a replacement before September 19?');
  await page.getByRole('button',{name:'Send message'}).click();
  await page.getByRole('button',{name:'Confirm replacement',exact:true}).waitFor({timeout:90000});
  await page.screenshot({path:'verification/live/proposal.png',fullPage:true});
  await page.getByRole('button',{name:'Confirm replacement',exact:true}).click();
  await page.getByRole('heading',{name:'Replacement confirmed'}).waitFor({timeout:30000});evidence.confirmed=true;
  await page.reload();await page.getByRole('heading',{name:'Replacement confirmed'}).waitFor({timeout:10000});evidence.refresh_confirmed=true;
  await page.screenshot({path:'verification/live/confirmed.png',fullPage:true});
  const response=await context.request.get(`${control}/control/runs/${data.run_id}/evidence`);evidence.server=await response.json();
} catch(error){evidence.failure=error.message;await page.screenshot({path:'verification/live/failure.png',fullPage:true});process.exitCode=1;}
finally{await writeFile('verification/live/evidence.json',JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2));await browser.close();}
