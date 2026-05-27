#!/usr/bin/env python3
"""Regression checks for source-derived paper-reader HTML rendering."""

from __future__ import annotations

import importlib.util
import json
import os
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


def write_fake_pdftotext(directory: Path, bbox_html: str) -> None:
    executable = directory / "pdftotext"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write({bbox_html!r})\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def pdf_bbox_page(line_specs: list[tuple[float, float, float, float]]) -> str:
    lines = "\n".join(
        f'<line xMin="{x_min}" yMin="{y_min}" xMax="{x_max}" yMax="{y_max}"></line>'
        for x_min, y_min, x_max, y_max in line_specs
    )
    return f'<doc><page width="600" height="800">{lines}</page></doc>'


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


def test_latex_float_width_classes_distinguish_figure_from_figure_star() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\begin{figure}
\includegraphics{fig/single}
\label{fig:single}
\end{figure}
\begin{figure*}
\includegraphics{fig/wide}
\label{fig:wide}
\end{figure*}
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <figure id="fig:single"><img data-source-pdf="fig/single.pdf"></figure>
  <figure id="fig:wide"><img data-source-pdf="fig/wide.pdf"></figure>
</body></html>
""",
            "lxml",
        )
        marked = module.mark_latex_float_widths(soup, tex)
        single = soup.find(id="fig:single")
        wide = soup.find(id="fig:wide")
        if marked != 2 or single is None or wide is None:
            raise AssertionError(f"Expected both floats to be marked, got marked={marked}, soup={soup}")
        if "paper-float-single" not in single.get("class", []) or "paper-float-wide" in single.get("class", []):
            raise AssertionError(f"Regular figure should remain single-column: {single}")
        if "paper-float-wide" not in wide.get("class", []):
            raise AssertionError(f"figure* should be marked wide: {wide}")


def test_broken_adjustbox_table_is_rebuilt_from_latex_tabular() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\begin{table*}
\caption{Watermark and evaluation setup.}
\label{tab:setup}
\begin{adjustbox}{max width=\textwidth}
\begin{tabular}{@{}L{0.22\textwidth}L{0.24\textwidth}L{0.48\textwidth}@{}}
\toprule
Ablation & Payload / detector & Watermark and metric \\
\midrule
20-bit sweep & Payload space $2^{20}$; segmented decoding. & $\gamma=0.5$; exact message acc. \\
RS+ECC & Payload space $2^{20}$; RS-coded segmented decoding. & $\delta\in\{1.0,1.5,\ldots,4.5\}$; no attack. \\
\bottomrule
\end{tabular}
\end{adjustbox}
\end{table*}
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <div class="table* paper-table" id="tab:setup"><div class="tabular"><p>@L0.22L0.24L0.48@ Ablation & Payload / detector & Watermark and metric</p></div></div>
</body></html>
""",
            "lxml",
        )
        replaced = module.replace_broken_latex_tables(soup, tex)
        table = soup.select_one("#tab\\:setup table")
        if replaced != 1 or table is None:
            raise AssertionError(f"Expected broken table to be rebuilt, got replaced={replaced}, soup={soup}")
        text = table.get_text(" ", strip=True)
        if "@L" in text or "Payload / detector" not in text or "RS+ECC" not in text:
            raise AssertionError(f"Rebuilt table text is wrong: {text}")
        if table.find("caption") is None or "Table 1:" not in table.find("caption").get_text(" ", strip=True):
            raise AssertionError("Rebuilt table should include a numbered caption")


def test_rebuilt_table_cells_clean_nested_tabular_linebreaks() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\begin{table*}
\caption{Payload and segment layouts.}
\label{tab:layouts}
\begin{tabular}{@{}ll@{}}
\toprule
Experiment & Segment layouts \\
\midrule
20-bit sweep & \begin{tabular}[t]{@{}l@{}}$B=20$\\$s=1,2$\\$n=s$\end{tabular} \\
\bottomrule
\end{tabular}
\end{table*}
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <div class="table* paper-table" id="tab:layouts"><div class="tabular"><p>@L0.3L0.7@ Experiment & Segment layouts</p></div></div>
</body></html>
""",
            "lxml",
        )
        replaced = module.replace_broken_latex_tables(soup, tex)
        table = soup.select_one("#tab\\:layouts table")
        if replaced != 1 or table is None:
            raise AssertionError(f"Expected nested-tabular table to be rebuilt: {soup}")
        cell = table.find("tbody").find_all("td")[1]
        text = cell.get_text(" ", strip=True)
        if "\\begin{tabular}" in str(cell) or "\\\\" in str(cell) or "B=20" not in text or "n=s" not in text:
            raise AssertionError(f"Nested tabular cleanup failed: {cell}")
        if not cell.find("br"):
            raise AssertionError(f"Nested tabular linebreaks should become br elements: {cell}")


def test_float_caption_numbers_are_added_from_latex_order() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\begin{figure}
\includegraphics{fig/a}
\caption{First figure caption.}
\label{fig:a}
\end{figure}
\begin{table}
\caption{First table caption.}
\label{tab:a}
\begin{tabular}{ll}
A & B \\
\end{tabular}
\end{table}
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <figure id="fig:a"><figcaption>First figure caption.</figcaption></figure>
  <div id="tab:a" class="paper-table"><table><caption>First table caption.</caption><tbody><tr><td>A</td><td>B</td></tr></tbody></table></div>
</body></html>
""",
            "lxml",
        )
        updated = module.add_float_caption_numbers(soup, tex)
        if updated != 2:
            raise AssertionError(f"Expected two numbered captions, got {updated}: {soup}")
        if "Figure 1:" not in soup.find("figcaption").get_text(" ", strip=True):
            raise AssertionError("Figure caption number missing")
        if "Table 1:" not in soup.find("caption").get_text(" ", strip=True):
            raise AssertionError("Table caption number missing")


def test_restore_latex_labels_does_not_shift_existing_table_ids() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\begin{table}
\caption{First table.}
\label{tab:first}
\begin{tabular}{ll}
A & B \\
\end{tabular}
\end{table}
\begin{table}
\caption{Second table.}
\label{tab:second}
\begin{tabular}{ll}
C & D \\
\end{tabular}
\end{table}
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <div id="tab:first" class="paper-table"><table><caption>First table.</caption></table></div>
  <div class="paper-table"><table><caption>Second table.</caption></table></div>
