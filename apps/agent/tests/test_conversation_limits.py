import copy
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def main(monkeypatch,tmp_path):
    from parceldesk import main
    monkeypatch.setenv('ACTIVE_AGENT_MANIFEST',str(tmp_path/'active.json'))
    monkeypatch.delenv('EVALUATION_CANDIDATE',raising=False)
    monkeypatch.setattr(main.config,'MODEL','tested-model')
    monkeypatch.setattr(main.config,'PROVIDER','anthropic')
    monkeypatch.setattr(main,'locks',{})
    monkeypatch.setattr(main,'session',lambda request:{'run_id':'r','customer_id':'C1'})
    return main


def state(main,count=0):
    return {'package_path':'/snapshot','agent_version':'version','model':main.config.MODEL,
            'provider':main.config.PROVIDER,'status':'open','messages':[],
            'model_messages':[{'role':'user','content':'preserve history'}],
            'requests':{str(i):[] for i in range(count)},'events':[]}


def test_manifest_without_package_path_does_not_select_working_directory(main,monkeypatch,tmp_path):
    from parceldesk.agent.runner import package_directory
    (tmp_path/'active.json').write_text(json.dumps({'model':'tested-model','provider':'anthropic'}))
    monkeypatch.setattr(main.config,'AGENT_DIR',tmp_path/'baseline')
    assert package_directory()==tmp_path/'baseline'


@pytest.mark.asyncio
async def test_twentieth_turn_allowed_twenty_first_refused_without_truncation(main,monkeypatch):
    saved=state(main,19);invocations=[]
    async def load(*args):return saved
    async def save(*args):pass
    async def effective(*args):return {'scenario':'healthy'}
    async def run(*args):invocations.append(True);yield 'completed',{'status':'open'}
    async def connected():return False
    for name,value in [('load_state',load),('save_state',save),('effective_context',effective),('run_turn',run)]:monkeypatch.setattr(main,name,value)
    response=await main.turn('c',main.Turn(message='request twenty',request_id='nineteen'),SimpleNamespace(is_disconnected=connected))
    assert len(saved['requests'])==20 and main.locks['c'].locked()
    with pytest.raises(main.HTTPException,match='already being prepared'):
        await main.turn('c',main.Turn(message='competing',request_id='twenty'),None)
    assert [chunk async for chunk in response.body_iterator]
    before=copy.deepcopy(saved)
    with pytest.raises(main.HTTPException) as error:
        await main.turn('c',main.Turn(message='request twenty one',request_id='twenty'),None)
    assert error.value.status_code==409 and '20 turns' in error.value.detail
    assert saved==before and len(invocations)==1 and not main.locks['c'].locked()
    assert saved['model_messages']==[{'role':'user','content':'preserve history'}]


@pytest.mark.asyncio
async def test_confirmed_replay_survives_cap_legacy_model_and_never_reinvokes(main,monkeypatch):
    saved=state(main,20);saved['status']='confirmed';saved.pop('model')
    event={'event_id':'e','type':'completed','payload':{'status':'open'}}
    saved['requests']['0']=[event]
    async def load(*args):return saved
    async def forbidden(*args):pytest.fail('Replay saved or reinvoked the model')
    monkeypatch.setattr(main,'load_state',load);monkeypatch.setattr(main,'save_state',forbidden);monkeypatch.setattr(main,'run_turn',forbidden)
    response=await main.turn('c',main.Turn(message='same request',request_id='0'),None)
    chunks=[chunk async for chunk in response.body_iterator]
    assert chunks==[main.format_event(event)] and len(saved['requests'])==20
    with pytest.raises(main.HTTPException) as error:
        await main.turn('c',main.Turn(message='another request',request_id='new'),None)
    assert error.value.status_code==409 and 'already confirmed' in error.value.detail
    assert not main.locks['c'].locked()


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value',[('model','other-model'),('provider','gemini'),('model',None)])
async def test_existing_conversation_cannot_silently_change_model(main,monkeypatch,field,value):
    saved=state(main);saved[field]=value
    async def load(*args):return saved
    monkeypatch.setattr(main,'load_state',load)
    with pytest.raises(main.HTTPException) as error:
        await main.turn('c',main.Turn(message='help',request_id='new'),None)
    assert error.value.status_code==409 and 'Start a new conversation' in error.value.detail
    assert not saved['requests'] and not main.locks['c'].locked()


