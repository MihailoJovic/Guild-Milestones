import json, threading, http.server
LOG=[]
class H(http.server.BaseHTTPRequestHandler):
    def _do(self):
        n=int(self.headers.get("Content-Length",0)); body=json.loads(self.rfile.read(n) or b"null")
        LOG.append((self.command,self.path,body))
        out=json.dumps({"id":"123"}).encode()
        self.send_response(200); self.send_header("Content-Length",str(len(out))); self.end_headers(); self.wfile.write(out)
    do_POST=_do; do_PATCH=_do
    def log_message(self,*a): pass
srv=http.server.HTTPServer(("127.0.0.1",8765),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
