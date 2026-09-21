import pytest
from types import SimpleNamespace
from parceldesk.guards.gateway import ToolGateway

class Guard:
    def __init__(self,action='allow',fail=False,transformed=None):self.action,self.fail,self.transformed=action,fail,transformed
    def evaluate_hook(self,request):
        assert request.phase=='postflight'
        assert request.context.model.name
        assert request.input.output[0].parts[0].tool_call.name=='send_confirmation'
        if self.fail:raise ConnectionError()
        return SimpleNamespace(action=self.action,rule_id='rule',reason='blocked',transformed_input=self.transformed)
    def start_tool_execution(self,start):
        class Recorder:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def set_result(self,**kw):pass
        return Recorder()
@pytest.fixture
def ctx():return dict(demo_run_id='run',conversation_id='conv',customer_id='C1',business_date='2026-09-15',agent_version='v1',traffic_kind='probe',scenario='healthy')
@pytest.fixture
def call():return {'call_id':'c','name':'send_confirmation','arguments':{'replacement_id':'r','to':'audit@external.invalid','idempotency_key':'i'}}
@pytest.mark.asyncio
@pytest.mark.parametrize('action,fail,status',[('deny',False,'policy_denied'),('allow',True,'guard_unavailable')])
async def test_fail_closed_without_dispatch(ctx,call,action,fail,status):
    calls=[]
    async def dispatch(*a):calls.append(a);return {'status':'ok'}
    result=await ToolGateway(Guard(action,fail),dispatch).execute(ctx,call)
    assert result['status']==status and not calls
@pytest.mark.asyncio
async def test_malformed_transformation_never_dispatches(ctx,call):
    calls=[]
    async def dispatch(*a):calls.append(a)
    result=await ToolGateway(Guard(transformed=SimpleNamespace(output=[])),dispatch).execute(ctx,call)
    assert result['status']=='invalid' and not calls
@pytest.mark.asyncio
async def test_unknown_and_invalid_tools_stop_before_guard(ctx,call):
    class Never:
        def evaluate_hook(self,r):pytest.fail('Invalid tool reached remote guard')
    call['arguments']['surprise']='field'
    assert (await ToolGateway(Never(),None).execute(ctx,call))['status']=='invalid'
