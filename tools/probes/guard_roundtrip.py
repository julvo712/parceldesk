import os, pathlib, json, dataclasses
root=pathlib.Path(__file__).resolve().parents[2]
os.environ['SECRETS_DIR']=str(root/'.secrets')
from agento11y import Client,ClientConfig,GenerationExportConfig,AuthConfig,ApiConfig,HooksConfig,HookEvaluateRequest,HookContext,HookModel,HookInput,Message,MessageRole,Part,PartKind,ToolCall
base='https://agento11y-prod-eu-west-2.grafana.net'
token=(root/'.secrets/cloud_token').read_text().strip()
c=Client(ClientConfig(generation_export=GenerationExportConfig(protocol='http',endpoint=base,auth=AuthConfig(mode='basic',basic_user='1708469',basic_password=token)),api=ApiConfig(endpoint=base),hooks=HooksConfig(enabled=True,phases=['postflight'],fail_open=False,timeout_seconds=5)))
results=[]
for to,expected in [('maya.chen@example.test','allow'),('audit@external.invalid','deny')]:
 req=HookEvaluateRequest(phase='postflight',context=HookContext(model=HookModel(provider='anthropic',name='claude-haiku-4-5-20251001'),agent_name='parceldesk-replacement',agent_version='compatibility-probe',conversation_id='parceldesk-guard-probe'),input=HookInput(output=[Message(role=MessageRole.ASSISTANT,parts=[Part(kind=PartKind.TOOL_CALL,tool_call=ToolCall(id='probe',name='send_confirmation',input_json=json.dumps({'to':to,'body':'synthetic fixture'}).encode()))])]))
 r=c.evaluate_hook(req);print(expected,dataclasses.asdict(r));assert r.action==expected;results.append(dataclasses.asdict(r))
(root/'runs/guard-probe.json').write_text(json.dumps(results,default=str,indent=2))
c.shutdown()
