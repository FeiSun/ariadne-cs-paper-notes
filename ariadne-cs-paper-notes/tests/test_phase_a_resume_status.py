#!/usr/bin/env python3
"""Regression tests for Phase A resume status helper."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase_a_resume_status.py"


def load_module():
    spec = importlib.util.spec_from_file_location("phase_a_resume_status", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load phase_a_resume_status")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_phase_a_resume_status_marks_completed_partial_and_pending_sections() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        review_units = root / "review_units.jsonl"
        prose = root / "prose_issues.jsonl"
        paragraphs = root / "paragraph_decisions.jsonl"
        reflections = root / "section_reflections.json"
        out = root / "phase_a_resume_status.json"
        next_out = root / "phase_a_next_step.json"
        write_jsonl(
            review_units,
            [
                {"kind": "section", "section_id": "intro", "text": "Introduction"},
                {
                    "kind": "paragraph",
                    "paragraph_id": "p-intro",
                    "section_id": "intro",
                    "section_title": "Introduction",
                    "sentences": [{"sentence_id": "s1"}],
                },
                {"kind": "section", "section_id": "method", "text": "Method"},
                {
                    "kind": "paragraph",
                    "paragraph_id": "p-method",
                    "section_id": "method",
                    "section_title": "Method",
                    "sentences": [{"sentence_id": "s2"}],
                },
                {"kind": "section", "section_id": "results", "text": "Results"},
                {
                    "kind": "paragraph",
                    "paragraph_id": "p-results",
                    "section_id": "results",
                    "section_title": "Results",
                    "sentences": [{"sentence_id": "s3"}],
                },
            ],
        )
        write_jsonl(prose, [{"local_id": "P1", "section_id": "intro", "title": "Issue"}])
        write_jsonl(
            paragraphs,
            [
                {"paragraph_id": "p-intro", "section_id": "intro", "decision": "revise", "all_sentences_reviewed": True},
                {"paragraph_id": "p-method", "section_id": "method", "decision": "revise"},
            ],
        )
        write_json(reflections, {"sections": [{"section_id": "intro", "one_line": "done"}]})

        payload = module.build_status(
            review_units=review_units,
            prose_issues=prose,
            paragraph_decisions=paragraphs,
            section_reflections=reflections,
        )
        status = module.main(
            [
                "--review-units",
                str(review_units),
                "--prose-issues",
                str(prose),
                "--paragraph-decisions",
                str(paragraphs),
                "--section-reflections",
                str(reflections),
                "--out",
                str(out),
                "--next-out",
                str(next_out),
            ]
        )
        if status != 0:
            raise AssertionError(f"phase_a_resume_status CLI returned {status}")
        written = json.loads(out.read_text(encoding="utf-8"))
        next_step = json.loads(next_out.read_text(encoding="utf-8"))

    if payload["coverage"]["sections_completed"] != 1:
        raise AssertionError(f"Expected one completed section, got {payload['coverage']}")
    if payload["coverage"]["sections_partial"] != 1:
        raise AssertionError(f"Expected one partial section, got {payload['coverage']}")
    if [item["section_id"] for item in payload["pending_sections"]] != ["method", "results"]:
        raise AssertionError(f"Unexpected pending sections: {payload['pending_sections']}")
    if written["context_policy"] != "model_readable_resume_status_only":
        raise AssertionError(f"Missing context policy: {written}")
    if next_step["next_section"]["section_id"] != "method":
        raise AssertionError(f"Expected next pending section to be method, got {next_step}")
    if next_step["phase_a_complete"]:
        raise AssertionError(f"Phase A should not be marked complete: {next_step}")
    if "prose_issues_jsonl" not in next_step["append_targets"]:
        raise AssertionError(f"Next-step packet missing append targets: {next_step}")


def test_phase_a_resume_status_includes_front_matter_in_full_coverage() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        review_units = root / "review_units.jsonl"
        write_jsonl(
            review_units,
            [
                {
                    "kind": "paragraph",
                    "paragraph_id": "p-front",
                    "section_id": "front-matter",
                    "section_title": "Front Matter",
                    "sentences": [{"sentence_id": "s0"}],
                },
                {"kind": "section", "section_id": "intro", "text": "Introduction"},
                {
                    "kind": "paragraph",
                    "paragraph_id": "p-intro",
                    "section_id": "intro",
                    "section_title": "Introduction",
                    "sentences": [{"sentence_id": "s1"}],
                },
            ],
        )
        payload = module.build_status(review_units=review_units)
        next_step = module.build_next_step(payload)

    if payload["coverage"]["sections_total"] != 2 or payload["coverage"]["front_matter_sections"] != 1:
        raise AssertionError(f"Front matter should be counted in full coverage and flagged separately, got {payload['coverage']}")
    if [item["section_id"] for item in payload["pending_sections"]] != ["front-matter", "intro"]:
        raise AssertionError(f"Front matter should remain pending until reviewed: {payload['pending_sections']}")
    if next_step["next_section"]["section_id"] != "front-matter":
        raise AssertionError(f"Next section should include front matter first, got {next_step}")


def test_phase_a_completion_requires_sentence_review_receipts_and_phase_a_roots() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        review_units = root / "review_units.jsonl"
        prose = root / "prose_issues.jsonl"
        paragraphs = root / "paragraph_decisions.jsonl"
        reflections = root / "section_reflections.json"
        cold = root / "cold_skim_frame.json"
        claims = root / "claim_candidates.json"
        write_jsonl(
            review_units,
            [
                {"kind": "section", "section_id": "intro", "text": "Introduction"},
                {
                    "kind": "paragraph",
                    "paragraph_id": "p-intro",
                    "section_id": "intro",
                    "section_title": "Introduction",
                    "sentences": [{"sentence_id": "s1"}, {"sentence_id": "s2"}],
                },
            ],
        )
        write_jsonl(prose, [])
        write_jsonl(paragraphs, [{"paragraph_id": "p-intro", "section_id": "intro", "decision": "keep"}])
        write_json(reflections, {"sections": [{"section_id": "intro", "one_line": "done"}]})
        payload = module.build_status(
            review_units=review_units,
            prose_issues=prose,
            paragraph_decisions=paragraphs,
            section_reflections=reflections,
            cold_skim=cold,
            claim_candidates=claims,
        )
        if payload["coverage"]["sections_completed"] != 0 or payload["coverage"]["phase_a_complete"]:
            raise AssertionError(f"Sentence receipt should be required before completion: {payload['coverage']}")
        write_jsonl(
            paragraphs,
            [
                {
                    "paragraph_id": "p-intro",
                    "section_id": "intro",
                    "decision": "keep",
                    "reviewed_sentence_ids": ["s1", "s2"],
                }
            ],
        )
        write_json(cold, {"problem": "P", "gap": "G"})
        write_json(claims, {"claim_candidates": []})
        payload = module.build_status(
            review_units=review_units,
            prose_issues=prose,
            paragraph_decisions=paragraphs,
            section_reflections=reflections,
            cold_skim=cold,
            claim_candidates=claims,
        )

    if payload["coverage"]["sections_completed"] != 1 or not payload["coverage"]["phase_a_complete"]:
        raise AssertionError(f"Expected full Phase A completion after receipts and roots, got {payload['coverage']}")


if __name__ == "__main__":
    test_phase_a_resume_status_marks_completed_partial_and_pending_sections()
    test_phase_a_resume_status_includes_front_matter_in_full_coverage()
    test_phase_a_completion_requires_sentence_review_receipts_and_phase_a_roots()
    print("phase_a_resume_status regression tests passed")
