#!/usr/bin/env python3
"""Native Pyroscope/OTel/GitHub views. No local candidate-ledger queries."""
import json
from pathlib import Path
from generate import Dashboard, NAMES, variable, link

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'foundation/resources'
DS = {'prometheus':'grafanacloud-prom','pyroscope':'grafanacloud-profiles','github':'pd-github'}
PYRO = 'grafana-pyroscope-datasource'
GITHUB = 'grafana-github-datasource'
CPU = 'process_cpu:cpu:nanoseconds:cpu:nanoseconds'
HEAP = 'memory:inuse_space:bytes:space:bytes'
ALLOC = 'memory:alloc_space:bytes:space:bytes'
NAMES.update({'pd-runtime-versions':'ParcelDesk | Runtime by version','pd-ai-delivery':'ParcelDesk | AI investment & delivery'})


def native(d, title, group, uid, query, *, kind='timeseries', unit='none', x=0, w=12, h=7, description='', field=None, calc='lastNotNull', transforms=None):
    i=d.panel(title,kind=kind,unit=unit,x=x,w=w,h=h,description=description)
    panel=d.elements[f'panel-{i}']['spec']
    panel['data']['spec']['queries']=[{'kind':'PanelQuery','spec':{'refId':'A','hidden':False,
        'query':{'kind':'DataQuery','group':group,'version':'v0','datasource':{'name':uid},'spec':query}}}]
    if transforms:panel['data']['spec']['transformations']=[{'kind':'Transformation','group':t['id'],'spec':{'options':t['spec']}} for t in transforms]
    if kind=='stat':panel['vizConfig']['spec']['fieldConfig']['defaults']['color']={'mode':'fixed','fixedColor':'blue'}
    if field:
        panel['vizConfig']['spec']['options']['reduceOptions']={'calcs':[calc],'fields':f'/^{field}$/','values':False}
    return panel


def github(kind, **options):
    return {'queryType':kind,'owner':'julvo712','repository':'parceldesk','options':options}


def profiles(profile, mode='metrics', single=False):
    selector='{service_name="$service"'+(',service_version="$version"' if single else '')+'}'
    return {'queryType':mode,'profileTypeId':profile,'labelSelector':selector,'groupBy':['service_version'], 'limit':10, 'maxNodes':2048}


def save(d, since):
    d.save(OUT)
    path=OUT/'dashboards'/f'{d.uid}.json';obj=json.loads(path.read_text())
    obj['spec']['description']='Native Grafana Cloud telemetry and direct GitHub API data for ParcelDesk.'
    obj['spec']['links']=[link('Runtime by version','/d/pd-runtime-versions'),link('AI investment & delivery','/d/pd-ai-delivery'),
        link('Profiles Drilldown','/a/grafana-pyroscope-app'),link('Agent Observability','/a/grafana-agento11y-app'),link('Repository','https://github.com/julvo712/parceldesk')]
    obj['spec']['timeSettings'].update({'from':since,'autoRefresh':'1m' if d.uid=='pd-runtime-versions' else '5m'})
    path.write_text(json.dumps(obj,indent=2)+'\n')


