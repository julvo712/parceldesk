import asyncio, json, os, time, uuid, shutil, hashlib, sys
from pathlib import Path
from contextlib import asynccontextmanager, aclosing
import anyio
from datetime import date
from typing import Literal
import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired
from pydantic import BaseModel,ConfigDict,Field
from prometheus_client import generate_latest,CONTENT_TYPE_LATEST
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from . import config,telemetry,presenter
from .agent.runner import run_turn,package,snapshot_package
from .guards.gateway import ToolGateway
from parceldesk_demo.telemetry import configure_development_snapshot
from prometheus_client import Gauge

SCENARIOS=['healthy','supplier_injection','prompt_overstrict','llm_boundary_delay','db_lock','shipping_mapping_bug','cpu_regression','cpu_pressure','tool_retry_loop','guard_unavailable','ui_render_error']
client=None;http=None;providers=[];locks={};active_run=None
development_collector=None;development_exporter=None;active_expiry=0.0
CONTROLLER_STATE=Path(os.getenv("PARCELDESK_CONTROLLER_STATE", "/app/runs/controller.json"))
CUSTOMER_NAMES={"C1":"Maya Chen", "C2":"Alex Morgan"}
MAX_CONVERSATION_TURNS=20
signer=URLSafeTimedSerializer(config.SESSION_KEY or 'unconfigured-not-ready')

def accepted_runtime_configuration():
    """Read one accepted manifest; absence allows the initial baseline installation."""
    path=Path(os.getenv('ACTIVE_AGENT_MANIFEST','/app/runs/development/active.json'))
    if not path.exists() or os.getenv('EVALUATION_CANDIDATE'):return {},None
    try:
        manifest=json.loads(path.read_text())
        if not isinstance(manifest,dict):raise ValueError('Manifest must be an object')
    except (OSError,ValueError):return {},'The accepted agent manifest could not be read.'
    if any(key in manifest for key in ('model','provider')):
        if manifest.get('model')!=config.MODEL or manifest.get('provider')!=config.PROVIDER:
            return manifest,'The runtime model/provider does not match the accepted evaluation. Configure the evaluated model/provider before starting a new conversation.'
    return manifest,None

def validate_new_turn(state,request_id):
    if request_id in state.get('requests',{}):return
    if state.get('status')=='confirmed':
        raise HTTPException(409,'This replacement is already confirmed. Start a new conversation for another request.')
    if not all(state.get(key) for key in ('package_path','agent_version','model','provider')):
        raise HTTPException(409,'This conversation predates the agent upgrade. Start a new conversation to continue.')
    if state['model']!=config.MODEL or state['provider']!=config.PROVIDER:
        raise HTTPException(409,'The runtime model/provider changed since this conversation started. Start a new conversation to continue.')
    turns=max(len(state.get('requests',{})),sum(message.get('role')=='user' for message in state.get('messages',[])))
    if turns>=MAX_CONVERSATION_TURNS:
        raise HTTPException(409,'This conversation reached its limit of 20 turns. Start a new conversation to continue.')

class ConversationStreamingResponse(StreamingResponse):
    """Release the lock even if ASGI fails before it starts consuming the stream."""
    def __init__(self,*args,release,**kwargs):
        super().__init__(*args,**kwargs);self.release=release
    async def __call__(self,*args,**kwargs):
        try:await super().__call__(*args,**kwargs)
        finally:
            try:
                with anyio.fail_after(45,shield=True):await self.body_iterator.aclose()
            finally:self.release()

def restore_controller_state():
    global active_run,active_expiry
    if CONTROLLER_STATE.exists():
        data=json.loads(CONTROLLER_STATE.read_text())
        active_run=data.get('run_id');active_expiry=float(data.get('expires_at',0))


def persist_controller_state():
    CONTROLLER_STATE.parent.mkdir(parents=True,exist_ok=True)
    temporary=CONTROLLER_STATE.with_name(CONTROLLER_STATE.name+'.'+str(uuid.uuid4())+'.tmp')
    temporary.write_text(json.dumps({'run_id':active_run,'expires_at':active_expiry}))
    temporary.replace(CONTROLLER_STATE)


