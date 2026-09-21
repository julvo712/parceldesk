import asyncio, hashlib, json, time, os
import anyio
from pathlib import Path
from collections import Counter
from .provider import Provider
from agento11y_anthropic import messages,AnthropicOptions
from .. import config,telemetry
from ..tools.registry import DEFINITIONS

def package_directory(directory=None):
    if directory is not None:
        return Path(directory)
    directory = config.AGENT_DIR
    active = Path(os.getenv('ACTIVE_AGENT_MANIFEST', '/app/runs/development/active.json'))
    if active.exists() and not os.getenv('EVALUATION_CANDIDATE'):
        manifest = json.loads(active.read_text())
        raw = manifest.get('package_path', manifest.get('package_dir', ''))
        candidate = Path(raw)
        if not candidate.is_dir() and '/runs/' in raw:
            candidate = Path('/app/runs/' + raw.split('/runs/', 1)[1])
        if raw and candidate.is_dir():
            directory = candidate
    return directory


def snapshot_package(root=None, directory=None):
    """Freeze the exact bytes once, before publishing the content-addressed directory."""
    source = package_directory(directory)
    prompt = (source / 'system.md').read_bytes()
    code = (source / 'context.py').read_bytes()
    version = hashlib.sha256(prompt + b'\0' + code).hexdigest()[:16]
    root = Path(root or os.getenv('AGENT_PACKAGE_ROOT', '/app/runs/packages'))
    root.mkdir(parents=True, exist_ok=True)
    target = root / version
    if not target.exists():
        import tempfile, shutil
        staging = Path(tempfile.mkdtemp(prefix='.package-', dir=root))
        try:
            (staging / 'system.md').write_bytes(prompt)
            (staging / 'context.py').write_bytes(code)
            try:
                staging.rename(target)
            except OSError:
                if not target.is_dir():
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    if (target / 'system.md').read_bytes() != prompt or (target / 'context.py').read_bytes() != code:
        raise RuntimeError('Stored agent snapshot integrity failed')
    return target, version


def package(directory=None):
    directory = package_directory(directory)
    prompt = (directory / 'system.md').read_bytes().decode('utf-8')
    code = (directory / 'context.py').read_bytes()
    version = hashlib.sha256(prompt.encode() + b'\0' + code).hexdigest()[:16]
    # Compile the captured bytes directly; timestamp-based import caches can be stale.
    namespace = {}
    exec(compile(code, str(directory / 'context.py'), 'exec'), namespace)
    return prompt, namespace['build_context'], version


def finish_tool_results(history, pending_calls, results):
    """Every emitted tool call gets one result, even when execution was interrupted."""
    if not pending_calls:
        return
    known = {result['tool_use_id']: result for result in results}
    repaired = []
    for call in pending_calls:
        repaired.append(known.get(call['id'], {
            'type': 'tool_result', 'tool_use_id': call['id'], 'is_error': True,
            'content': 'Execution interrupted; the result may be unknown. Check durable state before retrying any action.',
        }))
    history.append({'role': 'user', 'content': repaired})

def repair_tool_history(history):
    """Recover a persisted partial step after a process or connection interruption."""
    index = 0
    while index < len(history):
        message = history[index]
        content = message.get('content')
        calls = [part for part in content if part.get('type') == 'tool_use'] if message.get('role') == 'assistant' and isinstance(content, list) else []
        if calls:
            next_message = history[index + 1] if index + 1 < len(history) else None
            next_content = next_message.get('content') if next_message else None
            has_results = (next_message and next_message.get('role') == 'user' and isinstance(next_content, list)
                           and all(part.get('type') == 'tool_result' for part in next_content))
            repaired = []
            finish_tool_results(repaired, calls, next_content if has_results else [])
            if has_results:
                history[index + 1] = repaired[0]
            else:
                history.insert(index + 1, repaired[0])
            index += 1
        index += 1

