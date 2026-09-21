"""Project-scoped, GET-only Docker metrics and operations/carrier log observer."""
from __future__ import annotations
import datetime as dt
import hashlib
import http.client
import json
import logging
import os
import pathlib
import re
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT = "parceldesk"
SERVICE_NAMES = {"operations":"parceldesk-operations", "carrier":"parceldesk-carrier", "agent-api":"parceldesk-agent", "web":"parceldesk-web", "postgres":"parceldesk-postgres", "alloy":"parceldesk-alloy", "observer":"parceldesk-observer"}
LOG_SERVICES = {"operations", "carrier"}  # Agent logs already use OTLP; never double ship.
METRICS = {
 "parceldesk_container_cpu_usage_seconds_total":("counter","Cumulative CPU seconds from Docker Engine stats"),
 "parceldesk_container_cpu_throttled_seconds_total":("counter","Cumulative throttled CPU seconds from Docker Engine stats"),
 "parceldesk_container_cpu_throttled_periods_total":("counter","Cumulative throttled CPU periods from Docker Engine stats"),
 "parceldesk_container_cpu_periods_total":("counter","Cumulative CPU scheduling periods from Docker Engine stats"),
 "parceldesk_container_memory_usage_bytes":("gauge","Memory usage including cache from Docker Engine stats"),
 "parceldesk_container_memory_working_set_bytes":("gauge","Memory usage minus inactive file cache from Docker Engine stats"),
 "parceldesk_container_memory_limit_bytes":("gauge","Container memory limit from Docker Engine stats"),
 "parceldesk_container_network_receive_bytes_total":("counter","Received network bytes across container interfaces"),
 "parceldesk_container_network_transmit_bytes_total":("counter","Transmitted network bytes across container interfaces"),
 "parceldesk_container_running":("gauge","Container was running during the last successful collection"),
}
class UnixHTTPConnection(http.client.HTTPConnection):
 def __init__(self,path:str):super().__init__("localhost",timeout=5);self.path=path
 def connect(self):self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect(self.path)
class DockerReader:
 """No method argument or arbitrary URL is exposed to callers."""
 def __init__(self,path="/var/run/docker.sock"):self.path=path
 def _get(self,path,query=None):
  if not (path=="/containers/json" or re.fullmatch(r"/containers/[a-f0-9]{64}/(?:stats|logs)",path)):raise ValueError("Docker endpoint outside observer allowlist")
  conn=UnixHTTPConnection(self.path)
  try:
   conn.request("GET","/v1.45"+path+("?"+urllib.parse.urlencode(query) if query else ""))
   response=conn.getresponse();body=response.read(8*1024*1024+1)
   if response.status!=200:raise RuntimeError(f"Docker read returned {response.status}")
   if len(body)>8*1024*1024:raise RuntimeError("Docker response exceeded collection limit")
   return body
  finally:conn.close()
 def containers(self):
  items=json.loads(self._get("/containers/json",{"all":"true","filters":json.dumps({"label":["com.docker.compose.project="+PROJECT]})}))
  return [c for c in items if c.get("Labels",{}).get("com.docker.compose.project")==PROJECT and c.get("Labels",{}).get("com.docker.compose.service") in SERVICE_NAMES and re.fullmatch("[a-f0-9]{64}",c.get("Id",""))]
 def stats(self,cid):return json.loads(self._get(f"/containers/{cid}/stats",{"stream":"false","one-shot":"true"}))
 def logs(self,cid,since):return self._get(f"/containers/{cid}/logs",{"stdout":"true","stderr":"true","timestamps":"true","since":str(since),"tail":"5000"})

def decode_stats(data):
 cpu=data.get("cpu_stats",{});throttling=cpu.get("throttling_data",{});memory=data.get("memory_stats",{});stats=memory.get("stats",{});usage=memory.get("usage",0)
 inactive=stats.get("inactive_file",stats.get("total_inactive_file",0))
 networks=list(data.get("networks",{}).values())
 result={}
 if "total_usage" in cpu.get("cpu_usage",{}):result["parceldesk_container_cpu_usage_seconds_total"]=cpu["cpu_usage"]["total_usage"]/1e9
 if "usage" in memory:
  result["parceldesk_container_memory_usage_bytes"]=usage
  result["parceldesk_container_memory_working_set_bytes"]=max(0,usage-inactive)
 if "limit" in memory:result["parceldesk_container_memory_limit_bytes"]=memory["limit"]
 if "networks" in data:
  result["parceldesk_container_network_receive_bytes_total"]=sum(n.get("rx_bytes",0) for n in networks)
  result["parceldesk_container_network_transmit_bytes_total"]=sum(n.get("tx_bytes",0) for n in networks)
 # Missing throttling fields are absent, never invented zeros (platform coverage differs).
 for source,target,divisor in [("throttled_time","parceldesk_container_cpu_throttled_seconds_total",1e9),("throttled_periods","parceldesk_container_cpu_throttled_periods_total",1),("periods","parceldesk_container_cpu_periods_total",1)]:
  if source in throttling:result[target]=throttling[source]/divisor
 return result

def demultiplex_logs(body:bytes)->bytes:
 if not body:return b""
 if body[0] not in (0,1,2):return body  # Docker TTY stream.
 parts=[];offset=0
 while offset<len(body):
  if len(body)-offset<8:raise ValueError("truncated Docker log frame")
  stream,_,_,_,size=struct.unpack(">BBBBI",body[offset:offset+8]);offset+=8
  if stream not in (0,1,2) or size>len(body)-offset:raise ValueError("invalid Docker log frame")
  parts.append(body[offset:offset+size]);offset+=size
 return b"".join(parts)

