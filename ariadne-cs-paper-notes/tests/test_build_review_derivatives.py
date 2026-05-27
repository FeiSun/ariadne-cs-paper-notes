#!/usr/bin/env python3
"""Regression tests for deterministic review-derivative artifacts."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_review_derivatives.py"
AUDIT_SCRIPT = ROOT / "scripts" / "audit_review_artifacts.py"
FIXTURES = ROOT / "tests" / "fixtures"
ARTIFACTS = FIXTURES / "review_artifacts"
HTML = FIXTURES / "expected_html_report.html"
SOURCE = FIXTURES / "source_paper_reader.html"


def load_module(script: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_derivative_artifacts_satisfy_existing_audit_contract() -> None:
    module = load_module(SCRIPT, "build_review_derivatives")
    audit = load_module(AUDIT_SCRIPT, "audit_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        payloads = module.build_all(
            findings_path=ARTIFACTS / "findings.json",
            annotations_path=ARTIFACTS / "annotations.json",
            issues_dir=None,
            layout_audit_path=ARTIFACTS / "layout_audit.json",
            source_artifact=SOURCE,
            source_hash="",
            requested_scope="fixture derived bundle",
            output_files=[str(HTML)],
            source_fidelity="fixture",
            html_source="manual-fixture",
            visible_scope="",
        )
        coverage = root / "coverage.json"
        manifest = root / "render_manifest.json"
        pass_observations = root / "pass_observations.json"
        module.write_json(coverage, payloads["coverage"])
        module.write_json(manifest, payloads["render_manifest"])
        module.write_json(pass_observations, payloads["pass_observations"])
        errors, warnings = audit.audit_artifacts(
            ARTIFACTS / "findings.json",
            ARTIFACTS / "claims.json",
            ARTIFACTS / "numeric_audit.json",
            coverage,
            manifest,
            pass_observations,
            HTML,
            SOURCE,
            ARTIFACTS / "annotations.json",
            ARTIFACTS,
            ARTIFACTS / "layout_audit.json",
        )
    allowed_warnings = {
        "legacy bundle: issue_artifacts/ absent; recommend migration",
        "render manifest paper_reader source integrity comparison was skipped",
    }
    unexpected = [warning for warning in warnings if warning not in allowed_warnings]
    if errors or unexpected:
        raise AssertionError(f"Derived artifacts should audit cleanly, errors={errors}, warnings={warnings}")


def test_derivatives_cli_writes_all_outputs() -> None:
    module = load_module(SCRIPT, "build_review_derivatives")
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        coverage = root / "coverage.json"
        manifest = root / "render_manifest.json"
        pass_observations = root / "pass_observations.json"
        status = module.main(
            [
                "--findings",
                str(ARTIFACTS / "findings.json"),
                "--annotations",
                str(ARTIFACTS / "annotations.json"),
                "--layout-audit",
                str(ARTIFACTS / "layout_audit.json"),
                "--source-artifact",
                str(SOURCE),
                "--requested-scope",
                "fixture cli",
                "--output-file",
                str(HTML),
                "--source-fidelity",
                "fixture",
                "--html-source",
                "manual-fixture",
                "--coverage-out",
                str(coverage),
                "--manifest-out",
                str(manifest),
                "--pass-observations-out",
                str(pass_observations),
            ]
        )
        if status != 0:
            raise AssertionError(f"build_review_derivatives CLI returned {status}")
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in (coverage, manifest, pass_observations)]
    if any(payload.get("generated_by") != "scripts/build_review_derivatives.py" for payload in payloads):
        raise AssertionError(f"Missing generated_by provenance: {payloads}")


def test_derivatives_manifest_can_match_paper_reader_only_render() -> None:
    module = load_module(SCRIPT, "build_review_derivatives")
    payloads = module.build_all(
        findings_path=ARTIFACTS / "findings.json",
        annotations_path=ARTIFACTS / "annotations.json",
        issues_dir=None,
        layout_audit_path=ARTIFACTS / "layout_audit.json",
        source_artifact=SOURCE,
        source_hash="",
        requested_scope="fixture paper-reader overlay",
        output_files=[str(HTML)],
        source_fidelity="fixture",
        html_source="manual-fixture",
        visible_scope="",
        render_mode="paper-reader-only",
    )
    sections = [
        section["id"]
        for section in payloads["render_manifest"].get("sections", [])
        if section.get("status") == "rendered"
    ]
    if sections != ["paper-reader", "coverage-receipt"]:
        raise AssertionError(f"Unexpected paper-reader-only manifest sections: {sections}")


def test_derivatives_manifest_can_match_global_findings_render() -> None:
    module = load_module(SCRIPT, "build_review_derivatives")
    payloads = module.build_all(
        findings_path=ARTIFACTS / "findings.json",
        annotations_path=ARTIFACTS / "annotations.json",
        issues_dir=None,
        layout_audit_path=ARTIFACTS / "layout_audit.json",
        source_artifact=SOURCE,
        source_hash="",
        requested_scope="fixture paper-reader overlay plus global findings",
        output_files=[str(HTML)],
        source_fidelity="fixture",
        html_source="manual-fixture",
        visible_scope="",
        render_mode="paper-reader-with-global-findings",
    )
    sections = [
        section["id"]
        for section in payloads["render_manifest"].get("sections", [])
        if section.get("status") == "rendered"
    ]
    if sections != ["paper-reader", "global-findings", "coverage-receipt"]:
        raise AssertionError(f"Unexpected global-findings manifest sections: {sections}")


def test_derivatives_use_phase_artifacts_for_coverage_and_defer_artifact_only_findings() -> None:
    module = load_module(SCRIPT, "build_review_derivatives")
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        findings = root / "findings.json"
        annotations = root / "annotations.json"
        phase_a = root / "phase_a_resume_status.json"
        phase_b = root / "phase_b_context.json"
        findings.write_text(
            json.dumps(
                {
                    "findings": [
                        {
                            "id": "F1",
                            "severity": "Minor",
                            "issue_type": "prose",
                            "render_visibility": "student_visible",
                            "source_issue_ids": ["prose:P1"],
                        },
                        {
                            "id": "F2",
                            "severity": "Minor",
                            "issue_type": "source_hygiene",
                            "render_visibility": "artifact_only",
                            "source_issue_ids": ["source_hygiene:S1"],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        annotations.write_text(
            json.dumps(
                {
                    "annotations": [
                        {"issue_id": "F1", "target_level": "sentence", "sentence_id": "s1"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        phase_a.write_text(
            json.dumps(
                {
                    "coverage": {
                        "sections_total": 1,
                        "sections_completed": 1,
                        "sections_pending": 0,
                        "paragraphs_total": 1,
                        "paragraphs_reviewed": 1,
                        "sentences_total": 4,
                        "sentences_reviewed": 4,
                        "sentence_review_receipt_complete": True,
                        "cold_skim_present": True,
                        "phase_a_complete": True,
                    }
                }
            ),
            encoding="utf-8",
        )
        phase_b.write_text(json.dumps({"coverage": {"sections_summarized": 1}}), encoding="utf-8")
        payloads = module.build_all(
            findings_path=findings,
            annotations_path=annotations,
            issues_dir=None,
            layout_audit_path=None,
            source_artifact=SOURCE,
            source_hash="",
            requested_scope="full compiled Ariadne review",
            output_files=[str(HTML)],
            source_fidelity="fixture",
            html_source="manual-fixture",
            visible_scope="",
            phase_a_status_path=phase_a,
            phase_b_context_path=phase_b,
        )
    units = {row["unit"]: row for row in payloads["coverage"]["units"]}
    passes = {row["pass"]: row["status"] for row in payloads["coverage"]["reader_journey_passes"]}
    if units["Sentences"]["total"] != 4 or units["Sentences"]["reviewed"] != 4:
        raise AssertionError(f"Expected sentence coverage from Phase A status, got {units}")
    if passes["Pass 1"] != "done" or passes["Pass 2"] != "done" or passes["Pass 4"] != "done":
        raise AssertionError(f"Expected concrete pass status from artifacts, got {passes}")
    if passes["Pass 6"] != "pending":
        raise AssertionError(f"Derivative builder should not pre-certify audit pass, got {passes}")
    if payloads["render_manifest"]["deferred_findings"] != ["F2"]:
        raise AssertionError(f"Artifact-only finding should be deferred for HTML audit: {payloads['render_manifest']}")
    if payloads["render_manifest"].get("deferred_findings_with_reason") != [{"id": "F2", "reason": "artifact_only"}]:
        raise AssertionError(f"Deferred findings should include reasons: {payloads['render_manifest']}")


if __name__ == "__main__":
    test_derivative_artifacts_satisfy_existing_audit_contract()
    test_derivatives_cli_writes_all_outputs()
    test_derivatives_manifest_can_match_paper_reader_only_render()
    test_derivatives_manifest_can_match_global_findings_render()
    test_derivatives_use_phase_artifacts_for_coverage_and_defer_artifact_only_findings()
    print("build_review_derivatives regression tests passed")
