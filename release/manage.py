#!/usr/bin/env python3
"""Install and recover only the ParcelDesk Compose project; credentials remain local."""
from __future__ import annotations
import argparse,datetime as dt,hashlib,importlib.util,json,os,pathlib,secrets,shutil,subprocess,sys,tarfile,urllib.request,urllib.parse
ROOT=pathlib.Path(__file__).resolve().parents[1]
STATE=ROOT/'runs'/'install'/'state.json'
PROJECT='parceldesk'
SERVICES={'web','agent-api','operations','carrier','postgres','alloy','observer'}

def run(args,*,input=None,check=True):
 result=subprocess.run([str(a) for a in args],cwd=ROOT,input=input,capture_output=True,text=True,timeout=900)
 if check and result.returncode:raise RuntimeError(f'{args[0]} {args[1] if len(args)>1 else ""} failed (exit {result.returncode}); inspect the named component locally')
 return result

def state():
 return json.loads(STATE.read_text()) if STATE.exists() else {'context':'demotests_gcloud'}

def compose(*args,override=None):
 command=['docker','compose','--project-name',PROJECT,'--file',str(ROOT/'compose.yaml')]
 candidate=override or state().get('override')
 if candidate and pathlib.Path(candidate).exists():command+=['--file',str(candidate)]
 image_override=state().get('image_override')
 if image_override and pathlib.Path(image_override).exists():command+=['--file',str(image_override)]
 return [*command,*args]

def save_state(value):STATE.parent.mkdir(parents=True,exist_ok=True);STATE.write_text(json.dumps(value,indent=2)+'\n')

def gcx(context,*args):return run(['gcx','--context',context,*args,'-o','json'])

def write_secret(name,value):
 directory=ROOT/'.secrets';directory.mkdir(mode=0o700,exist_ok=True);p=directory/name
 fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:f.write(value)

def prerequisites(context):
 missing=[tool for tool in ('docker','gcx','python3','git') if not shutil.which(tool)]
 if missing:raise RuntimeError('Missing tools: '+', '.join(missing))
 run(['docker','info','--format','{{.Architecture}}']);run(['gcx','--context',context,'config','check'])

