#!/usr/bin/env python3
"""Contract checks for the HTML report fixture."""

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
        'data-filter="all"',
        'data-filter="blocker"',
        'data-filter="major"',
        'data-filter="minor"',
        'data-filter="polish"',
        "data-severity=",
        "data-hidden-by-filter",
        "data-filter-empty",
        "aria-pressed",
        "data-type-filter",
        "data-issue-type",
        "empty-state",
        "pdf-anchor",
        "caption",
        'scope="col"',
        "finding-link",
        "querySelectorAll",
        "hiddenByFilter",
        "Reader-Journey passes performed",
        "Pass 0 done",
        "Pass 1 done",
        "Pass 2 done",
        "Pass 3 done",
        "Pass 4 done",
        "Pass 5 done",
        "Pass 6 done",
        "总评诊断与可救骨架",
        "问题索引",
        "主张与证据审计",
        "逐章精读批注",
        "数字 / 公式 / 图表 / 版式 / 提交就绪",
        "共性问题汇总",
        "修改路线",
        "覆盖回执与 artifacts",
        "读后一句话",
        "章节任务是否对齐",
        "建议结构",
        "未闭合问题",
        "关联问题",
        "段落",
        "句子",
        "检查维度",
        "读者卡点",
        "违反原则",
        "下一稿任务",
        "自改问题",
        "data-note-kind=\"section\"",
        "data-note-kind=\"paragraph\"",
        "data-note-kind=\"sentence\"",
        "data-decision",
        "表中数值",
        "可见复算值",
        "差值",
        "口径说明",
        "High-risk fields complete",
        "Severity audit",
        "Rebuttal reverse check",
        "Known blind spots",
        "Structured artifacts",
        "Numerical signals cited",
        "Coverage consistency",
        "Body section / selector",
        "Actual count",
        "#deep-reading-notes [data-note-kind=&quot;sentence&quot;]",
        "#deep-reading-notes [data-note-kind=&quot;paragraph&quot;]",
        "#deep-reading-notes [data-note-kind=&quot;section&quot;]",
        "notes citing source principles",
        "Polish items",
        "PDF pages",
        "Figures",
        "References",
        "Pending in",
        "Minimal viable paper",
        "Delete vs. downgrade",
        "Fix type",
        "Next revision thread",
        "置信度",
        "验证方式",
        "判级理由",
    ]
    for token in required_tokens:
        assert_contains(html, token)

    required_sections = [
        "executive-diagnosis",
        "issue-index",
        "claim-evidence-audit",
        "deep-reading-notes",
        "submission-readiness",
        "local-comments",
        "revision-plan",
        "coverage-receipt",
    ]
    for section_id in required_sections:
        assert_contains(html, f'id="{section_id}"')
        assert_contains(html, f'href="#{section_id}"')

    forbidden_legacy_sections = [
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

    issue_index = html.split('<section id="issue-index">', 1)[1].split('<section id="claim-evidence-audit">', 1)[0]
    assert_not_contains(issue_index, "降级条件")
    assert_not_contains(issue_index, "下一稿任务")

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
