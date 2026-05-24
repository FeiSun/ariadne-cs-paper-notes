#!/usr/bin/env python3
"""Regression checks for source-derived paper-reader HTML rendering."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_paper_html.py"


def load_module():
    spec = importlib.util.spec_from_file_location("render_paper_html", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load render_paper_html module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_render_paper_html_wraps_source_sentences_with_provenance() -> None:
    if shutil.which("pandoc") is None:
        print("pandoc unavailable; skipping render_paper_html smoke test")
        return
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\title{Tiny Paper}
\begin{document}
\maketitle
\section{Intro}
First sentence. Second sentence with $x+1$ math.
\section{Method}
Third sentence?
\end{document}
""",
            encoding="utf-8",
        )
        output = tmp / "paper_reader.html"
        rendered, raw, count = module.render(tex, output)
        html = rendered.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        pane = soup.select_one(".paper-pane")
        if pane is None:
            raise AssertionError("Rendered output missing .paper-pane")
        if pane.get("data-paper-html-source") != "pandoc":
            raise AssertionError("Rendered output missing pandoc source provenance")
        if pane.get("data-source-fidelity") != "deterministic":
            raise AssertionError("Rendered output missing deterministic source fidelity")
        if pane.get("data-annotation-mode") != "overlay-only":
            raise AssertionError("Rendered output must use overlay-only annotation mode")
        if not pane.get("data-source-hash", "").startswith("sha256:"):
            raise AssertionError("Rendered output missing source hash")
        sentence_ids = [node.get("data-sentence-id") for node in soup.select(".paper-sentence")]
        if count < 3 or len(sentence_ids) < 3:
            raise AssertionError(f"Expected at least three sentence spans, got count={count} ids={sentence_ids}")
        if len(sentence_ids) != len(set(sentence_ids)):
            raise AssertionError(f"Sentence ids are not unique: {sentence_ids}")
        if not raw.exists():
            raise AssertionError("Source HTML artifact was not written")


def test_render_paper_html_overlays_annotations_without_rewriting_body() -> None:
    if shutil.which("pandoc") is None:
        print("pandoc unavailable; skipping render_paper_html annotation smoke test")
        return
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\section{Intro}
First issue sentence. Clean sentence.
\end{document}
""",
            encoding="utf-8",
        )
        annotated_once = tmp / "seed.html"
        module.render(tex, annotated_once)
        seed_html = annotated_once.read_text(encoding="utf-8")
        seed_soup = BeautifulSoup(seed_html, "lxml")
        target_id = seed_soup.select_one(".paper-sentence")["data-sentence-id"]
        annotations = tmp / "annotations.json"
        annotations.write_text(
            json.dumps(
                {
                    "annotations": [
                        {
                            "sentence_id": target_id,
                            "severity": "major",
                            "issue_type": "claim",
                            "issue_id": "A1",
                            "title": "Claim needs evidence",
                            "problem": "The sentence asserts a result without context.",
                            "why": "Readers cannot verify the basis.",
                            "principle": "Claim strength must match evidence.",
                            "task": "Add evidence or narrow the claim.",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        output = tmp / "annotated.html"
        module.render(tex, output, annotations_path=annotations)
        soup = BeautifulSoup(output.read_text(encoding="utf-8"), "lxml")
        target = soup.select_one(f'.paper-sentence[data-sentence-id="{target_id}"]')
        if target is None or "has-annotation" not in target.get("class", []):
            raise AssertionError("Annotation target was not marked in the paper body")
        card = soup.select_one(f'[data-target-sentence="{target_id}"]')
        if card is None or "Claim needs evidence" not in card.get_text(" ", strip=True):
            raise AssertionError("Annotation card was not rendered")
        if not card.has_attr("hidden"):
            raise AssertionError("Annotation card should be hidden until the target sentence is activated")
        panel = soup.select_one("#annotation-panel")
        if panel is None or panel.get("data-empty") != "true":
            raise AssertionError("Annotation panel should start in the empty/default state")
        if soup.select_one("[data-annotation-empty]") is None:
            raise AssertionError("Annotation panel is missing the click-to-open empty state")
        if soup.select_one(f'[data-scroll-target="{target_id}"]') is None:
            raise AssertionError("Annotation card should include a pointer back to the source sentence")
        if target.get_text(" ", strip=True) != "First issue sentence.":
            raise AssertionError("Annotation overlay rewrote the paper sentence")
        if "AriadnePaperReaderOpenAnnotation" not in str(soup):
            raise AssertionError("Annotation interaction API was not rendered")


def test_cleanup_removes_latex_layout_artifacts() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <div class="wrapfigure"><p><span>r</span><span>0.4</span><embed src="fig.pdf"></p></div>
  <div class="wraptable"><div class="adjustbox"><p><span>max width=0.38</span></p><table><tr><td>1</td></tr></table></div></div>
</body></html>
""",
        "lxml",
    )
    module.cleanup_pandoc_artifacts(soup)
    text = soup.get_text(" ", strip=True)
    if "max width" in text or "0.38" in text or text.startswith("r 0.4"):
        raise AssertionError(f"Layout parameters leaked into rendered text: {text!r}")
    if soup.select_one(".paper-float") is None:
        raise AssertionError("wrapfigure/wraptable was not tagged as a paper float")
    if soup.select_one("div.adjustbox") is not None:
        raise AssertionError("adjustbox wrapper should be removed")


