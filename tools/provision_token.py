"""Use the stack's supported setup proxy. Never print returned credentials."""
import json, subprocess, pathlib, os
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE='/api/plugin-proxy/grafana-agento11y-app/grafanacom-api'
def api(path,data=None):
 cmd=['gcx','--context','demotests_gcloud','api',BASE+path]
 if data is not None:cmd+=['-d','@-']
 p=subprocess.run(cmd,input=json.dumps(data) if data else None,text=True,capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr)
 return json.loads(p.stdout)
secret=ROOT/'.secrets/cloud_token'
if secret.exists(): print('Dedicated ingestion token already present'); raise SystemExit
policy=api('/v1/accesspolicies?region=prod-eu-west-2',{'name':'stack-1708469-agento11y-app-parceldesk','displayName':'ParcelDesk demo runtime','realms':[{'type':'stack','identifier':'1708469','labelPolicies':[]}],'scopes':['sigil:write','metrics:write','traces:write','logs:write']})
token=api('/v1/tokens?region=prod-eu-west-2',{'name':'stack-1708469-agento11y-app-parceldesk','accessPolicyId':policy['id'],'displayName':'ParcelDesk runtime','expiresAt':'2026-12-15T00:00:00Z'})
fd=os.open(secret,os.O_CREAT|os.O_WRONLY|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:f.write(token['token'])
(ROOT/'config/cloud-token-metadata.json').write_text(json.dumps({'policy_id':policy['id'],'token_id':token.get('id'),'expires_at':'2026-12-15T00:00:00Z','scopes':policy.get('scopes')},indent=2)+'\n')
print('Created stack-scoped runtime credential, saved mode 0600; expiry 2026-12-15')
