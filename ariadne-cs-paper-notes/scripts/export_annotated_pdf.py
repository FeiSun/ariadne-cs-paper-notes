#!/usr/bin/env python3
"""Optionally export native PDF highlights from Ariadne bbox annotations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def as_rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [item for item in payload[key] if isinstance(item, dict)]
    return []


def finding_index(path: Path) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in as_rows(load_json(path), "findings") if item.get("id")}


def annotation_anchor(annotation: dict[str, Any]) -> str:
    for field in ("sentence_id", "paragraph_id", "section_id"):
        value = str(annotation.get(field) or "")
        if value:
            return value
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--sentence-bbox", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        import fitz  # type: ignore
    except ModuleNotFoundError:
        print("PyMuPDF is unavailable; skipping annotated PDF export.")
        return 0

    findings = finding_index(args.findings)
    annotations = as_rows(load_json(args.annotations), "annotations")
    bbox = load_json(args.sentence_bbox)
    anchors = bbox.get("anchors") if isinstance(bbox, dict) and isinstance(bbox.get("anchors"), dict) else {}
    doc = fitz.open(str(args.pdf))
    written = 0
    for annotation in annotations:
        issue_id = str(annotation.get("issue_id") or "")
        finding = findings.get(issue_id, {})
        anchor_id = annotation_anchor(annotation)
        anchor = anchors.get(anchor_id) if isinstance(anchors, dict) else None
        if not isinstance(anchor, dict) or anchor.get("unmappable"):
            continue
        for rect in anchor.get("rects", []):
            page_no = int(rect.get("page") or 0) - 1
            if page_no < 0 or page_no >= len(doc):
                continue
            page = doc[page_no]
            pdf_rect = fitz.Rect(float(rect["x0"]), float(rect["y0"]), float(rect["x1"]), float(rect["y1"]))
            annot = page.add_highlight_annot(pdf_rect)
            annot.set_info(
                title=f"{finding.get('severity', 'Ariadne')} {issue_id}",
                content="\n".join(
                    str(part)
                    for part in (
                        finding.get("title") or issue_id,
                        finding.get("diagnosis") or "",
                        finding.get("next_draft_task") or "",
                    )
                    if part
                ),
            )
            annot.update()
            written += 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(args.out))
    doc.close()
    print(f"Annotated PDF: {args.out} ({written} highlight rects)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
