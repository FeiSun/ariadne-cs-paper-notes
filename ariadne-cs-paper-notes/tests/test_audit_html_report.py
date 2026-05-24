#!/usr/bin/env python3
"""Regression tests for Ariadne HTML report auditing."""

from __future__ import annotations

import importlib.util
import hashlib
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_html_report.py"
SOURCE = ROOT / "tests" / "fixtures" / "source_paper_reader.html"


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
        "paper-reader",
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
        '<section id="paper-reader"><h2>paper-reader</h2></section>',
        """
<section id="paper-reader" class="paper-reader">
  <h2>paper-reader</h2>
  <div class="reader-shell">
    <article class="paper-pane" data-paper-html-source="manual-fixture" data-source-fidelity="fixture" data-source-artifact="tests/fixtures/source_paper_reader.html" data-source-hash="sha256:d9fa0d504f1f956363924e63180f2559d417b079f37f16cdc1d32b594fc2bdc8" data-sentence-id-scheme="section-index-v1" data-annotation-mode="overlay-only">
      <p>
        <span class="paper-sentence" data-sentence-id="s-intro-001">Clean sentence.</span>
        <span class="paper-sentence has-annotation" data-sentence-id="s-intro-002" data-has-issue="true" data-issue-ids="F1" data-severity="major" data-issue-type="prose" role="button" tabindex="0" aria-describedby="ann-s-intro-002">Problem sentence.</span>
      </p>
    </article>
    <aside id="annotation-panel" class="annotation-panel" aria-label="批注详情">
      <article id="ann-s-intro-002" class="annotation-card" data-target-sentence="s-intro-002" data-issue-ids="F1" data-severity="major" data-issue-type="prose">
        <h3>问题是什么</h3>
        <p>句子问题。</p>
      </article>
    </aside>
  </div>
</section>
""",
    )
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


def paper_reader_only_html() -> str:
    return """<!doctype html>
<html><body>
<article class="review-report" data-report-kind="paper-reader-only">
  <section id="paper-reader" class="paper-reader">
    <div class="reader-shell">
      <article class="paper-pane" data-paper-html-source="pandoc" data-source-fidelity="deterministic" data-source-artifact="source.html" data-source-hash="sha256:d9fa0d504f1f956363924e63180f2559d417b079f37f16cdc1d32b594fc2bdc8" data-sentence-id-scheme="section-index-v1" data-annotation-mode="overlay-only">
        <p>
          <span class="paper-sentence" data-sentence-id="s-intro-001">Clean sentence.</span>
          <span class="paper-sentence has-annotation" data-sentence-id="s-intro-002" data-has-issue="true" data-issue-ids="F1" data-severity="major" data-issue-type="claim" role="button" tabindex="0" aria-describedby="ann-s-intro-002">Problem sentence.</span>
        </p>
      </article>
      <aside id="annotation-panel" class="annotation-panel">
        <article id="ann-s-intro-002" class="annotation-card" data-target-sentence="s-intro-002" data-issue-ids="F1" data-severity="major" data-issue-type="claim">
          <h3>问题是什么</h3>
          <p>句子问题。</p>
        </article>
      </aside>
    </div>
  </section>
  <section id="coverage-receipt">
    <h2>覆盖回执与 artifacts</h2>
    <p>Coverage consistency gate: passed for source-backed paper-reader fixture.</p>
    <table><caption>Receipt</caption><thead><tr><th scope="col">Unit</th></tr></thead><tbody><tr><td>paper-reader-only</td></tr></tbody></table>
  </section>
</article>
</body></html>"""


