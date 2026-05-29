#!/usr/bin/env python3
"""Regression tests for build_sentence_bbox.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_sentence_bbox.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_sentence_bbox", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load build_sentence_bbox")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_word(module, text: str, index: int):
    return module.WordBox(
        page=1,
        text=text,
        norm="".join(module.tokens(text)),
        x0=float(index * 10),
        y0=10.0,
        x1=float(index * 10 + 8),
        y1=20.0,
    )


def test_find_token_window_trims_exact_sentence_boundary() -> None:
    module = load_module()
    raw_words = "remains an open question We study this question with controlled QA".split()
    words = [make_word(module, word, index) for index, word in enumerate(raw_words)]
    search = module.WordSearchIndex(words)

    matched, ratio = module.find_token_window(module.tokens("We study this question."), search)

    matched_text = " ".join(word.text for word in matched)
    if matched_text != "We study this question":
        raise AssertionError(f"Expected exact sentence boundary, got {matched_text!r} at ratio={ratio}")
    if ratio != 1.0:
        raise AssertionError(f"Expected exact match ratio, got {ratio}")


def test_parse_word_boxes_strips_poppler_control_chars() -> None:
    module = load_module()
    xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><doc><page width="100" height="200">
<flow><block><line><word xMin="1" yMin="2" xMax="3" yMax="4">\x01</word>
<word xMin="5" yMin="6" xMax="7" yMax="8">ok</word></line></block></flow>
</page></doc></body></html>"""

    words, page_sizes = module.parse_word_boxes(xhtml)

    if [word.text for word in words] != ["ok"] or page_sizes != {1: (100.0, 200.0)}:
        raise AssertionError(f"Expected control-char word to be ignored, got words={words} page_sizes={page_sizes}")


def test_find_token_window_does_not_fuzzy_scan_every_word() -> None:
    module = load_module()
    raw_words = [f"filler{i}" for i in range(2000)]
    raw_words[1234:1237] = ["method", "improves", "accuracie"]
    words = [make_word(module, word, index) for index, word in enumerate(raw_words)]
    search = module.WordSearchIndex(words)
    original_matcher = module.SequenceMatcher
    calls = {"count": 0}

    class CountingMatcher:
        def __init__(self, *args, **kwargs):
            calls["count"] += 1
            self.matcher = original_matcher(*args, **kwargs)

        def ratio(self):
            return self.matcher.ratio()

    module.SequenceMatcher = CountingMatcher
    try:
        matched, ratio = module.find_token_window(module.tokens("method improves accuracy"), search)
    finally:
        module.SequenceMatcher = original_matcher

    matched_text = " ".join(word.text for word in matched)
    if matched_text != "method improves accuracie":
        raise AssertionError(f"Expected local fuzzy match, got {matched_text!r} at ratio={ratio}")
    if calls["count"] >= 200:
        raise AssertionError(f"Expected indexed candidate search, got {calls['count']} SequenceMatcher calls")


def test_merge_rects_unions_paragraph_sentence_lines() -> None:
    module = load_module()
    rects = [
        {"page": 1, "x0": 10.0, "y0": 10.0, "x1": 40.0, "y1": 20.0},
        {"page": 1, "x0": 45.0, "y0": 10.5, "x1": 80.0, "y1": 20.5},
        {"page": 1, "x0": 12.0, "y0": 30.0, "x1": 70.0, "y1": 40.0},
    ]
    merged = module.merge_rects(rects, {1: (100.0, 200.0)})

    if len(merged) != 2:
        raise AssertionError(f"Expected two merged paragraph lines, got {merged}")
    if merged[0]["x0"] != 10.0 or merged[0]["x1"] != 80.0:
        raise AssertionError(f"Expected first line union, got {merged[0]}")
    if merged[0]["x1_pct"] != 0.8 or merged[1]["y1_pct"] != 0.2:
        raise AssertionError(f"Expected percentage coordinates, got {merged}")


def test_find_token_window_can_limit_to_y_band() -> None:
    module = load_module()
    words = [
        module.WordBox(page=1, text="target", norm="target", x0=0, y0=10, x1=10, y1=20),
        module.WordBox(page=1, text="phrase", norm="phrase", x0=12, y0=10, x1=22, y1=20),
        module.WordBox(page=1, text="target", norm="target", x0=0, y0=210, x1=10, y1=220),
        module.WordBox(page=1, text="phrase", norm="phrase", x0=12, y0=210, x1=22, y1=220),
    ]
    search = module.WordSearchIndex(words)

    matched, ratio = module.find_token_window(["target", "phrase"], search, page=1, y=210)

    if ratio != 1.0 or matched[0].y0 != 210:
        raise AssertionError(f"Expected y-band match on lower line, got {matched} ratio={ratio}")


