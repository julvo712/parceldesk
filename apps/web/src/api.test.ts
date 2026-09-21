import { describe, expect, it, vi, afterEach } from 'vitest';
import { api, parseEvent, streamTurn } from './api';
afterEach(() => vi.unstubAllGlobals());
describe('stream framing', () => {
  it('preserves CRLF event identities and typed payloads', () => { expect(parseEvent('id: e1\r\nevent: text_delta\r\ndata: {"payload":{"delta":"hello"}}')).toEqual({ type: 'text_delta', event_id: 'e1', conversation_id: undefined, request_id: undefined, payload: { delta: 'hello' } }); });
  it('ignores heartbeat comments', () => expect(parseEvent(': ping')).toBeNull());
  it('reconstructs fragmented unicode and suppresses duplicate events', async () => {
    const bytes = new TextEncoder().encode('event: text_delta\nid: a\ndata: {"delta":"🎧"}\n\nevent: text_delta\nid: a\ndata: {"delta":"🎧"}\n\nevent: completed\nid: b\ndata: {}\n\n');
    const body = new ReadableStream({ start(controller) { for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3)); controller.close(); } });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body))); const events: unknown[] = [];
    await streamTurn('/api/test', {}, new AbortController().signal, e => events.push(e)); expect(events).toHaveLength(2); expect(events[0]).toMatchObject({ payload: { delta: '🎧' } });
  });
  it('reports expired sessions without echoing sensitive response data', async () => { vi.stubGlobal('fetch', vi.fn(async () => new Response('private detail', { status: 401 }))); await expect(api('/api/orders')).rejects.toMatchObject({ status: 401, message: expect.stringContaining('expired') }); });
});