def test_pdf_assets_are_external_by_default() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex_dir = tmp / "tex"
        html_dir = tmp / "html"
        asset_dir = html_dir / "paper_reader_assets"
        tex_dir.mkdir()
        html_dir.mkdir()
        pdf = tex_dir / "fig.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        soup = BeautifulSoup(
            """
<html><body>
  <figure><embed src="fig.pdf"></figure>
</body></html>
""",
            "lxml",
        )

        def fake_pdf_to_png(pdf_path: Path, output_png_path: Path) -> Path | None:
            if pdf_path != pdf.resolve():
                raise AssertionError(f"Unexpected PDF path: {pdf_path}")
            output_png_path.parent.mkdir(parents=True, exist_ok=True)
            output_png_path.write_bytes(b"png")
            return output_png_path

        original = module.pdf_embed_to_png_asset
        module.pdf_embed_to_png_asset = fake_pdf_to_png
        try:
            converted = module.rasterize_pdf_assets(
                soup,
                tex_dir,
                asset_dir=asset_dir,
                html_dir=html_dir,
            )
        finally:
            module.pdf_embed_to_png_asset = original

        image = soup.select_one("img.paper-asset-image")
        if converted != 1 or image is None:
            raise AssertionError("Expected local PDF embed to become an image asset")
        src = image.get("src", "")
        if src.startswith("data:image"):
            raise AssertionError("Default PDF asset rendering should not inline image bytes")
        if not src.startswith("paper_reader_assets/") or not src.endswith(".png"):
            raise AssertionError(f"Expected relative asset path, got {src!r}")
        if not (html_dir / src).exists():
            raise AssertionError("Rendered PNG asset was not written")
        if image.get("data-source-pdf") != "fig.pdf":
            raise AssertionError("Image should retain the original PDF source for visual audit traceability")


def test_sentence_wrapping_keeps_citations_inside_sentence() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <h1 id="intro">Intro</h1>
  <p>As shown in Table <a href="#tab">1</a>, RL improves recall. Next sentence.</p>