</body></html>
""",
            "lxml",
        )
        restored = module.restore_latex_labels(soup, tex)
        first = soup.find(id="tab:first")
        second = soup.find(id="tab:second")
        misplaced_anchor = first.find(id="tab:second") if first is not None else None
        if restored != 1 or second is None:
            raise AssertionError(f"Expected only the missing second table label to be restored: restored={restored}, soup={soup}")
        if misplaced_anchor is not None:
            raise AssertionError("Second table label was incorrectly inserted into the already-labeled first table")


def test_table_labels_are_restored_by_content_when_pandoc_reorders_tables() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\begin{table*}
\caption{Main results caption.}
\label{tab:main}
\begin{tabular}{lrr}
Method & NQ & PopQA \\
Base & 21.42 & 16.96 \\
RL & 34.12 & 22.27 \\
\end{tabular}
\end{table*}
\begin{wraptable}{r}{0.35\textwidth}
\caption{Algorithm ablation caption.}
\label{tab:algo}
\begin{tabular}{lrrr}
Method & Llama & OLMo & Qwen \\
Pre-RL & 30.15 & 22.79 & 21.42 \\
GRPO & 46.39 & 36.91 & 34.12 \\
PPO & 46.42 & 37.12 & 32.48 \\
\end{tabular}
\end{wraptable}
\begin{table*}
\caption{Model scale caption.}
\label{tab:scale}
\begin{tabular}{lrrr}
NQ & Qwen2.5-7B & Qwen2.5-14B & Qwen2.5-72B \\
Pre-RL & 21.42 & 25.24 & 34.64 \\
Post-RL & 34.12 & 41.88 & 49.61 \\
\end{tabular}
\end{table*}
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <div class="paper-table"><table><caption>Wrong leading caption.</caption><tbody><tr><th>Method</th><th>NQ</th><th>PopQA</th></tr><tr><td>Base</td><td>21.42</td><td>16.96</td></tr><tr><td>RL</td><td>34.12</td><td>22.27</td></tr></tbody></table></div>
  <div class="paper-table"><table><caption>Wrong middle caption.</caption><tbody><tr><th>NQ</th><th>Qwen2.5-7B</th><th>Qwen2.5-14B</th><th>Qwen2.5-72B</th></tr><tr><td>Pre-RL</td><td>21.42</td><td>25.24</td><td>34.64</td></tr><tr><td>Post-RL</td><td>34.12</td><td>41.88</td><td>49.61</td></tr></tbody></table></div>
  <div class="paper-table"><table><caption>Wrong trailing caption.</caption><tbody><tr><th>Method</th><th>Llama</th><th>OLMo</th><th>Qwen</th></tr><tr><td>Pre-RL</td><td>30.15</td><td>22.79</td><td>21.42</td></tr><tr><td>GRPO</td><td>46.39</td><td>36.91</td><td>34.12</td></tr><tr><td>PPO</td><td>46.42</td><td>37.12</td><td>32.48</td></tr></tbody></table></div>
</body></html>
""",
            "lxml",
        )
        module.restore_latex_labels(soup, tex)
        module.add_float_caption_numbers(soup, tex)
        main = soup.find(id="tab:main")
        algo = soup.find(id="tab:algo")
        scale = soup.find(id="tab:scale")
        if main is None or "Main results caption" not in main.get_text(" ", strip=True) or "PopQA" not in main.get_text(" ", strip=True):
            raise AssertionError(f"Main table label/caption should stay with main-results cells: {soup}")
        if algo is None or "Table 2: Algorithm ablation caption" not in algo.get_text(" ", strip=True) or "PPO" not in algo.get_text(" ", strip=True):
            raise AssertionError(f"Algorithm table should be Table 2 and keep PPO cells: {soup}")
        if scale is None or "Table 3: Model scale caption" not in scale.get_text(" ", strip=True) or "Qwen2.5-72B" not in scale.get_text(" ", strip=True):
            raise AssertionError(f"Model-scale table should be Table 3 and keep scale cells: {soup}")


def test_commented_inputs_do_not_shift_float_numbers_or_references() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        active = tmp / "active_table.tex"
        commented = tmp / "commented_table.tex"
        tex = tmp / "paper.tex"
        active.write_text(
            r"""
\begin{table}
\caption{Active table caption.}
\label{tab:active}
\begin{tabular}{ll}
A & B \\
\end{tabular}
\end{table}
""",
            encoding="utf-8",
        )
        commented.write_text(
            r"""
\begin{table}
\caption{Commented-out table caption.}
\label{tab:commented}
\begin{tabular}{ll}
X & Y \\
\end{tabular}
\end{table}
""",
            encoding="utf-8",
        )
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
% \input{commented_table}
\input{active_table}
See Table~\ref{tab:active}.
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <div id="tab:active" class="paper-table"><table><caption>Active table caption.</caption><tbody><tr><td>A</td><td>B</td></tr></tbody></table></div>
  <p>See Table <a data-reference="tab:active" href="#tab:active">[tab:active]</a>.</p>
</body></html>
""",
            "lxml",
        )
        module.add_float_caption_numbers(soup, tex)
        module.sync_float_reference_numbers(soup, tex)
        text = soup.get_text(" ", strip=True)
        if "Commented-out table caption" in text:
            raise AssertionError(f"Commented input was expanded into the HTML model: {soup}")
        if "Table 1: Active table caption" not in text:
            raise AssertionError(f"Active table should remain Table 1: {soup}")
        if soup.find("a", attrs={"data-reference": "tab:active"}).get_text(" ", strip=True) != "1":
            raise AssertionError(f"Table reference should be synchronized to 1: {soup}")


def test_latex_caption_inline_markup_is_rendered_cleanly() -> None:
    module = load_module()
    soup = BeautifulSoup("<html><body><caption></caption></body></html>", "lxml")
    caption = soup.find("caption")
    module.append_latex_inline(soup, caption, r"Accuracy (\%) with \textbf{bold} values and Pass@$k$.")
    text = caption.get_text(" ", strip=True)
    if r"\%" in text or r"\textbf" in text or "Pass@ k" not in text:
        raise AssertionError(f"LaTeX caption markup should render as clean HTML text: {caption}")
    if caption.find("strong") is None or caption.find(class_="math-inline") is None:
        raise AssertionError(f"Expected inline bold and math markup in caption: {caption}")


def test_latex_paragraph_headings_are_not_display_numbered() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\section{Related Work}
\paragraph{Detection-stage gaps in multi-bit decoding}
Body sentence.
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <h1 id="related-work">Related Work</h1>
  <h4 id="detection-stage-gaps-in-multi-bit-decoding">Detection-stage gaps in multi-bit decoding</h4>
  <p>Body sentence.</p>
</body></html>
""",
            "lxml",
        )
        marked = module.mark_latex_paragraph_headings(soup, tex)
        module.ensure_display_section_numbers(soup)
        heading = soup.find(id="detection-stage-gaps-in-multi-bit-decoding")
        if marked != 1 or heading is None or "paper-run-in-heading" not in heading.get("class", []):
            raise AssertionError(f"Expected paragraph heading to be marked run-in: {heading}")
        if heading.get("data-section-number"):
            raise AssertionError(f"Paragraph heading should not receive display numbering: {heading}")


def test_restore_mathml_equation_labels_from_tex_annotations() -> None:
    module = load_module()
    soup = BeautifulSoup(
        r"""
<html><body>
  <p>Equation reference <a href="#eq:demo" data-reference="eq:demo">[eq:demo]</a>.</p>
  <math display="block"><semantics><mrow></mrow><annotation encoding="application/x-tex">\label{eq:demo} x=1</annotation></semantics></math>
</body></html>
""",
        "lxml",
    )
    restored = module.restore_mathml_labels(soup)
    if restored != 1 or soup.find(id="eq:demo") is None:
        raise AssertionError(f"Expected MathML label id to be restored, got restored={restored}, soup={soup}")


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


