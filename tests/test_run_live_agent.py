"""Offline checks for the decision-divergence experiment and its checkpoints.

These exercise experiments/run_live_agent.py, not the recovery adjudicator's
model adapter. All responses are synthetic, output uses temporary files, and
real HTTP connections are blocked even if a response fixture is missed.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments import run_live_agent as runner  # noqa: E402

KEY = "offline-decision-experiment-key-93"
ENDPOINT = "https://model.invalid/v1/chat/completions"


def model_response(decision="full_refund"):
    return {
        "status": "model_response", "decision": decision, "http_status": 200,
        "raw_response": "synthetic response", "raw_text": decision, "error": None,
        "returned_model": "returned-model", "usage": {"prompt_tokens": 2},
    }


def api_error(status=503):
    return {
        "status": "api_error", "http_status": status,
        "raw_response": "synthetic failure", "error": f"HTTP {status}",
    }


class LiveDecisionRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="belay-decision-test-")
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name) / "results.json"
        self.calls = []
        self.delays = []
        for target in ("urllib.request.OpenerDirector.open", "socket.create_connection"):
            blocker = patch(target, side_effect=AssertionError("Real network calls are forbidden"))
            blocker.start()
            self.addCleanup(blocker.stop)

    def run_main(self, outcomes, *options, sleep=None):
        responses = iter(outcomes)

        def invoke(endpoint, key, payload, timeout, output_mode="json"):
            self.calls.append({
                "endpoint": endpoint, "key": key, "payload": payload,
                "timeout": timeout, "output_mode": output_mode,
            })
            return copy.deepcopy(next(responses))

        argv = [
            str(ROOT / "experiments" / "run_live_agent.py"),
            "--model", "requested-model", "--base-url", "https://model.invalid/v1",
            "--reps", "2", "--out", str(self.out),
            "--api-key-env", "BELAY_TEST_LIVE_KEY", *options,
        ]
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", argv),
            patch.dict(os.environ, {"BELAY_TEST_LIVE_KEY": KEY}),
            patch.object(runner, "invoke", side_effect=invoke),
            patch.object(runner.time, "sleep", side_effect=sleep or self.delays.append),
            contextlib.redirect_stdout(self.stdout),
            contextlib.redirect_stderr(self.stderr),
        ):
            returncode = runner.main()
        return returncode, json.loads(self.out.read_text(encoding="utf-8"))

    def test_fenced_json_preserves_strict_schema(self):
        accepted = {
            '```json\n{"decision":"full_refund"}\n```': "full_refund",
            '```JSON\r\n"split_refund_plus_credit"\r\n```': "split_refund_plus_credit",
            '```\n{"decision":"full_refund"}\n```': "full_refund",
        }
        for raw, expected in accepted.items():
            with self.subTest(raw=raw):
                self.assertEqual(runner.parse_decision(raw), expected)
        rejected = [
            '```json\n{"decision":"full_refund","extra":1}\n```',
            '```json\n{"decision":"full_refund","decision":"full_refund"}\n```',
            'prefix\n```json\n{"decision":"full_refund"}\n```',
            '```json\n{"decision":"full_refund"}\n```\nextra',
            '```python\n{"decision":"full_refund"}\n```',
        ]
        for raw in rejected:
            with self.subTest(raw=raw):
                self.assertEqual(runner.parse_decision(raw), "unparseable")

    def test_retry_preserves_request_identity_and_response_denominator(self):
        rc, data = self.run_main([api_error(), api_error(), model_response(), model_response()])
        self.assertEqual(rc, 0)
        self.assertEqual(self.delays, [15, 30])
        self.assertEqual([case["retry_index"] for case in data["cases"]], [0, 1, 2, 0])
        self.assertEqual([case["rep"] for case in data["cases"]], [1, 1, 1, 2])
        self.assertEqual(len({call["payload"] for call in self.calls}), 1)
        request_hash = runner.digest(self.calls[0]["payload"])
        self.assertEqual({case["request_sha256"] for case in data["cases"]}, {request_hash})
        self.assertEqual(data["summary"]["responses"], 2)
        self.assertEqual(data["summary"]["by_condition"][0]["api_errors"], 2)

    def test_retry_exhaustion_records_every_attempt_and_caps_delay(self):
        rc, data = self.run_main([api_error()] * 5, "--retries-503", "4")
        self.assertEqual(rc, 1)
        self.assertEqual(self.delays, [15, 30, 60, 60])
        self.assertEqual(len(data["cases"]), 5)
        self.assertEqual(data["metadata"]["status"], "stopped_api_error")
        self.assertEqual(data["summary"]["responses"], 0)

    def test_other_errors_stop_immediately(self):
        rc, data = self.run_main([api_error(429)])
        self.assertEqual((rc, len(self.calls), self.delays), (1, 1, []))
        self.assertEqual(data["cases"][0]["http_status"], 429)

    def test_call_budget_counts_retries_and_resume_only_fills_missing_response(self):
        rc, data = self.run_main([api_error(), model_response()], "--max-calls", "2")
        self.assertEqual(rc, 3)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(data["metadata"]["status"], "paused_call_budget")
        rc, resumed = self.run_main(
            [model_response("split_refund_plus_credit")], "--max-calls", "1", "--resume",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(resumed["cases"]), 3)
        self.assertEqual(resumed["cases"][:2], data["cases"])
        self.assertEqual(resumed["summary"]["responses"], 2)

    def test_last_budgeted_error_does_not_sleep_or_retry(self):
        rc, data = self.run_main([api_error()], "--max-calls", "1")
        self.assertEqual((rc, len(self.calls), self.delays), (1, 1, []))
        self.assertEqual(len(data["cases"]), 1)

    def test_checkpoint_precedes_backoff_and_interrupt_preserves_attempt(self):
        def interrupt(delay):
            checkpoint = json.loads(self.out.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["metadata"]["status"], "retrying_503")
            self.assertEqual(len(checkpoint["cases"]), 1)
            self.assertEqual(checkpoint["cases"][0]["retry_scheduled_seconds"], delay)
            raise KeyboardInterrupt

        rc, data = self.run_main([api_error()], sleep=interrupt)
        self.assertEqual(rc, 130)
        self.assertEqual(data["metadata"]["status"], "interrupted")
        self.assertEqual(len(data["cases"]), 1)

    def test_provider_echoed_key_is_redacted_before_retry_checkpoint(self):
        echoed = api_error()
        echoed.update(raw_response=KEY, error=f"HTTP 503 {KEY}", request_id=KEY)

        def inspect_checkpoint(_delay):
            self.assertNotIn(KEY, self.out.read_text(encoding="utf-8"))

        rc, data = self.run_main(
            [echoed, model_response(), model_response()], sleep=inspect_checkpoint,
        )
        self.assertEqual(rc, 0)
        self.assertNotIn(KEY, self.out.read_text(encoding="utf-8"))
        self.assertNotIn(KEY, self.stdout.getvalue() + self.stderr.getvalue())
        self.assertTrue(data["cases"][0]["credential_redacted"])

    def test_invoke_retains_raw_model_metadata_and_parses_fence(self):
        envelope = {
            "model": "actual-returned-model", "id": "response-1", "system_fingerprint": "fp-1",
            "usage": {"prompt_tokens": 5, "completion_tokens": 8},
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": '```json\n{"decision":"full_refund"}\n```',
            }}],
        }
        response = io.BytesIO(json.dumps(envelope).encode())
        response.status = 200
        response.headers = {"x-request-id": "request-1"}
        opener = SimpleNamespace(open=Mock(return_value=response))
        payload = runner.encode({"model": "requested-model"})
        with patch("urllib.request.build_opener", return_value=opener):
            record = runner.invoke(ENDPOINT, KEY, payload, 1)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.data, payload)
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(record["status"], "model_response")
        self.assertEqual(record["decision"], "full_refund")
        self.assertEqual(record["returned_model"], "actual-returned-model")
        self.assertEqual(record["request_id"], "request-1")
        self.assertEqual(record["system_fingerprint"], "fp-1")
        self.assertEqual(json.loads(record["raw_response"]), envelope)

    def test_new_run_preserves_prior_raw_cases_and_flattens_archive(self):
        rc, first = self.run_main([model_response(), model_response()])
        self.assertEqual(rc, 0)
        rc, second = self.run_main(
            [model_response("split_refund_plus_credit")] * 2,
            "--new-run", "--model", "second-model",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(second["previous_runs"], [first])
        rc, third = self.run_main(
            [model_response()] * 2, "--new-run", "--model", "third-model",
        )
        self.assertEqual(rc, 0)
        second.pop("previous_runs")
        self.assertEqual(third["previous_runs"], [first, second])
        self.assertEqual(third["summary"]["responses"], 2)
        self.assertEqual(len(self.calls), 6)

    def test_resume_refuses_different_parser_without_rewriting_archived_parse(self):
        rc, prior = self.run_main([model_response("unparseable"), model_response()])
        self.assertEqual(rc, 0)
        # An earlier strict-parser run retained this fenced answer as invalid.
        prior["metadata"]["configuration"]["parser"] = "strict-label-or-single-key-json-v1"
        prior["cases"][0]["raw_text"] = '```json\n{"decision":"full_refund"}\n```'
        self.out.write_text(json.dumps(prior), encoding="utf-8")
        retained_bytes = self.out.read_bytes()
        with self.assertRaises(SystemExit) as stopped:
            self.run_main([], "--resume")
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn("resume configuration differs", self.stderr.getvalue())
        self.assertEqual(self.out.read_bytes(), retained_bytes)
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
