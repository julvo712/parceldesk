import copy
import unittest
from coding.import_native import conversation_records
from parceldesk_demo.development.events import DevelopmentLedger
from coding.enrich_claude_usage import enrichments, selected_metadata
import json


class NativeCodingTests(unittest.TestCase):
    def source(self,provider='openai',agent='codex'):
        return {'conversation_id':'real-source-fixture','generation_count':1,'generations':[{
            'conversation_id':'real-source-fixture','generation_id':'generation-1','agent_name':agent,
            'model':{'name':'example-model','provider':provider},'completed_at':'2026-09-15T13:00:00Z',
            'usage':{'input_tokens':'100','cache_read_input_tokens':'80','output_tokens':'12'},
            'input':[{'content':'private content must never be copied'}]}]}
    def test_openai_normalizes_exclusive_input_without_double_counting_reasoning(self):
        data=self.source();data['generations'][0]['usage']['reasoning_tokens']='8'
        record=conversation_records(data)[0]
        self.assertEqual(record['usage'],{'input':20,'output':12,'cache_read':80,'cache_write':None})
        self.assertIsNone(record['estimated_cost_usd']);self.assertNotIn('private',str(record))
    def test_anthropic_input_excludes_cache(self):
        record=conversation_records(self.source('anthropic','claude-code'))[0]
        self.assertEqual(record['usage']['input'],100);self.assertEqual(record['tool'],'claude_code')
    def test_unknown_reads_do_not_become_zero_or_duplicate_inclusive_input(self):
        data=self.source();del data['generations'][0]['usage']['cache_read_input_tokens']
        usage=conversation_records(data)[0]['usage']
        self.assertIsNone(usage['input']);self.assertIsNone(usage['cache_read'])
    def test_cursor_unknown_overlap_preserves_other_measured_buckets(self):
        record=conversation_records(self.source('cursor','cursor'))[0]
        self.assertIsNone(record['usage']['input'])
        self.assertEqual(record['usage']['cache_read'],80)
        self.assertEqual(record['usage']['output'],12)
    def test_explicit_native_zero_cost_has_provenance_and_is_not_unknown(self):
        data=self.source();data['generations'][0]['cost_usd']='0.0000'
        record=conversation_records(data)[0]
        self.assertEqual(record['estimated_cost_usd'],'0.0000')
        self.assertEqual(record['price_basis'],'native-reported-usd:cost_usd')
    def test_replay_dedupes_and_source_time_is_preserved(self):
        record=conversation_records(self.source())[0];ledger=DevelopmentLedger(':memory:')
        try:
            self.assertTrue(ledger.import_session(record));self.assertFalse(ledger.import_session(record))
            row=ledger.db.execute('SELECT * FROM session_records').fetchone()
            self.assertEqual(row['source_timestamp'],'2026-09-15T13:00:00+00:00')
            self.assertEqual(ledger.db.execute('SELECT COUNT(*) FROM session_records').fetchone()[0],1)
        finally:ledger.close()
    def test_partial_mismatched_duplicate_and_synthetic_sources_fail(self):
        for change in ('partial','mismatch','duplicate','synthetic','bad_cache','unknown_provider','bool'):
            data=self.source();g=data['generations'][0]
            if change=='partial':data['generation_count']=2
            if change=='mismatch':g['conversation_id']='different'
            if change=='duplicate':data['generations'].append(copy.deepcopy(g));data['generation_count']=2
            if change=='synthetic':data['synthetic']=True
            if change=='bad_cache':g['usage']['cache_read_input_tokens']='101'
            if change=='unknown_provider':g['model']['provider']='unknown'
            if change=='bool':g['usage']['input_tokens']=True
            with self.assertRaises(ValueError,msg=change):conversation_records(data)
    def test_known_agent_cannot_be_reassigned(self):
        with self.assertRaises(ValueError):conversation_records(self.source(),tool='cursor')
    def test_enrichment_preserves_time_known_tokens_and_original_replay(self):
        record=conversation_records(self.source())[0];ledger=DevelopmentLedger(':memory:')
        try:
            ledger.import_session(record)
            args={'record_id':record['record_id'],'usage':{'cache_write':0},'cost_usd':'0.04',
                  'price_basis':'test-only-provenance','evidence_ref':'test-only-source'}
            self.assertTrue(ledger.enrich_session(**args));self.assertFalse(ledger.enrich_session(**args))
            self.assertFalse(ledger.import_session(record))
            row=ledger.db.execute('SELECT * FROM session_records').fetchone()
            self.assertEqual(row['source_timestamp'],record['source_timestamp'])
            self.assertEqual(row['cost_usd'],'0.04')
            with self.assertRaises(ValueError):ledger.enrich_session(**{**args,'usage':{'input':0}})
            with self.assertRaises(ValueError):ledger.enrich_session(**{**args,'cost_usd':'0.05'})
        finally:ledger.close()
    def claude_metadata(self):
        source=self.source('anthropic','claude-code');g=source['generations'][0]
        g['model']['name']='claude-sonnet-5';g['usage']['cache_write_input_tokens']='50'
        usage={'input_tokens':100,'output_tokens':12,'cache_read_input_tokens':80,'cache_creation_input_tokens':50,
               'cache_creation':{'ephemeral_5m_input_tokens':0,'ephemeral_1h_input_tokens':50},
               'service_tier':'standard','speed':'standard','inference_geo':'global',
               'server_tool_use':{'web_search_requests':0,'web_fetch_requests':0}}
        message={'id':'message-1','model':'claude-sonnet-5','usage':usage}
        return source,message
    def test_claude_ttl_price_join_and_metadata_only_dedup(self):
        source,message=self.claude_metadata()
        row={'type':'assistant','sessionId':source['conversation_id'],
             'message':{**message,'content':'secret transcript'}}
        messages=selected_metadata([json.dumps(row),json.dumps(row)],source['conversation_id'])
        self.assertEqual(len(messages),1);self.assertNotIn('secret',str(messages))
        records=enrichments(source,messages,'fixture-hash')
        self.assertEqual(records[0]['cost_usd'],'0.000536')
        self.assertIn('cache_write_1h_tokens',records[0]['price_basis'])
    def test_claude_missing_ttl_mismatch_and_ambiguous_join_fail(self):
        for problem in ('ttl','count','duplicate','geo'):
            source,message=self.claude_metadata();messages=[message]
            if problem=='ttl':del message['usage']['cache_creation']['ephemeral_1h_input_tokens']
            if problem=='count':message['usage']['cache_creation']['ephemeral_1h_input_tokens']=49
            if problem=='duplicate':messages.append({**message,'id':'message-2'})
            if problem=='geo':message['usage']['inference_geo']='us'
            with self.assertRaises(ValueError,msg=problem):enrichments(source,messages,'fixture-hash')


if __name__=='__main__':unittest.main()
