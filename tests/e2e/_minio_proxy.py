# ruff: noqa
import http.server
import socketserver
import urllib.request
import urllib.parse


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/health"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def _proxy(self):
        parsed = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)
        url = query_params["url"][0]
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None
        req = urllib.request.Request(url, data=body, method=self.command)
        for header in ["Content-Type", "Content-Length"]:
            if header in self.headers:
                req.add_header(header, self.headers[header])
        with urllib.request.urlopen(req) as resp:
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp.read())


if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", 8080), ProxyHandler) as httpd:
        httpd.serve_forever()
