#!/usr/bin/env python3
"""Run a fixed workload against the currently deployed build, without model calls."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    folder=ROOT/'runs/foundation'; folder.mkdir(parents=True,exist_ok=True)
    build=json.loads((folder/'deployed-build.json').read_text())
    run_id=str(uuid.uuid4())
    env={**os.environ, 'RUN_ID':run_id, 'SERVICE_VERSION':build['SERVICE_VERSION']}
    summary=folder/'k6-summary.json'
    summary.unlink(missing_ok=True)
    start=dt.datetime.now(dt.timezone.utc)
    result=subprocess.run(['docker','compose','--project-name','parceldesk','--file',str(ROOT/'compose.yaml'),
        '--file',str(ROOT/'load/compose.yaml'),'run','--rm','--no-deps','load'],cwd=ROOT,env=env)
    end=dt.datetime.now(dt.timezone.utc)
    report={'workload':'orders','run_id':run_id,'build':build,'started_at':start.isoformat(),'finished_at':end.isoformat(),
        'rate_per_second':int(env.get('RATE','10')),'duration':env.get('DURATION','2m'),'exit_code':result.returncode}
    if summary.exists():report['k6']=json.loads(summary.read_text())
    (folder/f'load-{start.strftime("%Y%m%dT%H%M%SZ")}.json').write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(result.returncode)
