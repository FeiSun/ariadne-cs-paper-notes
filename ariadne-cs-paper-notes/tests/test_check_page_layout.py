#!/usr/bin/env python3
"""Regression tests for page-local PDF layout checks."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_page_layout.py"
PDF = ROOT / "debug" / "Hidden_Knowledge_with_RL" / "main.pdf"


def load_module():
    spec = importlib.util.spec_from_file_location("check_page_layout", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_page_layout module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_pages() -> None:
    module = load_module()
    if module.parse_pages("1-3,5", 10) != [1, 2, 3, 5]:
        raise AssertionError("page range parser returned unexpected pages")


def test_bbox_parser_preserves_camelcase_attributes() -> None:
    module = load_module()
    parser = module.BBoxParser()
    parser.feed(
        '<page width="612.0" height="792.0"><line xMin="10.5" yMin="20.0" xMax="50.5" yMax="30.0">'
        '<word xMin="10.5" yMin="20.0" xMax="50.5" yMax="30.0">Word</word></line></page>'
    )
    line = parser.pages[0]["lines"][0]
    if line["xMin"] != 10.5 or line["xMax"] != 50.5:
        raise AssertionError(f"Expected nonzero bbox values, got {line}")


def test_real_pdf_page_outputs_compact_json_when_available() -> None:
    if not PDF.exists():
        return
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        output = Path(handle.name)
    try:
        rc = load_module().main([str(PDF), "--pages", "1", "--out", str(output)])
        if rc != 0:
            raise AssertionError("check_page_layout returned nonzero")
        payload = json.loads(output.read_text(encoding="utf-8"))
    finally:
        output.unlink(missing_ok=True)
    if payload["tool"] != "scripts/check_page_layout.py":
        raise AssertionError("layout payload missing tool provenance")
    if payload["pages_checked"] != [1]:
        raise AssertionError(f"expected page 1 only, got {payload['pages_checked']}")
    if len(payload["observations"]) > 12:
        raise AssertionError("layout observations should be capped per page")
    for idx, item in enumerate(payload["observations"], 1):
        expected_prefix = "layout-p001-"
        if not str(item.get("observation_id", "")).startswith(expected_prefix):
            raise AssertionError(f"layout observation #{idx} missing stable observation_id: {item}")
        if item["region_or_bbox"] == [0.0, 0.0, 0.0, 0.0]:
            raise AssertionError(f"zero bbox leaked into observation: {item}")


def main() -> int:
    test_parse_pages()
    test_bbox_parser_preserves_camelcase_attributes()
    test_real_pdf_page_outputs_compact_json_when_available()
    print("check_page_layout regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
