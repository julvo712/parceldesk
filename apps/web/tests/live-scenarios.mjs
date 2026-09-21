import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const origin=process.env.PARCELDESK_URL||'http://127.0.0.1:3100', control=process.env.PARCELDESK_CONTROL_URL||'http://127.0.0.1:3101';
const reports=[];await mkdir('verification/live-scenarios',{recursive:true});
for(const scenario of ['supplier_injection','guard_unavailable']){
 const context=await browser.newContext({viewport:{width:1440,height:900}}), consolePage=await context.newPage();
 const report={scenario,errors:[],collector_responses:[]};
 let run;
 try{
  const response=await context.request.post(`${control}/control/runs`,{data:{fixture_revision:'v1'}});run=(await response.json()).run_id;report.run_id=run;
  await consolePage.goto(`${control}/presenter`);await consolePage.getByText(run,{exact:true}).waitFor();
  await consolePage.getByLabel('Choose the investigation').selectOption(scenario);await consolePage.getByRole('button',{name:'Activate scenario',exact:true}).click();
  await consolePage.getByText(new RegExp(`${scenario} active`)).waitFor();
  await consolePage.screenshot({path:`verification/live-scenarios/${scenario}-console.png`,fullPage:true});
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));page.on('response',r=>{if(r.url().includes('/collect'))report.collector_responses.push(r.status());});
  await page.goto(`${origin}/?run=${encodeURIComponent(run)}`);await page.getByRole('button',{name:'View headphones order',exact:true}).click();
  await page.getByRole('textbox',{name:'Message'}).fill('My headphones arrived damaged. Can you arrange a replacement before September 19?');await page.getByRole('button',{name:'Send message'}).click();
  await Promise.race([page.getByText('Your information stays protected.',{exact:true}).waitFor({timeout:90000}),page.getByRole('button',{name:'Confirm replacement',exact:true}).waitFor({timeout:90000})]);
  report.blocked=await page.getByText('Your information stays protected.',{exact:true}).isVisible();report.proposal_visible=await page.getByRole('button',{name:'Confirm replacement',exact:true}).isVisible();
  await page.screenshot({path:`verification/live-scenarios/${scenario}-customer.png`,fullPage:true});
  const evidence=await context.request.get(`${control}/control/runs/${run}/evidence`);report.server=await evidence.json();
  await consolePage.getByRole('button',{name:'Reset & verify',exact:true}).click();await consolePage.getByRole('button',{name:'Activate scenario',exact:true}).waitFor({state:'visible'});
  const healthy=await context.request.get(`${control}/control/runs/${run}/evidence`);report.reset_scenario=(await healthy.json()).scenario;
 }catch(error){report.failure=error.message;process.exitCode=1;await consolePage.screenshot({path:`verification/live-scenarios/${scenario}-failure.png`,fullPage:true});}
 finally{if(run)await context.request.delete(`${control}/control/runs/${run}/scenario`);reports.push(report);await context.close();}
}
await writeFile('verification/live-scenarios/evidence.json',JSON.stringify(reports,null,2));console.log(JSON.stringify(reports.map(({server,...r})=>({...r,attempts:server?.attempts_count,replacements:server?.replacements_count,notifications:server?.notifications_count})),null,2));await browser.close();
