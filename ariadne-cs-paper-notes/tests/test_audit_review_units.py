#!/usr/bin/env python3
"""Regression tests for audit_review_units.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_review_units.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_review_units", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load audit_review_units")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def caption_row(paragraph_id: str, label: str, sentence_count: int) -> dict:
    return {
        "kind": "paragraph",
        "paragraph_id": paragraph_id,
        "section_id": "results",
        "unit_kind": "caption",
        "label": label,
        "sentences": [
            {
                "sentence_id": f"s-{paragraph_id}-{idx:03d}",
                "unit_kind": "caption",
                "label": label,
                "float_kind": "figure",
                "text": f"Caption sentence {idx}.",
                "rendered_text_initial": f"Caption sentence {idx}.",
                "source_file": "main.tex",
                "line_start": idx,
                "line_end": idx,
                "text_hash": "sha256:test",
            }
            for idx in range(1, sentence_count + 1)
        ],
    }


def test_caption_label_duplicates_are_paragraph_scoped() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        write_jsonl(
            units,
            [
                {"kind": "section", "section_id": "results", "text": "Results"},
                caption_row("cap-results-001", "fig:one", 2),
            ],
        )
        errors, _warnings, summary = module.audit_review_units(units)

    if errors or summary.get("caption_labels") != 1:
        raise AssertionError(f"Expected one multi-sentence caption label to pass, errors={errors}, summary={summary}")


def test_duplicate_caption_label_across_paragraphs_is_error() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        write_jsonl(
            units,
            [
                {"kind": "section", "section_id": "results", "text": "Results"},
                caption_row("cap-results-001", "fig:one", 1),
                caption_row("cap-results-002", "fig:one", 1),
            ],
        )
        errors, _warnings, _summary = module.audit_review_units(units)

    if not any("duplicate caption label" in error for error in errors):
        raise AssertionError(f"Expected duplicate label across caption paragraphs to error, got {errors}")


if __name__ == "__main__":
    test_caption_label_duplicates_are_paragraph_scoped()
    test_duplicate_caption_label_across_paragraphs_is_error()
    print("audit_review_units regression tests passed")
