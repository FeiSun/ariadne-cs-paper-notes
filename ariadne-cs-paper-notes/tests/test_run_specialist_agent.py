#!/usr/bin/env python3
"""Regression tests for optional LLM specialist refinement runner."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_specialist_agent.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_specialist_agent", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_specialist_agent")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def issue_artifact(domain: str) -> dict[str, object]:
    return {
        "artifact_type": "ariadne_issue_artifact",
        "schema_version": 1,
        "domain": domain,
        "context_policy": "model_readable_issue_only",
        "status": "skipped",
        "source_artifacts": [],
        "coverage": {"checked": 0, "issues": 0, "skipped": 1},
        "issues": [],
        "skip_reason": "test stub",
    }


def test_specialist_agent_dry_run_copies_artifact_and_writes_packet() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        issues = root / "issue_artifacts"
        out = root / "issue_artifacts_llm"
        write_json(issues / "layout_issues.json", issue_artifact("layout"))
        status = module.main(
            [
                "--issues-dir",
                str(issues),
                "--out-dir",
                str(out),
                "--agent-cmd",
                "not-a-real-specialist",
                "--dry-run",
                "--audit",
            ]
        )
        copied = json.loads((out / "layout_issues.json").read_text(encoding="utf-8"))
        packet = json.loads((out / "layout_issues.packet.json").read_text(encoding="utf-8"))
        summary = json.loads((out / "specialist_agent_summary.json").read_text(encoding="utf-8"))

    if status != 0:
        raise AssertionError(f"Dry-run specialist runner should pass, got {status}")
    if copied["domain"] != "layout":
        raise AssertionError(f"Copied artifact changed unexpectedly: {copied}")
    if packet["context_policy"] != "model_readable_specialist_packet":
        raise AssertionError(f"Missing packet context policy: {packet}")
    if "rule_refs" in packet:
        raise AssertionError(f"Specialist packets should not load maintenance-only rules by default: {packet}")
    if summary["audit"]["status"] != "passed":
        raise AssertionError(f"Expected dry-run output audit to pass, got {summary}")


def test_specialist_agent_command_writes_output() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        issues = root / "issue_artifacts"
        out = root / "issue_artifacts_llm"
        write_json(issues / "polish_issues.json", issue_artifact("polish"))
        agent = root / "fake_specialist.py"
        agent.write_text(
            "\n".join(
                [
                    "import json, os",
                    "payload=json.load(open(os.environ['ARIADNE_SPECIALIST_INPUT']))",
                    "payload['status']='skipped'",
                    "json.dump(payload, open(os.environ['ARIADNE_SPECIALIST_OUTPUT'], 'w'))",
                ]
            ),
            encoding="utf-8",
        )
        status = module.main(
            [
                "--issues-dir",
                str(issues),
                "--out-dir",
                str(out),
                "--domains",
                "polish",
                "--agent-cmd",
                f"{sys.executable} {agent}",
            ]
        )
        summary = json.loads((out / "specialist_agent_summary.json").read_text(encoding="utf-8"))

    if status != 0:
        raise AssertionError(f"Specialist command should pass, got {status}")
    if summary["results"][0]["status"] != "completed":
        raise AssertionError(f"Expected completed specialist result, got {summary}")


if __name__ == "__main__":
    test_specialist_agent_dry_run_copies_artifact_and_writes_packet()
    test_specialist_agent_command_writes_output()
    print("run_specialist_agent regression tests passed")