def test_bibliography_before_appendix_is_restored_after_pandoc_append() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\section{Body}
Body sentence.
\bibliography{refs}
\appendix
\section{Proof}\label{sec:proof}
Appendix sentence.
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <h1 id="body">Body</h1>
  <p>Body sentence.</p>
  <h1 id="sec:proof">Proof</h1>
  <p>Appendix sentence.</p>
  <h1 id="references">References</h1>
  <div id="refs" class="references csl-bib-body"><div class="csl-entry">Reference item.</div></div>
</body></html>
""",
            "lxml",
        )
        moved = module.restore_bibliography_position(soup, tex)
        refs = soup.find(id="references")
        appendix = soup.find(id="sec:proof")
        if not moved or refs is None or appendix is None:
            raise AssertionError(f"Expected references to move before appendix: moved={moved}, soup={soup}")
        if refs.find_next("h1") is not appendix:
            raise AssertionError("References heading should precede the first appendix heading")
        if refs.find_next_sibling(id="refs") is None:
            raise AssertionError("References body should move together with its heading")


def test_reused_source_restores_references_before_appendix_and_alpha_numbers() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        raw_html = tmp / "paper.source.html"
        out = tmp / "paper.html"
        assets = tmp / "assets"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\section{Intro}\label{sec:intro}
Body sentence.
\bibliography{refs}
\appendix
\section{Prompt Details}\label{apd:prompts}
Appendix sentence.
\subsection{Data Split}\label{apd:data}
Nested appendix sentence.
\end{document}
""",
            encoding="utf-8",
        )
        raw_html.write_text(
            module.source_artifact_shell(
                "Demo",
                """
<h1 id="sec:intro">Intro</h1>
<p><span class="paper-sentence" data-sentence-id="s-sec-intro-p001-s001">Body sentence.</span></p>
<h1 id="apd:prompts">Prompt Details</h1>
<p><span class="paper-sentence" data-sentence-id="s-apd-prompts-p001-s001">Appendix sentence.</span></p>
<h2 id="apd:data">Data Split</h2>
<p><span class="paper-sentence" data-sentence-id="s-apd-data-p001-s001">Nested appendix sentence.</span></p>
<h1 id="references">References</h1>
<div id="refs" class="references csl-bib-body"><div class="csl-entry">Reference item.</div></div>
""",
            ),
            encoding="utf-8",
        )

        soup, _, _ = module.prepare_source_soup(
            tex,
            raw_html,
            output_path=out,
            asset_dir=assets,
            inline_images=False,
            reuse_raw_html=True,
        )
        module.ensure_display_section_numbers(soup, tex)

        refs = soup.find(id="references")
        appendix = soup.find(id="apd:prompts")
        nested = soup.find(id="apd:data")
        if refs is None or appendix is None or nested is None:
            raise AssertionError(f"Expected refs and appendix headings in reused source: {soup}")
        if refs.find_next("h1") is not appendix:
            raise AssertionError(f"References should be restored before appendix in reused source: {soup}")
        if appendix.get("data-section-number") != "A" or nested.get("data-section-number") != "A.1":
            raise AssertionError(f"Appendix headings should use alpha numbering, got {appendix}, {nested}")


def test_appendix_section_reference_text_uses_alpha_number() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
\section{Intro}\label{sec:intro}
See Appendix~\ref{apd:prompts}.
\bibliography{refs}
\appendix
\section{Prompt Details}\label{apd:prompts}
Appendix sentence.
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <h1 id="sec:intro">Intro</h1>
  <p>See Appendix <a data-reference="apd:prompts" href="#apd:prompts">9</a>.</p>
  <h1 id="apd:prompts">Prompt Details</h1>
</body></html>
""",
            "lxml",
        )
        module.ensure_display_section_numbers(soup, tex)
        updated = module.sync_section_reference_numbers(soup)
        link = soup.find("a", attrs={"data-reference": "apd:prompts"})
        if updated != 1 or link is None or link.get_text(" ", strip=True) != "A":
            raise AssertionError(f"Appendix ref text should sync to alpha number: updated={updated}, soup={soup}")


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


def test_acl_review_front_matter_is_anonymized_and_not_numbered() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\usepackage[review]{acl}
\title{Demo ACL Paper}
\author{Jane Doe \\ Secret Lab \\ jane@example.com}
\begin{document}
\maketitle
\section{Introduction}
Intro sentence.
\end{document}
""",
            encoding="utf-8",
        )
        soup = BeautifulSoup(
            """
<html><body>
  <header id="title-block-header">
    <h1 class="title" id="demo-acl-paper">Demo ACL Paper</h1>
    <p class="author">Jane Doe<br>Secret Lab<br><code>jane@example.com</code></p>
    <div class="abstract"><div class="abstract-title">Abstract</div><p>Abstract sentence.</p></div>
  </header>
  <h1 id="introduction">Introduction</h1>
  <p>Intro sentence.</p>
</body></html>
""",
            "lxml",
        )
        module.normalize_front_matter(soup, tex)
        sentence_count = module.wrap_sentences(soup)
        module.ensure_display_section_numbers(soup)

        title = soup.select_one(".paper-title")
        author = soup.select_one(".paper-author")
        abstract = soup.select_one("body > .abstract")
        intro = soup.find(id="introduction")
        if title is None or title.get("id") != "demo-acl-paper" or title.get("data-section-number"):
            raise AssertionError(f"Title should be marked as unnumbered front matter: {title}")
        if author is None or author.get_text(" ", strip=True) != "Anonymous ACL submission":
            raise AssertionError(f"ACL review author block should be anonymized: {author}")
        if "Jane Doe" in soup.get_text(" ", strip=True) or "jane@example.com" in soup.get_text(" ", strip=True):
            raise AssertionError("Source author identity leaked after ACL review normalization")
        if author.select_one(".paper-sentence") is not None:
            raise AssertionError("Anonymous ACL author placeholder should not be sentence-reviewable")
        if abstract is None:
            raise AssertionError("Abstract should remain visible after title block normalization")
        if "paper-abstract-wide" in abstract.get("class", []):
            raise AssertionError("Abstract should not be forced full-width by venue-level defaults")
        if intro is None or intro.get("data-section-number") != "1":
            raise AssertionError(f"Introduction should be the first numbered section: {intro}")
        if sentence_count != 2:
            raise AssertionError(f"Expected abstract and introduction body sentences only, got {sentence_count}")
        if module.resolve_paper_layout(tex, "source") != "single":
            raise AssertionError("ACL review package alone should not force a two-column layout")
        tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% placeholder for layout resolver\n")
        if module.resolve_paper_layout(tex, "source") != "paged":
            raise AssertionError("A PDF page map without two-column evidence should default to paged single-column")


def test_neurips_source_layout_defaults_to_paged_single_when_pdf_exists() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\usepackage[preprint]{neurips_2026}
\begin{document}
Hello.
\end{document}
""",
            encoding="utf-8",
        )
        if module.resolve_paper_layout(tex, "source") != "single":
            raise AssertionError("NeurIPS package names should not be treated as two-column layout evidence")
        tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% placeholder for layout resolver\n")
        if module.resolve_paper_layout(tex, "source") != "paged":
            raise AssertionError("NeurIPS source layout should default to paged single-column when the PDF exists")


def test_pdf_geometry_selects_paged_two_column_without_conference_hack() -> None:
    module = load_module()
    two_column_lines: list[tuple[float, float, float, float]] = []
    for i in range(18):
        y = 120 + i * 18
        two_column_lines.append((52, y, 268, y + 10))
        two_column_lines.append((332, y, 548, y + 10))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        write_fake_pdftotext(tmp, pdf_bbox_page(two_column_lines))
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{tmp}{os.pathsep}{old_path}"
        try:
            tex = tmp / "paper.tex"
            tex.write_text(
                r"""
