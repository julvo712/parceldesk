"""Native v2 presenter dashboard: GA table actions and real controller telemetry."""
import json

SCENARIOS=[
 ('Guardrails','Prompt injection','supplier_injection','Supplier instructions attempt an unauthorized notification.'),
 ('Quality','Overstrict agent policy','prompt_overstrict','A real model refuses useful work; local tool access is removed.'),
 ('LLM latency','Model boundary delay','llm_boundary_delay','Disclosed delay at the provider adapter.'),
 ('Database','Database contention','db_lock','Real conflicting PostgreSQL lock.'),
 ('Application','Shipping mapping bug','shipping_mapping_bug','Compare the promised date with the raw carrier estimate.'),
 ('Profiling','CPU regression','cpu_regression','Inefficient request code creates trace-linked CPU profiles.'),
 ('Infrastructure','Container CPU pressure','cpu_pressure','Bounded CPU load inside the service quota.'),
 ('Agent behavior','Repeated tool calls','tool_retry_loop','Bounded stock errors expose retries and failed tool calls.'),
 ('Reliability','Guard unavailable','guard_unavailable','Protected tool dispatch fails closed.'),
 ('Frontend','Resolution render error','ui_render_error','Browser rendering fails while backend evidence survives.'),
]

def add_presenter(out,ds,Dashboard,server):
 d=Dashboard('pd-presenter','## The whole story, connected.\n**1 Create a run → 2 Open the customer app → 3 Activate one scenario → 4 Follow the evidence → 5 Reset & verify.**\n\n[Open customer experience](http://localhost:3101/control/presenter/customer) · [Local presenter](http://localhost:3101) · [Runtime investigation](/d/pd-runtime) · [Agent quality](/d/pd-agent-quality)\n\nControls operate on the Mac running this browser. Allow local-network access if prompted. State below is real controller readback exported to Cloud; allow **10–30 seconds** after a click and check freshness.',ds)
 d.vars=[]
 def stat(title,expr,legend='',unit='none',text=False):
  i=d.panel(title,expr,legend=legend,unit=unit,w=6,h=4,x=(len(d.elements)-1)%4*6,y=d.y)
  panel=d.elements[f'panel-{i}']['spec']['vizConfig']['spec']
  panel['options']['text']={'valueSize':26,'titleSize':14}
  if text:panel['options']['textMode']='name'
  return panel
 scenario=stat('Current scenario','parceldesk_presenter_info{scenario="healthy"} or (0 * parceldesk_presenter_info)','{{scenario}}',text=True)
 scenario['fieldConfig']['defaults'].update(color={'mode':'thresholds'},thresholds={'mode':'absolute','steps':[{'color':'orange','value':None},{'color':'green','value':1}]})
 stat('Lease remaining','clamp_min(parceldesk_presenter_lease_expires_seconds - time(),0)',unit='s')
 fresh=stat('Controller readback age','time() - parceldesk_presenter_observed_seconds',unit='s')
 fresh['fieldConfig']['defaults'].update(color={'mode':'thresholds'},thresholds={'mode':'absolute','steps':[{'color':'green','value':None},{'color':'orange','value':30},{'color':'red','value':60}]})
 ready=stat('Controller connection','parceldesk_presenter_available')
 ready['fieldConfig']['defaults']['mappings']=[{'type':'value','options':{'1':{'text':'Connected','color':'green'},'0':{'text':'Unavailable','color':'red'}}}]
 d.y+=4
 def actions(title,rows,command,h):
  i=d.panel(title,kind='table',w=24,h=h,y=d.y,description='Static command catalog, not telemetry. Buttons call the local controller; read the live state and action receipt to verify the effect.')
  e=d.elements[f'panel-{i}']['spec'];d.y+=h
  q={'type':'json','source':'inline','format':'table','parser':'backend','data':json.dumps(rows),'root_selector':'','columns':[{'selector':key,'text':key,'type':'string'} for key in rows[0]]}
  e['data']['spec']['queries']=[{'kind':'PanelQuery','spec':{'refId':'A','hidden':False,'query':{'kind':'DataQuery','group':'yesoreyeram-infinity-datasource','version':'v0','datasource':{'name':'grafanacloud-infinity'},'spec':q}}}]
  config=e['vizConfig']['spec'];config['options'].update(cellHeight='md',showHeader=True)
  action={'type':'fetch','title':'Activate' if command=='activate' else 'Run','confirmation':'Activate ${__data.fields["Scenario"]} for up to five minutes on the current ParcelDesk run?' if command=='activate' else '${__data.fields["Control"]} on this Mac?','fetch':{'url':'http://localhost:3101/control/presenter/command','method':'POST','headers':[['Content-Type','application/json']],'body':'{"command":"activate","scenario":"${__value.raw}","ttl_seconds":300}' if command=='activate' else '{"command":"${__value.raw}"}'}}
  config['fieldConfig']['overrides']=[{'matcher':{'id':'byName','options':'Action'},'properties':[{'id':'custom.cellOptions','value':{'type':'actions'}},{'id':'actions','value':[action]},{'id':'custom.width','value':130}]}, {'matcher':{'id':'byName','options':'Chapter' if command=='activate' else 'Control'},'properties':[{'id':'custom.width','value':210}]}]
 actions('Run controls',[
  {'Control':'Create demo run','Purpose':'New isolated customer fixture; reset an active fault first.','Action':'new_run'},
  {'Control':'Reset & verify','Purpose':'Clear the fault, preserve evidence, confirm healthy readback.','Action':'reset'},
  {'Control':'Run native guard check','Purpose':'Real operator probe. No model call or business action.','Action':'guard_probe'},
  {'Control':'Refresh controller evidence','Purpose':'Read authoritative state; Cloud panels update after ingestion.','Action':'refresh'},
 ],'control',7)
 # Display labels as names, without leaking meaningless metric values into the view.
 d.row({'title':'Active run','expr':'parceldesk_presenter_info','legend':'{{run_id}}'}, {'title':'Accepted prompt / model','expr':'parceldesk_presenter_info','legend':'{{agent_version}} · {{model}}'}, {'title':'Last action receipt','expr':'clamp_max(parceldesk_presenter_action_seconds{status="verified"},1) or (0 * parceldesk_presenter_action_seconds)','legend':'{{command}} · {{status}}'},h=4)
 for i in range(len(d.elements)-2,len(d.elements)+1):
  opt=d.elements[f'panel-{i}']['spec']['vizConfig']['spec']['options'];opt['textMode']='name';opt['text']={'titleSize':16,'valueSize':24}
 d.elements[f'panel-{len(d.elements)}']['spec']['vizConfig']['spec']['fieldConfig']['defaults'].update(color={'mode':'thresholds'},thresholds={'mode':'absolute','steps':[{'color':'red','value':None},{'color':'green','value':1}]})
 actions('Choose the investigation · one active fault at a time',[{'Chapter':chapter,'Scenario':name,'What to look for':desc,'Action':key} for chapter,name,key,desc in SCENARIOS],'activate',14)
 d.row({'title':'Persisted proposals','expr':'parceldesk_presenter_proposals'}, {'title':'Confirmed replacements','expr':'parceldesk_presenter_replacements'}, {'title':'Sandbox notifications','expr':'parceldesk_presenter_notifications'},h=4)
 d.row({'title':'Native guard probe result','expr':'clamp_max(parceldesk_presenter_probe_seconds{result="denied"},1) or (0 * parceldesk_presenter_probe_seconds)','legend':'{{result}}'}, {'title':'Guard probe age','expr':'time() - parceldesk_presenter_probe_seconds','unit':'s'}, {'title':'Probe business actions · must be zero','expr':'parceldesk_presenter_probe_business_actions'},h=4)
 d.elements[f'panel-{len(d.elements)-2}']['spec']['vizConfig']['spec']['options']['textMode']='name'
 d.elements[f'panel-{len(d.elements)-2}']['spec']['vizConfig']['spec']['fieldConfig']['defaults'].update(color={'mode':'thresholds'},thresholds={'mode':'absolute','steps':[{'color':'red','value':None},{'color':'green','value':1}]})
 d.logs('Presenter action receipts · actual run IDs','{service_name="parceldesk-agent"} | json | event="presenter_action" | line_format "{{.command}} · {{.status}} · {{.scenario}} · run {{.run_id}}"')
 d.text('Follow the chapter','**Coding:** [FinOps](/d/pd-coding-finops) → [Adoption](/d/pd-coding-adoption) → [Delivery & quality](/d/pd-delivery-quality)  \n**Agent:** [Generations, guards and experiments](/a/grafana-agento11y-app) · [Quality dashboard](/d/pd-agent-quality)  \n**Application:** [Frontend](/a/grafana-kowalski-app) · [Application Observability](/a/grafana-app-observability-app) · [Traces](/a/grafana-exploretraces-app) · [Profiles](/a/grafana-pyroscope-app)  \n\nUse a fresh conversation after changing scenario. Controls address the current controller run, shared with the local console. A dashboard viewed on another computer cannot control this Mac. A green API toast is a response receipt; verify the scenario, run and readback age above.',5)
 d.save(out)
 p=out/'dashboards'/'pd-presenter.json';obj=json.loads(p.read_text());obj['spec']['timeSettings']['autoRefresh']='10s';obj['spec']['timeSettings']['autoRefreshIntervals']=['10s','15s','30s','1m'];obj['spec']['description']='Parallel presenter console: native Grafana actions call the local ParcelDesk controller, with authoritative state exported to Cloud.';p.write_text(json.dumps(obj,indent=2)+'\n')