def test_find_token_window_can_limit_to_synctex_region() -> None:
    module = load_module()
    words = [
        module.WordBox(page=1, text="target", norm="target", x0=10, y0=10, x1=40, y1=20),
        module.WordBox(page=1, text="phrase", norm="phrase", x0=42, y0=10, x1=80, y1=20),
        module.WordBox(page=1, text="target", norm="target", x0=10, y0=210, x1=40, y1=220),
        module.WordBox(page=1, text="phrase", norm="phrase", x0=42, y0=210, x1=80, y1=220),
    ]
    search = module.WordSearchIndex(words)

    matched, ratio = module.find_token_window(
        ["target", "phrase"],
        search,
        page=1,
        region={"x0": 0, "y0": 190, "x1": 120, "y1": 240},
    )

    if ratio != 1.0 or matched[0].y0 != 210:
        raise AssertionError(f"Expected region match on lower line, got {matched} ratio={ratio}")


def test_find_token_window_can_match_across_adjacent_pages() -> None:
    module = load_module()
    words = [
        module.WordBox(page=1, text="cross", norm="cross", x0=10, y0=700, x1=40, y1=710),
        module.WordBox(page=1, text="page", norm="page", x0=42, y0=700, x1=70, y1=710),
        module.WordBox(page=2, text="sentence", norm="sentence", x0=10, y0=10, x1=70, y1=20),
        module.WordBox(page=2, text="continues", norm="continues", x0=72, y0=10, x1=130, y1=20),
    ]
    search = module.WordSearchIndex(words)

    matched, ratio = module.find_token_window(["cross", "page", "sentence", "continues"], search, pages=[1, 2])

    if ratio != 1.0 or [word.page for word in matched] != [1, 1, 2, 2]:
        raise AssertionError(f"Expected adjacent-page match, got {matched} ratio={ratio}")


def test_expand_caption_prefix_adds_rendered_label() -> None:
    module = load_module()
    words = [
        module.WordBox(page=1, text="Figure", norm="figure", x0=10, y0=10, x1=40, y1=20),
        module.WordBox(page=1, text="3:", norm="3", x0=42, y0=10, x1=52, y1=20),
        module.WordBox(page=1, text="Training", norm="training", x0=54, y0=10, x1=100, y1=20),
        module.WordBox(page=1, text="dynamics", norm="dynamics", x0=102, y0=10, x1=150, y1=20),
    ]
    search = module.WordSearchIndex(words)

    expanded = module.expand_caption_prefix(words[2:], search)

    if [word.text for word in expanded] != ["Figure", "3:", "Training", "dynamics"]:
        raise AssertionError(f"Expected rendered caption label prefix, got {expanded}")


def test_review_units_pdf_text_payload_is_sidecar() -> None:
    module = load_module()
    payload = module.review_units_pdf_text_payload(
        {
            "pdf_hash": "sha256:pdf",
            "review_units_hash": "sha256:units",
            "anchors": {
                "s1": {
                    "rendered_text_pdf": "Rendered text.",
                    "confidence": "high",
                    "method": "synctex_region+poppler_word_match",
                    "match_ratio": 1.0,
                    "unmappable": False,
                }
            },
        }
    )

    if payload["anchors"]["s1"]["rendered_text_pdf"] != "Rendered text.":
        raise AssertionError(f"Expected rendered PDF text sidecar, got {payload}")
    if payload["pdf_hash"] != "sha256:pdf" or payload["review_units_hash"] != "sha256:units":
        raise AssertionError(f"Expected hashes in sidecar, got {payload}")


def test_review_unit_texts_indexes_caption_labels() -> None:
    module = load_module()
    import tempfile

    with tempfile.TemporaryDirectory() as tempdir:
        units = Path(tempdir) / "review_units.jsonl"
        units.write_text(
            (
                '{"kind":"paragraph","paragraph_id":"cap-results-001","unit_kind":"caption",'
                '"label":"fig:example","float_kind":"figure","sentences":['
                '{"sentence_id":"s-results-001-s001","unit_kind":"caption","label":"fig:example",'
                '"float_kind":"figure","text":"Training dynamics.","rendered_text_initial":"Training dynamics."}]}'
                "\n"
            ),
            encoding="utf-8",
        )

        index = module.review_unit_texts(units)

    if "fig:example" not in index or index["fig:example"].get("unit_kind") != "caption":
        raise AssertionError(f"Expected caption label alias in unit index, got {index}")


