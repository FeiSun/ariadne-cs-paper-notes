#!/usr/bin/env python3
"""Regression tests for source hygiene/anonymity checks."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_source_hygiene.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_source_hygiene", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_source_hygiene")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_hygiene_emits_anonymity_and_placeholder_findings() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass[anonymous=false]{article}",
                    r"\author{Jane Doe \thanks{Supported by grant. ORCID: 0000-0002-1825-0097}}",
                    r"\affiliation{University of Somewhere}",
                    r"\iclrfinalcopy",
                    r"\begin{document}",
                    r"Contact jane@example.com. TODO fix this. Broken ref \ref{??}.",
                    r"\section*{Acknowledgments}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        payload = module.build_payload(tex)

    titles = [item["title"] for item in payload["observations"]]
    expected = [
        "Placeholder or broken-reference markers remain in the source",
        "TODO/TBD/FIXME markers remain in the source",
        "Identity/anonymity signals are visible in the source",
        "Final/non-anonymous template switch is present",
    ]
    for title in expected:
        if title not in titles:
            raise AssertionError(f"Missing source hygiene observation {title!r}; got {titles}")


def test_source_hygiene_cli_writes_json() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        out = root / "source_hygiene_audit.json"
        tex.write_text(r"\documentclass{article}\begin{document}Clean.\end{document}", encoding="utf-8")
        status = module.main([str(tex), "--out", str(out)])
        if status != 0:
            raise AssertionError(f"check_source_hygiene CLI returned {status}")
        payload = json.loads(out.read_text(encoding="utf-8"))
    if payload["tool"] != "scripts/check_source_hygiene.py":
        raise AssertionError(f"Missing tool provenance: {payload}")


if __name__ == "__main__":
    test_source_hygiene_emits_anonymity_and_placeholder_findings()
    test_source_hygiene_cli_writes_json()
    print("check_source_hygiene regression tests passed")
