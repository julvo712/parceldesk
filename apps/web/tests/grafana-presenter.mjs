// Requires explicit approval to grant local-network permission in this temporary browser context.
import {chromium} from 'playwright';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {writeFile,mkdir} from 'node:fs/promises';
const execFileAsync=promisify(execFile);
if(process.env.PRESENTER_TEST_LOCAL_NETWORK_PERMISSION!=='1')throw Error('Local-network browser permission needs explicit approval. Set PRESENTER_TEST_LOCAL_NETWORK_PERMISSION=1 only after approval.');
const origin='https://demotests.grafana.net',context='demotests_gcloud';
const root=new URL('../../../',import.meta.url),out=new URL('infra/grafana/evidence/presenter/',root);await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const ctx=await browser.newContext({viewport:{width:1440,height:1100}});
await ctx.grantPermissions(['local-network-access'],{origin});
// Real Cloud responses via the existing authorized context. No new accounts, permission
// changes, fabricated responses or localhost interception. Normal UI actions remain native.
await ctx.route(origin+'/**',async route=>{
 const req=route.request(),url=new URL(req.url());
 const document=req.resourceType()==='document'&&url.pathname.startsWith('/d/');
 const query=url.pathname==='/api/ds/query'||/^\/apis\/query\.grafana\.app\/[^/]+\/namespaces\/[^/]+\/query$/.test(url.pathname);
 if(!document&&url.pathname!=='/bootdata'&&!/^\/apis?\//.test(url.pathname))return route.continue();
 if(req.method()!=='GET'&&!(req.method()==='POST'&&query))return route.continue();
 try{
  const args=['--context',context,'api',url.pathname+url.search];
  if(req.method()==='POST')args.push('-d',req.postData());
  const {stdout}=await execFileAsync('gcx',args,{maxBuffer:12*1024*1024});
  await route.fulfill({status:200,contentType:document?'text/html':'application/json',body:stdout});
 }catch(error){report.relay_errors.push({path:url.pathname,message:(error.stderr||error.message).slice(0,600)});await route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({message:'gcx verification relay failed'})});}
});
const page=await ctx.newPage(),report={checked_at:new Date().toISOString(),authentication:'existing gcx read/query relay; no Grafana permission changes',local_network_permission:'explicitly approved; temporary browser context only',actions:[],cloud:[],errors:[],relay_errors:[]};
page.on('requestfailed',r=>{if(r.url().startsWith('http://localhost:3101'))report.errors.push({url:r.url(),error:r.failure()?.errorText});});
async function action(button,index,expected){
 await page.getByRole('button',{name:button,exact:true}).nth(index).click();
 const pending=page.waitForResponse(r=>r.url().includes('/control/presenter/command')&&r.request().method()==='POST',{timeout:20000});
 await page.getByRole('button',{name:'Confirm',exact:true}).click();
 const response=await pending,result=await response.json();
 report.actions.push({command:expected,status:response.status(),body:response.request().postDataJSON(),result});
 if(response.status()!==200||result.status!=='verified')throw Error(`${expected} failed: ${response.status()}`);
 console.log(JSON.stringify({action:expected,status:result.status,scenario:result.controller.scenario,run_id:result.controller.run_id}));
 return result;
}
async function cloud(result){
 const {run_id,scenario,observed_at}=result.controller;
 const expr=`parceldesk_presenter_info{run_id="${run_id}",scenario="${scenario}"} and on() (parceldesk_presenter_observed_seconds >= ${observed_at})`;
 for(let i=0;i<12;i++){
  const {stdout}=await execFileAsync('gcx',['--context',context,'metrics','query','-d','grafanacloud-prom',expr,'-o','json']);
  const value=JSON.parse(stdout);if(value.data?.result?.length){report.cloud.push({run_id,scenario,verified:true,query:expr,result:value});return;}
  await new Promise(r=>setTimeout(r,4000));
 }
 throw Error('Fresh controller state did not arrive in Cloud: '+scenario);
}
try{
 await page.goto(origin+'/d/pd-presenter?from=now-30m&to=now',{waitUntil:'domcontentloaded'});
 await page.getByText('Run controls',{exact:true}).waitFor({timeout:45000});
 await page.getByRole('button',{name:'Run',exact:true}).first().waitFor({timeout:30000});
 const created=await action('Run',0,'new_run');await cloud(created);
 // Resolve the actual customer link at click time, including when an older session exists.
 const href=await page.getByRole('link',{name:'Open customer experience',exact:true}).getAttribute('href');
 const customer=await ctx.newPage();await customer.goto(new URL(href,origin).href);await customer.getByRole('heading',{name:'Hello, Maya.'}).waitFor();
 const session=await (await customer.request.get('http://localhost:3100/api/session')).json();
 if(session.run_id!==created.controller.run_id)throw Error('Customer link selected another run');
 report.customer_run_matches=true;await customer.close();
 const on=await action('Activate',0,'supplier_injection');await cloud(on);
 await page.getByText('supplier_injection',{exact:true}).first().waitFor({timeout:30000});
 await page.getByText('Prompt injection',{exact:true}).waitFor({timeout:20000});
 await page.screenshot({path:new URL('browser-active.png',out).pathname,fullPage:true});
 const off=await action('Run',1,'reset');await cloud(off);
 const probe=await action('Run',2,'guard_probe');
 if(!probe.result.denied||probe.result.model_invoked||probe.result.business_actions_executed)throw Error('Native guard probe invariants failed');
 await action('Run',3,'refresh');
 await page.getByText('healthy',{exact:true}).first().waitFor({timeout:30000});
 await page.screenshot({path:new URL('browser-verified.png',out).pathname,fullPage:true});
 report.passed=true;
}catch(e){report.passed=false;report.failure=e.message;await page.screenshot({path:new URL('browser-failure.png',out).pathname,fullPage:true});throw e;}
finally{
 // Always clear the fault created by this test; preserve all evidence and the selected run.
 const cleanup=await fetch('http://localhost:3101/control/presenter/command',{method:'POST',headers:{Origin:origin,'X-Grafana-Action':'1','Content-Type':'application/json'},body:JSON.stringify({command:'reset'})});
 report.cleanup=await cleanup.json();
 await writeFile(new URL('browser-verification.json',out),JSON.stringify(report,null,2));
 await browser.close();
}
