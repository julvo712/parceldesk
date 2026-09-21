from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from parceldesk_demo.worktrees import read_native_report

class NativeReportTests(unittest.TestCase):
    def report(self):
        return {'experiment':{'experiment_id':'exp-test','candidate':{'agent_version':'abc'},'status':'completed','result_status':'ready'},
                'summary':{'completed_count':1,'pass_denominator':1},'rows':[{'trials':[{'trial':{'trial_id':'trial-one','status':'completed'},'final_score':{'score_key':'final','evaluator_id':'parceldesk-business-verifier','passed':True}}]}]}
    def read(self,r):
        with patch('parceldesk_demo.worktrees.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(r))):return read_native_report('exp-test','abc',1)
    def test_complete_primary_verdict_passes(self):self.assertTrue(self.read(self.report())['accepted'])
    def test_false_primary_is_verified_rejection(self):
        r=self.report();r['rows'][0]['trials'][0]['final_score']['passed']=False
        result=self.read(r);self.assertTrue(result['verified']);self.assertFalse(result['accepted'])
    def test_pending_wrong_candidate_and_missing_final_are_rejected(self):
        for edit in ('pending','version','score','denominator'):
            r=self.report()
            if edit=='pending':r['experiment']['result_status']='pending'
            elif edit=='version':r['experiment']['candidate']['agent_version']='other'
            elif edit=='score':r['rows'][0]['trials'][0]['final_score']={}
            else:r['summary']['pass_denominator']=0
            with self.assertRaises(ValueError):self.read(r)
    def test_failed_read_never_becomes_accepted(self):
        with patch('parceldesk_demo.worktrees.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='')):
            with self.assertRaisesRegex(RuntimeError,'unavailable'):read_native_report('exp-test','abc',1)

if __name__=='__main__':unittest.main()
