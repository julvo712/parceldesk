"""Truthful telemetry adapters for development events and saved evaluation evidence.

This module does not execute evaluations, mutate their results, or synthesize
success. Native reports take precedence over local copies of the same experiment.
"""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
import re
from .development.metrics import label
from .development.events import encoded, utcnow, timestamp

CHECKS=('primary_verdict','correctness_passed','task_completed','unsafe_attempt','prevention_passed','false_refusal')


def _number_time(value, fallback):
    try:
        return datetime.fromisoformat(timestamp(value)).timestamp()
    except (ValueError,TypeError,AttributeError):
        return fallback


def _bool_check(key,value):
    if not isinstance(value,bool):return None
    return not value if key in ('unsafe_attempt','false_refusal') else value


def normalize_report(data, source_path, modified_at):
    """Produce only bounded metrics fields and evidence references, not transcripts."""
    if data.get('synthetic') is True or data.get('test_fixture') is True:return None
    native=data.get('experiment')
    if isinstance(native,dict) and isinstance(data.get('rows'),list):
        eid=native.get('experiment_id');version=native.get('candidate',{}).get('agent_version')
        if not eid or not version:return None
        status=native.get('status','unknown');result_status=native.get('result_status','unknown')
        observations={};verifiers=set();duplicates=0
        for row in data['rows']:
            for entry in row.get('trials',[]):
                trial=entry.get('trial',{});tid=trial.get('trial_id')
                if not tid:continue
                scores=[entry.get('final_score',{}),*entry.get('scores',[])]
                for score in scores:
                    key=score.get('score_key');key='primary_verdict' if key in ('final','primary_verdict') else key
                    if key not in CHECKS or not isinstance(score.get('passed'),bool):continue
                    evaluator=str(score.get('evaluator_version','unknown'));verifiers.add(evaluator)
                    identity=(tid,key,evaluator)
                    result='pass' if score['passed'] else 'fail'
                    value={'trial_id':tid,'check':key,'result':result,'evaluator_version':evaluator}
                    if identity in observations and observations[identity]!=value:
                        observations[identity]={**value,'result':'conflict'};duplicates+=1
                    else:observations.setdefault(identity,value)
        if duplicates:status='conflicting'
        suite_match=re.match(r'^ParcelDesk (full|smoke|heldout) ',native.get('name',''))
        return dict(experiment_id=eid,version=version,suite_version=str(native.get('suite_version','unknown')),
                    evaluation_suite=suite_match.group(1) if suite_match else 'unknown',
                    evaluator_version=','.join(sorted(verifiers)) or 'unknown',source='native',status=status,
                    result_status=result_status,observations=list(observations.values()),evidence_ref=str(source_path),
                    observed_at=_number_time(native.get('completed_at') or native.get('updated_at'),modified_at),
                    provider=native.get('candidate',{}).get('model_provider','unknown'),model=native.get('candidate',{}).get('model_name','unknown'),
                    cost_usd=data.get('summary',{}).get('total_cost'),cost_coverage=data.get('summary',{}).get('cost_coverage','unknown'),
                    total_tokens=data.get('summary',{}).get('total_tokens'),token_coverage=data.get('summary',{}).get('token_coverage','unknown'))
    if data.get('experiment_id') and data.get('agent_version') and isinstance(data.get('cases'),list):
        observations={};version=str(data.get('evaluator_version','unknown'))
        for case in data['cases']:
            tid=case.get('trial_id')
            if not tid:continue
            for key,value in case.get('score',{}).items():
                key='primary_verdict' if key=='primary_passed' else key
                if key not in CHECKS:continue
                passed=_bool_check(key,value)
                if passed is None:continue
                identity=(tid,key,version);result='pass' if passed else 'fail'
                item={'trial_id':tid,'check':key,'result':result,'evaluator_version':version}
                if identity in observations and observations[identity]!=item:item['result']='conflict'
                observations[identity]=item
        return dict(experiment_id=data['experiment_id'],version=data['agent_version'],
                    suite_version=str(data.get('suite_version','unknown')),evaluator_version=version,source='local',
                    provider=data.get('provider','unknown'),model=data.get('model','unknown'),
                    evaluation_suite=data.get('suite') if data.get('suite') in ('full','smoke','heldout') else 'unknown',
                    status=data.get('status','unknown'),result_status=data.get('native_report_status','not_read'),
                    observations=list(observations.values()),evidence_ref=str(source_path),observed_at=modified_at)
    return None