</body></html>
""",
        "lxml",
    )
    count = module.wrap_sentences(soup)
    sentences = [node.get_text("", strip=True) for node in soup.select(".paper-sentence")]
    if count != 2:
        raise AssertionError(f"Expected two sentence spans, got {count}: {sentences}")
    if not any("As shown in Table" in sentence and "1" in sentence and "RL improves recall." in sentence for sentence in sentences):
        raise AssertionError(f"Citation was split out of its sentence: {sentences}")


def test_sentence_wrapping_preserves_list_paragraph_structure() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p>Contributions:</p>
  <ul>
    <li><p>First contribution sentence.</p></li>
    <li><p>Second contribution sentence.</p></li>
  </ul>
</body></html>
""",
        "lxml",
    )
    module.wrap_sentences(soup)
    if soup.select("li > span.paper-sentence > p"):
        raise AssertionError(f"List paragraphs must not be wrapped by outer inline spans: {soup.select_one('ul')}")
    if soup.select(".paper-sentence .paper-sentence"):
        raise AssertionError(f"Sentence spans must not nest inside each other: {soup.select_one('ul')}")
    texts = [node.get_text(" ", strip=True) for node in soup.select("li p .paper-sentence")]
    if texts != ["First contribution sentence.", "Second contribution sentence."]:
        raise AssertionError(f"Expected list paragraph text to remain wrapped in-place, got {texts}")


def test_paragraph_ids_reset_at_section_boundaries() -> None:
    module = load_module()

    def paragraph_ids_by_text(body_html: str) -> dict[str, str]:
        soup = BeautifulSoup(body_html, "lxml")
        module.wrap_sentences(soup)
        ids: dict[str, str] = {}
        for paragraph in soup.select("p[data-paragraph-id]"):
            ids[paragraph.get_text(" ", strip=True)] = paragraph["data-paragraph-id"]
        return ids

    original = paragraph_ids_by_text(
        """
<html><body>
  <h1 id="introduction">Introduction</h1>
  <p>Intro paragraph one.</p>
  <p>Intro paragraph two.</p>
  <h1 id="method">Method</h1>
  <p>Method paragraph one.</p>
  <p>Method paragraph two.</p>
  <h1 id="results">Results</h1>
  <p>Results paragraph.</p>
</body></html>
"""
    )
    inserted = paragraph_ids_by_text(
        """
<html><body>
  <h1 id="introduction">Introduction</h1>
  <p>Intro paragraph one.</p>
  <p>Inserted new intro paragraph.</p>
  <p>Intro paragraph two.</p>
  <h1 id="method">Method</h1>
  <p>Method paragraph one.</p>
  <p>Method paragraph two.</p>
  <h1 id="results">Results</h1>
  <p>Results paragraph.</p>
</body></html>
"""
    )
    if inserted["Intro paragraph two."] != "p-introduction-003":
        raise AssertionError(f"Inserted intro paragraph should shift only later Introduction ids, got {inserted}")
    for text in ("Method paragraph one.", "Method paragraph two.", "Results paragraph."):
        if inserted[text] != original[text]:
            raise AssertionError(f"{text!r} id drifted across section boundary: {original[text]} -> {inserted[text]}")
    expected_ids = {
        "Method paragraph one.": "p-method-001",
        "Method paragraph two.": "p-method-002",
        "Results paragraph.": "p-results-001",
    }
    for text, expected_id in expected_ids.items():
        if inserted[text] != expected_id:
            raise AssertionError(f"Expected {text!r} to use section-local id {expected_id}, got {inserted[text]}")


def test_restore_latex_labels_for_wrapfigure_and_tables() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        child = tmp / "fig.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\input{fig}
\begin{table}
\begin{tabular}{cc}
A & B \\
\end{tabular}
\label{tab:tiny}
\end{table}
\end{document}
""",
            encoding="utf-8",
        )
        child.write_text(
            r"""
\begin{wrapfigure}{r}{0.4\textwidth}
\includegraphics{Figures/demo}
\label{fig:demo}
\end{wrapfigure}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <div class="wrapfigure paper-float paper-figure"><img class="paper-asset-image" data-source-pdf="Figures/demo.pdf"></div>
  <div class="paper-table"><table><tr><td>A</td></tr></table></div>
