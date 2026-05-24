#!/usr/bin/env python3
"""Regression tests for specialist issue artifact reducers."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_specialist_issues.py"
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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_issue_artifact_audits(payload: dict[str, object], filename: str) -> None:
    audit = load_module(AUDIT_SCRIPT, "audit_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        issues_dir = Path(tempdir)
        write_json(issues_dir / filename, payload)
        errors, warnings, _ids = audit.audit_issue_artifacts(issues_dir)
    if errors or warnings:
        raise AssertionError(f"Issue artifact should pass audit, errors={errors}, warnings={warnings}")


def test_reference_audit_reduces_to_issue_artifact() -> None:
    module = load_module(SCRIPT, "build_specialist_issues")
    with tempfile.TemporaryDirectory() as tempdir:
        raw = Path(tempdir) / "references_audit.json"
        write_json(
            raw,
            {
                "reference_count_estimate": {"bibtex_entries_in_bib_files": 2, "rendered_references_in_bbl": 1},
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
        payload = module.build_reference(raw)
    if payload["domain"] != "reference" or payload["coverage"]["issues"] != 1:
        raise AssertionError(f"Unexpected reference issue payload: {payload}")
    assert_issue_artifact_audits(payload, "reference_issues.json")


def test_numeric_audit_without_signals_is_skipped() -> None:
    module = load_module(SCRIPT, "build_specialist_issues")
    with tempfile.TemporaryDirectory() as tempdir:
        raw = Path(tempdir) / "numeric_audit.json"
        write_json(raw, {"signal_count": 0, "signals": []})
        payload = module.build_numeric(raw)
    if payload["status"] != "skipped" or payload["issues"]:
        raise AssertionError(f"Expected numeric skipped stub, got {payload}")
    assert_issue_artifact_audits(payload, "numeric_issues.json")


def test_layout_needs_main_review_becomes_issue() -> None:
    module = load_module(SCRIPT, "build_specialist_issues")
    with tempfile.TemporaryDirectory() as tempdir:
        raw = Path(tempdir) / "layout_audit.json"
        write_json(
            raw,
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
        payload = module.build_layout(raw)
    if payload["status"] != "completed" or payload["coverage"]["issues"] != 1:
        raise AssertionError(f"Expected one layout issue, got {payload}")
    assert_issue_artifact_audits(payload, "layout_issues.json")


def test_source_hygiene_audit_reduces_to_issue_artifact() -> None:
    module = load_module(SCRIPT, "build_specialist_issues")
    with tempfile.TemporaryDirectory() as tempdir:
        raw = Path(tempdir) / "source_hygiene_audit.json"
        write_json(
            raw,
            {
                "coverage": {"identity_items": 2, "todos": 1},
                "observations": [
                    {
                        "observation_id": "source-001",
                        "issue_type": "anonymity",
                        "severity": "high",
                        "title": "Identity/anonymity signals are visible in the source",
                        "evidence": "email: jane@example.com; author command: Jane Doe",
                        "recommendation": "Anonymize identity signals.",
                        "confidence": 0.94,
                    }
                ],
            },
        )
        payload = module.build_source_hygiene(raw)
    if payload["domain"] != "source_hygiene" or payload["coverage"]["issues"] != 1:
        raise AssertionError(f"Unexpected source hygiene payload: {payload}")
    assert_issue_artifact_audits(payload, "source_hygiene_issues.json")


def test_polish_audit_reduces_to_issue_artifact() -> None:
    module = load_module(SCRIPT, "build_specialist_issues")
    with tempfile.TemporaryDirectory() as tempdir:
        raw = Path(tempdir) / "polish_audit.json"
        write_json(
            raw,
            {
                "coverage": {"words_checked": 120, "signals_checked": 2},
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
        payload = module.build_polish(raw)
    if payload["domain"] != "polish" or payload["coverage"]["issues"] != 1:
        raise AssertionError(f"Unexpected polish payload: {payload}")
    assert_issue_artifact_audits(payload, "polish_issues.json")


def test_symbol_audit_reduces_to_issue_artifact() -> None:
    module = load_module(SCRIPT, "build_specialist_issues")
    with tempfile.TemporaryDirectory() as tempdir:
        raw = Path(tempdir) / "symbol_audit.json"
        write_json(
            raw,
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
        payload = module.build_symbol(raw)
    if payload["domain"] != "symbol" or payload["coverage"]["issues"] != 1:
        raise AssertionError(f"Unexpected symbol payload: {payload}")
    assert_issue_artifact_audits(payload, "symbol_issues.json")


def test_figure_caption_audit_reduces_to_issue_artifact() -> None:
    module = load_module(SCRIPT, "build_specialist_issues")
    with tempfile.TemporaryDirectory() as tempdir:
        raw = Path(tempdir) / "figure_caption_audit.json"
        write_json(
            raw,
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
        payload = module.build_figure_caption(raw)
    if payload["domain"] != "figure_caption" or payload["coverage"]["issues"] != 1:
        raise AssertionError(f"Unexpected figure/caption payload: {payload}")
    assert_issue_artifact_audits(payload, "figure_caption_issues.json")


if __name__ == "__main__":
    test_reference_audit_reduces_to_issue_artifact()
    test_numeric_audit_without_signals_is_skipped()
    test_layout_needs_main_review_becomes_issue()
    test_source_hygiene_audit_reduces_to_issue_artifact()
    test_polish_audit_reduces_to_issue_artifact()
    test_symbol_audit_reduces_to_issue_artifact()
    test_figure_caption_audit_reduces_to_issue_artifact()
    print("build_specialist_issues regression tests passed")
