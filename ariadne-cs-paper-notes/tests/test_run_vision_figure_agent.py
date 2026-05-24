#!/usr/bin/env python3
"""Regression tests for optional vision figure/caption specialist hook."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_vision_figure_agent.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_vision_figure_agent", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_vision_figure_agent")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vision_figure_agent_dry_run_writes_manifest_when_tools_available() -> None:
    module = load_module()
    if not shutil.which("pdftoppm"):
        return
    try:
        from PIL import Image
    except Exception:
        return
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        pdf = root / "paper.pdf"
        Image.new("RGB", (400, 300), "white").save(pdf)
        out = root / "figure_caption_vision_issues.json"
        status = module.main(
            [
                "--pdf",
                str(pdf),
                "--out",
                str(out),
                "--agent-cmd",
                "not-real",
                "--pages",
                "1",
                "--dry-run",
            ]
        )
        manifest = json.loads((root / "vision_image_manifest.json").read_text(encoding="utf-8"))
        packet = json.loads(out.with_suffix(".vision_packet.json").read_text(encoding="utf-8"))
        summary = json.loads((root / "vision_figure_agent_summary.json").read_text(encoding="utf-8"))
    if status != 0:
        raise AssertionError(f"Vision dry-run should pass, got {status}")
    if manifest["context_policy"] != "model_readable_image_manifest_only" or len(manifest["images"]) != 1:
        raise AssertionError(f"Unexpected image manifest: {manifest}")
    if packet["context_policy"] != "model_readable_vision_specialist_packet":
        raise AssertionError(f"Unexpected vision packet: {packet}")
    if summary["status"] != "dry_run":
        raise AssertionError(f"Unexpected vision summary: {summary}")


if __name__ == "__main__":
    test_vision_figure_agent_dry_run_writes_manifest_when_tools_available()
    print("run_vision_figure_agent regression tests passed")