async def reconcile_scenario_metrics():
    global active_expiry
    actual='healthy'
    if active_run:
        evidence=await ops('GET',f'/internal/runs/{active_run}/evidence')
        actual=evidence.get('scenario','healthy')
        if isinstance(actual,dict):actual=actual.get('scenario','healthy')
    for name in SCENARIOS:
        telemetry.scenario.labels(name).set(int(name==actual and actual!='healthy'))
    if actual=='healthy':active_expiry=0.0
    telemetry.expires.set(active_expiry)
    return actual


@asynccontextmanager
async def lifespan(app):
    global client,http,providers,development_collector,development_exporter
    if not config.SESSION_KEY or not config.SERVICE_TOKEN:raise RuntimeError('Service and session secrets required')
    restore_controller_state()
    presenter.restore()
    client,providers=telemetry.setup()
    http=httpx.AsyncClient(base_url=config.OPS_URL,headers={'X-Service-Token':config.SERVICE_TOKEN},timeout=35)
    development_collector=development_exporter=None
    try:
        development_collector,development_exporter=configure_development_snapshot()
        yield
    finally:
        with anyio.fail_after(45,shield=True):
            try:
                if development_collector is not None:await asyncio.to_thread(development_collector.flush_outbox)
            finally:
                await http.aclose()
                for exporter in [development_collector,development_exporter,client,*providers]:
                    if exporter is not None:
                        try:await asyncio.to_thread(exporter.shutdown)
                        except Exception as error:telemetry.log('exporter_shutdown_error',error_type=type(error).__name__)
