"""Run the local operator app: python -m recovery_app.server."""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from recovery_app.engine import AppError, Engine

ROOT = Path(__file__).resolve().parents[1]


def make_server(engine, port=8766):
    web = Path(__file__).parent / "web"
    assets = {
        "/": (web / "index.html", "text/html; charset=utf-8"),
        "/index.html": (web / "index.html", "text/html; charset=utf-8"),
        "/app.js": (web / "app.js", "text/javascript; charset=utf-8"),
        "/app.css": (web / "app.css", "text/css; charset=utf-8"),
        "/wallet.js": (web / "wallet.js", "text/javascript; charset=utf-8"),
        "/fonts/manrope.woff2": (ROOT / "site/assets/fonts/manrope.woff2", "font/woff2"),
        "/favicon.svg": (ROOT / "site/assets/favicon.svg", "image/svg+xml"),
    }

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_args):
            pass

        def _origin(self):
            return "http://127.0.0.1:" + str(self.server.server_port)

        def _check(self, mutation=False):
            if self.headers.get("Host") != self._origin().removeprefix("http://"):
                raise AppError("Open the app at " + self._origin(), 403)
            if mutation:
                if self.headers.get("Origin") not in (None, self._origin()):
                    raise AppError("Cross-origin requests are not allowed", 403)
                if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                    raise AppError("Cross-site requests are not allowed", 403)
                if self.headers.get_content_type() != "application/json":
                    raise AppError("Send application/json", 415)
                if self.headers.get("Transfer-Encoding"):
                    raise AppError("Transfer-Encoding is not supported")

        def _respond(self, status, value, content_type="application/json; charset=utf-8", *, filename=None):
            data = json.dumps(value, allow_nan=False).encode() if content_type.startswith("application/json") else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                self._check()
                if self.path in assets:
                    path, kind = assets[self.path]
                    if not path.is_file():
                        raise AppError("Application asset unavailable", 503)
                    return self._respond(200, path.read_bytes(), kind)
                if self.path == "/api/config":
                    return self._respond(200, engine.config())
                if self.path == "/api/incidents":
                    return self._respond(200, {"incidents": engine.list_incidents()})
                match = re.fullmatch(r"/api/incidents/([a-f0-9]{32})(/receipt)?", self.path)
                if match:
                    incident_id = match.group(1)
                    if match.group(2):
                        return self._respond(200, engine.receipt(incident_id), filename=f"belay-{incident_id}.json")
                    return self._respond(200, engine.get(incident_id))
                raise AppError("Not found", 404)
            except AppError as exc:
                self._respond(exc.status, {"error": str(exc)})
            except Exception:
                self._respond(500, {"error": "Unable to read this incident. No external action was issued."})

        def do_POST(self):
            try:
                self._check(mutation=True)
                if len(self.headers.get_all("Content-Length", [])) != 1:
                    raise AppError("One Content-Length header is required")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise AppError("Invalid Content-Length") from None
                if not 0 < length <= 8192:
                    raise AppError("Send a JSON object of at most 8192 bytes")
                try:
                    def reject_constant(_value):
                        raise ValueError("Non-finite number")
                    body = json.loads(self.rfile.read(length), parse_constant=reject_constant)
                except (ValueError, UnicodeError):
                    raise AppError("Invalid JSON") from None
                if not isinstance(body, dict):
                    raise AppError("Send a JSON object")
                if self.path == "/api/incidents" and set(body) == {"scenario"}:
                    return self._respond(201, engine.create(body["scenario"]))
                if self.path == "/api/wallet/prepare" and set(body) == {"sender", "recipient", "amount_units"}:
                    return self._respond(201, engine.prepare_wallet(**body))
                wallet = re.fullmatch(r"/api/wallet/([a-f0-9]{32})/(dispatch|transaction)", self.path)
                if wallet:
                    if wallet.group(2) == "dispatch" and not body:
                        return self._respond(200, engine.dispatch_wallet(wallet.group(1)))
                    if wallet.group(2) == "transaction" and set(body) == {"transaction_hash"}:
                        return self._respond(200, engine.attach_transaction(wallet.group(1), body["transaction_hash"]))
                    raise AppError("Unexpected wallet request fields")
                match = re.fullmatch(r"/api/incidents/([a-f0-9]{32})/(investigate|resolve|probe|revoke)", self.path)
                if match:
                    incident_id, action = match.groups()
                    if action == "investigate" and set(body) == {"agent"}:
                        return self._respond(200, engine.investigate(incident_id, body["agent"]))
                    if action == "resolve" and set(body) == {"proposal_id"}:
                        return self._respond(200, engine.resolve(incident_id, body["proposal_id"]))
                    if action in {"probe", "revoke"} and not body:
                        return self._respond(200, getattr(engine, action)(incident_id))
                    raise AppError("Unexpected incident request fields")
                raise AppError("Unknown endpoint or unexpected request fields", 400)
            except AppError as exc:
                self._respond(exc.status, {"error": str(exc)})
            except (ValueError, TypeError):
                self._respond(400, {"error": "Invalid request values; no automatic retry was issued"})
            except Exception:
                self._respond(500, {"error": "The operation could not finish. Inspect the saved incident before retrying."})

        def unsupported(self):
            self._respond(405, {"error": "Method not allowed"})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = unsupported

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # Drain handlers before the caller releases the engine's directory lease.
    server.daemon_threads = False
    server.block_on_close = True
    return server


def main():
    parser = argparse.ArgumentParser(description="Belay Recovery Desk: local evidence and user-signed Arc testnet transfers")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", default=".belay-recovery")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    engine = Engine(args.data_dir)
    try:
        server = make_server(engine, args.port)
        print(f"Belay Recovery Desk: http://127.0.0.1:{server.server_port}", flush=True)
        print("Local simulations and Arc Testnet only. Wallet keys stay in MetaMask.", flush=True)
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
