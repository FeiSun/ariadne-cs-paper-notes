#!/usr/bin/env python3
"""Regression tests for extract_tex_review_units.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_tex_review_units.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_tex_review_units", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load extract_tex_review_units")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tex_units_preserve_input_source_lines_and_ignore_commented_input() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        (root / "sections").mkdir()
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Intro}",
                    r"\input{sections/intro}",
                    r"% \input{sections/commented}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        (root / "sections" / "intro.tex").write_text(
            "First sentence in input. Second sentence stays together.\n",
            encoding="utf-8",
        )
        (root / "sections" / "commented.tex").write_text("This should not appear.\n", encoding="utf-8")
        units = module.extract_units(tex)

    paragraphs = [unit for unit in units if unit.get("kind") == "paragraph"]
    all_text = " ".join(sentence["text"] for unit in paragraphs for sentence in unit.get("sentences", []))
    if "This should not appear" in all_text:
        raise AssertionError(f"Commented input leaked into review units: {all_text}")
    if "First sentence in input." not in all_text:
        raise AssertionError(f"Input section sentence missing: {all_text}")
    first_sentence = paragraphs[0]["sentences"][0]
    if Path(first_sentence["source_file"]).name != "intro.tex" or first_sentence["line_start"] != 1:
        raise AssertionError(f"Expected original input file line, got {first_sentence}")


def test_tex_units_resolve_root_relative_input_from_section_file() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        (root / "Section").mkdir()
        (root / "Figures").mkdir()
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\input{Section/body}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        (root / "Section" / "body.tex").write_text(
            "\n".join(
                [
                    r"\section{Results}",
                    r"\input{Figures/wrap_result}",
                ]
            ),
            encoding="utf-8",
        )
        (root / "Figures" / "wrap_result.tex").write_text(
            "\n".join(
                [
                    r"\begin{wrapfigure}{r}{0.3\linewidth}",
                    r"\caption{Root-relative figure caption.}",
                    r"\label{fig:root-relative}",
                    r"\end{wrapfigure}",
                ]
            ),
            encoding="utf-8",
        )
        units = module.extract_units(tex)

    captions = [unit for unit in units if unit.get("unit_kind") == "caption"]
    if len(captions) != 1 or captions[0].get("label") != "fig:root-relative":
        raise AssertionError(f"Expected root-relative input caption with label, got {captions}")
    if Path(captions[0]["source_file"]).name != "wrap_result.tex":
        raise AssertionError(f"Expected source path from expanded input, got {captions[0]}")


def test_tex_units_extract_caption_with_label() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Results}",
                    r"\begin{figure}",
                    r"\caption{Training accuracy over time.}\label{fig:train}",
                    r"\end{figure}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        units = module.extract_units(tex)

    captions = [sentence for unit in units if unit.get("unit_kind") == "caption" for sentence in unit.get("sentences", [])]
    if len(captions) != 1:
        raise AssertionError(f"Expected one caption sentence, got {captions}")
    if captions[0].get("label") != "fig:train" or captions[0].get("float_kind") != "figure":
        raise AssertionError(f"Caption metadata missing: {captions[0]}")


def test_tex_units_attach_label_from_following_float_line() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Results}",
                    r"\begin{table}",
                    r"\caption{General capability benchmarks.}",
                    r"\label{tab3}",
                    r"\end{table}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        units = module.extract_units(tex)

    captions = [unit for unit in units if unit.get("unit_kind") == "caption"]
    if len(captions) != 1 or captions[0].get("label") != "tab3":
        raise AssertionError(f"Expected following-line label on caption paragraph, got {captions}")
    sentence = captions[0]["sentences"][0]
    if sentence.get("label") != "tab3" or sentence.get("float_kind") != "table":
        raise AssertionError(f"Expected following-line label on caption sentence, got {sentence}")


def test_tex_units_attach_label_from_following_section_line() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Method}",
                    r"\label{sec:method}",
                    r"This section explains the method.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        units = module.extract_units(tex)

    section = next(unit for unit in units if unit.get("kind") == "section")
    if section.get("section_id") != "method" or "sec:method" not in section.get("aliases", []):
        raise AssertionError(f"Expected section label alias, got {section}")


def test_tex_units_attach_label_from_same_section_line() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Method}\label{sec:method}",
                    r"This section explains the method.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        units = module.extract_units(tex)

    section = next(unit for unit in units if unit.get("kind") == "section")
    if "sec:method" not in section.get("aliases", []):
        raise AssertionError(f"Expected same-line section label alias, got {section}")


def test_tex_units_extract_footnotes_without_polluting_prose() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Intro}",
                    r"Main claim remains readable.\footnote{Footnote caveat should be reviewed separately.} Next sentence continues.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        units = module.extract_units(tex)

    prose_sentences = [
        sentence
        for unit in units
        if unit.get("unit_kind") == "prose"
        for sentence in unit.get("sentences", [])
    ]
    footnote_sentences = [
        sentence
        for unit in units
        if unit.get("unit_kind") == "footnote"
        for sentence in unit.get("sentences", [])
    ]
    prose_text = " ".join(sentence["rendered_text_initial"] for sentence in prose_sentences)
    footnote_text = " ".join(sentence["rendered_text_initial"] for sentence in footnote_sentences)
    if "Footnote caveat" in prose_text:
        raise AssertionError(f"Footnote text leaked into prose units: {prose_text}")
    if "Main claim remains readable." not in prose_text or "Next sentence continues." not in prose_text:
        raise AssertionError(f"Prose around footnote was not preserved: {prose_text}")
    if "Footnote caveat should be reviewed separately." not in footnote_text:
        raise AssertionError(f"Footnote unit missing text: {footnote_text}")
    if not footnote_sentences[0]["sentence_id"].startswith("s-intro-001-s"):
        raise AssertionError(f"Unexpected footnote sentence id: {footnote_sentences[0]}")
    if Path(footnote_sentences[0]["source_file"]).name != "main.tex" or footnote_sentences[0]["line_start"] != 4:
        raise AssertionError(f"Footnote source span should point to original line: {footnote_sentences[0]}")


def test_tex_units_append_layout_page_units() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Intro}",
                    "Hello.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        layout = root / "layout_audit.json"
        layout.write_text(
            """
{
  "page_summaries": [{"page": 1, "line_count": 10, "word_count": 120, "observations": 1, "needs_main_review": true}],
  "observations": [{"page": 1, "observation_id": "layout-p001-001"}]
}
""".strip(),
            encoding="utf-8",
        )
        units = module.extract_units(tex)
        module.append_layout_units(units, layout)

    layout_units = [unit for unit in units if unit.get("unit_kind") == "page_layout"]
    if len(layout_units) != 1:
        raise AssertionError(f"Expected one page_layout unit, got {layout_units}")
    sentence = layout_units[0]["sentences"][0]
    if sentence["line_start"] != "page:1" or sentence["metrics"]["observation_ids"] != ["layout-p001-001"]:
        raise AssertionError(f"Unexpected page_layout metadata: {sentence}")


if __name__ == "__main__":
    test_tex_units_preserve_input_source_lines_and_ignore_commented_input()
    test_tex_units_resolve_root_relative_input_from_section_file()
    test_tex_units_extract_caption_with_label()
    test_tex_units_attach_label_from_following_float_line()
    test_tex_units_attach_label_from_following_section_line()
    test_tex_units_attach_label_from_same_section_line()
    test_tex_units_extract_footnotes_without_polluting_prose()
    test_tex_units_append_layout_page_units()
    print("extract_tex_review_units regression tests passed")
