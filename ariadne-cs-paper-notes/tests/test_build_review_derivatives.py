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


if __name__ == "__main__":
    test_derivative_artifacts_satisfy_existing_audit_contract()
    test_derivatives_cli_writes_all_outputs()
    test_derivatives_manifest_can_match_paper_reader_only_render()
    print("build_review_derivatives regression tests passed")
