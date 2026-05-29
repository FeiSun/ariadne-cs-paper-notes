#!/usr/bin/env python3
"""Regression tests for current Ariadne HTML report auditing."""

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


def pdf_overlay_html(extra: str = "") -> str:
    problem = "\u95ee\u9898\u662f\u4ec0\u4e48"
    sentence_problem = "\u53e5\u5b50\u95ee\u9898\u3002"
    return f"""<!doctype html>
<html><body>
<article class="review-report" data-report-kind="pdf-overlay">
  <section id="paper-reader" class="paper-reader">
    <div class="reader-shell">
      <article class="paper-pane pdf-paper-pane" data-paper-view="pdfjs-overlay" data-source-artifact="main.tex" data-source-hash="sha256:a1b010a23da8ba9357adca0a97a7c61f716a74a08a7c0fb17c7e7cee245692eb" data-sentence-id-scheme="section-paragraph-sentence-v2" data-annotation-mode="pdfjs-overlay">
        <div id="finding-anchor-index" hidden aria-hidden="true"><span id="F1"></span></div>
        <div id="pdfjs-viewer" class="pdfjs-viewer" data-pdf-src="paper.pdf"></div>
        <script type="application/json" id="pdf-overlay-data">{{"1":["<button class=\\\"pdf-highlight paper-sentence has-annotation\\\" data-sentence-id=\\\"s-intro-002\\\" data-has-issue=\\\"true\\\" data-issue-ids=\\\"F1\\\" data-severity=\\\"major\\\" data-issue-type=\\\"claim\\\" type=\\\"button\\\" aria-describedby=\\\"ann-s-intro-002\\\"></button>"]}}</script>
      </article>
      <aside id="annotation-panel" class="annotation-panel">
        <article id="ann-s-intro-002" class="annotation-card" data-target-sentence="s-intro-002" data-issue-ids="F1" data-severity="major" data-issue-type="claim">
          <h3>{problem}</h3>
          <p>{sentence_problem}</p>
        </article>
      </aside>
    </div>
  </section>
  <section id="bbox-diagnostics"><h2>PDF Anchor Diagnostics</h2></section>
  <section id="coverage-receipt">
    <h2>Coverage Receipt</h2>
    <p>Coverage consistency gate: passed for PDF overlay fixture.</p>
    <table><caption>Receipt</caption><thead><tr><th scope="col">Unit</th></tr></thead><tbody><tr><td>pdf-overlay</td></tr></tbody></table>
  </section>
  {extra}
</article>
</body></html>"""


def issue_report_html(extra: str = "") -> str:
    return f"""<!doctype html>
<html><body>
<article class="review-report" data-report-kind="issue-report-only">
  <section id="issue-report">
    <h2>Issue Report</h2>
    <article id="F1" class="finding-card" data-severity="Major" data-issue-type="claim">
      <h3>F1</h3>
      <p>Concrete issue report entry.</p>
    </article>
  </section>
  <section id="coverage-receipt">
    <h2>Coverage Receipt</h2>
    <p>Coverage consistency gate: passed for report-only fixture.</p>
    <table><caption>Coverage summary</caption><thead><tr><th scope="col">Unit</th></tr></thead><tbody><tr><td>Findings</td></tr></tbody></table>
  </section>
  {extra}
</article>
</body></html>"""