\documentclass{article}
\usepackage[review]{acl}
\begin{document}
Hello.
\end{document}
""",
                encoding="utf-8",
            )
            tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% fake bbox-driven layout resolver\n")
            if module.resolve_paper_layout(tex, "source") != "paged-two-column":
                raise AssertionError("Compiled PDF geometry, not ACL package name, should select paged two-column layout")
        finally:
            os.environ["PATH"] = old_path


def test_pdf_geometry_overrides_source_twocolumn_when_compiled_pdf_is_single() -> None:
    module = load_module()
    single_column_lines = [(70, 110 + i * 18, 530, 120 + i * 18) for i in range(24)]
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        write_fake_pdftotext(tmp, pdf_bbox_page(single_column_lines))
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{tmp}{os.pathsep}{old_path}"
        try:
            tex = tmp / "paper.tex"
            tex.write_text(
                r"""
\documentclass[twocolumn]{article}
\begin{document}
Hello.
\end{document}
""",
                encoding="utf-8",
            )
            tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% fake bbox-driven layout resolver\n")
            if module.resolve_paper_layout(tex, "source") != "paged":
                raise AssertionError("When a compiled PDF is readable, its geometry should override source twocolumn hints")
        finally:
            os.environ["PATH"] = old_path


def test_twocolumn_option_does_not_override_existing_pdf_layout() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass[twocolumn]{article}
\begin{document}
Hello.
\end{document}
""",
            encoding="utf-8",
        )
        if module.resolve_paper_layout(tex, "source") != "two-column":
            raise AssertionError("Generic twocolumn documentclass option should select two-column layout")
        tex.with_suffix(".pdf").write_bytes(b"%PDF-1.4\n% placeholder for layout resolver\n")
        if module.resolve_paper_layout(tex, "source") != "paged":
            raise AssertionError("When a compiled PDF exists, source layout should not promote to two-column without PDF geometry evidence")


def test_pdf_anonymous_front_matter_overrides_source_author_for_any_template() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\title{Demo Anonymous Paper}
\author{Jane Doe \\ Secret Lab \\ jane@example.com}
\begin{document}
\maketitle
\section{Introduction}
Intro sentence.
\end{document}
""",
            encoding="utf-8",
        )
        tex.with_suffix(".pdf").write_bytes(b"%PDF fake")
        soup = BeautifulSoup(
            """
<html><body>
  <header id="title-block-header">
    <h1 class="title" id="demo-anonymous-paper">Demo Anonymous Paper</h1>
    <p class="author">Jane Doe<br>Secret Lab<br><code>jane@example.com</code></p>
  </header>
  <h1 id="introduction">Introduction</h1>
  <p>Intro sentence.</p>
</body></html>
""",
            "lxml",
        )
        original = module.pdf_front_matter_is_anonymous
        try:
            module.pdf_front_matter_is_anonymous = lambda path: path == tex  # type: ignore[assignment]
            module.normalize_front_matter(soup, tex)
        finally:
            module.pdf_front_matter_is_anonymous = original  # type: ignore[assignment]

        author = soup.select_one(".paper-author")
        if author is None or author.get_text(" ", strip=True) != "Anonymous submission":
            raise AssertionError(f"PDF-anonymous front matter should anonymize source author block: {author}")
        if "Jane Doe" in soup.get_text(" ", strip=True) or "jane@example.com" in soup.get_text(" ", strip=True):
            raise AssertionError("Source author identity leaked despite anonymous compiled PDF")
        if author.get("data-anonymous-front-matter") != "true":
            raise AssertionError(f"Generic anonymous front matter should be marked: {author}")


def test_paged_layout_groups_existing_sentence_ids_without_coordinate_anchors() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <h1 id="intro" data-section-number="1">Introduction</h1>
  <p id="p-intro-001" class="paper-paragraph has-paragraph-annotation" data-paragraph-id="p-intro-001" data-has-issue="true" aria-describedby="ann-paragraph-p-intro-001-1">
    <button class="annotation-bubble paragraph">Major</button>
    <span class="paper-sentence has-annotation" data-sentence-id="s-intro-p001-s001">First sentence.</span>
    <span class="paper-sentence has-annotation" data-sentence-id="s-intro-p001-s002">Second sentence crosses the page.</span>
  </p>
  <p data-paragraph-id="p-intro-002"><span class="paper-sentence" data-sentence-id="s-intro-p002-s001">Third sentence.</span></p>
</body></html>
""",
        "lxml",
    )
    pages, assigned = module.split_children_into_pages(
        soup,
        {
            "s-intro-p001-s001": 1,
            "s-intro-p001-s002": 2,
            "s-intro-p002-s001": 2,
        },
    )
    if assigned != 3 or len(pages) != 2:
        raise AssertionError(f"Expected two page wrappers for three assigned sentences, got pages={len(pages)} assigned={assigned}")
    page_numbers = [page.get("data-page") for page in soup.select(".paper-page")]
    if page_numbers != ["1", "2"]:
        raise AssertionError(f"Unexpected page wrappers: {page_numbers}")
    sentence_ids = [node.get("data-sentence-id") for node in soup.select(".paper-sentence")]
    if sentence_ids != ["s-intro-p001-s001", "s-intro-p001-s002", "s-intro-p002-s001"]:
        raise AssertionError(f"Sentence ids changed during page wrapping: {sentence_ids}")
    if len(soup.select('[data-paragraph-id="p-intro-001"]')) != 1:
        raise AssertionError("Paged paragraph split should not duplicate the paragraph anchor")
    fragment = soup.select_one('[data-paragraph-fragment-of="p-intro-001"]')
    if fragment is None or fragment.get("data-paragraph-id"):
        raise AssertionError(f"Continuation paragraph fragment should be marked but not anchorable: {fragment}")


def test_paged_layout_preserves_abstract_and_keeps_overview_outside_pages() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <aside id="paper-overview-annotations">Whole paper note.</aside>
  <header id="title-block-header"><h1 class="paper-title">Demo</h1></header>
  <div class="abstract"><div class="abstract-title">Abstract</div><p data-paragraph-id="p-abstract-001"><span class="paper-sentence" data-sentence-id="s-abstract-p001-s001">Abstract sentence.</span></p></div>
  <h1 id="intro" data-section-number="1">Introduction</h1>
  <p data-paragraph-id="p-intro-001"><span class="paper-sentence" data-sentence-id="s-intro-p001-s001">Intro sentence.</span></p>
