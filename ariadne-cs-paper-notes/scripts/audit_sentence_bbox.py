#!/usr/bin/env python3
"""Audit PDF bbox mappings and evidence snippets for Ariadne annotations."""

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


def normalize_evidence(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.replace("∼", "~").replace("−", "-")
    text = re.sub(r"\\(?:textbf|textit|emph|texttt|mathrm|mathbf|mathit)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?", "", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text.strip(" \t\n\r.,;:!?\"'()[]{}")


def compact_text(value: Any, *, max_chars: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def review_unit_index(review_units: Path, review_units_pdf_text: Path | None = None) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(review_units):
        if row.get("kind") == "section":
            section_id = str(row.get("section_id") or "")
            if section_id:
                index[section_id] = row
                aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
                for alias in aliases:
                    alias_text = str(alias or "")
                    if alias_text and alias_text not in index:
                        index[alias_text] = row
            continue
        if row.get("kind") != "paragraph":
            continue
        paragraph_id = str(row.get("paragraph_id") or "")
        sentences = [item for item in row.get("sentences", []) if isinstance(item, dict)]
        if paragraph_id:
            copy = dict(row)
            copy["text"] = " ".join(str(item.get("text") or "") for item in sentences)
            copy["rendered_text_pdf"] = " ".join(str(item.get("rendered_text_pdf") or item.get("rendered_text_initial") or "") for item in sentences)
            index[paragraph_id] = copy
            label = str(row.get("label") or "")
            if label:
                index[label] = copy
        for sentence in sentences:
            sentence_id = str(sentence.get("sentence_id") or "")
            if sentence_id:
                index[sentence_id] = sentence
            label = str(sentence.get("label") or "")
            if label and label not in index:
                index[label] = sentence
    sidecar = load_json(review_units_pdf_text)
    anchors = sidecar.get("anchors") if isinstance(sidecar, dict) and isinstance(sidecar.get("anchors"), dict) else {}
    for anchor_id, anchor in anchors.items():
        if not isinstance(anchor, dict) or anchor_id not in index:
            continue
        text = str(anchor.get("rendered_text_pdf") or "")
        if text:
            index[anchor_id]["rendered_text_pdf"] = text
    return index


def finding_by_id(findings: Path | None) -> dict[str, dict[str, Any]]:
    payload = load_json(findings)
    rows = payload.get("findings") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}
    return {str(item.get("id")): item for item in rows if isinstance(item, dict) and item.get("id")}


def annotations_list(annotations: Path | None) -> list[dict[str, Any]]:
    payload = load_json(annotations)
    rows = payload.get("annotations") if isinstance(payload, dict) else payload
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def annotation_anchor(annotation: dict[str, Any]) -> tuple[str, str]:
    level = str(annotation.get("target_level") or "").lower()
    for candidate_level, field in (
        ("sentence", "sentence_id"),
        ("paragraph", "paragraph_id"),
        ("section", "section_id"),
        ("paper", "paper_id"),
    ):
        value = str(annotation.get(field) or "")
        if value:
            return level or candidate_level, value
    return level, ""


def evidence_snippet(finding: dict[str, Any]) -> str:
    return compact_text(finding.get("evidence_snippet") or finding.get("snippet") or finding.get("quote"), max_chars=500)


def snippet_matches(snippet: str, unit: dict[str, Any], bbox_anchor: dict[str, Any] | None, *, threshold: float) -> bool:
    normalized_snippet = normalize_evidence(snippet)
    if not normalized_snippet:
        return False
    candidates = [
        unit.get("text"),
        unit.get("rendered_text_initial"),
        unit.get("rendered_text_pdf"),
        bbox_anchor.get("rendered_text_pdf") if isinstance(bbox_anchor, dict) else "",
    ]
    for candidate in candidates:
        normalized_candidate = normalize_evidence(candidate)
        if not normalized_candidate:
            continue
        if normalized_snippet in normalized_candidate:
            return True
        if SequenceMatcher(None, normalized_snippet, normalized_candidate).ratio() >= threshold:
            return True
    return False


def unit_matches_bbox_text(unit: dict[str, Any], bbox_anchor: dict[str, Any], *, threshold: float) -> bool:
    bbox_text = normalize_evidence(bbox_anchor.get("rendered_text_pdf"))
    if not bbox_text:
        return False
    for candidate in (unit.get("text"), unit.get("rendered_text_initial"), unit.get("rendered_text_pdf")):
        unit_text = normalize_evidence(candidate)
        if not unit_text:
            continue
        if unit_text in bbox_text or bbox_text in unit_text:
            return True
        if SequenceMatcher(None, unit_text, bbox_text).ratio() >= threshold:
            return True
    return False


def audit_sentence_bbox(
    *,
    review_units: Path,
    review_units_pdf_text: Path | None,
    sentence_bbox: Path | None,
    annotations: Path | None,
    findings: Path | None,
    evidence_threshold: float,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    unit_index = review_unit_index(review_units, review_units_pdf_text)
    bbox_payload = load_json(sentence_bbox)
    bbox_anchors = bbox_payload.get("anchors") if isinstance(bbox_payload, dict) and isinstance(bbox_payload.get("anchors"), dict) else {}
    findings_index = finding_by_id(findings)
    mapped = 0
    unmappable = 0
    low_confidence = 0
    anchors_checked = 0
    weak_bbox_anchors = 0

    if isinstance(bbox_anchors, dict):
        for anchor, bbox_anchor in bbox_anchors.items():
            if anchor not in unit_index or not isinstance(bbox_anchor, dict) or bbox_anchor.get("unmappable"):
                continue
            anchors_checked += 1
            if not unit_matches_bbox_text(unit_index[anchor], bbox_anchor, threshold=evidence_threshold):
                weak_bbox_anchors += 1
                warnings.append(f"bbox anchor `{anchor}` rendered_text_pdf weakly matches review unit text")

    for annotation in annotations_list(annotations):
        level, anchor = annotation_anchor(annotation)
        if level not in {"sentence", "paragraph", "section"}:
            continue
        issue_id = str(annotation.get("issue_id") or "")
        if anchor not in unit_index:
            errors.append(f"annotation {issue_id or '<missing issue>'} targets unknown {level} `{anchor}`")
            continue
        bbox_anchor = bbox_anchors.get(anchor) if isinstance(bbox_anchors, dict) else None
        if sentence_bbox is not None:
            if not isinstance(bbox_anchor, dict):
                errors.append(f"annotation {issue_id or '<missing issue>'} target `{anchor}` has no bbox anchor")
            elif bbox_anchor.get("unmappable"):
                unmappable += 1
                warnings.append(f"annotation {issue_id or '<missing issue>'} target `{anchor}` is unmappable: {bbox_anchor.get('reason')}")
            elif not bbox_anchor.get("rects"):
                errors.append(f"annotation {issue_id or '<missing issue>'} target `{anchor}` has empty rects")
            else:
                mapped += 1
                if bbox_anchor.get("confidence") == "low":
                    low_confidence += 1
                    warnings.append(f"annotation {issue_id or '<missing issue>'} target `{anchor}` has low-confidence bbox")
        finding = findings_index.get(issue_id)
        if not finding:
            continue
        if level in {"sentence", "paragraph"}:
            snippet = evidence_snippet(finding)
            if not snippet:
                errors.append(f"finding {issue_id} anchored to {level} `{anchor}` missing evidence_snippet/snippet")
            elif not snippet_matches(snippet, unit_index[anchor], bbox_anchor if isinstance(bbox_anchor, dict) else None, threshold=evidence_threshold):
                errors.append(f"finding {issue_id} evidence snippet does not match anchored {level} `{anchor}`")

    summary = {
        "review_units": str(review_units),
        "review_units_pdf_text": str(review_units_pdf_text) if review_units_pdf_text else "",
        "sentence_bbox": str(sentence_bbox) if sentence_bbox else "",
        "annotations": str(annotations) if annotations else "",
        "findings": str(findings) if findings else "",
        "mapped_annotations": mapped,
        "unmappable_annotations": unmappable,
        "low_confidence_annotations": low_confidence,
        "anchors_checked": anchors_checked,
        "weak_bbox_anchors": weak_bbox_anchors,
        "errors": len(errors),
        "warnings": len(warnings),
    }
    return errors, warnings, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-units", required=True, type=Path)
    parser.add_argument("--review-units-pdf-text", type=Path)
    parser.add_argument("--sentence-bbox", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--findings", type=Path)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--evidence-threshold", type=float, default=0.80)
    args = parser.parse_args(argv)

    errors, warnings, summary = audit_sentence_bbox(
        review_units=args.review_units.expanduser().resolve(),
        review_units_pdf_text=args.review_units_pdf_text.expanduser().resolve() if args.review_units_pdf_text else None,
        sentence_bbox=args.sentence_bbox.expanduser().resolve() if args.sentence_bbox else None,
        annotations=args.annotations.expanduser().resolve() if args.annotations else None,
        findings=args.findings.expanduser().resolve() if args.findings else None,
        evidence_threshold=args.evidence_threshold,
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
        "Sentence bbox audit passed: "
        f"mapped={summary['mapped_annotations']} unmappable={summary['unmappable_annotations']} "
        f"low_confidence={summary['low_confidence_annotations']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
