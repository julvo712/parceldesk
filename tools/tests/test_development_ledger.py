import concurrent.futures
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from parceldesk_demo.development.events import DevelopmentLedger, timestamp
from parceldesk_demo.development.pricing import estimate

BASE=datetime(2026,9,15,12,tzinfo=timezone.utc)

def event(n,kind,seconds=0,task='task-1',**payload):
    return {'event_id':n,'task_id':task,'event':kind,'source_timestamp':(BASE+timedelta(seconds=seconds)).isoformat(),
            'actor':'test-presenter','tool':'codex','evidence_ref':'test-fixture:'+n,'payload':payload}

def session(s,cost='0.10',model='known',seconds=0,**extra):
    return {'session_id':s,'tool':'codex','model':model,'source_timestamp':(BASE+timedelta(seconds=seconds)).isoformat(),
            'evidence_ref':'test-session:'+s,'usage':{'input':100,'output':50,'cache_read':0,'cache_write':0},
            'estimated_cost_usd':cost,'price_basis':'provider-recorded' if cost is not None else 'unpriced',**extra}

class LedgerTests(unittest.TestCase):
    def test_native_rfc3339_fractional_seconds_normalize_on_host_python(self):
        for digits in ('1','12','123','1234','12345','123456','1234567','12345678','123456789'):
            self.assertEqual(timestamp('2026-09-15T15:11:53.'+digits+'Z'),
                             '2026-09-15T15:11:53.'+(digits+'000000')[:6]+'+00:00')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'ledger.sqlite';self.ledger=DevelopmentLedger(self.path)
    def tearDown(self):self.ledger.close();self.temp.cleanup()
    def rework(self):
        return [event('start','task_started'),event('link1','session_linked',1,session_id='session-A'),
                event('subA','candidate_submitted',10,candidate_id='A'),event('evalA','candidate_evaluated',100,candidate_id='A',result='rejected'),
                event('link2','session_linked',101,session_id='session-B'),event('subB','candidate_submitted',200,candidate_id='B'),
                event('evalB','candidate_evaluated',590,candidate_id='B',result='passed'),event('acceptB','candidate_accepted',600,candidate_id='B')]
    def test_rework_exact_cost_replay_and_persistence(self):
        self.ledger.import_session(session('session-A','0.10'));self.ledger.import_session(session('session-B','0.20'))
        for e in self.rework():
            self.assertTrue(self.ledger.append(e).inserted);self.assertFalse(self.ledger.append(e).inserted)
        s=self.ledger.summarize('task-1')
        self.assertTrue(s.accepted);self.assertEqual(s.elapsed_seconds,600);self.assertEqual(s.rejected_candidates,1)
        self.assertFalse(s.first_pass);self.assertEqual(s.estimated_cost_usd,Decimal('0.30'))
        self.ledger.close();self.ledger=DevelopmentLedger(self.path)
        self.assertEqual(self.ledger.summarize('task-1'),s)
        self.assertIn('parceldesk_development_cost_usd{coverage="accepted",tool="codex"} 0.30',self.ledger.metrics_text())
    def test_out_of_order_acceptance_is_pending_until_evidence_arrives(self):
        events=self.rework()
        self.ledger.append(events[-1]);self.assertFalse(self.ledger.summarize('task-1').accepted)
        for e in reversed(events[:-1]):self.ledger.append(e)
        self.assertTrue(self.ledger.summarize('task-1').accepted)
        self.assertEqual(self.ledger.summarize('task-1').elapsed_seconds,600)
    def test_never_accepted_and_unknown_price_remain_unknown(self):
        self.ledger.append(event('start','task_started'));self.ledger.append(event('link','session_linked',1,session_id='unknown'))
        self.ledger.import_session(session('unknown',None,model='unpriced'))
        s=self.ledger.summarize('task-1')
        self.assertFalse(s.accepted);self.assertIsNone(s.elapsed_seconds);self.assertIsNone(s.estimated_cost_usd)
        self.assertEqual(s.unpriced_records,1);self.assertIsNone(s.first_pass)
        self.assertNotIn('parceldesk_coding_cost_usd{',self.ledger.metrics_text())
        self.assertIn('parceldesk_coding_price_coverage{tool="codex"} 0',self.ledger.metrics_text())
    def test_shared_session_allocations_enforce_cap_and_preserve_cost(self):
        self.ledger.import_session(session('shared','1.00'))
        self.ledger.append(event('a','session_linked',1,task='A',session_id='shared',allocation='0.4'))
        self.ledger.append(event('b','session_linked',2,task='B',session_id='shared',allocation='0.6'))
        self.assertEqual(self.ledger.summarize('A').estimated_cost_usd,Decimal('0.400'))
        self.assertEqual(self.ledger.summarize('B').estimated_cost_usd,Decimal('0.600'))
        with self.assertRaisesRegex(ValueError,'100%'):self.ledger.append(event('c','session_linked',3,task='C',session_id='shared',allocation='0.1'))
        self.assertNotIn('C',self.ledger.task_ids())
    def test_conflicting_immutable_event_id_is_rejected(self):
        self.ledger.append(event('a','task_started'))
        with self.assertRaisesRegex(ValueError,'immutable'):self.ledger.append(event('a','task_started',1))
    def test_old_session_observation_cannot_replace_newer_usage(self):
        self.assertTrue(self.ledger.import_session(session('s','0.20',seconds=10)))
        self.assertFalse(self.ledger.import_session(session('s','0.10',seconds=0)))
        self.assertFalse(self.ledger.import_session(session('s','0.20',seconds=10)))
        self.assertIn('parceldesk_coding_cost_usd{model="known",tool="codex"} 0.20',self.ledger.metrics_text())
    def test_same_timestamp_conflicting_session_and_reassignment_rejected(self):
        r=session('s');self.ledger.import_session(r)
        with self.assertRaisesRegex(ValueError,'identical source'):self.ledger.import_session({**r,'estimated_cost_usd':'0.99'})
        with self.assertRaisesRegex(ValueError,'reassign'):self.ledger.import_session({**r,'record_id':'s:known','session_id':'other','source_timestamp':(BASE+timedelta(seconds=1)).isoformat()})
    def test_branch_deleted_or_renamed_does_not_change_explicit_commit(self):
        self.ledger.append(event('start','task_started',branch='old-branch'))
        self.ledger.append(event('commit','commit_linked',1,commit='abc123',branch='renamed-branch'))
        self.ledger.append(event('pr','pr_observed',2,url='https://github.com/example/project/pull/42'))
        s=self.ledger.summarize('task-1');self.assertEqual(s.commits,('abc123',));self.assertEqual(len(s.pull_requests),1)
    def test_terminal_cancelled_task_remains_visible(self):
        self.ledger.append(event('start','task_started'));self.ledger.append(event('end','task_closed',10,state='cancelled'))
        self.assertEqual(self.ledger.summarize('task-1').state,'cancelled')
    def test_synthetic_records_are_excluded_from_export(self):
        self.ledger.append({**event('fake','task_started'), 'synthetic':True})
        self.ledger.import_session(session('fake','999',synthetic=True))
        self.assertEqual(self.ledger.task_ids(),[]);self.assertNotIn('999',self.ledger.metrics_text())
    def test_conflicting_completed_verdict_rolls_back(self):
        self.ledger.append(event('eval1','candidate_evaluated',1,candidate_id='A',result='passed'))
        with self.assertRaisesRegex(ValueError,'Conflicting completed'):self.ledger.append(event('eval2','candidate_evaluated',2,candidate_id='A',result='rejected'))
        self.assertEqual(len(self.ledger.events()),1)
    def test_concurrent_idempotent_append(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.ledger.append(event('once','task_started')),range(20)))
        self.assertEqual(sum(r.inserted for r in results),1)
    def test_outbox_retries_without_losing_committed_event(self):
        def failing(_):raise RuntimeError('sink unavailable')
        self.ledger.event_sink=failing
        with self.assertRaises(RuntimeError):self.ledger.append(event('a','task_started'))
        self.assertEqual(len(self.ledger.events()),1)
        delivered=[];self.ledger.event_sink=delivered.append;self.ledger.flush_outbox();self.ledger.flush_outbox()
        self.assertEqual(len(delivered),1)
    def test_generation_and_cumulative_views_cannot_double_count(self):
        self.ledger.import_session(session('s'))
        with self.assertRaisesRegex(ValueError,'mix generation'):
            self.ledger.import_session(session('s',record_id='generation-1',granularity='generation'))
    def test_late_allocation_cannot_override_newer_mapping(self):
        self.ledger.import_session(session('s','1.00'))
        self.ledger.append(event('new','session_linked',20,session_id='s',allocation='0.4'))
        self.ledger.append(event('old','session_linked',10,session_id='s',allocation='0.8'))
        self.assertEqual(self.ledger.summarize('task-1').estimated_cost_usd,Decimal('0.400'))
    def test_cumulative_token_regression_is_rejected(self):
        self.ledger.import_session(session('s'))
        r=session('s',seconds=20);r['usage']['input']=50
        with self.assertRaisesRegex(ValueError,'cannot decrease'):self.ledger.import_session(r)
    def test_price_registry_exact_cache_semantics(self):
        catalog={'models':{'m':{'source_url':'https://provider.example/prices','effective_date':'2026-09-15','usd_per_million':{'input':'2','output':'10','cache_read':'.2','cache_write':'2.5'}}}}
        self.assertEqual(estimate({'input':1000000,'output':100000,'cache_read':2000000,'cache_write':0},'m',catalog),Decimal('3.4'))
        self.assertIsNone(estimate({'input':100,'output':100,'cache_read':None,'cache_write':0},'m',catalog))
        self.assertIsNone(estimate({'input':100,'output':100,'cache_read':0,'cache_write':0},'unknown',catalog))

if __name__=='__main__':unittest.main()