class EvaluationTelemetry:
    """Cache normalized file observations durably in the existing SQLite ledger."""
    def __init__(self,ledger,reports_dir,log_sink=None):
        self.ledger=ledger;self.reports_dir=Path(reports_dir);self.log_sink=log_sink;self._lock=threading.RLock()
        with ledger._lock,ledger.db:
            ledger.db.execute('''CREATE TABLE IF NOT EXISTS evaluation_report_sources (
              source_path TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, source_mtime REAL NOT NULL,
              normalized TEXT, read_status TEXT NOT NULL)''')
            ledger.db.execute('''CREATE TABLE IF NOT EXISTS evaluation_telemetry_emitted (
              event_id TEXT PRIMARY KEY)''')

    def refresh(self):
        with self.ledger._lock,self._lock,self.ledger.db:
            if not self.reports_dir.exists():return
            for path in sorted(self.reports_dir.rglob('*.json')):
                if path.is_symlink() or not path.resolve().is_relative_to(self.reports_dir.resolve()):continue
                try:stat=path.stat()
                except OSError:continue
                # Logs/transcripts and unrelated large artifacts are not telemetry inputs.
                if stat.st_size>32*1024*1024:continue
                fingerprint=f'model-suite-scoped-v3:{stat.st_mtime_ns}:{stat.st_size}'
                previous=self.ledger.db.execute('SELECT fingerprint,normalized FROM evaluation_report_sources WHERE source_path=?',(str(path),)).fetchone()
                if previous and previous['fingerprint']==fingerprint:continue
                try:
                    data=json.loads(path.read_text());normalized=normalize_report(data,str(path),stat.st_mtime) if isinstance(data,dict) else None
                except (ValueError,OSError):
                    # A report may be mid-write. Keep previous valid evidence; expose read errors.
                    self.ledger.db.execute('INSERT INTO evaluation_report_sources VALUES (?,?,?,?,?) ON CONFLICT(source_path) DO UPDATE SET fingerprint=excluded.fingerprint,read_status=excluded.read_status',(str(path),fingerprint,stat.st_mtime,None,'read_error' if previous and previous['normalized'] else 'unclassified_read_error'))
                    continue
                self.ledger.db.execute('INSERT OR REPLACE INTO evaluation_report_sources VALUES (?,?,?,?,?)',
                    (str(path),fingerprint,stat.st_mtime,encoded(normalized) if normalized else None,'observed' if normalized else 'unrelated'))
            if self.log_sink:
                for report in self._selected():
                    event={'event':'evaluation_completed' if report['status']=='completed' else 'evaluation_observed',
                           'experiment_id':report['experiment_id'],'agent_version':report['version'],
                           'evaluator_version':report['evaluator_version'],'suite_version':report['suite_version'],
                           'provider':report.get('provider','unknown'),'model':report.get('model','unknown'),
                           'evaluation_suite':report.get('evaluation_suite','unknown'),
                           'source':report['source'],'status':report['status'],'native_result_status':report['result_status'],
                           'observed_checks':len(report['observations']),'evidence_ref':report['evidence_ref'],
                           'experiment_path':'/a/grafana-agento11y-app/experiments/runs/'+report['experiment_id'],
                           'source_timestamp':datetime.fromtimestamp(report['observed_at'],timezone.utc).isoformat()}
                    eid=hashlib.sha256(encoded(event).encode()).hexdigest()
                    if not self.ledger.db.execute('SELECT 1 FROM evaluation_telemetry_emitted WHERE event_id=?',(eid,)).fetchone():
                        self.log_sink({**event,'event_id':'eval:'+eid})
                        self.ledger.db.execute('INSERT INTO evaluation_telemetry_emitted VALUES (?)',(eid,))

    def _selected(self):
        selected={}
        for row in self.ledger.db.execute('SELECT normalized,source_mtime FROM evaluation_report_sources WHERE normalized IS NOT NULL'):
            report=json.loads(row['normalized']);eid=report['experiment_id']
            # Native evidence supersedes local even if native is pending. Complete
            # evidence outranks partial copies; ties select the latest observation.
            rank=(report['source']=='native',report['status']=='completed' and report['result_status']=='ready',len(report['observations']),row['source_mtime'])
            if eid not in selected or rank>selected[eid][0]:selected[eid]=(rank,report)
        return [v[1] for v in selected.values()]

    def reports(self):
        self.refresh()
        with self.ledger._lock:return self._selected()

    def metrics_text(self):
        reports=self.reports();checks=Counter();states=Counter();last_seen={};costs=Counter();tokens=Counter()
        for report in reports:
            if report.get('cost_usd') is not None:
                value=Decimal(str(report['cost_usd']))
                if value.is_finite() and value>=0:costs[(report.get('provider','unknown'),report.get('model','unknown'),report['evaluator_version'],report.get('cost_coverage','unknown'),report.get('evaluation_suite','unknown'))]+=value
            if isinstance(report.get('total_tokens'),int) and report['total_tokens']>=0:
                tokens[(report.get('provider','unknown'),report.get('model','unknown'),report['evaluator_version'],report.get('token_coverage','unknown'),report.get('evaluation_suite','unknown'))]+=report['total_tokens']
            states[(report['version'],report['evaluator_version'],report['suite_version'],report['source'],report['status'],report['result_status'],report.get('provider','unknown'),report.get('model','unknown'),report.get('evaluation_suite','unknown'))]+=1
            last_seen[(report['source'],report['status'])]=max(last_seen.get((report['source'],report['status']),0),report['observed_at'])
            for check in report['observations']:
                checks[(check['check'],check['result'],report['version'],check['evaluator_version'],report['suite_version'],report['source'],report.get('provider','unknown'),report.get('model','unknown'),report.get('evaluation_suite','unknown'))]+=1
        lines=['# HELP parceldesk_evaluations_total Observed unique trial checks; native evidence supersedes local copies',
               '# TYPE parceldesk_evaluations_total counter']
        def emit(name,value,names,values):
            attrs=','.join(f'{k}="{label(v)}"' for k,v in zip(names,values));lines.append(f'{name}{{{attrs}}} {value}')
        for dims,count in sorted(checks.items()):emit('parceldesk_evaluations_total',count,('check','result','version','evaluator_version','suite_version','source','provider','model','evaluation_suite'),dims)
        lines+=['# HELP parceldesk_evaluation_reports Number of actual report observations by state/version','# TYPE parceldesk_evaluation_reports gauge']
        for dims,count in sorted(states.items()):emit('parceldesk_evaluation_reports',count,('version','evaluator_version','suite_version','source','status','native_result_status','provider','model','evaluation_suite'),dims)
        lines+=['# HELP parceldesk_evaluation_report_last_seen_seconds Actual evaluation evidence source timestamp','# TYPE parceldesk_evaluation_report_last_seen_seconds gauge']
        for dims,stamp in sorted(last_seen.items()):emit('parceldesk_evaluation_report_last_seen_seconds',stamp,('source','status'),dims)
        lines+=['# HELP parceldesk_evaluation_cost_usd Native reported evaluation LLM consumption with explicit coverage; not judge billing','# TYPE parceldesk_evaluation_cost_usd gauge']
        for dims,amount in sorted(costs.items()):emit('parceldesk_evaluation_cost_usd',amount,('provider','model','evaluator_version','coverage','evaluation_suite'),dims)
        lines+=['# HELP parceldesk_evaluation_tokens_total Native reported total evaluation tokens; cache breakdown unavailable','# TYPE parceldesk_evaluation_tokens_total counter']
        for dims,amount in sorted(tokens.items()):emit('parceldesk_evaluation_tokens_total',amount,('provider','model','evaluator_version','coverage','evaluation_suite'),dims)
        with self.ledger._lock:
            errors=self.ledger.db.execute('SELECT count(*) FROM evaluation_report_sources WHERE read_status="read_error"').fetchone()[0]
        lines+=['# HELP parceldesk_evaluation_report_read_errors Current report files with failed JSON reads','# TYPE parceldesk_evaluation_report_read_errors gauge',f'parceldesk_evaluation_report_read_errors {errors}']
        return '\n'.join(lines)+'\n'


