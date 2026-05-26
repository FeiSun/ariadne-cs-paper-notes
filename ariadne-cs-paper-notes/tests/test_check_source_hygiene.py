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


def test_acl_review_front_matter_author_commands_are_not_visible_identity_findings() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\documentclass{article}",
            r"\usepackage[review]{acl}",
            r"\author{Jane Doe \\ Secret Lab \\ jane@example.com}",
            r"\begin{document}",
            r"\maketitle",
            r"Clean body.",
            r"\end{document}",
        ]
    )
    observations, coverage = module.audit_source(raw, raw)
    titles = [item["title"] for item in observations]
    if any("Identity/anonymity signals are visible in the source" == title for title in titles):
        raise AssertionError(f"ACL review front-matter author commands should not become visible identity findings: {observations}")
    if coverage.get("acl_review_mode") != 1 or coverage.get("front_matter_identity_items_suppressed", 0) == 0:
        raise AssertionError(f"Expected ACL review-mode suppression coverage, got {coverage}")


def test_compiled_pdf_text_controls_front_matter_identity_visibility_for_any_template() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\documentclass{article}",
            r"\author{Jane Doe \\ Secret Lab \\ jane@example.com}",
            r"\begin{document}",
            r"\maketitle",
            r"Clean body.",
            r"\end{document}",
        ]
    )
    anonymous_pdf = "Demo Paper\nAnonymous submission\n\nAbstract\nClean body."
    observations, coverage = module.audit_source(raw, raw, compiled_text=anonymous_pdf, compiled_source="paper.pdf")
    if any(item.get("issue_type") == "anonymity" for item in observations):
        raise AssertionError(f"Front-matter source identity should be suppressed when compiled PDF is anonymous: {observations}")
    if coverage.get("compiled_visibility_checked") != 1 or coverage.get("compiled_front_matter_identity_items") != 0:
        raise AssertionError(f"Expected compiled anonymous coverage, got {coverage}")

    visible_pdf = "Demo Paper\nJane Doe\nSecret Lab\njane@example.com\n\nAbstract\nClean body."
    observations, coverage = module.audit_source(raw, raw, compiled_text=visible_pdf, compiled_source="paper.pdf")
    titles = [item["title"] for item in observations]
    if "Compiled submission still exposes identity/anonymity signals" not in titles:
        raise AssertionError(f"Compiled visible identity should remain an anonymity issue: {observations}")
    compiled_observation = next(item for item in observations if item["title"] == "Compiled submission still exposes identity/anonymity signals")
    if compiled_observation.get("visibility_basis") != "compiled_pdf":
        raise AssertionError(f"Expected compiled-PDF visibility basis, got {compiled_observation}")
    if coverage.get("compiled_front_matter_identity_items", 0) == 0:
        raise AssertionError(f"Expected visible compiled front-matter identity coverage, got {coverage}")


if __name__ == "__main__":
    test_source_hygiene_emits_anonymity_and_placeholder_findings()
    test_source_hygiene_cli_writes_json()
    test_acl_review_front_matter_author_commands_are_not_visible_identity_findings()
    test_compiled_pdf_text_controls_front_matter_identity_visibility_for_any_template()
    print("check_source_hygiene regression tests passed")