def write_temp_html(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with tmp:
        tmp.write(text)
    return Path(tmp.name)


def audit_text(text: str) -> tuple[list[str], list[str]]:
    module = load_module()
    path = write_temp_html(text)
    try:
        return module.audit(path)
    finally:
        path.unlink(missing_ok=True)


def test_audit_allows_pdf_overlay_deliverable() -> None:
    errors, warnings = audit_text(pdf_overlay_html())
    if errors or warnings:
        raise AssertionError(f"Expected PDF overlay HTML to pass, errors={errors}, warnings={warnings}")


def test_audit_allows_issue_report_only_deliverable() -> None:
    errors, warnings = audit_text(issue_report_html())
    if errors or warnings:
        raise AssertionError(f"Expected report-only HTML to pass, errors={errors}, warnings={warnings}")


def test_audit_rejects_pdf_overlay_that_declares_html_source() -> None:
    html = pdf_overlay_html().replace(
        'data-paper-view="pdfjs-overlay"',
        'data-paper-view="pdfjs-overlay" data-paper-html-source="extracted-text" data-source-fidelity="deterministic"',
        1,
    )
    errors, _ = audit_text(html)
    if not any("must not declare data-paper-html-source" in error for error in errors):
        raise AssertionError(f"Expected PDF overlay provenance error, got {errors}")


def test_audit_rejects_pdf_overlay_without_paper_view() -> None:
    html = pdf_overlay_html().replace('data-paper-view="pdfjs-overlay"', 'data-paper-view="missing"', 1)
    errors, _ = audit_text(html)
    if not any('must set data-paper-view="pdfjs-overlay"' in error for error in errors):
        raise AssertionError(f"Expected PDF overlay paper-view error, got {errors}")


def test_audit_rejects_legacy_workbench_sections_in_current_reports() -> None:
    errors, _ = audit_text(pdf_overlay_html('<section id="issue-index"><h2>Legacy</h2></section>'))
    if not any("legacy workbench sections" in error for error in errors):
        raise AssertionError(f"Expected legacy workbench section rejection, got {errors}")


def test_audit_rejects_overlay_card_location_snippet_and_evidence_labels() -> None:
    problem = "\u95ee\u9898\u662f\u4ec0\u4e48"
    sentence_problem = "\u53e5\u5b50\u95ee\u9898\u3002"
    labels = {
        "location": "\u4f4d\u7f6e",
        "snippet": "\u539f\u53e5/\u7247\u6bb5",
        "evidence": "\u8bc1\u636e/\u9a8c\u8bc1",
    }
    html = pdf_overlay_html().replace(
        f"<h3>{problem}</h3>\n          <p>{sentence_problem}</p>",
        f"""
          <h3>{problem}</h3>
          <dl>
            <dt>{labels["location"]}</dt><dd>p-intro-001, sentence 2</dd>
            <dt>{labels["snippet"]}</dt><dd>Problem sentence.</dd>
            <dt>{labels["evidence"]}</dt><dd>sentence span generated from renderer provenance</dd>
            <dt>{problem}</dt><dd>{sentence_problem}</dd>
          </dl>""",
        1,
    )
    errors, _ = audit_text(html)
    for label in labels.values():
        if not any(f"visible `{label}`" in error for error in errors):
            raise AssertionError(f"Expected forbidden label error for {label}, got {errors}")


def test_audit_rejects_overlay_card_mechanical_provenance() -> None:
    problem = "\u95ee\u9898\u662f\u4ec0\u4e48"
    sentence_problem = "\u53e5\u5b50\u95ee\u9898\u3002"
    why = "\u4e3a\u4ec0\u4e48\u6709\u95ee\u9898"
    html = pdf_overlay_html().replace(
        f"<h3>{problem}</h3>\n          <p>{sentence_problem}</p>",
        f"""
          <h3>{problem}</h3>
          <dl>
            <dt>{problem}</dt><dd>{sentence_problem}</dd>
            <dt>{why}</dt><dd>renderer generated data-sentence-id.</dd>
          </dl>""",
        1,
    )
    errors, _ = audit_text(html)
    if not any("mechanical renderer provenance" in error for error in errors):
        raise AssertionError(f"Expected mechanical provenance error, got {errors}")


def test_audit_rejects_uninformative_overlay_card_evidence() -> None:
    problem = "\u95ee\u9898\u662f\u4ec0\u4e48"
    sentence_problem = "\u53e5\u5b50\u95ee\u9898\u3002"
    evidence = "\u6838\u67e5\u4f9d\u636e"
    html = pdf_overlay_html().replace(
        f"<h3>{problem}</h3>\n          <p>{sentence_problem}</p>",
        f"""
          <h3>{problem}</h3>
          <dl>
            <dt>{problem}</dt><dd>{sentence_problem}</dd>
            <dt>{evidence}</dt><dd>Generic prose judgment.</dd>
          </dl>""",
        1,
    )
    errors, _ = audit_text(html)
    if not any("without concrete manuscript-level evidence" in error for error in errors):
        raise AssertionError(f"Expected uninformative evidence error, got {errors}")


def test_audit_allows_meaningful_overlay_card_evidence() -> None:
    problem = "\u95ee\u9898\u662f\u4ec0\u4e48"
    sentence_problem = "\u53e5\u5b50\u95ee\u9898\u3002"
    evidence = "\u6838\u67e5\u4f9d\u636e"
    html = pdf_overlay_html().replace(
        f"<h3>{problem}</h3>\n          <p>{sentence_problem}</p>",
        f"""
          <h3>Numeric issue</h3>
          <dl>
            <dt>{problem}</dt><dd>Numeric value cannot be recomputed.</dd>
            <dt>{evidence}</dt><dd>Table 1 visible cells; visible arithmetic mean recomputed from table.</dd>
          </dl>""",
        1,
    )
    errors, _ = audit_text(html)
    if errors:
        raise AssertionError(f"Expected meaningful evidence card to pass, got {errors}")


def test_audit_allows_unanchored_annotation_cards_without_sentence_target() -> None:
    html = pdf_overlay_html().replace(
        "</aside>",
        """
        <details class="unanchored-drawer">
          <summary>Unmapped annotations (1)</summary>
          <article id="ann-unanchored-1" class="annotation-card is-unanchored" data-unanchored="true" data-issue-ids="F1" data-severity="major" data-issue-type="layout">
            <h3>Global layout note</h3>
            <p>This issue is preserved without pretending to have a sentence anchor.</p>
          </article>
        </details>
      </aside>""",
        1,
    )
    errors, _ = audit_text(html)
    if errors:
        raise AssertionError(f"Expected unanchored annotation card to pass, got {errors}")


def test_audit_rejects_unanchored_annotation_with_sentence_target() -> None:
    html = pdf_overlay_html().replace(
        "</aside>",
        """
        <article id="ann-unanchored-1" class="annotation-card is-unanchored" data-unanchored="true" data-target-sentence="unanchored-1" data-issue-ids="F1" data-severity="major" data-issue-type="layout">
          <h3>Bad unanchored note</h3>
        </article>
      </aside>""",
        1,
    )
    errors, _ = audit_text(html)
    if not any("unanchored annotation card must not set target-sentence" in error for error in errors):
        raise AssertionError(f"Expected invalid unanchored target error, got {errors}")


def test_audit_rejects_unmatched_sentence_annotation() -> None:
    html = pdf_overlay_html().replace('data-sentence-id=\\\"s-intro-002\\\"', 'data-sentence-id=\\\"s-intro-099\\\"', 1)
    errors, _ = audit_text(html)
    if not any("has no matching annotation card" in error for error in errors):
        raise AssertionError(f"Expected unmatched annotation error, got {errors}")


def test_audit_rejects_vague_numeric_summary_without_values() -> None:
    extra = """
<section id="numeric-summary">
  <h2>Numeric summary</h2>
  <p>Table 1 Method A/B Score X has a discrepancy with the visible mean and may come from hidden decimals, so it needs recheck.</p>
</section>
"""
    errors, _ = audit_text(issue_report_html(extra))
    if not any("vague numeric language" in error for error in errors):
        raise AssertionError(f"Expected vague numeric language error, got {errors}")


def test_audit_allows_concrete_numeric_summary_with_reported_computed_delta() -> None:
    extra = """
<section id="numeric-summary">
  <h2>Numeric summary</h2>
  <p>Table 1 Method A Score X: visible computed value is 95.52, reported value is 95.77, delta +0.25; if weighted aggregation is used, state the denominator.</p>
</section>
"""
    errors, _ = audit_text(issue_report_html(extra))
    if errors:
        raise AssertionError(f"Expected concrete numeric summary to pass, got {errors}")


def test_audit_rejects_raw_numerical_schema_keys_in_html_body() -> None:
    extra = """
<section id="numeric-summary">
  <h2>Numeric summary</h2>
  <p>reported_value: 95.77; visible_computed_value: 95.52; delta: +0.25; aggregation_caveat: visible mean only.</p>
</section>
"""
    errors, _ = audit_text(issue_report_html(extra))
    if not any("raw numerical schema keys" in error for error in errors):
        raise AssertionError(f"Expected raw schema key error, got {errors}")


def test_audit_rejects_undefined_linked_finding() -> None:
    extra = '<section id="extra-links"><h2>Extra</h2><a class="finding-link" href="#F3">F3</a></section>'
    errors, _ = audit_text(issue_report_html(extra))
    if not any("linked finding `F3`" in error for error in errors):
        raise AssertionError(f"Expected undefined linked finding error, got {errors}")


def test_audit_rejects_table_without_caption_or_scope() -> None:
    extra = '<section id="bad-table"><h2>Bad table</h2><table><tr><th>Header</th></tr><tr><td>body</td></tr></table></section>'
    errors, _ = audit_text(issue_report_html(extra))
    if not any("missing <caption>" in error for error in errors):
        raise AssertionError(f"Expected missing caption error, got {errors}")
    if not any("<th> without scope" in error for error in errors):
        raise AssertionError(f"Expected missing th scope error, got {errors}")


def test_audit_rejects_incomplete_html_structure() -> None:
    errors, _ = audit_text(issue_report_html('<section id="broken-section"><article data-severity="major" data-issue-type="prose"><p>unfinished'))
    if not any("structurally incomplete or misnested" in error for error in errors):
        raise AssertionError(f"Expected structural HTML error, got {errors}")


def main() -> int:
    test_audit_allows_pdf_overlay_deliverable()
    test_audit_allows_issue_report_only_deliverable()
    test_audit_rejects_pdf_overlay_that_declares_html_source()
    test_audit_rejects_pdf_overlay_without_paper_view()
    test_audit_rejects_legacy_workbench_sections_in_current_reports()
    test_audit_rejects_overlay_card_location_snippet_and_evidence_labels()
    test_audit_rejects_overlay_card_mechanical_provenance()
    test_audit_rejects_uninformative_overlay_card_evidence()
    test_audit_allows_meaningful_overlay_card_evidence()
    test_audit_allows_unanchored_annotation_cards_without_sentence_target()
    test_audit_rejects_unanchored_annotation_with_sentence_target()
    test_audit_rejects_unmatched_sentence_annotation()
    test_audit_rejects_vague_numeric_summary_without_values()
    test_audit_allows_concrete_numeric_summary_with_reported_computed_delta()
    test_audit_rejects_raw_numerical_schema_keys_in_html_body()
    test_audit_rejects_undefined_linked_finding()
    test_audit_rejects_table_without_caption_or_scope()
    test_audit_rejects_incomplete_html_structure()
    print("audit_html_report regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
