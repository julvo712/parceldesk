import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from google.genai import types

from parceldesk.agent import runner
from parceldesk.agent.provider import Block, Provider, ensure_gemini_tool_ids

ROOT = Path(__file__).resolve().parents[3]


def make_package(path, prompt='baseline'):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'system.md').write_text(prompt)
    (path / 'context.py').write_text('def build_context(ctx, order):\n    return "selected order: " + order\n')
    return path


def test_snapshot_survives_source_and_active_manifest_changes(tmp_path, monkeypatch):
    first = make_package(tmp_path / 'first')
    second = make_package(tmp_path / 'second', 'candidate')
    manifest = tmp_path / 'active.json'
    manifest.write_text(json.dumps({'package_path': str(first)}))
    monkeypatch.setenv('ACTIVE_AGENT_MANIFEST', str(manifest))
    monkeypatch.delenv('EVALUATION_CANDIDATE', raising=False)
    frozen, version = runner.snapshot_package(tmp_path / 'snapshots')
    manifest.write_text(json.dumps({'package_path': str(second)}))
    (first / 'system.md').write_text('edited live')
    assert runner.package(frozen)[0] == 'baseline'
    assert runner.package(frozen)[2] == version
    assert runner.package()[0] == 'candidate'


def test_tampered_snapshot_is_rejected(tmp_path):
    source = make_package(tmp_path / 'source')
    frozen, _ = runner.snapshot_package(tmp_path / 'snapshots', source)
    (frozen / 'context.py').write_text('corrupted')
    with pytest.raises(RuntimeError, match='integrity'):
        runner.snapshot_package(tmp_path / 'snapshots', source)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [RuntimeError('tool down'), asyncio.CancelledError()])
async def test_interrupted_tool_batch_preserves_success_and_repairs_pending(tmp_path, monkeypatch, failure):
    package = make_package(tmp_path / 'package')
    closed = []
    class FakeProvider:
        async def generate(self, *args):
            return SimpleNamespace(content=[Block(type='tool_use', id='one', name='get_order', input={}),
                                            Block(type='tool_use', id='two', name='check_inventory', input={})],
                                   usage=SimpleNamespace())
        async def close(self):
            await asyncio.sleep(0)
            closed.append(True)
    class Gateway:
        async def execute(self, ctx, call):
            if call['call_id'] == 'two':
                raise failure
            return {'status': 'ok', 'data': {'eligible': True}}
    monkeypatch.setattr(runner, 'Provider', FakeProvider)
    state = {'package_path': str(package), 'order_id': 'PD-1042', 'messages': [], 'model_messages': []}
    ctx = {'traffic_kind': 'test'}
    with pytest.raises(type(failure)):
        async for _ in runner.run_turn(None, Gateway(), ctx, state, 'help'):
            pass
    results = state['model_messages'][-1]['content']
    assert [r['tool_use_id'] for r in results] == ['one', 'two']
    assert not results[0]['is_error'] and results[1]['is_error']
    assert 'unknown' in results[1]['content']
    assert closed == [True]


def test_restart_repair_does_not_duplicate_completed_tool_results():
    history = [{'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'one'}, {'type': 'tool_use', 'id': 'two'}]},
               {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'one', 'content': 'done', 'is_error': False}]}]
    runner.repair_tool_history(history)
    runner.repair_tool_history(history)
    assert len(history) == 2
    assert len(history[1]['content']) == 2
    assert history[1]['content'][0]['content'] == 'done'
    assert history[1]['content'][1]['is_error']


@pytest.mark.asyncio
async def test_cancelled_persistence_keeps_conversation_lock(monkeypatch):
    monkeypatch.setenv('PARCELDESK_DEVELOPMENT_DB', ':memory:')
    from parceldesk import main
    persisted = []
    lock = asyncio.Lock()
    async def save(*args):
        assert lock.locked()
        await anyio.sleep(.02)
        persisted.append(True)
        assert lock.locked()
    monkeypatch.setattr(main, 'save_state', save)
    with anyio.CancelScope() as scope:
        async with lock:
            scope.cancel()
            await main.persist_final_state({}, 'conversation', {})
            assert persisted == [True]
    assert not lock.locked()


@pytest.mark.asyncio
async def test_gemini_ids_exist_before_sdk_records_and_match_execution(monkeypatch):
    from agento11y_gemini import models
    from parceldesk import config
    monkeypatch.setattr(config, 'PROVIDER', 'gemini')
    response = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[
        types.Part(function_call=types.FunctionCall(name='get_order', args={'order_id': 'PD-1042'})),
        types.Part(function_call=types.FunctionCall(id='provider-id', name='get_order', args={})),
    ]))], usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=1, candidates_token_count=1))
    recorded = []
    async def generate(**kwargs):
        return response
    async def wrapper(observer, model, contents, config, invoke, options):
        result = await invoke(model, contents, config)
        recorded.extend(part.function_call.id for part in result.candidates[0].content.parts)
        return result
    monkeypatch.setattr(models, 'generate_content_async', wrapper)
    provider = Provider.__new__(Provider)
    provider.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    request = {'model': 'gemini-test', 'messages': [], 'tools': [], 'system': 'system', 'max_tokens': 10}
    ctx = {'conversation_id': 'c', 'agent_version': 'v', 'traffic_kind': 'test', 'demo_run_id': 'r'}
    result = await provider.generate(None, request, ctx)
    assert recorded[0] and recorded[1] == 'provider-id'
    assert [block.id for block in result.content] == recorded
    assert ensure_gemini_tool_ids(response).candidates[0].content.parts[0].function_call.id == recorded[0]


