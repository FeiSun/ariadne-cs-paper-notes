#!/usr/bin/env python3
"""Regression tests for audit_rendered_text_drift.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_rendered_text_drift.py"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_rendered_text_drift", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load audit_rendered_text_drift")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rendered_text_drift_reports_bad_pdf_text() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        units.write_text(
            json.dumps(
                {
                    "kind": "paragraph",
                    "paragraph_id": "p1",
                    "sentences": [
                        {
                            "sentence_id": "s1",
                            "text": "The method improves accuracy.",
                            "rendered_text_initial": "The method improves accuracy.",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        sidecar = root / "review_units_pdf_text.json"
        sidecar.write_text(
            json.dumps({"anchors": {"s1": {"rendered_text_pdf": "Completely unrelated words.", "unmappable": False}}}),
            encoding="utf-8",
        )

        errors, _warnings, summary = module.audit_drift(
            review_units=units,
            review_units_pdf_text=sidecar,
            warn_threshold=0.90,
            error_threshold=0.80,
        )

    if not errors or summary["errors"] != 1:
        raise AssertionError(f"Expected drift error, got errors={errors}, summary={summary}")


def test_rendered_text_drift_ignores_citation_rendering_style() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        units.write_text(
            json.dumps(
                {
                    "kind": "paragraph",
                    "paragraph_id": "p1",
                    "sentences": [
                        {
                            "sentence_id": "s1",
                            "text": "Large-scale models such as Qwen-VL [qwen] improve reasoning.",
                            "rendered_text_initial": "Large-scale models such as Qwen-VL [qwen] improve reasoning.",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        sidecar = root / "review_units_pdf_text.json"
        sidecar.write_text(
            json.dumps(
                {
                    "anchors": {
                        "s1": {
                            "rendered_text_pdf": "Large-scale models such as Qwen-VL [Bai et al., 2025] improve reasoning.",
                            "unmappable": False,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        errors, _warnings, summary = module.audit_drift(
            review_units=units,
            review_units_pdf_text=sidecar,
            warn_threshold=0.95,
            error_threshold=0.90,
        )

    if errors or summary["warnings"]:
        raise AssertionError(f"Expected citation style drift to pass, errors={errors}, summary={summary}")


def test_rendered_text_drift_ignores_parenthetical_author_year_citations() -> None:
    module = load_module()
    initial = module.normalize_for_drift("MPAC [yoo2024mpac] allocates generated tokens.")
    pdf = module.normalize_for_drift("MPAC (Yoo et al., 2024) allocates generated tokens.")

    if initial != pdf:
        raise AssertionError(f"Expected bracket and parenthetical citations to normalize together, got {initial!r} vs {pdf!r}")


def test_math_heavy_drift_with_good_bbox_match_warns_not_errors() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        units = root / "review_units.jsonl"
        units.write_text(
            json.dumps(
                {
                    "kind": "paragraph",
                    "paragraph_id": "p1",
                    "sentences": [
                        {
                            "sentence_id": "s1",
                            "text": r"Since each mask value $r_{x_t}(m, x_{:t})$ follows $\sum_t r_{x_t}$.",
                            "rendered_text_initial": "Since each mask value r_x_t follows _t r_x_t.",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        sidecar = root / "review_units_pdf_text.json"
        sidecar.write_text(
            json.dumps(
                {
                    "anchors": {
                        "s1": {
                            "rendered_text_pdf": "Since each mask value r x t P token count t r x t",
                            "unmappable": False,
                            "match_ratio": 0.91,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        errors, warnings, summary = module.audit_drift(
            review_units=units,
            review_units_pdf_text=sidecar,
            warn_threshold=0.95,
            error_threshold=0.90,
        )

    if errors or summary["warnings"] != 1 or not any("math-heavy" in warning for warning in warnings):
        raise AssertionError(f"Expected math-heavy drift to warn, errors={errors}, warnings={warnings}, summary={summary}")


if __name__ == "__main__":
    test_rendered_text_drift_reports_bad_pdf_text()
    test_rendered_text_drift_ignores_citation_rendering_style()
    test_rendered_text_drift_ignores_parenthetical_author_year_citations()
    test_math_heavy_drift_with_good_bbox_match_warns_not_errors()
    print("audit_rendered_text_drift regression tests passed")
