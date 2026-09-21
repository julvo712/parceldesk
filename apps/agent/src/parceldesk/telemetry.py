import json, logging, os, time
from opentelemetry import trace, metrics, _logs
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from prometheus_client import Counter, Histogram, Gauge
from agento11y import Client, ClientConfig, GenerationExportConfig, ApiConfig, AuthConfig, HooksConfig, ContentCaptureMode
from . import config

turns=Counter('parceldesk_turns_total','Completed turns',['outcome','traffic_kind'])
guards=Counter('parceldesk_guard_decisions_total','Actual guard decisions',['action','source'])
tools=Counter('parceldesk_tool_calls_total','Tool outcomes',['tool','status'])
tokens=Counter('parceldesk_llm_tokens_total','Provider reported usage',['provider','model','type','traffic_kind'])
llm_duration=Histogram('parceldesk_llm_duration_seconds','Provider operation seconds',['provider','model','traffic_kind'],buckets=(.1,.5,1,2,5,10,20,40,90))
http_requests=Counter('parceldesk_http_requests_total','HTTP responses',['service','method','status'])
freshness=Gauge('parceldesk_signal_last_seen_seconds','Last real local observation',['signal'])
build=Gauge('parceldesk_build_info','Application version',['version'])
scenario=Gauge('parceldesk_scenario_active','Active scenario',['scenario'])
expires=Gauge('parceldesk_scenario_expires_seconds','Scenario expiration')
last_reset=Gauge('parceldesk_last_reset_timestamp_seconds','Successful reset wallclock')

def setup():
    # Explicit endpoint+empty headers prevent inherited host credentials from escaping into the wrong stack.
    base=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT','http://alloy:4318').rstrip('/')
    resource=Resource.create({'service.name':'parceldesk-agent','service.namespace':'parceldesk','service.version':os.getenv('SERVICE_VERSION','development'),'deployment.environment.name':'demo-local'})
    tp=TracerProvider(resource=resource);tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=base+'/v1/traces',headers={})));trace.set_tracer_provider(tp)
    mp=MeterProvider(resource=resource,metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=base+'/v1/metrics',headers={}),export_interval_millis=10000)]);metrics.set_meter_provider(mp)
    lp=LoggerProvider(resource=resource);lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=base+'/v1/logs',headers={})));_logs.set_logger_provider(lp)
    logger=logging.getLogger('parceldesk');logger.setLevel(logging.INFO);logger.addHandler(LoggingHandler(level=logging.INFO,logger_provider=lp));logger.addHandler(logging.StreamHandler())
    HTTPXClientInstrumentor().instrument()
    c=Client(ClientConfig(generation_export=GenerationExportConfig(protocol='http',endpoint=config.GEN_ENDPOINT,auth=AuthConfig(mode='basic',basic_user=config.CLOUD_TENANT,basic_password=config.CLOUD_TOKEN)),api=ApiConfig(endpoint=config.GEN_ENDPOINT),hooks=HooksConfig(enabled=True,phases=['postflight'],timeout_seconds=5,fail_open=False),content_capture=ContentCaptureMode.FULL,agent_name='parceldesk-replacement'))
    build.labels(os.getenv('SERVICE_VERSION','development')).set(1)
    return c,[tp,mp,lp]

def log(event,**fields):
    s=trace.get_current_span().get_span_context()
    record={'event':event,'trace_id':f'{s.trace_id:032x}','span_id':f'{s.span_id:016x}',**fields}
    logging.getLogger('parceldesk').info(json.dumps(record))
    freshness.labels('logs').set(time.time())
