"""Export inspectable, explicitly recorded operator cases for GitHub Pages."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from recovery_app.engine import SCENARIOS, Engine


def export_recording(destination: Path, *, source_commit="working-tree"):
    """Record real local simulator/validator calls; never invoke wallet or model."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    web = Path(__file__).parent / "web"
    for name in ("index.html", "app.js", "app.css"):
        shutil.copyfile(web / name, destination / name)
    (destination / "recorded.js").write_text("window.BELAY_RECORDED = true;\n", encoding="utf-8")
    index = destination / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace(
        '<script type="module" src="app.js"></script>',
        '<script src="recorded.js"></script>\n    <script type="module" src="app.js"></script>',
    ), encoding="utf-8")
    (destination / "fonts").mkdir(exist_ok=True)
    fonts = Path(__file__).resolve().parents[1] / "site/assets/fonts"
    shutil.copyfile(fonts.parent / "favicon.svg", destination / "favicon.svg")
    for name in ("manrope.woff2", "OFL.txt"):
        shutil.copyfile(fonts / name, destination / "fonts" / name)
    with tempfile.TemporaryDirectory(prefix="belay-recorded-operator-") as folder:
        engine = Engine(folder)
        try:
            incidents = []
            for scenario in SCENARIOS:
                incident = engine.create(scenario["id"])
                incident = engine.investigate(incident["id"], "heuristic")
                # Preserve a pending conflict/unknown beside completed examples.
                if scenario["id"] in {"lost_ack", "never_sent"}:
                    incident = engine.resolve(incident["id"], incident["proposal"]["id"])
                incidents.append(incident)
            config = engine.config()
            config.update(mode="recorded", agents=[{"id": "heuristic", "label": "Recorded deterministic baseline", "available": False}],
                          wallet={"enabled": False}, source_commit=source_commit)
            output = {"config": config, "incidents": incidents, "source_commit": source_commit,
                      "recorded_at": datetime.now(timezone.utc).isoformat(),
                      "execution": "Recorded local simulated provider operations; no model requests, wallet calls or OS-kill experiment."}
        finally:
            engine.close()
    (destination / "fixtures.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output