def timestamp_ns(value:str)->int:
 match=re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z",value)
 if not match:raise ValueError("Docker timestamp must be RFC3339 UTC")
 seconds=int(dt.datetime.strptime(match[1],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp())
 return seconds*1_000_000_000+int((match[2] or "").ljust(9,"0"))

def decode_logs(body:bytes):
 for line in demultiplex_logs(body).decode("utf-8",errors="replace").splitlines():
  stamp,sep,text=line.partition(" ")
  if not sep:continue
  try:ns=timestamp_ns(stamp)
  except ValueError:continue
  yield ns,text

def metric_text(samples):
 lines=[]
 for name,(kind,help_text) in METRICS.items():
  lines.extend([f"# HELP {name} {help_text}",f"# TYPE {name} {kind}"])
  for labels,values in samples:
   if name in values:
    labeltext=",".join(k+"="+json.dumps(str(v)) for k,v in sorted(labels.items()))
    lines.append(f"{name}{{{labeltext}}} {values[name]}")
 return "\n".join(lines)+"\n"

class Observer:
 def __init__(self,reader=None,state_path=None,loki_url=None):
  self.reader=reader or DockerReader(os.getenv("DOCKER_SOCKET","/var/run/docker.sock"));self.path=pathlib.Path(state_path or os.getenv("OBSERVER_STATE","/var/lib/observer/cursors.json"));self.loki=loki_url or os.getenv("LOKI_PUSH_URL","http://alloy:3100/loki/api/v1/push")
  self.lock=threading.Lock();self.metrics="";self.last_success=0.;self.errors=0;self.log_entries=0;self.cursors={}
  try:self.cursors=json.loads(self.path.read_text())
  except (FileNotFoundError,ValueError):pass
 def save(self):
  self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix(".tmp");fd=os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
  with os.fdopen(fd,"w") as f:json.dump(self.cursors,f,sort_keys=True)
  os.replace(tmp,self.path)
 def collect_logs(self,cid,service):
  cursor=self.cursors.get(cid,{"ns":int(time.time()-60)*1_000_000_000,"keys":[]});seen=set(cursor["keys"]);fresh=[];newest=cursor["ns"]
  for ns,text in decode_logs(self.reader.logs(cid,max(0,cursor["ns"]//1_000_000_000-1))):
   key=str(ns)+":"+hashlib.sha256(text.encode()).hexdigest()
   if ns<cursor["ns"] or key in seen:continue
   fresh.append([str(ns),text]);seen.add(key);newest=max(newest,ns)
  if not fresh:return
  payload={"streams":[{"stream":{"app":"parceldesk","service_name":SERVICE_NAMES[service],"compose_service":service,"source":"docker-stdout"},"values":sorted(fresh,key=lambda row:int(row[0]))}]}
  request=urllib.request.Request(self.loki,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST")
  with urllib.request.urlopen(request,timeout=5) as response:
   if response.status!=204 and response.status!=200:raise RuntimeError("Loki receiver rejected logs")
  # Retain same-timestamp signatures only; replay overlap below cursor is skipped.
  self.cursors[cid]={"ns":newest,"keys":[key for key in seen if key.startswith(str(newest)+":")]};self.log_entries+=len(fresh);self.save()
 def collect(self):
  samples=[];containers=self.reader.containers()
  for container in containers:
   service=container["Labels"]["com.docker.compose.service"];cid=container["Id"]
   labels={"project":PROJECT,"compose_service":service,"service_name":SERVICE_NAMES[service],"replica":container["Labels"].get("com.docker.compose.container-number","1")}
   running=container.get("State")=="running";values={"parceldesk_container_running":int(running)}
   if running:values.update(decode_stats(self.reader.stats(cid)))
   samples.append((labels,values))
   if service in LOG_SERVICES:
    try:self.collect_logs(cid,service)
    except Exception as error:self.errors+=1;logging.warning("log collection failed for %s: %s",service,type(error).__name__)
  with self.lock:self.metrics=metric_text(samples);self.last_success=time.time()
 def render(self):
  with self.lock:return self.metrics+f"# TYPE parceldesk_observer_last_success_timestamp_seconds gauge\nparceldesk_observer_last_success_timestamp_seconds {self.last_success}\n# TYPE parceldesk_observer_errors_total counter\nparceldesk_observer_errors_total {self.errors}\n# TYPE parceldesk_observer_log_entries_total counter\nparceldesk_observer_log_entries_total {self.log_entries}\n"
 def run(self,stop):
  while not stop.is_set():
   try:self.collect()
   except Exception as error:self.errors+=1;logging.warning("container collection failed: %s",type(error).__name__)
   stop.wait(5)

def main():
 observer=Observer();stop=threading.Event();threading.Thread(target=observer.run,args=(stop,),daemon=True).start()
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   if self.path=="/metrics":body=observer.render().encode();status=200;content="text/plain; version=0.0.4"
   elif self.path=="/health":status=200 if time.time()-observer.last_success<30 else 503;body=json.dumps({"status":"ready" if status==200 else "stale"}).encode();content="application/json"
   else:status=404;body=b"not found";content="text/plain"
   self.send_response(status);self.send_header("Content-Type",content);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(("0.0.0.0",9108),Handler)
 try:server.serve_forever()
 finally:stop.set();server.server_close()
if __name__=="__main__":main()
