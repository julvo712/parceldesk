#!/usr/bin/env python3
"""Exercise real isolated Go faults, retain evidence, and always reset leases."""
import concurrent.futures,datetime as dt,importlib.util,json,pathlib,subprocess,time,uuid
ROOT=pathlib.Path(__file__).resolve().parents[2]
COMPOSE=['docker','compose','--project-name','parceldesk','--file',str(ROOT/'compose.yaml')]
CHILD='''import json,sys,pathlib,urllib.request
p=json.load(sys.stdin)
token=pathlib.Path('/run/secrets/service_token').read_text().strip()
headers={'Content-Type':'application/json','X-Service-Token':token}
if p.get('trace_id'):headers['traceparent']='00-'+p['trace_id']+'-'+p['parent_id']+'-01'
body=json.dumps(p['body']).encode() if p.get('body') is not None else None
r=urllib.request.Request('http://operations:8080'+p['path'],data=body,headers=headers,method=p['method'])
with urllib.request.urlopen(r,timeout=20) as response:print(response.read().decode())
'''
def request(method,path,body=None,trace_id=None):
 p={'method':method,'path':path,'body':body,'trace_id':trace_id,'parent_id':uuid.uuid4().hex[:16]};start=time.monotonic();r=subprocess.run(COMPOSE+['exec','-T','agent-api','python','-c',CHILD],input=json.dumps(p),capture_output=True,text=True,timeout=30)
 if r.returncode:raise RuntimeError(f'{method} {path} failed (child exit {r.returncode})')
 return {'response':json.loads(r.stdout),'duration_seconds':time.monotonic()-start,'trace_id':trace_id}