</body></html>
""",
            "lxml",
        )
        module.restore_latex_labels(soup, tex)
        if soup.find(id="fig:demo") is None:
            raise AssertionError("Expected wrapfigure label to be restored")
        if soup.find(id="tab:tiny") is None:
            raise AssertionError("Expected table label to be restored")


def test_ensure_references_heading_for_csl_entries() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p>Final body sentence.</p>
  <div id="refs" class="references csl-bib-body"><div class="csl-entry">Reference item.</div></div>
</body></html>
""",
        "lxml",
    )
    module.ensure_references_heading(soup)
    heading = soup.find(id="references")
    if heading is None or heading.get_text(" ", strip=True) != "References":
        raise AssertionError("Expected deterministic References heading before #refs")
    if heading.find_next_sibling(id="refs") is None:
        raise AssertionError("References heading should be inserted immediately before #refs")


def test_bibliography_paths_find_tex_bibliography_files() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        bib = tmp / "refs.bib"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
Citation \citep{demo}.
\bibliographystyle{plainnat}
\bibliography{refs}
\end{document}
""",
            encoding="utf-8",
        )
        bib.write_text(
            r"""
@article{demo,
  title={Demo Title},
  author={Author, A.},
  journal={Journal},
  year={2024}
}
""",
            encoding="utf-8",
        )
        bibs = module.bibliography_paths(tex)
        if bibs != [bib.resolve()]:
            raise AssertionError(f"Expected bibliography file to be discovered, got {bibs}")


def test_imports_existing_review_html_without_dropping_unanchored_notes() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        review = tmp / "review.html"
        review.write_text(
            """
<!doctype html><html><body>
<section id="top-priorities">
  <article class="finding" id="F1" data-severity="blocker">
    <div class="finding-title"><span class="badge blocker">Blocker</span><span>Mechanism overclaim</span></div>
    <p class="field"><strong>位置：</strong>Abstract</p>
    <p class="field"><strong>片段：</strong><q>redistributes probability mass over existing knowledge</q></p>
    <p class="field"><strong>问题：</strong>机制表述强于证据。</p>
    <p class="field"><strong>读者影响：</strong>读者会追问参数级证据。</p>
    <p class="field"><strong>修改建议：</strong>降级为 behavioral interpretation。</p>
  </article>
</section>
<section id="margin-notes">
  <table>
    <tr><th>位置</th><th>检查维度</th><th>原句/片段</th><th>问题</th><th>为什么影响读者</th><th>修改建议</th><th>严重度</th></tr>
    <tr data-severity="major"><td>Intro</td><td>scope</td><td>not present in paper</td><td>全局意见。</td><td>需要保留。</td><td>不要丢。</td><td>Major</td></tr>
  </table>
</section>
</body></html>
""",
            encoding="utf-8",
        )
        annotations = module.load_review_html_annotations(review)
        if len(annotations) != 2:
            raise AssertionError(f"Expected two imported annotations, got {len(annotations)}")
        soup = BeautifulSoup(
            """
<html><body>
  <p><span class="paper-sentence" data-sentence-id="s1">The result redistributes probability mass over existing knowledge.</span></p>
