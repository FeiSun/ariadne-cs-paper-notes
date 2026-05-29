#!/usr/bin/env python3
"""Regression tests for generic external agent command adapter."""

from __future__ import annotations

import importlib.util
import json
import os
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


def test_agent_command_can_read_packet_from_env_and_pipe_prompt() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        packet = root / "phase_a_prompt_packet.json"
        out = root / "seen.json"
        packet.write_text(json.dumps({"phase": "phase_a", "write_targets": {}}), encoding="utf-8")
        consumer = root / "consumer.py"
        consumer.write_text(
            "\n".join(
                [
                    "import json, os, pathlib, sys",
                    "pathlib.Path(sys.argv[1]).write_text(json.dumps({",
                    "    'packet': os.environ.get('ARIADNE_PACKET'),",
                    "    'prompt_file': os.environ.get('ARIADNE_PROMPT_FILE'),",
                    "    'stdin_has_packet_heading': '# Ariadne Agent Packet: phase_a' in sys.stdin.read(),",
                    "}) + '\\n')",
                ]
            ),
            encoding="utf-8",
        )
        old_packet_env = os.environ.get("ARIADNE_PROMPT_PACKET")
        os.environ["ARIADNE_PROMPT_PACKET"] = str(packet)
        try:
            status = module.main(
                [
                    "--command",
                    f"{sys.executable} {consumer} {out}",
                    "--stdin-prompt",
                ]
            )
        finally:
            if old_packet_env is not None:
                os.environ["ARIADNE_PROMPT_PACKET"] = old_packet_env
            else:
                os.environ.pop("ARIADNE_PROMPT_PACKET", None)
        payload = json.loads(out.read_text(encoding="utf-8"))
        prompt_exists = Path(payload["prompt_file"]).exists()

    if status != 0:
        raise AssertionError(f"Expected env packet command success, got {status}")
    if payload["packet"] != str(packet.resolve()) or not payload["stdin_has_packet_heading"]:
        raise AssertionError(f"Expected packet env and stdin prompt, got {payload}")
    if not prompt_exists:
        raise AssertionError(f"Expected prompt file to exist, got {payload}")


def test_agent_command_passes_extra_env_to_nested_command() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        packet = root / "packet.json"
        out = root / "env.json"
        agent_home = root / "agent-home"
        packet.write_text(json.dumps({"phase": "phase_a", "write_targets": {}}), encoding="utf-8")
        consumer = root / "consumer.py"
        consumer.write_text(
            "\n".join(
                [
                    "import json, os, pathlib, sys",
                    "pathlib.Path(sys.argv[1]).write_text(json.dumps({",
                    "    'CODEX_HOME': os.environ.get('CODEX_HOME'),",
                    "    'ARIADNE_PACKET': os.environ.get('ARIADNE_PACKET'),",
                    "}) + '\\n')",
                ]
            ),
            encoding="utf-8",
        )
        status = module.main(
            [
                "--packet",
                str(packet),
                "--command",
                f"{sys.executable} {consumer} {out}",
                "--env",
                f"CODEX_HOME={agent_home}",
            ]
        )
        payload = json.loads(out.read_text(encoding="utf-8"))
        summary = json.loads(packet.with_suffix(packet.suffix + ".agent_command_summary.json").read_text(encoding="utf-8"))

    if status != 0:
        raise AssertionError(f"Expected command success with extra env, got {status}")
    if payload["CODEX_HOME"] != str(agent_home):
        raise AssertionError(f"Expected CODEX_HOME in nested command, got {payload}")
    if "CODEX_HOME" not in summary.get("extra_env_keys", []):
        raise AssertionError(f"Expected summary to record extra env key, got {summary}")


if __name__ == "__main__":
    test_agent_command_dry_run_writes_prompt()
    test_agent_command_parses_stdout_json()
    test_agent_command_can_read_packet_from_env_and_pipe_prompt()
    test_agent_command_passes_extra_env_to_nested_command()
    print("run_agent_command regression tests passed")
