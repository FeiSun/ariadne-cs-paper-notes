#!/usr/bin/env python3
"""Regression tests for deterministic P1 specialist runner."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_p1_specialists.py"
AUDIT_SCRIPT = ROOT / "scripts" / "audit_review_artifacts.py"


def load_module(script: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_runner_uses_existing_raw_audits_and_builds_issue_artifacts() -> None:
    module = load_module(SCRIPT, "run_p1_specialists")
    audit = load_module(AUDIT_SCRIPT, "audit_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        bundle.mkdir()
        write_json(
            bundle / "layout_audit.json",
            {
                "pages_checked": [1],
                "observations": [
                    {
                        "observation_id": "layout-p001-001",
                        "page": 1,
                        "issue_type": "edge_text",
                        "severity": "polish",
                        "observation": "Text near edge.",
                        "evidence": "Line bbox touches margin.",
                        "needs_main_review": True,
                    }
                ],
            },
        )
        write_json(bundle / "numeric_audit.json", {"signal_count": 0, "signals": []})
        write_json(
            bundle / "references_audit.json",
            {
                "reference_count_estimate": {"bibtex_entries_in_bib_files": 2},
                "findings": [
                    {
                        "severity": "high",
                        "title": "Hidden DOI fields",
                        "evidence": "Found xdoi fields.",
                        "recommendation": "Use doi fields.",
                        "confidence": 0.95,
                        "observation_id": "reference-hidden-metadata-fields",
                    }
                ],
            },
        )
        write_json(
            bundle / "source_hygiene_audit.json",
            {
                "coverage": {"identity_items": 1},
                "observations": [
                    {
                        "observation_id": "source-001",
                        "issue_type": "anonymity",
                        "severity": "high",
                        "title": "Identity/anonymity signals are visible in the source",
                        "evidence": "author command: Jane Doe",
                        "recommendation": "Anonymize author identity.",
                        "confidence": 0.94,
                    }
                ],
            },
        )
        write_json(
            bundle / "polish_audit.json",
            {
                "coverage": {"words_checked": 120, "signals_checked": 1},
                "observations": [
                    {
                        "observation_id": "polish-001",
                        "issue_type": "hyphenation_consistency",
                        "severity": "low",
                        "title": "Hyphenation variants are used for the same term family",
                        "evidence": "fine-tuning: fine tuning=1, fine-tuning=2",
                        "recommendation": "Choose one spelling.",
                        "confidence": 0.82,
                    }
                ],
            },
        )
        write_json(
            bundle / "symbol_audit.json",
            {
                "coverage": {"display_equations": 1, "signals_checked": 1},
                "observations": [
                    {
                        "observation_id": "symbol-001",
                        "issue_type": "macro_redefinition",
                        "severity": "medium",
                        "title": "Macro \\risk has multiple distinct expansions",
                        "evidence": "'R'; '\\mathcal{R}'",
                        "recommendation": "Use one macro definition or rename distinct concepts.",
                        "confidence": 0.9,
                    }
                ],
            },
        )
        write_json(
            bundle / "figure_caption_audit.json",
            {
                "coverage": {"floats": 1, "captions": 0, "signals_checked": 1},
                "observations": [
                    {
                        "observation_id": "figure-caption-001",
                        "issue_type": "missing_caption",
                        "severity": "medium",
                        "title": "Figure/table floats are missing captions",
                        "evidence": "figure 1 (fig:no-caption)",
                        "recommendation": "Give every evidence-bearing figure/table a caption.",
                        "confidence": 0.9,
                    }
                ],
            },
        )

        summary = module.run_specialists(
            bundle=bundle,
            tex=None,
            pdf=None,
            aux=None,
            bbl=None,
            domains=["layout", "numeric", "reference", "source_hygiene", "polish", "symbol", "figure_caption"],
            force=False,
            pages="all",
        )
        errors, warnings, ids = audit.audit_issue_artifacts(bundle / "issue_artifacts")

    if errors or warnings:
        raise AssertionError(f"Generated issue artifacts should audit cleanly, errors={errors}, warnings={warnings}")
    if {
        "layout:L1",
        "reference:reference-hidden-metadata-fields",
        "source_hygiene:source-001",
        "polish:polish-001",
        "symbol:symbol-001",
        "figure_caption:figure-caption-001",
    } - ids:
        raise AssertionError(f"Missing expected issue ids: {ids}")
    statuses = {item["domain"]: item["status"] for item in summary["results"]}
    if statuses != {
        "layout": "completed",
        "numeric": "skipped",
        "reference": "completed",
        "source_hygiene": "completed",
        "polish": "completed",
        "symbol": "completed",
        "figure_caption": "completed",
    }:
        raise AssertionError(f"Unexpected runner statuses: {statuses}")


def test_runner_writes_skipped_stubs_without_inputs() -> None:
    module = load_module(SCRIPT, "run_p1_specialists")
    audit = load_module(AUDIT_SCRIPT, "audit_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        summary = module.run_specialists(
            bundle=bundle,
            tex=None,
            pdf=None,
            aux=None,
            bbl=None,
            domains=["layout", "numeric", "reference", "source_hygiene", "polish", "symbol", "figure_caption"],
            force=False,
            pages="all",
        )
        errors, warnings, _ids = audit.audit_issue_artifacts(bundle / "issue_artifacts")

    if errors or warnings:
        raise AssertionError(f"Skipped stubs should audit cleanly, errors={errors}, warnings={warnings}")
    if any(item["status"] != "skipped" for item in summary["results"]):
        raise AssertionError(f"Expected all skipped, got {summary}")


def test_runner_refreshes_stale_layout_audit_for_current_pdf() -> None:
    module = load_module(SCRIPT, "run_p1_specialists")
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bundle = root / "bundle"
        pdf = root / "main.pdf"
        pdf.write_bytes(b"%PDF-1.4\ncurrent")
        write_json(
            bundle / "layout_audit.json",
            {
                "pdf": str(pdf),
                "pdf_hash": "sha256:00000000",
                "pages_total": 1,
                "pages_checked": [1],
                "observations": [],
            },
        )
        commands: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            return "/usr/bin/pdftotext-test" if name == "pdftotext" else None

        def fake_run_command(cmd: list[str], *, cwd=None, timeout=180):  # noqa: ARG001
            commands.append(cmd)
            if Path(cmd[1]).name == "check_page_layout.py":
                out = Path(cmd[cmd.index("--out") + 1])
                write_json(
                    out,
                    {
                        "tool": "scripts/check_page_layout.py",
                        "tool_version": "1",
                        "script_hash": "sha256:11111111",
                        "pdf": str(pdf),
                        "pdf_hash": module.sha256_path(pdf),
                        "pages_total": 1,
                        "pages_checked": [1],
                        "page_summaries": [],
                        "observations": [],
                    },
                )
            elif Path(cmd[1]).name == "build_specialist_issues.py":
                out = Path(cmd[cmd.index("--out") + 1])
                raw = bundle / "layout_audit.json"
                write_json(
                    out,
                    {
                        "artifact_type": "ariadne_issue_artifact",
                        "schema_version": 1,
                        "domain": "layout",
                        "context_policy": "model_readable_issue_only",
                        "status": "skipped",
                        "source_artifacts": [
                            {
                                "path": str(raw),
                                "hash": module.sha256_path(raw),
                                "context_policy": "tool_output_hash_only",
                            }
                        ],
                        "coverage": {"checked": 1, "issues": 0, "skipped": 1},
                        "issues": [],
                    },
                )

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        original_run_command = module.run_command
        original_which = module.shutil.which
        module.run_command = fake_run_command
        module.shutil.which = fake_which
        try:
            summary = module.run_specialists(
                bundle=bundle,
                tex=None,
                pdf=pdf,
                aux=None,
                bbl=None,
                domains=["layout"],
                force=False,
                pages="all",
            )
        finally:
            module.run_command = original_run_command
            module.shutil.which = original_which
        refreshed = json.loads((bundle / "layout_audit.json").read_text(encoding="utf-8"))
        expected_pdf_hash = module.sha256_path(pdf)

    command_names = [Path(command[1]).name for command in commands]
    if command_names != ["check_page_layout.py", "build_specialist_issues.py"]:
        raise AssertionError(f"Expected stale layout audit to refresh before issue build, got {command_names}")
    if refreshed["pdf_hash"] != expected_pdf_hash:
        raise AssertionError(f"Refreshed layout audit should bind to current PDF, got {refreshed}")
    if summary["results"][0]["status"] != "skipped":
        raise AssertionError(f"Expected refreshed empty layout issue artifact to be skipped, got {summary}")


def test_runner_passes_pdf_to_figure_caption_audit() -> None:
    module = load_module(SCRIPT, "run_p1_specialists")
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bundle = root / "bundle"
        tex = root / "main.tex"
        pdf = root / "main.pdf"
        tex.write_text(r"\documentclass{article}\begin{document}\caption{Example caption}\end{document}", encoding="utf-8")
        pdf.write_bytes(b"%PDF-1.4\n")

        commands: list[list[str]] = []

        def fake_run_command(cmd: list[str], timeout: int = 180):  # noqa: ARG001
            commands.append(cmd)
            raw = bundle / "figure_caption_audit.json"
            write_json(
                raw,
                {
                    "coverage": {"floats": 0, "captions": 1, "rendered_pages_checked": 1},
                    "observations": [],
                },
            )

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        module.run_command = fake_run_command
        original_run_builder = module.run_builder

        def fake_run_builder(domain: str, raw_audit: Path, out: Path):
            payload = {
                "artifact_type": "ariadne_issue_artifact",
                "schema_version": 1,
                "domain": domain,
                "context_policy": "model_readable_issue_only",
                "status": "skipped",
                "source_artifacts": [],
                "coverage": {"checked": 1, "issues": 0, "skipped": 1},
                "issues": [],
            }
            write_json(out, payload)
            return {
                "domain": domain,
                "status": "skipped",
                "raw_audit": str(raw_audit),
                "issues": str(out),
                "issue_count": 0,
                "checked": 1,
            }

        module.run_builder = fake_run_builder
        summary = module.run_specialists(
            bundle=bundle,
            tex=tex,
            pdf=pdf,
            aux=None,
            bbl=None,
            domains=["figure_caption"],
            force=True,
            pages="1",
            pdftoppm="/usr/bin/pdftoppm-test",
        )
        module.run_builder = original_run_builder

    if not commands:
        raise AssertionError("Expected runner to invoke check_figure_caption")
    command = commands[0]
    if "--pdf" not in command or str(pdf) not in command or "--pages" not in command or "1" not in command:
        raise AssertionError(f"Runner did not pass PDF/page options to figure caption audit: {command}")
    if "--pdftoppm" not in command or "/usr/bin/pdftoppm-test" not in command:
        raise AssertionError(f"Runner did not pass pdftoppm option to figure caption audit: {command}")
    if summary["results"][0]["status"] != "skipped":
        raise AssertionError(f"Empty figure/caption issue artifact should be skipped, got {summary}")


if __name__ == "__main__":
    test_runner_uses_existing_raw_audits_and_builds_issue_artifacts()
    test_runner_writes_skipped_stubs_without_inputs()
    test_runner_refreshes_stale_layout_audit_for_current_pdf()
    test_runner_passes_pdf_to_figure_caption_audit()
    print("run_p1_specialists regression tests passed")