</body></html>
""",
            "lxml",
        )
        assigned = module.assign_sentence_targets(soup, annotations)
        applied = module.apply_annotations(soup, assigned)
        anchored = [item for item in applied if item.get("sentence_id")]
        unanchored = [item for item in applied if item.get("unanchored") == "true"]
        if len(anchored) != 1 or anchored[0].get("sentence_id") != "s1":
            raise AssertionError(f"Expected one anchored annotation on s1, got {anchored}")
        if len(unanchored) != 1:
            raise AssertionError(f"Expected unmatched review note to be preserved, got {unanchored}")
        cards_html = module.render_annotation_cards(applied)
        if "未定位到具体句子的批注（1）" not in cards_html:
            raise AssertionError("Unanchored imported notes should be rendered in the fallback drawer")
        cards_soup = BeautifulSoup(cards_html, "lxml")
        unanchored_card = cards_soup.select_one(".annotation-card[data-unanchored='true']")
        if unanchored_card is None:
            raise AssertionError("Expected unmatched review note to render as an unanchored annotation card")
        if unanchored_card.has_attr("data-target-sentence"):
            raise AssertionError("Unanchored annotation cards must not pretend to target a paper sentence")
        anchored_card = cards_soup.select_one("[data-target-sentence='s1']")
        if anchored_card is None or not anchored_card.has_attr("hidden"):
            raise AssertionError("Anchored annotation cards should remain hidden until their sentence is activated")


def test_multiple_annotations_on_one_sentence_get_unique_cards() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p><span class="paper-sentence" data-sentence-id="s1">One overloaded sentence.</span></p>
</body></html>
""",
        "lxml",
    )
    applied = module.apply_annotations(
        soup,
        [
            {
                "sentence_id": "s1",
                "severity": "major",
                "issue_type": "claim",
                "issue_id": "A1",
                "title": "Claim issue",
                "problem": "First problem.",
            },
            {
                "sentence_id": "s1",
                "severity": "minor",
                "issue_type": "prose",
                "issue_id": "A2",
                "title": "Prose issue",
                "problem": "Second problem.",
            },
        ],
    )
    target = soup.select_one(".paper-sentence")
    if target is None:
        raise AssertionError("Missing paper sentence")
    if target.get("data-inline-label") != "Major · 2 issues":
        raise AssertionError(f"Expected multi-issue inline label, got {target.get('data-inline-label')}")
    describedby = target.get("aria-describedby", "").split()
    if describedby != ["ann-s1-1", "ann-s1-2"]:
        raise AssertionError(f"Expected aria-describedby to list both cards, got {describedby}")
    cards_soup = BeautifulSoup(module.render_annotation_cards(applied), "lxml")
    card_ids = [card.get("id") for card in cards_soup.select(".annotation-card[data-target-sentence='s1']")]
    if card_ids != ["ann-s1-1", "ann-s1-2"]:
        raise AssertionError(f"Expected unique cards for each annotation, got {card_ids}")


def test_annotation_cards_prefer_self_check_question_over_task() -> None:
    module = load_module()
    cards_soup = BeautifulSoup(
        module.render_annotation_cards(
            [
                {
                    "sentence_id": "s1",
                    "severity": "minor",
                    "issue_type": "mechanics",
                    "issue_id": "A1",
                    "title": "Agreement issue",
                    "problem": "The verb does not agree with the subject.",
                    "principle": "语法、句法、拼写、标点和数量指称必须正确",
                    "task": "Change 'denotes' to 'denote'.",
                    "self_check": "这句话的主谓是否一致？",
                }
            ]
        ),
        "lxml",
    )
    card_text = cards_soup.get_text(" ", strip=True)
    if "自改问题" not in card_text:
        raise AssertionError("Annotation card should expose self-check questions")
    if "这句话的主谓是否一致？" not in card_text:
        raise AssertionError("Annotation card should prefer the self_check field")
    if "下一稿任务 / 自改问题" in card_text or "Change 'denotes' to 'denote'." in card_text:
        raise AssertionError("Annotation card should not show command-style task text when self_check is present")


def test_annotation_cards_hide_mechanical_anchor_metadata() -> None:
    module = load_module()
    cards_soup = BeautifulSoup(
        module.render_annotation_cards(
            [
                {
                    "sentence_id": "s1",
                    "target_level": "sentence",
                    "severity": "minor",
                    "issue_type": "prose",
                    "issue_id": "A1",
                    "title": "Overloaded sentence",
                    "problem": "The sentence carries too many conditions.",
                    "why": "Readers must reconstruct the setup before seeing the claim.",
                    "principle": "句首接旧信息，句尾放新信息",
                    "self_check": "这句话能否拆成 setup 和 takeaway？",
                    "location": "p-intro-001, sentence 2",
                    "snippet": "We study this question in a controlled setting.",
                    "evidence_basis": "sentence span generated from source-derived paper-reader HTML",
                    "verification_method": "data-sentence-id from section-paragraph-sentence-v2 scheme",
                    "confidence": "high",
                    "severity_rationale": "Minor",
                }
            ]
        ),
        "lxml",
    )
    card_text = cards_soup.get_text(" ", strip=True)
    for hidden_text in (
        "位置",
        "原句/片段",
        "证据/验证",
        "核查依据",
        "p-intro-001",
        "We study this question",
        "source-derived paper-reader",
        "data-sentence-id",
        "置信度",
        "严重度理由",
    ):
        if hidden_text in card_text:
            raise AssertionError(f"Mechanical metadata should stay out of margin cards: {hidden_text}")
    for visible_text in ("问题是什么", "为什么有问题", "违反原则", "自改问题"):
        if visible_text not in card_text:
            raise AssertionError(f"Expected teaching field in annotation card: {visible_text}")