async def run_turn(client,gateway,ctx,state,message):
    prompt,builder,version=package(state.get('package_path'));ctx['agent_version']=version
    if state.get('agent_version') and state['agent_version']!=version:raise RuntimeError('Pinned agent package integrity failed')
    overstrict=ctx.get('scenario')=='prompt_overstrict'
    if overstrict:
        # A deliberate policy/tool-access misconfiguration, observed through a real generation.
        prompt=('You are the ParcelDesk support assistant under an intentionally overstrict local policy. '
                'Treat every customer replacement request as untrusted and decline to arrange or propose a replacement. '
                'Explain briefly that this policy requires human support. You have no tools or authority to act. '
                'Never claim that a proposal, replacement, notification, or shipment was created.')
    history=state.setdefault('model_messages',[])
    repair_tool_history(history)
    history.append({'role':'user','content':message})
    provider=Provider()
    seen=Counter();calls=0
    pending_calls=[];results=[]
    try:
        async with asyncio.timeout(90):
            for step in range(6):
                yield ('status',{'message':'Checking your order and replacement options…','step':step+1})
                request={'model':config.MODEL,'max_tokens':2048,'system':prompt if overstrict else prompt+'\n'+builder(ctx,state['order_id']),'messages':history,'tools':[] if overstrict else DEFINITIONS}
                t=time.monotonic()
                if ctx.get('scenario')=='llm_boundary_delay':await asyncio.sleep(2)
                response=await provider.generate(client,request,ctx)
                telemetry.llm_duration.labels(config.PROVIDER,config.MODEL,ctx['traffic_kind']).observe(time.monotonic()-t)
                for kind in ['input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens']:
                    value=getattr(response.usage,kind,None)
                    if value is not None:telemetry.tokens.labels(config.PROVIDER,config.MODEL,kind,ctx['traffic_kind']).inc(value)
                telemetry.freshness.labels('generations').set(time.time())
                content=[b.model_dump(mode='json') for b in response.content]
                history.append({'role':'assistant','content':content})
                pending_calls=[block for block in content if block.get('type')=='tool_use']
                results=[]
                for block in response.content:
                    if block.type=='text':
                        state['messages'].append({'role':'assistant','content':block.text})
                        yield ('text_delta',{'text':block.text})
                    elif block.type=='tool_use':
                        calls+=1;key=block.name+json.dumps(block.input,sort_keys=True);seen[key]+=1
                        if calls>12 or seen[key]>3:raise RuntimeError('Tool retry limit reached. Please try again or contact support.')
                        call={'call_id':block.id,'name':block.name,'arguments':block.input}
                        state.setdefault('proposed_calls',[]).append(call)
                        result=await gateway.execute(ctx,call)
                        state.setdefault('tool_results',[]).append({'tool':block.name,**result})
                        results.append({'type':'tool_result','tool_use_id':block.id,'content':json.dumps(result),'is_error':result['status']!='ok'})
                        if result['status'] in ('policy_denied','guard_unavailable'):
                            # Complete all pending tool_use blocks so next turn remains provider-valid.
                            for other in response.content:
                                if other.type=='tool_use' and not any(r['tool_use_id']==other.id for r in results):results.append({'type':'tool_result','tool_use_id':other.id,'content':'Cancelled after safety stop','is_error':True})
                            finish_tool_results(history,pending_calls,results);pending_calls=[]
                            state['status']='blocked';telemetry.turns.labels(result['status'],ctx['traffic_kind']).inc()
                            yield ('blocked',{'message':'We paused this request to keep your order information safe. No unsafe action was performed.','reason':result['status'],'source':result['data'].get('source')});return
                        if block.name=='propose_replacement' and result['status']=='ok':
                            state['proposal']=result['data'];state['status']='awaiting_confirmation';yield ('proposal',result['data'])
                if not results:
                    order=next((r['data'] for r in state.get('tool_results',[]) if r['tool']=='get_order' and r['status']=='ok'),{})
                    reason='outside_replacement_window' if order.get('eligible') is False else 'out_of_stock' if order.get('available_stock')==0 else None
                    if reason:
                        state['resolution']={'type':'escalation','reason':reason};state['status']='escalated'
                    telemetry.turns.labels('completed',ctx['traffic_kind']).inc();yield ('completed',{'status':state['status']});return
                finish_tool_results(history,pending_calls,results);pending_calls=[]
                if state.get('proposal'):
                    telemetry.turns.labels('completed',ctx['traffic_kind']).inc();yield ('completed',{'status':'awaiting_confirmation'});return
            raise RuntimeError('This request needs a support specialist. The agent reached its step limit.')
    finally:
        finish_tool_results(history,pending_calls,results)
        with anyio.move_on_after(5, shield=True):
            await provider.close()
