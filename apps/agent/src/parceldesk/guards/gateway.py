import asyncio, dataclasses, json
from agento11y import HookEvaluateRequest,HookContext,HookModel,HookInput,Message,MessageRole,Part,PartKind,ToolCall,ToolExecutionStart
from ..tools.registry import validate
from .. import telemetry,config

class ToolGateway:
    def __init__(self,client,dispatch,audit=None):self.client,self.dispatch,self.audit=client,dispatch,audit
    async def execute(self,ctx,call):
        name=call['name'];cid=call['call_id']
        try: args=validate(name,call['arguments'])
        except (ValueError,TypeError):return {'call_id':cid,'status':'invalid','data':{'reason':'Tool arguments did not match the schema'}}
        req=HookEvaluateRequest(phase='postflight',context=HookContext(model=HookModel(provider=config.PROVIDER,name=config.MODEL),agent_name='parceldesk-replacement',agent_version=ctx['agent_version'],conversation_id=ctx['conversation_id']),input=HookInput(output=[Message(role=MessageRole.ASSISTANT,parts=[Part(kind=PartKind.TOOL_CALL,tool_call=ToolCall(id=cid,name=name,input_json=json.dumps(args).encode()))])]))
        try:
            if ctx.get('scenario')=='guard_unavailable':raise ConnectionError('Injected guard transport outage')
            verdict=await asyncio.wait_for(asyncio.to_thread(self.client.evaluate_hook,req),timeout=5.5)
        except Exception:
            telemetry.guards.labels('unavailable','transport').inc();telemetry.log('guard_decision',action='unavailable',source='transport',tool=name,**ctx)
            if self.audit:await self.audit(ctx,cid,name,'guard_unavailable','Safety service unavailable')
            return {'call_id':cid,'status':'guard_unavailable','data':{'reason':'Safety service unavailable; nothing dispatched','source':'transport'}}
        action=verdict.action
        telemetry.guards.labels(action,'grafana').inc();telemetry.log('guard_decision',action=action,source='grafana',rule_id=verdict.rule_id,tool=name,**ctx)
        if action!='allow':
            if self.audit:await self.audit(ctx,cid,name,'policy_denied',verdict.reason)
            return {'call_id':cid,'status':'policy_denied','data':{'reason':verdict.reason,'rule_id':verdict.rule_id,'source':'grafana'}}
        if verdict.transformed_input is not None:
            try:
                transformed=verdict.transformed_input.output
                matches=[p.tool_call for m in transformed for p in m.parts if p.tool_call and p.tool_call.id==cid]
                if len(matches)!=1 or matches[0].name!=name:raise ValueError('Invalid transformation')
                args=validate(name,json.loads(matches[0].input_json))
            except Exception:return {'call_id':cid,'status':'invalid','data':{'reason':'Guard transformation was invalid'}}
        with self.client.start_tool_execution(ToolExecutionStart(tool_name=name,tool_call_id=cid,conversation_id=ctx['conversation_id'],agent_name='parceldesk-replacement',agent_version=ctx['agent_version'],include_content=True)) as rec:
            result=await self.dispatch(ctx,name,args,cid)
            rec.set_result(arguments=args,result=result)
        telemetry.tools.labels(name,result['status']).inc()
        telemetry.log('tool_result',tool=name,status=result['status'],**ctx)
        return result