</body></html>
""",
        "lxml",
    )
    pages, assigned = module.split_children_into_pages(
        soup,
        {
            "s-abstract-p001-s001": 1,
            "s-intro-p001-s001": 1,
        },
    )
    if assigned != 2 or len(pages) != 1:
        raise AssertionError(f"Expected one paper page with two sentences, got pages={len(pages)} assigned={assigned}")
    if soup.select_one(".paper-page #paper-overview-annotations") is not None:
        raise AssertionError("Paper-level overview UI must not consume PDF page layout space")
    if soup.select_one("body > #paper-overview-annotations") is None:
        raise AssertionError("Paper-level overview should remain available outside page containers")
    if soup.select_one('.paper-page[data-page="1"] > .abstract') is None:
        raise AssertionError(f"Abstract wrapper should remain a direct page child for column-span CSS: {soup.select_one('.paper-page')}")
    if soup.select_one(".paper-page > .abstract > p .paper-sentence") is None:
        raise AssertionError("Abstract sentence anchor was lost while preserving the abstract wrapper")


def test_paged_layout_places_float_only_blocks_and_preserves_pdf_page_count() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p><span class="paper-sentence" data-sentence-id="s-intro-p001-s001">Main text sentence.</span></p>
  <div id="tab:appendix-setup" class="table* paper-table paper-table-rebuilt paper-float-wide">
    <table><caption>Appendix setup configuration for late-page ablations.</caption><tbody><tr><td>A</td></tr></tbody></table>
  </div>
</body></html>
""",
        "lxml",
    )
    pages, assigned = module.split_children_into_pages(
        soup,
        {"s-intro-p001-s001": 1},
        block_assignments={"tab:appendix-setup": 3},
        min_pages=4,
    )
    if assigned != 1 or len(pages) != 4:
        raise AssertionError(f"Expected four PDF page wrappers with one sentence assignment, got pages={len(pages)}")
    table = soup.find(id="tab:appendix-setup")
    page3 = soup.select_one('.paper-page[data-page="3"]')
    page4 = soup.select_one('.paper-page[data-page="4"]')
    if table is None or table.find_parent(class_="paper-page") is not page3:
        raise AssertionError(f"Float-only table should be placed on its matched PDF page: {soup}")
    if page4 is None:
        raise AssertionError("Paged layout should preserve trailing PDF-only pages even when no source sentence maps there")


def test_paged_layout_caption_sentence_page_keeps_float_in_source_position() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <figure id="fig:late" class="paper-float-wide">
    <figcaption><span class="paper-sentence" data-sentence-id="s-cap-p001-s001">Late figure caption sentence.</span></figcaption>
  </figure>
</body></html>
""",
        "lxml",
    )
    pages = [
        module.normalize_for_match(""),
        module.normalize_for_match("Late figure caption sentence."),
        module.normalize_for_match(""),
        module.normalize_for_match("Late figure caption sentence."),
    ]
    pages = [" ".join(module.text_match_tokens(page)) for page in pages]
    sentence_assignments = {"s-cap-p001-s001": 2}
    block_assignments = module.block_page_assignments_from_pages(soup, pages, sentence_assignments)
    module.split_children_into_pages(
        soup,
        sentence_assignments,
        block_assignments=block_assignments,
        min_pages=4,
    )
    figure = soup.find(id="fig:late")
    if figure is None or figure.find_parent(class_="paper-page").get("data-page") != "2":
        raise AssertionError(f"Float with caption sentence page should not jump to a later repeated caption page: {soup}")


def test_sentence_page_assignment_can_skip_unanchored_reference_pages() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p><span class="paper-sentence" data-sentence-id="s-main-001">Main body sentence with distinctive evidence.</span></p>
  <div id="refs"><div class="csl-entry">A reference entry without sentence anchors.</div></div>
  <p><span class="paper-sentence" data-sentence-id="s-appendix-001">Appendix method sentence with distinctive configuration and appendix-specific page context.</span></p>
</body></html>
""",
        "lxml",
    )
    pages = [
        module.normalize_for_match("Main body sentence with distinctive evidence."),
        module.normalize_for_match("Reference entry one."),
        module.normalize_for_match("Reference entry two."),
        module.normalize_for_match("Appendix method sentence with distinctive configuration and appendix-specific page context."),
    ]
    pages = [" ".join(module.text_match_tokens(page)) for page in pages]
    assignments = module.sentence_page_assignments_from_pages(soup, pages)
    if assignments.get("s-main-001") != 1 or assignments.get("s-appendix-001") != 4:
        raise AssertionError(f"Page assignment should skip reference-only PDF pages: {assignments}")


def test_sentence_page_assignment_uses_global_alignment_for_ambiguous_page_turns() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p><span class="paper-sentence" data-sentence-id="s-first">Opening calibration sentence with distinctive first page evidence.</span></p>
  <p><span class="paper-sentence" data-sentence-id="s-ambiguous">During detection each segment is decoded independently.</span></p>
  <p><span class="paper-sentence" data-sentence-id="s-page-two">Theoretical decoding accuracy rises slowly with segmentation and fewer tokens per segment.</span></p>
  <p><span class="paper-sentence" data-sentence-id="s-page-three">Existing methods exhibit message dependent generation biases across candidate messages.</span></p>
</body></html>
""",
        "lxml",
    )
    pages = [
        "Opening calibration sentence with distinctive first page evidence.",
        "During detection each segment. Theoretical decoding accuracy rises slowly with segmentation and fewer tokens per segment.",
        "During detection each segment is decoded independently. Existing methods exhibit message dependent generation biases across candidate messages.",
    ]
    pages = [" ".join(module.text_match_tokens(module.normalize_for_match(page))) for page in pages]
    greedy = module._greedy_sentence_page_assignments_from_pages(soup, pages)
    assignments = module.sentence_page_assignments_from_pages(soup, pages)
    if greedy.get("s-ambiguous") != 3 or greedy.get("s-page-two") != 3:
        raise AssertionError(f"Fixture should reproduce the old premature page turn: {greedy}")
    if assignments.get("s-ambiguous") != 2 or assignments.get("s-page-two") != 2:
        raise AssertionError(f"Global page alignment should keep the page-two run together: {assignments}")
    if assignments.get("s-page-three") != 3:
        raise AssertionError(f"Global page alignment should still advance on the real next-page sentence: {assignments}")


def test_flow_block_assignment_places_reference_blocks_on_pdf_pages() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p><span class="paper-sentence" data-sentence-id="s-main-001">Main body sentence with distinctive evidence.</span></p>
  <div id="refs"><div class="csl-entry">Azaria Amos Mitchell internal state language model lying findings association computational linguistics.</div></div>
  <p><span class="paper-sentence" data-sentence-id="s-appendix-001">Appendix method sentence with distinctive configuration.</span></p>
</body></html>
""",
        "lxml",
    )
    pages = [
        module.normalize_for_match("Main body sentence with distinctive evidence."),
        module.normalize_for_match("Azaria Amos Mitchell internal state language model lying findings association computational linguistics."),
        module.normalize_for_match("Reference continuation only."),
        module.normalize_for_match("Appendix method sentence with distinctive configuration."),
    ]
    pages = [" ".join(module.text_match_tokens(page)) for page in pages]
    sentence_assignments = module.sentence_page_assignments_from_pages(soup, pages)
    flow_assignments = module.flow_block_page_assignments_from_pages(soup, pages, sentence_assignments, {})
    refs = soup.find(id="refs")
    if refs is None or flow_assignments.get(id(refs)) != 2:
        raise AssertionError(f"Reference block should be assigned to its matched PDF page: {flow_assignments}")