class DevelopmentLogExporter:
    """Separate resource identity; leaves application/global OTel providers untouched."""
    def __init__(self,endpoint=None):
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk._logs import LoggerProvider,LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        base=(endpoint or os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT','http://alloy:4318')).rstrip('/')
        self.provider=LoggerProvider(resource=Resource.create({'service.name':'parceldesk-development','service.namespace':'parceldesk','deployment.environment.name':'demo-local'}))
        self.provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=base+'/v1/logs',headers={})))
        self.logger=logging.Logger('parceldesk-development',level=logging.INFO)
        self.logger.propagate=False
        self.logger.addHandler(LoggingHandler(level=logging.INFO,logger_provider=self.provider))

    def emit(self,event):
        if event.get('synthetic') is True:return
        self.logger.info(encoded({**event,'observed_at':utcnow()}))

    def flush(self):return self.provider.force_flush(timeout_millis=5000)
    def shutdown(self):self.provider.shutdown()


def configure_development_telemetry(ledger,reports_dir='/app/runs',endpoint=None):
    """Call during API lifespan, add collector.metrics_text() at /metrics, shut down exporter."""
    exporter=DevelopmentLogExporter(endpoint)
    ledger.event_sink=exporter.emit
    ledger.flush_outbox()
    collector=EvaluationTelemetry(ledger,reports_dir,log_sink=exporter.emit)
    collector.refresh()
    return collector,exporter


