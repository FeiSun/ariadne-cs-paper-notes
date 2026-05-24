#!/usr/bin/env python3
"""Regression tests for symbol/notation consistency checks."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_symbol.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_symbol", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_symbol")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_symbol_audit_emits_macro_unknown_and_variant_signals() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\newcommand{\risk}{R}",
                    r"\renewcommand{\risk}{\mathcal{R}}",
                    r"\begin{document}",
                    r"\begin{equation}",
                    r"\epsilon = \varepsilon + \mystery(x)",
                    r"\end{equation}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        payload = module.build_payload(tex)

    issue_types = {item["issue_type"] for item in payload["observations"]}
    expected = {"macro_redefinition", "unknown_math_command", "variant_symbol_pair"}
    if not expected <= issue_types:
        raise AssertionError(f"Missing symbol issue types {expected - issue_types}; got {issue_types}")
    if any("equation is wrong" in item["evidence"].lower() for item in payload["observations"]):
        raise AssertionError(f"Symbol audit should not assert equation correctness: {payload}")


def test_symbol_cli_writes_json() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        out = root / "symbol_audit.json"
        tex.write_text(r"\documentclass{article}\begin{document}No display math.\end{document}", encoding="utf-8")
        status = module.main([str(tex), "--out", str(out)])
        if status != 0:
            raise AssertionError(f"check_symbol CLI returned {status}")
        payload = json.loads(out.read_text(encoding="utf-8"))
    if payload["tool"] != "scripts/check_symbol.py":
        raise AssertionError(f"Missing tool provenance: {payload}")


if __name__ == "__main__":
    test_symbol_audit_emits_macro_unknown_and_variant_signals()
    test_symbol_cli_writes_json()
    print("check_symbol regression tests passed")