def configure(context,profile_path):
 profile=json.loads(pathlib.Path(profile_path or ROOT/'release'/'cloud-config.example.json').read_text())
 if profile.get('context')!=context:raise RuntimeError('The nonsecret Cloud profile must name the explicitly selected gcx context')
 keys=['grafana_url','cloud_tenant','generation_endpoint','otlp_endpoint','prometheus_url','prometheus_user','loki_url','loki_user','profiles_url','profiles_user','faro_collect_url']
 if any(not profile.get(key) for key in keys):raise RuntimeError('Incomplete nonsecret Cloud profile')
 for key in keys:
  if key.endswith('url') or key.endswith('endpoint'):
   parsed=urllib.parse.urlsplit(profile[key])
   if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise RuntimeError('Cloud endpoints must be credential-free HTTPS URLs')
 for name in ('postgres_password','service_token','session_key'):
  if not (ROOT/'.secrets'/name).exists():write_secret(name,secrets.token_urlsafe(36))
 for name,env in [('cloud_token','PARCELDESK_CLOUD_TOKEN'),('profiles_token','PARCELDESK_PROFILES_TOKEN'),('gemini_key','GEMINI_API_KEY'),('anthropic_key','ANTHROPIC_API_KEY'),('openai_key','OPENAI_API_KEY')]:
  if not (ROOT/'.secrets'/name).exists():
   if os.getenv(env):write_secret(name,os.environ[env])
   elif name in ('gemini_key','anthropic_key','openai_key'):write_secret(name,'')
   else:raise RuntimeError(f'Missing .secrets/{name}; supply your target stack ingestion credential before install')
 provider=profile.get('llm_provider','anthropic')
 models={'anthropic':'claude-sonnet-4-5-20250929','gemini':'gemini-2.5-flash','openai':'gpt-4.1-mini-2025-04-14'}
 if provider not in models:raise RuntimeError('Unsupported explicit llm_provider')
 model=profile.get('llm_model') or models[provider]
 if not (ROOT/'.secrets'/(provider+'_key')).read_text().strip():raise RuntimeError('Missing credential for selected '+provider+' provider; configure it explicitly rather than falling back')
 profile['llm_provider']=provider;profile['llm_model']=model
 run([sys.executable,ROOT/'tools'/'write_env.py'])
 default=json.loads((ROOT/'release'/'cloud-config.example.json').read_text());alloy=(ROOT/'infra'/'alloy'/'config.alloy').read_text()
 # Replace only the explicit original target literals; credentials remain mounted secret references.
 for key in ['otlp_endpoint','prometheus_url','loki_url','profiles_url']:
  alloy=alloy.replace(json.dumps(default[key]),json.dumps(profile[key]))
 alloy=alloy.replace('username = '+json.dumps(default['prometheus_user']),'username = '+json.dumps(profile['prometheus_user']))
 alloy=alloy.replace('username = '+json.dumps(default['loki_user']),'username = '+json.dumps(profile['loki_user']))
 alloy=alloy.replace('username = '+json.dumps(default['cloud_tenant']),'username = '+json.dumps(profile['cloud_tenant']))
 # Profiles may use a different tenant/user even when the initial demo uses the same number.
 marker='pyroscope.write "cloud"';start=alloy.find(marker)
 if start>=0:alloy=alloy[:start]+alloy[start:].replace('username = '+json.dumps(profile['cloud_tenant']),'username = '+json.dumps(profile['profiles_user']))
 folder=ROOT/'runs'/'install';folder.mkdir(parents=True,exist_ok=True);alloy_path=folder/'config.alloy';alloy_path.write_text(alloy)
 override={'services':{'alloy':{'volumes':[str(alloy_path)+':/etc/alloy/config.alloy:ro']},'agent-api':{'environment':{'GRAFANA_URL':profile['grafana_url'],'CLOUD_TENANT':profile['cloud_tenant'],'AGENTO11Y_ENDPOINT':profile['generation_endpoint'],'LLM_PROVIDER':provider,'LLM_MODEL':model}}}}
 if provider=='openai':
  override['services']['agent-api']['secrets']=['openai_key'];override['secrets']={'openai_key':{'file':str(ROOT/'.secrets/openai_key')}}
 nginx=(ROOT/'infra/web/nginx.conf').read_text().replace(default['faro_collect_url'],profile['faro_collect_url'])
 nginx=nginx.replace(urllib.parse.urlsplit(default['faro_collect_url']).hostname,urllib.parse.urlsplit(profile['faro_collect_url']).hostname)
 nginx_path=folder/'nginx.conf';nginx_path.write_text(nginx)
 override['services']['web']={'volumes':[str(nginx_path)+':/etc/nginx/conf.d/default.conf:ro']}
 override_path=folder/'compose.override.json';override_path.write_text(json.dumps(override,indent=2)+'\n')
 sources=json.loads(gcx(context,'datasources','list').stdout).get('datasources',[]);mapping={}
 for source in sources:
  if not source.get('type'):
   source['type']=json.loads(gcx(context,'datasources','get',source['uid']).stdout).get('spec',{}).get('type','')
 for kind in ('prometheus','loki','tempo','pyroscope'):
  choices=[d for d in sources if d['type']==({'pyroscope':'grafana-pyroscope-datasource'}.get(kind,kind))]
  selected=profile.get('datasources',{}).get(kind)
  if selected:choices=[d for d in choices if d['uid']==selected]
  if len(choices)!=1:raise RuntimeError(f'Expected exactly one {kind} datasource; select defaults in the profile before installation')
  mapping[kind]=choices[0]['uid']
 # Use generation's callable interface; restore its global manifest to avoid changing another install's target.
 spec=importlib.util.spec_from_file_location('pd_dashboards',ROOT/'infra/grafana/generate.py');generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
 manifest_path=ROOT/'infra/grafana/manifest.json';prior=manifest_path.read_bytes() if manifest_path.exists() else None
 resources=folder/'dashboards'
 try:generator.generate(resources,mapping)
 finally:
  if prior is not None:manifest_path.write_bytes(prior)
  elif manifest_path.exists():manifest_path.unlink()
 local_manifest={'context':context,'server':profile['grafana_url'],'datasources':mapping,'resources':str(resources)};(folder/'dashboard-manifest.json').write_text(json.dumps(local_manifest,indent=2)+'\n')
 value={'context':context,'profile':profile,'override':str(override_path),'resources':str(resources),'installed_at':dt.datetime.now(dt.timezone.utc).isoformat()};save_state(value);return value

