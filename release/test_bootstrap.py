import hashlib,importlib.util,json,pathlib,shutil,tempfile,unittest
from unittest.mock import patch
DIR=pathlib.Path(__file__).parent
spec=importlib.util.spec_from_file_location('bootstrap_manager',DIR/'manage.py');manage=importlib.util.module_from_spec(spec);spec.loader.exec_module(manage)
class BootstrapTests(unittest.TestCase):
 def fixture(self,root):
  (root/'release').mkdir();shutil.copyfile(DIR/'build.py',root/'release/build.py');(root/'README.md').write_text('ParcelDesk test source\n');(root/'.secrets').mkdir();(root/'.secrets/cloud_token').write_text('private-bootstrap-test-secret')
 def test_extracted_bundle_creates_own_repository_not_parent(self):
  with tempfile.TemporaryDirectory() as directory:
   parent=pathlib.Path(directory);root=parent/'extracted';root.mkdir();self.fixture(root)
   with patch.object(manage,'ROOT',parent):manage.run(['git','init','--initial-branch=main'])
   with patch.object(manage,'ROOT',root):
    result=manage.initialize_baseline();self.assertTrue(result['created_repository']);self.assertEqual(pathlib.Path(manage.run(['git','rev-parse','--show-toplevel']).stdout.strip()).resolve(),root.resolve());tracked=manage.run(['git','ls-files']).stdout;self.assertNotIn('.secrets',tracked);self.assertIn('README.md',tracked);self.assertEqual(manage.initialize_baseline()['created_repository'],False)
 def test_existing_unknown_repository_is_not_committed(self):
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);self.fixture(root)
   with patch.object(manage,'ROOT',root):
    manage.run(['git','init','--initial-branch=main'])
    with self.assertRaisesRegex(RuntimeError,'installer will not commit'):manage.initialize_baseline()
    self.assertNotEqual(manage.run(['git','rev-parse','--verify','HEAD'],check=False).returncode,0)
 def test_secret_scan_precedes_repository_mutation(self):
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);self.fixture(root);(root/'README.md').write_text('private-bootstrap-test-secret')
   with patch.object(manage,'ROOT',root):
    with self.assertRaisesRegex(RuntimeError,'Credential-like'):manage.initialize_baseline()
   self.assertFalse((root/'.git').exists())
 def test_reference_verifies_content_and_model_then_preserves_existing_activation(self):
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);ref=root/'agents/reference/validated';ref.mkdir(parents=True);prompt=b'validated';code=b'def build_context(state): return state\n';(ref/'system.md').write_bytes(prompt);(ref/'context.py').write_bytes(code);version=hashlib.sha256(prompt+b'\0'+code).hexdigest()[:16];manifest={'agent_version':version,'provider':'anthropic','model':'validated-model','experiment_id':'recorded-experiment','evidence_ref':'recorded-report'};(ref/'manifest.json').write_text(json.dumps(manifest))
   with patch.object(manage,'ROOT',root):
    with self.assertRaisesRegex(RuntimeError,'provider/model differs'):manage.activate_shipped_reference({'llm_provider':'anthropic','llm_model':'another'})
    self.assertFalse((root/'runs/development/active.json').exists());result=manage.activate_shipped_reference({'llm_provider':'anthropic','llm_model':'validated-model'});self.assertEqual(result['agent_version'],version);active=root/'runs/development/active.json';data=json.loads(active.read_text());self.assertEqual(data['mode'],'shipped_reference');self.assertEqual(pathlib.Path(data['package_path']).parent,(root/'runs/packages').resolve());before=active.read_bytes();self.assertEqual(manage.activate_shipped_reference({})['status'],'preserved_existing_activation');self.assertEqual(before,active.read_bytes())
