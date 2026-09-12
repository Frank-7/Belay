"""The recorded UI must report what real sandbox executions actually did."""

from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from experiments.recovery_demo import generate_demo, main  # noqa: E402
from viewer.build_viewer import render_html, script_json  # noqa: E402


class RecoveryDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = generate_demo()
        cls.cases = {case["id"]: case for case in cls.demo["cases"]}

    def test_crashes_are_real_and_recording_is_labelled(self):
        self.assertEqual(self.demo["execution"], "recorded")
        self.assertIn("sandbox", self.demo["payments"])
        self.assertIn("Simulated", self.demo["agent"])
        self.assertEqual(len(self.cases), 3)
        self.assertTrue(all(case["crash_confirmed"] for case in self.cases.values()))

    def test_lost_ack_stays_paused_until_sufficient_evidence(self):
        case = self.cases["lost_ack"]
        none, stale, fresh = case["stages"]
        self.assertEqual(none["applied"]["action"], "none")
        self.assertEqual(stale["claim"]["verdict"], "absent")
        self.assertEqual(stale["dossier"]["verdict"], "abstain")
        self.assertEqual(stale["applied"]["action"], "none")
        self.assertEqual(fresh["applied"]["action"], "closed_from_evidence")
        self.assertEqual(fresh["workflow_after_resume"], "committed")
        for stage in case["stages"]:
            self.assertEqual(stage["ledger_before"], stage["ledger_after"])
            self.assertEqual(len(stage["ledger_after"]), 1)
            self.assertEqual(stage["ledger_after"][0]["amount_cents"], 5000)

    def test_absence_completion_is_once_and_resume_issues_nothing(self):
        stage = self.cases["complete_absent"]["stages"][0]
        self.assertEqual(stage["ledger_before"], [])
        self.assertEqual(stage["applied"]["action"], "completed")
        self.assertEqual(stage["dossier"]["proposal"]["amount_cents"], 5000)
        self.assertEqual(stage["ledger_after"], [{"amount_cents": 5000, "external_id": 1}])
        self.assertEqual(stage["workflow_after_resume"], "committed")
        kinds = [row["kind"] for row in stage["journal"]]
        self.assertLess(kinds.index("adjudication_intent"), kinds.index("adjudicated"))

    def test_permission_is_revoked_after_proposal_and_refuses_effect(self):
        stage = self.cases["revoked"]["stages"][0]
        self.assertTrue(stage["permission_revoked_after_proposal"])
        self.assertEqual(stage["dossier"]["verdict"], "absent")
        self.assertEqual(stage["applied"]["action"], "refused")
        self.assertEqual(stage["ledger_after"], [])
        self.assertIsNone(stage["workflow_after_resume"])
        self.assertIn("adjudication_refused", [row["kind"] for row in stage["journal"]])

    def test_model_prose_cannot_close_the_embedded_script(self):
        hostile = '</script><script>globalThis.injected=true</script><img src=x onerror=alert(1)>\u2028&'
        demo = copy.deepcopy(self.demo)
        demo["agent"] = hostile
        demo["cases"][0]["stages"][0]["dossier"]["reasoning"] = [hostile]
        encoded = script_json(demo)
        self.assertNotIn("<", encoded)
        self.assertEqual(json.loads(encoded), demo)
        html = render_html([], demo)
        self.assertEqual(html.count("</script>"), 1)
        self.assertNotIn(hostile, html)
        self.assertIn("Recorded execution", html)
        self.assertIn("Under the hood: crash forensics", html)

    def test_failed_recordings_are_saved_but_do_not_report_success(self):
        for kind, expected in (("violation", 1), ("model_error", 2)):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                demo = copy.deepcopy(self.demo)
                stage = demo["cases"][0]["stages"][0]
                if kind == "violation":
                    stage["grade"] = "false"
                else:
                    stage["model_metrics"] = {"errors": {"refusal": 1}}
                output = os.path.join(directory, "recording.json")
                with patch("experiments.recovery_demo.generate_demo", return_value=demo):
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(main(["--out", output]), expected)
                with open(output, encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh), demo)

    def test_model_option_cannot_silently_run_the_heuristic(self):
        with patch("experiments.recovery_demo.generate_demo") as generate:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["--model", "example-model"])
            self.assertEqual(error.exception.code, 2)
            generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
