#!/usr/bin/env python3
"""Regression tests for source-level figure/caption checks."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_figure_caption.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_figure_caption", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_figure_caption")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_figure_caption_audit_emits_source_level_signals() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        figures = root / "figures"
        figures.mkdir()
        (figures / "exists.pdf").write_text("fake", encoding="utf-8")
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"See Figure~\ref{fig:missing}.",
                    r"\begin{figure}",
                    r"\includegraphics{figures/missing}",
                    r"\label{fig:no-caption}",
                    r"\end{figure}",
                    r"\begin{figure}",
                    r"\includegraphics{figures/exists}",
                    r"\caption{TODO}",
                    r"\end{figure}",
                    r"\begin{table}",
                    r"\caption{Short}",
                    r"\label{tab:short}",
                    r"\end{table}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        payload = module.build_payload(tex)

    issue_types = {item["issue_type"] for item in payload["observations"]}
    expected = {
        "missing_caption",
        "thin_caption",
        "caption_placeholder",
        "missing_label",
        "unresolved_float_reference",
        "missing_graphic_asset",
    }
    if not expected <= issue_types:
        raise AssertionError(f"Missing figure/caption issue types {expected - issue_types}; got {issue_types}")


def test_rendered_caption_geometry_flags_edge_and_label_only_lines() -> None:
    module = load_module()
    parsed_pages = [
        (
            1,
            {
                "width": 612.0,
                "height": 792.0,
                "lines": [
                    {
                        "xMin": 4.0,
                        "yMin": 730.0,
                        "xMax": 606.0,
                        "yMax": 748.0,
                        "words": [
                            {"text": "Figure", "xMin": 4.0, "yMin": 730.0, "xMax": 40.0, "yMax": 748.0},
                            {"text": "1:", "xMin": 45.0, "yMin": 730.0, "xMax": 60.0, "yMax": 748.0},
                        ],
                    }
                ],
            },
        )
    ]
    observations, coverage = module.analyze_rendered_caption_pages(
        parsed_pages,
        source_caption_count=1,
        pages_all=True,
    )
    issue_types = {item["issue_type"] for item in observations}
    expected = {"rendered_caption_edge_risk", "rendered_caption_label_only"}
    if not expected <= issue_types:
        raise AssertionError(f"Missing rendered caption issue types {expected - issue_types}; got {issue_types}")
    if coverage["rendered_pages_checked"] != 1 or coverage["rendered_captions_detected"] != 1:
        raise AssertionError(f"Unexpected rendered coverage: {coverage}")


def test_raster_asset_quality_flags_low_resolution_and_blank_assets() -> None:
    module = load_module()
    try:
        from PIL import Image
    except Exception:
        return
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        figures = root / "figures"
        figures.mkdir()
        image_path = figures / "blank.png"
        Image.new("RGB", (180, 120), "white").save(image_path)
        raw = r"\includegraphics{figures/blank}"
        observations, coverage, warnings = module.audit_raster_asset_quality(raw, root)

    issue_types = {item["issue_type"] for item in observations}
    expected = {"low_resolution_figure_asset", "near_blank_figure_asset"}
    if not expected <= issue_types:
        raise AssertionError(f"Missing raster asset issue types {expected - issue_types}; got {issue_types}")
    if warnings:
        raise AssertionError(f"Unexpected raster warnings: {warnings}")
    if coverage["raster_assets_checked"] != 1 or coverage["raster_asset_signals_checked"] < 2:
        raise AssertionError(f"Unexpected raster coverage: {coverage}")


def test_pdf_asset_quality_flags_blank_preview_when_pdftoppm_available() -> None:
    module = load_module()
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return
    try:
        from PIL import Image
    except Exception:
        return
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        figures = root / "figures"
        figures.mkdir()
        pdf_path = figures / "blank_plot.pdf"
        Image.new("RGB", (480, 320), "white").save(pdf_path)
        raw = r"\includegraphics{figures/blank_plot}"
        observations, coverage, warnings = module.audit_figure_asset_quality(raw, root, pdftoppm=pdftoppm)

    issue_types = {item["issue_type"] for item in observations}
    if "near_blank_figure_asset" not in issue_types:
        raise AssertionError(f"Expected near-blank PDF preview signal; got {issue_types}")
    if warnings:
        raise AssertionError(f"Unexpected PDF asset warnings: {warnings}")
    if coverage["pdf_figure_assets_checked"] != 1 or coverage["pdf_figure_asset_signals_checked"] < 1:
        raise AssertionError(f"Unexpected PDF asset coverage: {coverage}")


def test_combined_source_and_rendered_observations_have_unique_ids() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\begin{figure}",
                    r"\caption{Short}",
                    r"\label{fig:short}",
                    r"\end{figure}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )

        def fake_rendered_pdf(*args, **kwargs):  # noqa: ARG001
            return (
                [
                    {
                        "observation_id": "figure-caption-001",
                        "issue_type": "rendered_caption_label_only",
                        "severity": "low",
                        "title": "Rendered caption is thin",
                        "evidence": "page 1: Figure 1:",
                        "recommendation": "Inspect caption.",
                        "confidence": 0.64,
                    }
                ],
                {"rendered_pages_checked": 1, "rendered_captions_detected": 1, "rendered_caption_signals_checked": 1},
                [],
            )

        module.audit_rendered_pdf = fake_rendered_pdf
        payload = module.build_payload(tex, pdf=root / "main.pdf")

    ids = [item["observation_id"] for item in payload["observations"]]
    if ids != ["figure-caption-001", "figure-caption-002"]:
        raise AssertionError(f"Combined observations should have stable unique ids, got {ids}")
    if payload["observations"][1].get("details", {}).get("original_observation_id") != "figure-caption-001":
        raise AssertionError(f"Expected original id provenance on renumbered observation: {payload['observations'][1]}")


def test_figure_caption_cli_writes_json() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        out = root / "figure_caption_audit.json"
        tex.write_text(r"\documentclass{article}\begin{document}No floats.\end{document}", encoding="utf-8")
        status = module.main([str(tex), "--out", str(out)])
        if status != 0:
            raise AssertionError(f"check_figure_caption CLI returned {status}")
        payload = json.loads(out.read_text(encoding="utf-8"))
    if payload["tool"] != "scripts/check_figure_caption.py":
        raise AssertionError(f"Missing tool provenance: {payload}")


if __name__ == "__main__":
    test_figure_caption_audit_emits_source_level_signals()
    test_rendered_caption_geometry_flags_edge_and_label_only_lines()
    test_raster_asset_quality_flags_low_resolution_and_blank_assets()
    test_pdf_asset_quality_flags_blank_preview_when_pdftoppm_available()
    test_combined_source_and_rendered_observations_have_unique_ids()
    test_figure_caption_cli_writes_json()
    print("check_figure_caption regression tests passed")
