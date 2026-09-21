"""Bounded aggregate exposition; all exact IDs remain in the ledger and logs."""
from collections import Counter, defaultdict
from decimal import Decimal
import json


def label(value):
    return str(value).replace('\\','\\\\').replace('\n','\\n').replace('"','\\"')


def render(ledger):
    lines=[]
    def emit(name,value,labels=None):
        suffix='{'+','.join(f'{k}="{label(v)}"' for k,v in sorted((labels or {}).items()))+'}' if labels else ''
        lines.append(f'{name}{suffix} {value}')
    def family(name,kind,help_text):
        lines.extend([f'# HELP {name} {help_text}',f'# TYPE {name} {kind}'])
    summaries=[ledger.summarize(t) for t in ledger.task_ids()]
    family('parceldesk_development_tasks','gauge','Durable genuine task inventory, observed at scrape time')
    counts=Counter(s.state for s in summaries)
    for state in ('incomplete','awaiting_evidence','accepted','failed','cancelled','closed'):
        emit('parceldesk_development_tasks',counts[state],{'state':state})
    family('parceldesk_development_candidates_total','counter','Unique completed candidate evaluation outcomes, identified by native experiment')
    outcomes=Counter()
    for task in ledger.task_ids():
        seen={}
        for e in ledger.events(task):
            if e['event']=='candidate_evaluated' and e['payload']['result'] in ('passed','rejected'):
                seen[(e['payload']['candidate_id'],e['payload'].get('experiment_id','legacy'))]=e['payload']['result']
        outcomes.update(seen.values())
    for outcome in ('passed','rejected'):emit('parceldesk_development_candidates_total',outcomes[outcome],{'outcome':outcome})
    family('parceldesk_development_tasks_first_pass_total','counter','Accepted tasks whose first evaluated candidate passed')
    emit('parceldesk_development_tasks_first_pass_total',sum(s.first_pass is True for s in summaries))
    family('parceldesk_development_accepted_duration_seconds','histogram','Measured source-time seconds from task start to accepted candidate')
    durations=[s.elapsed_seconds for s in summaries if s.elapsed_seconds is not None]
    for bound in (30,60,120,300,600,1200,3600,7200,14400,float('inf')):
        emit('parceldesk_development_accepted_duration_seconds_bucket',sum(v<=bound for v in durations),{'le':'+Inf' if bound==float('inf') else bound})
    emit('parceldesk_development_accepted_duration_seconds_sum',sum(durations))
    emit('parceldesk_development_accepted_duration_seconds_count',len(durations))
    rows=ledger.db.execute('SELECT * FROM session_records WHERE synthetic=0').fetchall()
    sessions=defaultdict(set);costs=defaultdict(Decimal);tokens=defaultdict(int);priced=Counter();total=Counter();allocations=defaultdict(Decimal)
    for row in ledger.db.execute('SELECT a.*,e.synthetic FROM associations a JOIN events e ON a.event_id=e.event_id WHERE a.relation="session" AND e.synthetic=0'):
        allocations[(row['target'],row['task_id'])]+=Decimal(row['allocation'])
    development_cost=defaultdict(Decimal)
    summary_map={s.task_id:s for s in summaries}
    for row in rows:
        tool,model=row['tool'],row['model'];sessions[tool].add(row['session_id']);total[tool]+=1
        for kind,amount in json.loads(row['usage']).items():
            if amount is not None:tokens[(tool,model,kind)]+=amount
        if row['cost_usd'] is None:continue
        cost=Decimal(row['cost_usd']);costs[(tool,model)]+=cost;priced[tool]+=1
        fraction=Decimal(0)
        for (session,task),allocation in allocations.items():
            if session!=row['session_id']:continue
            fraction+=allocation
            coverage='accepted' if summary_map.get(task) and summary_map[task].accepted else 'incomplete'
            development_cost[(tool,coverage)]+=cost*allocation
        if fraction<1:development_cost[(tool,'unassigned')]+=cost*(1-fraction)
    family('parceldesk_coding_sessions','gauge','Distinct authentic imported sessions per tool')
    family('parceldesk_coding_tokens_total','counter','Normalized token buckets from durable deduplicated source records')
    family('parceldesk_coding_cost_usd','gauge','Known API-equivalent USD consumption, not subscription invoices')
    family('parceldesk_coding_price_coverage','gauge','Priced source records divided by all authentic source records per tool')
    family('parceldesk_coding_unpriced_records','gauge','Source records with unknown estimated cost')
    for tool,ids in sorted(sessions.items()):
        emit('parceldesk_coding_sessions',len(ids),{'tool':tool})
        emit('parceldesk_coding_price_coverage',Decimal(priced[tool])/Decimal(total[tool]),{'tool':tool})
        emit('parceldesk_coding_unpriced_records',total[tool]-priced[tool],{'tool':tool})
    for (tool,model,kind),amount in sorted(tokens.items()):emit('parceldesk_coding_tokens_total',amount,{'tool':tool,'model':model,'type':kind})
    for (tool,model),cost in sorted(costs.items()):emit('parceldesk_coding_cost_usd',cost,{'tool':tool,'model':model})
    family('parceldesk_development_cost_usd','gauge','Known session consumption explicitly allocated by task state; unassigned remains visible')
    for (tool,coverage),cost in sorted(development_cost.items()):emit('parceldesk_development_cost_usd',cost,{'tool':tool,'coverage':coverage})
    return '\n'.join(lines)+'\n'