def test_annotation_cards_show_meaningful_numeric_evidence() -> None:
    module = load_module()
    cards_soup = BeautifulSoup(
        module.render_annotation_cards(
            [
                {
                    "sentence_id": "s1",
                    "target_level": "sentence",
                    "severity": "major",
                    "issue_type": "numeric",
                    "issue_id": "A1",
                    "title": "Average mismatch",
                    "problem": "The prose average does not match the visible table cells.",
                    "why": "Readers cannot verify the headline number from the table.",
                    "principle": "不要让读者做翻译题/查字典题/算术题",
                    "self_check": "这个数字能否从表格直接复算？",
                    "evidence_basis": "Table 1 visible cells",
                    "verification_method": "visible arithmetic mean recomputed from table",
                    "reported_value": "27%",
                    "visible_computed_value": "35.77%",
                    "delta": "8.77 pp",
                    "aggregation_caveat": "Excluding SimpleQA changes the denominator.",
                }
            ]
        ),
        "lxml",
    )
    card_text = cards_soup.get_text(" ", strip=True)
    if "核查依据" not in card_text or "Table 1 visible cells" not in card_text:
        raise AssertionError("Meaningful numeric evidence should remain visible")
    for expected in ("表中数值", "可见复算值", "差值", "口径说明"):
        if expected not in card_text:
            raise AssertionError(f"Numeric details should remain visible: {expected}")


def test_missing_explicit_sentence_id_falls_back_to_snippet_match() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p><span class="paper-sentence" data-sentence-id="new-id">Limitations are discussed in Section 6.</span></p>
</body></html>
""",
        "lxml",
    )
    assigned = module.assign_sentence_targets(
        soup,
        [
            {
                "sentence_id": "old-id",
                "snippet": "Limitations are discussed in Section 6",
                "title": "Checklist limitation anchor",
            }
        ],
    )
    if assigned[0].get("sentence_id") != "new-id":
        raise AssertionError(f"Expected stale id to be recovered by snippet matching, got {assigned}")


def test_paragraph_section_and_paper_annotations_render_as_bubbles() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <h1 id="intro">Intro</h1>
  <p data-paragraph-id="p-intro-001"><span class="paper-sentence" data-sentence-id="s1">Paragraph body.</span></p>
</body></html>
""",
        "lxml",
    )
    applied = module.apply_annotations(
        soup,
        [
            {
                "target_level": "paragraph",
                "paragraph_id": "p-intro-001",
                "severity": "major",
                "issue_type": "structure",
                "issue_id": "P1",
                "short": "段落任务不清",
                "title": "Paragraph job is unclear",
            },
            {
                "target_level": "section",
                "section_id": "intro",
                "severity": "minor",
                "issue_type": "flow",
                "issue_id": "S1",
                "short": "缺少章节桥",
                "title": "Section needs a bridge",
            },
            {
                "target_level": "paper",
                "severity": "major",
                "issue_type": "paper",
                "issue_id": "W1",
                "short": "主线需收紧",
                "title": "Whole-paper thread needs tightening",
            },
        ],
    )
    paragraph = soup.select_one('[data-paragraph-id="p-intro-001"]')
    heading = soup.find(id="intro")
    overview = soup.find(id="paper-overview-annotations")
    if paragraph is None or "has-paragraph-annotation" not in paragraph.get("class", []):
        raise AssertionError(f"Paragraph annotation bubble was not attached: {paragraph}")
    if heading is None or "has-section-annotation" not in heading.get("class", []):
        raise AssertionError(f"Section annotation bubble was not attached: {heading}")
    if overview is None or "has-paper-annotation" not in overview.get("class", []):
        raise AssertionError("Paper-level overview annotation was not rendered")
    cards_soup = BeautifulSoup(module.render_annotation_cards(applied), "lxml")
    if cards_soup.select_one('[data-target-paragraph="p-intro-001"]') is None:
        raise AssertionError("Paragraph annotation card missing target")
    if cards_soup.select_one('[data-target-section="intro"]') is None:
        raise AssertionError("Section annotation card missing target")
    if cards_soup.select_one('[data-target-paper="paper"]') is None:
        raise AssertionError("Paper annotation card missing target")


