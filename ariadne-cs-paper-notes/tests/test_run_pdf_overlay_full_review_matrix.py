#!/usr/bin/env python3
"""Regression tests for run_pdf_overlay_full_review_matrix.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_pdf_overlay_full_review_matrix.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_pdf_overlay_full_review_matrix", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_pdf_overlay_full_review_matrix")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_full_review_matrix_runs_three_pipelines_then_strict_matrix() -> None:
    module = load_module()

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        for name in ("hidden.tex", "neurips.tex", "acl.tex"):
            (root / name).write_text("x", encoding="utf-8")
        commands: list[list[str]] = []

        def fake_run_command(cmd, *, timeout):  # noqa: ARG001
            commands.append(cmd)
            if "run_review_pipeline.py" in cmd[1]:
                bundle = Path(cmd[cmd.index("--bundle") + 1])
                bundle.mkdir(parents=True, exist_ok=True)
                (bundle / "pipeline_status.json").write_text(json.dumps({"state": "complete"}) + "\n", encoding="utf-8")
                return Result(stdout="Pipeline state: complete")
            summary = Path(cmd[cmd.index("--summary-out") + 1])
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text(json.dumps({"passed": True, "bundles_passed": 3, "matrix_complete": True}) + "\n", encoding="utf-8")
            return Result(stdout=summary.read_text(encoding="utf-8"))

        original = module.run_command
        module.run_command = fake_run_command
        try:
            code = module.main(
                [
                    "--hidden-input",
                    str(root / "hidden.tex"),
                    "--neurips-input",
                    str(root / "neurips.tex"),
                    "--acl-input",
                    str(root / "acl.tex"),
                    "--out-root",
                    str(root / "out"),
                    "--prose-agent-cmd",
                    "agent command",
                    "--no-export-annotated-pdf",
                ]
            )
        finally:
            module.run_command = original
        payload = json.loads((root / "out" / "full_review_matrix_summary.json").read_text(encoding="utf-8"))

    if code != 0 or not payload["passed"]:
        raise AssertionError(f"Expected full matrix pass, got code={code}, payload={payload}")
    pipeline_commands = [cmd for cmd in commands if "run_review_pipeline.py" in cmd[1]]
    if len(pipeline_commands) != 3:
        raise AssertionError(f"Expected three pipeline commands, got {commands}")
    if not all("--paper-view" in cmd and "pdf-overlay" in cmd for cmd in pipeline_commands):
        raise AssertionError(f"Expected pdf-overlay pipeline commands, got {pipeline_commands}")
    if not any("run_pdf_overlay_migration_matrix.py" in cmd[1] for cmd in commands):
        raise AssertionError(f"Expected strict migration matrix command, got {commands}")


def test_full_review_matrix_preflight_checks_fixtures_and_nested_agent_command() -> None:
    module = load_module()

    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        for name in ("hidden.tex", "neurips.tex", "acl.tex"):
            (root / name).write_text("x", encoding="utf-8")
        helper = root / "helper.py"
        helper.write_text("print('ok')\n", encoding="utf-8")
        summary = root / "out" / "preflight.json"
        code = module.main(
            [
                "--hidden-input",
                str(root / "hidden.tex"),
                "--neurips-input",
                str(root / "neurips.tex"),
                "--acl-input",
                str(root / "acl.tex"),
                "--out-root",
                str(root / "out"),
                "--summary-out",
                str(summary),
                "--prose-agent-cmd",
                f"{sys.executable} scripts/run_agent_command.py --stdin-prompt --command '{sys.executable} {helper}'",
                "--skip-pdf-build",
                "--preflight",
            ]
        )
        payload = json.loads(summary.read_text(encoding="utf-8"))

    if code != 0 or not payload["passed"]:
        raise AssertionError(f"Expected passing preflight, code={code}, payload={payload}")
    if payload["mode"] != "preflight" or len(payload["jobs"]) != 3:
        raise AssertionError(f"Expected three preflight jobs, got {payload}")
    nested = payload["prose_agent_cmd"].get("nested_command")
    if not nested or not nested.get("ok"):
        raise AssertionError(f"Expected nested --command executable check, got {payload['prose_agent_cmd']}")
    if "pdftotext" not in payload["tools"] or "pdftoppm" not in payload["tools"]:
        raise AssertionError(f"Expected PDF tool checks, got {payload['tools']}")


def test_full_review_matrix_preflight_fails_missing_input() -> None:
    module = load_module()

    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        existing = root / "paper.tex"
        existing.write_text("x", encoding="utf-8")
        code = module.main(
            [
                "--hidden-input",
                str(existing),
                "--neurips-input",
                str(root / "missing.tex"),
                "--acl-input",
                str(existing),
                "--out-root",
                str(root / "out"),
                "--prose-agent-cmd",
                sys.executable,
                "--skip-pdf-build",
                "--preflight",
            ]
        )
        payload = json.loads((root / "out" / "full_review_matrix_summary.json").read_text(encoding="utf-8"))

    if code == 0 or payload["passed"]:
        raise AssertionError(f"Expected failing preflight for missing input, got {payload}")
    if not any("neurips input does not exist" in error for error in payload["errors"]):
        raise AssertionError(f"Expected missing input error, got {payload['errors']}")


def test_full_review_matrix_skips_existing_complete_bundle_by_default() -> None:
    module = load_module()

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        for name in ("hidden.tex", "neurips.tex", "acl.tex"):
            (root / name).write_text("x", encoding="utf-8")
        hidden_bundle = root / "out" / "hidden"
        hidden_bundle.mkdir(parents=True)
        (hidden_bundle / "pipeline_status.json").write_text(json.dumps({"state": "complete", "next_action": ""}) + "\n", encoding="utf-8")
        commands: list[list[str]] = []

        def fake_run_command(cmd, *, timeout):  # noqa: ARG001
            commands.append(cmd)
            if "run_review_pipeline.py" in cmd[1]:
                bundle = Path(cmd[cmd.index("--bundle") + 1])
                bundle.mkdir(parents=True, exist_ok=True)
                (bundle / "pipeline_status.json").write_text(json.dumps({"state": "complete"}) + "\n", encoding="utf-8")
                return Result(stdout="Pipeline state: complete")
            summary = Path(cmd[cmd.index("--summary-out") + 1])
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text(json.dumps({"passed": True, "bundles_passed": 3, "matrix_complete": True}) + "\n", encoding="utf-8")
            return Result(stdout=summary.read_text(encoding="utf-8"))

        original = module.run_command
        module.run_command = fake_run_command
        try:
            code = module.main(
                [
                    "--hidden-input",
                    str(root / "hidden.tex"),
                    "--neurips-input",
                    str(root / "neurips.tex"),
                    "--acl-input",
                    str(root / "acl.tex"),
                    "--out-root",
                    str(root / "out"),
                    "--prose-agent-cmd",
                    "agent command",
                    "--no-export-annotated-pdf",
                ]
            )
        finally:
            module.run_command = original
        payload = json.loads((root / "out" / "full_review_matrix_summary.json").read_text(encoding="utf-8"))

    if code != 0 or not payload["passed"]:
        raise AssertionError(f"Expected pass with skipped bundle, got {payload}")
    pipeline_commands = [cmd for cmd in commands if "run_review_pipeline.py" in cmd[1]]
    if len(pipeline_commands) != 2:
        raise AssertionError(f"Expected only two pipeline runs because hidden was complete, got {commands}")
    hidden_row = next(row for row in payload["jobs"] if row["label"] == "hidden")
    if not hidden_row.get("skipped_existing_complete"):
        raise AssertionError(f"Expected hidden row to be marked skipped_existing_complete, got {hidden_row}")


def test_full_review_matrix_requires_agent_only_for_incomplete_bundles() -> None:
    module = load_module()

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        for name in ("hidden.tex", "neurips.tex", "acl.tex"):
            (root / name).write_text("x", encoding="utf-8")
        for label in ("hidden", "neurips", "acl"):
            bundle = root / "out" / label
            bundle.mkdir(parents=True)
            (bundle / "pipeline_status.json").write_text(json.dumps({"state": "complete", "next_action": ""}) + "\n", encoding="utf-8")
        commands: list[list[str]] = []

        def fake_run_command(cmd, *, timeout):  # noqa: ARG001
            commands.append(cmd)
            summary = Path(cmd[cmd.index("--summary-out") + 1])
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text(json.dumps({"passed": True, "bundles_passed": 3, "matrix_complete": True}) + "\n", encoding="utf-8")
            return Result(stdout=summary.read_text(encoding="utf-8"))

        original = module.run_command
        module.run_command = fake_run_command
        try:
            code = module.main(
                [
                    "--hidden-input",
                    str(root / "hidden.tex"),
                    "--neurips-input",
                    str(root / "neurips.tex"),
                    "--acl-input",
                    str(root / "acl.tex"),
                    "--out-root",
                    str(root / "out"),
                    "--no-export-annotated-pdf",
                ]
            )
        finally:
            module.run_command = original
        payload = json.loads((root / "out" / "full_review_matrix_summary.json").read_text(encoding="utf-8"))

    if code != 0 or not payload["passed"]:
        raise AssertionError(f"Expected completed bundles to validate without prose-agent-cmd, got {payload}")
    if not all(row.get("skipped_existing_complete") for row in payload["jobs"]):
        raise AssertionError(f"Expected all complete bundles to be skipped, got {payload['jobs']}")
    if any("run_review_pipeline.py" in cmd[1] for cmd in commands):
        raise AssertionError(f"Expected no pipeline reruns for complete bundles, got {commands}")


def test_full_review_matrix_errors_without_agent_for_incomplete_bundle() -> None:
    module = load_module()

    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        for name in ("hidden.tex", "neurips.tex", "acl.tex"):
            (root / name).write_text("x", encoding="utf-8")
        code = module.main(
            [
                "--hidden-input",
                str(root / "hidden.tex"),
                "--neurips-input",
                str(root / "neurips.tex"),
                "--acl-input",
                str(root / "acl.tex"),
                "--out-root",
                str(root / "out"),
                "--no-export-annotated-pdf",
            ]
        )
        payload = json.loads((root / "out" / "full_review_matrix_summary.json").read_text(encoding="utf-8"))

    if code == 0 or payload["passed"]:
        raise AssertionError(f"Expected failure without prose-agent-cmd for incomplete bundles, got {payload}")
    if not all("--prose-agent-cmd is required" in row.get("error", "") for row in payload["jobs"]):
        raise AssertionError(f"Expected explicit missing-agent errors, got {payload['jobs']}")


if __name__ == "__main__":
    test_full_review_matrix_runs_three_pipelines_then_strict_matrix()
    test_full_review_matrix_preflight_checks_fixtures_and_nested_agent_command()
    test_full_review_matrix_preflight_fails_missing_input()
    test_full_review_matrix_skips_existing_complete_bundle_by_default()
    test_full_review_matrix_requires_agent_only_for_incomplete_bundles()
    test_full_review_matrix_errors_without_agent_for_incomplete_bundle()
    print("run_pdf_overlay_full_review_matrix regression tests passed")
