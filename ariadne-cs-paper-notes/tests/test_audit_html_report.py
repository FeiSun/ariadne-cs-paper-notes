#!/usr/bin/env python3
"""Regression tests for Ariadne HTML report auditing."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_html_report.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_html_report", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load audit_html_report module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def minimal_html(extra: str = "") -> str:
    sections = [
        "executive-diagnosis",
        "issue-index",
        "claim-evidence-audit",
        "deep-reading-notes",
        "submission-readiness",
        "local-comments",
        "revision-plan",
        "coverage-receipt",
    ]
    body = "\n".join(f'<section id="{section}"><h2>{section}</h2></section>' for section in sections)
    body = body.replace(
        '<section id="issue-index"><h2>issue-index</h2></section>',
        """
<section id="issue-index">
  <h2>issue-index</h2>
  <table><caption>Issue index</caption><thead><tr><th scope="col">ID</th></tr></thead>
  <tbody><tr data-severity="major"><td><a id="F1" class="finding-link" href="#F1">F1</a></td></tr></tbody></table>
</section>
""",
    )
    body = body.replace(
        '<section id="deep-reading-notes"><h2>deep-reading-notes</h2></section>',
        """
<section id="deep-reading-notes">
  <h2>deep-reading-notes</h2>
  <section class="paper-section" id="sec-intro">
    <h3>Intro</h3>
    <table><caption>Section reflection</caption><thead><tr><th scope="col">章节</th></tr></thead>
    <tbody><tr data-note-kind="section" data-severity="major"><td>Intro</td></tr></tbody></table>
    <table><caption>Paragraph and sentence notes</caption><thead><tr><th scope="col">位置</th></tr></thead>
    <tbody>
      <tr data-note-kind="paragraph" data-severity="major" data-decision="merge"><td>Intro ¶1</td></tr>
      <tr data-note-kind="sentence" data-severity="major"><td>Intro ¶1 S1</td></tr>
    </tbody></table>
  </section>
</section>
""",
    )
    body = body.replace(
        '<section id="submission-readiness"><h2>submission-readiness</h2></section>',
        """
<section id="submission-readiness"><h2>submission-readiness</h2>
  <table><caption>Submission readiness</caption><thead><tr><th scope="col">类别</th></tr></thead>
  <tbody><tr id="pdf-page-1" class="pdf-anchor" data-severity="polish"><td>PDF p.1</td></tr></tbody></table>
</section>
""",
    )
    return f"""<!doctype html>
<html><body>
<nav>
  <a href="#deep-reading-notes">notes</a>
  <a href="#issue-index">issues</a>
</nav>
{body}
{extra}
</body></html>"""


def write_temp_html(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with tmp:
        tmp.write(text)
    return Path(tmp.name)


def test_audit_rejects_missing_deep_reading_section() -> None:
    module = load_module()
    path = write_temp_html(minimal_html().replace('<section id="deep-reading-notes"', '<section id="deep-reading-notes-missing"', 1))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("deep-reading-notes" in error for error in errors):
        raise AssertionError(f"Expected missing deep-reading-notes error, got {errors}")


def test_audit_counts_nested_deep_reading_rows() -> None:
    module = load_module()
    path = write_temp_html(minimal_html())
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected nested deep-reading rows to pass, got {errors}")


def test_audit_rejects_body_count_mismatch() -> None:
    module = load_module()
    extra = """
<section id="coverage-extra">
  <table>
    <caption>Coverage</caption>
    <thead><tr><th scope="col">Unit</th><th scope="col">Count</th></tr></thead>
    <tbody><tr><td>Sentence notes</td><td>2</td><td>#deep-reading-notes [data-note-kind="sentence"]</td><td>1</td><td>fail</td></tr></tbody>
  </table>
</section>
"""
    path = write_temp_html(minimal_html(extra))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("declared sentence" in error for error in errors):
        raise AssertionError(f"Expected declared sentence count mismatch, got {errors}")


def test_audit_rejects_legacy_split_note_sections() -> None:
    module = load_module()
    extra = '<section id="paragraph-surgery"><h2>legacy</h2></section>'
    path = write_temp_html(minimal_html(extra))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("ordered #deep-reading-notes" in error for error in errors):
        raise AssertionError(f"Expected legacy split-section error, got {errors}")


def test_audit_rejects_vague_numeric_summary_without_values() -> None:
    module = load_module()
    extra = """
