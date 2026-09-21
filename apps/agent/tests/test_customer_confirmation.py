from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from parceldesk import main
from parceldesk.guards.gateway import ToolGateway

@pytest.mark.asyncio
async def test_denied_customer_request_never_reaches_business_dispatch(monkeypatch):
    state={'status':'confirmed','replacement':{'replacement_id':'owned-replacement'},'agent_version':'accepted'}
    monkeypatch.setattr(main,'session',lambda r:{'run_id':'run','customer_id':'C1'})
    monkeypatch.setattr(main,'load_state',AsyncMock(return_value=state))
    monkeypatch.setattr(main,'effective_context',AsyncMock(return_value={'conversation_id':'c','demo_run_id':'run','scenario':'healthy'}))
    dispatch=AsyncMock();audit=AsyncMock()
    monkeypatch.setattr(main,'dispatch',dispatch);monkeypatch.setattr(main,'audit',audit)
    def evaluate(request):
        assert b'audit@external.invalid' in request.input.output[0].parts[0].tool_call.input_json
        return SimpleNamespace(action='deny',rule_id='recipient-boundary',reason='Unauthorized recipient')
    monkeypatch.setattr(main,'client',SimpleNamespace(evaluate_hook=evaluate))
    result=await main.send_customer_confirmation('c',main.ConfirmationRecipient(recipient='AUDIT@external.invalid',idempotency_key='key'),None)
    assert result['status']=='blocked'
    dispatch.assert_not_awaited();audit.assert_awaited_once()
    assert state['status']=='confirmed'

@pytest.mark.asyncio
async def test_unowned_conversation_stops_before_guard(monkeypatch):
    monkeypatch.setattr(main,'session',lambda r:{'run_id':'run','customer_id':'C2'})
    monkeypatch.setattr(main,'load_state',AsyncMock(side_effect=HTTPException(404,'not found')))
    ctx=AsyncMock();monkeypatch.setattr(main,'effective_context',ctx)
    with pytest.raises(HTTPException) as e:await main.send_customer_confirmation('other',main.ConfirmationRecipient(recipient='test@example.test',idempotency_key='key'),None)
    assert e.value.status_code==404;ctx.assert_not_awaited()

@pytest.mark.asyncio
async def test_unconfirmed_replacement_stops_before_guard(monkeypatch):
    monkeypatch.setattr(main,'session',lambda r:{'run_id':'run','customer_id':'C1'})
    monkeypatch.setattr(main,'load_state',AsyncMock(return_value={'status':'awaiting_confirmation'}))
    with pytest.raises(HTTPException) as e:await main.send_customer_confirmation('open',main.ConfirmationRecipient(recipient='test@example.test',idempotency_key='key'),None)
    assert e.value.status_code==409

@pytest.mark.asyncio
async def test_guard_outage_fails_closed_for_customer(monkeypatch):
    monkeypatch.setattr(main,'session',lambda r:{'run_id':'run','customer_id':'C1'})
    monkeypatch.setattr(main,'load_state',AsyncMock(return_value={'status':'confirmed','replacement':{'id':'owned'},'agent_version':'accepted'}))
    monkeypatch.setattr(main,'effective_context',AsyncMock(return_value={'conversation_id':'c','demo_run_id':'run','scenario':'guard_unavailable'}))
    dispatch=AsyncMock();monkeypatch.setattr(main,'dispatch',dispatch);monkeypatch.setattr(main,'audit',AsyncMock())
    result=await main.send_customer_confirmation('c',main.ConfirmationRecipient(recipient='test@example.test',idempotency_key='key'),None)
    assert result['status']=='unavailable';dispatch.assert_not_awaited()
