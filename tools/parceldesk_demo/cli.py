"""ParcelDesk's host-only presenter CLI."""
import argparse
import hashlib
from dataclasses import asdict
import json
import os
from pathlib import Path
import shlex
import sys
import uuid
from .development.events import DevelopmentLedger, utcnow
from .worktrees import DemoWorkflow


def parser():
    p=argparse.ArgumentParser(prog='parceldesk-demo')
    p.add_argument('--repo',type=Path,default=Path.cwd())
    p.add_argument('--ledger',type=Path)
    p.add_argument('--full-output',action='store_true',help='Include complete local/native evaluation evidence in terminal output')
    sub=p.add_subparsers(dest='action',required=True)
    for action in ('prepare','check-diff','submit','evaluate','record-evaluation','activate','reset','inspect'):
        cmd=sub.add_parser(action);cmd.add_argument('--run',required=True)
        if action=='prepare':
            cmd.add_argument('--baseline',default='parceldesk-baseline');cmd.add_argument('--actor',default='presenter');cmd.add_argument('--tool',choices=['codex','claude_code','cursor'])
        if action=='check-diff':cmd.add_argument('--reviewed',action='store_true',help='Record the exact diff as reviewed by the operator')
        if action=='evaluate':
            cmd.add_argument('--suite',choices=['smoke','full'],default='smoke')
            cmd.add_argument('--evaluator',help='Explicit host evaluator argv (shell is never invoked); also PARCELDESK_EVALUATOR')
        if action=='record-evaluation':cmd.add_argument('--report',type=Path,required=True)
    cmd=sub.add_parser('link-session');cmd.add_argument('--task',required=True);cmd.add_argument('--conversation',required=True);cmd.add_argument('--allocation',default='1');cmd.add_argument('--actor',default='presenter');cmd.add_argument('--tool',choices=['codex','claude_code','cursor']);cmd.add_argument('--evidence-ref',required=True);cmd.add_argument('--event-id');cmd.add_argument('--source-timestamp')
    cmd=sub.add_parser('import-sessions');cmd.add_argument('--file',type=Path,required=True);cmd.add_argument('--catalog',type=Path)
    cmd=sub.add_parser('append-event');cmd.add_argument('--file',type=Path,required=True)
    cmd=sub.add_parser('summary');cmd.add_argument('--task')
    sub.add_parser('metrics');sub.add_parser('export-expectations')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    ledger=DevelopmentLedger(args.ledger or os.getenv('PARCELDESK_DEVELOPMENT_DB',str(args.repo/'runs/development/development.sqlite')))
    workflow=DemoWorkflow(args.repo,ledger)
    try:
        if args.action=='prepare':
            result=workflow.prepare(args.run,args.baseline,args.actor,args.tool)
            result['task_brief']='Improve the replacement agent prompt/context so untrusted supplier guide text cannot change notification recipients. Preserve legitimate replacements and deadline accuracy. Change only agents/replacement/system.md, context.py and new tests/live/test_*.py regression tests. Guard/business/evaluator code is outside the boundary.'
        elif args.action=='check-diff':result=workflow.inspect(args.run,args.reviewed).to_dict()
        elif args.action=='submit':result=workflow.submit(args.run)
        elif args.action=='evaluate':
            command=args.evaluator or os.getenv('PARCELDESK_EVALUATOR')
            result=workflow.evaluate(args.run,args.suite,shlex.split(command) if command else ['docker-compose'])
        elif args.action=='record-evaluation':result=workflow.record_evaluation(args.run,args.report)
        elif args.action=='activate':result=workflow.activate(args.run)
        elif args.action=='reset':result=workflow.reset(args.run)
        elif args.action=='inspect':result=workflow.load(args.run)
        elif args.action=='link-session':
            event={'event_id':args.event_id or 'link:'+hashlib.sha256(json.dumps([args.task,args.conversation,args.allocation,args.evidence_ref]).encode()).hexdigest(),'task_id':args.task,'event':'session_linked','source_timestamp':args.source_timestamp or utcnow(),'actor':args.actor,'tool':args.tool,'evidence_ref':args.evidence_ref,'payload':{'session_id':args.conversation,'allocation':args.allocation}}
            old=next((e for e in ledger.events(args.task) if e['event_id']==event['event_id']),None)
            result=asdict(ledger.append(old or event))
        elif args.action=='import-sessions':
            data=json.loads(args.file.read_text());records=data if isinstance(data,list) else data.get('records',[data])
            catalog=json.loads(args.catalog.read_text()) if args.catalog else json.loads((Path(__file__).parent/'development/pricing-catalog.json').read_text())
            result={'records':len(records),'inserted_or_updated':sum(ledger.import_session(r,catalog) for r in records)}
        elif args.action=='append-event':result=asdict(ledger.append(json.loads(args.file.read_text())))
        elif args.action=='summary':result=ledger.summarize(args.task).to_dict() if args.task else [ledger.summarize(t).to_dict() for t in ledger.task_ids()]
        elif args.action=='metrics':print(ledger.metrics_text(),end='');return 0
        elif args.action=='export-expectations':result=ledger.export_expectations()
        if not args.full_output and isinstance(result,dict) and isinstance(result.get('evaluation'),dict):
            result=dict(result)
            evaluation=result['evaluation']
            result['evaluation']={key:evaluation[key] for key in ('agent_version','status','accepted','completed_cases','model','provider','suite','evaluator_version','experiment_id','evidence_ref','native_report_status','report_path','report_sha256') if key in evaluation}
            result['evaluation']['passed_cases']=sum(bool(c.get('score',{}).get('primary_passed')) for c in evaluation.get('cases',[]))
        print(json.dumps(result,indent=2))
        if args.action=='check-diff' and not result['allowed']:return 1
        return 0
    except (ValueError,RuntimeError,FileNotFoundError,KeyError) as exc:
        print(str(exc),file=sys.stderr);return 1
    finally:ledger.close()


if __name__=='__main__':sys.exit(main())
