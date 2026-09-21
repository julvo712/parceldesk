#!/usr/bin/env python3
"""One real, bounded synthetic customer journey; no model response fixtures."""
import argparse,http.cookiejar,json,pathlib,time,urllib.request,uuid
ROOT=pathlib.Path(__file__).resolve().parents[1]
def run(base='http://127.0.0.1:3100',output=None):
 opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def request(method,path,data=None):
  req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method)
  with opener.open(req,timeout=100) as response:return response.read().decode()
 start=time.monotonic();session=json.loads(request('POST','/api/demo-session',{'customer_id':'C1'}));conversation=json.loads(request('POST','/api/conversations',{'order_id':'PD-1042'}));cid=conversation['conversation_id']
 stream=request('POST',f'/api/conversations/{cid}/turns',{'message':'My headphones arrived damaged. Please arrange a replacement by 2026-09-20.','request_id':str(uuid.uuid4())})
 state=json.loads(request('GET',f'/api/conversations/{cid}'));proposal=state.get('proposal');result={'run_id':session['run_id'],'conversation_id':cid,'passed':False,'state':state,'duration_seconds':time.monotonic()-start}
 try:
  if not proposal:raise RuntimeError('Real model did not produce a proposal')
  response=json.loads(request('POST','/api/proposals/'+proposal['proposal_id']+'/confirm',{'idempotency_key':str(uuid.uuid4())}));state=json.loads(request('GET',f'/api/conversations/{cid}'));result.update(state=state,confirmation=response,passed=state.get('status')=='confirmed',duration_seconds=time.monotonic()-start)
  if not result['passed']:raise RuntimeError('Confirmed state was not persisted')
 finally:
  target=pathlib.Path(output or ROOT/'runs/runtime-smoke.json');target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ('state','confirmation')},indent=2));return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:3100');p.add_argument('--output');args=p.parse_args();raise SystemExit(0 if run(args.base_url,args.output)['passed'] else 1)