<section id="numeric-summary">
  <h2>数字一致性重点</h2>
  <p>Table 1 Method A/B Score X 与可见均值有偏差，可能来自隐藏小数或定义不清，需要核对。</p>
</section>
"""
    path = write_temp_html(minimal_html(extra))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("vague numeric language" in error for error in errors):
        raise AssertionError(f"Expected vague numeric language error, got {errors}")


def test_audit_allows_concrete_numeric_summary_with_reported_computed_delta() -> None:
    module = load_module()
    extra = """
<section id="numeric-summary">
  <h2>数字一致性重点</h2>
  <p>Table 1 Method A Score X：按可见三列复算 95.52，表中写 95.77，delta +0.25；若使用 weighted aggregation，需要说明 denominator。</p>
</section>
"""
    path = write_temp_html(minimal_html(extra))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected concrete numeric summary to pass, got {errors}")


def test_audit_rejects_raw_numerical_schema_keys_in_html_body() -> None:
    module = load_module()
    extra = """
<section id="numeric-summary">
  <h2>数字一致性重点</h2>
  <p>reported_value: 95.77；visible_computed_value: 95.52；delta: +0.25；aggregation_caveat: visible mean only.</p>
</section>
"""
    path = write_temp_html(minimal_html(extra))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("raw numerical schema keys" in error for error in errors):
        raise AssertionError(f"Expected raw schema key error, got {errors}")


def test_audit_rejects_undefined_linked_finding() -> None:
    module = load_module()
    extra = """
<section id="extra-links">
  <h2>Extra</h2>
  <a class="finding-link" href="#N3">N3</a>
</section>
"""
    path = write_temp_html(minimal_html(extra))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("linked finding `N3`" in error for error in errors):
        raise AssertionError(f"Expected undefined linked finding error, got {errors}")


def test_audit_rejects_verbose_issue_index_operational_fields() -> None:
    module = load_module()
    html = minimal_html().replace("</section>\n\n<section id=\"claim-evidence-audit\"", "<p><strong>降级条件：</strong>补实验。</p></section>\n\n<section id=\"claim-evidence-audit\"", 1)
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("#issue-index should be compact" in error for error in errors):
        raise AssertionError(f"Expected compact issue index error, got {errors}")


def test_audit_rejects_table_without_caption_or_scope() -> None:
    module = load_module()
    extra = """
<section id="bad-table">
  <h2>Bad table</h2>
  <table><tr><th>Header</th></tr><tr><td>body</td></tr></table>
</section>
"""
    path = write_temp_html(minimal_html(extra))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("missing <caption>" in error for error in errors):
        raise AssertionError(f"Expected missing caption error, got {errors}")
    if not any("<th> without scope" in error for error in errors):
        raise AssertionError(f"Expected missing th scope error, got {errors}")


def test_audit_rejects_incomplete_html_structure() -> None:
    module = load_module()
    html = minimal_html(
        """
<section id="broken-section">
  <article data-severity="major" data-issue-type="prose">
    <p>unfinished
"""
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("structurally incomplete or misnested" in error for error in errors):
        raise AssertionError(f"Expected structural HTML error, got {errors}")


def main() -> int:
    test_audit_rejects_missing_deep_reading_section()
    test_audit_counts_nested_deep_reading_rows()
    test_audit_rejects_body_count_mismatch()
    test_audit_rejects_legacy_split_note_sections()
    test_audit_rejects_vague_numeric_summary_without_values()
    test_audit_allows_concrete_numeric_summary_with_reported_computed_delta()
    test_audit_rejects_raw_numerical_schema_keys_in_html_body()
    test_audit_rejects_undefined_linked_finding()
    test_audit_rejects_verbose_issue_index_operational_fields()
    test_audit_rejects_table_without_caption_or_scope()
    test_audit_rejects_incomplete_html_structure()
    print("audit_html_report regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
