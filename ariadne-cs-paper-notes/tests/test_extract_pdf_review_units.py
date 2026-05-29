#!/usr/bin/env python3
"""Regression tests for extract_pdf_review_units.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_pdf_review_units.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_pdf_review_units", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load extract_pdf_review_units")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pdf_review_units_split_pages_paragraphs_and_sentences() -> None:
    module = load_module()
    text = "Title\n\nFirst sentence. Second sentence.\fThird page sentence."
    pages = module.split_pages(text)
    paragraphs = [para for page in pages for para in module.split_paragraphs(page)]
    sentences = [sentence for paragraph in paragraphs for sentence in module.split_sentences(paragraph)]

    if pages != ["Title\n\nFirst sentence. Second sentence.", "Third page sentence."]:
        raise AssertionError(f"Unexpected pages: {pages}")
    if sentences != ["Title", "First sentence.", "Second sentence.", "Third page sentence."]:
        raise AssertionError(f"Unexpected PDF-only sentences: {sentences}")


if __name__ == "__main__":
    test_pdf_review_units_split_pages_paragraphs_and_sentences()
    print("extract_pdf_review_units regression tests passed")
