import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import manage
from verify_values import compare

class ManagementSafety(unittest.TestCase):
 def copy_resources(self,dest):
  for p in (manage.ROOT/'resources').rglob('*.json'):
   q=dest/p.relative_to(manage.ROOT/'resources');q.parent.mkdir(parents=True,exist_ok=True);q.write_text(p.read_text())
 def test_refuses_cross_folder_and_duplicate_resource_sets(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);self.copy_resources(root)
   p=root/'dashboards/pd-overview.json';doc=json.loads(p.read_text());doc['metadata']['annotations']['grafana.app/folder']='unrelated';p.write_text(json.dumps(doc))
   with self.assertRaisesRegex(RuntimeError,'unexpected folder'):manage.owned(root)
   self.copy_resources(root)
   p.write_text((root/'dashboards/pd-runtime.json').read_text())
   with self.assertRaisesRegex(RuntimeError,'exactly one copy'):manage.owned(root)
 def test_refuses_synthetic_or_missing_value_evidence(self):
  for fixture in ({'checks':[]},{'source_evidence':'test','synthetic':True,'checks':[{}]},{'source_evidence':'real','synthetic':False,'checks':[]}):
   with self.assertRaises(ValueError):compare('test',fixture)
 def test_missing_cloud_series_is_not_zero_or_pass(self):
  fixture={'source_evidence':'real-ledger-checksum','synthetic':False,'checks':[{'name':'real accepted tasks','query':'sum(parceldesk_development_tasks{state="accepted"})','expected':0}]}
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'evidence').mkdir()
   with patch('verify_values.ROOT',root),patch('verify_values.call',return_value={'status':'success','data':{'result':[]}}):
    result=compare('test',fixture)
    self.assertFalse(result['passed']);self.assertIsNone(result['checks'][0]['actual'])
 def test_readback_does_not_ignore_spec_difference(self):
  p,d=manage.owned(manage.ROOT/'resources')[0]
  bad=json.loads(json.dumps(d));bad['spec']['title']='silently changed'
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'evidence').mkdir()
   with patch('manage.ROOT',root),patch('manage.owned',return_value=[(p,d)]),patch('manage.resource',return_value=bad):
    with self.assertRaisesRegex(RuntimeError,'mismatch'):manage.verify('test',root)

if __name__=='__main__':unittest.main()
