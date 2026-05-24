#!/usr/bin/env python3
"""Regression tests for mechanical polish checks."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_polish.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_polish", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_polish")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_polish_emits_grouped_mechanical_findings() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"Smith et al show the the result, e.g this fine tuning recipe.",
                    r"Later we use fine-tuning and zero shot as a baseline.",
                    r"Figure \ref{fig:demo} reports the behaviour of the model.",
                    "The behavior improves \u2014 but the source keeps smart punctuation.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        payload = module.build_payload(tex)

    issue_types = {item["issue_type"] for item in payload["observations"]}
    expected = {
        "repeated_word",
        "latin_abbreviation",
        "hyphenation_consistency",
        "spelling_consistency",
        "unicode_punctuation",
        "reference_spacing",
    }
    if not expected <= issue_types:
        raise AssertionError(f"Missing polish issue types {expected - issue_types}; got {issue_types}")


def test_polish_cli_writes_json() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        out = root / "polish_audit.json"
        tex.write_text(r"\documentclass{article}\begin{document}Clean prose.\end{document}", encoding="utf-8")
        status = module.main([str(tex), "--out", str(out)])
        if status != 0:
            raise AssertionError(f"check_polish CLI returned {status}")
        payload = json.loads(out.read_text(encoding="utf-8"))
    if payload["tool"] != "scripts/check_polish.py":
        raise AssertionError(f"Missing tool provenance: {payload}")


if __name__ == "__main__":
    test_polish_emits_grouped_mechanical_findings()
    test_polish_cli_writes_json()
    print("check_polish regression tests passed")