def initialize_baseline():
 """Only an extracted release with no own .git receives an initial source commit."""
 canonical='parceldesk-baseline'
 if (ROOT/'.git').exists():
  if run(['git','rev-parse','--verify',canonical+'^{commit}'],check=False).returncode==0:
   return {'created_repository':False,'baseline':canonical}
  legacy=run(['git','rev-parse','--verify','demo-baseline^{commit}'],check=False)
  if legacy.returncode:raise RuntimeError('Existing repository has no known baseline. Explicitly tag the reviewed demo baseline as parceldesk-baseline before installation; installer will not commit your changes.')
  run(['git','tag',canonical,legacy.stdout.strip()])
  return {'created_repository':False,'baseline':canonical,'source':'existing demo-baseline tag'}
 spec=importlib.util.spec_from_file_location('pd_release_build',ROOT/'release/build.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
 entries=builder.inspect_source(ROOT)
 if not entries:raise RuntimeError('No scanned release source to initialize')
 # An explicit init here prevents a surrounding parent repository from capturing the demo.
 run(['git','init','--initial-branch=main',str(ROOT)])
 run(['git','add','--',*[entry['path'] for entry in entries]])
 run(['git','-c','user.name=ParcelDesk Installer','-c','user.email=parceldesk@local.invalid','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false','commit','-m','Initialize scanned ParcelDesk release baseline'])
 run(['git','tag',canonical,'HEAD'])
 return {'created_repository':True,'baseline':canonical,'source_files':len(entries)}


def activate_shipped_reference(profile):
 active=ROOT/'runs/development/active.json'
 if active.exists():return {'status':'preserved_existing_activation'}
 directory=ROOT/'agents/reference/validated';manifest_path=directory/'manifest.json'
 if not manifest_path.is_file():raise RuntimeError('Release is missing the validated shipped reference manifest')
 manifest=json.loads(manifest_path.read_text());prompt=(directory/'system.md').read_bytes();code=(directory/'context.py').read_bytes()
 version=hashlib.sha256(prompt+b'\0'+code).hexdigest()[:16]
 if manifest.get('agent_version')!=version:raise RuntimeError('Shipped reference bytes differ from its manifest')
 if manifest.get('provider')!=profile['llm_provider'] or manifest.get('model')!=profile['llm_model']:raise RuntimeError('Selected provider/model differs from validated shipped reference; explicitly validate that model before selecting this reference')
 if not manifest.get('evidence_ref') or not manifest.get('experiment_id'):raise RuntimeError('Shipped reference requires its recorded validation evidence')
 target=ROOT/'runs/packages'/version;target.mkdir(parents=True,exist_ok=True)
 for name,data in [('system.md',prompt),('context.py',code)]:
  path=target/name
  if path.exists() and path.read_bytes()!=data:raise RuntimeError('Existing immutable package bytes differ')
  path.write_bytes(data)
 active.parent.mkdir(parents=True,exist_ok=True)
 value={**manifest,'mode':'shipped_reference','source':'release_reference','package_path':str(target.resolve()),'activated_at':dt.datetime.now(dt.timezone.utc).isoformat()}
 temporary=active.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(active)
 return {'status':'activated_shipped_reference','agent_version':version}


def install(args):
 prerequisites(args.context);baseline=initialize_baseline();configured=configure(args.context,args.cloud_config)
 reference=activate_shipped_reference(configured["profile"]);configured["baseline"]=baseline;configured["reference"]=reference;save_state(configured)
 run(compose('up','--detach','--build','--wait','--wait-timeout','180'))
 run(compose('exec','-T','postgres','psql','-U','parceldesk','-d','parceldesk'),input=(ROOT/'tools/observer/provision-monitor.sql').read_text())
 run([sys.executable,ROOT/'infra/grafana/manage.py','deploy','--context',args.context,'--path',configured['resources']])
 return doctor(args)

def doctor(args):
 checks=[]
 def check(name,fn):
  try:detail=fn();checks.append({'check':name,'status':'passed','detail':detail})
  except Exception as error:checks.append({'check':name,'status':'failed','detail':str(error)})
 check('docker',lambda:run(['docker','info','--format','{{.Architecture}}']).stdout.strip())
 def containers():
  result=run(compose('ps','--all','--format','json')).stdout.strip();items=json.loads(result) if result.startswith('[') else [json.loads(line) for line in result.splitlines() if line]
  live={c['Service']:c for c in items};missing=SERVICES-set(live);bad=[s for s,c in live.items() if c.get('State')!='running' or c.get('Health') in ('unhealthy','starting')]
  if missing or bad:raise RuntimeError(f'Missing: {sorted(missing)}; not ready: {bad}')
  return [{'service':s,'state':c.get('State'),'health':c.get('Health') or 'no container healthcheck'} for s,c in sorted(live.items())]
 check('containers',containers)
 check('api_and_operations_ready',lambda:run(compose('exec','-T','agent-api','python','-c',"import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=5); print(r.status)")).stdout.strip())
 check('web',lambda:urllib.request.urlopen('http://127.0.0.1:3100/health/live',timeout=5).status)
 check('presenter',lambda:urllib.request.urlopen('http://127.0.0.1:3101/control/status',timeout=5).status)
 check('observer',lambda:run(compose('exec','-T','observer','python','-c',"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9108/health',timeout=5).status)")).stdout.strip())
 def credentials():
  bad=[p.name for p in (ROOT/'.secrets').iterdir() if p.is_file() and p.stat().st_mode&0o077]
  if bad:raise RuntimeError('Secret files readable outside owner: '+', '.join(bad))
  return 'local files have owner-only permissions'
 check('secret_file_permissions',credentials)
 if not args.local_only:
  check('gcx_context',lambda:run(['gcx','--context',args.context,'config','check']).stdout.strip())
  mapping=state().get('profile',{});manifest=ROOT/'runs/install/dashboard-manifest.json';ds=json.loads(manifest.read_text())['datasources']['prometheus'] if manifest.exists() else 'grafanacloud-prom'
  for name,query in [('container_metrics','count(parceldesk_container_cpu_usage_seconds_total)'),('postgres_metrics','max(pg_up{service_name="parceldesk-postgres"})'),('application_metrics','count(parceldesk_build_info)')]:
   def verify(q=query):
    result=json.loads(gcx(args.context,'metrics','query','-d',ds,q).stdout);values=result.get('data',{}).get('result',[])
    if not values:raise RuntimeError('No recent observed series')
    if float(values[0]['value'][1])<=0:raise RuntimeError('Observed signal is not healthy')
    return {'series':len(values),'value':values[0]['value'][1]}
   check(name,verify)
 else:checks.append({'check':'cloud_signals','status':'not_checked','detail':'--local-only requested'})
 report={'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'context':args.context,'passed':all(c['status']!='failed' for c in checks),'coverage':'local only' if args.local_only else 'local and core Cloud metrics; full model/guard/eval/browser/profile verification is a separate acceptance run','checks':checks}
 (ROOT/'runs').mkdir(exist_ok=True);(ROOT/'runs/doctor.json').write_text(json.dumps(report,indent=2)+'\n');return report

def validate_archive(path):
 with tarfile.open(path,'r:gz') as archive:
  members=archive.getmembers()
  if len({m.name for m in members})!=len(members):raise RuntimeError('Duplicate archive member')
  manifest_members=[m for m in members if m.name.endswith('/RELEASE-MANIFEST.json')]
  if len(manifest_members)!=1:raise RuntimeError('Release manifest missing or duplicated')
  manifest=json.load(archive.extractfile(manifest_members[0]));prefix=manifest_members[0].name.rsplit('/',1)[0]+'/'
  expected={prefix+e['path']:e for e in manifest['files']}
  if set(m.name for m in members)!=set(expected)|{manifest_members[0].name}:raise RuntimeError('Archive differs from manifest')
  out=[]
  for member in members:
   if member.name==manifest_members[0].name:continue
   relative=pathlib.PurePosixPath(member.name[len(prefix):]);target=(ROOT/relative).resolve()
   if not member.isfile() or relative.is_absolute() or '..' in relative.parts or ROOT.resolve() not in target.parents or any(x in {'.secrets','.env','.git','runs'} for x in relative.parts):raise RuntimeError('Unsafe archive member')
   data=archive.extractfile(member).read()
   if hashlib.sha256(data).hexdigest()!=expected[member.name]['sha256']:raise RuntimeError('Archive checksum mismatch')
   out.append((relative,data,expected[member.name]['mode']))
  return manifest,out

def snapshot():
 spec=importlib.util.spec_from_file_location('pd_release_build',ROOT/'release/build.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
 folder=ROOT/'runs'/'releases'/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ');folder.mkdir(parents=True)
 bundle=builder.build('rollback',folder);dump=run(compose('exec','-T','postgres','pg_dump','-U','parceldesk','--no-owner','--no-acl','parceldesk')).stdout
 (folder/'database.sql').write_text(dump);os.chmod(folder/'database.sql',0o600)
 image_ids={}
 for cid in run(compose('ps','--quiet')).stdout.splitlines():
  detail=run(['docker','inspect','--format','{{.Image}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}',cid]).stdout.strip().split('|')
  if detail[1]!=PROJECT or detail[2] not in SERVICES:raise RuntimeError('Snapshot encountered an unowned container')
  image_ids[detail[2]]=detail[0]
 info={'archive':bundle['archive'],'sha256':bundle['sha256'],'images':image_ids,'install_state':state(),'database':str(folder/'database.sql')};(folder/'snapshot.json').write_text(json.dumps(info,indent=2)+'\n');return folder

def apply_entries(entries):
 previous=state().get('owned_source_files',[])
 target_names={str(r) for r,_,_ in entries}
 for name in previous:
  path=(ROOT/name).resolve()
  if name not in target_names and ROOT.resolve() in path.parents and path.is_file():path.unlink()
 for relative,data,mode in entries:
  target=ROOT/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(mode)
 value=state();value['owned_source_files']=sorted(target_names);value.pop('image_override',None);save_state(value)

def upgrade(args):
 manifest,entries=validate_archive(args.archive);backup=snapshot()
 apply_entries(entries)
 run(compose('up','--detach','--build','--wait','--wait-timeout','180'))
 return {'upgraded_to':manifest['version'],'rollback_snapshot':str(backup),'next_step':'Run doctor and the real journey/guard/evaluation acceptance checks before presenting'}

def rollback(args):
 folder=pathlib.Path(args.snapshot).resolve()
 if (ROOT/'runs/releases').resolve() not in folder.parents:raise RuntimeError('Rollback snapshot must belong to this project runs/releases')
 saved=json.loads((folder/'snapshot.json').read_text());archive=pathlib.Path(saved['archive'])
 if hashlib.sha256(archive.read_bytes()).hexdigest()!=saved['sha256']:raise RuntimeError('Snapshot archive checksum mismatch')
 manifest,entries=validate_archive(archive)
 current_migrations={p.name for p in (ROOT/'services/operations/migrations').glob('*.sql')};old_migrations={str(pathlib.PurePosixPath(r).name) for r,_,_ in entries if str(r).startswith('services/operations/migrations/') and str(r).endswith('.sql')}
 if current_migrations-old_migrations and not args.restore_database:raise RuntimeError('Schema version changed; explicit --restore-database is required to restore snapshot data and discard later demo writes')
 for image in saved['images'].values():run(['docker','image','inspect','--format','{{.Id}}',image])
 run(compose('stop','web','agent-api','operations','carrier','observer'))
 if args.restore_database:
  run(compose('exec','-T','postgres','psql','-U','parceldesk','-d','postgres','-v','ON_ERROR_STOP=1','-c','DROP DATABASE parceldesk WITH (FORCE)'))
  run(compose('exec','-T','postgres','psql','-U','parceldesk','-d','postgres','-v','ON_ERROR_STOP=1','-c','CREATE DATABASE parceldesk'))
  run(compose('exec','-T','postgres','psql','-U','parceldesk','-d','parceldesk','-v','ON_ERROR_STOP=1'),input=pathlib.Path(saved['database']).read_text())
 apply_entries(entries)
 for name in current_migrations-old_migrations:(ROOT/'services/operations/migrations'/name).unlink(missing_ok=True)
 override=folder/'rollback-images.json';override.write_text(json.dumps({'services':{service:{'image':image} for service,image in saved['images'].items()}},indent=2)+'\n')
 value=saved['install_state'];value['image_override']=str(override);value['owned_source_files']=[str(r) for r,_,_ in entries];save_state(value)
 run(compose('up','--detach','--no-build','--wait','--wait-timeout','180'))
 return {'restored_snapshot':str(folder),'database_restored':args.restore_database,'image_ids_restored':saved['images']}

def uninstall(args):
 if not args.owned_only:raise RuntimeError('uninstall requires --owned-only')
 # Compose labels plus the exact project file restrict removal. No global prune or Cloud deletion.
 command=compose('down','--remove-orphans')
 if args.remove_data:command.append('--volumes')
 run(command);return {'project':PROJECT,'removed':'project containers and network','data_removed':args.remove_data,'preserved':'local secrets, source, snapshots, and Grafana Cloud resources'}

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['install','doctor','upgrade','rollback','uninstall']);p.add_argument('--context',default=state().get('context','demotests_gcloud'));p.add_argument('--cloud-config',type=pathlib.Path);p.add_argument('--local-only',action='store_true');p.add_argument('--archive',type=pathlib.Path);p.add_argument('--snapshot',type=pathlib.Path);p.add_argument('--restore-database',action='store_true');p.add_argument('--owned-only',action='store_true');p.add_argument('--remove-data',action='store_true');a=p.parse_args()
 if a.action=='upgrade' and not a.archive:p.error('--archive required')
 if a.action=='rollback' and not a.snapshot:p.error('--snapshot required')
 try:result=globals()[a.action](a);print(json.dumps(result,indent=2));return 0 if result.get('passed',True) else 1
 except Exception as error:print(json.dumps({'status':'failed','reason':str(error)}),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
