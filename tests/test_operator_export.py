"""The public operator walkthrough cannot silently become a live executor."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recovery_app.engine import Engine  # noqa: E402
from recovery_app.export import export_recording  # noqa: E402
from scripts.build_site import check_local_links  # noqa: E402


class OperatorExportTests(unittest.TestCase):
    def test_recording_uses_offline_pipeline_and_disables_live_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.object(Engine, "_arc_provider", side_effect=AssertionError("no chain calls during export")):
                result = export_recording(path, source_commit="a" * 40)
            self.assertEqual(result["config"]["mode"], "recorded")
            self.assertFalse(result["config"]["wallet"]["enabled"])
            self.assertEqual(len(result["incidents"]), 6)
            self.assertEqual(json.loads((path / "fixtures.json").read_text())["source_commit"], "a" * 40)
            cases = {incident["scenario"]: incident for incident in result["incidents"]}
            self.assertEqual(cases["conflicting_sources"]["proposal"]["verdict"], "abstain")
            self.assertEqual(cases["lost_ack"]["status"], "resolved")
            self.assertTrue(all(incident["proposal"]["metrics"]["requests"] == 0 for incident in result["incidents"]))
            self.assertIn('src="recorded.js"', (path / "index.html").read_text(encoding="utf-8"))
            self.assertFalse((path / "wallet.js").exists())
            check_local_links(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
