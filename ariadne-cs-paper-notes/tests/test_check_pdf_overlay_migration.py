#!/usr/bin/env python3
"""Regression tests for check_pdf_overlay_migration.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_pdf_overlay_migration.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_pdf_overlay_migration", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_pdf_overlay_migration")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_full_review_markers(bundle: Path) -> None:
    write_json(
        bundle / "phase_a_resume_status.json",
        {"coverage": {"phase_a_complete": True, "sentence_review_receipt_complete": True}},
    )
    write_json(bundle / "argument_map.json", {"nodes": []})
    write_json(bundle / "claims.json", {"claims": []})
    write_json(bundle / "salvageable_core.json", {"summary": "ok"})
    whole_paper = bundle / "issue_artifacts" / "whole_paper_findings.jsonl"
    whole_paper.parent.mkdir(parents=True, exist_ok=True)
    whole_paper.write_text('{"id":"W1"}\n', encoding="utf-8")


def test_migration_bundle_status_requires_pdf_overlay_and_clean_audits() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        write_json(bundle / "render_manifest.json", {"pdf_overlay": {"mode": "pdf-overlay"}})
        write_json(bundle / "sentence_bbox_audit.json", {"mapped_annotations": 9, "unmappable_annotations": 1, "errors": 0})
        write_json(bundle / "rendered_text_drift_audit.json", {"errors": 0})
        write_json(bundle / "pipeline_status.json", {"state": "complete"})
        write_json(bundle / "findings.json", {"findings": [{"id": "F1", "source_domain": "prose"}]})
        write_json(bundle / "annotations.json", {"annotations": [{"issue_id": "F1", "sentence_id": "s1"}]})
        write_full_review_markers(bundle)

        status = module.bundle_status(bundle)

    if not status["passed"] or status["mapping_rate"] != 0.9:
        raise AssertionError(f"Expected clean migration bundle, got {status}")


def test_migration_bundle_status_rejects_smoke_without_full_review() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        write_json(bundle / "render_manifest.json", {"pdf_overlay": {"mode": "pdf-overlay"}})
        write_json(bundle / "sentence_bbox_audit.json", {"mapped_annotations": 1, "unmappable_annotations": 0, "errors": 0})
        write_json(bundle / "rendered_text_drift_audit.json", {"errors": 0})
        write_json(bundle / "pipeline_status.json", {"state": "partial"})
        write_json(bundle / "findings.json", {"findings": [{"id": "F1", "source_domain": "layout"}]})
        write_json(bundle / "annotations.json", {"annotations": [{"issue_id": "F1", "sentence_id": "s1"}]})

        status = module.bundle_status(bundle)
        preview_status = module.bundle_status(bundle, require_full_review=False)

    if status["passed"] or not any("Phase A" in error for error in status["errors"]):
        raise AssertionError(f"Expected full-review migration failure, got {status}")
    if not preview_status["passed"]:
        raise AssertionError(f"Expected deterministic preview to pass full-review checks, got {preview_status}")


if __name__ == "__main__":
    test_migration_bundle_status_requires_pdf_overlay_and_clean_audits()
    test_migration_bundle_status_rejects_smoke_without_full_review()
    print("check_pdf_overlay_migration regression tests passed")
