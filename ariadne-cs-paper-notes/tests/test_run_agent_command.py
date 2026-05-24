#!/usr/bin/env python3
"""Regression tests for generic external agent command adapter."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_agent_command.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_agent_command", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_agent_command")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_agent_command_dry_run_writes_prompt() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        packet = root / "packet.json"
        packet.write_text(json.dumps({"phase": "phase_a", "write_targets": {}}), encoding="utf-8")
        status = module.main(["--packet", str(packet), "--command", "not-real", "--dry-run"])
        prompt = packet.with_suffix(packet.suffix + ".prompt.md")
        summary = json.loads(packet.with_suffix(packet.suffix + ".agent_command_summary.json").read_text(encoding="utf-8"))
        if status != 0 or not prompt.exists():
            raise AssertionError(f"Dry-run should write prompt, status={status}, prompt={prompt.exists()}")
        if summary["context_policy"] != "model_readable_agent_command_status_only":
            raise AssertionError(f"Unexpected summary policy: {summary}")


def test_agent_command_parses_stdout_json() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        packet = root / "packet.json"
        out = root / "stdout.json"
        packet.write_text(json.dumps({"phase": "phase_b"}), encoding="utf-8")
        producer = root / "producer.py"
        producer.write_text("import json; print(json.dumps({'ok': True}))\n", encoding="utf-8")
        status = module.main(
            [
                "--packet",
                str(packet),
                "--command",
                f"{sys.executable} {producer}",
                "--stdout-json-out",
                str(out),
            ]
        )
        payload = json.loads(out.read_text(encoding="utf-8"))
    if status != 0 or payload != {"ok": True}:
        raise AssertionError(f"Expected parsed stdout JSON, status={status}, payload={payload}")


if __name__ == "__main__":
    test_agent_command_dry_run_writes_prompt()
    test_agent_command_parses_stdout_json()
    print("run_agent_command regression tests passed")
