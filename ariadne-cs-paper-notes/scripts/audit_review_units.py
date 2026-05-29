#!/usr/bin/env python3
"""Audit source-derived Ariadne review units."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {line_no} is not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}: line {line_no} must be an object")
        rows.append(row)
    return rows


def sentence_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sentences: list[dict[str, Any]] = []
    for row in rows:
        if row.get("kind") != "paragraph":
            continue
        for sentence in row.get("sentences", []):
            if isinstance(sentence, dict):
                sentences.append(sentence)
    return sentences


def audit_review_units(
    path: Path,
    *,
    previous: Path | None = None,
    regression_ratio: float = 0.05,
    require_source_spans: bool = True,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    rows = read_jsonl(path)
    sections = [row for row in rows if row.get("kind") == "section"]
    paragraphs = [row for row in rows if row.get("kind") == "paragraph"]
    sentences = sentence_rows(rows)
    ids: set[str] = set()
    unit_counts: Counter[str] = Counter()
    caption_labels: dict[str, str] = {}

    if not sections:
        errors.append("review_units contains no section rows")
    if not paragraphs:
        errors.append("review_units contains no paragraph rows")
    if not sentences:
        errors.append("review_units contains no sentence rows")

    for row in sections:
        if not row.get("section_id"):
            errors.append("section row missing section_id")
        if not row.get("text"):
            errors.append(f"section {row.get('section_id') or '<missing>'} missing text")

    for row in paragraphs:
        paragraph_id = str(row.get("paragraph_id") or "")
        if not paragraph_id:
            errors.append("paragraph row missing paragraph_id")
        if not row.get("section_id"):
            errors.append(f"paragraph {paragraph_id or '<missing>'} missing section_id")
        if not isinstance(row.get("sentences"), list) or not row.get("sentences"):
            errors.append(f"paragraph {paragraph_id or '<missing>'} has no sentences")
        if row.get("unit_kind") == "caption":
            label = str(row.get("label") or "")
            if label:
                previous_paragraph_id = caption_labels.get(label)
                if previous_paragraph_id and previous_paragraph_id != paragraph_id:
                    errors.append(f"duplicate caption label `{label}`")
                caption_labels[label] = paragraph_id

    for sentence in sentences:
        sentence_id = str(sentence.get("sentence_id") or "")
        unit_kind = str(sentence.get("unit_kind") or "prose")
        unit_counts[unit_kind] += 1
        if not sentence_id:
            errors.append("sentence row missing sentence_id")
        elif sentence_id in ids:
            errors.append(f"duplicate sentence_id `{sentence_id}`")
        ids.add(sentence_id)
        for field in ("text",):
            if sentence.get(field) in {None, ""}:
                errors.append(f"sentence {sentence_id or '<missing>'} missing `{field}`")
        for field in ("rendered_text_initial", "source_file", "line_start", "line_end", "text_hash"):
            if sentence.get(field) in {None, ""}:
                message = f"sentence {sentence_id or '<missing>'} missing `{field}`"
                if require_source_spans:
                    errors.append(message)
                else:
                    warnings.append(message)
        if sentence.get("line_start") not in {None, ""} or sentence.get("line_end") not in {None, ""}:
            try:
                raw_start = sentence.get("line_start")
                raw_end = sentence.get("line_end")
                line_start = int(str(raw_start).split(":", 1)[1] if str(raw_start).startswith("page:") else raw_start)
                line_end = int(str(raw_end).split(":", 1)[1] if str(raw_end).startswith("page:") else raw_end)
                if line_start <= 0 or line_end < line_start:
                    errors.append(f"sentence {sentence_id} has invalid line range {line_start}..{line_end}")
            except (TypeError, ValueError):
                errors.append(f"sentence {sentence_id or '<missing>'} line range is not numeric")
        if unit_kind == "caption":
            if not sentence.get("float_kind"):
                warnings.append(f"caption sentence {sentence_id} missing float_kind")

    if previous and previous.exists():
        old_count = len(sentence_rows(read_jsonl(previous)))
        new_count = len(sentences)
        if old_count and new_count < old_count * (1 - regression_ratio):
            warnings.append(
                f"sentence count dropped from {old_count} to {new_count} "
                f"({regression_ratio:.0%} regression threshold)"
            )

    summary = {
        "review_units": str(path),
        "sections": len(sections),
        "paragraphs": len(paragraphs),
        "sentences": len(sentences),
        "unit_kind_counts": dict(unit_counts),
        "caption_labels": len(caption_labels),
        "errors": len(errors),
        "warnings": len(warnings),
    }
    return errors, warnings, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_units", type=Path)
    parser.add_argument("--previous", type=Path, help="Previous review_units snapshot for sentence-count regression warning")
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--regression-ratio", type=float, default=0.05)
    parser.add_argument("--allow-missing-source-spans", action="store_true", help="Warn instead of failing when legacy HTML-derived units lack source spans")
    args = parser.parse_args(argv)

    errors, warnings, summary = audit_review_units(
        args.review_units.expanduser().resolve(),
        previous=args.previous.expanduser().resolve() if args.previous else None,
        regression_ratio=args.regression_ratio,
        require_source_spans=not args.allow_missing_source_spans,
    )
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(
        "Review units audit passed: "
        f"sections={summary['sections']} paragraphs={summary['paragraphs']} "
        f"sentences={summary['sentences']} unit_kinds={summary['unit_kind_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
