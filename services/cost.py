"""HTTP/API Gateway adapter around the selected checkout's actual Lambda handler."""
import importlib.util
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

path = Path("/source/lambda/langfuse_cost_tracker/lambda_function.py")
bundle = Path("/tmp/ciab-ca.pem")
bundle.write_bytes(Path("/etc/ssl/certs/ca-certificates.crt").read_bytes() + b"\n" + Path("/certs/ca.crt").read_bytes())
os.environ["SSL_CERT_FILE"] = str(bundle)
handler = None
if path.is_file():
    spec = importlib.util.spec_from_file_location("cost_tracker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = module.lambda_handler


class Server(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond(200 if handler else 503, {"available": bool(handler), "source": str(path)})

    def do_POST(self):
        if self.path != "/cost":
            return self.respond(404, {"error": "unknown path"})
        if not handler:
            return self.respond(503, {"error": "selected PR stack does not include AE-225 cost tracker"})
        size = int(self.headers.get("Content-Length", 0))
        if size > 65536:
            return self.respond(413, {"error": "request too large"})
        try:
            event = {"headers": dict(self.headers), "body": self.rfile.read(size).decode()}
            result = handler(event, None)
            self.respond(result["statusCode"], json.loads(result["body"]))
        except Exception as error:
            self.respond(500, {"error": type(error).__name__})

    def respond(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Server).serve_forever()
