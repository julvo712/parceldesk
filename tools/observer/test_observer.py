import importlib.util,json,pathlib,struct,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
spec=importlib.util.spec_from_file_location('observer',pathlib.Path(__file__).with_name('observer.py'));o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
class Tests(unittest.TestCase):
 def test_cgroup_v2_real_engine_shape(self):
  # Docker Engine stats wire shape: nanoseconds, bytes, and cumulative periods.
  d={'cpu_stats':{'cpu_usage':{'total_usage':2500000000},'throttling_data':{'throttled_time':125000000,'throttled_periods':7,'periods':80}},'memory_stats':{'usage':4096,'limit':8192,'stats':{'inactive_file':1024}},'networks':{'eth0':{'rx_bytes':123,'tx_bytes':345},'eth1':{'rx_bytes':2,'tx_bytes':5}}}
  m=o.decode_stats(d);self.assertEqual(m['parceldesk_container_cpu_usage_seconds_total'],2.5);self.assertEqual(m['parceldesk_container_cpu_throttled_seconds_total'],.125);self.assertEqual(m['parceldesk_container_memory_working_set_bytes'],3072);self.assertEqual(m['parceldesk_container_network_receive_bytes_total'],125)
 def test_cgroup_v1_and_missing_throttling(self):
  m=o.decode_stats({'memory_stats':{'usage':100,'stats':{'total_inactive_file':500}}});self.assertEqual(m['parceldesk_container_memory_working_set_bytes'],0);self.assertNotIn('parceldesk_container_cpu_throttled_periods_total',m);self.assertNotIn('parceldesk_container_cpu_usage_seconds_total',m)
 def test_nanoseconds_and_frame_decoder(self):
  line=b'2026-09-15T10:00:00.123456789Z {"msg":"tool completed"}\n';frame=struct.pack('>BBBBI',1,0,0,0,len(line))+line
  ns,text=list(o.decode_logs(frame))[0];self.assertEqual(ns%1000000000,123456789);self.assertEqual(text,'{"msg":"tool completed"}')
  with self.assertRaises(ValueError):o.demultiplex_logs(frame[:-1])
 def test_docker_scope_filter_and_mutation_path_rejected(self):
  class Reader(o.DockerReader):
   def _get(self,path,query=None):return json.dumps([{'Id':'a'*64,'Labels':{'com.docker.compose.project':'parceldesk','com.docker.compose.service':'operations'}},{'Id':'b'*64,'Labels':{'com.docker.compose.project':'other','com.docker.compose.service':'operations'}}]).encode()
  self.assertEqual(len(Reader().containers()),1)
  with self.assertRaises(ValueError):o.DockerReader()._get('/containers/'+'a'*64+'/stop')
 def test_log_retry_does_not_advance_cursor_and_success_deduplicates(self):
  lines=b'2026-09-15T10:00:00.000000001Z one\n2026-09-15T10:00:00.000000002Z two\n'
  class Reader:
   def logs(self,*args):return lines
  received=[]
  class Handler(BaseHTTPRequestHandler):
   fail=True
   def do_POST(self):
    payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));received.append(payload);self.send_response(503 if Handler.fail else 204);self.end_headers()
   def log_message(self,*args):pass
  server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with tempfile.TemporaryDirectory() as d:
    obs=o.Observer(Reader(),pathlib.Path(d)/'cursor.json',f'http://127.0.0.1:{server.server_port}/loki/api/v1/push');obs.cursors['a']={'ns':0,'keys':[]}
    with self.assertRaises(Exception):obs.collect_logs('a','operations')
    self.assertEqual(obs.cursors['a']['ns'],0);Handler.fail=False;obs.collect_logs('a','operations');obs.collect_logs('a','operations');self.assertEqual(len(received),2);self.assertEqual(obs.log_entries,2);self.assertEqual(len(received[1]['streams'][0]['values']),2)
  finally:server.shutdown();server.server_close()
if __name__=='__main__':unittest.main()