def test_reference_entries_can_split_across_pdf_pages() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <div id="refs" class="references csl-bib-body">
    <div class="csl-entry" id="ref-a">Azaria Amos Mitchell internal state language model lying findings association computational linguistics.</div>
    <div class="csl-entry" id="ref-b">Ziegler Daniel Stiennon Radford Amodei Christiano Irving fine tuning language models human preferences.</div>
  </div>
</body></html>
""",
        "lxml",
    )
    pages = [
        module.normalize_for_match("Azaria Amos Mitchell internal state language model lying findings association computational linguistics."),
        module.normalize_for_match("Ziegler Daniel Stiennon Radford Amodei Christiano Irving fine tuning language models human preferences."),
    ]
    pages = [" ".join(module.text_match_tokens(page)) for page in pages]
    flow_assignments = module.flow_block_page_assignments_from_pages(soup, pages, {}, {})
    module.split_children_into_pages(soup, {}, flow_block_assignments=flow_assignments, min_pages=2)
    if soup.select_one('.paper-page[data-page="1"] #ref-a') is None:
        raise AssertionError(f"First reference entry should be on page 1: {soup}")
    if soup.select_one('.paper-page[data-page="2"] #ref-b') is None:
        raise AssertionError(f"Second reference entry should be on page 2: {soup}")


def test_paged_layout_can_backfill_pages_after_late_float() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <figure id="fig:late"><figcaption><span class="paper-sentence" data-sentence-id="s-fig-001">Late float caption.</span></figcaption></figure>
  <p><span class="paper-sentence" data-sentence-id="s-body-001">Earlier body sentence.</span></p>
</body></html>
""",
        "lxml",
    )
    module.split_children_into_pages(
        soup,
        {"s-fig-001": 4, "s-body-001": 2},
        block_assignments={"fig:late": 4},
        min_pages=4,
    )
    if soup.select_one('.paper-page[data-page="2"] [data-sentence-id="s-body-001"]') is None:
        raise AssertionError(f"Content matched to an existing earlier page should be backfilled there: {soup}")
    late = soup.find(id="fig:late")
    if late is None or late.find_parent(class_="paper-page").get("data-page") != "4":
        raise AssertionError(f"Late float should remain on its explicit page: {soup}")


def test_list_blocks_can_split_across_pdf_pages() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <ol>
    <li id="li-a">Checklist claim accurately reflect contributions scope.</li>
    <li id="li-b">Checklist limitation assumption societal impact reproducibility.</li>
  </ol>
</body></html>
""",
        "lxml",
    )
    pages = [
        module.normalize_for_match("Checklist claim accurately reflect contributions scope."),
        module.normalize_for_match("Checklist limitation assumption societal impact reproducibility."),
    ]
    pages = [" ".join(module.text_match_tokens(page)) for page in pages]
    flow_assignments = module.flow_block_page_assignments_from_pages(soup, pages, {}, {})
    module.split_children_into_pages(soup, {}, flow_block_assignments=flow_assignments, min_pages=2)
    if soup.select_one('.paper-page[data-page="1"] #li-a') is None:
        raise AssertionError(f"First list item should be on page 1: {soup}")
    if soup.select_one('.paper-page[data-page="2"] #li-b') is None:
        raise AssertionError(f"Second list item should be on page 2: {soup}")


def test_paged_two_column_css_prevents_extra_columns_from_overlapping_sidebar() -> None:
    module = load_module()
    html = module.report_shell(
        "Demo",
        '<div class="paper-page" data-page="1"></div>',
        tex_path=Path("/tmp/paper.tex"),
        raw_html_path=Path("/tmp/paper.source.html"),
        raw_hash="sha256:test",
        sentence_count=0,
        annotations=[],
        paper_layout="paged-two-column",
        page_map={"pages": 1},
    )
    if "column-count:2" not in html or "column-fill:balance" not in html:
        raise AssertionError("Paged two-column layout should distribute each PDF page across both columns")
    if "min-height:1120px" not in html or "overflow:hidden" not in html:
        raise AssertionError("Paged layout should keep each page visually bounded so extra columns cannot overlap the sidebar")
    if " height:1120px" in html or "{ height:1120px" in html or "column-fill:auto" in html:
        raise AssertionError("Paged two-column layout must not leave PDF page content stuck in the left CSS column")
    if ".paper-page > figure" in html or ".paper-layout-two-column > figure" in html:
        raise AssertionError("Regular single-column figures must not be forced to span both columns")


def test_paged_single_column_css_uses_page_wrappers_without_column_count() -> None:
    module = load_module()
    html = module.report_shell(
        "Demo",
        '<div class="paper-page" data-page="1"></div>',
        tex_path=Path("/tmp/paper.tex"),
        raw_html_path=Path("/tmp/paper.source.html"),
        raw_hash="sha256:test",
        sentence_count=0,
        annotations=[],
        paper_layout="paged",
        page_map={"pages": 1},
    )
    if 'data-paper-layout="paged"' not in html or "paged single-column · 1 pages" not in html:
        raise AssertionError("Paged single-column layout should be exposed in report metadata and toolbar")
    if ".paper-pane.paper-layout-paged > .paper-page { column-count:2" in html:
        raise AssertionError("Paged single-column pages must not inherit two-column balancing")
    if ".paper-pane.paper-layout-paged { font-size:15px;" not in html:
        raise AssertionError("Paged single-column layout should have its own page-wrapper styling")


def test_empty_full_report_annotation_panel_warns_not_complete() -> None:
    module = load_module()
    html = module.report_shell(
        "Demo",
        "<p>Body.</p>",
        tex_path=Path("/tmp/paper.tex"),
        raw_html_path=Path("/tmp/paper.source.html"),
        raw_hash="sha256:test",
        sentence_count=1,
        annotations=[],
        full_report=True,
    )
    if "审阅未完成" not in html or "Prose Phase A/B" not in html:
        raise AssertionError("Empty full reports should warn users that prose review did not complete")
    if "has-annotation" in html and "下一步应让审阅逻辑" in html:
        raise AssertionError("Empty-state copy should be user-facing, not renderer-internal guidance")


def test_coverage_receipt_lists_visible_findings_not_rendered_in_overlay() -> None:
    module = load_module()
    html = module.report_shell(
        "Demo",
        "<p>Body.</p>",
        tex_path=Path("/tmp/paper.tex"),
        raw_html_path=Path("/tmp/paper.source.html"),
        raw_hash="sha256:test",
        sentence_count=1,
        annotations=[],
        findings=[
            {
                "id": "F9",
                "severity": "Minor",
                "issue_type": "prose",
                "render_visibility": "student_visible",
                "title": "Visible but unanchored issue",
                "primary_anchor": "missing-anchor",
            }
        ],
        full_report=True,
    )
    if "未渲染 findings" not in html or "F9" not in html or "not anchored in overlay/global sections" not in html:
        raise AssertionError("Coverage receipt should expose visible findings that were not rendered in overlay/global sections")


def test_table_css_keeps_paper_tables_centerable() -> None:
    module = load_module()
    html = module.report_shell(
        "Demo",
        '<div class="paper-page" data-page="1"><div id="tab:demo" class="paper-table"><table><tbody><tr><td>A</td></tr></tbody></table></div></div>',
        tex_path=Path("/tmp/paper.tex"),
        raw_html_path=Path("/tmp/paper.source.html"),
        raw_hash="sha256:test",
        sentence_count=0,
        annotations=[],
        paper_layout="paged-two-column",
        page_map={"pages": 1},
    )
    if ".paper-pane table { width:auto;" not in html or "margin-left:auto; margin-right:auto;" not in html:
        raise AssertionError("Paper tables should remain centerable instead of becoming left-aligned block tables")
    if ".paper-pane table { width:100%; border-collapse:collapse; display:block;" in html:
        raise AssertionError("Global paper table CSS should not force every table into a left-aligned scroll block")
    if ".paper-pane .paper-table { max-width:100%; overflow-x:auto;" not in html:
        raise AssertionError("Horizontal table overflow should be handled by the paper-table wrapper")


def test_caption_target_cards_use_figure_caption_pointer_label() -> None:
    module = load_module()
    cards = module.render_annotation_cards(
        [
            {
                "issue_id": "F1",
                "severity": "polish",
                "issue_type": "rendered_caption_label_only",
                "target_level": "section",
                "section_id": "tab:data_split",
                "title": "Caption is thin",
                "problem": "Caption lacks takeaway.",
            }
        ]
    )
    if "指向图表/Caption" not in cards:
        raise AssertionError("Caption-target issue should not be labeled as a generic section pointer")
    if "指向章节" in cards:
        raise AssertionError("Caption-target issue leaked the generic section pointer label")


def test_inline_annotation_label_is_clipped_inside_pill() -> None:
    module = load_module()
    html = module.report_shell(
        "Demo",
        '<p><span class="paper-sentence has-annotation" data-inline-label="很长很长的中文批注标题">Sentence.</span></p>',
        tex_path=Path("/tmp/paper.tex"),
        raw_html_path=Path("/tmp/paper.source.html"),
        raw_hash="sha256:test",
        sentence_count=1,
        annotations=[],
    )
    if "overflow:hidden; text-overflow:ellipsis" not in html:
        raise AssertionError("Inline annotation labels should be clipped instead of painting over paper text")


def test_acl_anonymous_front_matter_suppresses_source_only_identity_false_positive() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <header><h1 class="paper-title" id="demo">Demo</h1><p class="paper-author paper-anonymous-author" data-acl-review-anonymous="true">Anonymous ACL submission</p></header>
  <p><span class="paper-sentence" data-sentence-id="s-front-p001-s001">Abstract sentence.</span></p>
  <p><span class="paper-sentence" data-sentence-id="s-front-p001-s002">Another sentence.</span></p>
</body></html>
""",
        "lxml",
    )
    annotations = [
        {
            "issue_id": "F1",
            "target_level": "sentence",
            "sentence_id": "s-front-p001-s001",
            "title": "匿名评审模式下首页仍暴露作者身份",
            "problem": "正文入口处直接显示作者姓名、单位占位和邮箱占位；若这是 ACL review 版，匿名性在第一页已经破坏。",
        },
        {
            "issue_id": "F2",
            "target_level": "sentence",
            "sentence_id": "s-front-p001-s002",
            "title": "普通文字问题",
            "problem": "This sentence still needs a useful note.",
        },
    ]
    assigned = module.assign_sentence_targets(soup, annotations)
    if [item["issue_id"] for item in assigned] != ["F2"]:
        raise AssertionError(f"Anonymous compiled front matter should filter source-only identity false positives: {assigned}")


