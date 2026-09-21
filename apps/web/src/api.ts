export class ApiError extends Error {
  constructor(message: string, public status = 0) { super(message); this.name = 'ApiError'; }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try { response = await fetch(path, { credentials: 'same-origin', ...init, headers: { 'Content-Type': 'application/json', ...init.headers } }); }
  catch { throw new ApiError('We could not connect. Check your connection, then try again.'); }
  if (!response.ok) {
    if (response.status === 401) throw new ApiError('Your demo session has expired. Sign in again to continue.', 401);
    throw new ApiError(response.status === 409 ? 'This request is already being handled. Refresh to see the latest state.' : 'We could not complete that request. Please try again.', response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export type StreamEvent = { type: string; event_id: string; conversation_id?: string; request_id?: string; payload: Record<string, unknown> };
export function parseEvent(block: string): StreamEvent | null {
  let type = 'message', id = ''; const lines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) type = line.slice(6).trim();
    if (line.startsWith('id:')) id = line.slice(3).trim();
    if (line.startsWith('data:')) lines.push(line.slice(5).trimStart());
  }
  if (!lines.length) return null;
  const data = JSON.parse(lines.join('\n')) as Record<string, unknown>;
  return { type: String(data.type ?? type), event_id: String(data.event_id ?? id), conversation_id: data.conversation_id as string | undefined, request_id: data.request_id as string | undefined, payload: (data.payload ?? data) as Record<string, unknown> };
}
export async function streamTurn(path: string, body: unknown, signal: AbortSignal, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: JSON.stringify(body), signal });
  if (!response.ok) throw new ApiError(response.status === 401 ? 'Your demo session has expired. Sign in again to continue.' : 'Your message could not be sent. Refresh the conversation before trying again.', response.status);
  if (!response.body) throw new ApiError('The connection ended. Refresh to recover your conversation.');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = ''; const seen = new Set<string>();
  const emit = (block: string) => { const event = parseEvent(block); if (!event || (event.event_id && seen.has(event.event_id))) return; if (event.event_id) seen.add(event.event_id); onEvent(event); };
  try {
    while (true) {
      const { value, done } = await reader.read(); buffer += decoder.decode(value, { stream: !done });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) { emit(buffer.slice(0, match.index)); buffer = buffer.slice(match.index + match[0].length); }
      if (done) break;
      if (buffer.length > 1_000_000) throw new ApiError('The response was too large. Refresh to recover your conversation.');
    }
    if (buffer.trim()) emit(buffer);
  } finally { reader.releaseLock(); }
}
