#!/usr/bin/env python3
"""Run Ariadne's deterministic review backbone with explicit prose checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_paper_pdf import find_entry_tex  # noqa: E402


STATUS_FILE = "pipeline_status.json"
ISSUE_DIR_NAME = "issue_artifacts"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def compact_tail(value: str, *, max_chars: int = 1600) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def script(name: str) -> str:
    return str(SCRIPT_DIR / name)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class PipelineStep:
    name: str
    status: str
    command: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    returncode: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    message: str = ""

    def to_json(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "status": self.status,
        }
        if self.command:
            payload["command"] = self.command
        if self.outputs:
            payload["outputs"] = self.outputs
        if self.returncode is not None:
            payload["returncode"] = self.returncode
        if self.stdout_tail:
            payload["stdout_tail"] = self.stdout_tail
        if self.stderr_tail:
            payload["stderr_tail"] = self.stderr_tail
        if self.message:
            payload["message"] = self.message
        return payload


@dataclass
class PipelineContext:
    input_path: Path
    entry_tex: Path
    bundle: Path
    issue_artifacts: Path
    pdf: Path | None
    report_html: Path
    source_html: Path
    review_units_jsonl: Path
    review_units_md: Path
    steps: list[PipelineStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    state: str = "running"
    next_action: str = ""

    def path_payload(self) -> dict[str, str]:
        return {
            "entry_tex": str(self.entry_tex),
            "bundle": str(self.bundle),
            "issue_artifacts": str(self.issue_artifacts),
            "pdf": str(self.pdf) if self.pdf else "",
            "report_html": str(self.report_html),
            "source_html": str(self.source_html),
            "review_units_jsonl": str(self.review_units_jsonl),
            "review_units_md": str(self.review_units_md),
        }


def run_command(name: str, cmd: list[str], *, outputs: list[Path] | None = None, timeout: int = 300) -> PipelineStep:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
    )
    return PipelineStep(
        name=name,
        status="completed" if result.returncode == 0 else "error",
        command=cmd,
        outputs=[str(path) for path in outputs or []],
        returncode=result.returncode,
        stdout_tail=compact_tail(result.stdout),
        stderr_tail=compact_tail(result.stderr),
    )


def default_bundle(entry_tex: Path) -> Path:
    return entry_tex.parent / f"ariadne_notes_{entry_tex.stem}"


def resolve_entry(source: Path) -> Path:
    return find_entry_tex(source.expanduser().resolve()).resolve()


def existing_pdf(entry_tex: Path, explicit_pdf: Path | None) -> Path | None:
    if explicit_pdf:
        pdf = explicit_pdf.expanduser().resolve()
        if not pdf.exists():
            raise FileNotFoundError(f"PDF does not exist: {pdf}")
        return pdf
    candidate = entry_tex.with_suffix(".pdf")
    return candidate if candidate.exists() else None


def initialize_context(args: argparse.Namespace) -> PipelineContext:
    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input does not exist: {input_path}")
    entry_tex = resolve_entry(input_path)
    bundle = (args.bundle.expanduser().resolve() if args.bundle else default_bundle(entry_tex).resolve())
    issue_artifacts = bundle / ISSUE_DIR_NAME
    pdf = existing_pdf(entry_tex, args.pdf)
    source_html = (
        args.source_html.expanduser().resolve()
        if args.source_html
        else (bundle / f"{entry_tex.stem}.source.html").resolve()
    )
    report_html = (args.report_html.expanduser().resolve() if args.report_html else (bundle / f"{entry_tex.stem}.html").resolve())
    return PipelineContext(
        input_path=input_path,
        entry_tex=entry_tex,
        bundle=bundle,
        issue_artifacts=issue_artifacts,
        pdf=pdf,
        report_html=report_html,
        source_html=source_html,
        review_units_jsonl=bundle / f"{entry_tex.stem}.review_units.jsonl",
        review_units_md=bundle / f"{entry_tex.stem}.review_units.md",
    )


def record_status(ctx: PipelineContext) -> Path:
    payload = {
        "schema_version": 1,
        "context_policy": "model_readable_pipeline_status_only",
        "generated_by": "scripts/run_review_pipeline.py",
        "state": ctx.state,
        "next_action": ctx.next_action,
        "inputs": {
            "input": str(ctx.input_path),
            "input_hash": sha256_path(ctx.input_path) if ctx.input_path.is_file() else "",
            "entry_tex_hash": sha256_path(ctx.entry_tex),
        },
        "paths": ctx.path_payload(),
        "warnings": ctx.warnings,
        "steps": [step.to_json() for step in ctx.steps],
    }
    status_path = ctx.bundle / STATUS_FILE
    write_json(status_path, payload)
    return status_path


def append_step(ctx: PipelineContext, step: PipelineStep) -> None:
    ctx.steps.append(step)
    if step.status == "error":
        ctx.state = f"failed:{step.name}"
        ctx.next_action = f"Inspect `{ctx.bundle / STATUS_FILE}` and fix the failed `{step.name}` step."
        record_status(ctx)
        raise RuntimeError(f"{step.name} failed with return code {step.returncode}")


def build_pdf_if_needed(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if ctx.pdf is not None:
        ctx.steps.append(PipelineStep("build_pdf", "skipped", outputs=[str(ctx.pdf)], message="using existing PDF"))
        return
    if args.skip_pdf_build:
        ctx.steps.append(PipelineStep("build_pdf", "skipped", message="PDF build disabled and no existing PDF found"))
        return
    step = run_command(
        "build_pdf",
        [sys.executable, script("build_paper_pdf.py"), str(ctx.entry_tex), "--timeout", str(args.pdf_timeout)],
        timeout=args.pdf_timeout + 30,
    )
    ctx.steps.append(step)
    if step.status == "completed":
        try:
            payload = json.loads(step.stdout_tail)
        except json.JSONDecodeError:
            payload = {}
        pdf = Path(str(payload.get("pdf") or ""))
        if pdf.exists():
            ctx.pdf = pdf.resolve()
        else:
            ctx.warnings.append("PDF build reported success but did not return a readable PDF path.")
    else:
        ctx.warnings.append("PDF build failed; continuing with source-only stages where possible.")


def render_source(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if args.source_html and ctx.source_html.exists():
        ctx.steps.append(PipelineStep("render_source_html", "skipped", outputs=[str(ctx.source_html)], message="using provided source HTML"))
        return
    if args.skip_render:
        if not ctx.source_html.exists():
            raise RuntimeError("--skip-render requires --source-html or an existing source HTML path")
        ctx.steps.append(PipelineStep("render_source_html", "skipped", outputs=[str(ctx.source_html)], message="render disabled"))
        return
    cmd = [
        sys.executable,
        script("render_paper_html.py"),
        str(ctx.entry_tex),
        "--output",
        str(ctx.report_html),
        "--raw-html",
        str(ctx.source_html),
        "--asset-dir",
        str(ctx.bundle / "assets"),
    ]
    step = run_command("render_source_html", cmd, outputs=[ctx.source_html, ctx.report_html], timeout=args.render_timeout)
    append_step(ctx, step)


def extract_units(ctx: PipelineContext) -> None:
    step = run_command(
        "extract_review_units",
        [
            sys.executable,
            script("extract_review_units.py"),
            str(ctx.source_html),
            "--jsonl",
            str(ctx.review_units_jsonl),
            "--markdown",
            str(ctx.review_units_md),
        ],
        outputs=[ctx.review_units_jsonl, ctx.review_units_md],
    )
    append_step(ctx, step)


def estimate_review_unit_tokens(path: Path) -> int:
    if not path.exists():
        return 0
    return max(1, int(len(path.read_text(encoding="utf-8", errors="replace")) / 4))


def maybe_build_prose_shards(ctx: PipelineContext, args: argparse.Namespace) -> None:
    token_estimate = estimate_review_unit_tokens(ctx.review_units_md)
    if token_estimate <= args.prose_shard_threshold:
        ctx.steps.append(
            PipelineStep(
                "build_prose_shards",
                "skipped",
                message=f"review_units token estimate {token_estimate} <= threshold {args.prose_shard_threshold}",
            )
        )
        return
    manifest = ctx.bundle / "phase_a_shard_manifest.json"
    step = run_command(
        "build_prose_shards",
        [
            sys.executable,
            script("build_prose_shards.py"),
            "--bundle",
            str(ctx.bundle),
            "--review-units-md",
            str(ctx.review_units_md),
            "--review-units-jsonl",
            str(ctx.review_units_jsonl),
            "--max-tokens-per-shard",
            str(args.prose_shard_size),
            "--out",
            str(manifest),
        ],
        outputs=[manifest, ctx.bundle / "phase_a_shards"],
    )
    append_step(ctx, step)


def run_specialists(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if args.skip_specialists:
        ctx.steps.append(PipelineStep("run_specialists", "skipped", message="specialist stage disabled"))
        return
    cmd = [
        sys.executable,
        script("run_p1_specialists.py"),
        "--bundle",
        str(ctx.bundle),
        "--tex",
        str(ctx.entry_tex),
        "--domains",
        args.domains,
        "--pages",
        args.pages,
    ]
    if ctx.pdf:
        cmd.extend(["--pdf", str(ctx.pdf)])
    if args.force_specialists:
        cmd.append("--force")
    step = run_command("run_specialists", cmd, outputs=[ctx.issue_artifacts, ctx.bundle / "p1_specialists_summary.json"], timeout=args.specialist_timeout)
    append_step(ctx, step)


def run_specialist_agent(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if not args.specialist_agent_cmd:
        ctx.steps.append(PipelineStep("run_specialist_agent", "skipped", message="no specialist agent command provided"))
        return
    out_dir = (args.specialist_agent_out_dir.expanduser().resolve() if args.specialist_agent_out_dir else ctx.bundle / "issue_artifacts_llm")
    cmd = [
        sys.executable,
        script("run_specialist_agent.py"),
        "--issues-dir",
        str(ctx.issue_artifacts),
        "--out-dir",
        str(out_dir),
        "--domains",
        args.specialist_agent_domains,
        "--agent-cmd",
        args.specialist_agent_cmd,
        "--agent-timeout",
        str(args.specialist_agent_timeout),
        "--audit",
    ]
    if args.specialist_agent_dry_run:
        cmd.append("--dry-run")
    step = run_command(
        "run_specialist_agent",
        cmd,
        outputs=[out_dir, out_dir / "specialist_agent_summary.json"],
        timeout=args.specialist_agent_timeout * 2,
    )
    append_step(ctx, step)
    if args.use_specialist_agent_output:
        ctx.issue_artifacts = out_dir


def run_vision_figure_agent(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if not args.vision_figure_agent_cmd:
        ctx.steps.append(PipelineStep("run_vision_figure_agent", "skipped", message="no vision figure agent command provided"))
        return
    if not ctx.pdf:
        ctx.steps.append(PipelineStep("run_vision_figure_agent", "skipped", message="no PDF available for vision figure agent"))
        return
    out = ctx.issue_artifacts / "figure_caption_vision_issues.json"
    cmd = [
        sys.executable,
        script("run_vision_figure_agent.py"),
        "--pdf",
        str(ctx.pdf),
        "--out",
        str(out),
        "--agent-cmd",
        args.vision_figure_agent_cmd,
        "--pages",
        args.vision_figure_pages,
        "--agent-timeout",
        str(args.vision_figure_agent_timeout),
    ]
    existing = ctx.issue_artifacts / "figure_caption_issues.json"
    if existing.exists():
        cmd.extend(["--figure-issues", str(existing)])
    if args.vision_figure_dry_run:
        cmd.append("--dry-run")
    step = run_command(
        "run_vision_figure_agent",
        cmd,
        outputs=[out, ctx.issue_artifacts / "vision_image_manifest.json", ctx.issue_artifacts / "vision_figure_agent_summary.json"],
        timeout=args.vision_figure_agent_timeout + 120,
    )
    append_step(ctx, step)


def run_prose_agent(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if not args.prose_agent_cmd:
        ctx.steps.append(PipelineStep("run_prose_agent", "skipped", message="no prose agent command provided"))
        return
    cmd = [
        sys.executable,
        script("run_prose_agent.py"),
        "--bundle",
        str(ctx.bundle),
        "--phase",
        args.prose_phase,
        "--agent-cmd",
        args.prose_agent_cmd,
        "--review-units-md",
        str(ctx.review_units_md),
        "--review-units-jsonl",
        str(ctx.review_units_jsonl),
        "--max-iterations",
        str(args.prose_max_iterations),
        "--agent-timeout",
        str(args.prose_agent_timeout),
        "--allow-incomplete",
    ]
    if args.prose_dry_run:
        cmd.append("--dry-run")
    shard_manifest = ctx.bundle / "phase_a_shard_manifest.json"
    if shard_manifest.exists():
        cmd.extend(["--shard-manifest", str(shard_manifest)])
    step = run_command(
        "run_prose_agent",
        cmd,
        outputs=[ctx.bundle / "prose_agent_summary.json"],
        timeout=max(args.prose_agent_timeout * max(1, args.prose_max_iterations), args.prose_agent_timeout + 60),
    )
    append_step(ctx, step)


def phase_a_status(ctx: PipelineContext) -> dict[str, Any]:
    status_path = ctx.bundle / "phase_a_resume_status.json"
    next_path = ctx.bundle / "phase_a_next_step.json"
    cmd = [
        sys.executable,
        script("phase_a_resume_status.py"),
        "--review-units",
        str(ctx.review_units_jsonl),
        "--prose-issues",
        str(ctx.issue_artifacts / "prose_issues.jsonl"),
        "--paragraph-decisions",
        str(ctx.bundle / "paragraph_decisions.jsonl"),
        "--section-reflections",
        str(ctx.bundle / "section_reflections.json"),
        "--cold-skim",
        str(ctx.bundle / "cold_skim_frame.json"),
        "--claim-candidates",
        str(ctx.bundle / "claim_candidates.json"),
        "--out",
        str(status_path),
        "--next-out",
        str(next_path),
    ]
    step = run_command("phase_a_resume_status", cmd, outputs=[status_path, next_path])
    append_step(ctx, step)
    build_phase_a_packet(ctx)
    return read_json(status_path)


def build_phase_a_packet(ctx: PipelineContext) -> None:
    packet_path = ctx.bundle / "phase_a_prompt_packet.json"
    step = run_command(
        "build_phase_a_prompt_packet",
        [
            sys.executable,
            script("build_prose_phase_packet.py"),
            "--phase",
            "phase_a",
            "--bundle",
            str(ctx.bundle),
            "--review-units-md",
            str(ctx.review_units_md),
            "--review-units-jsonl",
            str(ctx.review_units_jsonl),
            "--out",
            str(packet_path),
        ],
        outputs=[packet_path],
    )
    append_step(ctx, step)


def build_phase_b_packet(ctx: PipelineContext) -> None:
    packet_path = ctx.bundle / "phase_b_prompt_packet.json"
    phase_b_context = ctx.bundle / "phase_b_context.json"
    step = run_command(
        "build_phase_b_prompt_packet",
        [
            sys.executable,
            script("build_prose_phase_packet.py"),
            "--phase",
            "phase_b",
            "--bundle",
            str(ctx.bundle),
            "--phase-b-context",
            str(phase_b_context),
            "--out",
            str(packet_path),
        ],
        outputs=[packet_path],
    )
    append_step(ctx, step)


def maybe_build_phase_b_context(ctx: PipelineContext) -> bool:
    required = [ctx.bundle / "cold_skim_frame.json", ctx.bundle / "section_reflections.json", ctx.bundle / "claim_candidates.json"]
    if not all(path.exists() for path in required):
        return False
    phase_b_context = ctx.bundle / "phase_b_context.json"
    step = run_command(
        "build_phase_b_context",
        [
            sys.executable,
            script("build_phase_b_input.py"),
            "--cold-skim",
            str(required[0]),
            "--section-reflections",
            str(required[1]),
            "--claim-candidates",
            str(required[2]),
            "--issues-dir",
            str(ctx.issue_artifacts),
            "--out",
            str(phase_b_context),
        ],
        outputs=[phase_b_context],
    )
    append_step(ctx, step)
    build_phase_b_packet(ctx)
    return True


def can_compile(ctx: PipelineContext, phase_a: dict[str, Any], *, allow_partial: bool) -> tuple[bool, str]:
    if allow_partial:
        return True, ""
    coverage = phase_a.get("coverage") if isinstance(phase_a, dict) else {}
    if not isinstance(coverage, dict) or not coverage.get("phase_a_complete"):
        return False, "needs_prose_phase_a"
    required_phase_b = [
        ctx.bundle / "argument_map.json",
        ctx.bundle / "claims.json",
        ctx.bundle / "salvageable_core.json",
        ctx.issue_artifacts / "whole_paper_findings.jsonl",
    ]
    if not all(path.exists() for path in required_phase_b):
        return False, "needs_prose_phase_b"
    return True, ""


def compile_artifacts(ctx: PipelineContext) -> None:
    source_hash = sha256_path(ctx.source_html) if ctx.source_html.exists() else ""
    step = run_command(
        "compile_review_artifacts",
        [
            sys.executable,
            script("compile_review_artifacts.py"),
            "--issues-dir",
            str(ctx.issue_artifacts),
            "--findings-out",
            str(ctx.bundle / "findings.json"),
            "--annotations-out",
            str(ctx.bundle / "annotations.json"),
            "--index-out",
            str(ctx.issue_artifacts / "compiled_issue_index.json"),
            "--source-artifact",
            str(ctx.source_html),
            "--source-hash",
            source_hash,
        ],
        outputs=[ctx.bundle / "findings.json", ctx.bundle / "annotations.json", ctx.issue_artifacts / "compiled_issue_index.json"],
    )
    append_step(ctx, step)


def build_derivatives(ctx: PipelineContext, *, requested_scope: str, full_report: bool) -> None:
    render_mode = "paper-reader-with-global-findings" if full_report else "paper-reader-only"
    cmd = [
        sys.executable,
        script("build_review_derivatives.py"),
        "--findings",
        str(ctx.bundle / "findings.json"),
        "--annotations",
        str(ctx.bundle / "annotations.json"),
        "--issues-dir",
        str(ctx.issue_artifacts),
        "--source-artifact",
        str(ctx.source_html),
        "--source-hash",
        sha256_path(ctx.source_html) if ctx.source_html.exists() else "",
        "--requested-scope",
        requested_scope,
        "--render-mode",
        render_mode,
        "--phase-a-status",
        str(ctx.bundle / "phase_a_resume_status.json"),
        "--phase-b-context",
        str(ctx.bundle / "phase_b_context.json"),
        "--source-integrity-check",
        "skipped",
        "--output-file",
        str(ctx.report_html),
        "--coverage-out",
        str(ctx.bundle / "coverage.json"),
        "--manifest-out",
        str(ctx.bundle / "render_manifest.json"),
        "--pass-observations-out",
        str(ctx.bundle / "pass_observations.json"),
    ]
    layout_audit = ctx.bundle / "layout_audit.json"
    if layout_audit.exists():
        cmd.extend(["--layout-audit", str(layout_audit)])
    step = run_command(
        "build_review_derivatives",
        cmd,
        outputs=[ctx.bundle / "coverage.json", ctx.bundle / "render_manifest.json", ctx.bundle / "pass_observations.json"],
    )
    append_step(ctx, step)


def render_final(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if args.skip_final_render:
        ctx.steps.append(PipelineStep("render_final_report", "skipped", message="final render disabled"))
        return
    cmd = [
        sys.executable,
        script("render_paper_html.py"),
        str(ctx.entry_tex),
        "--output",
        str(ctx.report_html),
        "--raw-html",
        str(ctx.source_html),
        "--annotations",
        str(ctx.bundle / "annotations.json"),
        "--findings",
        str(ctx.bundle / "findings.json"),
        "--issues-dir",
        str(ctx.issue_artifacts),
        "--asset-dir",
        str(ctx.bundle / "assets"),
        "--reuse-raw-html",
        "--coverage",
        str(ctx.bundle / "coverage.json"),
        "--paper-layout",
        args.paper_layout,
    ]
    if args.full_report:
        cmd.append("--full-report")
    if args.inline_images:
        cmd.append("--inline-images")
    step = run_command("render_final_report", cmd, outputs=[ctx.report_html, ctx.source_html], timeout=args.render_timeout)
    append_step(ctx, step)


def run_audits(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if args.skip_audit:
        ctx.steps.append(PipelineStep("audit", "skipped", message="audit disabled"))
        return
    html_step = run_command("audit_html_report", [sys.executable, script("audit_html_report.py"), str(ctx.report_html), "--source", str(ctx.source_html)])
    append_step(ctx, html_step)
    cmd = [
        sys.executable,
        script("audit_review_artifacts.py"),
        "--findings",
        str(ctx.bundle / "findings.json"),
        "--annotations",
        str(ctx.bundle / "annotations.json"),
        "--coverage",
        str(ctx.bundle / "coverage.json"),
        "--manifest",
        str(ctx.bundle / "render_manifest.json"),
        "--pass-observations",
        str(ctx.bundle / "pass_observations.json"),
        "--issue-artifacts",
        str(ctx.issue_artifacts),
        "--html",
        str(ctx.report_html),
        "--source",
        str(ctx.source_html),
    ]
    claims = ctx.bundle / "claims.json"
    if claims.exists():
        cmd.extend(["--claims", str(claims)])
    layout_audit = ctx.bundle / "layout_audit.json"
    if layout_audit.exists():
        cmd.extend(["--layout-audit", str(layout_audit)])
    review_step = run_command("audit_review_artifacts", cmd)
    append_step(ctx, review_step)


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    ctx = initialize_context(args)
    ctx.bundle.mkdir(parents=True, exist_ok=True)
    ctx.issue_artifacts.mkdir(parents=True, exist_ok=True)
    try:
        build_pdf_if_needed(ctx, args)
        render_source(ctx, args)
        extract_units(ctx)
        maybe_build_prose_shards(ctx, args)
        run_specialists(ctx, args)
        run_specialist_agent(ctx, args)
        run_vision_figure_agent(ctx, args)
        run_prose_agent(ctx, args)
        phase_a = phase_a_status(ctx)
        maybe_build_phase_b_context(ctx)
        allowed, blocked_state = can_compile(ctx, phase_a, allow_partial=args.allow_partial_compile)
        if args.prepare_only or not allowed:
            ctx.state = "prepared" if args.prepare_only else blocked_state
            if ctx.state == "needs_prose_phase_a":
                shard_manifest = ctx.bundle / "phase_a_shard_manifest.json"
                if shard_manifest.exists():
                    ctx.next_action = f"Run sharded Prose Phase A using `{shard_manifest}`, then run Phase B synthesis."
                else:
                    ctx.next_action = f"Run Prose Phase A using `{ctx.bundle / 'phase_a_prompt_packet.json'}`."
            elif ctx.state == "needs_prose_phase_b":
                ctx.next_action = f"Run Prose Phase B using `{ctx.bundle / 'phase_b_prompt_packet.json'}`."
            else:
                shard_manifest = ctx.bundle / "phase_a_shard_manifest.json"
                if shard_manifest.exists():
                    ctx.next_action = f"Deterministic prep complete. Run sharded Prose Phase A using `{shard_manifest}`."
                else:
                    ctx.next_action = f"Deterministic prep complete. Continue with Prose Phase A using `{ctx.bundle / 'phase_a_prompt_packet.json'}`."
            status_path = record_status(ctx)
            return {"status_path": status_path, "state": ctx.state, "next_action": ctx.next_action}
        requested_scope = "partial compiled Ariadne review" if args.allow_partial_compile else "full compiled Ariadne review"
        compile_artifacts(ctx)
        build_derivatives(ctx, requested_scope=requested_scope, full_report=args.full_report)
        render_final(ctx, args)
        run_audits(ctx, args)
        ctx.state = "complete"
        ctx.next_action = f"Review report ready at `{ctx.report_html}`."
        status_path = record_status(ctx)
        return {"status_path": status_path, "state": ctx.state, "next_action": ctx.next_action}
    except Exception:
        if not ctx.state.startswith("failed:"):
            ctx.state = "failed"
            ctx.next_action = f"Inspect `{ctx.bundle / STATUS_FILE}` for the last completed step."
            record_status(ctx)
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="LaTeX project directory or entry .tex file")
    parser.add_argument("--bundle", type=Path, help="Output artifact bundle directory")
    parser.add_argument("--pdf", type=Path, help="Existing compiled PDF")
    parser.add_argument("--source-html", type=Path, help="Existing canonical source HTML; skips source render")
    parser.add_argument("--report-html", type=Path, help="Final report HTML path")
    parser.add_argument("--domains", default="all", help="Specialist domains for run_p1_specialists.py")
    parser.add_argument("--pages", default="all", help="Page range for layout/figure rendered checks")
    parser.add_argument("--force-specialists", action="store_true", help="Regenerate raw specialist audits")
    parser.add_argument("--skip-specialists", action="store_true", help="Skip specialist stage")
    parser.add_argument("--specialist-agent-cmd", help="Optional external specialist refinement command for run_specialist_agent.py")
    parser.add_argument("--specialist-agent-domains", default="all", help="Specialist domains to refine when --specialist-agent-cmd is provided")
    parser.add_argument("--specialist-agent-out-dir", type=Path, help="Output dir for refined specialist artifacts; default <bundle>/issue_artifacts_llm")
    parser.add_argument("--specialist-agent-timeout", type=int, default=900)
    parser.add_argument("--specialist-agent-dry-run", action="store_true")
    parser.add_argument("--use-specialist-agent-output", action="store_true", help="Compile/render from refined specialist issue artifacts")
    parser.add_argument("--vision-figure-agent-cmd", help="Optional external vision specialist command for figure/table page images")
    parser.add_argument("--vision-figure-pages", default="all", help="Pages to render for optional vision figure specialist")
    parser.add_argument("--vision-figure-agent-timeout", type=int, default=1200)
    parser.add_argument("--vision-figure-dry-run", action="store_true")
    parser.add_argument("--prose-agent-cmd", help="Optional external agent command for run_prose_agent.py")
    parser.add_argument("--prose-phase", default="all", choices=("phase_a", "phase_b", "all"), help="Prose phase(s) to run when --prose-agent-cmd is provided")
    parser.add_argument("--prose-max-iterations", type=int, default=200, help="Maximum Phase A agent iterations")
    parser.add_argument("--prose-agent-timeout", type=int, default=1800, help="Timeout per prose agent command call")
    parser.add_argument("--prose-dry-run", action="store_true", help="Build prose packets without invoking --prose-agent-cmd")
    parser.add_argument("--prose-shard-threshold", type=int, default=40_000, help="Build Phase A shard packets when review_units token estimate exceeds this value")
    parser.add_argument("--prose-shard-size", type=int, default=35_000, help="Approximate max tokens per Phase A shard packet")
    parser.add_argument("--skip-pdf-build", action="store_true", help="Do not attempt to build a missing PDF")
    parser.add_argument("--skip-render", action="store_true", help="Do not render source HTML; requires --source-html or existing source")
    parser.add_argument("--prepare-only", action="store_true", help="Stop after deterministic prep and Phase A resume packet")
    parser.add_argument("--allow-partial-compile", action="store_true", help="Compile available issues even if Prose Phase A/B is incomplete")
    parser.add_argument("--full-report", action="store_true", help="Render global Major/Blocker paper-level findings after the paper-reader overlay")
    parser.add_argument("--skip-final-render", action="store_true", help="Compile artifacts but skip final HTML rendering")
    parser.add_argument("--skip-audit", action="store_true", help="Skip final audits")
    parser.add_argument("--inline-images", action="store_true", help="Inline rendered PDF figures in final HTML")
    parser.add_argument(
        "--paper-layout",
        choices=("source", "single", "two-column", "paged", "paged-two-column"),
        default="source",
        help="Paper pane layout for the final HTML; source infers layout from generic LaTeX/PDF signals and PDF page maps.",
    )
    parser.add_argument("--pdf-timeout", type=int, default=300)
    parser.add_argument("--render-timeout", type=int, default=300)
    parser.add_argument("--specialist-timeout", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        result = run_pipeline(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Pipeline state: {result['state']}")
    print(f"Pipeline status: {result['status_path']}")
    print(f"Next action: {result['next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
