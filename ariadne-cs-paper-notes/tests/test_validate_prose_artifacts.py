#!/usr/bin/env python3
"""Regression tests for Prose Phase A artifact validation."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_prose_artifacts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("validate_prose_artifacts", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load validate_prose_artifacts")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_validator_accepts_complete_phase_a_artifacts() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        review_units = root / "review_units.jsonl"
        prose = root / "issue_artifacts" / "prose_issues.jsonl"
        decisions = root / "paragraph_decisions.jsonl"
        reflections = root / "section_reflections.json"
        write_jsonl(
            review_units,
            [
                {"kind": "paragraph", "paragraph_id": "p1", "section_id": "intro"},
                {"kind": "paragraph", "paragraph_id": "p2", "section_id": "method"},
            ],
        )
        write_jsonl(
            prose,
            [
                {
                    "local_id": "P1",
                    "severity": "Major",
                    "issue_type": "prose",
                    "title": "开头主张缺少证据边界",
                    "diagnosis": "这个句子过早给出宽泛主张，但没有说明它由哪些设置和证据支撑。",
                    "reader_friction": "读者还不知道 claim 的适用范围，就被要求先相信一个较强结论。",
                    "writing_principle": "文字精确性先于 flow",
                    "self_check": "下一稿能否在这个位置写清对象、范围和证据边界？",
                    "confidence": "high",
                    "evidence_refs": [{"source_artifact": "review_units.jsonl", "anchor": "p1"}],
                    "severity_rationale": "该问题影响读者判断第一段 claim 的可信度。",
                    "downgrade_condition": "补齐范围和证据边界后可降级。",
                    "section_id": "intro",
                    "paragraph_id": "p1",
                    "target_anchors": ["p1"],
                }
            ],
        )
        write_jsonl(
            decisions,
            [
                {
                    "paragraph_id": "p1",
                    "section_id": "intro",
                    "decision": "revise",
                    "paragraph_job": "setup",
                    "next_draft_task": "补齐主张的范围和证据边界。",
                    "all_sentences_reviewed": True,
                    "linked_issue_ids": ["P1"],
                },
                {
                    "paragraph_id": "p2",
                    "section_id": "method",
                    "decision": "keep",
                    "paragraph_job": "method",
                    "next_draft_task": "None.",
                    "all_sentences_reviewed": True,
                },
            ],
        )
        reflections.write_text(
            json.dumps(
                {
                    "sections": [
                        {"section_id": "intro", "one_line": "Intro.", "role_in_argument": "setup", "unresolved_questions": [], "top_issue_ids": ["P1"]},
                        {"section_id": "method", "one_line": "Method.", "role_in_argument": "method", "unresolved_questions": [], "top_issue_ids": []},
                    ]
                }
            ),
            encoding="utf-8",
        )
        errors, warnings = module.validate(
            review_units=review_units,
            prose_issues=prose,
            paragraph_decisions=decisions,
            section_reflections=reflections,
        )
    if errors or warnings:
        raise AssertionError(f"Expected complete artifacts to pass, errors={errors}, warnings={warnings}")


def test_validator_rejects_backfill_style_artifacts() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        review_units = root / "review_units.jsonl"
        prose = root / "issue_artifacts" / "prose_issues.jsonl"
        decisions = root / "paragraph_decisions.jsonl"
        reflections = root / "section_reflections.json"
        write_jsonl(
            review_units,
            [
                {"kind": "paragraph", "paragraph_id": "p1", "section_id": "intro"},
                {"kind": "paragraph", "paragraph_id": "p2", "section_id": "intro"},
            ],
        )
        write_jsonl(prose, [{"local_id": "P1", "section_id": "intro"}])
        write_jsonl(decisions, [{"paragraph_id": "p2", "section_id": "intro"}])
        reflections.write_text(json.dumps({"sections": [{"section_id": "intro"}]}), encoding="utf-8")
        errors, _warnings = module.validate(
            review_units=review_units,
            prose_issues=prose,
            paragraph_decisions=decisions,
            section_reflections=reflections,
        )
    expected = ("missing sentence review receipt", "missing anchor", "missing 1 paragraph")
    if not all(any(item in error for error in errors) for item in expected):
        raise AssertionError(f"Expected validator errors {expected}, got {errors}")


def test_validator_rejects_visible_english_prose_issue() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        review_units = root / "review_units.jsonl"
        prose = root / "issue_artifacts" / "prose_issues.jsonl"
        decisions = root / "paragraph_decisions.jsonl"
        reflections = root / "section_reflections.json"
        write_jsonl(review_units, [{"kind": "paragraph", "paragraph_id": "p1", "section_id": "intro"}])
        write_jsonl(
            prose,
            [
                {
                    "local_id": "P1",
                    "severity": "Major",
                    "issue_type": "prose",
                    "title": "Opening overclaims",
                    "diagnosis": "The sentence overclaims without a boundary.",
                    "reader_friction": "The reader cannot recover the evidence boundary.",
                    "writing_principle": "reader-first prose",
                    "self_check": "Can the next draft clarify the boundary?",
                    "confidence": "high",
                    "evidence_refs": [{"source_artifact": "review_units.jsonl", "anchor": "p1"}],
                    "severity_rationale": "Major issue.",
                    "downgrade_condition": "Boundary added.",
                    "section_id": "intro",
                    "paragraph_id": "p1",
                    "target_anchors": ["p1"],
                }
            ],
        )
        write_jsonl(
            decisions,
            [
                {
                    "paragraph_id": "p1",
                    "section_id": "intro",
                    "decision": "revise",
                    "paragraph_job": "setup",
                    "next_draft_task": "补边界。",
                    "all_sentences_reviewed": True,
                    "linked_issue_ids": ["P1"],
                }
            ],
        )
        reflections.write_text(
            json.dumps({"sections": [{"section_id": "intro", "one_line": "Intro.", "role_in_argument": "setup", "unresolved_questions": [], "top_issue_ids": ["P1"]}]}),
            encoding="utf-8",
        )
        errors, _warnings = module.validate(
            review_units=review_units,
            prose_issues=prose,
            paragraph_decisions=decisions,
            section_reflections=reflections,
        )
    if not any("Chinese" in error or "closed Ariadne principle" in error for error in errors):
        raise AssertionError(f"Expected Chinese/principle contract errors, got {errors}")


def main() -> int:
    test_validator_accepts_complete_phase_a_artifacts()
    test_validator_rejects_backfill_style_artifacts()
    test_validator_rejects_visible_english_prose_issue()
    print("validate_prose_artifacts regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
