#!/usr/bin/env python3
"""Seeded defect fixtures for Ariadne signal extraction."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_paper_text.py"
FIXTURES = ROOT / "tests" / "fixtures" / "seeded_defects"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_paper_text", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load extract_paper_text module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_seeded_defect_signals_match_manifest() -> None:
    module = load_module()
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        raw = (FIXTURES / case["file"]).read_text(encoding="utf-8")
        output = "\n".join(module.summarize_table_sanity(raw, 50) + module.summarize_symbol_consistency(raw, 50))
        for needle in case["must_find"]:
            if needle not in output:
                raise AssertionError(f"{case['file']} missing expected signal {needle!r}\n--- output ---\n{output}")
        for forbidden in case["must_not_claim"]:
            if forbidden.lower() in output.lower():
                raise AssertionError(f"{case['file']} made forbidden claim {forbidden!r}\n--- output ---\n{output}")


def main() -> int:
    test_seeded_defect_signals_match_manifest()
    print("seeded defect fixture tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
