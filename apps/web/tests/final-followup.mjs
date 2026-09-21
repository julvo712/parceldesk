import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
const output='verification/final-anthropic',origin='http://127.0.0.1:3100',control='http://127.0.0.1:3101';
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
for(const scenario of ['llm_boundary_delay','guard_unavailable']){
 const file=`${output}/${scenario}.json`,report=JSON.parse(await readFile(file,'utf8'));
 const ctx=await browser.newContext({viewport:{width:1440,height:900}}),page=await ctx.newPage();
 try{
  await ctx.request.post(`${origin}/api/demo-session`,{data:{customer_id:'C1',run_id:report.run_id}});
  await ctx.addInitScript(cid=>sessionStorage.setItem('pd-conversation',cid),report.recovery.cid);
  await page.goto(origin);await page.getByRole('textbox',{name:'Message'}).waitFor();
  const response=page.waitForResponse(r=>r.url().endsWith('/turns'));
  await page.getByRole('textbox',{name:'Message'}).fill('I don’t see a replacement proposal yet. Please prepare it for me so I can review and confirm.');await page.getByRole('button',{name:'Send message'}).click();await (await response).finished();await page.waitForFunction(()=>!document.querySelector('#message').disabled);
  report.followup_recovery=await (await ctx.request.get(`${origin}/api/conversations/${report.recovery.cid}`)).json();report.final_recovered_proposal=!!report.followup_recovery.proposal;
  await page.screenshot({path:`${output}/${scenario}-followup-recovery.png`,fullPage:true});
  report.final_server=await (await ctx.request.get(`${control}/control/runs/${report.run_id}/evidence`)).json();
 }catch(e){report.followup_error=e.message;process.exitCode=1;}
 finally{await writeFile(file,JSON.stringify(report,null,2));console.log(JSON.stringify({scenario,first_attempt_failure:report.failure,followup_recovered:report.final_recovered_proposal,error:report.followup_error}));await ctx.close();}
}
await browser.close();
