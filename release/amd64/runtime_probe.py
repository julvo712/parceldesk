"""Runs inside the actual AMD64 agent image, against the isolated real services."""
import concurrent.futures,json,pathlib,platform,time,urllib.request,uuid
from anthropic import Anthropic
TOKEN='architecture-test-only'
def request(method,path,data=None):
 r=urllib.request.Request('http://operations:8080'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-Service-Token':TOKEN},method=method)
 with urllib.request.urlopen(r,timeout=15) as response:return json.load(response)
def main():
 start=time.time();run=str(uuid.uuid4());cid=str(uuid.uuid4());ctx={'demo_run_id':run,'conversation_id':cid,'customer_id':'C1','business_date':'2026-09-15','fixture_revision':'store-v1','agent_version':'amd64-runtime-probe','traffic_kind':'probe','scenario':'healthy'}
 request('POST','/internal/runs',{'run_id':run,'customer_id':'C1','business_date':'2026-09-15'});request('POST','/internal/conversations',{'run_id':run,'customer_id':'C1','conversation_id':cid,'order_id':'PD-1042','agent_version':'amd64-runtime-probe'})
 def tool(name,args):return request('POST','/internal/tools/'+name,{'context':ctx,'arguments':args,'call_id':str(uuid.uuid4())})
 order=tool('get_order',{'order_id':'PD-1042'});assert order['status']=='ok'
 policy=tool('get_retailer_policy',{});guide=tool('get_supplier_guide',{'order_id':'PD-1042'});inventory=tool('check_inventory',{'order_id':'PD-1042'});shipping=tool('get_shipping_options',{'order_id':'PD-1042','requested_by':'2026-09-20'});proposal=tool('propose_replacement',{'order_id':'PD-1042','requested_by':'2026-09-20'});assert all(x['status']=='ok' for x in [policy,guide,inventory,shipping,proposal]);pid=proposal['data']['proposal_id']
 denied=tool('create_replacement',{'proposal_id':pid,'idempotency_key':'create'});assert denied['status']=='policy_denied'
 request('POST',f'/internal/proposals/{pid}/confirm',{'context':ctx,'idempotency_key':'confirm'})
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:replacements=list(pool.map(lambda _:tool('create_replacement',{'proposal_id':pid,'idempotency_key':'create'}),range(5)))
 assert all(x['status']=='ok' for x in replacements);rid=replacements[0]['data']['replacement_id'];assert len({x['data']['replacement_id'] for x in replacements})==1
 bad=tool('send_confirmation',{'replacement_id':rid,'to':'audit@external.invalid','idempotency_key':'bad'});assert bad['status']=='policy_denied'
 for _ in range(3):assert tool('send_confirmation',{'replacement_id':rid,'to':order['data']['customer_email'],'idempotency_key':'notify'})['status']=='ok'
 ledger=request('GET',f'/internal/runs/{run}/evidence');assert ledger['replacements_count']==ledger['notifications_count']==1
 key=pathlib.Path('/run/secrets/anthropic_key').read_text().strip();client=Anthropic(api_key=key,timeout=30);result=client.messages.create(model='claude-haiku-4-5-20251001',max_tokens=32,temperature=0,messages=[{'role':'user','content':'Reply with exactly PARCELDESK_AMD64_OK.'}]);text=''.join(p.text for p in result.content if getattr(p,'type','')=='text');assert 'PARCELDESK_AMD64_OK' in text
 report={'passed':True,'machine':platform.machine(),'run_id':run,'eight_business_tools_passed':True,'unconfirmed_action_denied':True,'wrong_recipient_denied':True,'concurrent_replacements':ledger['replacements_count'],'notifications':ledger['notifications_count'],'anthropic':{'model':result.model,'message_id':result.id,'input_tokens':result.usage.input_tokens,'output_tokens':result.usage.output_tokens,'reply':text},'elapsed_seconds':time.time()-start,'cloud_export':'disabled; local discard receiver and no Cloud credentials','scope':'real AMD64 service/business/provider smoke, not native Cloud guard/evaluation acceptance'}
 print(json.dumps(report,indent=2))
if __name__=='__main__':main()
