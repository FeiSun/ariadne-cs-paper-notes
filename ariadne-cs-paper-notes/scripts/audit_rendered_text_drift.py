#!/usr/bin/env python3
"""Audit drift between initial review-unit rendering and PDF-extracted text."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.replace("∼", "~").replace("−", "-")
    text = re.sub(r"\\(?:textbf|textit|emph|texttt|mathrm|mathbf|mathit)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?", "", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def normalize_for_drift(value: Any) -> str:
    text = normalize(value)
    text = re.sub(r"\[[^\]]*\]", " [citation] ", text)
    text = re.sub(r"\([a-z][^()]*\b(?:19|20)\d{2}[a-z]?[^()]*\)", " [citation] ", text)
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\b(\d+)\s*,\s*(\d{3})\b", r"\1,\2", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact(value: Any, *, max_chars: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def math_heavy(value: Any) -> bool:
    text = str(value or "")
    return bool(
        "$" in text
        or "\\(" in text
        or "\\[" in text
        or "\\begin{equation" in text
        or re.search(r"\\(?:eqref|frac|sum|prod|int|alpha|beta|gamma|theta|lambda|sim|approx|leq|geq|cdot|times)\b", text)
    )


def sentence_units(review_units: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(review_units):
        if row.get("kind") != "paragraph":
            continue
        for sentence in row.get("sentences", []):
            if isinstance(sentence, dict) and sentence.get("sentence_id"):
                index[str(sentence["sentence_id"])] = sentence
    return index


def audit_drift(
    *,
    review_units: Path,
    review_units_pdf_text: Path,
    warn_threshold: float,
    error_threshold: float,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    units = sentence_units(review_units)
    payload = load_json(review_units_pdf_text)
    anchors = payload.get("anchors") if isinstance(payload, dict) and isinstance(payload.get("anchors"), dict) else {}
    checked = 0
    skipped = 0
    warnings_count = 0
    errors_count = 0
    worst: list[dict[str, Any]] = []
    for unit_id, unit in units.items():
        anchor = anchors.get(unit_id) if isinstance(anchors, dict) else None
        if not isinstance(anchor, dict) or anchor.get("unmappable"):
            skipped += 1
            continue
        initial = normalize_for_drift(unit.get("rendered_text_initial") or unit.get("text"))
        pdf_text = normalize_for_drift(anchor.get("rendered_text_pdf"))
        if not initial or not pdf_text:
            skipped += 1
            continue
        checked += 1
        if initial in pdf_text or pdf_text in initial:
            ratio = 1.0
        else:
            ratio = SequenceMatcher(None, initial, pdf_text).ratio()
        anchor_ratio = float(anchor.get("match_ratio") or 0)
        downgrade_math_error = math_heavy(unit.get("text") or unit.get("rendered_text_initial")) and anchor_ratio >= 0.80
        if ratio < error_threshold and not downgrade_math_error:
            errors_count += 1
            errors.append(f"{unit_id} rendered text drift ratio {ratio:.3f} below error threshold {error_threshold:.2f}")
        elif ratio < warn_threshold:
            warnings_count += 1
            if downgrade_math_error:
                warnings.append(
                    f"{unit_id} math-heavy rendered text drift ratio {ratio:.3f} below error threshold "
                    f"{error_threshold:.2f}, but bbox match ratio is {anchor_ratio:.3f}"
                )
            else:
                warnings.append(f"{unit_id} rendered text drift ratio {ratio:.3f} below warning threshold {warn_threshold:.2f}")
        worst.append(
            {
                "unit_id": unit_id,
                "ratio": round(ratio, 3),
                "initial": compact(unit.get("rendered_text_initial") or unit.get("text")),
                "pdf": compact(anchor.get("rendered_text_pdf")),
            }
        )
    worst.sort(key=lambda item: float(item["ratio"]))
    summary = {
        "review_units": str(review_units),
        "review_units_pdf_text": str(review_units_pdf_text),
        "checked": checked,
        "skipped": skipped,
        "warnings": warnings_count,
        "errors": errors_count,
        "warn_threshold": warn_threshold,
        "error_threshold": error_threshold,
        "worst": worst[:25],
    }
    return errors, warnings, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-units", required=True, type=Path)
    parser.add_argument("--review-units-pdf-text", required=True, type=Path)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--warn-threshold", type=float, default=0.72)
    parser.add_argument("--error-threshold", type=float, default=0.45)
    args = parser.parse_args(argv)

    errors, warnings, summary = audit_drift(
        review_units=args.review_units.expanduser().resolve(),
        review_units_pdf_text=args.review_units_pdf_text.expanduser().resolve(),
        warn_threshold=args.warn_threshold,
        error_threshold=args.error_threshold,
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
    print(f"Rendered-text drift audit passed: checked={summary['checked']} warnings={summary['warnings']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