class SnapshotTelemetry:
    """Read host snapshots; keep eval cache and spool receipts inside the VM.

    local_ledger must never point to the host development DB. Repeated event IDs
    resume against local receipts; a crash before acknowledgment can replay an
    event and its immutable ID remains available for downstream deduplication.
    """
    def __init__(self,snapshot_path,local_ledger,reports_dir,exporter):
        self.snapshot_path=Path(snapshot_path);self.ledger=local_ledger;self.exporter=exporter
        self.collector=EvaluationTelemetry(local_ledger,reports_dir,log_sink=exporter.emit)
        self.last_snapshot=None;self.read_error=False
        with local_ledger._lock,local_ledger.db:
            local_ledger.db.execute('CREATE TABLE IF NOT EXISTS development_spool_receipts (event_id TEXT PRIMARY KEY,acknowledged_at TEXT NOT NULL)')

    def read_snapshot(self):
        try:
            if self.snapshot_path.stat().st_size>64*1024*1024:raise ValueError('Snapshot exceeds bound')
            value=json.loads(self.snapshot_path.read_text())
            if value.get('schema_version')!=1 or not isinstance(value.get('metrics'),str) or not isinstance(value.get('events'),list):
                raise ValueError('Invalid telemetry snapshot')
            datetime.fromisoformat(value['published_at'].replace('Z','+00:00'))
            self.last_snapshot=value;self.read_error=False
        except (OSError,ValueError,KeyError):self.read_error=True
        return self.last_snapshot

    def flush_outbox(self):
        snapshot=self.read_snapshot()
        if not snapshot:return
        with self.ledger._lock:
            pending=[]
            for event in snapshot['events']:
                eid=event.get('event_id')
                if not eid or event.get('synthetic') is True:continue
                if self.ledger.db.execute('SELECT 1 FROM development_spool_receipts WHERE event_id=?',(eid,)).fetchone():continue
                self.exporter.emit(event);pending.append(eid)
            # A negative force-flush result keeps every receipt pending. This is
            # local exporter acknowledgment, not proof of Cloud query visibility.
            if pending and self.exporter.flush():
                with self.ledger.db:
                    self.ledger.db.executemany('INSERT OR IGNORE INTO development_spool_receipts VALUES (?,?)',[(eid,utcnow()) for eid in pending])

    def metrics_text(self):
        self.flush_outbox();snapshot=self.last_snapshot
        text=snapshot['metrics'] if snapshot else ''
        text+='# HELP parceldesk_development_snapshot_read_error Latest immutable host snapshot read failed\n# TYPE parceldesk_development_snapshot_read_error gauge\n'
        text+=f'parceldesk_development_snapshot_read_error {int(self.read_error)}\n'
        if snapshot:
            published=datetime.fromisoformat(snapshot['published_at'].replace('Z','+00:00')).timestamp()
            text+='# HELP parceldesk_development_snapshot_published_seconds Source snapshot publication timestamp\n# TYPE parceldesk_development_snapshot_published_seconds gauge\n'
            text+=f'parceldesk_development_snapshot_published_seconds {published}\n'
        return text+self.collector.metrics_text()

    def shutdown(self):self.ledger.close()


def configure_development_snapshot(snapshot_path='/app/runs/development/telemetry-snapshot.json',
                                   reports_dir='/app/runs',cache_db='/data/telemetry/evaluations.sqlite',endpoint=None):
    from .development.events import DevelopmentLedger
    exporter=DevelopmentLogExporter(endpoint)
    # This database lives on a Docker named volume, never a Mac bind mount.
    cache=DevelopmentLedger(cache_db,publish_snapshots=False)
    collector=SnapshotTelemetry(snapshot_path,cache,reports_dir,exporter)
    collector.flush_outbox()
    return collector,exporter


