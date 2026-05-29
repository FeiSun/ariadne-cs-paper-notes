#!/usr/bin/env python3
"""Run Ariadne's deterministic review backbone with explicit prose checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_paper_pdf import expanded_latex_for_tool_detection, find_entry_tex  # noqa: E402


STATUS_FILE = "pipeline_status.json"
ISSUE_DIR_NAME = "issue_artifacts"
BIB_COMMAND_RE = re.compile(
    r"\\(?:bibliography|addbibresource|addglobalbib|addsectionbib)(?:\s*\[[^\]]*\])?\s*\{[^{}]+\}"
    r"|\\printbibliography\b"
)
BIBLATEX_PACKAGE_RE = re.compile(r"\\usepackage(?:\s*\[[^\]]*\])?\s*\{[^{}]*\bbiblatex\b[^{}]*\}")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


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
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)
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
    review_units_jsonl: Path
    review_units_md: Path
    sentence_bbox: Path
    pdf_overlay_html: Path
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
            "review_units_jsonl": str(self.review_units_jsonl),
            "review_units_md": str(self.review_units_md),
            "review_units_pdf_text": str(review_units_pdf_text_path(self)),
            "sentence_bbox": str(self.sentence_bbox),
            "pdf_overlay_html": str(self.pdf_overlay_html),
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
        stdout=result.stdout,
        stderr=result.stderr,
        stdout_tail=compact_tail(result.stdout),
        stderr_tail=compact_tail(result.stderr),
    )


def default_bundle(entry_tex: Path) -> Path:
    return entry_tex.parent / f"ariadne_notes_{entry_tex.stem}"


def resolve_entry(source: Path) -> Path:
    return find_entry_tex(source.expanduser().resolve()).resolve()


def is_pdf_input(source: Path) -> bool:
    return source.expanduser().resolve().suffix.lower() == ".pdf"


def uses_pdf_review_units(ctx: Any, args: argparse.Namespace | None = None) -> bool:
    if isinstance(ctx, Path):
        return is_pdf_input(ctx)
    if isinstance(ctx, argparse.Namespace):
        return getattr(ctx, "review_units_source", "") == "pdf"
    return is_pdf_input(ctx.entry_tex) or (args is not None and getattr(args, "review_units_source", "") == "pdf")


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
    if args.review_units_source == "pdf":
        if is_pdf_input(input_path):
            pdf = input_path
        else:
            tex = resolve_entry(input_path)
            pdf = existing_pdf(tex, args.pdf)
            if pdf is None:
                raise FileNotFoundError("PDF review-unit source requested, but no input or companion PDF was found")
        entry_tex = pdf
    else:
        entry_tex = input_path if is_pdf_input(input_path) else resolve_entry(input_path)
        pdf = input_path if is_pdf_input(input_path) else existing_pdf(entry_tex, args.pdf)
    bundle = (args.bundle.expanduser().resolve() if args.bundle else default_bundle(entry_tex).resolve())
    issue_artifacts = bundle / ISSUE_DIR_NAME
    default_report = bundle / (
        "issue_report.html" if args.paper_view == "report-only" else "ariadne_review_pdf/index.html"
    )
    report_html = (args.report_html.expanduser().resolve() if args.report_html else default_report.resolve())
    return PipelineContext(
        input_path=input_path,
        entry_tex=entry_tex,
        bundle=bundle,
        issue_artifacts=issue_artifacts,
        pdf=pdf,
        report_html=report_html,
        review_units_jsonl=bundle / f"{entry_tex.stem}.review_units.jsonl",
        review_units_md=bundle / f"{entry_tex.stem}.review_units.md",
        sentence_bbox=bundle / "sentence_bbox.json",
        pdf_overlay_html=report_html if args.paper_view == "pdf-overlay" else bundle / "ariadne_review_pdf" / "index.html",
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


def strip_latex_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        escaped = False
        kept: list[str] = []
        for char in line:
            if char == "%" and not escaped:
                break
            kept.append(char)
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
        lines.append("".join(kept))
    return "\n".join(lines)


def tex_tree_hash(entry: Path) -> str:
    return sha256_text(strip_latex_comments(expanded_latex_for_tool_detection(entry)))


def force_rebuild(args: argparse.Namespace, target: str) -> bool:
    values = set(getattr(args, "force_rebuild", []) or [])
    return "all" in values or target in values


def latex_uses_bibliography(entry: Path) -> bool:
    if is_pdf_input(entry):
        return False
    expanded = strip_latex_comments(expanded_latex_for_tool_detection(entry))
    return bool(BIB_COMMAND_RE.search(expanded) or BIBLATEX_PACKAGE_RE.search(expanded))


def existing_pdf_has_incomplete_bibliography(entry: Path, pdf: Path) -> bool:
    if not pdf.exists() or not latex_uses_bibliography(entry):
        return False
    bbl_candidates = {pdf.with_suffix(".bbl"), entry.with_suffix(".bbl")}
    if not any(path.exists() and path.stat().st_size > 0 for path in bbl_candidates):
        return True
    log_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in {pdf.with_suffix(".log"), entry.with_suffix(".log")}
        if path.exists()
    )
    return bool(
        re.search(r"No file\s+[^.\s]+\.bbl", log_text)
        or "There were undefined citations" in log_text
        or re.search(r"Citation `[^']+' .* undefined", log_text)
    )


def layout_audit_stale_for_pdf(layout_audit: Path, pdf: Path) -> bool:
    if not layout_audit.exists():
        return True
    try:
        payload = read_json(layout_audit)
    except (OSError, json.JSONDecodeError):
        return True
    declared_hash = str(payload.get("pdf_hash") or "")
    return not declared_hash or declared_hash != sha256_path(pdf)


def layout_issue_stale_for_raw(layout_issues: Path, layout_audit: Path) -> bool:
    if not layout_issues.exists():
        return layout_audit.exists()
    if not layout_audit.exists():
        return True
    try:
        payload = read_json(layout_issues)
    except (OSError, json.JSONDecodeError):
        return True
    source_artifacts = payload.get("source_artifacts")
    if not isinstance(source_artifacts, list):
        return True
    raw_hash = sha256_path(layout_audit)
    raw_path = str(layout_audit)
    for source in source_artifacts:
        if not isinstance(source, dict):
            continue
        source_path = str(source.get("path") or "")
        if source_path == raw_path or Path(source_path).name == layout_audit.name:
            return str(source.get("hash") or "") != raw_hash
    return True


def refresh_stale_layout_artifacts(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if ctx.pdf is None or not ctx.pdf.exists():
        return
    layout_audit = ctx.bundle / "layout_audit.json"
    layout_issues = ctx.issue_artifacts / "layout_issues.json"
    has_layout_artifacts = layout_audit.exists() or layout_issues.exists()
    if not has_layout_artifacts:
        return

    needs_audit = layout_audit_stale_for_pdf(layout_audit, ctx.pdf)
    needs_issues = needs_audit or layout_issue_stale_for_raw(layout_issues, layout_audit)
    if not needs_audit and not needs_issues:
        return

    if needs_audit:
        if not shutil.which("pdftotext"):
            ctx.warnings.append(
                "Could not refresh stale layout_audit.json because pdftotext is unavailable; stale layout artifacts will be ignored."
            )
            return
        ctx.warnings.append("Refreshing layout_audit.json because the compiled PDF changed.")
        step = run_command(
            "refresh_layout_audit",
            [
                sys.executable,
                script("check_page_layout.py"),
                str(ctx.pdf),
                "--pages",
                args.pages,
                "--out",
                str(layout_audit),
            ],
            outputs=[layout_audit],
            timeout=args.specialist_timeout,
        )
        append_step(ctx, step)

    if needs_issues or needs_audit:
        step = run_command(
            "refresh_layout_issues",
            [
                sys.executable,
                script("build_specialist_issues.py"),
                "--domain",
                "layout",
                "--raw-audit",
                str(layout_audit),
                "--out",
                str(layout_issues),
            ],
            outputs=[layout_issues],
            timeout=args.specialist_timeout,
        )
        append_step(ctx, step)


def prepare_layout_audit_for_review_units(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if ctx.pdf is None or not ctx.pdf.exists() or uses_pdf_review_units(ctx, args):
        ctx.steps.append(PipelineStep("prepare_layout_audit_for_review_units", "skipped", message="no TeX/PDF layout unit input"))
        return
    layout_audit = ctx.bundle / "layout_audit.json"
    if layout_audit.exists() and not layout_audit_stale_for_pdf(layout_audit, ctx.pdf):
        ctx.steps.append(PipelineStep("prepare_layout_audit_for_review_units", "skipped", outputs=[str(layout_audit)], message="fresh layout_audit.json already exists"))
        return
    if not shutil.which("pdftotext"):
        ctx.steps.append(PipelineStep("prepare_layout_audit_for_review_units", "skipped", message="pdftotext unavailable"))
        return
    step = run_command(
        "prepare_layout_audit_for_review_units",
        [
            sys.executable,
            script("check_page_layout.py"),
            str(ctx.pdf),
            "--pages",
            args.pages,
            "--out",
            str(layout_audit),
        ],
        outputs=[layout_audit],
        timeout=args.specialist_timeout,
    )
    if step.status != "completed":
        ctx.warnings.append("Could not prepare layout_audit.json before review-unit extraction; page_layout units will be omitted.")
        step.status = "skipped"
        step.message = "layout audit unavailable for review-unit extraction"
    ctx.steps.append(step)


def usable_layout_audit_path(ctx: PipelineContext) -> Path | None:
    layout_audit = ctx.bundle / "layout_audit.json"
    if not layout_audit.exists():
        return None
    if ctx.pdf is None or not ctx.pdf.exists():
        return layout_audit
    try:
        payload = read_json(layout_audit)
    except (OSError, json.JSONDecodeError):
        return layout_audit
    declared_hash = str(payload.get("pdf_hash") or "")
    if declared_hash and declared_hash != sha256_path(ctx.pdf):
        ctx.warnings.append("Ignoring stale layout_audit.json because its PDF hash does not match the current compiled PDF.")
        return None
    return layout_audit


def review_units_cache_path(ctx: PipelineContext) -> Path:
    return ctx.bundle / "review_units_cache.json"


def review_units_pdf_text_path(ctx: PipelineContext) -> Path:
    return ctx.bundle / f"{ctx.entry_tex.stem}.review_units_pdf_text.json"


def review_units_cache_valid(ctx: PipelineContext) -> bool:
    if not ctx.review_units_jsonl.exists() or not ctx.review_units_md.exists():
        return False
    cache_path = review_units_cache_path(ctx)
    if not cache_path.exists():
        return False
    try:
        payload = read_json(cache_path)
    except (OSError, json.JSONDecodeError):
        return False
    if uses_pdf_review_units(ctx):
        return (
            str(payload.get("source")) == str(ctx.entry_tex)
            and str(payload.get("source_hash") or "") == sha256_path(ctx.entry_tex)
            and str(payload.get("extractor_hash") or "") == sha256_path(Path(script("extract_pdf_review_units.py")))
        )
    expected_hash = tex_tree_hash(ctx.entry_tex)
    layout_audit = ctx.bundle / "layout_audit.json"
    if layout_audit.exists():
        expected_hash = sha256_text(expected_hash + sha256_path(layout_audit))
    return (
        str(payload.get("entry_tex")) == str(ctx.entry_tex)
        and str(payload.get("tex_tree_hash") or "") == expected_hash
        and str(payload.get("extractor_hash") or "") == sha256_path(Path(script("extract_tex_review_units.py")))
    )


def write_review_units_cache(ctx: PipelineContext) -> None:
    if uses_pdf_review_units(ctx):
        write_json(
            review_units_cache_path(ctx),
            {
                "schema_version": 1,
                "source": str(ctx.entry_tex),
                "source_mode": "pdf_only",
                "source_hash": sha256_path(ctx.entry_tex),
                "extractor_hash": sha256_path(Path(script("extract_pdf_review_units.py"))),
                "review_units_jsonl_hash": sha256_path(ctx.review_units_jsonl),
                "review_units_md_hash": sha256_path(ctx.review_units_md),
            },
        )
        return
    source_hash = tex_tree_hash(ctx.entry_tex)
    layout_audit = ctx.bundle / "layout_audit.json"
    if layout_audit.exists():
        source_hash = sha256_text(source_hash + sha256_path(layout_audit))
    write_json(
        review_units_cache_path(ctx),
        {
            "schema_version": 1,
            "entry_tex": str(ctx.entry_tex),
            "tex_tree_hash": source_hash,
            "extractor_hash": sha256_path(Path(script("extract_tex_review_units.py"))),
            "review_units_jsonl_hash": sha256_path(ctx.review_units_jsonl),
            "review_units_md_hash": sha256_path(ctx.review_units_md),
        },
    )


def sentence_bbox_cache_valid(ctx: PipelineContext) -> bool:
    sidecar = review_units_pdf_text_path(ctx)
    if ctx.pdf is None or not ctx.pdf.exists() or not ctx.sentence_bbox.exists() or not sidecar.exists():
        return False
    try:
        bbox_payload = read_json(ctx.sentence_bbox)
        sidecar_payload = read_json(sidecar)
    except (OSError, json.JSONDecodeError):
        return False
    pdf_hash = sha256_path(ctx.pdf)
    units_hash = sha256_path(ctx.review_units_jsonl)
    return (
        str(bbox_payload.get("pdf_hash") or "") == pdf_hash
        and str(bbox_payload.get("review_units_hash") or "") == units_hash
        and str(sidecar_payload.get("pdf_hash") or "") == pdf_hash
        and str(sidecar_payload.get("review_units_hash") or "") == units_hash
    )


def build_pdf_if_needed(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if uses_pdf_review_units(ctx, args):
        ctx.pdf = ctx.entry_tex
        ctx.steps.append(PipelineStep("build_pdf", "skipped", outputs=[str(ctx.pdf)], message="PDF-only input"))
        return
    if ctx.pdf is not None and not existing_pdf_has_incomplete_bibliography(ctx.entry_tex, ctx.pdf):
        ctx.steps.append(PipelineStep("build_pdf", "skipped", outputs=[str(ctx.pdf)], message="using existing PDF"))
        return
    if ctx.pdf is not None:
        ctx.warnings.append("Existing PDF appears to be missing a completed bibliography pass; rebuilding PDF with the standard LaTeX bibliography flow.")
        ctx.pdf = None
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
            payload = json.loads(step.stdout or step.stdout_tail)
        except json.JSONDecodeError:
            payload = {}
        pdf = Path(str(payload.get("pdf") or ""))
        if pdf.exists():
            ctx.pdf = pdf.resolve()
        else:
            ctx.warnings.append("PDF build reported success but did not return a readable PDF path.")
    else:
        ctx.warnings.append("PDF build failed; continuing with source-only stages where possible.")


def extract_units(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if not force_rebuild(args, "units") and review_units_cache_valid(ctx):
        ctx.steps.append(
            PipelineStep(
                "extract_tex_review_units",
                "skipped",
                outputs=[str(ctx.review_units_jsonl), str(ctx.review_units_md)],
                message="cached review units match current TeX tree",
            )
        )
        audit_summary = ctx.bundle / "review_units_audit.json"
        if audit_summary.exists():
            ctx.steps.append(PipelineStep("audit_review_units", "skipped", outputs=[str(audit_summary)], message="cached audit summary exists"))
            return
    if uses_pdf_review_units(ctx, args):
        cmd = [
            sys.executable,
            script("extract_pdf_review_units.py"),
            str(ctx.entry_tex),
            "--jsonl",
            str(ctx.review_units_jsonl),
            "--markdown",
            str(ctx.review_units_md),
        ]
        step_name = "extract_pdf_review_units"
    else:
        cmd = [
            sys.executable,
            script("extract_tex_review_units.py"),
            str(ctx.entry_tex),
            "--jsonl",
            str(ctx.review_units_jsonl),
            "--markdown",
            str(ctx.review_units_md),
        ]
        layout_audit = ctx.bundle / "layout_audit.json"
        if layout_audit.exists():
            cmd.extend(["--layout-audit", str(layout_audit)])
        step_name = "extract_tex_review_units"
    step = run_command(step_name, cmd, outputs=[ctx.review_units_jsonl, ctx.review_units_md])
    append_step(ctx, step)
    audit_step = run_command(
        "audit_review_units",
        [
            sys.executable,
            script("audit_review_units.py"),
            str(ctx.review_units_jsonl),
            "--summary-out",
            str(ctx.bundle / "review_units_audit.json"),
        ],
        outputs=[ctx.bundle / "review_units_audit.json"],
    )
    append_step(ctx, audit_step)
    write_review_units_cache(ctx)


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
        "--domains",
        args.domains,
        "--pages",
        args.pages,
    ]
    if not uses_pdf_review_units(ctx, args):
        cmd.extend(["--tex", str(ctx.entry_tex)])
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


def remap_legacy_issue_anchors(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if not getattr(args, "remap_legacy_issue_anchors", False):
        ctx.steps.append(PipelineStep("remap_legacy_issue_anchors", "skipped", message="legacy anchor remap disabled"))
        return
    out_dir = ctx.bundle / "issue_artifacts_remapped"
    step = run_command(
        "remap_legacy_issue_anchors",
        [
            sys.executable,
            script("remap_issue_anchors.py"),
            "--review-units",
            str(ctx.review_units_jsonl),
            "--issues-dir",
            str(ctx.issue_artifacts),
            "--out-dir",
            str(out_dir),
            "--threshold",
            str(getattr(args, "legacy_anchor_remap_threshold", 0.80)),
        ],
        outputs=[out_dir, out_dir / "anchor_remap_summary.json"],
    )
    append_step(ctx, step)
    ctx.issue_artifacts = out_dir


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


def current_source_artifact(ctx: PipelineContext, args: argparse.Namespace) -> Path:
    return ctx.entry_tex


def effective_paper_view(ctx: PipelineContext, args: argparse.Namespace) -> str:
    if args.paper_view == "pdf-overlay" and (ctx.pdf is None or not ctx.pdf.exists()):
        return "report-only"
    return args.paper_view


def compile_artifacts(ctx: PipelineContext, args: argparse.Namespace) -> None:
    source_artifact = current_source_artifact(ctx, args)
    source_hash = sha256_path(source_artifact) if source_artifact.exists() else ""
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
            str(source_artifact),
            "--source-hash",
            source_hash,
        ],
        outputs=[ctx.bundle / "findings.json", ctx.bundle / "annotations.json", ctx.issue_artifacts / "compiled_issue_index.json"],
    )
    append_step(ctx, step)


def build_derivatives(ctx: PipelineContext, args: argparse.Namespace, *, requested_scope: str, full_report: bool) -> None:
    view = effective_paper_view(ctx, args)
    render_mode = "issue-report-only" if view == "report-only" else "pdf-overlay"
    output_file = ctx.report_html if view == "report-only" else ctx.pdf_overlay_html
    source_artifact = current_source_artifact(ctx, args)
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
        str(source_artifact),
        "--source-hash",
        sha256_path(source_artifact) if source_artifact.exists() else "",
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
        str(output_file),
        "--coverage-out",
        str(ctx.bundle / "coverage.json"),
        "--manifest-out",
        str(ctx.bundle / "render_manifest.json"),
        "--pass-observations-out",
        str(ctx.bundle / "pass_observations.json"),
    ]
    layout_audit = usable_layout_audit_path(ctx)
    if layout_audit is not None:
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
    view = effective_paper_view(ctx, args)
    if args.paper_view == "pdf-overlay" and view == "report-only":
        ctx.warnings.append("PDF overlay requested but no compiled PDF is available; rendering issue-report-only HTML.")
    if view == "report-only":
        step = run_command(
            "render_issue_report",
            [
                sys.executable,
                script("render_issue_report_html.py"),
                "--findings",
                str(ctx.bundle / "findings.json"),
                "--coverage",
                str(ctx.bundle / "coverage.json"),
                "--output",
                str(ctx.report_html),
                "--title",
                f"Ariadne Issue Report: {ctx.entry_tex.stem}",
            ],
            outputs=[ctx.report_html],
            timeout=args.render_timeout,
        )
        append_step(ctx, step)
        return
    if view == "pdf-overlay":
        if ctx.pdf is None or not ctx.pdf.exists():
            ctx.steps.append(PipelineStep("render_final_report", "skipped", message="no PDF available for pdf-overlay render"))
            return
        step = run_command(
            "render_pdf_overlay_report",
            [
                sys.executable,
                script("render_pdf_overlay_html.py"),
                "--pdf",
                str(ctx.pdf),
                "--findings",
                str(ctx.bundle / "findings.json"),
                "--annotations",
                str(ctx.bundle / "annotations.json"),
                "--sentence-bbox",
                str(ctx.sentence_bbox),
                "--coverage",
                str(ctx.bundle / "coverage.json"),
                "--manifest",
                str(ctx.bundle / "render_manifest.json"),
                "--output",
                str(ctx.pdf_overlay_html),
                "--dpi",
                str(args.pdf_overlay_dpi),
                "--title",
                f"Ariadne PDF Review: {ctx.entry_tex.stem}",
            ],
            outputs=[ctx.pdf_overlay_html, ctx.pdf_overlay_html.parent / "paper.pdf", ctx.pdf_overlay_html.parent / "pdfjs"],
            timeout=args.render_timeout,
        )
        append_step(ctx, step)
        ctx.report_html = ctx.pdf_overlay_html
        return
    raise RuntimeError(f"Unsupported paper view: {args.paper_view}")


def build_sentence_bbox(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if effective_paper_view(ctx, args) != "pdf-overlay":
        ctx.steps.append(PipelineStep("build_sentence_bbox", "skipped", message="paper view is not pdf-overlay"))
        return
    if ctx.pdf is None or not ctx.pdf.exists():
        ctx.steps.append(PipelineStep("build_sentence_bbox", "skipped", message="no PDF available for bbox mapping"))
        return
    sidecar = review_units_pdf_text_path(ctx)
    if not force_rebuild(args, "bbox") and sentence_bbox_cache_valid(ctx):
        ctx.steps.append(
            PipelineStep(
                "build_sentence_bbox",
                "skipped",
                outputs=[str(ctx.sentence_bbox), str(sidecar)],
                message="cached bbox mapping matches current PDF and review units",
            )
        )
        return
    step = run_command(
        "build_sentence_bbox",
        [
            sys.executable,
            script("build_sentence_bbox.py"),
            "--pdf",
            str(ctx.pdf),
            "--review-units",
            str(ctx.review_units_jsonl),
            "--out",
            str(ctx.sentence_bbox),
            "--review-units-pdf-text-out",
            str(sidecar),
        ],
        outputs=[ctx.sentence_bbox, sidecar],
        timeout=args.bbox_timeout,
    )
    append_step(ctx, step)


def audit_sentence_bbox(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if effective_paper_view(ctx, args) != "pdf-overlay":
        ctx.steps.append(PipelineStep("audit_sentence_bbox", "skipped", message="paper view is not pdf-overlay"))
        return
    if not ctx.sentence_bbox.exists():
        ctx.steps.append(PipelineStep("audit_sentence_bbox", "skipped", message="sentence_bbox.json does not exist"))
        return
    sidecar = review_units_pdf_text_path(ctx)
    cmd = [
        sys.executable,
        script("audit_sentence_bbox.py"),
        "--review-units",
        str(ctx.review_units_jsonl),
        "--sentence-bbox",
        str(ctx.sentence_bbox),
        "--annotations",
        str(ctx.bundle / "annotations.json"),
        "--findings",
        str(ctx.bundle / "findings.json"),
        "--summary-out",
        str(ctx.bundle / "sentence_bbox_audit.json"),
        "--evidence-threshold",
        str(args.evidence_threshold),
    ]
    if sidecar.exists():
        cmd.extend(["--review-units-pdf-text", str(sidecar)])
    step = run_command(
        "audit_sentence_bbox",
        cmd,
        outputs=[ctx.bundle / "sentence_bbox_audit.json"],
    )
    append_step(ctx, step)


def audit_rendered_text_drift(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if effective_paper_view(ctx, args) != "pdf-overlay":
        ctx.steps.append(PipelineStep("audit_rendered_text_drift", "skipped", message="paper view is not pdf-overlay"))
        return
    sidecar = review_units_pdf_text_path(ctx)
    if not sidecar.exists():
        ctx.steps.append(PipelineStep("audit_rendered_text_drift", "skipped", message="review_units_pdf_text sidecar does not exist"))
        return
    step = run_command(
        "audit_rendered_text_drift",
        [
            sys.executable,
            script("audit_rendered_text_drift.py"),
            "--review-units",
            str(ctx.review_units_jsonl),
            "--review-units-pdf-text",
            str(sidecar),
            "--summary-out",
            str(ctx.bundle / "rendered_text_drift_audit.json"),
            "--warn-threshold",
            str(args.rendered_text_warn_threshold),
            "--error-threshold",
            str(args.rendered_text_error_threshold),
        ],
        outputs=[ctx.bundle / "rendered_text_drift_audit.json"],
    )
    append_step(ctx, step)


def export_annotated_pdf(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if not args.export_annotated_pdf:
        ctx.steps.append(PipelineStep("export_annotated_pdf", "skipped", message="annotated PDF export disabled"))
        return
    if effective_paper_view(ctx, args) != "pdf-overlay" or ctx.pdf is None or not ctx.sentence_bbox.exists():
        ctx.steps.append(PipelineStep("export_annotated_pdf", "skipped", message="pdf-overlay artifacts unavailable"))
        return
    out = ctx.bundle / f"{ctx.entry_tex.stem}.annotated.pdf"
    step = run_command(
        "export_annotated_pdf",
        [
            sys.executable,
            script("export_annotated_pdf.py"),
            "--pdf",
            str(ctx.pdf),
            "--findings",
            str(ctx.bundle / "findings.json"),
            "--annotations",
            str(ctx.bundle / "annotations.json"),
            "--sentence-bbox",
            str(ctx.sentence_bbox),
            "--out",
            str(out),
        ],
        outputs=[out],
        timeout=args.render_timeout,
    )
    append_step(ctx, step)


def run_audits(ctx: PipelineContext, args: argparse.Namespace) -> None:
    if args.skip_audit:
        ctx.steps.append(PipelineStep("audit", "skipped", message="audit disabled"))
        return
    html_cmd = [sys.executable, script("audit_html_report.py"), str(ctx.report_html)]
    html_step = run_command("audit_html_report", html_cmd)
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
    ]
    claims = ctx.bundle / "claims.json"
    if claims.exists():
        cmd.extend(["--claims", str(claims)])
    layout_audit = usable_layout_audit_path(ctx)
    if layout_audit is not None:
        cmd.extend(["--layout-audit", str(layout_audit)])
    review_step = run_command("audit_review_artifacts", cmd)
    append_step(ctx, review_step)


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    ctx = initialize_context(args)
    ctx.bundle.mkdir(parents=True, exist_ok=True)
    ctx.issue_artifacts.mkdir(parents=True, exist_ok=True)
    try:
        build_pdf_if_needed(ctx, args)
        refresh_stale_layout_artifacts(ctx, args)
        prepare_layout_audit_for_review_units(ctx, args)
        extract_units(ctx, args)
        maybe_build_prose_shards(ctx, args)
        run_specialists(ctx, args)
        run_specialist_agent(ctx, args)
        run_vision_figure_agent(ctx, args)
        remap_legacy_issue_anchors(ctx, args)
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
        build_sentence_bbox(ctx, args)
        compile_artifacts(ctx, args)
        build_derivatives(ctx, args, requested_scope=requested_scope, full_report=args.full_report)
        audit_sentence_bbox(ctx, args)
        audit_rendered_text_drift(ctx, args)
        render_final(ctx, args)
        export_annotated_pdf(ctx, args)
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
    parser.add_argument("input", type=Path, help="LaTeX project directory, entry .tex file, or PDF-only input")
    parser.add_argument("--bundle", type=Path, help="Output artifact bundle directory")
    parser.add_argument("--pdf", type=Path, help="Existing compiled PDF")
    parser.add_argument("--report-html", type=Path, help="Final report HTML path")
    parser.add_argument(
        "--review-units-source",
        choices=("tex", "pdf"),
        default="tex",
        help="Build Phase A review units from TeX, or from PDF text when only a PDF is available",
    )
    parser.add_argument("--paper-view", choices=("pdf-overlay", "report-only"), default="pdf-overlay", help="Final report renderer")
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
    parser.add_argument(
        "--remap-legacy-issue-anchors",
        action="store_true",
        help="Remap existing prose issue anchors onto current TeX-derived review units before compile.",
    )
    parser.add_argument("--legacy-anchor-remap-threshold", type=float, default=0.80)
    parser.add_argument("--prose-agent-cmd", help="Optional external agent command for run_prose_agent.py")
    parser.add_argument("--prose-phase", default="all", choices=("phase_a", "phase_b", "all"), help="Prose phase(s) to run when --prose-agent-cmd is provided")
    parser.add_argument("--prose-max-iterations", type=int, default=200, help="Maximum Phase A agent iterations")
    parser.add_argument("--prose-agent-timeout", type=int, default=1800, help="Timeout per prose agent command call")
    parser.add_argument("--prose-dry-run", action="store_true", help="Build prose packets without invoking --prose-agent-cmd")
    parser.add_argument("--prose-shard-threshold", type=int, default=40_000, help="Build Phase A shard packets when review_units token estimate exceeds this value")
    parser.add_argument("--prose-shard-size", type=int, default=35_000, help="Approximate max tokens per Phase A shard packet")
    parser.add_argument("--skip-pdf-build", action="store_true", help="Do not attempt to build a missing PDF")
    parser.add_argument("--prepare-only", action="store_true", help="Stop after deterministic prep and Phase A resume packet")
    parser.add_argument("--allow-partial-compile", action="store_true", help="Compile available issues even if Prose Phase A/B is incomplete")
    parser.add_argument("--full-report", action="store_true", help="Render global Major/Blocker paper-level findings after the PDF overlay")
    parser.add_argument("--skip-final-render", action="store_true", help="Compile artifacts but skip final HTML rendering")
    parser.add_argument("--skip-audit", action="store_true", help="Skip final audits")
    parser.add_argument("--pdf-overlay-dpi", type=int, default=150, help="Deprecated; PDF overlay now renders through PDF.js")
    parser.add_argument("--bbox-timeout", type=int, default=300)
    parser.add_argument("--evidence-threshold", type=float, default=0.80)
    parser.add_argument("--rendered-text-warn-threshold", type=float, default=0.72)
    parser.add_argument("--rendered-text-error-threshold", type=float, default=0.45)
    parser.add_argument("--force-rebuild", action="append", choices=("units", "bbox", "all"), default=[], help="Ignore cached artifacts for the selected stage")
    parser.add_argument(
        "--export-annotated-pdf",
        dest="export_annotated_pdf",
        action="store_true",
        default=True,
        help="Export native PDF annotations when PyMuPDF is available (default)",
    )
    parser.add_argument("--no-export-annotated-pdf", dest="export_annotated_pdf", action="store_false", help="Skip native annotated PDF export")
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
