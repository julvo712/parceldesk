#!/usr/bin/env python3
"""Join one explicitly selected Claude usage log to its native conversation.

Only usage/model/message IDs enter the ledger. Prompt, response, and tool text
are never emitted. Prices are API-equivalent token estimates, not subscriptions.
"""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coding.import_native import conversation_records, tokens
from parceldesk_demo.development.events import DevelopmentLedger, encoded

PRICING={'source_url':'https://platform.claude.com/docs/en/about-claude/pricing',
         'verified_at':'2026-09-15','model':'claude-sonnet-5',
         'usd_per_million':{'input':'2','output':'10','cache_read':'0.20',
                            'cache_write_5m':'2.50','cache_write_1h':'4'}}


def selected_metadata(lines, conversation):
    messages={}
    for line in lines:
        row=json.loads(line)
        if row.get('type')!='assistant':continue
        if row.get('sessionId')!=conversation:raise ValueError('Source log has a different session ID')
        message=row.get('message',{});mid=message.get('id')
        if not mid or not message.get('usage'):continue
        # Deliberately do not copy message.content or any tool/prompt fields.
        value={'id':mid,'model':message.get('model'),'usage':message['usage']}
        if mid in messages and messages[mid]!=value:raise ValueError('Conflicting usage for one message ID')
        messages[mid]=value
    return list(messages.values())


def enrichments(native, messages, source_sha256):
    records=conversation_records(native);results=[];joined=set()
    for record in records:
        if record['tool']!='claude_code' or record['model']!=PRICING['model']:
            raise ValueError('This verified price snapshot supports claude-sonnet-5 only')
        keys=(('input','input_tokens'),('output','output_tokens'),('cache_write','cache_creation_input_tokens'))
        matches=[m for m in messages if m['model']==record['model'] and
                 all(record['usage'][a] is not None and tokens(m['usage'],b)==record['usage'][a] for a,b in keys)]
        if len(matches)!=1 or matches[0]['id'] in joined:raise ValueError('Native generation to message join is not one-to-one')
        message=matches[0];joined.add(message['id']);usage=message['usage']
        if usage.get('service_tier')!='standard' or usage.get('speed')!='standard' or usage.get('inference_geo')!='global':
            raise ValueError('Unsupported pricing tier, speed or inference geography')
        server=usage.get('server_tool_use',{})
        if server.get('web_search_requests')!=0 or server.get('web_fetch_requests')!=0:
            raise ValueError('Additional server tool usage requires separate pricing')
        cache=usage.get('cache_creation',{})
        five=tokens(cache,'ephemeral_5m_input_tokens');hour=tokens(cache,'ephemeral_1h_input_tokens')
        measured={a:tokens(usage,b) for a,b in keys};measured['cache_read']=tokens(usage,'cache_read_input_tokens')
        if any(v is None for v in measured.values()) or five is None or hour is None:
            raise ValueError('Missing explicit cache/timing metadata; cost stays unknown')
        if five+hour!=measured['cache_write']:raise ValueError('TTL counts do not match native cache writes')
        for bucket,value in record['usage'].items():
            if value is not None and measured[bucket]!=value:raise ValueError('Raw usage conflicts with native measured tokens')
        billable={**measured,'cache_write_5m':five,'cache_write_1h':hour}
        amount=sum((Decimal(billable[k])*Decimal(rate)/Decimal(1_000_000)
                    for k,rate in PRICING['usd_per_million'].items()),Decimal(0))
        evidence=record['evidence_ref']+';claude-source-sha256:'+source_sha256+';message:'+message['id']
        basis=encoded({'kind':'api-equivalent-token-estimate','pricing':PRICING,
                       'cache_write_5m_tokens':five,'cache_write_1h_tokens':hour})
        results.append({'record_id':record['record_id'],'usage':measured,'cost_usd':str(amount),
                        'price_basis':basis,'evidence_ref':evidence})
    if len(joined)!=len(messages):raise ValueError('Source contains unmatched messages; fetch a complete matching native conversation')
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',required=True,type=Path)
    parser.add_argument('--claude-jsonl',required=True,type=Path)
    parser.add_argument('--ledger',required=True,type=Path)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();native=json.loads(args.native.read_text())
    if args.claude_jsonl.name!=native['conversation_id']+'.jsonl':
        raise ValueError('Explicit Claude log filename must match native conversation ID')
    raw=args.claude_jsonl.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    records=enrichments(native,selected_metadata(raw.decode().splitlines(),native['conversation_id']),digest)
    updated=0
    if not args.dry_run:
        ledger=DevelopmentLedger(args.ledger)
        try:
            for record in records:updated+=int(ledger.enrich_session(**record))
        finally:ledger.close()
    print(json.dumps({'dry_run':args.dry_run,'joined_generations':len(records),'enriched_records':updated,
        'source_sha256':digest,'api_equivalent_token_estimate_usd':str(sum((Decimal(r['cost_usd']) for r in records),Decimal(0))),
        'pricing':PRICING},indent=2))


if __name__=='__main__':main()
