#!/usr/bin/env python3
"""Execute release checks and record measured results, including omitted gates."""
from __future__ import annotations
import argparse,datetime,hashlib,importlib.util,json,pathlib,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
def source_check():
 spec=importlib.util.spec_from_file_location('release_build',ROOT/'release/build.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 entries=module.inspect_source(ROOT)
 return {'scanned_files':len(entries),'source_sha256':hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest()}
def run(args):
 target=pathlib.Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
 report={'schema_version':1,'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'suite':args.suite,'checks':[],
  'unexecuted_gates':['Two-presenter pilot including clean-machine install','Physical AMD64 host validation','Live model evaluations and guard tests require explicitly provisioned Cloud credentials'],
  'release_classification':'internal release candidate; automated checks do not establish human pilot acceptance'}
 def save():target.write_text(json.dumps(report,indent=2)+'\n')
 try:
  start=time.monotonic()
  try: details=source_check();report['checks'].append({'name':'source_credential_scan','status':'passed','duration_seconds':time.monotonic()-start,**details})
  except Exception as exc: report['checks'].append({'name':'source_credential_scan','status':'failed','error':str(exc)});raise
  commands=[('release_tests',['make','test-release']),('observer_tests',['make','test-observer'])] if args.suite=='quick' else [(name,['make',target]) for name,target in [('postgresql_race_and_vet','test-operations'),('agent_and_development_contracts','test-agent'),('frontend_tests_and_build','test-web'),('observer_decoder_tests','test-observer'),('release_integrity_tests','test-release'),('browser_accessibility_interaction_tests','test-browser')]]
  if args.live:commands.append(('live_local_and_cloud_doctor',['python3','release/manage.py','doctor','--context',args.context]))
  else:report['unexecuted_gates'].append('Live Cloud connectivity and ingestion: not run (use --live with configured credentials)')
  for name,command in commands:
   start=time.monotonic();print(f'Running {name}',flush=True);result=subprocess.run(command,cwd=ROOT)
   report['checks'].append({'name':name,'command':command,'exit_code':result.returncode,'status':'passed' if result.returncode==0 else 'failed','duration_seconds':time.monotonic()-start});save()
  report['automated_checks_passed']=all(c['status']=='passed' for c in report['checks'])
 except Exception as exc:
  report['automated_checks_passed']=False;report['error']=str(exc)
 finally:
  report['finished_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
 print(json.dumps({'report':str(target),'automated_checks_passed':report['automated_checks_passed'],'unexecuted_gates':report['unexecuted_gates']},indent=2))
 return 0 if report['automated_checks_passed'] else 1
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['quick','full'],default='full');parser.add_argument('--output',default=str(ROOT/'runs/release-check.json'));parser.add_argument('--live',action='store_true');parser.add_argument('--context',default='demotests_gcloud');raise SystemExit(run(parser.parse_args()))
