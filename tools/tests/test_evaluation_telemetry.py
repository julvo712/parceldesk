import json
from pathlib import Path
import tempfile
import unittest
from parceldesk_demo.development.events import DevelopmentLedger
from parceldesk_demo.telemetry import EvaluationTelemetry,normalize_report


def native(evaluator='1',passed=True):
    score={'score_key':'final','passed':passed,'evaluator_version':evaluator}
    return {'experiment':{'experiment_id':'exp-real-format','candidate':{'agent_version':'prompt-hash'},'status':'completed','result_status':'ready','suite_version':'v1'},'rows':[{'trials':[{'trial':{'trial_id':'trial-1','status':'completed'},'final_score':score,'scores':[score,{'score_key':'unsafe_attempt','passed':False,'evaluator_version':evaluator}]}]}]}

def local():
    return {'experiment_id':'exp-real-format','agent_version':'prompt-hash','status':'running','completed_cases':1,'cases':[{'trial_id':'trial-1','score':{'primary_passed':True,'unsafe_attempt':True,'prevention_passed':True}}]}

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.ledger=DevelopmentLedger(self.root/'ledger.sqlite');self.reports=self.root/'runs';self.reports.mkdir();self.logs=[];self.collector=EvaluationTelemetry(self.ledger,self.reports,self.logs.append)
    def tearDown(self):self.ledger.close();self.tmp.cleanup()
    def write(self,name,value):
        p=self.reports/name;p.write_text(json.dumps(value));return p
    def test_native_and_file_copies_do_not_duplicate_local_trials(self):
        self.write('local.json',local());self.write('native.json',native());self.write('copied-native.json',native())
        metrics=self.collector.metrics_text()
        self.assertIn('check="primary_verdict",result="pass",version="prompt-hash",evaluator_version="1",suite_version="v1",source="native",provider="unknown",model="unknown",evaluation_suite="unknown"} 1',metrics)
        self.assertNotIn('source="local"',metrics)
        self.assertEqual(sum(len(r['observations']) for r in self.collector.reports()),2)
    def test_v1_and_v2_verifiers_never_share_series(self):
        a=native();b=native('2');b['experiment']['experiment_id']='exp-other';b['rows'][0]['trials'][0]['trial']['trial_id']='trial-2'
        self.write('old.json',a);self.write('new.json',b)
        text=self.collector.metrics_text();self.assertIn('evaluator_version="1"',text);self.assertIn('evaluator_version="2"',text)
    def test_local_missing_version_is_unknown_and_unsafe_true_is_fail(self):
        self.write('local.json',local());text=self.collector.metrics_text()
        self.assertIn('check="unsafe_attempt",result="fail"',text);self.assertIn('evaluator_version="unknown"',text);self.assertIn('status="running"',text)
        self.assertNotIn('native_result_status="ready"',text)
    def test_partial_write_preserves_prior_evidence_but_exposes_error(self):
        p=self.write('native.json',native());self.collector.metrics_text();p.write_text('{"experiment":')
        text=self.collector.metrics_text();self.assertIn('parceldesk_evaluation_report_read_errors 1',text);self.assertIn('check="primary_verdict"',text)
    def test_no_report_has_no_success_series(self):
        text=self.collector.metrics_text();self.assertNotIn('parceldesk_evaluations_total{',text)
    def test_explicit_synthetic_report_excluded(self):
        self.write('synthetic.json',{**native(),'synthetic':True});self.assertEqual(self.collector.reports(),[])
    def test_logs_are_deduplicated_across_restarts(self):
        self.write('native.json',native());self.collector.refresh();self.collector.refresh();self.assertEqual(len(self.logs),1)
        self.assertNotIn('state',self.logs[0]);self.assertNotIn('cases',self.logs[0])
        another=EvaluationTelemetry(self.ledger,self.reports,self.logs.append);another.refresh();self.assertEqual(len(self.logs),1)
    def test_conflicting_primary_verdict_never_silently_passes(self):
        d=native();d['rows'][0]['trials'][0]['scores'][0]={**d['rows'][0]['trials'][0]['scores'][0],'passed':False}
        self.write('bad.json',d);text=self.collector.metrics_text();self.assertIn('result="conflict"',text);self.assertIn('status="conflicting"',text)
    def test_identical_prompt_on_different_models_stays_separate(self):
        for model in ('small-model','large-model'):
            report=native('2');report['experiment']['experiment_id']='exp-'+model
            report['experiment']['candidate'].update(model_provider='provider',model_name=model)
            self.write(model+'.json',report)
        text=self.collector.metrics_text()
        self.assertIn('source="native",provider="provider",model="small-model",evaluation_suite="unknown"} 1',text)
        self.assertIn('source="native",provider="provider",model="large-model",evaluation_suite="unknown"} 1',text)
    def test_full_and_heldout_trials_stay_separate_for_same_prompt(self):
        for suite in ('full','heldout'):
            report=native('2');report['experiment']['experiment_id']='exp-'+suite
            report['experiment']['name']='ParcelDesk '+suite+' prompt-hash'
            self.write(suite+'.json',report)
        text=self.collector.metrics_text()
        self.assertIn('evaluation_suite="full"} 1',text)
        self.assertIn('evaluation_suite="heldout"} 1',text)

if __name__=='__main__':unittest.main()
