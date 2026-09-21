"""SQLite event ledger for authentic development outcomes and coding consumption.

Immutable events preserve source time and ingestion time. Materialized associations
are rebuilt in source-time order so late delivery and retries cannot add activity.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import tempfile
import fcntl
import re
from functools import wraps
from typing import Callable, Optional
from .pricing import TOKEN_TYPES, estimate, money

EVENTS = {'task_started', 'session_linked', 'candidate_submitted', 'candidate_evaluated',
          'candidate_accepted', 'task_closed', 'commit_linked', 'pr_observed'}
TOOLS = {'codex', 'claude_code', 'cursor'}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Source timestamp must be an ISO timestamp with timezone')
    try:
        # Python 3.9 only accepts 3/6 fractional digits; native RFC3339 clocks
        # emit 1..9. Datetime storage has microsecond precision; retain original
        # source documents for sub-microsecond evidence.
        value=re.sub(r'(?<=:\d{2})\.(\d{1,9})(?=Z$|[+-]\d{2}:?\d{2}$)',
                     lambda match:'.'+(match.group(1)+'000000')[:6],value)
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid source timestamp') from exc
    if dt.tzinfo is None:
        raise ValueError('Source timestamp must include timezone')
    return dt.astimezone(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


@dataclass(frozen=True)
class AppendResult:
    inserted: bool
    event_id: str


@dataclass(frozen=True)
class TaskSummary:
    task_id: str
    state: str
    accepted: bool
    elapsed_seconds: Optional[float]
    rejected_candidates: int
    first_pass: Optional[bool]
    estimated_cost_usd: Optional[Decimal]
    known_cost_usd: Decimal
    unpriced_records: int
    linked_sessions: tuple
    candidate_ids: tuple
    commits: tuple
    pull_requests: tuple
    source_started_at: Optional[str]
    source_accepted_at: Optional[str]

    def to_dict(self):
        data = asdict(self)
        for key in ('estimated_cost_usd', 'known_cost_usd'):
            data[key] = str(data[key]) if data[key] is not None else None
        return data


def synchronized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class DevelopmentLedger:
    def __init__(self, path=None, event_sink: Optional[Callable] = None, publish_snapshots=True):
        self._lock = threading.RLock()
        self.path = str(path or os.getenv('PARCELDESK_DEVELOPMENT_DB', '/data/development.sqlite'))
        if self.path != ':memory:':
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS events (
          event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
          source_timestamp TEXT NOT NULL, received_timestamp TEXT NOT NULL,
          actor TEXT NOT NULL, tool TEXT, evidence_ref TEXT NOT NULL,
          synthetic INTEGER NOT NULL, payload TEXT NOT NULL, canonical TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_task_time ON events(task_id, source_timestamp, event_id);
        CREATE TABLE IF NOT EXISTS session_records (
          record_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, tool TEXT NOT NULL,
          model TEXT NOT NULL, source_timestamp TEXT NOT NULL, received_timestamp TEXT NOT NULL,
          user_name TEXT, repo TEXT, usage TEXT NOT NULL, cost_usd TEXT,
          price_basis TEXT NOT NULL, evidence_ref TEXT NOT NULL, synthetic INTEGER NOT NULL,
          canonical TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS sessions_session ON session_records(session_id);
        CREATE TABLE IF NOT EXISTS associations (
          task_id TEXT NOT NULL, relation TEXT NOT NULL, target TEXT NOT NULL,
          allocation TEXT, event_id TEXT NOT NULL REFERENCES events(event_id),
          PRIMARY KEY(task_id, relation, target));
        CREATE TABLE IF NOT EXISTS outbox (
          id TEXT PRIMARY KEY, event TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS session_enrichments (
          enrichment_id TEXT PRIMARY KEY, record_id TEXT NOT NULL,
          original_canonical TEXT NOT NULL, enriched_canonical TEXT NOT NULL,
          received_timestamp TEXT NOT NULL);
        ''')
        self.db.commit()
        self.event_sink = event_sink
        self.publish_snapshots=publish_snapshots and self.path!=':memory:'

    def close(self):
        try:self.publish_snapshot()
        finally:self.db.close()

    @synchronized
    def publish_snapshot(self):
        """Atomic host-to-container transport: no shared SQLite or mmap files.

        A separate host lock serializes publishers before they read current DB
        state. Consumers see either complete snapshot, never a partial write.
        The full append-only event spool lets a restarting consumer resume from
        its own durable acknowledgments without modifying this host database.
        """
        if not self.publish_snapshots:return
        target=Path(self.path).parent/'telemetry-snapshot.json'
        with (target.parent/'telemetry-snapshot.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            events=[json.loads(row['event']) for row in self.db.execute('SELECT event FROM outbox ORDER BY id')]
            payload={'schema_version':1,'published_at':utcnow(),'metrics':self.metrics_text(),
                     'events':[e for e in events if not e.get('synthetic',False)]}
            fd,temp=tempfile.mkstemp(prefix='.telemetry-snapshot-',dir=target.parent)
            try:
                with os.fdopen(fd,'w') as stream:
                    stream.write(encoded(payload)+'\n');stream.flush();os.fsync(stream.fileno())
                os.replace(temp,target)
            finally:
                if os.path.exists(temp):os.unlink(temp)

    @synchronized
    def append(self, event) -> AppendResult:
        e = dict(event)
        kind = e.get('event', e.get('kind'))
        if kind not in EVENTS:
            raise ValueError('Unsupported development event')
        for key in ('event_id', 'task_id', 'actor', 'evidence_ref'):
            if not isinstance(e.get(key), str) or not e[key].strip():
                raise ValueError(f'{key} is required')
        payload = e.get('payload', {})
        if not isinstance(payload, dict):
            raise ValueError('payload must be an object')
        source = timestamp(e.get('source_timestamp'))
        tool = e.get('tool')
        if tool is not None and tool not in TOOLS:
            raise ValueError('Unsupported coding tool')
        synthetic = bool(e.get('synthetic', False))
        if kind == 'session_linked':
            if not payload.get('session_id'):
                raise ValueError('session_id is required')
            allocation = money(payload.get('allocation', 1))
            if allocation > 1 or allocation == 0:
                raise ValueError('Session allocation must be > 0 and <= 1')
            payload = {**payload, 'allocation': str(allocation)}
        if kind.startswith('candidate_') and not payload.get('candidate_id'):
            raise ValueError('candidate_id is required')
        if kind == 'candidate_evaluated' and payload.get('result') not in ('passed', 'rejected', 'error', 'pending'):
            raise ValueError('Evaluation result must be explicit')
        if kind == 'task_closed' and payload.get('state') not in ('cancelled', 'failed', 'closed'):
            raise ValueError('Terminal task state must be explicit')
        if kind == 'commit_linked' and not payload.get('commit'):
            raise ValueError('Explicit commit is required')
        if kind == 'pr_observed' and not payload.get('url'):
            raise ValueError('Explicit pull-request URL is required')
        canonical = encoded(dict(event_id=e['event_id'], task_id=e['task_id'], event=kind,
                                 source_timestamp=source, actor=e['actor'], tool=tool,
                                 evidence_ref=e['evidence_ref'], synthetic=synthetic, payload=payload))
        with self.db:
            old = self.db.execute('SELECT canonical FROM events WHERE event_id=?', (e['event_id'],)).fetchone()
            if old:
                if old['canonical'] != canonical:
                    raise ValueError('Conflicting reuse of immutable event_id')
                return AppendResult(False, e['event_id'])
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            (e['event_id'], e['task_id'], kind, source, utcnow(), e['actor'], tool,
                             e['evidence_ref'], int(synthetic), encoded(payload), canonical))
            self._rebuild_associations()
            self.summarize(e['task_id'], include_synthetic=True)
            self.db.execute('INSERT INTO outbox(id,event) VALUES (?,?)', (e['event_id'], canonical))
        self.flush_outbox()
        return AppendResult(True, e['event_id'])

    def _rebuild_associations(self):
        self.db.execute('DELETE FROM associations')
        rows = self.db.execute('SELECT * FROM events ORDER BY source_timestamp,event_id').fetchall()
        for row in rows:
            p = json.loads(row['payload']);kind = row['kind']
            if kind == 'session_linked':
                relation, target, allocation = 'session', p['session_id'], p['allocation']
            elif kind == 'candidate_submitted':
                relation, target, allocation = 'candidate', p['candidate_id'], None
            elif kind == 'commit_linked':
                relation, target, allocation = 'commit', p['commit'], None
            elif kind == 'pr_observed':
                relation, target, allocation = 'pr', p['url'], None
            else:
                continue
            self.db.execute('INSERT OR REPLACE INTO associations VALUES (?,?,?,?,?)',
                            (row['task_id'], relation, target, allocation, row['event_id']))
        totals = {}
        for row in self.db.execute('SELECT target,allocation FROM associations WHERE relation="session"'):
            totals[row['target']] = totals.get(row['target'], Decimal(0)) + Decimal(row['allocation'])
        if any(v > 1 for v in totals.values()):
            raise ValueError('Explicit session allocations across tasks cannot exceed 100%')

    @synchronized
    def import_session(self, record, catalog=None):
        """Upsert a cumulative source record, or use one record_id per generation.

        Never mix those source granularities for the same session. A record may be
        updated only by a strictly newer source observation; repeats are idempotent.
        """
        r = dict(record)
        for key in ('session_id', 'model', 'evidence_ref'):
            if not isinstance(r.get(key), str) or not r[key]:
                raise ValueError(f'{key} is required')
        if r.get('tool') not in TOOLS:
            raise ValueError('Unsupported coding tool')
        granularity=r.get('granularity','generation' if r.get('record_id') else 'cumulative')
        if granularity not in ('generation','cumulative'):
            raise ValueError('Granularity must be generation or cumulative')
        r['record_id'] = r.get('record_id') or f'{r["session_id"]}:{r["model"]}'
        r['source_timestamp'] = timestamp(r.get('source_timestamp'))
        usage = {k: r.get('usage', {}).get(k) for k in TOKEN_TYPES}
        for value in usage.values():
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError('Usage must contain nonnegative integer token buckets or null')
        cost = money(r['estimated_cost_usd']) if r.get('estimated_cost_usd') is not None else estimate(usage, r['model'], catalog or {})
        basis = r.get('price_basis', 'unpriced' if cost is None else 'catalog')
        if cost is not None and basis == 'unpriced':
            raise ValueError('Priced consumption requires a price basis')
        normalized = dict(record_id=r['record_id'], session_id=r['session_id'], tool=r['tool'], model=r['model'],
                          source_timestamp=r['source_timestamp'], user=r.get('user'), repo=r.get('repo'), usage=usage,
                          estimated_cost_usd=str(cost) if cost is not None else None, price_basis=basis,
                          evidence_ref=r['evidence_ref'], synthetic=bool(r.get('synthetic', False)), granularity=granularity)
        canonical = encoded(normalized)
        with self.db:
            existing=self.db.execute('SELECT canonical FROM session_records WHERE session_id=?',(r['session_id'],)).fetchall()
            if any(json.loads(x['canonical']).get('granularity','cumulative')!=granularity for x in existing):
                raise ValueError('Do not mix generation records with cumulative records in one session')
            old = self.db.execute('SELECT * FROM session_records WHERE record_id=?', (r['record_id'],)).fetchone()
            if old:
                if old['canonical'] == canonical:
                    return False
                if self.db.execute('SELECT 1 FROM session_enrichments WHERE record_id=? AND original_canonical=?',
                                   (r['record_id'],canonical)).fetchone():
                    return False  # Native replay cannot erase separately proven enrichment.
                if any(old[k] != normalized[k] for k in ('session_id', 'tool', 'model')):
                    raise ValueError('Cannot reassign a source record to another session/tool/model')
                if old['source_timestamp'] > r['source_timestamp']:
                    return False
                if old['source_timestamp'] == r['source_timestamp']:
                    raise ValueError('Conflicting values at identical source timestamp')
                previous_usage=json.loads(old['usage'])
                if any(previous_usage.get(k) is not None and usage[k] is not None and usage[k]<previous_usage[k] for k in TOKEN_TYPES):
                    raise ValueError('Cumulative source token counters cannot decrease')
            self.db.execute('INSERT OR REPLACE INTO session_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (r['record_id'], r['session_id'], r['tool'], r['model'], r['source_timestamp'], utcnow(),
                             r.get('user'), r.get('repo'), encoded(usage), normalized['estimated_cost_usd'], basis,
                             r['evidence_ref'], int(normalized['synthetic']), canonical))
            eid = 'session:' + hashlib.sha256(canonical.encode()).hexdigest()
            self.db.execute('INSERT OR IGNORE INTO outbox(id,event) VALUES (?,?)',
                            (eid, encoded({'event':'coding_session_imported', 'event_id':eid, **normalized})))
        self.flush_outbox()
        return True

    @synchronized
    def enrich_session(self, record_id, usage, cost_usd, price_basis, evidence_ref):
        """Fill unknown metadata with separately joined source evidence.

        Preserve generation identity and original event time; never rewrite a
        known token count or existing price. The before/after audit also makes
        replay of the original native readback idempotent after enrichment.
        """
        old=self.db.execute('SELECT * FROM session_records WHERE record_id=?',(record_id,)).fetchone()
        if not old:raise ValueError('Import the native generation before enriching it')
        cost=money(cost_usd)
        if not price_basis or not evidence_ref:raise ValueError('Enrichment requires pricing and source provenance')
        before=json.loads(old['canonical']);merged=dict(before['usage'])
        for key,value in usage.items():
            if key not in TOKEN_TYPES or isinstance(value,bool) or not isinstance(value,int) or value<0:
                raise ValueError('Enrichment usage must contain known nonnegative token buckets')
            if merged.get(key) is not None and merged[key]!=value:
                raise ValueError('Enrichment cannot change a measured token count')
            merged[key]=value
        if old['cost_usd'] is not None and money(old['cost_usd'])!=cost:
            raise ValueError('Enrichment cannot replace an existing price')
        after={**before,'usage':merged,'estimated_cost_usd':str(cost),
               'price_basis':price_basis,'evidence_ref':evidence_ref}
        canonical=encoded(after)
        if old['canonical']==canonical:return False
        if old['cost_usd'] is not None:raise ValueError('Existing price provenance is immutable')
        eid='session-enrichment:'+hashlib.sha256(canonical.encode()).hexdigest()
        received=utcnow()
        with self.db:
            self.db.execute('INSERT INTO session_enrichments VALUES (?,?,?,?,?)',
                            (eid,record_id,old['canonical'],canonical,received))
            self.db.execute('UPDATE session_records SET usage=?,cost_usd=?,price_basis=?,evidence_ref=?,canonical=?,received_timestamp=? WHERE record_id=?',
                            (encoded(merged),str(cost),price_basis,evidence_ref,canonical,received,record_id))
            self.db.execute('INSERT INTO outbox(id,event) VALUES (?,?)',
                            (eid,encoded({'event':'coding_session_enriched','event_id':eid,**after})))
        self.flush_outbox()
        return True

    @synchronized
    def flush_outbox(self):
        """At-least-once telemetry delivery; event IDs make duplicates inspectable."""
        self.publish_snapshot()
        if self.event_sink is None:
            return
        for row in self.db.execute('SELECT * FROM outbox WHERE delivered=0').fetchall():
            self.event_sink(json.loads(row['event']))
            with self.db:
                self.db.execute('UPDATE outbox SET delivered=1 WHERE id=?', (row['id'],))

    @synchronized
    def events(self, task_id=None, include_synthetic=False):
        clauses = [] if include_synthetic else ['synthetic=0'];params=[]
        if task_id is not None:
            clauses.append('task_id=?');params.append(task_id)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        return [json.loads(r['canonical']) for r in self.db.execute('SELECT canonical FROM events'+where+' ORDER BY source_timestamp,event_id',params)]

    @synchronized
    def task_ids(self, include_synthetic=False):
        return sorted({e['task_id'] for e in self.events(include_synthetic=include_synthetic)})

    @synchronized
    def summarize(self, task_id, include_synthetic=False) -> TaskSummary:
        events = self.events(task_id, include_synthetic)
        start = next((e['source_timestamp'] for e in events if e['event']=='task_started'), None)
        candidates = {};evaluations={};commits=[];prs=[];sessions={};accepted_at=None;accepted_candidate=None;accepted_experiment=None;state='incomplete' if start else 'awaiting_evidence'
        for e in events:
            p=e['payload'];kind=e['event']
            if kind=='candidate_submitted':
                candidates.setdefault(p['candidate_id'], {'submitted':e['source_timestamp']})
            elif kind=='candidate_evaluated':
                c=candidates.setdefault(p['candidate_id'], {})
                key=(p['candidate_id'],p.get('experiment_id','legacy'))
                verdict=evaluations.setdefault(key,{})
                # Each native experiment is immutable; another model/run may
                # evaluate identical prompt bytes without erasing prior work.
                if 'result' not in verdict or verdict['result'] in ('pending','error'):
                    verdict.update(result=p['result'],evaluated=e['source_timestamp'])
                elif verdict['result']!=p['result'] and p['result'] in ('passed','rejected'):
                    raise ValueError('Conflicting completed candidate verdicts')
                c.update(verdict)
            elif kind=='candidate_accepted':
                if state in ('cancelled','failed','closed'):
                    raise ValueError('A terminally closed task cannot later be accepted')
                c=candidates.get(p['candidate_id'], {})
                key=(p['candidate_id'],p.get('experiment_id','legacy'))
                verdict=evaluations.get(key,{})
                if verdict.get('result')=='passed' and c.get('submitted') and start:
                    if accepted_candidate and accepted_candidate!=p['candidate_id']:
                        raise ValueError('Task has multiple accepted candidates')
                    accepted_candidate=p['candidate_id'];accepted_experiment=key;accepted_at=accepted_at or e['source_timestamp'];state='accepted'
                else:
                    state='awaiting_evidence'
            elif kind=='task_closed' and state!='accepted':state=p['state']
            elif kind=='session_linked':sessions[p['session_id']]=Decimal(p['allocation'])
            elif kind=='commit_linked':commits.append(p['commit'])
            elif kind=='pr_observed':prs.append(p['url'])
        elapsed=None
        if accepted_at and start:
            elapsed=(datetime.fromisoformat(accepted_at)-datetime.fromisoformat(start)).total_seconds()
            if elapsed<0:raise ValueError('Acceptance predates task start')
        complete=[(k,v) for k,v in evaluations.items() if v.get('result') in ('passed','rejected')]
        complete.sort(key=lambda kv:(kv[1]['evaluated'],kv[0]))
        first_pass=bool(complete and complete[0][0]==accepted_experiment and complete[0][1]['result']=='passed') if accepted_at else None
        known=Decimal(0);unknown=0;found_records=0
        for session,allocation in sessions.items():
            query='SELECT * FROM session_records WHERE session_id=?'+('' if include_synthetic else ' AND synthetic=0')
            records=self.db.execute(query,(session,)).fetchall()
            if not records:unknown+=1
            for r in records:
                found_records+=1
                if r['cost_usd'] is None:unknown+=1
                else:known+=Decimal(r['cost_usd'])*allocation
        total=known if unknown==0 and bool(sessions) and found_records else None
        return TaskSummary(task_id,state,bool(accepted_at),elapsed,sum(v.get('result')=='rejected' for v in evaluations.values()),
                           first_pass,total,known,unknown,tuple(sorted(sessions)),tuple(sorted(candidates)),tuple(sorted(set(commits))),
                           tuple(sorted(set(prs))),start,accepted_at)

    @synchronized
    def metrics_text(self):
        from .metrics import render
        return render(self)

    @synchronized
    def export_expectations(self):
        summaries=[self.summarize(t) for t in self.task_ids()]
        records=self.db.execute('SELECT canonical FROM session_records WHERE synthetic=0 ORDER BY record_id').fetchall()
        checksum=hashlib.sha256(encoded({'events':self.events(),'records':[json.loads(r[0]) for r in records]}).encode()).hexdigest()
        checks=[{'name':'Accepted tasks','query':'sum(parceldesk_development_tasks{state="accepted"})','expected':sum(s.accepted for s in summaries)},
                {'name':'Rejected candidates','query':'sum(parceldesk_development_candidates_total{outcome="rejected"})','expected':sum(s.rejected_candidates for s in summaries)}]
        return {'source_evidence':f'sqlite-ledger-sha256:{checksum}','synthetic':False,'checks':checks}