@pytest.mark.asyncio
async def test_mismatched_accepted_model_blocks_creation_and_degrades_readiness(main,monkeypatch,tmp_path):
    (tmp_path/'active.json').write_text(json.dumps({'model':'accepted-sonnet','provider':'anthropic'}))
    async def healthy(*args):return SimpleNamespace(is_success=True)
    monkeypatch.setattr(main,'http',SimpleNamespace(get=healthy))
    monkeypatch.setattr(main.config,'ANTHROPIC_KEY','configured');monkeypatch.setattr(main.config,'CLOUD_TOKEN','configured')
    with pytest.raises(main.HTTPException) as error:
        await main.new_conversation(main.Conversation(order_id='PD-1042'),None)
    assert error.value.status_code==409 and 'accepted evaluation' in error.value.detail
    health=await main.ready();control=await main.readiness()
    assert health.status_code==503
    assert json.loads(health.body)['checks']['accepted_model_provider'] is False
    assert control['status']=='degraded' and control['checks']['accepted_model_provider'] is False
    assert 'accepted evaluation' in control['configuration_error']


@pytest.mark.asyncio
async def test_matching_accepted_configuration_is_pinned_on_new_conversation(main,monkeypatch,tmp_path):
    source=tmp_path/'package';source.mkdir();(source/'system.md').write_text('policy');(source/'context.py').write_text('def build_context(ctx, order):return ""')
    (tmp_path/'active.json').write_text(json.dumps({'model':main.config.MODEL,'provider':main.config.PROVIDER,'package_path':str(source)}))
    monkeypatch.setenv('AGENT_PACKAGE_ROOT',str(tmp_path/'snapshots'))
    saved=[]
    async def ops(*args):return {}
    async def save(s,cid,state):saved.append(state)
    monkeypatch.setattr(main,'ops',ops);monkeypatch.setattr(main,'save_state',save)
    await main.new_conversation(main.Conversation(order_id='PD-1042'),None)
    assert saved[0]['model']=='tested-model' and saved[0]['provider']=='anthropic'
    assert saved[0]['package_path']!=str(source) and saved[0]['requests']=={}


@pytest.mark.asyncio
async def test_response_start_failure_releases_reserved_conversation_lock(main,monkeypatch):
    saved=state(main)
    async def load(*args):return saved
    async def save(*args):pass
    monkeypatch.setattr(main,'load_state',load);monkeypatch.setattr(main,'save_state',save)
    response=await main.turn('c',main.Turn(message='help',request_id='new'),None)
    async def fail_send(message):raise RuntimeError('Connection already closed')
    with pytest.raises(RuntimeError,match='Connection already closed'):
        await response({'type':'http','asgi':{'spec_version':'2.4'}},None,fail_send)
    assert not main.locks['c'].locked() and saved['requests']=={'new':[]}


@pytest.mark.asyncio
async def test_response_body_failure_closes_model_and_persists_before_unlock(main,monkeypatch):
    saved=state(main);actions=[]
    async def load(*args):return saved
    async def save(*args):assert main.locks['c'].locked();actions.append('save')
    async def effective(*args):return {'scenario':'healthy'}
    async def run(*args):
        try:yield 'status',{'message':'working'}
        finally:assert main.locks['c'].locked();actions.append('model_closed')
    for name,value in [('load_state',load),('save_state',save),('effective_context',effective),('run_turn',run)]:monkeypatch.setattr(main,name,value)
    response=await main.turn('c',main.Turn(message='help',request_id='new'),None)
    async def fail_body(message):
        if message['type']=='http.response.body':raise RuntimeError('Socket closed after start')
    with pytest.raises(RuntimeError,match='Socket closed after start'):
        await response({'type':'http','asgi':{'spec_version':'2.4'}},None,fail_body)
    assert actions[-2:]==['model_closed','save']
    assert not main.locks['c'].locked() and len(saved['requests'])==1
