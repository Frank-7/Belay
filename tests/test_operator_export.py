"""The public operator walkthrough cannot silently become a live executor."""

import json
import os
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

    def test_unresolved_build_root_preserves_link_containment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "published"
            (output / "detour").mkdir(parents=True)
            (output / "app.js").write_text("// public asset", encoding="utf-8")
            index = output / "index.html"
            index.write_text('<script src="app.js"></script>', encoding="utf-8")
            check_local_links(output / "detour" / "..")
            (root / "private.js").write_text("// outside the output", encoding="utf-8")
            index.write_text('<script src="../private.js"></script>', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes the build output"):
                check_local_links(output / "detour" / "..")

    def test_aliased_build_root_does_not_reject_its_own_assets(self):
        with tempfile.TemporaryDirectory(prefix="belay-export-path-") as directory:
            root = Path(directory).resolve()
            output = root / "published-operator-recording"
            output.mkdir()
            (output / "app.js").write_text("// public asset", encoding="utf-8")
            (output / "index.html").write_text('<script src="app.js"></script>', encoding="utf-8")
            if os.name == "nt":
                import ctypes

                buffer = ctypes.create_unicode_buffer(32768)
                size = ctypes.windll.kernel32.GetShortPathNameW(str(output), buffer, len(buffer))
                if not size or Path(buffer.value) == output:
                    self.skipTest("8.3 short path aliases are unavailable on this volume")
                alias = Path(buffer.value)
            else:
                alias = root / "published-alias"
                alias.symlink_to(output, target_is_directory=True)
            self.assertNotEqual(alias, alias.resolve())
            check_local_links(alias)


if __name__ == "__main__":
    unittest.main(verbosity=2)
