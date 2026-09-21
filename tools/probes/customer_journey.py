import httpx,uuid,json,pathlib
c=httpx.Client(base_url='http://localhost:3100',timeout=100)
r=c.post('/api/demo-session',json={'customer_id':'C1'});r.raise_for_status();run=r.json()['run_id']
r=c.post('/api/conversations',json={'order_id':'PD-1042'});r.raise_for_status();cid=r.json()['conversation_id']
r=c.post(f'/api/conversations/{cid}/turns',json={'message':'My headphones arrived damaged. Please arrange a replacement by 2026-09-20.','request_id':str(uuid.uuid4())});r.raise_for_status();print(r.text[-1400:])
s=c.get(f'/api/conversations/{cid}').json();p=s.get('proposal');print('State',s['status'],'proposal',p)
if p:
 r=c.post('/api/proposals/'+p['proposal_id']+'/confirm',json={'idempotency_key':str(uuid.uuid4())});print('Confirm',r.status_code,r.text)
 s=c.get(f'/api/conversations/{cid}').json();print('Persisted status',s['status'])
 pathlib.Path('parceldesk/runs/customer-journey.json').write_text(json.dumps({'run_id':run,'conversation_id':cid,'state':s},indent=2))
 assert s['status']=='confirmed'
else:raise SystemExit('No proposal: live journey did not pass')
