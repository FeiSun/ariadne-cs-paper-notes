#!/usr/bin/env python3
"""Regression tests for structured Ariadne review artifact auditing."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_review_artifacts.py"
FIXTURES = ROOT / "tests" / "fixtures"
ARTIFACTS = FIXTURES / "review_artifacts"
HTML = FIXTURES / "expected_html_report.html"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_review_artifacts", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load audit_review_artifacts module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(payload: object) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    with tmp:
        json.dump(payload, tmp)
    return Path(tmp.name)


def valid_finding(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "F1",
        "severity": "Blocker",
        "location": "Abstract",
        "diagnosis": "Abstract missing.",
        "reader_friction": "Reader cannot recover the paper story.",
        "writing_principle": "first-page reader test",
        "next_draft_task": "Add problem/gap/idea/evidence/boundary.",
        "evidence_basis": "rendered PDF",
        "verification_method": "PDF visual pass",
        "confidence": "high",
        "severity_rationale": "First-page recoverability fails.",
        "downgrade_condition": "Complete abstract added.",
    }
    payload.update(overrides)
    return payload


def test_review_artifact_fixture_passes_contract() -> None:
    module = load_module()
    errors, warnings = module.audit_artifacts(
        ARTIFACTS / "findings.json",
        ARTIFACTS / "claims.json",
        ARTIFACTS / "numeric_audit.json",
        ARTIFACTS / "coverage.json",
        ARTIFACTS / "render_manifest.json",
        ARTIFACTS / "pass_observations.json",
        HTML,
    )
    if errors or warnings:
        raise AssertionError(f"Structured artifact audit failed.\nErrors: {errors}\nWarnings: {warnings}")


def test_bundle_cli_paths_pass_contract() -> None:
    module = load_module()
    errors, warnings = module.audit_artifacts(
        ARTIFACTS / "findings.json",
        ARTIFACTS / "claims.json",
        ARTIFACTS / "numeric_audit.json",
        ARTIFACTS / "coverage.json",
        ARTIFACTS / "render_manifest.json",
        ARTIFACTS / "pass_observations.json",
        HTML,
    )
    if errors or warnings:
        raise AssertionError(f"Bundle-equivalent artifact audit failed.\nErrors: {errors}\nWarnings: {warnings}")


def test_high_risk_finding_requires_downgrade_condition() -> None:
    module = load_module()
    finding = valid_finding()
    del finding["downgrade_condition"]
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("downgrade_condition" in error for error in errors):
        raise AssertionError(f"Expected downgrade_condition error, got {errors}")


def test_json_finding_must_render_or_be_deferred() -> None:
    module = load_module()
    path = write_json({"findings": [valid_finding(id="F99")]})
    try:
        errors, _ = module.audit_artifacts(path, html_path=HTML)
    finally:
        path.unlink(missing_ok=True)
    if not any("not rendered in HTML" in error for error in errors):
        raise AssertionError(f"Expected render/deferred error, got {errors}")


def test_skipped_coverage_requires_pending_marker() -> None:
    module = load_module()
    path = write_json({"units": [{"unit": "Pages", "total": 10, "reviewed": 8, "with_issues": 2, "clean": 6, "skipped": 2}]})
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", coverage_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("skipped > 0 without pending_in" in error for error in errors):
        raise AssertionError(f"Expected skipped coverage error, got {errors}")


def test_numerical_finding_requires_aggregation_caveat() -> None:
    module = load_module()
    finding = valid_finding(
        id="F2",
        reported_value="95.77",
        visible_computed_value="95.52",
        delta="+0.25",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("aggregation_caveat" in error for error in errors):
        raise AssertionError(f"Expected aggregation_caveat error, got {errors}")


def test_numerical_finding_must_be_blocker() -> None:
    module = load_module()
    finding = valid_finding(
        id="F2",
        severity="Minor",
        diagnosis="Table 1 Method A Score X：按可见三列复算 95.52，不是表中的 95.77；delta +0.25。",
        reported_value="95.77",
        visible_computed_value="95.52",
        delta="+0.25",
        aggregation_caveat="visible arithmetic mean only",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("must use severity `Blocker`" in error for error in errors):
        raise AssertionError(f"Expected numerical severity error, got {errors}")


def test_numerical_finding_must_include_concrete_values_in_diagnosis() -> None:
    module = load_module()
    finding = valid_finding(
        id="F2",
        diagnosis="Score X 与可见均值有偏差，需复查。",
        reported_value="95.77",
        visible_computed_value="95.52",
        delta="+0.25",
        aggregation_caveat="visible arithmetic mean only",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("reported_value" in error or "vague language" in error for error in errors):
        raise AssertionError(f"Expected concrete numeric diagnosis error, got {errors}")


def test_numerical_finding_can_use_directive_language_with_values() -> None:
    module = load_module()
    finding = valid_finding(
        id="F2",
        diagnosis="Table 3 Qwen2.5-32B MMMU Avg：按可见六列复算 37.64，不是表中的 47.70；delta +10.06。",
        reported_value="47.70",
        visible_computed_value="37.64",
        delta="+10.06",
        aggregation_caveat="deterministic gap; only a specific stated denominator/weighting explanation could rebut it",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, warnings = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Directive numeric finding with values should pass, got errors={errors}, warnings={warnings}")


def test_numeric_audit_schema_is_checked() -> None:
    module = load_module()
    path = write_json(
        {
            "signal_count": 1,
            "signals": [
                {
                    "table_id": "Table 1",
                    "row_label": "Method A",
                    "reported_value": "95.77",
                    "visible_computed_value": "95.52",
                    "delta": "+0.25",
                    "required_severity": "Blocker",
                }
            ],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", numeric_audit_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("aggregation_caveat" in error for error in errors):
        raise AssertionError(f"Expected numeric audit aggregation_caveat error, got {errors}")


def test_numeric_audit_render_required_signal_requires_blocker_severity() -> None:
    module = load_module()
    path = write_json(
        {
            "signal_count": 1,
            "signals": [
                {
                    "table_id": "Table 1",
                    "row_label": "Method A",
                    "reported_value": "95.77",
                    "visible_computed_value": "95.52",
                    "delta": "+0.25",
                    "aggregation_caveat": "visible arithmetic mean only",
                    "required_severity": "Minor",
                }
            ],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", numeric_audit_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("required_severity" in error and "Blocker" in error for error in errors):
        raise AssertionError(f"Expected required_severity error, got {errors}")


def test_numeric_audit_signal_must_render_in_html() -> None:
    module = load_module()
    html = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with html:
        html.write(HTML.read_text(encoding="utf-8").replace("95.52", "95.51"))
    path = Path(html.name)
    try:
        errors, _ = module.audit_artifacts(
            ARTIFACTS / "findings.json",
            numeric_audit_path=ARTIFACTS / "numeric_audit.json",
            html_path=path,
        )
    finally:
        path.unlink(missing_ok=True)
    if not any("numeric signal not rendered" in error and "95.52" in error for error in errors):
        raise AssertionError(f"Expected missing rendered numeric signal error, got {errors}")


def test_numeric_audit_signal_requires_nearby_blocker_rendering() -> None:
    module = load_module()
    html = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with html:
        html.write(HTML.read_text(encoding="utf-8").replace('data-severity="blocker" data-issue-type="numeric"', 'data-severity="minor" data-issue-type="numeric"').replace("■ Blocker</span> F2", "● Minor</span> F2"))
    path = Path(html.name)
    try:
        errors, _ = module.audit_artifacts(
            ARTIFACTS / "findings.json",
            numeric_audit_path=ARTIFACTS / "numeric_audit.json",
            html_path=path,
        )
    finally:
        path.unlink(missing_ok=True)
    if not any("without nearby Blocker severity" in error for error in errors):
        raise AssertionError(f"Expected missing nearby Blocker severity error, got {errors}")


def test_pass_observations_schema_is_checked() -> None:
    module = load_module()
    path = write_json(
        {
            "pass_0_engagement_contract": [],
            "pass_1_cold_start_skim": [{"what_tripped_me": "missing location"}],
            "pass_2_linear_deep_read": [],
            "pass_3_section_reflections": [],
            "pass_4_whole_paper_argument": [],
            "pass_5_submission_walk": [],
            "pass_6_output_calibration": [],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", pass_observations_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("missing `location`" in error for error in errors):
        raise AssertionError(f"Expected pass observation location error, got {errors}")


def test_render_manifest_rendered_section_must_exist_in_html() -> None:
    module = load_module()
    manifest = write_json(
        {
            "output_files": ["expected_html_report.html"],
            "sections": [{"id": "missing-section", "status": "rendered"}],
            "deferred_findings": [],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest, html_path=HTML)
    finally:
        manifest.unlink(missing_ok=True)
    if not any("missing-section" in error for error in errors):
        raise AssertionError(f"Expected missing rendered section error, got {errors}")


def test_render_manifest_deferred_finding_must_exist_in_json() -> None:
    module = load_module()
    manifest = write_json(
        {
            "output_files": ["expected_html_report.html"],
            "sections": [{"id": "issue-index", "status": "rendered"}],
            "deferred_findings": ["F404"],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest)
    finally:
        manifest.unlink(missing_ok=True)
    if not any("unknown finding id" in error for error in errors):
        raise AssertionError(f"Expected unknown deferred finding error, got {errors}")


def main() -> int:
    test_review_artifact_fixture_passes_contract()
    test_bundle_cli_paths_pass_contract()
    test_high_risk_finding_requires_downgrade_condition()
    test_json_finding_must_render_or_be_deferred()
    test_skipped_coverage_requires_pending_marker()
    test_numerical_finding_requires_aggregation_caveat()
    test_numerical_finding_must_be_blocker()
    test_numerical_finding_must_include_concrete_values_in_diagnosis()
    test_numerical_finding_can_use_directive_language_with_values()
    test_numeric_audit_schema_is_checked()
    test_numeric_audit_render_required_signal_requires_blocker_severity()
    test_numeric_audit_signal_must_render_in_html()
    test_numeric_audit_signal_requires_nearby_blocker_rendering()
    test_pass_observations_schema_is_checked()
    test_render_manifest_rendered_section_must_exist_in_html()
    test_render_manifest_deferred_finding_must_exist_in_json()
    print("audit_review_artifacts regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
