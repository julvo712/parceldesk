import json,base64,pathlib,urllib.request,urllib.error
root=pathlib.Path(__file__).resolve().parents[2];token=(root/'.secrets/cloud_token').read_text().strip()
payload={'phase':'postflight','context':{'agent_name':'parceldesk-replacement','agent_version':'probe','model':{'provider':'anthropic','name':'claude-haiku-4-5-20251001'},'conversation_id':'pd-probe'},'input':{'output':[{'role':'assistant','parts':[{'kind':'tool_call','tool_call':{'id':'probe','name':'send_confirmation','input_json':{'to':'audit@external.invalid'}}}]}]}}
for base in ['https://agento11y-prod-eu-west-2.grafana.net','https://sigil-prod-eu-west-2.grafana.net']:
 req=urllib.request.Request(base+'/api/v1/hooks:evaluate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Basic '+base64.b64encode(('1708469:'+token).encode()).decode()})
 try:
  with urllib.request.urlopen(req) as r:print(base,r.status,r.read().decode())
 except urllib.error.HTTPError as e:print(base,e.code,e.read().decode())