def test_generic_anonymous_front_matter_suppresses_source_only_identity_false_positive() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <header><h1 class="paper-title" id="demo">Demo</h1><p class="paper-author">Anonymous submission</p></header>
  <p><span class="paper-sentence" data-sentence-id="s-front-p001-s001">Abstract sentence.</span></p>
  <p><span class="paper-sentence" data-sentence-id="s-front-p001-s002">Another sentence.</span></p>
</body></html>
""",
        "lxml",
    )
    annotations = [
        {
            "issue_id": "F1",
            "target_level": "sentence",
            "sentence_id": "s-front-p001-s001",
            "title": "匿名评审模式下首页仍暴露作者身份",
            "problem": "首页作者姓名已经可见，双盲风险很高。",
        },
        {
            "issue_id": "F2",
            "target_level": "sentence",
            "sentence_id": "s-front-p001-s002",
            "title": "普通文字问题",
            "problem": "This sentence still needs a useful note.",
        },
    ]
    assigned = module.assign_sentence_targets(soup, annotations)
    if [item["issue_id"] for item in assigned] != ["F2"]:
        raise AssertionError(f"Generic anonymous compiled front matter should filter source-only identity false positives: {assigned}")


def test_reuse_raw_html_does_not_rewrite_source_artifact() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex = tmp / "paper.tex"
        tex.write_text(
            r"""
\documentclass{article}
\title{Tiny}
\begin{document}
\maketitle
\section{Intro}
Stable sentence.
\end{document}
""",
            encoding="utf-8",
        )
        raw_html = tmp / "paper.source.html"
        source_body = """
<header id="title-block-header"><h1 class="title paper-title" id="tiny">Tiny</h1></header>
<h1 id="intro" data-section-number="1">Intro</h1>
<p data-paragraph-id="p-intro-001"><span class="paper-sentence" data-sentence-id="s-intro-p001-s001">Stable sentence.</span></p>
"""
        raw_html.write_text(module.source_artifact_shell("Tiny", source_body), encoding="utf-8")
        before = raw_html.read_text(encoding="utf-8")
        output = tmp / "paper.html"

        module.render(tex, output, raw_html_path=raw_html, reuse_raw_html=True)

        after = raw_html.read_text(encoding="utf-8")
        if after != before:
            raise AssertionError("--reuse-raw-html must not rewrite the canonical source artifact")
        rendered = BeautifulSoup(output.read_text(encoding="utf-8"), "lxml")
        if rendered.select_one('.paper-sentence[data-sentence-id="s-intro-p001-s001"]') is None:
            raise AssertionError("Reused source sentence anchors should render into the final report")


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
        if "未定位到唯一原句的批注（1）" not in cards_html:
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
    if cards_soup.select_one('[data-target-paper^="paper-"]') is None:
        raise AssertionError("Paper annotation card missing target")


def test_unanchored_paper_annotations_do_not_create_overview_buttons() -> None:
    module = load_module()
    soup = BeautifulSoup(
        """
<html><body>
  <p><span class="paper-sentence" data-sentence-id="s1">Clean sentence.</span></p>
