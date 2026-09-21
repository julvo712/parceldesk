import {chromium} from 'playwright';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
const saved=JSON.parse(await readFile('verification/live/evidence.json','utf8'));
const run=saved.run_id,cid=saved.server.proposals[0].conversation_id;
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage();
const evidence={run_id:run,conversation_id:cid,collector_statuses:[],error_payloads:[],boundary_visible:false,recovered:false};
page.on('request',r=>{if(r.url().includes('/collect')){try{const body=r.postDataJSON();if(body.exceptions?.length)evidence.error_payloads.push(body.exceptions.map(e=>({type:e.type,value:e.value,context:e.context})));}catch{}}});
page.on('response',r=>{if(r.url().includes('/collect'))evidence.collector_statuses.push(r.status());});
await context.addInitScript(({run,cid})=>{sessionStorage.setItem('pd-run',run);sessionStorage.setItem('pd-conversation',cid);},{run,cid});
await mkdir('verification/live-ui-error',{recursive:true});
try{
 const response=await context.request.post(`http://127.0.0.1:3101/control/runs/${run}/scenario`,{data:{scenario:'ui_render_error',ttl_seconds:120}});if(!response.ok())throw Error(`scenario HTTP${response.status()}`);
 await page.goto(`http://127.0.0.1:3100/?run=${run}`);
 await page.getByRole('heading',{name:'We could not display your resolution'}).waitFor({timeout:15000});evidence.boundary_visible=true;
 await page.screenshot({path:'verification/live-ui-error/failure.png',fullPage:true});
 await context.request.delete(`http://127.0.0.1:3101/control/runs/${run}/scenario`);
 await page.getByRole('button',{name:'Refresh status',exact:true}).click();
 await page.getByRole('heading',{name:'Replacement confirmed'}).waitFor({timeout:10000});evidence.recovered=true;
 await page.screenshot({path:'verification/live-ui-error/recovered.png',fullPage:true});
 // Observe an actual collector delivery after the caught error, bounded to five seconds.
 if(!evidence.error_payloads.length) await page.waitForRequest(r=>r.url().includes('/collect')&&!!r.postData()?.includes('Resolution panel render failed'),{timeout:5000}).catch(()=>{});
 if(!evidence.collector_statuses.length)await page.waitForResponse(r=>r.url().includes('/collect')&&r.status()===202,{timeout:5000});
}catch(e){evidence.failure=e.message;process.exitCode=1;await page.screenshot({path:'verification/live-ui-error/unexpected.png',fullPage:true});}
finally{await context.request.delete(`http://127.0.0.1:3101/control/runs/${run}/scenario`);await writeFile('verification/live-ui-error/evidence.json',JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2));await browser.close();}
