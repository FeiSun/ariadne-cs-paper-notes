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
        summary = json.loads(packet.with_suffix(packet.suffix + ".agent_command_summary.json").read_text(encoding="utf-8"))
        prompt = Path(summary["prompt_file"])
        if status != 0 or not prompt.exists():
            raise AssertionError(f"Dry-run should write prompt, status={status}, prompt={prompt.exists()}")
        prompt_text = prompt.read_text(encoding="utf-8")
    if "可见批注语言合同" not in prompt_text or "读者卡点 -> 单一违反原则 -> 自改问题" not in prompt_text:
        raise AssertionError(f"Prompt missing Chinese critique contract: {prompt_text}")
    if summary["context_policy"] != "model_readable_agent_command_status_only":
        raise AssertionError(f"Unexpected summary policy: {summary}")


def test_agent_command_resolves_rule_refs_into_prompt() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        rule = root / "rule.md"
        packet = root / "packet.json"
        rule.write_text("# Test Rule\n\nUnique rule body.\n", encoding="utf-8")
        packet.write_text(
            json.dumps(
                {
                    "phase": "phase_a",
                    "rule_refs": [
                        {
                            "id": "test_rule",
                            "path": str(rule),
                            "hash": module.sha256_path(rule),
                            "purpose": "test rule resolution",
                        }
                    ],
                    "write_targets": {},
                }
            ),
            encoding="utf-8",
        )
        status = module.main(["--packet", str(packet), "--command", "not-real", "--dry-run"])
        summary = json.loads(packet.with_suffix(packet.suffix + ".agent_command_summary.json").read_text(encoding="utf-8"))
        prompt = Path(summary["prompt_file"]).read_text(encoding="utf-8")
        if status != 0:
            raise AssertionError(f"Dry-run with rule_refs should pass, got {status}")
        if "## Resolved Rule References" not in prompt or "Unique rule body." not in prompt:
            raise AssertionError(f"Resolved rule content missing from prompt: {prompt}")
        if "可见给学生的批注意见默认必须用中文书写" not in prompt:
            raise AssertionError(f"Resolved prompt should include Chinese output contract: {prompt}")


def test_agent_command_fails_on_missing_rule_ref() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        try:
            module.resolve_rule_refs({"phase": "phase_a", "rule_refs": [{"id": "missing", "path": str(root / "missing.md")}]})
        except FileNotFoundError:
            missing_failed = True
        else:
            missing_failed = False
    if not missing_failed:
        raise AssertionError("Missing rule ref should fail before prompt generation")


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
    test_agent_command_resolves_rule_refs_into_prompt()
    test_agent_command_fails_on_missing_rule_ref()
    test_agent_command_parses_stdout_json()
    print("run_agent_command regression tests passed")
