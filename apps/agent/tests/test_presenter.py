import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import HTTPException
from parceldesk import main,presenter

@pytest.fixture(autouse=True)
def isolate(monkeypatch,tmp_path):
    monkeypatch.setattr(presenter,'STATE_FILE',tmp_path/'actions.json')
    monkeypatch.setattr(presenter,'state',{})
    monkeypatch.setattr(presenter,'snapshot',{})
    monkeypatch.setattr(presenter,'last_new',0)

@pytest.mark.asyncio
async def test_bridge_origin_and_preflight_do_not_open_other_routes(monkeypatch):
    called=[]
    async def execute(body,controller):called.append(body.command);return {'status':'verified'}
    monkeypatch.setattr(presenter,'execute',execute)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://localhost:3101') as c:
        headers={'Origin':presenter.ORIGIN,'X-Grafana-Action':'1','Content-Type':'application/json'}
        pre=await c.options(presenter.PATH,headers={'Origin':presenter.ORIGIN,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,x-grafana-action','Access-Control-Request-Private-Network':'true'})
        assert pre.status_code==200 and pre.headers['access-control-allow-private-network']=='true'
        assert (await c.post(presenter.PATH,json={'command':'refresh'},headers=headers)).status_code==200
        for origin in ('https://evil.example','https://demotests.grafana.net.evil.example','null'):
            assert (await c.post(presenter.PATH,json={'command':'reset'},headers={**headers,'Origin':origin})).status_code==403
        assert (await c.post(presenter.PATH,json={'command':'reset'})).status_code==403
        assert (await c.post(presenter.PATH,content='{}',headers={'Origin':presenter.ORIGIN,'Content-Type':'text/plain'})).status_code==403
        assert (await c.post('/control/runs',json={},headers=headers)).status_code==403
        assert (await c.post(presenter.PATH,json={'command':'shell','scenario':'whoami'},headers=headers)).status_code==422
        assert (await c.post(presenter.PATH,json={'command':'activate','ttl_seconds':301},headers=headers)).status_code==422
    assert called==['refresh']

@pytest.fixture
def controller():
    async def evidence(rid):return {'scenario':'healthy','replacements_count':2,'notifications_count':2}
    return SimpleNamespace(active_run='run-1',active_expiry=0,evidence=evidence,package=lambda:('',None,'version'),config=SimpleNamespace(MODEL='model'),SCENARIOS=main.SCENARIOS,Run=main.Run,Scenario=main.Scenario,control_new=AsyncMock(),scenario_on=AsyncMock(),scenario_off=AsyncMock(),native_guard_probe=AsyncMock(return_value={'denied':True,'business_actions_executed':False,'model_invoked':False}),telemetry=SimpleNamespace(log=lambda *a,**k:None))

@pytest.mark.asyncio
async def test_reset_requires_authoritative_readback(controller):
    controller.evidence=AsyncMock(return_value={'scenario':'db_lock'})
    with pytest.raises(HTTPException) as e:await presenter.execute(presenter.Command(command='reset'),controller)
    assert e.value.status_code==503
    assert presenter.state['last_action']['status']=='unverified'
    controller.scenario_off.assert_awaited_once_with('run-1')

@pytest.mark.asyncio
async def test_create_refuses_active_fault_and_double_click(controller):
    controller.evidence=AsyncMock(return_value={'scenario':'cpu_pressure'})
    with pytest.raises(HTTPException):await presenter.execute(presenter.Command(command='new_run'),controller)
    controller.control_new.assert_not_awaited()
    controller.evidence=AsyncMock(return_value={'scenario':'healthy'})
    await presenter.execute(presenter.Command(command='new_run'),controller)
    with pytest.raises(HTTPException):await presenter.execute(presenter.Command(command='new_run'),controller)
    assert controller.control_new.await_count==1

@pytest.mark.asyncio
async def test_refuses_unknown_and_overlapping_scenarios(controller):
    for name in ('healthy','shell','../reset'):
        with pytest.raises(HTTPException):await presenter.execute(presenter.Command(command='activate',scenario=name),controller)
    controller.evidence=AsyncMock(return_value={'scenario':'supplier_injection'})
    with pytest.raises(HTTPException):await presenter.execute(presenter.Command(command='activate',scenario='db_lock'),controller)
    controller.scenario_on.assert_not_awaited()

@pytest.mark.asyncio
async def test_probe_and_reset_persist_verified_result(controller):
    await presenter.execute(presenter.Command(command='guard_probe'),controller)
    await presenter.execute(presenter.Command(command='reset'),controller)
    presenter.state={};presenter.restore()
    assert presenter.state['probe']['denied']
    assert presenter.state['last_action']['status']=='verified'
    assert presenter.snapshot['counts']['replacements']==2

@pytest.mark.asyncio
async def test_read_failure_keeps_old_timestamp_and_blocks_action(controller):
    await presenter.observe(controller);stamp=presenter.snapshot['observed_at']
    controller.evidence=AsyncMock(side_effect=RuntimeError('unavailable'))
    with pytest.raises(HTTPException):await presenter.execute(presenter.Command(command='new_run'),controller)
    assert presenter.snapshot['available']==0 and presenter.snapshot['observed_at']==stamp
    controller.control_new.assert_not_awaited()


@pytest.mark.asyncio
async def test_customer_link_uses_current_run(monkeypatch):
    monkeypatch.setattr(main,"active_run","new-run")
    response=await main.presenter_customer()
    assert response.headers["location"]=="http://localhost:3100/?run=new-run"
    assert response.headers["cache-control"]=="no-store"
    monkeypatch.setattr(main,"active_run",None)
    with pytest.raises(HTTPException):await main.presenter_customer()
