"""Native dashboard bridge. Browser-local, exact-origin, bounded commands only."""
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from prometheus_client.core import GaugeMetricFamily
from pydantic import BaseModel, ConfigDict, Field

PATH = '/control/presenter/command'
ORIGIN = os.getenv('PRESENTER_GRAFANA_ORIGIN', os.getenv('GRAFANA_URL', 'https://demotests.grafana.net')).rstrip('/')
STATE_FILE = Path(os.getenv('PRESENTER_STATE_FILE', '/app/runs/presenter-actions.json'))
lock = asyncio.Lock()
state = {}
last_new = 0.0
snapshot = {}

class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command: Literal['new_run','activate','reset','guard_probe','refresh']
    scenario: str = ''
    ttl_seconds: int = Field(default=300, ge=1, le=300)


def cors_headers():
    return {'Access-Control-Allow-Origin': ORIGIN, 'Vary': 'Origin',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type, X-Grafana-Action',
            'Access-Control-Allow-Private-Network': 'true',
            'Access-Control-Max-Age': '600'}

async def protect(request, call_next):
    # CORS is restricted to this one bridge; legacy APIs stay same-origin.
    if request.headers.get('origin') != ORIGIN:
        return JSONResponse({'detail':'Only the configured Grafana origin may use dashboard controls'},status_code=403)
    if request.method == 'OPTIONS':
        headers={x.strip().lower() for x in request.headers.get('access-control-request-headers','').split(',') if x.strip()}
        if request.headers.get('access-control-request-method') != 'POST' or not headers.issubset({'content-type','x-grafana-action'}):
            return JSONResponse({'detail':'Unsupported dashboard preflight'},status_code=403)
        return JSONResponse({},headers=cors_headers())
    if request.method != 'POST' or request.headers.get('x-grafana-action') != '1' or request.headers.get('content-type','').split(';')[0] != 'application/json':
        return JSONResponse({'detail':'Dashboard actions require POST, JSON and X-Grafana-Action: 1'},status_code=403,headers=cors_headers())
    response=await call_next(request)
    response.headers.update(cors_headers())
    return response


def restore():
    global state
    try: state=json.loads(STATE_FILE.read_text())
    except FileNotFoundError: state={}


def persist():
    STATE_FILE.parent.mkdir(parents=True,exist_ok=True)
    temporary=STATE_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(STATE_FILE)


async def observe(controller):
    """Read authoritative business state. Never stamp an unavailable read as fresh."""
    global snapshot
    try:
        rid=controller.active_run
        evidence=await controller.evidence(rid) if rid else {}
        scenario=evidence.get('scenario','healthy')
        snapshot={'observed_at':time.time(),'available':1,'run_id':rid or 'none',
                  'scenario':scenario,'agent_version':controller.package()[2],
                  'model':controller.config.MODEL,
                  'expires_at':controller.active_expiry if scenario!='healthy' else 0,
                  'counts':{key:int(evidence.get(key+'_count',0)) for key in ('proposals','confirmations','replacements','notifications')}}
    except Exception:
        snapshot={**snapshot,'available':0}
    return snapshot


async def execute(body, controller):
    global last_new
    if body.command=='activate' and body.scenario not in controller.SCENARIOS[1:]:
        raise HTTPException(422,'Choose a supported failure scenario')
    async with lock:
        result={}
        try:
            current=await observe(controller)
            if not current.get('available'):raise HTTPException(503,'Controller readback is unavailable; no action was started')
            if body.command=='new_run':
                if current['scenario']!='healthy':raise HTTPException(409,'Reset the active fault before creating another run')
                if time.monotonic()-last_new<5:raise HTTPException(409,'A run was just created; use the current run')
                result=await controller.control_new(controller.Run())
                last_new=time.monotonic()
            elif body.command in ('activate','reset'):
                if not controller.active_run:raise HTTPException(409,'Create a demo run first')
                if body.command=='activate':
                    if current['scenario']!='healthy':raise HTTPException(409,'Reset the active fault before starting another scenario')
                    result=await controller.scenario_on(controller.active_run,controller.Scenario(scenario=body.scenario,ttl_seconds=body.ttl_seconds))
                else:
                    result=await controller.scenario_off(controller.active_run)
            elif body.command=='guard_probe':
                result=await controller.native_guard_probe()
                state['probe']={**result,'observed_at':time.time()}
            verified=await observe(controller)
            if not verified.get('available'):raise HTTPException(503,'Action returned but readback failed; verify before continuing')
            if body.command=='reset' and verified['scenario']!='healthy':raise HTTPException(503,'Fault reset did not verify healthy')
            if body.command=='activate' and verified['scenario']!=body.scenario:raise HTTPException(503,'Requested scenario was not observed')
            state['last_action']={'command':body.command,'scenario':body.scenario,'status':'verified','at':time.time(),'run_id':controller.active_run or 'none'}
            persist()
            controller.telemetry.log('presenter_action',**state['last_action'])
            return {'status':'verified','controller':verified,'result':result}
        except HTTPException as error:
            state['last_action']={'command':body.command,'scenario':body.scenario,'status':'rejected' if error.status_code<500 else 'unverified','at':time.time(),'run_id':controller.active_run or 'none'}
            persist()
            controller.telemetry.log('presenter_action',**state['last_action'],reason=error.detail)
            raise


class Collector:
    def collect(self):
        current=snapshot.copy()
        def gauge(name,value,labels=None):
            m=GaugeMetricFamily('parceldesk_presenter_'+name,'Presenter controller readback',labels=list((labels or {}).keys()))
            m.add_metric(list((labels or {}).values()),value)
            return m
        yield gauge('available',current.get('available',0))
        if 'observed_at' in current:
            yield gauge('observed_seconds',current['observed_at'])
            yield gauge('info',1,{k:current[k] for k in ('run_id','scenario','agent_version','model')})
            yield gauge('lease_expires_seconds',current['expires_at'])
            for k,v in current['counts'].items():yield gauge(k,v)
        action=state.get('last_action')
        if action:yield gauge('action_seconds',action['at'],{k:action[k] for k in ('command','scenario','status','run_id')})
        probe=state.get('probe')
        if probe:
            yield gauge('probe_seconds',probe['observed_at'],{'result':'denied' if probe.get('denied') else 'not_denied'})
            yield gauge('probe_business_actions',int(probe['business_actions_executed']))
