#!/usr/bin/env python3
"""Regression tests for render_pdf_overlay_html.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_pdf_overlay_html.py"


def load_module():
    spec = importlib.util.spec_from_file_location("render_pdf_overlay_html", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load render_pdf_overlay_html")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_fixture(root: Path, *, mapped: bool = True) -> Path:
    module = load_module()
    pdf = root / "main.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    findings = root / "findings.json"
    write_json(
        findings,
        {
            "findings": [
                {
                    "id": "F1",
                    "severity": "Major",
                    "issue_type": "prose",
                    "title": "Sentence issue",
                    "diagnosis": "Tighten this sentence.",
                },
                {
                    "id": "F2",
                    "severity": "Minor",
                    "issue_type": "prose",
                    "title": "Unmapped issue",
                    "diagnosis": "Unmapped.",
                },
            ]
        },
    )
    annotations = root / "annotations.json"
    write_json(
        annotations,
        {
            "annotations": [
                {"issue_id": "F1", "target_level": "sentence", "sentence_id": "s1"},
                {"issue_id": "F2", "target_level": "sentence", "sentence_id": "s2"},
            ]
        },
    )
    bbox = root / "sentence_bbox.json"
    write_json(
        bbox,
        {
            "pdf_hash": "sha256:abc",
            "review_units_hash": "sha256:def",
            "page_sizes": {"1": {"width": 100, "height": 200}},
            "coverage": {"anchors_total": 2, "mapped": 1 if mapped else 0, "unmappable": 1},
            "anchors": {
                "s1": {"unmappable": not mapped, "rects": [{"page": 1, "x0": 10, "y0": 20, "x1": 50, "y1": 40}] if mapped else []},
                "s2": {"unmappable": True, "reason": "no match"},
            },
        },
    )
    output = root / "index.html"
    module.render_overlay_html(
        pdf=pdf,
        findings_path=findings,
        annotations_path=annotations,
        sentence_bbox_path=bbox,
        coverage_path=None,
        manifest_path=None,
        output=output,
        dpi=150,
        title="Test",
    )
    return output


def test_pdf_overlay_uses_pdfjs_instead_of_page_images() -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        output = render_fixture(root)
        html = output.read_text(encoding="utf-8")

        if not (output.parent / "paper.pdf").exists():
            raise AssertionError("Expected embedded PDF copy in report bundle")
        if not (output.parent / "pdfjs" / "pdf.min.js").exists() or not (output.parent / "pdfjs" / "pdf.worker.min.js").exists():
            raise AssertionError("Expected local PDF.js runtime assets in report bundle")
        if (output.parent / "pages").exists() or "pages/page-" in html or "<img " in html:
            raise AssertionError("PDF.js report must not depend on page PNG images")

    expected = [
        'data-report-kind="pdf-overlay"',
        'data-paper-view="pdfjs-overlay"',
        'data-annotation-mode="pdfjs-overlay"',
        'id="pdfjs-viewer"',
        'src="pdfjs/pdf.min.js"',
        "pdfjsLib.getDocument({url: pdfSource})",
        "pdfjsLib.renderTextLayer",
        'className = \'pdf-text-layer\'',
        'class=\\"pdf-highlight paper-sentence has-annotation severity-major\\"',
        'data-card-ids=\\"ann-F1\\"',
        'data-jump-page="1"',
        "ArrowDown",
        "focusCardAt",
    ]
    for token in expected:
        if token not in html:
            raise AssertionError(f"Expected PDF.js overlay token missing: {token}")


def test_pdf_overlay_marks_unmapped_cards_without_fake_jump() -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        html = render_fixture(Path(tempdir)).read_text(encoding="utf-8")

    if 'id="ann-F2"' not in html or 'data-unanchored="true"' not in html:
        raise AssertionError("Expected unmapped annotation card to be explicit")
    if '<span class="card-title">Unmapped issue</span>\n    <span class="card-jump-label">未映射到 PDF</span>' not in html:
        raise AssertionError("Expected unmapped card to tell the reader it cannot jump to PDF")
    if 'data-jump-target="s2"' in html:
        raise AssertionError("Unmapped card must not expose a fake PDF jump target")


if __name__ == "__main__":
    test_pdf_overlay_uses_pdfjs_instead_of_page_images()
    test_pdf_overlay_marks_unmapped_cards_without_fake_jump()
    print("render_pdf_overlay_html regression tests passed")
