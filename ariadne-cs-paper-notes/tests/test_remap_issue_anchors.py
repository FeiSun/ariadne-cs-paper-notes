#!/usr/bin/env python3
"""Regression tests for remap_issue_anchors.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "remap_issue_anchors.py"


def load_module():
    spec = importlib.util.spec_from_file_location("remap_issue_anchors", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load remap_issue_anchors")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_remap_sentence_anchor_by_snippet() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        units.write_text(
            (
                '{"kind":"paragraph","paragraph_id":"p-introduction-001","section_id":"introduction",'
                '"sentences":[{"sentence_id":"s-introduction-001-s001","text":"The method improves factual recall."}]}\n'
            ),
            encoding="utf-8",
        )
        index = module.review_unit_index(units)
        row = {
            "local_id": "P1",
            "snippet": "The method improves factual recall.",
            "primary_anchor": "s-introduction-p001-s001",
            "target_anchors": ["s-introduction-p001-s001"],
            "render_hint": {"anchor": "s-introduction-p001-s001", "target_level": "sentence"},
        }

        remapped, changes = module.remap_row(row, index, threshold=0.80)

    if remapped["primary_anchor"] != "s-introduction-001-s001":
        raise AssertionError(f"Expected remapped sentence anchor, got {remapped}")
    if remapped["target_anchors"] != ["s-introduction-001-s001"]:
        raise AssertionError(f"Expected remapped target anchors, got {remapped}")
    if remapped["render_hint"]["anchor"] != "s-introduction-001-s001" or remapped["render_hint"]["target_level"] != "sentence":
        raise AssertionError(f"Expected remapped render hint, got {remapped}")
    if not changes:
        raise AssertionError("Expected remap changes to be recorded")


def test_section_alias_is_exact_anchor() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        units.write_text(
            '{"kind":"section","section_id":"background","text":"Background","aliases":["sec:background"]}\n',
            encoding="utf-8",
        )
        index = module.review_unit_index(units)

    replacement, score, method = module.replacement_for_anchor(
        "sec:background",
        row={"snippet": "Background"},
        units=index,
        threshold=0.80,
    )

    if replacement != "background" or score != 1.0 or method != "kept_exact":
        raise AssertionError(f"Expected section alias to map to canonical id, got {(replacement, score, method)}")


if __name__ == "__main__":
    test_remap_sentence_anchor_by_snippet()
    test_section_alias_is_exact_anchor()
    print("remap_issue_anchors regression tests passed")
