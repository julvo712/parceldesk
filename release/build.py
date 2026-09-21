#!/usr/bin/env python3
"""Build deterministic, credential-free source bundles and optional OCI images."""
from __future__ import annotations
import argparse,gzip,hashlib,io,json,os,pathlib,re,subprocess,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
ALLOW_DIRS={'.cursor','.github','agents','apps','config','design','docs','evals','fixtures','infra','release','services','tools','load'}
ALLOW_FILES={'CLAUDE.md','AGENTS.md','README.md','Makefile','compose.yaml','compose.test.yaml','.gitignore','.dockerignore','pyproject.toml','uv.lock'}
EXCLUDE={'node_modules','.venv','__pycache__','.pytest_cache','dist','runs','.secrets','.git','.worktrees','playwright-report','test-results','backups','evidence','verification','bin'}
SECRET_PATTERN=re.compile(rb'(?:glsa_[A-Za-z0-9_]{20,}|glc_[A-Za-z0-9_=-]{30,}|sk-ant-[A-Za-z0-9_-]{25,}|AIza[A-Za-z0-9_-]{30,})')

def files(root=ROOT):
 for p in sorted(root.rglob('*')):
  relative=p.relative_to(root)
  if not p.is_file() or p.is_symlink() or any(part in EXCLUDE for part in relative.parts):continue
  if relative.parts[0] not in ALLOW_DIRS and str(relative) not in ALLOW_FILES:continue
  if p.name.startswith('.env') or p.suffix in {'.log','.pyc'} or p.name=='.DS_Store':continue
  yield p,relative.as_posix()

def secret_values(root):
 directory=root/'.secrets'
 return [p.read_bytes().strip() for p in directory.iterdir() if p.is_file() and len(p.read_bytes().strip())>=12] if directory.exists() else []

def inspect_source(root=ROOT):
 known=secret_values(root);entries=[]
 for p,name in files(root):
  data=p.read_bytes()
  if SECRET_PATTERN.search(data) or any(value in data for value in known):raise RuntimeError(f'Credential-like content found in {name}; no bundle created')
  entries.append({'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'mode':0o755 if os.access(p,os.X_OK) else 0o644})
 return entries

def build(version='0.1.0',output=None,root=ROOT):
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',version):raise ValueError('invalid version')
 entries=inspect_source(root);source_digest=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 manifest={'schema_version':1,'version':version,'source_sha256':source_digest,'source_date_epoch':0,'files':entries,'image_build_platforms':['linux/arm64','linux/amd64'],'architecture_acceptance':'See docs/support-matrix.md and release/acceptance.json. Build targets are not runtime verification.','credentials_included':False}
 directory=pathlib.Path(output or root/'release'/'dist');directory.mkdir(parents=True,exist_ok=True);target=directory/f'parceldesk-{version}.tar.gz'
 # All timestamps, owners and ordering are fixed; an unchanged tree produces identical bytes.
 temporary=target.with_suffix(target.suffix+'.tmp')
 with temporary.open('wb') as raw:
  with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as zipped:
   with tarfile.open(fileobj=zipped,mode='w') as tar:
    for entry in entries:
     data=(root/entry['path']).read_bytes()
     if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise RuntimeError('Source changed during release build; retry after edits finish')
     info=tarfile.TarInfo(f'parceldesk-{version}/'+entry['path']);info.size=len(data);info.mode=entry['mode'];info.mtime=0;info.uid=info.gid=0;info.uname=info.gname='';tar.addfile(info,io.BytesIO(data))
    data=(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode();info=tarfile.TarInfo(f'parceldesk-{version}/RELEASE-MANIFEST.json');info.size=len(data);info.mode=0o644;info.mtime=0;tar.addfile(info,io.BytesIO(data))
 os.replace(temporary,target)
 checksum=hashlib.sha256(target.read_bytes()).hexdigest();target.with_suffix(target.suffix+'.sha256').write_text(f'{checksum}  {target.name}\n')
 return {'archive':str(target),'sha256':checksum,'files':len(entries),'source_sha256':source_digest}

def images(platforms,version,output):
 directory=pathlib.Path(output);directory.mkdir(parents=True,exist_ok=True)
 targets={'operations':('services/operations','services/operations/Dockerfile'),'agent-api':('.','apps/agent/Dockerfile'),'web':('apps/web','apps/web/Dockerfile'),'observer':('tools/observer','tools/observer/Dockerfile')}
 results=[]
 for platform in platforms:
  if platform not in ('linux/arm64','linux/amd64'):raise ValueError('unsupported image platform')
  for service,(context,dockerfile) in targets.items():
   name=f'parceldesk-{service}-{version}-{platform.split("/")[1]}.oci.tar';dest=directory/name;metadata=directory/(name+'.metadata.json')
   cmd=['docker','buildx','build','--platform',platform,'--provenance=mode=min','--metadata-file',str(metadata),'--tag',f'parceldesk/{service}:{version}','--file',str(ROOT/dockerfile),'--output',f'type=oci,dest={dest}',str(ROOT/context)]
   subprocess.run(cmd,check=True,cwd=ROOT)
   results.append({'service':service,'platform':platform,'file':name,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'build_metadata':json.loads(metadata.read_text()),'runtime_test':'not_run'})
 (directory/'images.json').write_text(json.dumps({'images':results},indent=2)+'\n');return results
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--version',default='0.1.0');parser.add_argument('--output',type=pathlib.Path);parser.add_argument('--images',action='store_true');parser.add_argument('--platform',action='append',choices=['linux/arm64','linux/amd64']);args=parser.parse_args()
 if args.images:print(json.dumps(images(args.platform or ['linux/arm64','linux/amd64'],args.version,args.output or ROOT/'release'/'dist'/'images'),indent=2))
 else:print(json.dumps(build(args.version,args.output),indent=2))