def test_issue_artifacts_render_as_unanchored_annotation_cards() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        issues_dir = tmp / "issue_artifacts"
        issues_dir.mkdir()
        (issues_dir / "layout_issues.json").write_text(
            json.dumps(
                {
                    "artifact_type": "ariadne_issue_artifact",
                    "domain": "layout",
                    "context_policy": "model_readable_issue_only",
                    "producer": "layout_agent",
                    "status": "completed",
                    "source_artifacts": [],
                    "coverage": {"checked": 1, "issues": 1, "skipped": 0},
                    "issues": [
                        {
                            "local_id": "L1",
                            "severity": "Major",
                            "issue_type": "layout",
                            "title": "Main table is cramped",
                            "diagnosis": "The main result table is hard to scan.",
                            "reader_friction": "The evidence is hard to compare.",
                            "writing_principle": "低认知负担 / reader-first",
                            "self_check": "Can the table be read without zooming?",
                            "evidence_refs": ["layout-p001-001"],
                            "confidence": "medium",
                            "severity_rationale": "It affects main evidence.",
                            "downgrade_condition": "Readable compiled table.",
                            "render_hint": {"anchor": "page:1", "display_group": "submission-readiness"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        annotations = module.load_issue_artifact_annotations(issues_dir)
    if len(annotations) != 1:
        raise AssertionError(f"Expected one issue-artifact annotation, got {annotations}")
    annotation = annotations[0]
    if annotation["issue_id"] != "layout:L1":
        raise AssertionError(f"Expected scoped issue id, got {annotation['issue_id']}")
    if annotation.get("unanchored") != "true":
        raise AssertionError("page-level issue artifact should render as unanchored card")
    cards = module.render_annotation_cards(annotations)
    if "Main table is cramped" not in cards or "submission-readiness" not in cards:
        raise AssertionError("Issue artifact annotation card did not preserve title/display group")


def main() -> int:
    test_render_paper_html_wraps_source_sentences_with_provenance()
    test_render_paper_html_overlays_annotations_without_rewriting_body()
    test_cleanup_removes_latex_layout_artifacts()
    test_sentence_wrapping_keeps_citations_inside_sentence()
    test_sentence_wrapping_preserves_list_paragraph_structure()
    test_paragraph_ids_reset_at_section_boundaries()
    test_restore_latex_labels_for_wrapfigure_and_tables()
    test_ensure_references_heading_for_csl_entries()
    test_bibliography_paths_find_tex_bibliography_files()
    test_imports_existing_review_html_without_dropping_unanchored_notes()
    test_multiple_annotations_on_one_sentence_get_unique_cards()
    test_annotation_cards_prefer_self_check_question_over_task()
    test_annotation_cards_hide_mechanical_anchor_metadata()
    test_annotation_cards_show_meaningful_numeric_evidence()
    test_missing_explicit_sentence_id_falls_back_to_snippet_match()
    test_paragraph_section_and_paper_annotations_render_as_bubbles()
    test_issue_artifacts_render_as_unanchored_annotation_cards()
    print("render_paper_html regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
