import argparse,importlib.util,json,pathlib,subprocess,tempfile,unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('release_check',pathlib.Path(__file__).with_name('check.py'));check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
class CheckEvidenceTests(unittest.TestCase):
 def test_failed_command_stays_failed_and_cloud_is_explicitly_omitted(self):
  with tempfile.TemporaryDirectory() as directory:
   path=pathlib.Path(directory)/'report.json';args=argparse.Namespace(output=str(path),suite='quick',live=False,context='demotests_gcloud')
   with patch.object(check,'source_check',return_value={'scanned_files':2}),patch.object(check.subprocess,'run',side_effect=[subprocess.CompletedProcess([],1),subprocess.CompletedProcess([],0)]):status=check.run(args)
   result=json.loads(path.read_text());self.assertEqual(status,1);self.assertFalse(result['automated_checks_passed']);self.assertEqual(result['checks'][1]['status'],'failed');self.assertTrue(any('not run' in x for x in result['unexecuted_gates']))
 def test_credential_scan_failure_runs_no_commands_and_is_persisted(self):
  with tempfile.TemporaryDirectory() as directory:
   path=pathlib.Path(directory)/'report.json';args=argparse.Namespace(output=str(path),suite='full',live=False,context='demotests_gcloud')
   with patch.object(check,'source_check',side_effect=RuntimeError('credential-like file blocked')),patch.object(check.subprocess,'run') as run:self.assertEqual(check.run(args),1);run.assert_not_called()
   self.assertFalse(json.loads(path.read_text())['automated_checks_passed'])
