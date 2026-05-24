#!/usr/bin/env python3
"""Build compact prompt packets for Ariadne Prose Phase A or Phase B."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CONTEXT_POLICY = "model_readable_prose_phase_packet"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def compact_text(value: Any, *, max_chars: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def source_record(path: Path | None, *, context_policy: str | None = None) -> dict[str, str] | None:
    if path is None or not path.exists():
        return None
    record = {"path": str(path), "hash": sha256_path(path)}
    if context_policy:
        record["context_policy"] = context_policy
    return record


def count_jsonl_rows(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def file_target(path: Path | None, *, mode: str, required: bool) -> dict[str, Any]:
    return {
        "path": str(path) if path else "",
        "mode": mode,
        "required": required,
        "exists": bool(path and path.exists()),
        "rows": count_jsonl_rows(path) if path and path.suffix == ".jsonl" else None,
    }


def section_packet(next_step: dict[str, Any]) -> dict[str, Any] | None:
    next_section = next_step.get("next_section") if isinstance(next_step, dict) else None
    if not isinstance(next_section, dict):
        return None
    return {
        "section_id": next_section.get("section_id"),
        "title": next_section.get("title"),
        "order": next_section.get("order"),
        "paragraphs": next_section.get("paragraphs"),
        "sentences": next_section.get("sentences"),
        "resume_flags": {
            "has_paragraph_decisions": next_section.get("has_paragraph_decisions"),
            "has_section_reflection": next_section.get("has_section_reflection"),
        },
    }


def build_phase_a_packet(
    *,
    review_units_md: Path,
    review_units_jsonl: Path,
    resume_status: Path | None,
    next_step_path: Path | None,
    prose_issues: Path,
    paragraph_decisions: Path,
    section_reflections: Path,
    cold_skim: Path,
    claim_candidates: Path,
) -> dict[str, Any]:
    status_payload = load_json(resume_status)
    next_step = load_json(next_step_path)
    if not isinstance(status_payload, dict):
        status_payload = {}
    if not isinstance(next_step, dict):
        next_step = {}
    coverage = status_payload.get("coverage") if isinstance(status_payload.get("coverage"), dict) else {}
    next_section = section_packet(next_step)
    return {
        "schema_version": SCHEMA_VERSION,
        "context_policy": CONTEXT_POLICY,
        "generated_by": "scripts/build_prose_phase_packet.py",
        "phase": "phase_a",
        "objective": "Run Ariadne Prose Phase A: cold skim, linear sentence/paragraph deep read, and section reflection.",
        "read_inputs": [
            source_record(review_units_md, context_policy="model_readable_full_prose_input"),
            source_record(review_units_jsonl, context_policy="model_readable_anchor_index"),
            source_record(resume_status, context_policy="model_readable_resume_status_only"),
            source_record(next_step_path, context_policy="model_readable_resume_status_only"),
        ],
        "next_section": next_section,
        "coverage": {
            "sections_total": coverage.get("sections_total", 0),
            "sections_completed": coverage.get("sections_completed", 0),
            "sections_partial": coverage.get("sections_partial", 0),
            "sections_pending": coverage.get("sections_pending", 0),
        },
        "write_targets": {
            "cold_skim_frame": file_target(cold_skim, mode="create_once_or_update_before_section_work", required=True),
            "prose_issues": file_target(prose_issues, mode="append_jsonl_by_section", required=True),
            "paragraph_decisions": file_target(paragraph_decisions, mode="append_jsonl_by_section", required=True),
            "section_reflections": file_target(section_reflections, mode="update_json_after_each_section", required=True),
            "claim_candidates": file_target(claim_candidates, mode="create_or_update_json", required=True),
        },
        "output_contract": {
            "prose_issues_jsonl": {
                "minimum_fields": ["local_id", "severity", "issue_type", "title", "diagnosis", "target_anchors", "section_id"],
                "cross_section_fields": ["target_anchors", "spans_sections", "related_issue_ids"],
            },
            "paragraph_decisions_jsonl": {
                "minimum_fields": ["paragraph_id", "section_id", "decision", "paragraph_job", "next_draft_task"],
            },
            "section_reflections_json": {
                "minimum_fields": ["section_id", "one_line", "role_in_argument", "top_issue_ids", "unresolved_questions"],
            },
        },
        "instructions": [
            "Read the full review_units Markdown for whole-paper continuity, but continue detailed work only from next_section when resuming.",
            "Do not write HTML. Write JSON/JSONL artifacts only.",
            "After each section, append prose issue and paragraph decision rows, then update section_reflections.json before continuing.",
            "If next_section is null, Phase A is complete; build phase_b_context next.",
        ],
    }


def build_phase_b_packet(
    *,
    phase_b_context: Path,
    argument_map: Path,
    claims: Path,
    salvageable_core: Path,
    whole_paper_findings: Path,
) -> dict[str, Any]:
    context_payload = load_json(phase_b_context)
    coverage = context_payload.get("coverage") if isinstance(context_payload, dict) and isinstance(context_payload.get("coverage"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "context_policy": CONTEXT_POLICY,
        "generated_by": "scripts/build_prose_phase_packet.py",
        "phase": "phase_b",
        "objective": "Run Ariadne Prose Phase B: whole-paper argument red-team and cross-domain integration.",
        "read_inputs": [source_record(phase_b_context, context_policy="model_readable_compact_synthesis_input")],
        "coverage": {
            "sections_summarized": coverage.get("sections_summarized", 0),
            "specialist_domains": coverage.get("specialist_domains", 0),
            "issue_count": coverage.get("issue_count", 0),
        },
        "write_targets": {
            "argument_map": file_target(argument_map, mode="create_or_update_json", required=True),
            "claims": file_target(claims, mode="create_or_update_json", required=True),
            "salvageable_core": file_target(salvageable_core, mode="create_or_update_json", required=True),
            "whole_paper_findings": file_target(whole_paper_findings, mode="append_or_create_jsonl", required=True),
        },
        "output_contract": {
            "whole_paper_findings_jsonl": {
                "minimum_fields": ["local_id", "severity", "issue_type", "title", "diagnosis", "source_issue_ids"],
                "integration_fields": ["related_issue_ids", "claim_ids", "specialist_domains"],
            },
            "claims_json": {
                "minimum_fields": ["claims"],
                "claim_fields": ["id", "text", "status", "evidence", "linked_finding_ids"],
            },
        },
        "instructions": [
            "Read phase_b_context.json only; do not reread full review_units or raw specialist audits.",
            "Integrate specialist issues only when they affect claim strength, reader trust, or acceptance risk.",
            "Keep lower-level issues separate unless a whole-paper finding truly absorbs them; preserve source_issue_ids.",
            "Do not write HTML. Write JSON/JSONL artifacts only.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("phase_a", "phase_b"))
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--review-units-md", type=Path)
    parser.add_argument("--review-units-jsonl", type=Path)
    parser.add_argument("--phase-b-context", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    bundle = args.bundle.expanduser().resolve()
    if args.phase == "phase_a":
        if not args.review_units_md or not args.review_units_jsonl:
            parser.error("--review-units-md and --review-units-jsonl are required for phase_a")
        packet = build_phase_a_packet(
            review_units_md=args.review_units_md.expanduser().resolve(),
            review_units_jsonl=args.review_units_jsonl.expanduser().resolve(),
            resume_status=bundle / "phase_a_resume_status.json",
            next_step_path=bundle / "phase_a_next_step.json",
            prose_issues=bundle / "issue_artifacts" / "prose_issues.jsonl",
            paragraph_decisions=bundle / "paragraph_decisions.jsonl",
            section_reflections=bundle / "section_reflections.json",
            cold_skim=bundle / "cold_skim_frame.json",
            claim_candidates=bundle / "claim_candidates.json",
        )
    else:
        phase_b_context = (args.phase_b_context or bundle / "phase_b_context.json").expanduser().resolve()
        packet = build_phase_b_packet(
            phase_b_context=phase_b_context,
            argument_map=bundle / "argument_map.json",
            claims=bundle / "claims.json",
            salvageable_core=bundle / "salvageable_core.json",
            whole_paper_findings=bundle / "issue_artifacts" / "whole_paper_findings.jsonl",
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.phase} prose packet: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
