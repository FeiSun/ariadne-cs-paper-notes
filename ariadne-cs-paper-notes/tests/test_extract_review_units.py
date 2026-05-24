#!/usr/bin/env python3
"""Regression tests for compact Ariadne review-unit extraction."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_review_units.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_review_units", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load extract_review_units module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_source(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "paper.source.html"
    path.write_text(f"<!doctype html><html><body>{body}</body></html>", encoding="utf-8")
    return path


def paragraph_units(units: list[dict[str, object]]) -> list[dict[str, object]]:
    return [unit for unit in units if unit.get("kind") == "paragraph"]


def sentence_ids(units: list[dict[str, object]]) -> list[str]:
    ids: list[str] = []
    for unit in paragraph_units(units):
        for sentence in unit.get("sentences", []):  # type: ignore[union-attr]
            ids.append(sentence["sentence_id"])  # type: ignore[index]
    return ids


def test_extracts_sections_paragraphs_and_sentences(tmp_path: Path) -> None:
    module = load_module()
    source = write_source(
        tmp_path,
        """
        <h1 id="introduction">Introduction</h1>
        <p data-paragraph-id="p-introduction-001">
          <span data-sentence-id="s-introduction-p001-s001">First sentence.</span>
          <span data-sentence-id="s-introduction-p001-s002">Second sentence.</span>
        </p>
        """,
    )
    units = module.extract_units(source)
    assert units[0]["kind"] == "section"
    assert units[0]["section_id"] == "introduction"
    paragraphs = paragraph_units(units)
    assert paragraphs[0]["paragraph_id"] == "p-introduction-001"
    assert sentence_ids(units) == ["s-introduction-p001-s001", "s-introduction-p001-s002"]


def test_checklist_boilerplate_is_filtered_by_default(tmp_path: Path) -> None:
    module = load_module()
    source = write_source(
        tmp_path,
        """
        <h1 id="neurips-paper-checklist">NeurIPS Paper Checklist</h1>
        <p data-paragraph-id="p-check-001"><span data-sentence-id="s-check-001">Question: Does the paper disclose compute?</span></p>
        <p data-paragraph-id="p-check-002"><span data-sentence-id="s-check-002">Answer:</span></p>
        <p data-paragraph-id="p-check-003"><span data-sentence-id="s-check-003">Justification: Compute is described in Appendix A.</span></p>
        <p data-paragraph-id="p-check-004"><span data-sentence-id="s-check-004">Guidelines: This is venue boilerplate.</span></p>
        """,
    )
    units = module.extract_units(source)
    assert sentence_ids(units) == ["s-check-002", "s-check-003"]


def test_checklist_boilerplate_flag_restores_template_text(tmp_path: Path) -> None:
    module = load_module()
    source = write_source(
        tmp_path,
        """
        <h1 id="neurips-paper-checklist">NeurIPS Paper Checklist</h1>
        <p data-paragraph-id="p-check-001"><span data-sentence-id="s-check-001">Question: Does the paper disclose compute?</span></p>
        <p data-paragraph-id="p-check-002"><span data-sentence-id="s-check-002">Answer:</span></p>
        <p data-paragraph-id="p-check-003"><span data-sentence-id="s-check-003">Guidelines: This is venue boilerplate.</span></p>
        """,
    )
    units = module.extract_units(source, include_checklist_boilerplate=True)
    assert sentence_ids(units) == ["s-check-001", "s-check-002", "s-check-003"]


def test_duplicate_sentence_id_is_kept_once(tmp_path: Path) -> None:
    module = load_module()
    source = write_source(
        tmp_path,
        """
        <h1 id="intro">Intro</h1>
        <p data-paragraph-id="p1"><span data-sentence-id="s1">Original.</span></p>
        <p data-paragraph-id="p2"><span data-sentence-id="s1">Duplicate wrapper.</span></p>
        """,
    )
    units = module.extract_units(source)
    assert sentence_ids(units) == ["s1"]


def test_missing_paragraph_parent_gets_fallback_id(tmp_path: Path) -> None:
    module = load_module()
    source = write_source(
        tmp_path,
        """
        <h1 id="methods">Methods</h1>
        <span data-sentence-id="s-methods-001">Loose sentence.</span>
        """,
    )
    units = module.extract_units(source)
    paragraphs = paragraph_units(units)
    assert paragraphs[0]["paragraph_id"] == "p-methods-unparagraphized"
    assert sentence_ids(units) == ["s-methods-001"]


def test_heading_without_id_is_not_section_unit(tmp_path: Path) -> None:
    module = load_module()
    source = write_source(
        tmp_path,
        """
        <h1>No ID Heading</h1>
        <p data-paragraph-id="p-front-001"><span data-sentence-id="s-front-001">Front text.</span></p>
        """,
    )
    units = module.extract_units(source)
    assert [unit for unit in units if unit.get("kind") == "section"] == []
    assert paragraph_units(units)[0]["section_id"] == "front-matter"


def test_markdown_writer_skips_empty_paragraphs(tmp_path: Path) -> None:
    module = load_module()
    units = [
        {"kind": "section", "section_id": "intro", "level": 1, "text": "Intro"},
        {"kind": "paragraph", "paragraph_id": "p-empty", "section_id": "intro", "section_title": "Intro", "sentences": []},
        {
            "kind": "paragraph",
            "paragraph_id": "p-full",
            "section_id": "intro",
            "section_title": "Intro",
            "sentences": [{"sentence_id": "s1", "text": "Sentence."}],
        },
    ]
    output = tmp_path / "units.md"
    module.write_markdown(units, output)
    text = output.read_text(encoding="utf-8")
    assert "p-empty" not in text
    assert "{s1} Sentence." in text
