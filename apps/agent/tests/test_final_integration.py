import time
from types import SimpleNamespace
import pytest

@pytest.fixture
def main(monkeypatch):
    monkeypatch.setenv('PARCELDESK_DEVELOPMENT_DB', ':memory:')
    from parceldesk import main
    return main


def test_controller_selection_survives_restart(main, monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'CONTROLLER_STATE', tmp_path / 'controller.json')
    monkeypatch.setattr(main, 'active_run', 'run-persisted')
    monkeypatch.setattr(main, 'active_expiry', 12345.)
    main.persist_controller_state()
    main.active_run = None
    main.active_expiry = 0
    main.restore_controller_state()
    assert main.active_run == 'run-persisted' and main.active_expiry == 12345.


@pytest.mark.asyncio
async def test_expired_server_lease_clears_stale_scenario_gauges(main, monkeypatch):
    monkeypatch.setattr(main, 'active_run', 'run')
    monkeypatch.setattr(main, 'active_expiry', time.time() + 300)
    main.telemetry.scenario.labels('supplier_injection').set(1)
    async def ops(*args): return {'scenario': 'healthy'}
    monkeypatch.setattr(main, 'ops', ops)
    assert await main.reconcile_scenario_metrics() == 'healthy'
    assert main.telemetry.scenario.labels('supplier_injection')._value.get() == 0
    assert main.telemetry.expires._value.get() == 0


@pytest.mark.asyncio
async def test_metrics_flushes_outbox_and_includes_evaluation_collector(main, monkeypatch):
    events = []
    monkeypatch.setattr(main, 'active_run', None)
    def metrics_text():
        events.append('snapshot-read-and-spool-flush')
        return 'coding_test 3\nevaluation_test 4\n'
    monkeypatch.setattr(main, 'development_collector', SimpleNamespace(metrics_text=metrics_text))
    response = await main.metrics()
    assert events == ['snapshot-read-and-spool-flush']
    assert not hasattr(main, 'ledger')
    assert b'coding_test 3\n' in response.body and b'evaluation_test 4\n' in response.body


@pytest.mark.asyncio
async def test_confirmation_uses_owned_order_recipient_not_customer_mapping(main, monkeypatch):
    monkeypatch.setattr(main, 'session', lambda request:{'run_id':'run', 'customer_id':'C2'})
    state = {'status':'awaiting_confirmation', 'agent_version':'v', 'package_path':'p', 'proposal':{}, 'messages':[]}
    async def load(*args): return state
    async def save(*args): pass
    async def effective(*args): return {'demo_run_id':'run','conversation_id':'c2-confirm','customer_id':'C2'}
    async def ops(method,path,body=None):
        return {'conversation_id':'c2-confirm','order_id':'PD-C2'} if method=='GET' else {}
    sent=[]
    class Gateway:
        def __init__(self,*args): pass
        async def execute(self,ctx,call):
            if call['name']=='get_order':return {'status':'ok','data':{'customer_email':'stored-c2@example.test'}}
            if call['name']=='create_replacement':return {'status':'ok','data':{'replacement_id':'replacement'}}
            sent.append(call['arguments']['to']);return {'status':'ok','data':{}}
    for name,value in [('load_state',load),('save_state',save),('effective_context',effective),('ops',ops),('ToolGateway',Gateway)]:monkeypatch.setattr(main,name,value)
    result=await main.confirm('proposal',main.Confirm(idempotency_key='key'),None)
    assert result['status']=='confirmed' and sent==['stored-c2@example.test']
    assert main.CUSTOMER_NAMES['C2']=='Alex Morgan'


@pytest.mark.asyncio
@pytest.mark.parametrize('action,denied,dispatch_attempted',[('deny',True,False),('allow',False,True)])
async def test_operator_probe_never_performs_business_mutation(main,monkeypatch,action,denied,dispatch_attempted):
    calls=[]
    async def ops(method,path,body=None):calls.append(path);return {}
    monkeypatch.setattr(main,'ops',ops)
    monkeypatch.setattr(main,'package',lambda:('prompt',None,'version'))
    class Guard:
        def evaluate_hook(self,request):
            assert request.phase=='postflight'
            assert b'audit@external.invalid' in request.input.output[0].parts[0].tool_call.input_json
            return SimpleNamespace(action=action,reason='operator test',rule_id='native-rule',transformed_input=None)
        def start_tool_execution(self,*args):
            class Recorder:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def set_result(self,**kw):pass
            return Recorder()
    monkeypatch.setattr(main,'client',Guard())
    result=await main.native_guard_probe()
    assert result['denied'] is denied and result['dispatch_attempted'] is dispatch_attempted
    assert result['model_invoked'] is False and result['business_actions_executed'] is False
    assert not any('/internal/tools/' in path for path in calls)


@pytest.mark.asyncio
async def test_lifespan_configures_and_shuts_down_development_exporter(main,monkeypatch):
    calls=[]
    class Exporter:
        def __init__(self,name):self.name=name
        def shutdown(self):calls.append(self.name)
    class HTTP:
        def __init__(self,**kwargs):pass
        async def aclose(self):calls.append('http')
    monkeypatch.setattr(main.config,'SESSION_KEY','test')
    monkeypatch.setattr(main.config,'SERVICE_TOKEN','test')
    monkeypatch.setattr(main,'restore_controller_state',lambda:None)
    monkeypatch.setattr(main.telemetry,'setup',lambda:(Exporter('agent'),[Exporter('traces')]))
    monkeypatch.setattr(main.httpx,'AsyncClient',HTTP)
    collector=SimpleNamespace(flush_outbox=lambda:calls.append('outbox'),shutdown=lambda:calls.append('cache'))
    def configure():
        calls.append('configured');return collector,Exporter('development')
    monkeypatch.setattr(main,'configure_development_snapshot',configure)
    async with main.lifespan(None):assert calls==['configured']
    assert calls==['configured','outbox','http','cache','development','agent','traces']
