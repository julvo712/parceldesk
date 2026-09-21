import argparse,hashlib,importlib.util,io,json,pathlib,tarfile,tempfile,unittest
from unittest.mock import patch
DIR=pathlib.Path(__file__).parent

def module(name):
 spec=importlib.util.spec_from_file_location('pd_'+name,DIR/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
build=module('build');manage=module('manage')
class ReleaseTests(unittest.TestCase):
 def test_source_bundle_is_reproducible_and_omits_secret_paths(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'apps').mkdir();(root/'apps/app.py').write_text('print("hello")\n');(root/'.secrets').mkdir();(root/'.secrets/cloud_token').write_text('private-unique-secret-value');(root/'.env').write_text('PRIVATE=private-unique-secret-value')
   first=build.build('test',root/'one',root);second=build.build('test',root/'two',root);self.assertEqual(first['sha256'],second['sha256'])
   with tarfile.open(first['archive']) as tar:self.assertEqual(tar.getnames(),['parceldesk-test/apps/app.py','parceldesk-test/RELEASE-MANIFEST.json'])
 def test_known_secret_value_blocks_artifact(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'apps').mkdir();(root/'.secrets').mkdir();(root/'.secrets/cloud_token').write_text('unique-private-credential-value');(root/'apps/leak.txt').write_text('unique-private-credential-value')
   with self.assertRaises(RuntimeError):build.build('test',root/'output',root)
 def test_archive_checksum_tampering_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'apps').mkdir();(root/'apps/app.py').write_text('hello');result=build.build('test',root/'out',root)
   with patch.object(manage,'ROOT',root):manifest,entries=manage.validate_archive(result['archive']);self.assertEqual(len(entries),1)
   bad=root/'bad.tar.gz'
   with tarfile.open(result['archive']) as original,tarfile.open(bad,'w:gz') as modified:
    for member in original.getmembers():
     data=original.extractfile(member).read()
     if member.name.endswith('app.py'):data=b'wrong';member.size=len(data)
     modified.addfile(member,io.BytesIO(data))
   with patch.object(manage,'ROOT',root):
    with self.assertRaises(RuntimeError):manage.validate_archive(bad)
 def test_archive_traversal_rejected_even_with_valid_checksum(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);archive=root/'bad.tar.gz';data=b'bad';entry={'path':'../escape','sha256':hashlib.sha256(data).hexdigest(),'mode':420}
   with tarfile.open(archive,'w:gz') as tar:
    for name,body in [('parceldesk-test/../escape',data),('parceldesk-test/RELEASE-MANIFEST.json',json.dumps({'files':[entry]}).encode())]:info=tarfile.TarInfo(name);info.size=len(body);tar.addfile(info,io.BytesIO(body))
   with patch.object(manage,'ROOT',root):
    with self.assertRaises(RuntimeError):manage.validate_archive(archive)
 def test_uninstall_requires_owned_flag_and_never_global_prunes(self):
  with self.assertRaises(RuntimeError):manage.uninstall(argparse.Namespace(owned_only=False,remove_data=False))
  with patch.object(manage,'run') as call,patch.object(manage,'state',return_value={}):
   manage.uninstall(argparse.Namespace(owned_only=True,remove_data=False));cmd=call.call_args.args[0];self.assertEqual(cmd[:4],['docker','compose','--project-name','parceldesk']);self.assertIn('down',cmd);self.assertNotIn('--volumes',cmd);self.assertNotIn('prune',cmd)
 def test_another_context_renders_separate_targets_without_credentials(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d)
   for folder in ['release','infra/alloy','infra/web','infra/grafana','.secrets']:(root/folder).mkdir(parents=True,exist_ok=True)
   default=json.loads((DIR/'cloud-config.example.json').read_text());(root/'release/cloud-config.example.json').write_text(json.dumps(default))
   (root/'infra/alloy/config.alloy').write_text((DIR.parent/'infra/alloy/config.alloy').read_text());(root/'infra/web/nginx.conf').write_text((DIR.parent/'infra/web/nginx.conf').read_text())
   (root/'infra/grafana/manifest.json').write_text('original manifest')
   (root/'infra/grafana/generate.py').write_text('from pathlib import Path\ndef generate(out,ds):\n out.mkdir(parents=True,exist_ok=True)\n (Path(__file__).parent/"manifest.json").write_text("changed")\n')
   for name in ['cloud_token','profiles_token','gemini_key','anthropic_key']:(root/'.secrets'/name).write_text('do-not-export-this-secret')
   profile=dict(default);profile['context']='another';profile['cloud_tenant']='99999';profile['prometheus_user']='11111';profile['loki_user']='22222';profile['profiles_user']='33333'
   for key in ['grafana_url','generation_endpoint','otlp_endpoint','prometheus_url','loki_url','profiles_url','faro_collect_url']:profile[key]='https://'+key.replace('_','-')+'.example.test/path'
   (root/'profile.json').write_text(json.dumps(profile))
   from types import SimpleNamespace
   sources={'datasources':[{'type':kind,'uid':'new-'+kind} for kind in ['prometheus','loki','tempo','grafana-pyroscope-datasource']]}
   with patch.object(manage,'ROOT',root),patch.object(manage,'STATE',root/'runs/install/state.json'),patch.object(manage,'run'),patch.object(manage,'gcx',return_value=SimpleNamespace(stdout=json.dumps(sources))):result=manage.configure('another',root/'profile.json')
   rendered=(root/'runs/install/config.alloy').read_text();self.assertIn(profile['otlp_endpoint'],rendered);self.assertNotIn(default['otlp_endpoint'],rendered);self.assertIn(profile['faro_collect_url'],(root/'runs/install/nginx.conf').read_text());self.assertEqual((root/'infra/grafana/manifest.json').read_text(),'original manifest')
   for path in (root/'runs/install').glob('*'):
    if path.is_file():self.assertNotIn('do-not-export-this-secret',path.read_text())
   self.assertEqual(result['context'],'another')
   overrides=json.loads((root/'runs/install/compose.override.json').read_text());self.assertEqual(overrides['services']['agent-api']['environment']['LLM_PROVIDER'],'anthropic')
   (root/'.secrets/anthropic_key').write_text('')
   with patch.object(manage,'ROOT',root),patch.object(manage,'STATE',root/'runs/install/state.json'),patch.object(manage,'run'),patch.object(manage,'gcx',return_value=SimpleNamespace(stdout=json.dumps(sources))):
    with self.assertRaisesRegex(RuntimeError,'Missing credential for selected anthropic'):manage.configure('another',root/'profile.json')

if __name__=='__main__':unittest.main()
