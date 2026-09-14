"""Serve the local purchase simulator and its JSON API on loopback only."""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from purchase_simulator.engine import DemoError, Engine
from purchase_simulator.mission_control import MissionEngine


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("Non-finite JSON number")


def make_server(engine, port=8777):
    web = Path(__file__).parent / "web"
    mission_engine = MissionEngine(engine.data_dir)
    assets = {"/": ("index.html", "text/html; charset=utf-8"),
              "/index.html": ("index.html", "text/html; charset=utf-8"),
              "/style.css": ("style.css", "text/css; charset=utf-8"),
              "/app.js": ("app.js", "text/javascript; charset=utf-8"),
              "/purchase": ("purchase/index.html", "text/html; charset=utf-8"),
              "/purchase/": ("purchase/index.html", "text/html; charset=utf-8"),
              "/purchase/style.css": ("purchase/style.css", "text/css; charset=utf-8"),
              "/purchase/app.js": ("purchase/app.js", "text/javascript; charset=utf-8")}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, payload, content_type="application/json; charset=utf-8"):
            body = json.dumps(payload, allow_nan=False).encode("utf-8") if content_type.startswith("application/json") else payload
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                             "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def check_host(self):
            expected = "127.0.0.1:" + str(self.server.server_port)
            if self.headers.get_all("Host", []) != [expected]:
                raise DemoError("Open the simulator through http://" + expected, 403)

        def read_body(self):
            self.check_host()
            origin = "http://127.0.0.1:" + str(self.server.server_port)
            if self.headers.get_all("Origin", []) not in ([], [origin]):
                raise DemoError("Cross-origin requests are not allowed", 403)
            if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                raise DemoError("Cross-site requests are not allowed", 403)
            if self.headers.get_content_type() != "application/json":
                raise DemoError("POST requires application/json", 415)
            if self.headers.get("Transfer-Encoding"):
                raise DemoError("Chunked requests are not supported")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise DemoError("One Content-Length header is required")
            try:
                length = int(lengths[0])
            except ValueError:
                raise DemoError("Invalid Content-Length") from None
            if not 0 < length <= 4096:
                raise DemoError("A JSON object of at most 4096 bytes is required")
            self.connection.settimeout(5)
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("Incomplete request body")
                data = json.loads(raw, object_pairs_hook=strict_object, parse_constant=reject_constant)
            except (ValueError, UnicodeError, OSError):
                raise DemoError("Invalid or incomplete JSON body") from None
            if not isinstance(data, dict):
                raise DemoError("JSON body must be an object")
            return data

        def error(self, exc):
            payload = {"error": str(exc)}
            if exc.current is not None:
                payload["current"] = exc.current
            self.respond(exc.status, payload)

        def do_GET(self):
            try:
                self.check_host()
                if self.path in assets:
                    name, content_type = assets[self.path]
                    path = web / name
                    if not path.is_file():
                        raise DemoError("Simulator interface asset is unavailable", 503)
                    return self.respond(200, path.read_bytes(), content_type)
                if self.path == "/api/config":
                    return self.respond(200, engine.config())
                if self.path == "/api/mission/config":
                    return self.respond(200, mission_engine.config())
                mission = re.fullmatch(r"/api/missions/([a-f0-9]{32})", self.path)
                if mission:
                    return self.respond(200, mission_engine.get(mission.group(1)))
                match = re.fullmatch(r"/api/runs/([a-f0-9]{32})", self.path)
                if match:
                    return self.respond(200, engine.get(match.group(1)))
                raise DemoError("Not found", 404)
            except DemoError as exc:
                self.error(exc)
            except Exception:
                self.respond(500, {"error": "Local simulator error; inspect the run before continuing"})

        def do_POST(self):
            try:
                body = self.read_body()
                if self.path == "/api/runs":
                    if set(body) != {"scenario", "budget_cents", "quantity"}:
                        raise DemoError("Provide only scenario, budget_cents and quantity")
                    return self.respond(201, engine.create(body["scenario"], body["budget_cents"], body["quantity"]))
                if self.path == "/api/missions/analyze":
                    if set(body) not in ({"request"}, {"request", "demo_outcome"}):
                        raise DemoError("Provide request and optionally demo_outcome")
                    return self.respond(201, mission_engine.analyze(
                        body["request"], demo_outcome=body.get("demo_outcome", "success")))
                details = re.fullmatch(r"/api/missions/([a-f0-9]{32})/details", self.path)
                if details:
                    if set(body) != {"expected_revision", "fields"}:
                        raise DemoError("Provide only expected_revision and fields")
                    return self.respond(200, mission_engine.update_details(details.group(1), body["expected_revision"], body["fields"]))
                reconcile = re.fullmatch(r"/api/missions/([a-f0-9]{32})/reconcile", self.path)
                if reconcile:
                    if set(body) != {"expected_revision", "evidence_digest"}:
                        raise DemoError("Provide only expected_revision and evidence_digest")
                    return self.respond(200, mission_engine.reconcile(
                        reconcile.group(1), body["expected_revision"], body["evidence_digest"]))
                mission_action = re.fullmatch(r"/api/missions/([a-f0-9]{32})/(authorize|advance|investigate)", self.path)
                if mission_action:
                    if set(body) != {"expected_revision"}:
                        raise DemoError("Provide only expected_revision")
                    method = {"authorize": mission_engine.authorize, "advance": mission_engine.advance,
                              "investigate": mission_engine.investigate}[mission_action.group(2)]
                    return self.respond(200, method(mission_action.group(1), body["expected_revision"]))
                match = re.fullmatch(r"/api/runs/([a-f0-9]{32})/(advance|verify|investigate)", self.path)
                if match:
                    if set(body) != {"expected_revision"}:
                        raise DemoError("Provide only expected_revision")
                    method = {"advance": engine.advance, "verify": engine.verify,
                              "investigate": engine.investigate}[match.group(2)]
                    return self.respond(200, method(match.group(1), body["expected_revision"]))
                raise DemoError("Not found", 404)
            except DemoError as exc:
                self.error(exc)
            except Exception:
                self.respond(500, {"error": "Local simulator error; reload this run before continuing"})

        def unsupported(self):
            self.respond(405, {"error": "Method not allowed"})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = unsupported

    class MissionHTTPServer(ThreadingHTTPServer):
        def server_close(self):
            try:
                super().server_close()
            finally:
                mission_engine.close()

    server = MissionHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = False
    server.block_on_close = True
    server.mission_engine = mission_engine
    return server


def main():
    parser = argparse.ArgumentParser(
        description="Belay Payment Mission MVP; generalized local payment simulation"
    )
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--data-dir", default=".belay-purchase-simulator")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    engine = Engine(args.data_dir)
    try:
        server = make_server(engine, args.port)
        print(f"Belay Payment Mission MVP: http://127.0.0.1:{server.server_port}", flush=True)
        print(f"Local simulated payments only. Data: {engine.data_dir}", flush=True)
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
