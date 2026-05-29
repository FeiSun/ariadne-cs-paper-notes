#!/usr/bin/env python3
"""Regression tests for audit_sentence_bbox.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_sentence_bbox.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_sentence_bbox", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load audit_sentence_bbox")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_evidence_snippet_must_match_anchor_text() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        units.write_text(
            json.dumps(
                {
                    "kind": "paragraph",
                    "paragraph_id": "p-intro-001",
                    "section_id": "intro",
                    "sentences": [
                        {
                            "sentence_id": "s-intro-p001-s001",
                            "unit_kind": "prose",
                            "text": "The method improves accuracy on NQ.",
                            "rendered_text_initial": "The method improves accuracy on NQ.",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        bbox = root / "bbox.json"
        write_json(
            bbox,
            {
                "anchors": {
                    "s-intro-p001-s001": {
                        "confidence": "high",
                        "unmappable": False,
                        "rendered_text_pdf": "The method improves accuracy on NQ.",
                        "rects": [{"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10}],
                    }
                }
            },
        )
        annotations = root / "annotations.json"
        write_json(
            annotations,
            {"annotations": [{"issue_id": "F1", "target_level": "sentence", "sentence_id": "s-intro-p001-s001"}]},
        )
        findings = root / "findings.json"
        write_json(
            findings,
            {"findings": [{"id": "F1", "snippet": "unrelated claim text"}]},
        )
        errors, _warnings, _summary = module.audit_sentence_bbox(
            review_units=units,
            review_units_pdf_text=None,
            sentence_bbox=bbox,
            annotations=annotations,
            findings=findings,
            evidence_threshold=0.80,
        )

    if not any("evidence snippet" in error for error in errors):
        raise AssertionError(f"Expected evidence mismatch error, got {errors}")


def test_bbox_anchor_coverage_warns_on_weak_text_match() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        units.write_text(
            json.dumps(
                {
                    "kind": "paragraph",
                    "paragraph_id": "p-intro-001",
                    "sentences": [
                        {
                            "sentence_id": "s-intro-p001-s001",
                            "unit_kind": "prose",
                            "text": "The method improves accuracy on NQ.",
                            "rendered_text_initial": "The method improves accuracy on NQ.",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        bbox = root / "bbox.json"
        write_json(
            bbox,
            {
                "anchors": {
                    "s-intro-p001-s001": {
                        "confidence": "high",
                        "unmappable": False,
                        "rendered_text_pdf": "A different sentence appears here.",
                        "rects": [{"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10}],
                    }
                }
            },
        )
        errors, warnings, summary = module.audit_sentence_bbox(
            review_units=units,
            review_units_pdf_text=None,
            sentence_bbox=bbox,
            annotations=None,
            findings=None,
            evidence_threshold=0.80,
        )

    if errors:
        raise AssertionError(f"Expected weak bbox text to warn, not error: {errors}")
    if summary.get("weak_bbox_anchors") != 1 or not any("weakly matches" in warning for warning in warnings):
        raise AssertionError(f"Expected weak bbox warning, got summary={summary}, warnings={warnings}")


def test_caption_label_anchor_is_auditable() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        units.write_text(
            json.dumps(
                {
                    "kind": "paragraph",
                    "paragraph_id": "cap-results-001",
                    "unit_kind": "caption",
                    "label": "fig:example",
                    "sentences": [
                        {
                            "sentence_id": "s-results-001-s001",
                            "unit_kind": "caption",
                            "label": "fig:example",
                            "text": "Training dynamics.",
                            "rendered_text_initial": "Training dynamics.",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        bbox = root / "bbox.json"
        write_json(
            bbox,
            {
                "anchors": {
                    "fig:example": {
                        "confidence": "medium",
                        "unmappable": False,
                        "rendered_text_pdf": "Figure 1: Training dynamics.",
                        "rects": [{"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10}],
                    }
                }
            },
        )
        annotations = root / "annotations.json"
        write_json(
            annotations,
            {"annotations": [{"issue_id": "F1", "target_level": "section", "section_id": "fig:example"}]},
        )
        errors, _warnings, summary = module.audit_sentence_bbox(
            review_units=units,
            review_units_pdf_text=None,
            sentence_bbox=bbox,
            annotations=annotations,
            findings=None,
            evidence_threshold=0.80,
        )

    if errors or summary.get("mapped_annotations") != 1:
        raise AssertionError(f"Expected caption label anchor to audit cleanly, errors={errors}, summary={summary}")


if __name__ == "__main__":
    test_evidence_snippet_must_match_anchor_text()
    test_bbox_anchor_coverage_warns_on_weak_text_match()
    test_caption_label_anchor_is_auditable()
    print("audit_sentence_bbox regression tests passed")
