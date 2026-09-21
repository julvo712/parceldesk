"""Discard-only local protocol receiver for architecture smoke tests; never exports."""
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_POST(self):
  self.rfile.read(min(int(self.headers.get('Content-Length','0')),8*1024*1024));self.send_response(200);self.send_header('Content-Type','application/x-protobuf');self.send_header('Content-Length','0');self.end_headers()
 def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'local architecture test sink')
 def log_message(self,*args):pass
HTTPServer(('0.0.0.0',4318),Handler).serve_forever()