def source_expectations(ledger,collector=None):
    """Freeze source-derived aggregates for independent Grafana Cloud comparisons."""
    with ledger._lock:
        report=ledger.export_expectations()
        report['checks'].append({'name':'Real task inventory','query':'sum(parceldesk_development_tasks)','expected':len(ledger.task_ids())})
        summaries=[ledger.summarize(task) for task in ledger.task_ids()]
        accepted=[s for s in summaries if s.accepted]
        report['checks'].append({'name':'First-pass accepted tasks','query':'sum(parceldesk_development_tasks_first_pass_total)','expected':sum(s.first_pass is True for s in accepted)})
        if accepted:
            report['checks'].append({'name':'Accepted elapsed source seconds','query':'sum(parceldesk_development_accepted_duration_seconds_sum)','expected':sum(s.elapsed_seconds for s in accepted)})
            known=sum((s.known_cost_usd for s in accepted),Decimal(0))
            if known>0:report['checks'].append({'name':'Known accepted-task consumption (partial coverage explicit)','query':'sum(parceldesk_development_cost_usd{coverage="accepted"})','expected':str(known)})
        records=ledger.db.execute('SELECT * FROM session_records WHERE synthetic=0').fetchall()
        for tool in sorted({r['tool'] for r in records}):
            rows=[r for r in records if r['tool']==tool];known=[r for r in rows if r['cost_usd'] is not None]
            report['checks'].extend([
                {'name':tool+' sessions','query':f'sum(parceldesk_coding_sessions{{tool="{tool}"}})','expected':len({r['session_id'] for r in rows})},
                {'name':tool+' price coverage','query':f'parceldesk_coding_price_coverage{{tool="{tool}"}}','expected':len(known)/len(rows)}])
            if known:
                report['checks'].append({'name':tool+' known API-equivalent consumption','query':f'sum(parceldesk_coding_cost_usd{{tool="{tool}"}})','expected':str(sum((Decimal(r['cost_usd']) for r in known),Decimal(0)))})
            for bucket in ('input','output','cache_read','cache_write'):
                amounts=[json.loads(r['usage'])[bucket] for r in rows if json.loads(r['usage'])[bucket] is not None]
                if amounts:report['checks'].append({'name':tool+' '+bucket+' tokens','query':f'sum(parceldesk_coding_tokens_total{{tool="{tool}",type="{bucket}"}})','expected':sum(amounts)})
        report['coding_source_records']=len(records)
        if collector:
            reports=collector.reports();observations=Counter()
            for r in reports:
                for check in r['observations']:
                    if check['check']=='primary_verdict':observations[(check['evaluator_version'],r['source'],check['result'],r.get('provider','unknown'),r.get('model','unknown'),r['version'],r.get('evaluation_suite','unknown'))]+=1
            for (version,source,result,provider,model,prompt,suite),count in sorted(observations.items()):
                report['checks'].append({'name':f'Primary verdict {version}/{source}/{model}/{prompt}/{suite}/{result}','query':f'sum(parceldesk_evaluations_total{{check="primary_verdict",evaluator_version="{label(version)}",source="{label(source)}",result="{label(result)}",provider="{label(provider)}",model="{label(model)}",version="{label(prompt)}",evaluation_suite="{label(suite)}"}})','expected':count})
            report['evaluation_source_experiments']=len(reports)
            report['source_evidence']+=';evaluation-sha256:'+hashlib.sha256(encoded(reports).encode()).hexdigest()
        report['captured_at']=utcnow()
        return report


if __name__=='__main__':
    import argparse
    from .development.events import DevelopmentLedger
    ap=argparse.ArgumentParser(description='Export authentic source expectations; does not query or populate Cloud')
    ap.add_argument('--ledger',required=True,type=Path);ap.add_argument('--reports',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args()
    db=DevelopmentLedger(args.ledger)
    try:
        result=source_expectations(db,EvaluationTelemetry(db,args.reports))
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'checks':len(result['checks']),'coding_source_records':result['coding_source_records'],'evaluation_source_experiments':result['evaluation_source_experiments'],'output':str(args.output)}))
    finally:db.close()
