#!/usr/bin/env python3
"""Record only immutable image metadata for the currently running owned project."""
import datetime,json,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
def call(args):return subprocess.check_output(args,cwd=ROOT,text=True).strip()
def capture():
 ids=call(['docker','compose','--project-name','parceldesk','--file',str(ROOT/'compose.yaml'),'ps','--quiet']).splitlines();images=[]
 for cid in ids:
  info=call(['docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.Image}}|{{.State.Running}}',cid]).split('|')
  if info[0]!='parceldesk':raise RuntimeError('Unowned container in image capture')
  data=json.loads(call(['docker','image','inspect','--format','{"id":"{{.Id}}","architecture":"{{.Architecture}}","os":"{{.Os}}","repo_digests":{{json .RepoDigests}}}',info[2]]));data.update(service=info[1],running=info[3]=='true');images.append(data)
 report={'schema_version':1,'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'project':'parceldesk','images':sorted(images,key=lambda row:row['service']),'note':'Local content IDs are immutable but not registry distribution references. ARM64/AMD64 OCI archives require build.py --images and their own runtime acceptance.'}
 (ROOT/'release/images.lock.json').write_text(json.dumps(report,indent=2)+'\n');return {'services':len(images),'architectures':sorted(set(x['architecture'] for x in images)),'manifest':'release/images.lock.json'}
if __name__=='__main__':print(json.dumps(capture(),indent=2))
