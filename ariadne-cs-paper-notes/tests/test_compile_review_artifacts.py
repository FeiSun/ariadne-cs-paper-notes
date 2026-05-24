#!/usr/bin/env python3
"""Regression tests for Ariadne issue-artifact compilation."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compile_review_artifacts.py"
AUDIT_SCRIPT = ROOT / "scripts" / "audit_review_artifacts.py"


def load_module(script: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def specialist_artifact(domain: str = "reference") -> dict[str, object]:
    return {
        "artifact_type": "ariadne_issue_artifact",
        "domain": domain,
        "context_policy": "model_readable_issue_only",
        "status": "completed",
        "source_artifacts": [
            {"path": f"{domain}_audit.json", "hash": "sha256:1234567890abcdef", "context_policy": "tool_only"}
        ],
        "coverage": {"checked": 3, "issues": 1, "skipped": 0},
        "issues": [
            {
                "local_id": "R1",
                "severity": "Major",
                "issue_type": "reference_format",
                "title": "Hidden DOI fields",
                "diagnosis": "Several cited entries use non-standard xdoi fields, so identifiers may not render.",
                "reader_friction": "Reviewers have to hunt for identifiers manually.",
                "writing_principle": "verifiable citation metadata",
                "self_check": "Do cited entries render DOI or URL fields in the bibliography?",
                "evidence_refs": ["bib:R1"],
                "confidence": "high",
                "severity_rationale": "Affects many cited references.",
                "downgrade_condition": "All cited identifiers render in the final bibliography.",
                "render_hint": {"anchor": "page:references", "display_group": "Reference Hygiene"},
            }
        ],
    }


def test_compile_jsonl_and_specialist_artifacts() -> None:
    module = load_module(SCRIPT, "compile_review_artifacts")
    audit = load_module(AUDIT_SCRIPT, "audit_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        issues = root / "issue_artifacts"
        issues.mkdir()
        (issues / "prose_issues.jsonl").write_text(
            json.dumps(
                {
                    "local_id": "P1",
                    "severity": "Minor",
                    "issue_type": "prose",
                    "title": "Opening sentence overclaims",
                    "diagnosis": "The sentence states a universal claim before naming the experimental boundary.",
                    "target_anchors": ["s-intro-p001-s001"],
                    "spans_sections": False,
                    "confidence": "medium",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (issues / "whole_paper_findings.jsonl").write_text(
            json.dumps(
                {
                    "local_id": "W1",
                    "severity": "Major",
                    "issue_type": "claim_evidence",
                    "title": "Single-run evidence is used like a stable result",
                    "diagnosis": "The paper-level story does not separate exploratory evidence from stable claims.",
                    "target_anchors": ["abstract", "experiments"],
                    "spans_sections": True,
                    "confidence": "medium",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        write_json(issues / "reference_issues.json", specialist_artifact())

        findings, annotations, index = module.compile_artifacts(
            issues_dir=issues,
            source_artifact="paper.source.html",
            source_hash="sha256:aaaaaaaaaaaaaaaa",
        )

        if index["source_issue_count"] != 3 or index["finding_count"] != 3:
            raise AssertionError(f"Unexpected compile counts: {index}")
        if len(index["normalized_jsonl_shards"]) != 2:
            raise AssertionError(f"Expected JSONL shards to be normalized, got {index['normalized_jsonl_shards']}")
        if annotations["annotation_schema"] != "anchor-only":
            raise AssertionError(f"Expected anchor-only annotations, got {annotations}")
        if [item["id"] for item in findings["findings"]] != ["F1", "F2", "F3"]:
            raise AssertionError(f"Expected stable F ids, got {findings['findings']}")
        source_ids = [item["source_issue_ids"][0] for item in findings["findings"]]
        if source_ids != ["prose:P1", "whole_paper:W1", "reference:R1"]:
            raise AssertionError(f"Unexpected source issue ids: {source_ids}")

        errors, warnings, _ids = audit.audit_findings(findings)
        if errors or warnings:
            raise AssertionError(f"Compiled findings should satisfy finding audit, errors={errors}, warnings={warnings}")
        errors, warnings = audit.audit_annotations(annotations, finding_ids={item["id"] for item in findings["findings"]})
        if errors:
            raise AssertionError(f"Compiled annotations should satisfy annotation audit, errors={errors}, warnings={warnings}")


def test_compiler_deduplicates_matching_evidence_refs() -> None:
    module = load_module(SCRIPT, "compile_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        issues = Path(tempdir) / "issue_artifacts"
        issues.mkdir()
        payload = specialist_artifact("layout")
        second = dict(payload["issues"][0])  # type: ignore[index]
        second["local_id"] = "R2"
        second["title"] = "Same issue repeated"
        payload["issues"].append(second)  # type: ignore[index,union-attr]
        payload["coverage"] = {"checked": 3, "issues": 2, "skipped": 0}
        write_json(issues / "layout_issues.json", payload)

        findings, _annotations, index = module.compile_artifacts(issues_dir=issues)

        if index["source_issue_count"] != 2 or index["finding_count"] != 1:
            raise AssertionError(f"Expected deduped finding, got {index}")
        source_ids = findings["findings"][0]["source_issue_ids"]
        if source_ids != ["layout:R1", "layout:R2"]:
            raise AssertionError(f"Expected merged source ids, got {source_ids}")


if __name__ == "__main__":
    test_compile_jsonl_and_specialist_artifacts()
    test_compiler_deduplicates_matching_evidence_refs()
    print("compile_review_artifacts regression tests passed")
