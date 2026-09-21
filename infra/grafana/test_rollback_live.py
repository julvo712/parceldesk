#!/usr/bin/env python3
"""Exercise upgrade and rollback in an isolated owned validation folder."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from manage import call,resource,owned,ROOT,digest


def run(context):
 originals=[d for _,d in owned(ROOT/'resources')]
 folder='parceldesk-validation'
 mapping={d['metadata']['name']:('pd-validation-'+d['metadata']['name'][3:] if d['kind']=='Dashboard' else folder) for d in originals}
 staged=[]
 for d in originals:
  d=deepcopy(d);d['metadata']['name']=mapping[d['metadata']['name']]
  d['spec']['title']='VALIDATION · '+d['spec']['title']
  if d['kind']=='Dashboard':d['metadata']['annotations']['grafana.app/folder']=folder
  staged.append(d)
 selectors=[('dashboards/' if d['kind']=='Dashboard' else 'folders/')+d['metadata']['name'] for d in staged]
 # Refuse collisions rather than replacing or cleaning another run's resources.
 for selector in selectors:
  try:resource(context,selector)
  except RuntimeError as e:
   if 'not found' in str(e).lower() or 'notfound' in str(e).lower():continue
   raise
  raise RuntimeError(f'Validation resource already exists; inspect its owner before retrying: {selector}')
 report={'started_at':datetime.now(timezone.utc).isoformat(),'context':context,'folder':folder,'phases':[],'cleanup':False}
 created=False
 with tempfile.TemporaryDirectory(prefix='pd-grafana-validation-') as tmp:
  base=Path(tmp)
  try:
   for phase,suffix in [('install',''),('upgrade',' · REVISION 2'),('rollback','')]:
    docs=[]
    for original in staged:
     d=deepcopy(original);d['spec']['title']+=suffix;docs.append(d)
     path=base/('dashboards' if d['kind']=='Dashboard' else 'folders');path.mkdir(exist_ok=True)
     (path/(d['metadata']['name']+'.json')).write_text(json.dumps(d))
    validation=call(context,'resources','validate','-p',str(base))
    if validation.get('failures') or validation.get('skipped'):raise RuntimeError('Validation did not pass fully')
    dry=call(context,'resources','push','-p',str(base),'--dry-run')
    if not dry.get('dry_run') or dry.get('summary',{}).get('succeeded')!=8:raise RuntimeError('Dry-run did not verify all eight resources')
    created=True
    for part in ('folders','dashboards'):call(context,'resources','push','-p',str(base/part))
    checks=[]
    for source,selector in zip(docs,selectors):
     live=resource(context,selector);ok=source['spec']==live['spec']
     if source['kind']=='Dashboard':ok=ok and live['metadata']['annotations'].get('grafana.app/folder')==folder
     checks.append({'resource':selector,'matches':ok,'spec_sha256':digest(live['spec'])})
    report['phases'].append({'phase':phase,'checks':checks,'passed':all(c['matches'] for c in checks)})
    if not report['phases'][-1]['passed']:raise RuntimeError(f'{phase}: source parity failed')
  finally:
   if created:
    # Named resource selectors only. Never use --force or --yes/type-wide deletion.
    for kind in ('dashboards/','folders/'):
     selected=[s for s in selectors if s.startswith(kind)]
     for selector in selected:
      live=resource(context,selector)
      if live['metadata'].get('labels',{}).get('parceldesk-owner')!='demo':raise RuntimeError('Validation cleanup refused: ownership changed')
     call(context,'resources','delete',*selected,'--dry-run')
     call(context,'resources','delete',*selected)
    report['cleanup']=True
   report['finished_at']=datetime.now(timezone.utc).isoformat()
   report['passed']=len(report['phases'])==3 and all(x['passed'] for x in report['phases']) and report['cleanup']
   (ROOT/'evidence'/'rollback-validation.json').write_text(json.dumps(report,indent=2)+'\n')
 return report

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--context',default='demotests_gcloud');a=p.parse_args()
 print(json.dumps(run(a.context),indent=2))