def write_temp_html(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with tmp:
        tmp.write(text)
    return Path(tmp.name)


def source_hash(path: Path = SOURCE) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def source_backed_paper_reader_html(source_path: Path = SOURCE, declared_hash: str | None = None) -> str:
    declared_hash = declared_hash or source_hash(source_path)
    source_body = source_path.read_text(encoding="utf-8")
    if "<body>" in source_body:
        source_body = source_body.split("<body>", 1)[1].split("</body>", 1)[0]
    annotated_body = source_body.replace(
        '<span class="paper-sentence">Our method solves this problem in practical deployment.</span>',
        '<span class="paper-sentence has-annotation" data-sentence-id="s-intro-002" data-has-issue="true" data-issue-ids="F1" data-severity="major" data-issue-type="claim" role="button" tabindex="0" aria-describedby="ann-s-intro-002">Our method solves this problem in practical deployment.</span>',
    )
    return f"""<!doctype html>
<html><body>
<article class="review-report" data-report-kind="paper-reader-only">
  <section id="paper-reader" class="paper-reader">
    <div class="reader-shell">
      <article class="paper-pane" data-paper-html-source="pandoc" data-source-fidelity="deterministic" data-source-artifact="{source_path}" data-source-hash="{declared_hash}" data-sentence-id-scheme="section-index-v1" data-annotation-mode="overlay-only">
{annotated_body}
      </article>
      <aside id="annotation-panel" class="annotation-panel">
        <article id="ann-s-intro-002" class="annotation-card" data-target-sentence="s-intro-002" data-issue-ids="F1" data-severity="major" data-issue-type="claim">
          <h3>问题是什么</h3>
          <p>句子问题。</p>
        </article>
      </aside>
    </div>
  </section>
  <section id="coverage-receipt">
    <h2>覆盖回执与 artifacts</h2>
    <p>Coverage consistency gate: passed for source-backed paper-reader fixture.</p>
    <table><caption>Receipt</caption><thead><tr><th scope="col">Unit</th></tr></thead><tbody><tr><td>paper-reader-only</td></tr></tbody></table>
  </section>
</article>
</body></html>"""


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


def test_audit_allows_paper_reader_only_deliverable() -> None:
    module = load_module()
    path = write_temp_html(paper_reader_only_html())
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected paper-reader-only HTML to pass, got {errors}")


def test_audit_with_source_verifies_hash_and_body() -> None:
    module = load_module()
    path = write_temp_html(source_backed_paper_reader_html())
    try:
        errors, warnings = module.audit_with_source(path, SOURCE)
    finally:
        path.unlink(missing_ok=True)
    if errors or warnings:
        raise AssertionError(f"Expected source-backed paper reader to verify cleanly, errors={errors}, warnings={warnings}")


def test_audit_with_source_rejects_bad_source_hash() -> None:
    module = load_module()
    path = write_temp_html(source_backed_paper_reader_html(declared_hash="sha256:0000000000000000"))
    try:
        errors, _ = module.audit_with_source(path, SOURCE)
    finally:
        path.unlink(missing_ok=True)
    if not any("source hash mismatch" in error for error in errors):
        raise AssertionError(f"Expected source hash mismatch error, got {errors}")


def test_audit_with_source_rejects_rewritten_paper_body() -> None:
    module = load_module()
    path = write_temp_html(source_backed_paper_reader_html().replace("Our method solves this problem", "Our method reframes this problem"))
    try:
        errors, _ = module.audit_with_source(path, SOURCE)
    finally:
        path.unlink(missing_ok=True)
    if not any("body differs from source artifact" in error for error in errors):
        raise AssertionError(f"Expected source body mismatch error, got {errors}")


def test_audit_with_source_warns_when_deliverable_source_not_checked() -> None:
    module = load_module()
    path = write_temp_html(source_backed_paper_reader_html())
    try:
        errors, warnings = module.audit_with_source(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected missing source to be warning-only, got errors={errors}")
    if not any("source integrity comparison skipped" in warning for warning in warnings):
        raise AssertionError(f"Expected skipped source integrity warning, got {warnings}")


def test_audit_rejects_paper_reader_card_location_snippet_and_evidence_labels() -> None:
    module = load_module()
    html = minimal_html().replace(
        "<h3>问题是什么</h3>\n        <p>句子问题。</p>",
        """
        <h3>句子问题</h3>
        <dl>
          <dt>位置</dt><dd>p-intro-001, sentence 2</dd>
          <dt>原句/片段</dt><dd>Problem sentence.</dd>
          <dt>证据/验证</dt><dd>sentence span generated from source-derived paper-reader HTML</dd>
          <dt>问题是什么</dt><dd>句子问题。</dd>
        </dl>""",
        1,
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    for label in ("位置", "原句/片段", "证据/验证"):
        if not any(f"visible `{label}`" in error for error in errors):
            raise AssertionError(f"Expected forbidden label error for {label}, got {errors}")


def test_audit_rejects_paper_reader_card_mechanical_provenance() -> None:
    module = load_module()
    html = minimal_html().replace(
        "<h3>问题是什么</h3>\n        <p>句子问题。</p>",
        """
        <h3>句子问题</h3>
        <dl>
          <dt>问题是什么</dt><dd>句子问题。</dd>
          <dt>为什么有问题</dt><dd>source-derived paper-reader HTML 生成了 data-sentence-id。</dd>
        </dl>""",
        1,
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("mechanical renderer provenance" in error for error in errors):
        raise AssertionError(f"Expected mechanical provenance error, got {errors}")


def test_audit_rejects_uninformative_paper_reader_card_evidence() -> None:
    module = load_module()
    html = minimal_html().replace(
        "<h3>问题是什么</h3>\n        <p>句子问题。</p>",
        """
        <h3>句子问题</h3>
        <dl>
          <dt>问题是什么</dt><dd>句子问题。</dd>
          <dt>核查依据</dt><dd>这是句子级 prose 判断。</dd>
        </dl>""",
        1,
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("without concrete manuscript-level evidence" in error for error in errors):
        raise AssertionError(f"Expected uninformative evidence error, got {errors}")


def test_audit_allows_meaningful_paper_reader_card_evidence() -> None:
    module = load_module()
    html = minimal_html().replace(
        "<h3>问题是什么</h3>\n        <p>句子问题。</p>",
        """
        <h3>数字问题</h3>
        <dl>
          <dt>问题是什么</dt><dd>数字不可复算。</dd>
          <dt>核查依据</dt><dd>Table 1 visible cells；visible arithmetic mean recomputed from table。</dd>
        </dl>""",
        1,
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected meaningful evidence card to pass, got {errors}")


def test_audit_allows_unanchored_annotation_cards_without_sentence_target() -> None:
    module = load_module()
    html = minimal_html().replace(
        "</aside>",
        """
      <details class="unanchored-drawer">
        <summary>未定位到具体句子的批注（1）</summary>
        <article id="ann-unanchored-1" class="annotation-card is-unanchored" data-unanchored="true" data-issue-ids="F1" data-severity="major" data-issue-type="layout">
          <h3>全局版式意见</h3>
          <p>这条意见保留旧 report 内容，但不冒充句子级锚点。</p>
        </article>
      </details>
    </aside>
""",
        1,
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected unanchored annotation card to pass, got {errors}")


def test_audit_allows_paragraph_section_and_paper_annotation_anchors() -> None:
    module = load_module()
    html = paper_reader_only_html().replace(
        '<span class="paper-sentence has-annotation" data-sentence-id="s-intro-002" data-has-issue="true" data-issue-ids="F1" data-severity="major" data-issue-type="claim" role="button" tabindex="0" aria-describedby="ann-s-intro-002">Problem sentence.</span>',
        '<span class="paper-sentence" data-sentence-id="s-intro-002">Problem sentence.</span>',
    ).replace(
        '<p>',
        '<aside id="paper-overview-annotations" class="paper-overview-annotations has-paper-annotation" data-paper-id="paper" data-has-issue="true" data-issue-ids="F1" data-severity="major" data-issue-type="paper"></aside><h1 id="intro" class="has-section-annotation" data-has-issue="true" data-issue-ids="F1" data-severity="major" data-issue-type="flow">Intro</h1><p data-paragraph-id="p-intro-001" class="has-paragraph-annotation" data-has-issue="true" data-issue-ids="F1" data-severity="major" data-issue-type="structure">',
        1,
    ).replace(
        '<article id="ann-s-intro-002" class="annotation-card" data-target-sentence="s-intro-002" data-issue-ids="F1" data-severity="major" data-issue-type="claim">',
        '<article id="ann-p-intro-001" class="annotation-card" data-target-level="paragraph" data-target-paragraph="p-intro-001" data-issue-ids="F1" data-severity="major" data-issue-type="structure"><h3>段落问题</h3></article><article id="ann-section-intro" class="annotation-card" data-target-level="section" data-target-section="intro" data-issue-ids="F1" data-severity="major" data-issue-type="flow"><h3>章节问题</h3></article><article id="ann-paper" class="annotation-card" data-target-level="paper" data-target-paper="paper" data-issue-ids="F1" data-severity="major" data-issue-type="paper"><h3>全文问题</h3></article><article id="ann-s-intro-002" class="annotation-card" data-target-sentence="s-intro-002" data-issue-ids="F1" data-severity="major" data-issue-type="claim">',
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected non-sentence paper-reader anchors to pass, got {errors}")


def test_audit_rejects_unanchored_annotation_with_sentence_target() -> None:
    module = load_module()
    html = minimal_html().replace(
        "</aside>",
        """
      <article id="ann-unanchored-1" class="annotation-card is-unanchored" data-unanchored="true" data-target-sentence="unanchored-1" data-issue-ids="F1" data-severity="major" data-issue-type="layout">
        <h3>Bad unanchored note</h3>
      </article>
    </aside>
""",
        1,
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("unanchored annotation card must not set target-sentence" in error for error in errors):
        raise AssertionError(f"Expected invalid unanchored target error, got {errors}")


def test_audit_rejects_missing_paper_reader() -> None:
    module = load_module()
    path = write_temp_html(minimal_html().replace('<section id="paper-reader"', '<section id="paper-reader-missing"', 1))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("paper-reader" in error for error in errors):
        raise AssertionError(f"Expected missing paper-reader error, got {errors}")


def test_audit_rejects_unmatched_sentence_annotation() -> None:
    module = load_module()
    path = write_temp_html(minimal_html().replace('data-target-sentence="s-intro-002"', 'data-target-sentence="s-intro-099"', 1))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("has no matching annotation card" in error for error in errors):
        raise AssertionError(f"Expected unmatched annotation error, got {errors}")


def test_audit_rejects_missing_paper_source_provenance() -> None:
    module = load_module()
    html = minimal_html().replace(
        ' data-source-fidelity="fixture" data-source-artifact="tests/fixtures/source_paper_reader.html" data-source-hash="sha256:d9fa0d504f1f956363924e63180f2559d417b079f37f16cdc1d32b594fc2bdc8" data-sentence-id-scheme="section-index-v1" data-annotation-mode="overlay-only"',
        "",
        1,
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("data-source-fidelity" in error for error in errors):
        raise AssertionError(f"Expected missing source provenance error, got {errors}")


def test_audit_rejects_limited_scope_without_visible_scope() -> None:
    module = load_module()
    html = minimal_html().replace('data-paper-html-source="manual-fixture"', 'data-paper-html-source="extracted-text"', 1).replace(
        'data-source-fidelity="fixture"',
        'data-source-fidelity="limited-scope"',
        1,
    )
    path = write_temp_html(html)
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("data-visible-scope" in error for error in errors):
        raise AssertionError(f"Expected missing visible scope error, got {errors}")


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
  <a class="finding-link" href="#F3">F3</a>
</section>
"""
    path = write_temp_html(minimal_html(extra))
    try:
        errors, _ = module.audit(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("linked finding `F3`" in error for error in errors):
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
    test_audit_allows_paper_reader_only_deliverable()
    test_audit_with_source_verifies_hash_and_body()
    test_audit_with_source_rejects_bad_source_hash()
    test_audit_with_source_rejects_rewritten_paper_body()
    test_audit_with_source_warns_when_deliverable_source_not_checked()
    test_audit_rejects_paper_reader_card_location_snippet_and_evidence_labels()
    test_audit_rejects_paper_reader_card_mechanical_provenance()
    test_audit_rejects_uninformative_paper_reader_card_evidence()
    test_audit_allows_meaningful_paper_reader_card_evidence()
    test_audit_allows_unanchored_annotation_cards_without_sentence_target()
    test_audit_rejects_unanchored_annotation_with_sentence_target()
    test_audit_rejects_missing_paper_reader()
    test_audit_rejects_unmatched_sentence_annotation()
    test_audit_rejects_missing_paper_source_provenance()
    test_audit_rejects_limited_scope_without_visible_scope()
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
