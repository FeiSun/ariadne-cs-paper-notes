#!/usr/bin/env python3
"""Regression tests for structured reference hygiene checks."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_references.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_references", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_references")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reference_checker_emits_hygiene_findings() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bib = root / "refs.bib"
        bib.write_text(
            "\n".join(
                [
                    "@article{deepseek2025r1,",
                    "  title={DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning},",
                    "  author={Li, YK and Qwen: and Team},",
                    "  journal={arXiv preprint arXiv: 2501.00001},",
                    "  year={2025},",
                    "  xurl={https://example.com},",
                    "  xdoi={10.1000/example}",
                    "}",
                    "@article{mismatch,",
                    "  title={Mismatched arXiv year},",
                    "  author={Doe, Jane},",
                    "  journal={arXiv preprint arXiv:2101.12345},",
                    "  year={2025}",
                    "}",
                    "@article{clean,",
                    "  title={{BERT} is protected},",
                    "  author={Doe, Jane},",
                    "  journal={Journal},",
                    "  year={2024},",
                    "  doi={10.1000/clean}",
                    "}",
                ]
            ),
            encoding="utf-8",
        )
        payload = module.build_payload(bib)

    titles = [finding["title"] for finding in payload["findings"]]
    expected = [
        "Non-standard URL/DOI/eprint fields suppress bibliographic metadata",
        "Inconsistent arXiv metadata style",
        "arXiv identifier year and BibTeX year appear inconsistent",
        "Author-field formatting anomalies",
        "Acronyms and model names may be lowercased by the bibliography style",
    ]
    for title in expected:
        if title not in titles:
            raise AssertionError(f"Missing reference finding {title!r}; got {titles}")
    if payload["reference_count_estimate"]["bibtex_entries_in_bib_files"] != 3:
        raise AssertionError(f"Unexpected reference counts: {payload['reference_count_estimate']}")


def test_reference_checker_cli_writes_json() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bib = root / "refs.bib"
        out = root / "references_audit.json"
        bib.write_text("@article{x,title={X},author={A},year={2024}}\n", encoding="utf-8")
        status = module.main([str(bib), "--out", str(out)])
        if status != 0:
            raise AssertionError(f"check_references CLI returned {status}")
        payload = json.loads(out.read_text(encoding="utf-8"))
    if payload["tool"] != "scripts/check_references.py":
        raise AssertionError(f"Missing tool provenance: {payload}")


if __name__ == "__main__":
    test_reference_checker_emits_hygiene_findings()
    test_reference_checker_cli_writes_json()
    print("check_references regression tests passed")
