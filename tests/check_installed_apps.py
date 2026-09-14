"""Exercise installed application assets and recovery without the source tree.

Install the wheel, then run: python -I tests/check_installed_apps.py
This is deliberately separate from source-tree unittest discovery.
"""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

import purchase_simulator
import recovery_app
from purchase_simulator.engine import Engine
from purchase_simulator.server import make_server


def main():
    source = Path(__file__).resolve().parents[1]
    assert sys.flags.isolated, "Use python -I to exclude checkout imports"
    for package in (purchase_simulator, recovery_app):
        assert not Path(package.__file__).resolve().is_relative_to(source), (
            "Expected an installed package outside the checkout", package.__file__
        )

    with tempfile.TemporaryDirectory(prefix="belay-installed-") as data:
        engine = Engine(data)
        server = make_server(engine, 0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()

        def request(method, path, body=None, expected=200, *, asset=False):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request(method, path, body=None if body is None else json.dumps(body),
                                   headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                content = response.read()
                assert response.status == expected, (method, path, response.status, content)
                if asset:
                    assert len(content) > 100, (path, "Missing packaged asset")
                    return content
                return json.loads(content)
            finally:
                connection.close()

        try:
            for path in ("/", "/app.js", "/style.css", "/purchase/",
                         "/purchase/app.js", "/purchase/style.css"):
                request("GET", path, asset=True)
            for name in ("index.html", "app.js", "app.css", "wallet.js"):
                assert (Path(recovery_app.__file__).parent / "web" / name).is_file(), name

            run = request("POST", "/api/runs", {
                "scenario": "payout_reply_lost", "budget_cents": 30_000, "quantity": 2,
            }, expected=201)
            route = f"/api/runs/{run['id']}"
            while run["step"] < 8:
                run = request("POST", route + "/advance", {"expected_revision": run["revision"]})
            finding = request("POST", route + "/investigate", {"expected_revision": run["revision"]})
            assert finding["can_reconcile"] and finding["verdict"] == "paid", finding
            assert request("GET", route)["revision"] == run["revision"]
            run = request("POST", route + "/advance", {"expected_revision": run["revision"]})
            assert run["provider_payout_count"] == 1, run

            mission = request("POST", "/api/missions/analyze", {
                "request": "Transfer $20 to Acme", "demo_outcome": "payout_reply_lost",
            }, expected=201)
            route = f"/api/missions/{mission['id']}"
            mission = request("POST", route + "/authorize", {"expected_revision": mission["revision"]})
            for _ in range(10):
                if not mission["can_advance"]:
                    break
                mission = request("POST", route + "/advance", {"expected_revision": mission["revision"]})
            assert mission["status"] == "payout_unknown", mission
            finding = request("POST", route + "/investigate", {"expected_revision": mission["revision"]})
            assert finding["can_reconcile"] and finding["verdict"] == "paid", finding
            assert request("GET", route)["revision"] == mission["revision"]
            body = {"expected_revision": mission["revision"], "evidence_digest": finding["evidence_digest"]}
            mission = request("POST", route + "/reconcile", body)
            request("POST", route + "/reconcile", body, expected=409)
            mission = request("POST", route + "/advance", {"expected_revision": mission["revision"]})
            assert mission["receipt"] and mission["terminal"], mission
            assert mission["provider_payment"]["attempt_count"] == 1, mission
            assert mission["money"]["payee_received_usd_cents"] == 2_000, mission
            print("Installed mission and purchase recovery, assets, revisions and single payouts passed.")
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            engine.close()


if __name__ == "__main__":
    main()
