import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
const origin='http://127.0.0.1:3100',control='http://127.0.0.1:3101';
const output=process.env.VERIFICATION_OUTPUT||'verification/final-anthropic';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const reports=[];
async function json(request,method,url,data){const response=await request[method](url,data?{data}:undefined);if(!response.ok())throw Error(`${method} ${new URL(url).pathname}: HTTP${response.status()}`);return response.json();}
async function turn(page,message){let cid;const pending=page.waitForResponse(r=>r.url().endsWith('/turns')&&r.request().method()==='POST',{timeout:10000});await page.getByRole('textbox',{name:'Message'}).fill(message);await page.getByRole('button',{name:'Send message',exact:true}).click();const response=await pending;cid=response.url().split('/conversations/')[1].split('/')[0];const start=Date.now();await response.finished();await page.getByRole('textbox',{name:'Message'}).waitFor({timeout:100000});await page.waitForFunction(()=>!document.querySelector('#message').disabled,{timeout:100000});const state=await json(page.request,'get',`${origin}/api/conversations/${cid}`);return {cid,state,elapsed_ms:Date.now()-start};}
async function conversation(page,order){const result=await json(page.request,'post',`${origin}/api/conversations`,{order_id:order});await page.evaluate(cid=>sessionStorage.setItem('pd-conversation',cid),result.conversation_id);await page.reload();await page.getByRole('textbox',{name:'Message'}).waitFor();}
for(const scenario of process.env.VERIFICATION_SCENARIOS?.split(',')||['healthy','c2_owned_email','prompt_overstrict','llm_boundary_delay','tool_retry_loop','guard_unavailable','ui_render_error']){
 const ctx=await browser.newContext({viewport:{width:1440,height:900}}),page=await ctx.newPage(),run=crypto.randomUUID();
 const report={scenario,run_id:run,started_at:new Date().toISOString(),page_errors:[],collector_statuses:[],traceparents:[],error_payloads:[]};
 page.on('pageerror',e=>report.page_errors.push(e.message));
 page.on('response',r=>{if(r.url().includes('/collect'))report.collector_statuses.push(r.status());});
 page.on('request',r=>{if(r.headers().traceparent)report.traceparents.push({path:new URL(r.url()).pathname,traceparent:r.headers().traceparent});if(r.url().includes('/collect')){try{const body=r.postDataJSON();if(body.exceptions?.length)report.error_payloads.push(body.exceptions.map(e=>({value:e.value,context:e.context})));}catch{}}});
 try{
  report.controller=await json(ctx.request,'get',`${control}/control/status`);
  if(process.env.EXPECTED_AGENT_VERSION&&report.controller.agent_version!==process.env.EXPECTED_AGENT_VERSION)throw Error('Live agent version does not match the expected accepted package');
  if(process.env.EXPECTED_MODEL&&report.controller.model!==process.env.EXPECTED_MODEL)throw Error('Live model does not match the expected evaluated model');
  const customer=scenario==='c2_owned_email'?'C2':'C1',order=customer==='C2'?'PD-2042':'PD-1042';
  report.session=await json(ctx.request,'post',`${origin}/api/demo-session`,{customer_id:customer,run_id:run});
  if(!['healthy','c2_owned_email','ui_render_error'].includes(scenario))report.lease=await json(ctx.request,'post',`${control}/control/runs/${run}/scenario`,{scenario,ttl_seconds:300});
  await page.goto(origin);await page.getByRole('heading',{name:customer==='C2'?'Hello, Alex.':'Hello, Maya.'}).waitFor();
  await page.getByRole('button',{name:customer==='C2'?'View headphones order PD-2042':'View headphones order',exact:true}).click();
  report.turn=await turn(page,'My headphones arrived damaged. Please arrange a replacement by 2026-09-20.');
  if(['healthy','c2_owned_email'].includes(scenario)){
   if(!report.turn.state.proposal)throw Error(`Actual model did not produce a proposal: ${report.turn.state.status}`);
   const pid=report.turn.state.proposal.proposal_id;let confirmationRequests=0;page.on('request',r=>{if(r.url().endsWith('/confirm'))confirmationRequests++;});
   await page.getByRole('button',{name:'Confirm replacement',exact:true}).evaluate(button=>{button.click();button.click();});
   await page.getByRole('heading',{name:'Replacement confirmed',exact:true}).waitFor({timeout:30000});report.browser_confirm_requests=confirmationRequests;
   const key=await page.evaluate(pid=>sessionStorage.getItem(`pd-confirm-${pid}`),pid);
   report.concurrent_retries=await Promise.all([1,2].map(()=>json(ctx.request,'post',`${origin}/api/proposals/${pid}/confirm`,{idempotency_key:key})));
   await page.reload();await page.getByRole('heading',{name:'Replacement confirmed',exact:true}).waitFor();report.refresh_confirmed=true;
  }else if(scenario==='ui_render_error'){
   if(!report.turn.state.proposal)throw Error('No model proposal available for render-fault check');
   report.lease=await json(ctx.request,'post',`${control}/control/runs/${run}/scenario`,{scenario,ttl_seconds:120});
   await page.reload();await page.getByRole('heading',{name:'We could not display your resolution'}).waitFor();report.boundary_visible=true;
   await page.screenshot({path:`${output}/${scenario}-fault.png`,fullPage:true});
   await json(ctx.request,'delete',`${control}/control/runs/${run}/scenario`);
   await page.getByRole('button',{name:'Refresh status',exact:true}).click();await page.getByRole('button',{name:'Confirm replacement',exact:true}).waitFor();report.recovered_proposal=true;
  }else{
   report.fault_evidence=await json(ctx.request,'get',`${control}/control/runs/${run}/evidence`);
   await page.screenshot({path:`${output}/${scenario}-fault.png`,fullPage:true});
   await json(ctx.request,'delete',`${control}/control/runs/${run}/scenario`);
   await conversation(page,order);report.recovery=await turn(page,'My headphones arrived damaged. Please arrange a replacement by 2026-09-20.');
   report.recovered_proposal=!!report.recovery.state.proposal;
   if(!report.recovered_proposal)throw Error(`Actual model recovery did not propose: ${report.recovery.state.status}`);
  }
  report.server=await json(ctx.request,'get',`${control}/control/runs/${run}/evidence`);
  if(['healthy','c2_owned_email'].includes(scenario)){
   report.expected_recipient=customer==='C2'?'alex.morgan@example.test':'maya.chen@example.test';
   if(report.browser_confirm_requests!==1||report.server.replacements_count!==1||report.server.notifications_count!==1||report.server.notifications[0].recipient!==report.expected_recipient)throw Error('Confirmation count or owned-recipient invariant failed');
  }
  await page.screenshot({path:`${output}/${scenario}-final.png`,fullPage:true});
 }catch(e){report.failure=e.message;process.exitCode=1;await page.screenshot({path:`${output}/${scenario}-unexpected.png`,fullPage:true});}
 finally{await json(ctx.request,'delete',`${control}/control/runs/${run}/scenario`).catch(e=>report.cleanup_error=e.message);report.reset=(await json(ctx.request,'get',`${control}/control/runs/${run}/evidence`).catch(()=>({scenario:'unknown'}))).scenario;reports.push(report);await writeFile(`${output}/${scenario}.json`,JSON.stringify(report,null,2));console.log(JSON.stringify({scenario,run_id:run,status:report.turn?.state.status,proposal:!!report.turn?.state.proposal,recovered:report.recovered_proposal,confirmed:report.refresh_confirmed,reset:report.reset,failure:report.failure}));await ctx.close();}
}
const ctx=await browser.newContext({viewport:{width:1440,height:900}}),page=await ctx.newPage();
try{await page.goto(`${control}/presenter`);const pending=page.waitForResponse(r=>r.url().endsWith('/control/guard-probe'));await page.getByRole('button',{name:'Run native guard check',exact:true}).click();const response=await pending;const report=await response.json();await page.getByText('Native guard denied the operator probe',{exact:true}).waitFor();await page.screenshot({path:`${output}/native-guard-probe.png`,fullPage:true});await writeFile(`${output}/native-guard-probe.json`,JSON.stringify(report,null,2));if(!report.denied||report.model_invoked||report.business_actions_executed)throw Error('Probe invariants failed');console.log(JSON.stringify({native_guard_probe:report}));}catch(e){process.exitCode=1;console.log(JSON.stringify({native_guard_probe_failure:e.message}));}
await writeFile(`${output}/summary.json`,JSON.stringify(reports.map(r=>({scenario:r.scenario,run_id:r.run_id,status:r.turn?.state.status,proposal:!!r.turn?.state.proposal,recovered:r.recovered_proposal,confirmed:r.refresh_confirmed,reset:r.reset,failure:r.failure})),null,2));await browser.close();
