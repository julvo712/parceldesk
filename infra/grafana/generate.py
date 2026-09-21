#!/usr/bin/env python3
"""Generate native Grafana v2 resources. No credentials or fabricated series."""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
NAMES={
 'pd-presenter':'00 · ParcelDesk | Presenter',
 'pd-overview':'01 · ParcelDesk | Start Here',
 'pd-coding-finops':'02 · ParcelDesk | Coding FinOps',
 'pd-coding-adoption':'03 · ParcelDesk | Coding Adoption',
 'pd-delivery-quality':'04 · ParcelDesk | Delivery & Quality',
 'pd-agent-quality':'05 · ParcelDesk | Agent Quality & Guardrails',
 'pd-runtime':'06 · ParcelDesk | Runtime & Dependencies',
 'pd-demo-readiness':'07 · ParcelDesk | Demo Readiness',
}

def link(title,url):
 return dict(title=title,type='link',icon='external link',tooltip=title,tags=[],asDropdown=False,targetBlank=False,includeVars=True,keepTime=True,url=url)

def variable(name,values,label):
 return {'kind':'CustomVariable','spec':dict(name=name,label=label,query=','.join(values),current={'text':'All','value':'$__all'},options=[{'text':'All','value':'$__all','selected':True}]+[{'text':v,'value':v,'selected':False} for v in values],multi=True,includeAll=True,allValue='.*',hide='dontHide',skipUrlSync=False,allowCustomValue=False)}