def main():
    (OUT/'dashboards').mkdir(parents=True,exist_ok=True)
    current='v0.2.0'
    d=Dashboard('pd-runtime-versions','## How does each version behave?\nCompare customer response times with CPU and memory profiles. Select a service and version to inspect its code. Use the same workload and container resources for a release comparison.',DS)
    service=variable('service',['parceldesk-agent','parceldesk-operations','parceldesk-carrier'],'Profile service')
    service['spec'].update({'multi':False,'includeAll':False,'current':{'text':'parceldesk-agent','value':'parceldesk-agent'}})
    service['spec']['options']=[{'text':s,'value':s,'selected':s=='parceldesk-agent'} for s in ['parceldesk-agent','parceldesk-operations','parceldesk-carrier']]
    version={'kind':'QueryVariable','spec':{'name':'version','label':'Inspect version','hide':'dontHide','skipUrlSync':False,
        'current':{'text':current,'value':current},'options':[],'multi':False,'includeAll':False,'allowCustomValue':False,
        'refresh':'onTimeRangeChanged','regex':'','sort':'alphabeticalAsc',
        'query':{'kind':'DataQuery','group':PYRO,'version':'v0','datasource':{'name':DS['pyroscope']},
            'spec':{'type':'labelValue','profileTypeId':CPU,'labelName':'service_version','refId':'variable'}}}}
    d.vars=[service,version]
    d.panel('Orders • requests / second','sum by(service_version)(rate(http_server_duration_milliseconds_count{service_name="parceldesk-agent",http_target="/api/orders"}[$__rate_interval]))',kind='timeseries',unit='reqps',legend='{{service_version}}',w=12,h=6)
    d.panel('Orders • p95 response time','histogram_quantile(0.95,sum by(le,service_version)(rate(http_server_duration_milliseconds_bucket{service_name="parceldesk-agent",http_target="/api/orders"}[$__rate_interval])))',kind='timeseries',unit='ms',legend='{{service_version}}',x=12,w=12,h=6);d.y+=6
    native(d,'CPU • by version',PYRO,DS['pyroscope'],profiles(CPU),unit='cores',description='Sampled CPU time converted to cores by the Pyroscope data source. Compare with request rate; more traffic can require more CPU.')
    native(d,'Allocated memory • by version',PYRO,DS['pyroscope'],profiles(ALLOC),unit='binBps',x=12,description='Sampled allocated bytes per second. Allocation rate is different from retained heap or process RSS.');d.y+=7
    native(d,'Live heap • by version',PYRO,DS['pyroscope'],profiles(HEAP),unit='bytes',description='Estimated live heap from sampled profiles, not total container memory.')
    d.panel('Orders • server errors / second','sum by(service_version)(rate(http_server_duration_milliseconds_count{service_name="parceldesk-agent",http_target="/api/orders",http_status_code=~"5.."}[$__rate_interval])) or on(service_version) (0 * sum by(service_version)(rate(http_server_duration_milliseconds_count{service_name="parceldesk-agent",http_target="/api/orders"}[$__rate_interval])))',kind='timeseries',unit='reqps',legend='{{service_version}}',x=12,w=12,h=7);d.y+=7
    native(d,'CPU • selected version',PYRO,DS['pyroscope'],profiles(CPU,'profile',True),kind='flamegraph',w=24,h=12,description='Select a frame to inspect the function. Profiles carry repository and Git commit labels for source navigation.');d.y+=12
    d.text('Compare two releases','Open **Profiles Drilldown → Diff flame graph** to compare two versions or test windows. Read absolute CPU and memory alongside the relative flamegraph differences. Commit, service version and test timestamps identify each run.',3)
    save(d,'now-1h')

    d=Dashboard('pd-ai-delivery','## What are we spending, and how is work moving?\nCoding-model consumption from Agent Observability, alongside delivery records read directly from GitHub. Repository: **julvo712/parceldesk**. Costs cover the selected coding agents in this demo stack; delivery covers this repository.',DS)
    d.vars=[]
    cost='sum by(gen_ai_agent_name)(increase(agento11y_generation_cost_usd_total{gen_ai_agent_name=~"codex|claude-code|cursor"}[$__range]))'
    d.panel('Recorded model-cost increase',cost,kind='stat',unit='currencyUSD',legend='{{gen_ai_agent_name}}',w=6,h=6,description='Increase in the native server-side model-cost counter over the selected window. Requires at least two samples. API-equivalent consumption, excluding subscriptions; not attributed to individual PRs.')
    native(d,'Merged pull requests',GITHUB,DS['github'],github('Pull_Requests',query='is:merged',timeField=2),kind='stat',x=6,w=6,h=6,field='number',calc='count',description='PRs merged within the selected time range, queried directly from GitHub.')
    native(d,'Median PR time to merge',GITHUB,DS['github'],github('Pull_Requests',query='is:merged',timeField=2),kind='stat',unit='s',x=12,w=6,h=6,field='open_time',calc='median',description='Median of merged_at minus created_at, for PRs merged in the selected window. Includes draft, implementation and review time.')
    native(d,'Published releases',GITHUB,DS['github'],github('Releases'),kind='stat',x=18,w=6,h=6,field='tag',calc='count',description='Published non-draft, non-prerelease GitHub releases in the selected time range.',transforms=[{'id':'filterByValue','spec':{'filters':[{'fieldName':'is_draft','config':{'id':'equal','options':{'value':False}}},{'fieldName':'is_prerelease','config':{'id':'equal','options':{'value':False}}}],'type':'include','match':'all'}}]);d.y+=6
    d.panel('Model-cost activity', 'sum by(gen_ai_agent_name)(rate(agento11y_generation_cost_usd_total{gen_ai_agent_name=~"codex|claude-code|cursor"}[$__rate_interval]))',kind='timeseries',unit='suffix:USD/s',legend='{{gen_ai_agent_name}}',w=12,h=7)
    native(d,'CI outcomes • all branches',GITHUB,DS['github'],github('Workflow_Usage',workflow='ci.yml'),kind='table',x=12,w=12,h=7,description='Native GitHub data source summary for the release-check workflow across repository branches. Superseded runs may be cancelled.',transforms=[{'id':'filterFieldsByName','kind':'transform','spec':{'include':{'names':['runs','successes','failures','cancelled','average run duration (approx.)']}}}]);d.y+=7
    native(d,'Merged changes',GITHUB,DS['github'],github('Pull_Requests',query='is:merged',timeField=2),kind='table',w=24,h=8,transforms=[{'id':'filterFieldsByName','kind':'transform','spec':{'include':{'names':['number','title','created_at','merged_at','open_time','url']}}}]);d.y+=8
    native(d,'Published releases',GITHUB,DS['github'],github('Releases'),kind='table',w=24,h=7,description='Actual GitHub releases and their publication timestamps. A published release does not imply a production deployment.',transforms=[{'id':'filterByValue','kind':'transform','spec':{'filters':[{'fieldName':'is_draft','config':{'id':'equal','options':{'value':False}}},{'fieldName':'is_prerelease','config':{'id':'equal','options':{'value':False}}}],'type':'include','match':'all'}},{'id':'filterFieldsByName','kind':'transform','spec':{'include':{'names':['name','tag','published_at','url']}}}]);d.y+=7
    d.text('Read these measures together','PR time and release cadence describe delivery. Use them with workload, team and quality context when judging an AI investment. A short repository history is a starting point for observation; longer-term trends build as the team uses its normal GitHub workflow.',3)
    save(d,'now-7d')
    print('Generated two native foundation dashboards:',OUT)


if __name__=='__main__':main()
