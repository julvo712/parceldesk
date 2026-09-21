#!/usr/bin/env python3
"""Scoped gcx deployment, source parity, query and renderer verification."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
UIDS=['pd-presenter','pd-overview','pd-coding-finops','pd-coding-adoption','pd-delivery-quality','pd-agent-quality','pd-runtime','pd-demo-readiness']

def call(context,*args,json_output=True):
 command=['gcx','--context',context,*args]+(['-o','json'] if json_output else [])
 r=subprocess.run(command,text=True,capture_output=True)
 if r.returncode:raise RuntimeError(f'{" ".join(command)}: {r.stderr.strip()}')
 if not json_output:return r.stdout
 try:return json.loads(r.stdout)
 except json.JSONDecodeError as e:raise RuntimeError('gcx did not return valid JSON') from e

def resource(context,selector):
 obj=call(context,'resources','get',selector)
 if 'items' in obj:
  if len(obj['items'])!=1:raise RuntimeError(f'{selector}: expected exactly one resource')
  return obj['items'][0]
 return obj

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def owned(path):
 docs=[]
 for p in sorted(path.rglob('*.json')):
  d=json.loads(p.read_text());name=d.get('metadata',{}).get('name')
  if d.get('kind')=='Dashboard' and name in UIDS:pass
  elif d.get('kind')=='Folder' and name=='parceldesk-demo':pass
  else:raise RuntimeError(f'Refusing unowned resource {p}')
  if d['metadata'].get('labels',{}).get('parceldesk-owner')!='demo':raise RuntimeError(f'Missing ownership label: {p}')
  if d['kind']=='Dashboard' and d['metadata'].get('annotations',{}).get('grafana.app/folder')!='parceldesk-demo':raise RuntimeError(f'Refusing unexpected folder: {p}')
  docs.append((p,d))
 if len(docs)!=len(UIDS)+1 or {d['metadata']['name'] for _,d in docs} != set(UIDS+['parceldesk-demo']):raise RuntimeError(f'Expected exactly one copy of the owned folder and all registered dashboards, found {len(docs)}')
 return docs

def verify(context,path):
 def check(entry):
  p,source=entry;selector=('dashboards/' if source['kind']=='Dashboard' else 'folders/')+source['metadata']['name'];live=resource(context,selector)
  # Only metadata/status are server-owned. Native v2 specs must match exactly.
  equal=source['spec']==live['spec'];folder=source['metadata'].get('annotations',{}).get('grafana.app/folder')
  actual_folder=live.get('metadata',{}).get('annotations',{}).get('grafana.app/folder')
  if folder and folder!=actual_folder:equal=False
  result={'resource':selector,'matches':equal,'source_sha256':digest(source['spec']),'live_sha256':digest(live['spec']),'folder':actual_folder,'url':live.get('url')}
  if not equal:
   (ROOT/'evidence'/f'{source["metadata"]["name"]}-mismatch.json').write_text(json.dumps({'source':source['spec'],'live':live['spec']},indent=2))
  return result
 with ThreadPoolExecutor(max_workers=4) as ex:results=list(ex.map(check,owned(path)))
 report={'checked_at':datetime.now(timezone.utc).isoformat(),'context':context,'resources':results,'passed':all(r['matches'] for r in results)}
 (ROOT/'evidence'/'parity.json').write_text(json.dumps(report,indent=2)+'\n')
 if not report['passed']:raise RuntimeError('Source-versus-live mismatch; see evidence/parity.json')
 return report

def backup(context):
 dest=ROOT/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 for uid in ['parceldesk-demo',*UIDS]:
  kind='folders' if uid=='parceldesk-demo' else 'dashboards'
  try:d=resource(context,f'{kind}/{uid}')
  except RuntimeError as e:
   if 'not found' in str(e).lower() or 'notfound' in str(e).lower():continue
   raise
  if d.get('metadata',{}).get('labels',{}).get('parceldesk-owner')!='demo':raise RuntimeError(f'Refusing to overwrite resource without ParcelDesk ownership: {uid}')
  meta={'name':uid,'labels':{'parceldesk-owner':'demo'}}
  if kind=='dashboards':meta['annotations']={'grafana.app/folder':'parceldesk-demo'}
  d={'apiVersion':d['apiVersion'],'kind':d['kind'],'metadata':meta,'spec':d['spec']}
  (dest/kind).mkdir(parents=True,exist_ok=True);(dest/kind/f'{uid}.json').write_text(json.dumps(d,indent=2)+'\n')
 return str(dest) if dest.exists() else None

def push(context,path):
 owned(path)
 call(context,'config','check',json_output=False)
 old=backup(context)
 validation=call(context,'resources','validate','-p',str(path))
 if validation.get('failures') or validation.get('skipped'):raise RuntimeError(f'Validation incomplete: {validation}')
 dry=call(context,'resources','push','-p',str(path),'--dry-run')
 if dry.get('dry_run') is not True or dry.get('summary',{}).get('succeeded')!=len(UIDS)+1 or dry.get('failures'):raise RuntimeError(f'Dry-run not fully supported/successful: {dry}')
 # Explicit folder-first operation, even though gcx can order mixed manifests.
 for part in ('folders','dashboards'):
  result=call(context,'resources','push','-p',str(path/part))
  if result.get('summary',{}).get('failed') or result.get('failures'):raise RuntimeError(f'Push failed: {result}')
 result=verify(context,path);result['backup']=old;result['dry_run']=dry
 (ROOT/'evidence'/'deployment.json').write_text(json.dumps(result,indent=2)+'\n')
 return result

def queries(context,path):
 tests=[]
 for _,d in owned(path):
  if d['kind']!='Dashboard':continue
  for panel in d['spec']['elements'].values():
   for q in panel['spec']['data']['spec']['queries']:
    q=q['spec']['query'];
    if q['group']=='yesoreyeram-infinity-datasource':continue # Static command catalog is verified by presenter browser tests.
    expr=q['spec']['expr'];expr=expr.replace('$__rate_interval','1m').replace('$__range','1h').replace('$traffic_kind','.*').replace('$tool','.*').replace('$eval_model','.*').replace('$eval_suite','.*')
    tests.append((d['metadata']['name'],panel['spec']['title'],q['group'],q['datasource']['name'],expr))
 def check(t):
  uid,title,group,ds,expr=t
  try:
   args=['metrics','query','-d',ds,expr] if group=='prometheus' else ['logs','query','-d',ds,expr,'--limit','5','--since','1h']
   result=call(context,*args);data=result.get('data',{}).get('result',[])
   return dict(dashboard=uid,panel=title,query=expr,query_success=result.get('status')=='success',series=len(data),state='observed' if data else 'no_observations',samples=data[:3])
  except RuntimeError as e:return dict(dashboard=uid,panel=title,query=expr,query_success=False,error=str(e))
 with ThreadPoolExecutor(max_workers=4) as ex:results=list(ex.map(check,tests))
 report={'checked_at':datetime.now(timezone.utc).isoformat(),'context':context,'queries':results,'syntax_passed':all(x['query_success'] for x in results),'data_backed_dashboards':sorted(set(x['dashboard'] for x in results if x.get('series',0)>0)),'acceptance':'query validation is not ledger-value or visual acceptance'}
 (ROOT/'evidence'/'queries.json').write_text(json.dumps(report,indent=2)+'\n')
 if not report['syntax_passed']:raise RuntimeError('One or more datasource queries failed; see evidence/queries.json')
 return {k:v for k,v in report.items() if k!='queries'}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['deploy','verify','queries','snapshot','rollback']);p.add_argument('--context',default='demotests_gcloud');p.add_argument('--path',type=Path,default=ROOT/'resources');p.add_argument('--backup',type=Path);a=p.parse_args();(ROOT/'evidence').mkdir(exist_ok=True)
 try:
  if a.action=='deploy':r=push(a.context,a.path)
  elif a.action=='verify':r=verify(a.context,a.path)
  elif a.action=='queries':r=queries(a.context,a.path)
  elif a.action=='rollback':
   if not a.backup:p.error('--backup is required for rollback')
   r=push(a.context,a.backup)
  else:r=call(a.context,'dashboards','snapshot',*UIDS,'--output-dir',str(ROOT/'evidence'/'snapshots'),'--width','1440','--since','1h','--theme','dark','--concurrency','2')
  print(json.dumps(r,indent=2))
 except RuntimeError as e:print(str(e),file=sys.stderr);sys.exit(1)
