import { useState } from 'react';
import type { FormEvent } from 'react';
import { LoaderCircle, Mail, ShieldCheck } from 'lucide-react';
import { api } from './api';
type Result = { status: 'blocked' | 'unavailable' | 'recorded'; message: string };
export default function ConfirmationEmail({ conversationId }: { conversationId: string }) {
  const [recipient, setRecipient] = useState(''), [busy, setBusy] = useState(false), [result, setResult] = useState<Result | null>(null);
  async function send(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setResult(null);
    try { setResult(await api<Result>(`/api/conversations/${encodeURIComponent(conversationId)}/confirmation`, { method: 'POST', body: JSON.stringify({ recipient: recipient.trim(), idempotency_key: crypto.randomUUID() }) })); }
    catch { setResult({ status: 'unavailable', message: 'We could not complete this request safely. Please try again shortly.' }); }
    finally { setBusy(false); }
  }
  return <section className="confirmation-email" aria-labelledby="email-confirmation-title"><h3 id="email-confirmation-title"><Mail size={20}/>Email your confirmation</h3><p>Your confirmation contains order details. We only send it to the verified email address on your account.</p><form onSubmit={send}><label htmlFor="confirmation-recipient">Email address</label><input id="confirmation-recipient" type="email" autoComplete="off" maxLength={254} required value={recipient} onChange={e => { setRecipient(e.target.value); setResult(null); }} placeholder="Enter your account email" disabled={busy}/><button className="secondary full" disabled={busy}>{busy ? <LoaderCircle size={17} className="spin"/> : <Mail size={17}/>} {busy ? 'Checking request…' : 'Send confirmation'}</button></form>{result && <div className={`notice ${result.status === 'recorded' ? '' : 'warning'}`} role="status"><div><strong><ShieldCheck size={18}/>{result.status === 'blocked' ? 'Request blocked' : result.status === 'recorded' ? 'Confirmation recorded' : 'Request paused'}</strong><p>{result.message}</p></div></div>}</section>;
}
