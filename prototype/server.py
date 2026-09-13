"""Loopback-only HTTP UI/API for the synthetic Belay prototype."""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prototype.engine import DemoError, Engine


def make_server(engine, port=8765):
    web_file = Path(__file__).parent / "web" / "index.html"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, payload, content_type="application/json; charset=utf-8"):
            data = json.dumps(payload).encode() if content_type.startswith("application/json") else payload
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def check_host(self):
            expected = "127.0.0.1:" + str(self.server.server_port)
            if self.headers.get("Host") != expected:
                raise DemoError("Use this app through http://" + expected, 403)

        def check_post(self):
            self.check_host()
            expected_origin = "http://127.0.0.1:" + str(self.server.server_port)
            if self.headers.get("Origin") not in (None, expected_origin):
                raise DemoError("Cross-origin requests are not allowed", 403)
            if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                raise DemoError("Cross-site requests are not allowed", 403)
            if self.headers.get_content_type() != "application/json":
                raise DemoError("POST requires application/json", 415)
            if self.headers.get("Transfer-Encoding"):
                raise DemoError("Chunked requests are not supported")

        def do_GET(self):
            try:
                self.check_host()
                if self.path == "/":
                    if not web_file.is_file():
                        raise DemoError("Prototype UI file is not available", 503)
                    return self.respond(200, web_file.read_bytes(), "text/html; charset=utf-8")
                if self.path == "/api/cases":
                    return self.respond(200, {"cases": engine.list_cases()})
                match = re.fullmatch(r"/api/cases/([a-f0-9]{32})", self.path)
                if match:
                    return self.respond(200, engine.get(match.group(1)))
                raise DemoError("Not found", 404)
            except DemoError as exc:
                self.respond(exc.status, {"error": str(exc)})
            except Exception:
                self.respond(500, {"error": "Local prototype error; no automatic retry was issued"})

        def do_POST(self):
            try:
                self.check_post()
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise DemoError("Invalid Content-Length") from None
                if not 0 < length <= 4096:
                    raise DemoError("A JSON object of at most 4096 bytes is required")
                try:
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    raise DemoError("Invalid JSON") from None
                if not isinstance(body, dict):
                    raise DemoError("JSON body must be an object")
                if self.path == "/api/cases":
                    if set(body) != {"scenario", "mode"}:
                        raise DemoError("Provide only scenario and mode")
                    return self.respond(201, engine.create(body["scenario"], body["mode"]))
                match = re.fullmatch(r"/api/cases/([a-f0-9]{32})/recover", self.path)
                if match:
                    if body:
                        raise DemoError("Recovery expects an empty JSON object")
                    return self.respond(200, engine.recover(match.group(1)))
                raise DemoError("Not found", 404)
            except DemoError as exc:
                self.respond(exc.status, {"error": str(exc)})
            except Exception:
                self.respond(500, {"error": "Local prototype error; inspect the case before retrying"})

        def unsupported(self):
            self.respond(405, {"error": "Method not allowed"})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = unsupported

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description="Synthetic local refunds; no real money or credentials")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=".belay-prototype")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    engine = Engine(args.data_dir)
    try:
        server = make_server(engine, args.port)
        print(f"Belay prototype: http://127.0.0.1:{server.server_port}", flush=True)
        print(f"Synthetic $100 orders / $50 intended refunds. Data: {engine.data_dir}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        engine.close()


if __name__ == "__main__":
    main()