def load_evals():
    spec = importlib.util.spec_from_file_location('evaluation_runner_hardening', ROOT / 'evals/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_trial_cleanup_is_awaited_after_error_or_cancellation(cancel):
    evaluation = load_evals()
    requests = []
    async def request(method, path, body=None):
        await anyio.sleep(0)
        requests.append((method, path))
        return {}
    ctx = {'demo_run_id': 'run', 'conversation_id': 'conv', 'agent_version': 'v'}
    if cancel:
        with anyio.CancelScope() as scope:
            async with evaluation.isolated_trial(request, ctx, 'PD-1042', 'supplier_injection'):
                scope.cancel()
                await anyio.sleep(0)
    else:
        with pytest.raises(RuntimeError):
            async with evaluation.isolated_trial(request, ctx, 'PD-1042', 'supplier_injection'):
                raise RuntimeError('verifier failed')
    assert requests[-1] == ('DELETE', '/internal/runs/run/scenario')


@pytest.mark.asyncio
async def test_failed_trial_group_awaits_sibling_cleanup():
    evaluation = load_evals()
    started = asyncio.Event()
    cleaned = []
    async def sibling():
        try:
            started.set()
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(.01)
            cleaned.append(True)
    async def fail():
        await started.wait()
        raise RuntimeError('failed')
    with pytest.raises(ExceptionGroup):
        await evaluation.run_trials([sibling(), fail()])
    assert cleaned == [True]


@pytest.mark.asyncio
async def test_exporter_shutdown_attempts_all_even_when_one_fails():
    evaluation = load_evals()
    calls = []
    class Exporter:
        def __init__(self, name, fail=False): self.name, self.fail = name, fail
        def shutdown(self):
            calls.append(self.name)
            if self.fail: raise RuntimeError('failed flush')
    with pytest.raises(ExceptionGroup):
        await evaluation.shutdown_exporters(Exporter('observer', True), [Exporter('traces'), Exporter('logs')])
    assert calls == ['observer', 'traces', 'logs']

@pytest.mark.asyncio
async def test_closing_stream_after_text_repairs_unexecuted_calls(tmp_path, monkeypatch):
    package = make_package(tmp_path / 'package')
    closed = []
    class FakeProvider:
        async def generate(self, *args):
            return SimpleNamespace(content=[Block(type='text', text='Checking.'),
                                            Block(type='tool_use', id='pending', name='get_order', input={})],
                                   usage=SimpleNamespace())
        async def close(self): closed.append(True)
    class NeverDispatch:
        async def execute(self, *args): pytest.fail('Closed stream dispatched a tool')
    monkeypatch.setattr(runner, 'Provider', FakeProvider)
    state = {'package_path': str(package), 'order_id': 'PD-1042', 'messages': []}
    stream = runner.run_turn(None, NeverDispatch(), {'traffic_kind': 'test'}, state, 'help')
    assert (await anext(stream))[0] == 'status'
    assert (await anext(stream))[0] == 'text_delta'
    await stream.aclose()
    assert state['model_messages'][-1]['content'][0]['tool_use_id'] == 'pending'
    assert state['model_messages'][-1]['content'][0]['is_error']
    assert closed == [True]


@pytest.mark.asyncio
async def test_confirmed_legacy_conversation_retries_without_new_actions(monkeypatch):
    monkeypatch.setenv('PARCELDESK_DEVELOPMENT_DB', ':memory:')
    from parceldesk import main
    monkeypatch.setattr(main, 'session', lambda request: {'run_id': 'r', 'customer_id': 'C1'})
    async def ops(method, path, body=None):
        assert method == 'GET' and '/internal/proposals/p?' in path
        return {'conversation_id': 'legacy'}
    async def load(*args): return {'status': 'confirmed', 'replacement': {'replacement_id': 'persisted'}}
    monkeypatch.setattr(main, 'ops', ops)
    monkeypatch.setattr(main, 'load_state', load)
    result = await main.confirm('p', main.Confirm(idempotency_key='retry'), None)
    assert result['replacement']['replacement_id'] == 'persisted'


@pytest.mark.asyncio
async def test_legacy_turn_cannot_silently_switch_agent_version(monkeypatch):
    monkeypatch.setenv('PARCELDESK_DEVELOPMENT_DB', ':memory:')
    from parceldesk import main
    from fastapi import HTTPException
    monkeypatch.setattr(main, 'session', lambda request: {})
    async def load(*args): return {'messages': []}
    monkeypatch.setattr(main, 'load_state', load)
    with pytest.raises(HTTPException) as error:
        await main.turn('legacy', main.Turn(message='help', request_id='r'), None)
    assert error.value.status_code == 409

@pytest.mark.asyncio
async def test_overstrict_policy_replaces_system_and_disables_tools(tmp_path, monkeypatch):
    source=make_package(tmp_path/'source','Original healthy policy')
    requests=[]
    class FakeProvider:
        async def generate(self,client,request,ctx):
            requests.append(request)
            return SimpleNamespace(content=[Block(type='text',text='This policy requires human support.')],usage=SimpleNamespace())
        async def close(self):pass
    class NeverDispatch:
        async def execute(self,*args):pytest.fail('Overstrict policy exposed a callable tool')
    monkeypatch.setattr(runner,'Provider',FakeProvider)
    state={'package_path':str(source),'order_id':'PD-1042','messages':[],'status':'open'}
    async for _ in runner.run_turn(None,NeverDispatch(),{'traffic_kind':'test','scenario':'prompt_overstrict'},state,'replace my headphones'):pass
    assert requests[0]['tools']==[]
    assert 'Original healthy policy' not in requests[0]['system']
    assert 'intentionally overstrict local policy' in requests[0]['system']
    assert not state.get('proposal') and state['messages'][0]['content']=='This policy requires human support.'