def stats():
 spec=importlib.util.spec_from_file_location('observer',ROOT/'tools/observer/observer.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);reader=m.DockerReader()
 for container in reader.containers():
  if container['Labels']['com.docker.compose.service']=='operations':return m.decode_stats(reader.stats(container['Id']))
 raise RuntimeError('Operations container not found')
def blockers():
 sql="SELECT COALESCE(json_agg(json_build_object('pid',pid,'wait_event_type',wait_event_type,'wait_event',wait_event,'blocking_pids',pg_blocking_pids(pid))), '[]'::json) FROM pg_stat_activity WHERE datname='parceldesk' AND cardinality(pg_blocking_pids(pid))>0"
 r=subprocess.run(COMPOSE+['exec','-T','postgres','psql','-U','parceldesk','-d','parceldesk','-Atc',sql],text=True,capture_output=True,timeout=10)
 if r.returncode:raise RuntimeError('Lock evidence query failed')
 return json.loads(r.stdout)
def main():
 run_id='go-rehearsal-'+uuid.uuid4().hex;conversation_id=str(uuid.uuid4());context={'demo_run_id':run_id,'conversation_id':conversation_id,'customer_id':'C1','business_date':'2026-09-15','fixture_revision':'store-v1','agent_version':'fault-probe','traffic_kind':'probe','scenario':'healthy'}
 report={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'run_id':run_id,'kind':'deterministic tool and infrastructure probe, not an LLM experiment','scenarios':{}}
 def tool(name,args):
  return request('POST','/internal/tools/'+name,{'context':context,'arguments':args,'call_id':str(uuid.uuid4())},uuid.uuid4().hex)
 def activate(name,ttl=30):return request('POST',f'/internal/runs/{run_id}/scenario',{'scenario':name,'ttl_seconds':ttl})
 def reset():return request('DELETE',f'/internal/runs/{run_id}/scenario')
 request('POST','/internal/runs',{'run_id':run_id,'customer_id':'C1','business_date':'2026-09-15'})
 request('POST','/internal/conversations',{'run_id':run_id,'customer_id':'C1','order_id':'PD-1042','conversation_id':conversation_id,'agent_version':'fault-probe'})
 try:
  baseline=tool('check_inventory',{'order_id':'PD-1042'});activate('db_lock')
  with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
   waiting=pool.submit(tool,'check_inventory',{'order_id':'PD-1042'});time.sleep(.6);observed=blockers();assert observed,'No actual PostgreSQL waiter observed';reset();blocked=waiting.result(timeout=10)
  recovered=tool('check_inventory',{'order_id':'PD-1042'});assert blocked['response']['status']=='ok' and recovered['response']['status']=='ok';assert not blockers()
  report['scenarios']['db_lock']={'baseline':baseline,'fault_request':blocked,'waiters':observed,'recovered':recovered,'passed':True}
  args={'order_id':'PD-1045','requested_by':'2026-09-20'};baseline=tool('get_shipping_options',args);activate('shipping_mapping_bug');fault=tool('get_shipping_options',args);reset();recovered=tool('get_shipping_options',args)
  b,f,r=[v['response']['data'] for v in (baseline,fault,recovered)];assert b['arrival_date']==b['raw_carrier']['arrival_date'];assert f['arrival_date']!=f['raw_carrier']['arrival_date'];assert r['arrival_date']==r['raw_carrier']['arrival_date'];report['scenarios']['shipping_mapping_bug']={'baseline':baseline,'fault':fault,'recovered':recovered,'passed':True}
  before=stats();baseline=tool('check_inventory',{'order_id':'PD-1042'});activate('cpu_regression',40);faults=[tool('check_inventory',{'order_id':'PD-1042'}) for _ in range(6)];after=stats();reset();recovered=tool('check_inventory',{'order_id':'PD-1042'});assert min(f['duration_seconds'] for f in faults)>1.5;assert recovered['duration_seconds']<max(f['duration_seconds'] for f in faults);report['scenarios']['cpu_regression']={'baseline':baseline,'fault_requests':faults,'cpu_seconds_delta':after['parceldesk_container_cpu_usage_seconds_total']-before['parceldesk_container_cpu_usage_seconds_total'],'recovered':recovered,'passed':True}
  before=stats();lease=activate('cpu_pressure',12);start=time.monotonic()
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:probes=list(pool.map(lambda _:request('GET','/internal/cpu-probe?duration_ms=900',trace_id=uuid.uuid4().hex),range(8)))
  time.sleep(max(0,7-(time.monotonic()-start)));during=stats();elapsed=time.monotonic()-start;busy_rate=(during['parceldesk_container_cpu_usage_seconds_total']-before['parceldesk_container_cpu_usage_seconds_total'])/elapsed
  reset();idle_before=stats();time.sleep(3);idle_after=stats();idle_rate=(idle_after['parceldesk_container_cpu_usage_seconds_total']-idle_before['parceldesk_container_cpu_usage_seconds_total'])/3;assert busy_rate>.5,(busy_rate,idle_rate);assert idle_rate<busy_rate/2,(busy_rate,idle_rate)
  throttle='parceldesk_container_cpu_throttled_periods_total';report['scenarios']['cpu_pressure']={'lease':lease['response'],'busy_cpu_cores':busy_rate,'recovered_cpu_cores':idle_rate,'throttled_periods_delta':during.get(throttle,0)-before.get(throttle,0),'profile_probe_traces':[p['trace_id'] for p in probes],'passed':True}
 finally:
  report['final_reset']=reset()['response'];report['final_evidence']=request('GET',f'/internal/runs/{run_id}/evidence')['response'];report['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();report['healthy_afterward']=report['final_evidence']['scenario']=='healthy';report['passed']=report['healthy_afterward'] and len(report['scenarios'])==4 and all(s['passed'] for s in report['scenarios'].values());path=ROOT/'docs/verification/go-fault-rehearsal.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'report':str(path),'run_id':run_id,'passed':report['passed'],'healthy_afterward':report['healthy_afterward'],'scenarios':list(report['scenarios'])},indent=2))
 return report
if __name__=='__main__':main()
