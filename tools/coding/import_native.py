#!/usr/bin/env python3
"""Import explicitly selected native conversation readbacks, never local transcripts.

Usage: python tools/coding/import_native.py runs/coding-claude-native.json \
    runs/coding-codex-native.json --ledger runs/development/development.sqlite
Absent token buckets stay unknown. Native reported USD amounts take precedence
over an explicitly supplied, provenance-backed price catalog.
"""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parceldesk_demo.development.events import DevelopmentLedger, timestamp
from parceldesk_demo.development.pricing import estimate, money

TOOL_NAMES = {'codex':'codex','claude-code':'claude_code','claude_code':'claude_code',
              'cursor':'cursor','cursor-agent':'cursor'}


def tokens(usage, key):
    value=usage.get(key)
    if value is None:return None
    if isinstance(value,bool) or not isinstance(value,(int,str)):
        raise ValueError(f'{key} must be a nonnegative integer or null')
    if isinstance(value,str) and not value.isdecimal():
        raise ValueError(f'{key} is not an integer token count')
    value=int(value)
    if value<0:raise ValueError(f'{key} cannot be negative')
    return value


def normalized_usage(generation):
    usage=generation.get('usage') or {}
    if not isinstance(usage,dict):raise ValueError('usage must be an object')
    buckets={name:tokens(usage,key) for name,key in (
        ('input','input_tokens'),('output','output_tokens'),
        ('cache_read','cache_read_input_tokens'),('cache_write','cache_write_input_tokens'))}
    provider=generation.get('model',{}).get('provider','').lower()
    if provider in {'openai','azure-openai','azure_openai'}:
        # OpenAI input is inclusive of cached reads. Missing reads mean exclusive
        # input cannot be derived; neither raw input nor cache is counted twice.
        raw,cached=buckets['input'],buckets['cache_read']
        if raw is not None and cached is not None and cached>raw:
            raise ValueError('OpenAI cached input exceeds inclusive input')
        buckets['input']=raw-cached if raw is not None and cached is not None else None
    elif provider=='cursor':
        # Cursor's official mapper copies hook input/cache counts without a
        # documented overlap contract. Preserve measured output/cache buckets;
        # exclusive input is unknown, even when raw reported input is present.
        buckets['input']=None
    elif provider!='anthropic':
        raise ValueError(f'Unverified provider token semantics: {provider or "missing"}')
    # Anthropic input excludes both cache reads and writes. total_tokens and
    # reasoning_tokens are deliberately not added: they overlap other fields.
    return buckets


def native_cost(generation):
    values=[]
    for key in ('cost_usd','estimated_cost_usd'):
        if generation.get(key) is not None:values.append((key,money(generation[key])))
    cost=generation.get('cost')
    if isinstance(cost,dict):
        for key in ('total_usd','total_cost_usd'):
            if cost.get(key) is not None:values.append(('cost.'+key,money(cost[key])))
    if not values:return None,'unpriced'
    if len({v for _,v in values})!=1:raise ValueError('Conflicting native USD amounts')
    return values[0][1],'native-reported-usd:'+values[0][0]


def conversation_records(data, tool=None, catalog=None):
    if not isinstance(data,dict) or not isinstance(data.get('generations'),list):
        raise ValueError('Expected a native conversation object containing generations')
    if data.get('synthetic') or data.get('test_fixture'):
        raise ValueError('Synthetic conversations cannot enter this authentic importer')
    conversation=data.get('conversation_id')
    if not isinstance(conversation,str) or not conversation:raise ValueError('Missing conversation_id')
    generations=data['generations']
    if 'generation_count' in data and int(data['generation_count'])!=len(generations):
        raise ValueError('Partial conversation: fetch every generation before importing')
    if not generations:raise ValueError('Conversation contains no generations')
    records=[];identities=set()
    for generation in generations:
        gid=generation.get('generation_id')
        if not isinstance(gid,str) or not gid or gid in identities:raise ValueError('Missing/duplicate generation identity')
        identities.add(gid)
        if generation.get('conversation_id')!=conversation:raise ValueError('Generation belongs to another conversation')
        if generation.get('synthetic') or generation.get('test_fixture'):raise ValueError('Synthetic generation rejected')
        detected=TOOL_NAMES.get(generation.get('agent_name')) or TOOL_NAMES.get(generation.get('agent_id'))
        if tool and detected and tool!=detected:raise ValueError('Explicit tool conflicts with native agent identity')
        coding_tool=detected or tool
        if coding_tool not in set(TOOL_NAMES.values()):raise ValueError('Unknown coding tool; supply --tool explicitly')
        model=generation.get('model',{}).get('name')
        if not isinstance(model,str) or not model:raise ValueError('Missing model identity')
        usage=normalized_usage(generation);cost,basis=native_cost(generation)
        if cost is None and catalog:
            cost=estimate(usage,model,catalog)
            if cost is not None:
                price=catalog['models'][model]
                basis='catalog:'+price['effective_date']+':'+price['source_url']
        records.append({'record_id':'native:'+conversation+':'+gid,
            'session_id':conversation,'granularity':'generation','tool':coding_tool,
            'model':model,'source_timestamp':timestamp(generation.get('completed_at') or generation.get('started_at')),
            'user':data.get('user_id') or generation.get('metadata',{}).get('sigil.user.id'),
            'repo':generation.get('tags',{}).get('cwd'),'usage':usage,
            'estimated_cost_usd':str(cost) if cost is not None else None,'price_basis':basis,
            'evidence_ref':'native://conversations/'+conversation+'/generations/'+gid,
            'synthetic':False})
    return records


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files',nargs='+',type=Path)
    parser.add_argument('--ledger',type=Path,default=Path(__file__).resolve().parents[2]/'runs/development/development.sqlite')
    parser.add_argument('--tool',choices=sorted(set(TOOL_NAMES.values())))
    parser.add_argument('--catalog',type=Path,help='Optional exact-model price catalog; unknown buckets remain unpriced')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args(argv)
    catalog=json.loads(args.catalog.read_text()) if args.catalog else None
    records=[];sources=[]
    # Validate all files before touching the ledger. No directory scanning or
    # inferred task association: callers must explicitly link real sessions.
    for file in args.files:
        raw=file.read_bytes();data=json.loads(raw,parse_float=Decimal)
        parsed=conversation_records(data,args.tool,catalog)
        records.extend(parsed)
        sources.append({'file':str(file),'sha256':hashlib.sha256(raw).hexdigest(),
                        'conversation_id':data['conversation_id'],'generations':len(parsed)})
    inserted=0
    if not args.dry_run:
        ledger=DevelopmentLedger(args.ledger)
        try:
            for record in records:inserted+=int(ledger.import_session(record))
        finally:ledger.close()
    print(json.dumps({'dry_run':args.dry_run,'sources':sources,'generation_records':len(records),
        'inserted_or_updated':inserted,'priced_records':sum(r['estimated_cost_usd'] is not None for r in records),
        'unpriced_records':sum(r['estimated_cost_usd'] is None for r in records),
        'unknown_token_buckets':sum(v is None for r in records for v in r['usage'].values())},indent=2))


if __name__=='__main__':main()