class Dashboard:
 def __init__(self,uid,intro,ds,coding=False):
  self.uid=uid;self.ds=ds;self.elements={};self.items=[];self.y=0
  self.vars=[variable('tool',['codex','claude_code','cursor'],'Coding tool')] if coding else [variable('traffic_kind',['runtime','experiment','probe'],'Traffic')]
  self.text('The story',intro,4)
 def panel(self,title,expr=None,kind='stat',unit='none',legend='',description='',x=0,w=8,h=5,y=None,content=None,source='prometheus'):
  i=len(self.elements)+1;n=f'panel-{i}';yy=self.y if y is None else y
  queries=[]
  if expr:
   spec={'expr':expr,'legendFormat':legend,'instant':kind in ('stat','table','bargauge'),'range':kind=='timeseries','format':'table' if kind=='table' else 'time_series','editorMode':'code'}
   if source=='loki':spec={'expr':expr,'queryType':'range','maxLines':100}
   queries=[{'kind':'PanelQuery','spec':{'refId':'A','hidden':False,'query':{'kind':'DataQuery','group':source,'version':'v0','datasource':{'name':self.ds[source]},'spec':spec}}}]
  options={}
  defaults={'unit':unit,'noValue':'No observations','color':{'mode':'palette-classic'},'thresholds':{'mode':'absolute','steps':[{'color':'blue','value':None}]},'mappings':[{'type':'special','options':{'match':'null','result':{'text':'No observations','color':'#8e8e98','index':0}}}]}
  if unit=='percentunit' and ('coverage' in title.lower() or 'completeness' in title.lower()):
   defaults['color']={'mode':'thresholds'}
   defaults['thresholds']={'mode':'absolute','steps':[{'color':'orange','value':None},{'color':'green','value':1}]}
  if kind=='stat':options={'reduceOptions':{'calcs':['lastNotNull'],'fields':'','values':False},'orientation':'auto','textMode':'auto','colorMode':'value','graphMode':'none','justifyMode':'auto','text':{'valueSize':32,'titleSize':16}}
  elif kind=='timeseries':
   options={'legend':{'displayMode':'list','placement':'bottom','calcs':[]},'tooltip':{'mode':'multi','sort':'desc'}}
   defaults['custom']={'drawStyle':'line','lineInterpolation':'smooth','lineWidth':2,'fillOpacity':12,'showPoints':'never','spanNulls':False,'axisCenteredZero':False,'axisColorMode':'text','axisBorderShow':False,'scaleDistribution':{'type':'linear'},'hideFrom':{'legend':False,'tooltip':False,'viz':False}}
  elif kind=='bargauge':options={'orientation':'horizontal','displayMode':'gradient','reduceOptions':{'calcs':['lastNotNull'],'fields':'','values':False},'showUnfilled':False}
  elif kind=='text':options={'mode':'markdown','content':content or ''}
  elif kind=='logs':options={'showTime':True,'showLabels':False,'showCommonLabels':False,'wrapLogMessage':True,'sortOrder':'Descending','enableLogDetails':True,'prettifyLogMessage':False}
  elif kind=='table':options={'showHeader':True,'cellHeight':'sm','footer':{'show':False}}
  self.elements[n]={'kind':'Panel','spec':{'id':i,'title':title,'description':description or 'Measured observations only. Missing telemetry is not zero. See the measurement contract.','links':[],'data':{'kind':'QueryGroup','spec':{'queries':queries,'transformations':[],'queryOptions':{'maxDataPoints':500,'interval':'15s'}}},'vizConfig':{'kind':'VizConfig','group':kind,'version':'13.0.0','spec':{'options':options,'fieldConfig':{'defaults':defaults,'overrides':[]}}},'transparent':kind=='text'}}
  self.items.append({'kind':'GridLayoutItem','spec':{'x':x,'y':yy,'width':w,'height':h,'element':{'kind':'ElementReference','name':n}}})
  return i
 def row(self,*panels,h=6):
  w=24//len(panels)
  for j,p in enumerate(panels):self.panel(x=j*w,w=w,h=h,**p)
  self.y+=h
 def text(self,title,content,h=3):
  h=max(h,4)+1
  self.panel(title,kind='text',content=content,w=24,h=h);self.y+=h
 def logs(self,title,query):
  self.panel(title,query,kind='logs',source='loki',w=24,h=8);self.y+=8
 def save(self,out):
  spec=dict(title=NAMES[self.uid],description='ParcelDesk production demo · evidence over claims',tags=['parceldesk','managed-by-gcx'],annotations=[],cursorSync='Crosshair',editable=True,preload=False,elements=self.elements,layout={'kind':'GridLayout','spec':{'items':self.items}},links=[link(v.split('| ')[1],f'/d/{k}') for k,v in NAMES.items() if k!=self.uid],variables=self.vars,timeSettings={'from':'now-1h','to':'now','timezone':'browser','autoRefresh':'30s','autoRefreshIntervals':['15s','30s','1m','5m'],'hideTimepicker':False,'fiscalYearStartMonth':0})
  obj={'apiVersion':'dashboard.grafana.app/v2','kind':'Dashboard','metadata':{'name':self.uid,'annotations':{'grafana.app/folder':'parceldesk-demo'},'labels':{'parceldesk-owner':'demo'}},'spec':spec}
  (out/'dashboards'/f'{self.uid}.json').write_text(json.dumps(obj,indent=2)+'\n')

def p(title,expr,kind='stat',unit='none',legend='',description=''):
 return dict(title=title,expr=expr,kind=kind,unit=unit,legend=legend,description=description)

