import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';

const origin='http://127.0.0.1:3100',control='http://127.0.0.1:3101';
const output='verification/final-anthropic',run=crypto.randomUUID();
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const ctx=await browser.newContext({viewport:{width:1440,height:900}}),page=await ctx.newPage();
const report={scenario:'prompt_overstrict',configuration:'replacement-policy-with-no-tools',run_id:run,started_at:new Date().toISOString()};
async function json(method,url,data){const r=await ctx.request[method](url,data?{data}:undefined);if(!r.ok())throw Error(`${method} ${url}: HTTP ${r.status()}`);return r.json();}
async function turn(message){
 const pending=page.waitForResponse(r=>r.url().endsWith('/turns'));
 await page.getByRole('textbox',{name:'Message'}).fill(message);await page.getByRole('button',{name:'Send message',exact:true}).click();
 const response=await pending;await response.finished();await page.waitForFunction(()=>!document.querySelector('#message').disabled,{timeout:100000});
 const cid=response.url().split('/conversations/')[1].split('/')[0];return {cid,state:await json('get',`${origin}/api/conversations/${cid}`)};
}
try{
 report.controller=await json('get',`${control}/control/status`);
 await json('post',`${origin}/api/demo-session`,{customer_id:'C1',run_id:run});
 report.lease=await json('post',`${control}/control/runs/${run}/scenario`,{scenario:'prompt_overstrict',ttl_seconds:300});
 await page.goto(origin);await page.getByRole('button',{name:'View headphones order',exact:true}).click();
 report.fault=await turn('My headphones arrived damaged. Please arrange a replacement by 2026-09-20.');
 report.fault_evidence=await json('get',`${control}/control/runs/${run}/evidence`);
 await page.screenshot({path:`${output}/prompt_overstrict-configured-fault.png`,fullPage:true});
 if(report.fault.state.proposal||report.fault_evidence.attempts_count!==0||report.fault_evidence.proposals_count!==0)throw Error('Overstrict configuration exposed a proposal or tool call');
 report.refusal_observed=report.fault.state.messages.some(m=>m.role==='assistant'&&/human|support|policy|unable|cannot|can.t|untrusted/i.test(m.content));
 if(!report.refusal_observed)throw Error('Actual generation did not contain a recognizable refusal');
 await json('delete',`${control}/control/runs/${run}/scenario`);
 const convo=await json('post',`${origin}/api/conversations`,{order_id:'PD-1042'});
 await page.evaluate(cid=>sessionStorage.setItem('pd-conversation',cid),convo.conversation_id);await page.reload();
 report.recovery=await turn('My headphones arrived damaged. Please arrange a replacement by 2026-09-20.');
 if(!report.recovery.state.proposal){
  report.first_recovery_failure='Actual model did not create a proposal';
  report.followup_recovery=await turn('I don’t see a replacement proposal yet. Please prepare it for me so I can review and confirm.');
 }
 report.recovered_proposal=!!(report.followup_recovery||report.recovery).state.proposal;
 if(!report.recovered_proposal)throw Error('Actual model did not recover a proposal after reset and followup');
 await page.screenshot({path:`${output}/prompt_overstrict-configured-recovery.png`,fullPage:true});
}catch(e){report.failure=e.message;process.exitCode=1;}
finally{
 await json('delete',`${control}/control/runs/${run}/scenario`).catch(e=>report.cleanup_error=e.message);
 report.final_evidence=await json('get',`${control}/control/runs/${run}/evidence`);report.reset=report.final_evidence.scenario;
 await writeFile(`${output}/prompt_overstrict-configured.json`,JSON.stringify(report,null,2));
 console.log(JSON.stringify({run_id:run,refusal:report.refusal_observed,recovered:report.recovered_proposal,reset:report.reset,failure:report.failure}));await browser.close();
}
