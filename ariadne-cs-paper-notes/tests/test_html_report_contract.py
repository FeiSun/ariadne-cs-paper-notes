#!/usr/bin/env python3
"""Contract checks for the paper-reader HTML report fixture."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "expected_html_report.html"
AUDIT_SCRIPT = ROOT / "scripts" / "audit_html_report.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_html_report", AUDIT_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load audit_html_report module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"Missing expected text: {needle}")


def assert_not_contains(text: str, needle: str) -> None:
    if needle in text:
        raise AssertionError(f"Unexpected legacy text: {needle}")


def test_html_report_fixture_satisfies_current_contract() -> None:
    html = FIXTURE.read_text(encoding="utf-8")

    required_tokens = [
        'data-report-kind="paper-reader-with-global-findings"',
        'id="paper-reader"',
        'class="paper-reader"',
        'class="reader-shell"',
        'class="paper-pane"',
        'data-paper-html-source="pandoc"',
        'data-source-fidelity="deterministic"',
        'data-source-artifact=',
        'data-source-hash="sha256:',
        'data-sentence-id-scheme="section-paragraph-sentence-v2"',
        'data-annotation-mode="overlay-only"',
        'id="annotation-panel"',
        'class="annotation-card',
        "问题是什么",
        "为什么有问题",
        "违反原则",
        "自改问题",
        "上一条",
        "下一条",
        "AriadnePaperReaderOpenAnnotation",
        "visibleSentences",
        'id="global-findings"',
        "全局重要问题",
        'id="coverage-receipt"',
        "Coverage consistency",
    ]
    for token in required_tokens:
        assert_contains(html, token)

    required_sections = ["paper-reader", "global-findings", "coverage-receipt"]
    for section_id in required_sections:
        assert_contains(html, f'id="{section_id}"')
        assert_contains(html, f'href="#{section_id}"')

    forbidden_legacy_sections = [
        'id="executive-diagnosis"',
        'id="issue-index"',
        'id="claim-evidence-audit"',
        'id="deep-reading-notes"',
        'id="submission-readiness"',
        'id="local-comments"',
        'id="revision-plan"',
        'id="top-priorities"',
        'id="section-review"',
        'id="paragraph-surgery"',
        'id="margin-notes"',
        'id="keep-notes"',
        'id="section-comments"',
        'id="section-reflections"',
    ]
    for token in forbidden_legacy_sections:
        assert_not_contains(html, token)

    audit_module = load_audit_module()
    errors, warnings = audit_module.audit(FIXTURE)
    if errors or warnings:
        raise AssertionError(f"HTML audit did not pass.\nErrors: {errors}\nWarnings: {warnings}")


def main() -> int:
    test_html_report_fixture_satisfies_current_contract()
    print("html_report fixture contract tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
