#!/usr/bin/env python3
"""Run fresh PDF-overlay full reviews for the three migration fixture styles."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ReviewJob:
    label: str
    input_path: Path
    bundle: Path


def run_command(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=timeout)


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compact_tail(value: str, *, max_chars: int = 2000) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def command_parts(command: str) -> list[str]:
    return shlex.split(command)


def executable_status(command: str) -> dict[str, Any]:
    try:
        parts = command_parts(command)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "parts": []}
    if not parts:
        return {"ok": False, "error": "command is empty", "parts": []}
    executable = parts[0]
    path: str | None = None
    if "/" in executable:
        candidate = Path(executable).expanduser()
        path = str(candidate)
        ok = candidate.exists()
    else:
        resolved = shutil.which(executable)
        path = resolved
        ok = bool(resolved)
    status: dict[str, Any] = {"ok": ok, "executable": executable, "resolved": path, "parts": parts}
    if not ok:
        status["error"] = f"executable not found: {executable}"
    if "--command" in parts:
        index = parts.index("--command")
        if index + 1 < len(parts):
            nested = executable_status(parts[index + 1])
            status["nested_command"] = nested
            if ok and not nested.get("ok"):
                status["ok"] = False
                status["error"] = f"nested --command is not executable: {nested.get('error')}"
        elif ok:
            status["ok"] = False
            status["error"] = "--command is missing its nested command value"
    return status


def pipeline_command(job: ReviewJob, args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_review_pipeline.py"),
        str(job.input_path),
        "--bundle",
        str(job.bundle),
        "--paper-view",
        "pdf-overlay",
        "--review-units-source",
        "tex",
        "--domains",
        args.domains,
        "--pages",
        args.pages,
        "--pdf-timeout",
        str(args.pdf_timeout),
        "--bbox-timeout",
        str(args.bbox_timeout),
        "--render-timeout",
        str(args.render_timeout),
        "--specialist-timeout",
        str(args.specialist_timeout),
        "--prose-agent-timeout",
        str(args.prose_agent_timeout),
        "--prose-max-iterations",
        str(args.prose_max_iterations),
    ]
    if args.prose_agent_cmd:
        cmd.extend(["--prose-agent-cmd", args.prose_agent_cmd])
    if args.force_specialists:
        cmd.append("--force-specialists")
    for target in args.force_rebuild or []:
        cmd.extend(["--force-rebuild", target])
    if args.skip_pdf_build:
        cmd.append("--skip-pdf-build")
    if args.no_export_annotated_pdf:
        cmd.append("--no-export-annotated-pdf")
    if args.specialist_agent_cmd:
        cmd.extend(["--specialist-agent-cmd", args.specialist_agent_cmd])
    if args.use_specialist_agent_output:
        cmd.append("--use-specialist-agent-output")
    if args.vision_figure_agent_cmd:
        cmd.extend(["--vision-figure-agent-cmd", args.vision_figure_agent_cmd])
    return cmd


def preflight(jobs: list[ReviewJob], args: argparse.Namespace, summary_out: Path) -> dict[str, Any]:
    tool_status = {tool: bool(shutil.which(tool)) for tool in ("pdftotext", "pdftoppm")}
    if not args.skip_pdf_build:
        tool_status["latexmk_or_pdflatex"] = bool(shutil.which("latexmk") or shutil.which("pdflatex"))
    rows: list[dict[str, Any]] = []
    for job in jobs:
        rows.append(
            {
                "label": job.label,
                "input": str(job.input_path),
                "input_exists": job.input_path.exists(),
                "bundle": str(job.bundle),
                "pipeline_command": pipeline_command(job, args),
            }
        )
    agent = executable_status(args.prose_agent_cmd) if args.prose_agent_cmd else {"ok": True, "skipped": True}
    specialist = executable_status(args.specialist_agent_cmd) if args.specialist_agent_cmd else None
    vision = executable_status(args.vision_figure_agent_cmd) if args.vision_figure_agent_cmd else None
    errors: list[str] = []
    for row in rows:
        if not row["input_exists"]:
            errors.append(f"{row['label']} input does not exist: {row['input']}")
    for tool, available in tool_status.items():
        if not available:
            errors.append(f"required tool not found for selected mode: {tool}")
    if args.prose_agent_cmd and not agent.get("ok"):
        errors.append(f"prose agent command is not executable: {agent.get('error')}")
    if specialist is not None and not specialist.get("ok"):
        errors.append(f"specialist agent command is not executable: {specialist.get('error')}")
    if vision is not None and not vision.get("ok"):
        errors.append(f"vision figure agent command is not executable: {vision.get('error')}")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_by": "scripts/run_pdf_overlay_full_review_matrix.py",
        "mode": "preflight",
        "passed": not errors,
        "errors": errors,
        "jobs": rows,
        "tools": tool_status,
        "prose_agent_cmd": agent,
        "specialist_agent_cmd": specialist,
        "vision_figure_agent_cmd": vision,
        "matrix_command": matrix_command(jobs, summary_out.parent / "strict_migration_matrix.json"),
        "note": "preflight does not invoke LLM agents or certify migration readiness",
    }
    return payload


def run_pipeline_job(job: ReviewJob, args: argparse.Namespace) -> dict[str, Any]:
    job.bundle.mkdir(parents=True, exist_ok=True)
    cmd = pipeline_command(job, args)
    status = load_json(job.bundle / "pipeline_status.json")
    if not args.rerun_completed and isinstance(status, dict) and status.get("state") == "complete":
        return {
            "label": job.label,
            "input": str(job.input_path),
            "bundle": str(job.bundle),
            "command": cmd,
            "returncode": 0,
            "state": "complete",
            "complete": True,
            "skipped_existing_complete": True,
            "stdout_tail": "",
            "stderr_tail": "",
            "next_action": status.get("next_action") or "",
        }
    if not args.prose_agent_cmd:
        return {
            "label": job.label,
            "input": str(job.input_path),
            "bundle": str(job.bundle),
            "command": cmd,
            "returncode": 2,
            "state": status.get("state") if isinstance(status, dict) else "",
            "complete": False,
            "stdout_tail": "",
            "stderr_tail": "",
            "next_action": "Provide --prose-agent-cmd or rerun after the bundle pipeline_status.json is complete.",
            "error": "--prose-agent-cmd is required unless the bundle is already complete",
        }
    result = run_command(cmd, timeout=args.pipeline_timeout)
    status = load_json(job.bundle / "pipeline_status.json")
    state = status.get("state") if isinstance(status, dict) else ""
    complete = result.returncode == 0 and state == "complete"
    return {
        "label": job.label,
        "input": str(job.input_path),
        "bundle": str(job.bundle),
        "command": cmd,
        "returncode": result.returncode,
        "state": state,
        "complete": complete,
        "stdout_tail": compact_tail(result.stdout),
        "stderr_tail": compact_tail(result.stderr),
        "next_action": status.get("next_action") if isinstance(status, dict) else "",
    }


def matrix_command(jobs: list[ReviewJob], summary_out: Path) -> list[str]:
    by_label = {job.label: job.bundle for job in jobs}
    return [
        sys.executable,
        str(SCRIPT_DIR / "run_pdf_overlay_migration_matrix.py"),
        "--hidden",
        str(by_label["hidden"]),
        "--neurips",
        str(by_label["neurips"]),
        "--acl",
        str(by_label["acl"]),
        "--summary-out",
        str(summary_out),
    ]


def run_matrix(jobs: list[ReviewJob], summary_out: Path, *, timeout: int) -> dict[str, Any]:
    cmd = matrix_command(jobs, summary_out)
    result = run_command(cmd, timeout=timeout)
    payload = load_json(summary_out)
    if not isinstance(payload, dict):
        payload = {
            "schema_version": 1,
            "generated_by": "scripts/run_pdf_overlay_full_review_matrix.py",
            "passed": False,
            "error": "migration matrix did not write JSON summary",
        }
    payload["command"] = cmd
    payload["returncode"] = result.returncode
    payload["stdout_tail"] = compact_tail(result.stdout)
    payload["stderr_tail"] = compact_tail(result.stderr)
    return payload


def default_bundle(out_root: Path, label: str) -> Path:
    return out_root / label


def build_jobs(args: argparse.Namespace) -> list[ReviewJob]:
    out_root = args.out_root.expanduser().resolve()
    return [
        ReviewJob("hidden", args.hidden_input.expanduser().resolve(), (args.hidden_bundle or default_bundle(out_root, "hidden")).expanduser().resolve()),
        ReviewJob("neurips", args.neurips_input.expanduser().resolve(), (args.neurips_bundle or default_bundle(out_root, "neurips")).expanduser().resolve()),
        ReviewJob("acl", args.acl_input.expanduser().resolve(), (args.acl_bundle or default_bundle(out_root, "acl")).expanduser().resolve()),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Example for a stdin-based CLI: --prose-agent-cmd "
            "\"python3 scripts/run_agent_command.py --env CODEX_HOME=.ariadne_codex_home --stdin-prompt --command "
            "'codex exec --cd /path/to/repo --sandbox workspace-write -'\""
        ),
    )
    parser.add_argument("--hidden-input", required=True, type=Path)
    parser.add_argument("--neurips-input", required=True, type=Path, help="NeurIPS/ICLR-style input")
    parser.add_argument("--acl-input", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--hidden-bundle", type=Path)
    parser.add_argument("--neurips-bundle", type=Path)
    parser.add_argument("--acl-bundle", type=Path)
    parser.add_argument("--summary-out", type=Path, help="Default: <out-root>/full_review_matrix_summary.json")
    parser.add_argument("--prose-agent-cmd")
    parser.add_argument("--specialist-agent-cmd")
    parser.add_argument("--use-specialist-agent-output", action="store_true")
    parser.add_argument("--vision-figure-agent-cmd")
    parser.add_argument("--domains", default="all")
    parser.add_argument("--pages", default="all")
    parser.add_argument("--force-specialists", action="store_true")
    parser.add_argument("--force-rebuild", action="append", choices=("units", "bbox", "all"), default=[])
    parser.add_argument("--skip-pdf-build", action="store_true")
    parser.add_argument("--no-export-annotated-pdf", action="store_true")
    parser.add_argument("--pdf-timeout", type=int, default=300)
    parser.add_argument("--bbox-timeout", type=int, default=300)
    parser.add_argument("--render-timeout", type=int, default=300)
    parser.add_argument("--specialist-timeout", type=int, default=300)
    parser.add_argument("--prose-agent-timeout", type=int, default=1800)
    parser.add_argument("--prose-max-iterations", type=int, default=200)
    parser.add_argument("--pipeline-timeout", type=int, default=7200)
    parser.add_argument("--matrix-timeout", type=int, default=900)
    parser.add_argument("--preflight", action="store_true", help="Validate inputs, tools, and planned commands without running LLM agents")
    parser.add_argument("--rerun-completed", action="store_true", help="Re-run pipeline jobs even when their bundle pipeline_status.json is already complete")
    args = parser.parse_args(argv)

    out_root = args.out_root.expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    jobs = build_jobs(args)
    summary_out = (args.summary_out or (out_root / "full_review_matrix_summary.json")).expanduser().resolve()
    if args.preflight:
        payload = preflight(jobs, args, summary_out)
        summary_out.parent.mkdir(parents=True, exist_ok=True)
        summary_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["passed"] else 1

    pipeline_rows = [run_pipeline_job(job, args) for job in jobs]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_by": "scripts/run_pdf_overlay_full_review_matrix.py",
        "jobs": pipeline_rows,
        "matrix": None,
        "passed": False,
    }
    if all(row["complete"] for row in pipeline_rows):
        matrix_summary = out_root / "strict_migration_matrix.json"
        payload["matrix"] = run_matrix(jobs, matrix_summary, timeout=args.matrix_timeout)
        payload["passed"] = bool(isinstance(payload["matrix"], dict) and payload["matrix"].get("matrix_complete"))
    else:
        payload["error"] = "one or more full-review pipeline jobs did not complete"
    summary_out.parent.mkdir(parents=True, exist_ok=True)
    summary_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