def test_page_layout_anchors_use_whole_page_rect() -> None:
    module = load_module()
    rects = module.whole_page_rect(2, {2: (100.0, 200.0)})

    if rects != [{"page": 2, "x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 200.0, "x0_pct": 0.0, "y0_pct": 0.0, "x1_pct": 1.0, "y1_pct": 1.0}]:
        raise AssertionError(f"Expected whole-page rect, got {rects}")
    if module.page_marker("page:12") != 12 or module.page_marker("12") is not None:
        raise AssertionError("Expected page marker parser for layout units")


def test_math_heavy_detection_enables_formula_fallback() -> None:
    module = load_module()
    if not module.math_heavy(r"The score is $p_\theta(y \mid x)$."):
        raise AssertionError("Expected inline math to be math-heavy")
    if not module.math_heavy(r"We use \frac{a}{b} in the loss."):
        raise AssertionError("Expected math command to be math-heavy")
    if module.math_heavy("Plain prose sentence."):
        raise AssertionError("Plain prose should not be math-heavy")


def test_math_tokens_normalize_latex_commands_and_pdf_glyphs() -> None:
    module = load_module()
    source_tokens = module.tokens(r"The score $p_\theta \leq 1$ improves.")
    pdf_tokens = module.tokens("The score p θ ≤ 1 improves.")

    if source_tokens != pdf_tokens:
        raise AssertionError(f"Expected comparable math tokens, got source={source_tokens} pdf={pdf_tokens}")


def test_find_best_token_window_uses_math_source_variant() -> None:
    module = load_module()
    words = [
        module.WordBox(page=1, text="The", norm="the", x0=0, y0=10, x1=10, y1=20),
        module.WordBox(page=1, text="score", norm="score", x0=12, y0=10, x1=35, y1=20),
        module.WordBox(page=1, text="p", norm="p", x0=37, y0=10, x1=42, y1=20),
        module.WordBox(page=1, text="θ", norm="theta", x0=44, y0=10, x1=52, y1=20),
        module.WordBox(page=1, text="improves", norm="improves", x0=54, y0=10, x1=100, y1=20),
    ]
    search = module.WordSearchIndex(words)
    variants = module.query_token_variants(
        {"text": r"The score $p_\theta$ improves."},
        "The score p improves.",
    )

    matched, ratio = module.find_best_token_window(variants, search, page=1)

    if ratio != 1.0 or [word.text for word in matched] != ["The", "score", "p", "θ", "improves"]:
        raise AssertionError(f"Expected source math variant to recover glyph word, got {matched} ratio={ratio}")


def test_synctex_fallback_prefers_region_words() -> None:
    module = load_module()
    words = [
        module.WordBox(page=1, text="near", norm="near", x0=10, y0=10, x1=30, y1=20),
        module.WordBox(page=1, text="formula", norm="formula", x0=35, y0=10, x1=70, y1=20),
        module.WordBox(page=1, text="far", norm="far", x0=10, y0=150, x1=30, y1=160),
    ]
    search = module.WordSearchIndex(words)
    matched = module.words_from_synctex_hint(
        search,
        {"status": "ok", "page": 1, "region": {"x0": 0, "y0": 0, "x1": 80, "y1": 30}},
    )

    if [word.text for word in matched] != ["near", "formula"]:
        raise AssertionError(f"Expected fallback words from SyncTeX region, got {matched}")


def test_math_rects_include_overlapping_synctex_region() -> None:
    module = load_module()
    word_rects = [
        {"page": 1, "x0": 10.0, "y0": 100.0, "x1": 40.0, "y1": 110.0},
        {"page": 1, "x0": 80.0, "y0": 100.5, "x1": 120.0, "y1": 110.5},
    ]
    hint_rects = [{"page": 1, "x0": 8.0, "y0": 98.0, "x1": 130.0, "y1": 114.0}]

    rects = module.augment_math_rects_with_synctex(word_rects, hint_rects, {1: (200.0, 400.0)})

    if len(rects) != 1 or rects[0]["x0"] != 8.0 or rects[0]["x1"] != 130.0:
        raise AssertionError(f"Expected math rect union with SyncTeX region, got {rects}")
    if rects[0]["x1_pct"] != 0.65 or rects[0]["y1_pct"] != 0.285:
        raise AssertionError(f"Expected percentage coordinates after union, got {rects}")


if __name__ == "__main__":
    test_find_token_window_trims_exact_sentence_boundary()
    test_parse_word_boxes_strips_poppler_control_chars()
    test_find_token_window_does_not_fuzzy_scan_every_word()
    test_merge_rects_unions_paragraph_sentence_lines()
    test_find_token_window_can_limit_to_y_band()
    test_find_token_window_can_limit_to_synctex_region()
    test_find_token_window_can_match_across_adjacent_pages()
    test_expand_caption_prefix_adds_rendered_label()
    test_review_units_pdf_text_payload_is_sidecar()
    test_review_unit_texts_indexes_caption_labels()
    test_page_layout_anchors_use_whole_page_rect()
    test_math_heavy_detection_enables_formula_fallback()
    test_math_tokens_normalize_latex_commands_and_pdf_glyphs()
    test_find_best_token_window_uses_math_source_variant()
    test_synctex_fallback_prefers_region_words()
    test_math_rects_include_overlapping_synctex_region()
    print("build_sentence_bbox regression tests passed")
