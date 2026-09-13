"""Sandbox evaluation checks; all model transports in this file are offline."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.evaluate_recovery import evaluate, heuristic_agent, main  # noqa: E402
from second.dossier import Claim  # noqa: E402
from second.evidence import Observation, Pointer  # noqa: E402
from second.live_agent import OpenAIRecoveryAgent  # noqa: E402


def mock_model():
    """Exercise actual API serialization with a clearly simulated responder."""
    heuristic = heuristic_agent()

    def transport(request, timeout):
        body = json.loads(request.data)
        data = json.loads(body["input"][1]["content"])
        if body["text"]["format"]["name"] == "recovery_pointers":
            value = {"pointers": heuristic.propose_pointers(data["view"])}
        else:
            observations = [Observation(Pointer.parse(obs["pointer"]), obs["payload"], "offline-fixture")
                            for obs in data["observations"]]
            value = heuristic.conclude(data["view"], observations).as_dict()
        return json.dumps({
            "status": "completed", "usage": {"input_tokens": 100, "output_tokens": 30},
            "output": [{"type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": json.dumps(value)}]}],
        }).encode()

    return OpenAIRecoveryAgent(api_key="sk-offline-eval-placeholder", model="explicit-test-model", transport=transport)


class EvaluationTests(unittest.TestCase):
    def test_default_covers_resolution_uncertainty_and_revocation_without_network(self):
        with patch.dict(os.environ, {"SECOND_OVERCONFIDENCE_P": "1", "SECOND_LAZINESS_P": "1"}):
            report = evaluate()
        result = report["summary"]["by_agent"]["heuristic"]
        self.assertEqual(report["summary"]["unique_cases"], 24)
        self.assertEqual(result["samples"], 24)
        self.assertEqual(result["resolved"], 8)
        self.assertEqual(result["false_resolutions"], 0)
        self.assertEqual(result["abstained"], 14)
        self.assertEqual(result["refused"], 2)
        self.assertEqual(report["live_model_requests"], 0)
        self.assertEqual(result["requests"], 0)
        for row in report["cases"]:
            if row["permission_revoked"]:
                self.assertEqual(row["ledger_before_cents"], row["ledger_after_cents"])

    def test_agents_and_repeats_receive_identical_isolated_fixtures(self):
        report = evaluate({"heuristic": heuristic_agent, "openai_mock": mock_model}, cases=3, repeats=2)
        groups = {}
        for row in report["cases"]:
            groups.setdefault(row["case_id"], []).append(row)
        for rows in groups.values():
            self.assertEqual(len(rows), 4)
            self.assertEqual(len({row["fixture_digest"] for row in rows}), 1)
            self.assertEqual(len({tuple(row["ledger_before_cents"]) for row in rows}), 1)
            self.assertEqual(len({row["grade"] for row in rows}), 1)
        self.assertEqual(report["live_model_requests"], 0)
        mocked = report["summary"]["by_agent"]["openai_mock"]
        self.assertEqual(mocked["requests"], 12)
        self.assertEqual(mocked["input_tokens"], 1200)
        self.assertEqual(mocked["output_tokens"], 360)
        self.assertIsNone(mocked["estimated_cost_usd"])
        self.assertNotIn("sk-offline-eval-placeholder", json.dumps(report))
        self.assertTrue(all(row["metrics"]["transport"] == "mock" for row in report["cases"] if row["agent"] == "openai_mock"))

    def test_fabricated_citations_never_resolve(self):
        class GuessingAgent:
            def propose_pointers(self, view):
                return ["invented_source:manifest"]

            def conclude(self, view, observations):
                return Claim("committed", ["fabricated"], ["I guessed"])

        report = evaluate({"guessing": GuessingAgent}, cases=2)
        result = report["summary"]["by_agent"]["guessing"]
        self.assertEqual(result["resolved"], 0)
        self.assertEqual(result["abstained"], 2)
        self.assertEqual(result["false_resolutions"], 0)

    def test_grader_uses_ledger_instead_of_claimed_success(self):
        # Remove the application guard to demonstrate that the independent
        # ledger grader notices a false report on the absent fixture.
        with patch("experiments.evaluate_recovery.apply_dossier",
                   return_value=SimpleNamespace(action="closed_from_evidence")):
            report = evaluate(cases=2)
        self.assertEqual(report["summary"]["by_agent"]["heuristic"]["false_resolutions"], 1)

    def test_bounds_prevent_unbounded_runs(self):
        for cases, repeats in [(0, 1), (25, 1), (1, 0), (1, 6)]:
            with self.subTest(cases=cases, repeats=repeats), self.assertRaises(ValueError):
                evaluate(cases=cases, repeats=repeats)

    def test_cli_writes_report_and_requires_explicit_openai_configuration(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            out = Path(directory) / "nested" / "report.json"
            self.assertEqual(main(["--cases", "1", "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text())["live_model_requests"], 0)
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main(["--agent", "openai", "--cases", "1"])
        self.assertEqual(stopped.exception.code, 2)

    def test_provider_failure_is_an_unsuccessful_comparison(self):
        def fail(_request, _timeout):
            raise TimeoutError("secret-should-not-leak")

        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), patch(
            "second.live_agent.OpenAIRecoveryAgent.from_env",
            side_effect=lambda **kwargs: OpenAIRecoveryAgent(api_key="offline-placeholder", model="test-model", transport=fail),
        ):
            out = Path(directory) / "failed-report.json"
            self.assertEqual(main(["--agent", "openai", "--cases", "1", "--out", str(out)]), 2)
            report = json.loads(out.read_text())
        self.assertEqual(report["summary"]["by_agent"]["openai"]["abstained"], 1)
        self.assertEqual(report["summary"]["by_agent"]["openai"]["provider_errors"], {"transport_error": 1})
        self.assertNotIn("secret-should-not-leak", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
