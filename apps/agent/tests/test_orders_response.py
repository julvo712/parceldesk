"""Exercise the real ASGI route, session validation, serialization and middleware."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from itsdangerous import TimestampSigner, URLSafeTimedSerializer

from parceldesk import main


@pytest.fixture
def signer(monkeypatch):
    value = URLSafeTimedSerializer('orders-test-only')
    monkeypatch.setattr(main, 'signer', value)
    return value


@asynccontextmanager
async def endpoint(monkeypatch, handler):
    # ASGITransport does not start lifespan: no real clients, LLM or exporters.
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url='http://operations.test'
    ) as upstream:
        monkeypatch.setattr(main, 'http', upstream)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url='http://customer.test'
        ) as browser:
            yield browser


def assert_headers(response):
    assert response.headers['content-type'] == 'application/json'
    assert int(response.headers['content-length']) == len(response.content)
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['referrer-policy'] == 'same-origin'
    assert 'set-cookie' not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize('wrapped', [True, False])
async def test_payload_order_defaults_and_json_types(monkeypatch, signer, wrapped):
    items = [
        {'id': 'z', 'order_id': 'explicit', 'product_name': 'Kopfhörer 🎧',
         'product': 'unused', 'image': 'old', 'eligible': True, 'available_stock': 0,
         'price_minor': 12999, 'ratio': 1.5, 'delivered_at': '2026-09-01',
         'extra': {'values': [None, False, 'text', 2]}},
        {'id': 'a', 'product': 'Legacy name'},
        {'id': 'b'},
        {'id': 'c', 'order_id': None, 'product_name': None},
        {},
    ]
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={'orders': items} if wrapped else items)

    async with endpoint(monkeypatch, upstream) as browser:
        browser.cookies.set('pd_session', signer.dumps({'run_id': 'run-a', 'customer_id': 'C1'}))
        response = await browser.get('/api/orders')
    expected = [
        {**items[0], 'image': '/images/headphones.webp'},
        {**items[1], 'order_id': 'a', 'product_name': 'Legacy name', 'image': '/images/headphones.webp'},
        {**items[2], 'order_id': 'b', 'product_name': 'Arc One headphones', 'image': '/images/headphones.webp'},
        {**items[3], 'image': '/images/headphones.webp'},
        {'order_id': None, 'product_name': 'Arc One headphones', 'image': '/images/headphones.webp'},
    ]
    payload = {'orders': expected, 'customer': {'customer_id': 'C1', 'name': 'Maya Chen'}}
    assert response.status_code == 200
    assert response.json() == payload
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    assert len(calls) == 1
    assert_headers(response)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{'orders': []}, {}, []])
async def test_empty_orders(monkeypatch, signer, payload):
    async with endpoint(monkeypatch, lambda request: httpx.Response(200, json=payload)) as browser:
        browser.cookies.set('pd_session', signer.dumps({'run_id': 'run-a', 'customer_id': 'C1'}))
        response = await browser.get('/api/orders')
    assert response.status_code == 200
    assert response.json() == {'orders': [], 'customer': {'customer_id': 'C1', 'name': 'Maya Chen'}}
    assert_headers(response)


@pytest.mark.asyncio
async def test_session_scopes_upstream_and_prevents_response_leakage(monkeypatch, signer):
    calls = []

    def upstream(request):
        assert request.method == 'GET'
        assert request.url.path == '/internal/orders'
        scope = dict(request.url.params)
        calls.append(scope)
        return httpx.Response(200, json={'orders': [{'id': f"{scope['run_id']}-{scope['customer_id']}"}]})

    async with endpoint(monkeypatch, upstream) as browser:
        for run, customer, name in [('run-a', 'C1', 'Maya Chen'), ('run-a', 'C2', 'Alex Morgan'), ('run-b', 'C1', 'Maya Chen')]:
            browser.cookies.set('pd_session', signer.dumps({'run_id': run, 'customer_id': customer}))
            response = await browser.get('/api/orders?run_id=attacker&customer_id=other')
            assert response.status_code == 200
            assert response.json()['customer'] == {'customer_id': customer, 'name': name}
            assert [o['order_id'] for o in response.json()['orders']] == [f'{run}-{customer}']
            assert calls[-1] == {'run_id': run, 'customer_id': customer}
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('cookie_kind', ['missing', 'invalid', 'expired'])
async def test_rejected_sessions_never_call_upstream(monkeypatch, signer, cookie_kind):
    def upstream(request):
        pytest.fail('Rejected session reached upstream')

    class ExpiredSigner(TimestampSigner):
        def get_timestamp(self):
            return super().get_timestamp() - 28801

    async with endpoint(monkeypatch, upstream) as browser:
        if cookie_kind == 'invalid':
            browser.cookies.set('pd_session', 'invalid-signature')
        elif cookie_kind == 'expired':
            expired = URLSafeTimedSerializer('orders-test-only', signer=ExpiredSigner)
            browser.cookies.set('pd_session', expired.dumps({'run_id': 'run-a', 'customer_id': 'C1'}))
        response = await browser.get('/api/orders')
    assert response.status_code == 401
    assert response.json() == {'detail': 'Your demo session expired. Please sign in again.'}
    assert_headers(response)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 404, 409, 422, 429, 500, 503])
async def test_upstream_errors_keep_safe_status_and_body(monkeypatch, signer, status):
    async with endpoint(monkeypatch, lambda request: httpx.Response(status, text='private upstream details')) as browser:
        browser.cookies.set('pd_session', signer.dumps({'run_id': 'run-a', 'customer_id': 'C1'}))
        response = await browser.get('/api/orders')
    assert response.status_code == (status if status in (400, 401, 403, 404, 409, 422) else 503)
    assert response.json() == {'detail': 'This request could not be completed. Please try again.'}
    assert_headers(response)
