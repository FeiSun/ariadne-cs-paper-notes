#!/usr/bin/env python3
"""Regression tests for Phase B context compaction."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_phase_b_input.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_phase_b_input", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load build_phase_b_input module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_phase_b_context_compacts_phase_and_specialist_artifacts() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        issues = root / "issue_artifacts"
        cold = root / "cold_skim_frame.json"
        sections = root / "section_reflections.json"
        claims = root / "claim_candidates.json"
        output = root / "phase_b_context.json"

        write_json(
            cold,
            {
                "problem": "Answering questions with latent model knowledge.",
                "gap": "The draft underspecifies when RL reveals rather than teaches facts.",
                "idea": "Use reinforcement learning to elicit hidden knowledge.",
                "evidence": "SimpleQA-style results and pass@k analysis.",
                "boundary": "Sparse-reward factual QA only.",
                "first_reader_breaks": ["abstract overclaims mechanism", "judge validation late"],
            },
        )
        write_json(
            sections,
            {
                "sections": [
                    {
                        "section_id": "intro",
                        "title": "Introduction",
                        "one_line_summary": "Strong hook, but mechanism language outruns evidence.",
                        "role_in_argument": "Frame the central hidden-knowledge claim.",
                        "top_issue_ids": ["P1", "P2"],
                    },
                    {
                        "section": "Experiments",
                        "summary": "Evidence is promising but single-run and judge-coupled.",
                        "linked_findings": ["P7"],
                    },
                ],
                "cross_section_terms": [
                    {
                        "term": "hidden knowledge",
                        "definitions": [
                            {"section_id": "intro", "anchor": "s-intro-1", "meaning": "latent facts"},
                            {"section_id": "experiments", "anchor": "s-exp-4", "meaning": "answerable items"},
                        ],
                        "issue_ids": ["P9"],
                    }
                ],
            },
        )
        write_json(
            claims,
            {
                "claim_candidates": [
                    {
                        "id": "C1",
                        "text": "RL unlocks latent knowledge rather than acquiring new facts.",
                        "location": "Abstract",
                        "strength": "strong mechanism claim",
                        "source_issue_ids": ["P1"],
                    }
                ]
            },
        )
        write_json(
            issues / "layout_issues.json",
            {
                "artifact_type": "ariadne_issue_artifact",
                "domain": "layout",
                "context_policy": "model_readable_issue_only",
                "status": "completed",
                "source_artifacts": [{"path": "layout_audit.json", "hash": "sha256:abc", "context_policy": "tool_only"}],
                "coverage": {"checked": 2, "issues": 1, "skipped": 0},
                "issues": [
                    {
                        "local_id": "L1",
                        "severity": "Major",
                        "issue_type": "layout",
                        "title": "Main table is cramped",
                        "diagnosis": "The main result table is hard to scan.",
                        "evidence_refs": ["layout-p002-001"],
                        "confidence": "medium",
                        "render_hint": {"anchor": "page:2", "display_group": "compiled-display-checks"},
                    }
                ],
            },
        )
        write_json(
            issues / "prose_issues.json",
            {
                "artifact_type": "ariadne_issue_artifact",
                "domain": "prose",
                "context_policy": "model_readable_issue_only",
                "status": "completed",
                "coverage": {"checked": 10, "issues": 1, "skipped": 0},
                "issues": [{"local_id": "P1", "severity": "Major", "title": "Should not appear as specialist compact issue"}],
            },
        )

        rc = module.main(
            [
                "--cold-skim",
                str(cold),
                "--section-reflections",
                str(sections),
                "--claim-candidates",
                str(claims),
                "--issues-dir",
                str(issues),
                "--out",
                str(output),
            ]
        )
        if rc != 0:
            raise AssertionError("build_phase_b_input returned nonzero")
        payload = json.loads(output.read_text(encoding="utf-8"))

    if payload["schema_version"] != 1:
        raise AssertionError("phase_b_context schema version mismatch")
    if payload["context_policy"] != "model_readable_compact_synthesis_input":
        raise AssertionError("phase_b_context missing context policy")
    if payload["coverage"]["sections_summarized"] != 2:
        raise AssertionError(f"expected 2 sections, got {payload['coverage']}")
    if payload["coverage"]["specialist_domains"] != 1 or payload["coverage"]["issue_count"] != 1:
        raise AssertionError(f"expected only layout specialist issue, got {payload['coverage']}")
    if payload["section_summaries"][1]["section_id"] != "experiments":
        raise AssertionError("section id fallback should derive from section title")
    if payload["specialist_issues_compact"][0]["local_id"] != "L1":
        raise AssertionError("layout issue missing from compact specialist issues")
    if any(item.get("local_id") == "P1" for item in payload["specialist_issues_compact"]):
        raise AssertionError("prose issues should not be duplicated as specialist compact issues")
    if not all("hash" in item for item in payload["source_artifacts"]):
        raise AssertionError("all source artifacts should carry hashes")


def test_phase_b_context_accepts_legacy_cold_skim_recoverable_fields() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        issues = root / "issue_artifacts"
        issues.mkdir()
        cold = root / "cold_skim_frame.json"
        sections = root / "section_reflections.json"
        claims = root / "claim_candidates.json"
        output = root / "phase_b_context.json"
        write_json(
            cold,
            {
                "problem_recoverable": "Legacy problem field.",
                "gap_recoverable": "Legacy gap field.",
                "idea_recoverable": "Legacy idea field.",
                "evidence_recoverable": "Legacy evidence field.",
                "boundary_recoverable": "Legacy boundary field.",
                "skim_breaks": [{"id": "B1"}, "B2"],
            },
        )
        write_json(sections, {"sections": [{"section_id": "intro", "one_line": "done"}]})
        write_json(claims, {"claim_candidates": [{"id": "C1", "text": "Claim"}]})
        status = module.main(
            [
                "--cold-skim",
                str(cold),
                "--section-reflections",
                str(sections),
                "--claim-candidates",
                str(claims),
                "--issues-dir",
                str(issues),
                "--out",
                str(output),
            ]
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
    if status != 0:
        raise AssertionError("build_phase_b_input returned nonzero")
    skim = payload["cold_skim"]
    if skim["problem"] != "Legacy problem field." or skim["gap"] != "Legacy gap field.":
        raise AssertionError(f"Legacy cold skim fields were not normalized: {skim}")
    if skim["first_reader_breaks"] != ["B1", "B2"]:
        raise AssertionError(f"Legacy skim breaks were not normalized: {skim}")


def main() -> int:
    test_phase_b_context_compacts_phase_and_specialist_artifacts()
    test_phase_b_context_accepts_legacy_cold_skim_recoverable_fields()
    print("build_phase_b_input regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
