#!/usr/bin/env python3
"""Validate Prose Phase A artifacts before compile/audit."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_language_contract import teaching_contract_errors  # noqa: E402


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_jsonl(path: Path, label: str, errors: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        errors.append(f"{label} missing: {path}")
        return rows
    for line_idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{label} line {line_idx} is not valid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"{label} line {line_idx} must be a JSON object")
            continue
        row["_line"] = line_idx
        rows.append(row)
    return rows


def review_unit_index(path: Path, errors: list[str]) -> tuple[dict[str, set[str]], dict[str, str], list[str]]:
    section_paragraphs: dict[str, set[str]] = {}
    paragraph_sections: dict[str, str] = {}
    paragraph_order: list[str] = []
    if not path.exists():
        errors.append(f"review_units missing: {path}")
        return section_paragraphs, paragraph_sections, paragraph_order
    for line_idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"review_units line {line_idx} is not valid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            continue
        paragraph_id = compact_text(row.get("paragraph_id"))
        section_id = compact_text(row.get("section_id"))
        if paragraph_id:
            paragraph_order.append(paragraph_id)
            paragraph_sections[paragraph_id] = section_id
            if section_id:
                section_paragraphs.setdefault(section_id, set()).add(paragraph_id)
    return section_paragraphs, paragraph_sections, paragraph_order


def list_field(row: dict[str, Any], key: str) -> list[str]:
    value = row.get(key)
    if not isinstance(value, list):
        return []
    return [compact_text(item) for item in value if compact_text(item)]


def issue_local_ids(rows: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for idx, row in enumerate(rows, 1):
        local_id = compact_text(row.get("local_id") or row.get("id") or row.get("issue_id") or f"P{idx}")
        ids.add(local_id)
    return ids


def validate(
    *,
    review_units: Path,
    prose_issues: Path,
    paragraph_decisions: Path,
    section_reflections: Path,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    section_paragraphs, paragraph_sections, paragraph_order = review_unit_index(review_units, errors)
    issue_rows = read_jsonl(prose_issues, "prose_issues.jsonl", errors)
    decision_rows = read_jsonl(paragraph_decisions, "paragraph_decisions.jsonl", errors)
    try:
        reflections_payload = load_json(section_reflections)
    except Exception as exc:
        errors.append(f"section_reflections.json could not be read: {exc}")
        reflections_payload = {}
    reflections = reflections_payload.get("sections") if isinstance(reflections_payload, dict) else None
    if not isinstance(reflections, list):
        errors.append("section_reflections.json must contain a `sections` list")
        reflections = []

    known_issues = issue_local_ids(issue_rows)
    seen_paragraphs: set[str] = set()
    decision_order: list[str] = []
    for row in decision_rows:
        line = row.get("_line", "?")
        paragraph_id = compact_text(row.get("paragraph_id"))
        section_id = compact_text(row.get("section_id"))
        if not paragraph_id:
            errors.append(f"paragraph_decisions.jsonl line {line} missing `paragraph_id`")
            continue
        if paragraph_id not in paragraph_sections:
            errors.append(f"paragraph_decisions.jsonl line {line} references unknown paragraph_id `{paragraph_id}`")
        elif section_id and paragraph_sections[paragraph_id] and section_id != paragraph_sections[paragraph_id]:
            errors.append(f"paragraph_decisions.jsonl line {line} section_id `{section_id}` does not match review_units section `{paragraph_sections[paragraph_id]}`")
        if paragraph_id in seen_paragraphs:
            errors.append(f"paragraph_decisions.jsonl has duplicate paragraph_id `{paragraph_id}`")
        seen_paragraphs.add(paragraph_id)
        decision_order.append(paragraph_id)
        if not compact_text(row.get("decision")):
            errors.append(f"paragraph_decisions.jsonl line {line} missing `decision`")
        if not compact_text(row.get("paragraph_job")):
            errors.append(f"paragraph_decisions.jsonl line {line} missing `paragraph_job`")
        if not compact_text(row.get("next_draft_task")):
            errors.append(f"paragraph_decisions.jsonl line {line} missing `next_draft_task`")
        has_sentence_receipt = bool(
            row.get("all_sentences_reviewed") is True
            or list_field(row, "reviewed_sentence_ids")
            or isinstance(row.get("sentence_checks"), list)
        )
        if not has_sentence_receipt:
            errors.append(f"paragraph_decisions.jsonl line {line} missing sentence review receipt")
        for linked in list_field(row, "linked_issue_ids") + list_field(row, "top_issue_ids"):
            if linked not in known_issues:
                errors.append(f"paragraph_decisions.jsonl line {line} links unknown prose issue `{linked}`")

    order_index = {paragraph_id: idx for idx, paragraph_id in enumerate(paragraph_order)}
    ordered_indices = [order_index[item] for item in decision_order if item in order_index]
    if ordered_indices != sorted(ordered_indices):
        errors.append("paragraph_decisions.jsonl is not in review_units paragraph order; full-paper traversal is not monotonic")

    for row in issue_rows:
        line = row.get("_line", "?")
        local_id = compact_text(row.get("local_id") or row.get("id") or row.get("issue_id"))
        for field in ("severity", "issue_type", "title", "diagnosis", "section_id"):
            if not compact_text(row.get(field)):
                errors.append(f"prose_issues.jsonl line {line} {local_id or '<missing id>'}: missing `{field}`")
        errors.extend(
            teaching_contract_errors(
                row,
                prefix=f"prose_issues.jsonl line {line} {local_id or '<missing id>'}",
                domain="prose",
            )
        )
        anchors = list_field(row, "target_anchors") or list_field(row, "anchors")
        fallback_anchor = compact_text(row.get("primary_anchor") or row.get("anchor") or row.get("sentence_id") or row.get("paragraph_id"))
        if not anchors and not fallback_anchor:
            errors.append(f"prose_issues.jsonl line {line} {local_id or '<missing id>'}: missing anchor/target_anchors")
        paragraph_id = compact_text(row.get("paragraph_id"))
        if paragraph_id and paragraph_id not in seen_paragraphs:
            errors.append(f"prose_issues.jsonl line {line} {local_id or '<missing id>'}: paragraph_id `{paragraph_id}` has no paragraph decision receipt")

    reflected_sections: set[str] = set()
    for idx, row in enumerate(reflections, 1):
        if not isinstance(row, dict):
            errors.append(f"section_reflections.json section #{idx} must be an object")
            continue
        section_id = compact_text(row.get("section_id"))
        if not section_id:
            errors.append(f"section_reflections.json section #{idx} missing `section_id`")
            continue
        reflected_sections.add(section_id)
        for field in ("one_line", "role_in_argument", "unresolved_questions"):
            if field not in row:
                errors.append(f"section_reflections.json section `{section_id}` missing `{field}`")
        for linked in list_field(row, "top_issue_ids"):
            if linked not in known_issues:
                errors.append(f"section_reflections.json section `{section_id}` links unknown prose issue `{linked}`")

    missing_paragraphs = sorted(set(paragraph_sections) - seen_paragraphs)
    if missing_paragraphs:
        errors.append(f"paragraph_decisions.jsonl missing {len(missing_paragraphs)} paragraph(s): {', '.join(missing_paragraphs[:8])}")
    missing_sections = sorted(set(section_paragraphs) - reflected_sections)
    if missing_sections:
        errors.append(f"section_reflections.json missing {len(missing_sections)} section(s): {', '.join(missing_sections[:8])}")
    if not issue_rows:
        warnings.append("prose_issues.jsonl has no rows; this is valid only if paragraph decisions certify clean coverage")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-units", required=True, type=Path)
    parser.add_argument("--prose-issues", required=True, type=Path)
    parser.add_argument("--paragraph-decisions", required=True, type=Path)
    parser.add_argument("--section-reflections", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    errors, warnings = validate(
        review_units=args.review_units,
        prose_issues=args.prose_issues,
        paragraph_decisions=args.paragraph_decisions,
        section_reflections=args.section_reflections,
    )
    payload = {
        "schema_version": 1,
        "generated_by": "validate_prose_artifacts.py",
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