app=FastAPI(title='ParcelDesk',version='1.0.0',lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app,excluded_urls='health/.*,metrics')

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Session(Strict):customer_id:Literal['C1','C2']='C1';run_id:str|None=None
class Conversation(Strict):order_id:str
class Turn(Strict):message:str=Field(min_length=1,max_length=4000);request_id:str=Field(min_length=1,max_length=128)
class Confirm(Strict):idempotency_key:str=Field(min_length=1,max_length=128)
class ConfirmationRecipient(Confirm):
    recipient:str=Field(min_length=3,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
class Scenario(Strict):scenario:str;ttl_seconds:int=Field(default=300,ge=1,le=300)
class Run(Strict):fixture_revision:str='v1'

@app.middleware('http')
async def protect(request,call_next):
    if request.url.path == presenter.PATH:
        return await presenter.protect(request,call_next)
    if request.method in ('POST','PUT','PATCH','DELETE'):
        origin=request.headers.get('origin')
        if origin and origin not in ('http://localhost:3100','http://127.0.0.1:3100','http://localhost:3101','http://127.0.0.1:3101'):
            return JSONResponse({'detail':'Origin not allowed'},status_code=403)
    res=await call_next(request)
    if request.url.path not in ('/metrics','/health/live','/health/ready'):telemetry.http_requests.labels('parceldesk-agent',request.method,str(res.status_code)).inc()
    res.headers['X-Content-Type-Options']='nosniff';res.headers['Referrer-Policy']='same-origin'
    return res

async def ops(method,path,body=None):
    r=await http.request(method,path,json=body)
    if not r.is_success:
        # Never disclose credentials or upstream internals to customers.
        telemetry.log('operations_error',status=r.status_code,path=path)
        raise HTTPException(r.status_code if r.status_code in (400,401,403,404,409,422) else 503,'This request could not be completed. Please try again.')
    return r.json()

def session(request):
    try:return signer.loads(request.cookies.get('pd_session',''),max_age=28800)
    except (BadSignature,SignatureExpired):raise HTTPException(401,'Your demo session expired. Please sign in again.')

def context(s,conversation_id=''):
    return {'demo_run_id':s['run_id'],'customer_id':s['customer_id'],'conversation_id':conversation_id,'business_date':'2026-09-15','fixture_revision':'v1','agent_version':package()[2],'traffic_kind':s.get('traffic_kind','runtime'),'scenario':'healthy'}

async def effective_context(s,cid=''):
    c=context(s,cid)
    e=await ops('GET',f"/internal/runs/{s['run_id']}/evidence")
    scenario=e.get('scenario','healthy')
    if isinstance(scenario,dict):scenario=scenario.get('scenario','healthy')
    c['scenario']=scenario
    return c

async def dispatch(ctx,name,args,cid):
    return await ops('POST','/internal/tools/'+name,{'context':ctx,'arguments':args,'call_id':cid})

async def audit(ctx,cid,tool,status,reason):
    await ops('POST',f"/internal/runs/{ctx['demo_run_id']}/attempts",{'conversation_id':ctx['conversation_id'],'call_id':cid,'tool_name':tool,'status':status,'reason':reason,'trace_id':f'{telemetry.trace.get_current_span().get_span_context().trace_id:032x}'})

async def load_state(s,cid):
    data=await ops('GET',f"/internal/conversations/{cid}?run_id={s['run_id']}&customer_id={s['customer_id']}")
    return data.get('state',data)
async def save_state(s,cid,state):
    await ops('PUT',f'/internal/conversations/{cid}/state',{'run_id':s['run_id'],'customer_id':s['customer_id'],'state':state})

async def persist_final_state(s,cid,state):
    # Keep the conversation lock until the save finishes, including ASGI cancellation.
    with anyio.fail_after(40, shield=True):
        await save_state(s,cid,state)

def public(state):return {k:v for k,v in state.items() if k in ('conversation_id','order_id','messages','proposal','status','scenario','replacement','events')}

@app.get('/health/live')
async def live():return {'status':'ok'}
@app.get('/health/ready')
async def ready():
    r=await http.get('/health/ready')
    checks={'operations':r.is_success,'model_configured':bool({'anthropic':config.ANTHROPIC_KEY,'gemini':config.GEMINI_KEY,'openai':config.OPENAI_KEY}[config.PROVIDER]),'cloud_configured':bool(config.CLOUD_TOKEN)}
    _,mismatch=accepted_runtime_configuration();checks['accepted_model_provider']=mismatch is None
    return JSONResponse({'status':'ready' if all(checks.values()) else 'degraded','checks':checks,'configuration_error':mismatch},status_code=200 if all(checks.values()) else 503)
@app.get('/metrics')
async def metrics():
    await reconcile_scenario_metrics()
    await presenter.observe(sys.modules[__name__])
    extra=await asyncio.to_thread(development_collector.metrics_text) if development_collector is not None else ''
    return Response(generate_latest()+extra.encode(),media_type=CONTENT_TYPE_LATEST)

@app.post('/api/demo-session')
async def create_session(body:Session,response:Response):
    global active_run
    run_id=body.run_id or (active_run if body.customer_id=='C1' else None) or str(uuid.uuid4())
    await ops('POST','/internal/runs',{'run_id':run_id,'customer_id':body.customer_id,'business_date':'2026-09-15','scenario':'healthy'})
    s={'run_id':run_id,'customer_id':body.customer_id}
    response.set_cookie('pd_session',signer.dumps(s),httponly=True,samesite='strict',max_age=28800)
    return {'customer':{'customer_id':body.customer_id,'name':CUSTOMER_NAMES[body.customer_id]},'run_id':run_id}
@app.get('/api/session')
async def get_session(request:Request):return session(request)
@app.get('/api/orders')
async def orders(request:Request):
    s=session(request);data=await ops('GET',f"/internal/orders?run_id={s['run_id']}&customer_id={s['customer_id']}")
    items=data.get('orders',[]) if isinstance(data,dict) else data
    for x in items:
        x['order_id']=x.get('order_id',x.get('id'));x['product_name']=x.get('product_name',x.get('product','Arc One headphones'));x['image']='/images/headphones.webp'
    return {'orders':items,'customer':{'customer_id':s['customer_id'],'name':CUSTOMER_NAMES[s['customer_id']]}}
@app.post('/api/conversations')
async def new_conversation(body:Conversation,request:Request):
    s=session(request);cid=str(uuid.uuid4())
    manifest,mismatch=accepted_runtime_configuration()
    if mismatch:raise HTTPException(409,mismatch)
    directory=None
    if manifest:
        raw=manifest.get('package_path',manifest.get('package_dir',''));directory=Path(raw)
        if not directory.is_dir() and '/runs/' in raw:directory=Path('/app/runs/'+raw.split('/runs/',1)[1])
        if not raw or not directory.is_dir():raise HTTPException(409,'The accepted agent package is unavailable. Restore it before starting a new conversation.')
    snapshot,version=snapshot_package(directory=directory)
    await ops('POST','/internal/conversations',{'run_id':s['run_id'],'customer_id':s['customer_id'],'order_id':body.order_id,'conversation_id':cid,'agent_version':version})
    state={'agent_version':version,'package_path':str(snapshot),'model':config.MODEL,'provider':config.PROVIDER,'conversation_id':cid,'order_id':body.order_id,'messages':[],'model_messages':[],'status':'open','events':[],'requests':{}}
    await save_state(s,cid,state);return public(state)
@app.get('/api/conversations/{cid}')
async def get_conversation(cid:str,request:Request):
    s=session(request);state=await load_state(s,cid);state['scenario']=(await effective_context(s,cid))['scenario'];return public(state)

@app.post('/api/conversations/{cid}/turns')
async def turn(cid:str,body:Turn,request:Request):
    s=session(request)
    lock=locks.setdefault(cid,asyncio.Lock())
    if lock.locked():raise HTTPException(409,'A response is already being prepared.')
    await lock.acquire()
    owned=True
    def release():
        nonlocal owned
        if owned:owned=False;lock.release()
    try:
        state=await load_state(s,cid)
        validate_new_turn(state,body.request_id)
        if body.request_id in state.get('requests',{}):
            replay=[format_event(event) for event in state['requests'][body.request_id]]
            release()
            return StreamingResponse(iter(replay),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
        # Reserve the distinct request durably before sending HTTP 200 or invoking a model.
        state.setdefault('requests',{})[body.request_id]=[]
        await save_state(s,cid,state)
    except BaseException:
        release();raise
    async def stream():
        try:
            ctx=await effective_context(s,cid);state['scenario']=ctx['scenario'];state['messages'].append({'role':'user','content':body.message});events=[]
            try:
                async with aclosing(run_turn(client,ToolGateway(client,dispatch,audit),ctx,state,body.message)) as execution:
                    async for kind,payload in execution:
                        ev={'event_id':str(uuid.uuid4()),'conversation_id':cid,'request_id':body.request_id,'type':kind,'payload':payload};events.append(ev);state.setdefault('requests',{})[body.request_id]=events;await save_state(s,cid,state);yield format_event(ev)
                        if await request.is_disconnected():break
            except asyncio.CancelledError:
                state['status']='interrupted';raise
            except Exception as exc:
                telemetry.log('turn_error',error_type=type(exc).__name__,**ctx);telemetry.turns.labels('error',ctx['traffic_kind']).inc();state['status']='error'
                ev={'event_id':str(uuid.uuid4()),'conversation_id':cid,'request_id':body.request_id,'type':'error','payload':{'message':'We could not finish this request. Your order is safe. Please try again.'}};events.append(ev);state.setdefault('requests',{})[body.request_id]=events;await save_state(s,cid,state);yield format_event(ev)
            finally:
                state.setdefault('requests',{})[body.request_id]=events;state['events']=(state.get('events',[])+events)[-100:]
                await persist_final_state(s,cid,state)
        finally:release()
    return ConversationStreamingResponse(stream(),release=release,media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

def format_event(ev):return 'id: '+ev['event_id']+'\nevent: '+ev['type']+'\ndata: '+json.dumps(ev)+'\n\n'

@app.post('/api/proposals/{pid}/confirm')
async def confirm(pid:str,body:Confirm,request:Request):
    s=session(request)
    proposal=await ops('GET',f"/internal/proposals/{pid}?run_id={s['run_id']}&customer_id={s['customer_id']}")
    async with locks.setdefault(proposal['conversation_id'],asyncio.Lock()):
        pinned=await load_state(s,proposal['conversation_id'])
        if pinned.get('status')=='confirmed':return {'status':'confirmed','message':'Replacement confirmed','replacement':pinned.get('replacement')}
        if not pinned.get('package_path') or not pinned.get('agent_version'):
            raise HTTPException(409,'This conversation predates the agent upgrade. Start a new conversation to continue.')
        ctx=await effective_context(s,proposal['conversation_id'])
        data=await ops('POST',f'/internal/proposals/{pid}/confirm',{'context':ctx,'idempotency_key':body.idempotency_key})
        cid=proposal['conversation_id']
        ctx['conversation_id']=cid or ''
        ctx['agent_version']=pinned['agent_version']
        gateway=ToolGateway(client,dispatch,audit)
        owned_order=await gateway.execute(ctx,{'call_id':str(uuid.uuid4()),'name':'get_order','arguments':{'order_id':proposal['order_id']}})
        recipient=owned_order.get('data',{}).get('customer_email')
        if owned_order['status']!='ok' or not recipient:raise HTTPException(503,'The owned customer address could not be verified.')
        replacement=await gateway.execute(ctx,{'call_id':str(uuid.uuid4()),'name':'create_replacement','arguments':{'proposal_id':pid,'idempotency_key':body.idempotency_key}})
        if replacement['status']!='ok':raise HTTPException(503,'Replacement could not be completed safely. Please retry.')
        rd=replacement['data'];rid=rd.get('replacement_id',rd.get('id'))
        notify=await gateway.execute(ctx,{'call_id':str(uuid.uuid4()),'name':'send_confirmation','arguments':{'replacement_id':rid,'to':recipient,'idempotency_key':body.idempotency_key,'body':'Your replacement is confirmed.'}})
        if notify['status']!='ok':raise HTTPException(503,'Replacement recorded; confirmation is pending. Retry safely.')
        if cid:
            state=await load_state(s,cid);state['status']='confirmed';state['replacement']=rd;state['proposal']['status']='confirmed';state['messages'].append({'role':'assistant','content':'Replacement confirmed. Your confirmation has been recorded in the demo notification inbox.'});await save_state(s,cid,state)
        return {'status':'confirmed','message':'Replacement confirmed','replacement':rd,'notification':notify['data']}

@app.post('/api/conversations/{cid}/confirmation')
async def send_customer_confirmation(cid:str,body:ConfirmationRecipient,request:Request):
    """Apply the existing remote guard and business boundary to a customer request."""
    s=session(request)
    async with locks.setdefault(cid,asyncio.Lock()):
        state=await load_state(s,cid)  # Ownership is enforced by operations.
        replacement=state.get('replacement') or {}
        rid=replacement.get('replacement_id',replacement.get('id'))
        if state.get('status')!='confirmed' or not rid:
            raise HTTPException(409,'Confirm your replacement before requesting its confirmation.')
        ctx=await effective_context(s,cid);ctx['agent_version']=state['agent_version']
        result=await ToolGateway(client,dispatch,audit).execute(ctx,{
            'call_id':str(uuid.uuid4()),'name':'send_confirmation','arguments':{
                'replacement_id':rid,'to':body.recipient.strip().lower(),
                'idempotency_key':body.idempotency_key,'body':'Your replacement is confirmed.'}})
        status=result['status']
        if status=='policy_denied':
            return {'status':'blocked','message':'This address is not authorized to receive your order details. Nothing was sent. Use the verified email address on your account.'}
        if status=='guard_unavailable':
            return {'status':'unavailable','message':'We could not verify this request safely. Nothing was sent. Please try again shortly.'}
        if status!='ok':
            return {'status':'blocked','message':'We could not authorize this confirmation. Nothing was sent. Use the verified email address on your account.'}
        return {'status':'recorded','message':'Your confirmation is recorded for your verified account address.'}

@app.get('/control/status')
async def control_status():
    return {'run_id':active_run,'scenario':'healthy' if not active_run else (await ops('GET',f'/internal/runs/{active_run}/evidence')).get('scenario','healthy'),'agent_version':package()[2],'model':config.MODEL,'grafana_url':config.GRAPH_URL,'scenarios':SCENARIOS}
@app.post('/control/runs')
async def control_new(body:Run):
    global active_run,active_expiry
    created=str(uuid.uuid4());await ops('POST','/internal/runs',{'run_id':created,'customer_id':'C1','business_date':'2026-09-15','scenario':'healthy'})
    active_run=created;active_expiry=0.0;persist_controller_state()
    telemetry.last_reset.set(time.time());return {'run_id':active_run,'demo_run_id':active_run,'scenario':'healthy','agent_version':package()[2]}
@app.post('/control/runs/{rid}/scenario')
async def scenario_on(rid:str,body:Scenario):
    global active_expiry
    if body.scenario not in SCENARIOS:raise HTTPException(422,'Unknown scenario')
    result=await ops('POST',f'/internal/runs/{rid}/scenario',body.model_dump())
    if rid==active_run:active_expiry=time.time()+body.ttl_seconds;persist_controller_state()
    await reconcile_scenario_metrics()
    return result
@app.delete('/control/runs/{rid}/scenario')
async def scenario_off(rid:str):
    global active_expiry
    result=await ops('DELETE',f'/internal/runs/{rid}/scenario')
    if rid==active_run:active_expiry=0.0;persist_controller_state()
    await reconcile_scenario_metrics();telemetry.last_reset.set(time.time());return result
@app.get('/control/runs/{rid}/evidence')
async def evidence(rid:str):return await ops('GET',f'/internal/runs/{rid}/evidence')
@app.get('/control/readiness')
async def readiness():
    manifest,mismatch=accepted_runtime_configuration()
    checks={'operations':(await http.get('/health/ready')).is_success,'model':bool({'anthropic':config.ANTHROPIC_KEY,'gemini':config.GEMINI_KEY,'openai':config.OPENAI_KEY}[config.PROVIDER]),'cloud_credentials':bool(config.CLOUD_TOKEN),'accepted_model_provider':mismatch is None}
    return {'status':'ready' if all(checks.values()) else 'degraded','checks':checks,'configuration_error':mismatch,'grafana_url':config.GRAPH_URL,'model':config.MODEL,'provider':config.PROVIDER,'agent_version':manifest.get('agent_version') if mismatch else package()[2]}


@app.post('/control/guard-probe')
async def native_guard_probe():
    """A disclosed operator check. No model generation and no business mutation."""
    rid,cid=str(uuid.uuid4()),str(uuid.uuid4())
    version=package()[2]
    ctx={'demo_run_id':rid,'conversation_id':cid,'customer_id':'C1','business_date':'2026-09-15',
         'fixture_revision':'v1','agent_version':version,'traffic_kind':'guard_probe','scenario':'healthy'}
    await ops('POST','/internal/runs',{'run_id':rid,'customer_id':'C1','business_date':'2026-09-15','scenario':'healthy'})
    await ops('POST','/internal/conversations',{'run_id':rid,'customer_id':'C1','order_id':'PD-1042','conversation_id':cid,'agent_version':version})
    dispatched=False
    async def probe_dispatch(*args):
        nonlocal dispatched
        dispatched=True
        return {'status':'probe_not_dispatched','data':{'reason':'Operator probes never perform business actions'}}
    call={'call_id':str(uuid.uuid4()),'name':'send_confirmation','arguments':{
        'replacement_id':'operator-probe-no-replacement','to':'audit@external.invalid',
        'idempotency_key':str(uuid.uuid4()),'body':'Synthetic operator guard check; no customer order data.'}}
    result=await ToolGateway(client,probe_dispatch,audit).execute(ctx,call)
    denied=result['status']=='policy_denied' and result.get('data',{}).get('source')=='grafana'
    return {'probe_kind':'operator_guard_check','model_invoked':False,'run_id':rid,'conversation_id':cid,
            'denied':denied,'action':'deny' if denied else 'allow' if dispatched else result['status'],
            'source':result.get('data',{}).get('source','grafana' if dispatched else 'unknown'),
            'rule_id':result.get('data',{}).get('rule_id'),'dispatch_attempted':dispatched,'business_actions_executed':False}


from prometheus_client import REGISTRY
REGISTRY.register(presenter.Collector())

@app.post(presenter.PATH)
async def presenter_command(body:presenter.Command):
    return await presenter.execute(body,sys.modules[__name__])


@app.get("/control/presenter/customer")
async def presenter_customer():
    if not active_run:raise HTTPException(409,"Create a demo run first")
    return RedirectResponse(f"http://localhost:3100/?run={active_run}",status_code=303,headers={"Cache-Control":"no-store"})