def generate(out,ds,context="demotests_gcloud",server="https://demotests.grafana.net"):
 server=server.rstrip("/")
 out.mkdir(parents=True,exist_ok=True)
 for folder in ('dashboards','folders'):(out/folder).mkdir(exist_ok=True)
 (out/'folders'/'parceldesk-demo.json').write_text(json.dumps({'apiVersion':'folder.grafana.app/v1','kind':'Folder','metadata':{'name':'parceldesk-demo','labels':{'parceldesk-owner':'demo'}},'spec':{'title':'ParcelDesk Demo','description':'Owned ParcelDesk demo dashboards, maintained through gcx.'}},indent=2)+'\n')
 from presenter_dashboard import add_presenter
 add_presenter(out,ds,Dashboard,server)
 t='traffic_kind=~"$traffic_kind"';c='tool=~"$tool"'
 d=Dashboard('pd-overview','## Build with AI. Ship with evidence.\nStart with a real replacement request. Follow its customer outcome into the agent, dependencies and infrastructure. Then compare prompt versions and the development work that produced them. **Traffic selection separates runtime, experiment and probe work.**',ds)
 d.row(p('Agent turns',f'sum(increase(parceldesk_turns_total{{{t}}}[$__range]))'),p('LLM latency · p95',f'histogram_quantile(0.95,sum by(le)(rate(parceldesk_llm_duration_seconds_bucket{{{t}}}[$__rate_interval])))',unit='s'),p('Agent outcomes',f'sum by(outcome)(increase(parceldesk_turns_total{{{t}}}[$__range]))',kind='bargauge',legend='{{outcome}}'))
 d.row(p('Turn outcomes over time',f'sum by(outcome)(rate(parceldesk_turns_total{{{t}}}[$__rate_interval]))',kind='timeseries',unit='ops',legend='{{outcome}}'),p('LLM reported usage fields',f'sum by(traffic_kind,type)(increase(parceldesk_llm_tokens_total{{{t}}}[$__range]))',kind='bargauge',legend='{{traffic_kind}} · {{type}}'))
 d.row(p('Guard decisions','sum by(action,source)(increase(parceldesk_guard_decisions_total[$__range]))',kind='bargauge',legend='{{source}} · {{action}}'),p('Primary verdicts · by verifier','sum by(evaluator_version,result)(parceldesk_evaluations_total{check="primary_verdict"})',kind='bargauge',legend='{{evaluator_version}} · {{result}}'),p('Service build metadata','sum by(version)(parceldesk_build_info)',kind='table'))
 d.text('Choose a chapter','**Developer / budget:** Coding FinOps → Adoption → Delivery & Quality.  \n**Trust / safety:** Agent Quality & Guardrails.  \n**Reliability:** Runtime & Dependencies → logs, trace and profile.  \n**Presenter:** Demo Readiness before starting. A blocked attack can mean prevention succeeded while agent behavior failed.',4)
 d.save(out)
 d=Dashboard('pd-coding-finops','## What did development consume?\n**API-equivalent USD estimates, not subscription invoices.** Real imported sessions only. Ledger totals are cumulative snapshots at the selected end time; time-series charts show how those totals were observed. Missing price or token fields remain unknown. One developer using three tools is still one developer.',ds,True)
 d.row(p('Estimated coding consumption',f'sum(parceldesk_coding_cost_usd{{{c}}})',unit='currencyUSD'),p('Observed sessions',f'sum(parceldesk_coding_sessions{{{c}}})'),p('Price coverage by tool',f'parceldesk_coding_price_coverage{{{c}}}',unit='percentunit',legend='{{tool}}'))
 d.row(p('Consumption by tool / model',f'sum by(tool,model)(parceldesk_coding_cost_usd{{{c}}})',kind='bargauge',unit='currencyUSD',legend='{{tool}} · {{model}}'),p('Input / output / cache tokens',f'sum by(tool,type)(parceldesk_coding_tokens_total{{{c}}})',kind='bargauge',legend='{{tool}} · {{type}}'),h=9)
 d.row(p('Observed cost over time',f'sum by(tool)(parceldesk_coding_cost_usd{{{c}}})',kind='timeseries',unit='currencyUSD',legend='{{tool}}'),p('Attributed / unassigned task cost',f'sum by(tool,coverage)(parceldesk_development_cost_usd{{{c}}})',kind='bargauge',unit='currencyUSD',legend='{{tool}} · {{coverage}}'))
 d.text('Interpret the numbers','Cached-input and cache-write semantics are normalized per provider before estimation. Coverage must be read beside every estimate. Session, user and repository detail belongs to the source ledger/log records, not unbounded metric labels. Actual seat spend is unavailable unless explicitly supplied; no invoice total is inferred.',3)
 d.logs('Coding session evidence · expand for source fields','{service_name="parceldesk-development"} | json | event=~"coding_session_imported|coding_session_enriched|session_linked" | tool=~"$tool"')
 d.save(out)
 d=Dashboard('pd-coding-adoption','## Are the coding tools being used?\nObserved usage from this developer’s real local sessions. Session volume describes activity; it does not prove productivity. Adoption percentage needs an eligible user roster and is deliberately not inferred.',ds,True)
 d.row(p('Sessions by coding tool',f'parceldesk_coding_sessions{{{c}}}',kind='bargauge',legend='{{tool}}'),p('Token activity by tool',f'sum by(tool)(parceldesk_coding_tokens_total{{{c}}})',kind='bargauge',legend='{{tool}}'),p('Pricing integration coverage',f'parceldesk_coding_price_coverage{{{c}}}',unit='percentunit',legend='{{tool}}'))
 d.row(p('Observed session inventory',f'parceldesk_coding_sessions{{{c}}}',kind='timeseries',legend='{{tool}}'),p('Observed token inventory',f'sum by(tool,type)(parceldesk_coding_tokens_total{{{c}}})',kind='timeseries',legend='{{tool}} · {{type}}'))
 d.logs('Real source and integration evidence','{service_name="parceldesk-development"} | json | event=~"coding_session_imported|coding_session_enriched|coding_import_failed|session_linked" | tool=~"$tool"')
 d.text('Scope and denominators','**People:** single-presenter scope, not three developers. **Sessions:** distinct source session IDs after deduplication. **Trend:** exporter observation time, not a reconstructed historical workday. Integration failures appear in source evidence when observed. No eligible-roster adoption percentage or human hours saved is claimed.',4)
 d.save(out)
 d=Dashboard('pd-delivery-quality','## Did the work produce an accepted change?\nA durable task ledger records start → candidate → evaluation → acceptance, with explicit session and commit links. Elapsed time includes rejected attempts. These are measured outcomes of this demo workflow, not a causal ranking of coding tools.',ds,True)
 d.row(p('Accepted tasks · ledger snapshot','sum(parceldesk_development_tasks{state="accepted"})'),p('Mean time to accepted change','sum(parceldesk_development_accepted_duration_seconds_sum) / sum(parceldesk_development_accepted_duration_seconds_count)',unit='s'),p('Rejected candidate evaluations','sum(parceldesk_development_candidates_total{outcome="rejected"})'))
 d.row(p('Task state inventory','sum by(state)(parceldesk_development_tasks)',kind='bargauge',legend='{{state}}'),p('Candidate outcomes','sum by(outcome)(parceldesk_development_candidates_total)',kind='bargauge',legend='{{outcome}}'))
 d.row(p('Time to acceptance · p95','histogram_quantile(0.95,sum by(le)(parceldesk_development_accepted_duration_seconds_bucket))',unit='s'),p('Known consumption / accepted task',f'sum(parceldesk_development_cost_usd{{{c},coverage="accepted"}}) / sum(parceldesk_development_tasks{{state="accepted"}})',unit='currencyUSD',description='Only explicitly allocated accepted-task consumption in numerator. Missing attribution is unknown; denominator excludes unfinished work.'),p('First-pass accepted tasks','sum(parceldesk_development_tasks_first_pass_total) / sum(parceldesk_development_tasks{state="accepted"})',unit='percentunit'))
 d.logs('Task, candidate, session and commit evidence','{service_name="parceldesk-development"} | json | event=~"task_started|session_linked|candidate_submitted|candidate_evaluated|candidate_accepted|task_closed|commit_linked|pr_observed"')
 d.text('Attribution contract','One session may support several tasks; allocations must sum to at most 100%. Unknown prices and unassigned sessions remain visible in FinOps. A never-accepted task stays incomplete. Exact commit/PR relationships are recorded only from an explicit link; no PR is guessed from nearby timestamps.',3)
 d.save(out)
 d=Dashboard('pd-agent-quality','## Separate agent behavior from successful prevention\nA tool guard denying an unsafe recipient is a prevention success **and** evidence of an unsafe agent attempt. Compare system-prompt versions on the same frozen cases, model and evaluator settings. Deterministic business checks are independent of an LLM judge. **Verifier 1 is legacy; verifier 2 uses stricter persisted-evidence checks. Compare prompt versions under the same verifier.**',ds)
 evaluation_model=variable('eval_model',['claude-sonnet-4-5-20250929','claude-haiku-4-5-20251001','gemini-2.5-flash','unknown'],'Evaluation model')
 evaluation_model['spec']['current']={'text':'claude-sonnet-4-5-20250929','value':'claude-sonnet-4-5-20250929'}
 for option in evaluation_model['spec']['options']:option['selected']=option['value']=='claude-sonnet-4-5-20250929'
 d.vars.append(evaluation_model)
 evaluation_suite=variable('eval_suite',['full','smoke','heldout','unknown'],'Evaluation suite')
 evaluation_suite['spec']['current']={'text':'full','value':'full'}
 for option in evaluation_suite['spec']['options']:option['selected']=option['value']=='full'
 d.vars.append(evaluation_suite)
 d.row(p('Evaluated trials · verifier / source','sum by(evaluator_version,source)(parceldesk_evaluations_total{evaluation_suite=~"$eval_suite",model=~"$eval_model",check="primary_verdict"})',legend='verifier {{evaluator_version}} · {{source}}'),p('Primary pass fraction · by verifier','(sum by(evaluator_version,source)(parceldesk_evaluations_total{evaluation_suite=~"$eval_suite",model=~"$eval_model",check="primary_verdict",result="pass"}) or (0 * sum by(evaluator_version,source)(parceldesk_evaluations_total{evaluation_suite=~"$eval_suite",model=~"$eval_model",check="primary_verdict"}))) / (sum by(evaluator_version,source)(parceldesk_evaluations_total{evaluation_suite=~"$eval_suite",model=~"$eval_model",check="primary_verdict"}) > 0)',unit='percentunit',legend='verifier {{evaluator_version}} · {{source}}'),p('Guard decision inventory','sum by(action,source)(parceldesk_guard_decisions_total)',kind='bargauge',legend='{{source}} · {{action}}'))
 d.row(p('Checks by prompt version','sum by(model,version,evaluator_version,result)(parceldesk_evaluations_total{evaluation_suite=~"$eval_suite",model=~"$eval_model",check="primary_verdict"})',kind='bargauge',legend='{{model}} · {{version}} · v{{evaluator_version}} · {{result}}'),h=12)
 d.row(p('Business correctness breakdown','sum by(check,evaluator_version,result)(parceldesk_evaluations_total{evaluation_suite=~"$eval_suite",model=~"$eval_model"})',kind='bargauge',legend='{{check}} · verifier {{evaluator_version}} · {{result}}'),h=9)
 d.row(p('Tool call attempts','sum by(tool,status)(increase(parceldesk_tool_calls_total{service_name="parceldesk-agent"}[$__range]))',kind='timeseries',legend='{{tool}} · {{status}}'),p('Reported usage · cache may overlap input',f'sum by(traffic_kind,type)(increase(parceldesk_llm_tokens_total{{{t}}}[$__range]))',kind='bargauge',legend='{{traffic_kind}} · {{type}}'))
 d.row(p('Native evaluation LLM consumption','sum by(evaluator_version,coverage)(parceldesk_evaluation_cost_usd{evaluation_suite=~"$eval_suite",model=~"$eval_model"})',kind='bargauge',unit='currencyUSD',legend='verifier {{evaluator_version}} · {{coverage}}'),p('Native evaluation tokens','sum by(evaluator_version,coverage)(parceldesk_evaluation_tokens_total{evaluation_suite=~"$eval_suite",model=~"$eval_model"})',kind='bargauge',legend='verifier {{evaluator_version}} · {{coverage}}'),p('Report state / source','sum by(evaluator_version,source,status,native_result_status)(parceldesk_evaluation_reports{evaluation_suite=~"$eval_suite",model=~"$eval_model"})',kind='table'))
 d.logs('Evaluation and guard evidence','{service_name=~"parceldesk-(agent|development)"} | json | event=~"evaluation_completed|evaluation_observed|guard_decision|candidate_evaluated|candidate_accepted"')
 d.text('Native investigation','Open [**Agent Observability**](/a/grafana-agento11y-app) to inspect conversations, generations, guards and experiments. Pending or errored native evaluations are not passes. Native experiment IDs and trace IDs are retained in the evidence events. Known-pattern filtering is not universal prompt-injection detection.',4)
 d.save(out)
 d=Dashboard('pd-runtime','## The same symptom can have a different cause\nFollow the browser request into the API, LLM, tool, carrier and SQL spans. A slow request is not automatically a slow model. Infrastructure and profile panels require their collector signals; no data is not healthy infrastructure.',ds)
 d.row(p('API request rate','sum by(service)(rate(parceldesk_http_requests_total[$__rate_interval]))',kind='timeseries',unit='reqps',legend='{{service}}'),p('API error fraction','(sum(rate(parceldesk_http_requests_total{status=~"5.."}[$__rate_interval])) or (0 * sum(rate(parceldesk_http_requests_total[$__rate_interval])))) / (sum(rate(parceldesk_http_requests_total[$__rate_interval])) > 0)',unit='percentunit'),p('LLM latency · p95',f'histogram_quantile(0.95,sum by(le)(rate(parceldesk_llm_duration_seconds_bucket{{{t}}}[$__rate_interval])))',unit='s'))
 d.row(p('LLM latency by model · p95',f'histogram_quantile(0.95,sum by(le,model)(rate(parceldesk_llm_duration_seconds_bucket{{{t}}}[$__rate_interval])))',kind='timeseries',unit='s',legend='{{model}}'),p('Tool error / result mix','sum by(tool,status)(rate(parceldesk_tool_calls_total{service_name="parceldesk-agent"}[$__rate_interval]))',kind='timeseries',unit='ops',legend='{{tool}} · {{status}}'))
 d.row(p('Scrape targets','up{job=~"parceldesk.*"}',kind='bargauge',legend='{{job}} · {{instance}}'),p('Process CPU cores','rate(process_cpu_seconds_total{job=~"parceldesk.*"}[$__rate_interval])',kind='timeseries',unit='cores',legend='{{job}}'),p('Process resident memory','process_resident_memory_bytes{job=~"parceldesk.*"}',kind='timeseries',unit='bytes',legend='{{job}}'))
 d.row(p('Customer API latency · p95','histogram_quantile(0.95,sum by(le)(rate(http_server_duration_milliseconds_bucket{service_name="parceldesk-agent",http_target=~"/api/.*"}[$__rate_interval]))) / 1000',kind='timeseries',unit='s',legend='API p95'),p('Operations latency · p95','histogram_quantile(0.95,sum by(le)(rate(http_server_request_duration_seconds_bucket{service_name="parceldesk-operations",http_route!~"/health.*"}[$__rate_interval])))',kind='timeseries',unit='s',legend='Operations p95'),p('Carrier latency · p95','histogram_quantile(0.95,sum by(le)(rate(http_server_request_duration_seconds_bucket{service_name="parceldesk-carrier",http_route!~"/health.*"}[$__rate_interval])))',kind='timeseries',unit='s',legend='Carrier p95'))
 d.row(p('Container CPU cores','sum by(compose_service)(rate(parceldesk_container_cpu_usage_seconds_total{project="parceldesk"}[$__rate_interval]))',kind='timeseries',unit='cores',legend='{{compose_service}}'),p('Container working set','sum by(compose_service)(parceldesk_container_memory_working_set_bytes{project="parceldesk"})',kind='timeseries',unit='bytes',legend='{{compose_service}}'),p('CPU throttled time','sum by(compose_service)(rate(parceldesk_container_cpu_throttled_seconds_total{project="parceldesk"}[$__rate_interval]))',kind='timeseries',unit='s',legend='{{compose_service}}'))
 d.row(p('Business tool latency · p95','histogram_quantile(0.95,sum by(le,tool_name)(rate(parceldesk_tool_duration_seconds_bucket[$__rate_interval])))',kind='timeseries',unit='s',legend='{{tool_name}}'),p('PostgreSQL locks','sum by(mode)(pg_locks_count{service_name="parceldesk-postgres"})',kind='timeseries',legend='{{mode}}'),p('Long-running database transactions','sum(pg_long_running_transactions{service_name="parceldesk-postgres"})'))
 d.logs('Correlated runtime logs','{service_name=~"parceldesk.*"} | json | route!~"/health.*|/metrics"')
 d.text('Follow the evidence','[Frontend Observability](/a/grafana-kowalski-app) · [Application Observability](/a/grafana-app-observability-app) · [Traces Drilldown](/a/grafana-exploretraces-app) · [Profiles Drilldown](/a/grafana-pyroscope-app) · [Logs Drilldown](/a/grafana-lokiexplore-app). Use the structured **trace_id** to open the distributed trace in Tempo. Follow the Go CPU request span to its profile when profiling correlation is available. SQL spans distinguish lock wait from model latency; carrier raw arrival data distinguishes application mapping errors from an LLM claim. Browser errors and performance are in the ParcelDesk Frontend Observability application.',4)
 d.save(out)
 d=Dashboard('pd-demo-readiness','## Check the evidence before presenting\nFreshness means a real signal was seen. Missing integrations, unknown prices and pending evaluations stay visible. Use the local presenter console to run doctor, reset and a baseline request before the meeting.',ds)
 d.row(p('ParcelDesk scrape targets','up{job=~"parceldesk.*"}',kind='bargauge',legend='{{job}}'),p('Signal age','time() - parceldesk_signal_last_seen_seconds',kind='bargauge',unit='s',legend='{{signal}}'),p('Service build metadata','sum by(version)(parceldesk_build_info)',kind='table'))
 d.row(p('Coding integrations · sessions','parceldesk_coding_sessions',kind='bargauge',legend='{{tool}}'),p('Pricing completeness','parceldesk_coding_price_coverage',kind='bargauge',unit='percentunit',legend='{{tool}}'),p('Active scenario','parceldesk_scenario_active',kind='bargauge',legend='{{scenario}}'))
 d.row(p('Scenario lease remaining','clamp_min(parceldesk_scenario_expires_seconds - time(),0)',unit='s'),p('Time since reset','time() - parceldesk_last_reset_timestamp_seconds',unit='s'),p('Observed evaluation checks','sum by(evaluator_version)(parceldesk_evaluations_total{check="primary_verdict"})'))
 d.row(p('Evaluation report age','time() - parceldesk_evaluation_report_last_seen_seconds',kind='bargauge',unit='s',legend='{{source}} · {{status}}'),p('Evaluation file read errors','parceldesk_evaluation_report_read_errors'),p('Container observer age','time() - parceldesk_observer_last_success_timestamp_seconds',unit='s'))
 d.row(p('Development snapshot age','time() - parceldesk_development_snapshot_published_seconds',unit='s',description='Time since the host last atomically published its real ledger. Idle development legitimately leaves this unchanged.'),p('Development snapshot read errors','parceldesk_development_snapshot_read_error',description='Zero means the container read a complete host snapshot; no cross-VM SQLite access.'),p('Unpriced coding records','sum(parceldesk_coding_unpriced_records)',description='Unknown cost remains visible even when some authentic consumption is priced.'))
 d.logs('Readiness, fault and reset evidence','{service_name="parceldesk-agent"} | json | event=~"doctor_completed|scenario_activated|scenario_expired|scenario_reset|reset_completed|coding_import_failed"')
 d.text('Presentation checklist','1. Confirm real LLM mode and baseline replacement.  \n2. Confirm traces, logs, metrics, browser and profile links.  \n3. Confirm all three coding sources are authentic; read price coverage.  \n4. Confirm candidate experiment verdicts and sample counts.  \n5. Enable one leased fault; explain the evidence; reset and rerun.  \n**Unavailable signal ≠ successful check.** Saved evidence must be labelled as saved.',5)
 d.save(out)
 (out.parent/'manifest.json').write_text(json.dumps({'schemaVersion':1,'owner':'parceldesk-demo','context':context,'server':server,'folder':'parceldesk-demo','dashboard_api':'dashboard.grafana.app/v2','datasources':ds,'dashboards':[{'uid':k,'title':v,'path':f'resources/dashboards/{k}.json','url':f'{server}/d/{k}'} for k,v in NAMES.items()]},indent=2)+'\n')

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--output',type=Path,default=ROOT/'resources');a.add_argument('--context',default='demotests_gcloud');a.add_argument('--server',default='https://demotests.grafana.net');a.add_argument('--prometheus',default='grafanacloud-prom');a.add_argument('--loki',default='grafanacloud-logs');a.add_argument('--tempo',default='grafanacloud-traces');a.add_argument('--pyroscope',default='grafanacloud-profiles');v=a.parse_args()
 generate(v.output,dict(prometheus=v.prometheus,loki=v.loki,tempo=v.tempo,pyroscope=v.pyroscope),context=v.context,server=v.server)