</body></html>
""",
        "lxml",
    )
    annotations = [
        {
            "issue_id": "figure_caption:L1",
            "severity": "minor",
            "issue_type": "figure_caption",
            "target_level": "paper",
            "paper_id": "paper",
            "title": "Caption is not anchored",
            "problem": "Rendered caption issue has no unique sentence anchor.",
            "unanchored": "true",
        }
    ]
    applied = module.apply_annotations(soup, annotations)
    if soup.select_one("#paper-overview-annotations .annotation-bubble.paper") is not None:
        raise AssertionError("Unanchored paper issue should not create a paper overview button")
    cards = module.render_annotation_cards(applied)
    if 'data-unanchored="true"' not in cards or 'data-target-paper=' in cards:
        raise AssertionError("Unanchored paper issue should render only as an unanchored card")


def test_issue_artifacts_respect_visibility_and_render_page_level_cards() -> None:
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
                            "render_hint": {"anchor": "page:1", "display_group": "compiled-display-checks"},
                        },
                        {
                            "local_id": "L2",
                            "severity": "Polish",
                            "issue_type": "edge_text",
                            "title": "Tool-only margin hint",
                            "diagnosis": "This should remain audit-only.",
                            "render_hint": {"anchor": "page:1", "display_group": "compiled-display-checks"},
                            "render_visibility": "artifact_only",
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
    if annotation.get("unanchored") == "true" or annotation.get("page_anchor") != "page:1":
        raise AssertionError(f"page-level issue artifact should be anchored as page-level paper note, got {annotation}")
    cards = module.render_annotation_cards(annotations)
    if "Main table is cramped" not in cards or "编译后展示检查" not in cards or "页级/版式批注（1）" not in cards:
        raise AssertionError("Issue artifact annotation card did not preserve title/display group label")
    if "未定位到具体句子的批注" in cards or "Tool-only margin hint" in cards:
        raise AssertionError("Page-level artifact should not be mislabeled as unanchored or leak audit-only hints")


def test_artifact_only_compiled_findings_do_not_render() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        findings = tmp / "findings.json"
        annotations = tmp / "annotations.json"
        findings.write_text(
            json.dumps(
                {
                    "findings": [
                        {
                            "id": "F1",
                            "severity": "Major",
                            "issue_type": "prose",
                            "render_visibility": "student_visible",
                            "title": "Visible issue",
                            "diagnosis": "This should render.",
                            "target_anchors": ["s1"],
                        },
                        {
                            "id": "F2",
                            "severity": "Major",
                            "issue_type": "source_hygiene",
                            "render_visibility": "artifact_only",
                            "title": "Macro-only issue",
                            "diagnosis": "This should stay out of HTML.",
                            "target_anchors": ["paper"],
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
                        {"issue_id": "F1", "target_level": "sentence", "sentence_id": "s1", "title": "Visible issue"},
                        {
                            "issue_id": "F2",
                            "target_level": "paper",
                            "paper_id": "paper",
                            "title": "Macro-only issue",
                            "render_visibility": "artifact_only",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        loaded_annotations = module.load_annotations(annotations)
        loaded_findings = module.load_findings(findings)
        finding_rows = module.load_findings_rows(findings)
        merged = module.merge_annotation_findings(loaded_annotations, loaded_findings)
        cards = module.render_annotation_cards(merged)
        globals_html = module.render_global_findings(finding_rows)

    if [item["issue_id"] for item in loaded_annotations] != ["F1"]:
        raise AssertionError(f"Artifact-only annotation should be filtered: {loaded_annotations}")
    if set(loaded_findings) != {"F1"} or [row["id"] for row in finding_rows] != ["F1"]:
        raise AssertionError(f"Artifact-only finding should be filtered from renderer inputs: {loaded_findings}, {finding_rows}")
    if "Macro-only issue" in cards or "Macro-only issue" in globals_html:
        raise AssertionError("Artifact-only finding leaked into rendered HTML")


def test_issue_artifact_annotations_are_suppressed_when_compiled_into_findings() -> None:
    module = load_module()
    annotations = [
        {"issue_id": "figure_caption:figure-caption-001", "target_level": "section", "section_id": "tab:data_split"},
        {"issue_id": "layout:L1", "target_level": "paper", "paper_id": "paper"},
    ]
    findings_by_id = {
        "F1": {
            "id": "F1",
            "source_issue_ids": ["figure_caption:figure-caption-001"],
        }
    }
    filtered = module.filter_compiled_issue_artifact_annotations(annotations, findings_by_id)
    if [item["issue_id"] for item in filtered] != ["layout:L1"]:
        raise AssertionError(f"Compiled source issue artifacts should not render twice: {filtered}")


def main() -> int:
    test_render_paper_html_wraps_source_sentences_with_provenance()
    test_render_paper_html_overlays_annotations_without_rewriting_body()
    test_cleanup_removes_latex_layout_artifacts()
    test_sentence_wrapping_keeps_citations_inside_sentence()
    test_sentence_wrapping_preserves_list_paragraph_structure()
    test_paragraph_ids_reset_at_section_boundaries()
    test_restore_latex_labels_for_wrapfigure_and_tables()
    test_restore_mathml_equation_labels_from_tex_annotations()
    test_table_labels_are_restored_by_content_when_pandoc_reorders_tables()
    test_commented_inputs_do_not_shift_float_numbers_or_references()
    test_latex_caption_inline_markup_is_rendered_cleanly()
    test_ensure_references_heading_for_csl_entries()
    test_bibliography_before_appendix_is_restored_after_pandoc_append()
    test_reused_source_restores_references_before_appendix_and_alpha_numbers()
    test_appendix_section_reference_text_uses_alpha_number()
    test_bibliography_paths_find_tex_bibliography_files()
    test_latex_paragraph_headings_are_not_display_numbered()
    test_acl_review_front_matter_is_anonymized_and_not_numbered()
    test_neurips_source_layout_defaults_to_paged_single_when_pdf_exists()
    test_pdf_geometry_selects_paged_two_column_without_conference_hack()
    test_pdf_geometry_overrides_source_twocolumn_when_compiled_pdf_is_single()
    test_twocolumn_option_does_not_override_existing_pdf_layout()
    test_imports_existing_review_html_without_dropping_unanchored_notes()
    test_paged_layout_groups_existing_sentence_ids_without_coordinate_anchors()
    test_paged_layout_preserves_abstract_and_keeps_overview_outside_pages()
    test_paged_layout_places_float_only_blocks_and_preserves_pdf_page_count()
    test_paged_layout_caption_sentence_page_keeps_float_in_source_position()
    test_sentence_page_assignment_can_skip_unanchored_reference_pages()
    test_sentence_page_assignment_uses_global_alignment_for_ambiguous_page_turns()
    test_flow_block_assignment_places_reference_blocks_on_pdf_pages()
    test_reference_entries_can_split_across_pdf_pages()
    test_paged_layout_can_backfill_pages_after_late_float()
    test_list_blocks_can_split_across_pdf_pages()
    test_paged_two_column_css_prevents_extra_columns_from_overlapping_sidebar()
    test_paged_single_column_css_uses_page_wrappers_without_column_count()
    test_empty_full_report_annotation_panel_warns_not_complete()
    test_coverage_receipt_lists_visible_findings_not_rendered_in_overlay()
    test_table_css_keeps_paper_tables_centerable()
    test_caption_target_cards_use_figure_caption_pointer_label()
    test_multiple_annotations_on_one_sentence_get_unique_cards()
    test_annotation_cards_prefer_self_check_question_over_task()
    test_annotation_cards_hide_mechanical_anchor_metadata()
    test_annotation_cards_show_meaningful_numeric_evidence()
    test_missing_explicit_sentence_id_falls_back_to_snippet_match()
    test_paragraph_section_and_paper_annotations_render_as_bubbles()
    test_unanchored_paper_annotations_do_not_create_overview_buttons()
    test_issue_artifacts_respect_visibility_and_render_page_level_cards()
    test_artifact_only_compiled_findings_do_not_render()
    test_issue_artifact_annotations_are_suppressed_when_compiled_into_findings()
    print("render_paper_html regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
