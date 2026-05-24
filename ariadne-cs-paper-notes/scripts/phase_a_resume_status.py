#!/usr/bin/env python3
"""Build a compact resumability status for Prose Phase A section-by-section review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def compact_text(value: Any, *, max_chars: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {line_no} is not valid JSON: {exc}") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def as_list(payload: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        keyed = []
        for key, value in payload.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("section_id", key)
                keyed.append(row)
        return keyed
    return []


def section_sequence(review_units_path: Path) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in read_jsonl(review_units_path):
        if row.get("kind") == "section":
            section_id = compact_text(row.get("section_id") or row.get("id"))
            if section_id and section_id not in seen:
                sections.append(
                    {
                        "section_id": section_id,
                        "title": compact_text(row.get("text") or row.get("title") or section_id),
                        "paragraphs": 0,
                        "sentences": 0,
                    }
                )
                seen.add(section_id)
            continue
        if row.get("kind") == "paragraph":
            section_id = compact_text(row.get("section_id") or "front-matter")
            if section_id not in seen:
                sections.append(
                    {
                        "section_id": section_id,
                        "title": compact_text(row.get("section_title") or section_id),
                        "paragraphs": 0,
                        "sentences": 0,
                    }
                )
                seen.add(section_id)
            target = next(item for item in sections if item["section_id"] == section_id)
            target["paragraphs"] += 1
            sentences = row.get("sentences")
            target["sentences"] += len(sentences) if isinstance(sentences, list) else 0
    return sections


def section_ids_from_rows(rows: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        for key in ("section_id", "target_section", "section", "anchor_section"):
            value = compact_text(row.get(key), max_chars=120)
            if value:
                ids.add(value)
    return ids


def section_reflection_ids(payload: Any) -> set[str]:
    ids: set[str] = set()
    for row in as_list(payload, ("sections", "section_reflections", "reflections")):
        if not isinstance(row, dict):
            continue
        value = compact_text(row.get("section_id") or row.get("id") or row.get("section"), max_chars=120)
        if value:
            ids.add(value)
    return ids


def source_record(path: Path | None) -> dict[str, str] | None:
    if path is None or not path.exists():
        return None
    return {"path": str(path), "hash": sha256_path(path)}


def build_status(
    *,
    review_units: Path,
    prose_issues: Path | None = None,
    paragraph_decisions: Path | None = None,
    section_reflections: Path | None = None,
    cold_skim: Path | None = None,
    claim_candidates: Path | None = None,
) -> dict[str, Any]:
    sections = section_sequence(review_units)
    front_matter_sections = [section for section in sections if section.get("section_id") in {"front-matter", "front_matter"}]
    review_sections = [section for section in sections if section not in front_matter_sections]
    issue_ids = section_ids_from_rows(read_jsonl(prose_issues))
    paragraph_ids = section_ids_from_rows(read_jsonl(paragraph_decisions))
    reflection_ids = section_reflection_ids(load_json(section_reflections))
    completed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    front_matter: list[dict[str, Any]] = []
    for index, section in enumerate(front_matter_sections, 1):
        section_id = section["section_id"]
        row = {
            **section,
            "order": index,
            "has_prose_issues": section_id in issue_ids or section["sentences"] == 0,
            "has_paragraph_decisions": section_id in paragraph_ids or section["paragraphs"] == 0,
            "has_section_reflection": section_id in reflection_ids,
            "status": "front_matter",
        }
        front_matter.append(row)
    for index, section in enumerate(review_sections, 1):
        section_id = section["section_id"]
        has_reflection = section_id in reflection_ids
        has_paragraphs = section_id in paragraph_ids or section["paragraphs"] == 0
        has_issues = section_id in issue_ids or section["sentences"] == 0
        row = {
            **section,
            "order": index,
            "has_prose_issues": has_issues,
            "has_paragraph_decisions": has_paragraphs,
            "has_section_reflection": has_reflection,
        }
        if has_reflection and has_paragraphs:
            completed.append(row)
        elif has_reflection or has_paragraphs or has_issues:
            partial.append(row)
            pending.append(row)
        else:
            pending.append(row)
    source_artifacts = [
        item
        for item in (
            source_record(review_units),
            source_record(prose_issues),
            source_record(paragraph_decisions),
            source_record(section_reflections),
            source_record(cold_skim),
            source_record(claim_candidates),
        )
        if item
    ]
    return {
        "schema_version": 1,
        "context_policy": "model_readable_resume_status_only",
        "generated_by": "scripts/phase_a_resume_status.py",
        "source_artifacts": source_artifacts,
        "coverage": {
            "sections_total": len(review_sections),
            "sections_completed": len(completed),
            "sections_partial": len(partial),
            "sections_pending": len(pending),
            "front_matter_sections": len(front_matter),
            "front_matter_paragraphs": sum(int(item.get("paragraphs", 0) or 0) for item in front_matter),
            "front_matter_sentences": sum(int(item.get("sentences", 0) or 0) for item in front_matter),
            "cold_skim_present": bool(cold_skim and cold_skim.exists()),
            "claim_candidates_present": bool(claim_candidates and claim_candidates.exists()),
        },
        "front_matter": front_matter,
        "completed_sections": completed,
        "partial_sections": partial,
        "pending_sections": pending,
        "resume_instruction": (
            "Ask the Prose Review Agent to continue Phase A only from the first pending section id. "
            "Do not reread completed section artifacts into orchestrator context."
        ),
    }


def build_next_step(
    status_payload: dict[str, Any],
    *,
    prose_issues: Path | None = None,
    paragraph_decisions: Path | None = None,
    section_reflections: Path | None = None,
    cold_skim: Path | None = None,
    claim_candidates: Path | None = None,
    max_pending: int = 20,
) -> dict[str, Any]:
    pending_sections = status_payload.get("pending_sections")
    if not isinstance(pending_sections, list):
        pending_sections = []
    compact_pending = []
    for row in pending_sections[:max_pending]:
        if not isinstance(row, dict):
            continue
        compact_pending.append(
            {
                "section_id": row.get("section_id"),
                "title": row.get("title"),
                "order": row.get("order"),
                "paragraphs": row.get("paragraphs"),
                "sentences": row.get("sentences"),
                "has_paragraph_decisions": row.get("has_paragraph_decisions"),
                "has_section_reflection": row.get("has_section_reflection"),
            }
        )
    next_section = compact_pending[0] if compact_pending else None
    append_targets = {
        "prose_issues_jsonl": str(prose_issues) if prose_issues else "",
        "paragraph_decisions_jsonl": str(paragraph_decisions) if paragraph_decisions else "",
        "section_reflections_json": str(section_reflections) if section_reflections else "",
        "cold_skim_frame_json": str(cold_skim) if cold_skim else "",
        "claim_candidates_json": str(claim_candidates) if claim_candidates else "",
    }
    return {
        "schema_version": 1,
        "context_policy": "model_readable_resume_status_only",
        "generated_by": "scripts/phase_a_resume_status.py",
        "phase": "prose_phase_a",
        "phase_a_complete": next_section is None,
        "next_section": next_section,
        "pending_sections_compact": compact_pending,
        "pending_sections_omitted": max(0, len(pending_sections) - len(compact_pending)),
        "append_targets": append_targets,
        "instructions": [
            "Continue Prose Phase A from next_section only.",
            "After finishing the section, append prose issues and paragraph decisions, then update section_reflections.json before moving on.",
            "Do not reread completed Phase A JSONL shards into orchestration context; rerun phase_a_resume_status.py to refresh this packet.",
            "If next_section is null, Phase A is complete and Phase B compaction may proceed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-units", required=True, type=Path)
    parser.add_argument("--prose-issues", type=Path)
    parser.add_argument("--paragraph-decisions", type=Path)
    parser.add_argument("--section-reflections", type=Path)
    parser.add_argument("--cold-skim", type=Path)
    parser.add_argument("--claim-candidates", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--next-out", type=Path, help="Optional compact next-step packet for the orchestrator")
    parser.add_argument("--max-pending", type=int, default=20, help="Maximum pending sections to include in --next-out")
    args = parser.parse_args(argv)

    payload = build_status(
        review_units=args.review_units,
        prose_issues=args.prose_issues,
        paragraph_decisions=args.paragraph_decisions,
        section_reflections=args.section_reflections,
        cold_skim=args.cold_skim,
        claim_candidates=args.claim_candidates,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.next_out:
        next_step = build_next_step(
            payload,
            prose_issues=args.prose_issues,
            paragraph_decisions=args.paragraph_decisions,
            section_reflections=args.section_reflections,
            cold_skim=args.cold_skim,
            claim_candidates=args.claim_candidates,
            max_pending=args.max_pending,
        )
        args.next_out.parent.mkdir(parents=True, exist_ok=True)
        args.next_out.write_text(json.dumps(next_step, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    coverage = payload["coverage"]
    print(
        "Wrote Phase A resume status: "
        f"completed={coverage['sections_completed']} pending={coverage['sections_pending']} to {args.out}"
    )
    if args.next_out:
        next_id = (next_step.get("next_section") or {}).get("section_id") if isinstance(next_step, dict) else None
        print(f"Wrote Phase A next-step packet: next={next_id or 'complete'} to {args.next_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
