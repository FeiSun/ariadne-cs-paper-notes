#!/usr/bin/env python3
"""Remap legacy Ariadne issue anchors onto a current review_units.jsonl file."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ANCHOR_FIELDS = ("primary_anchor", "anchor", "paragraph_id", "sentence_id")


def compact_text(value: Any, *, max_chars: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.replace("∼", "~").replace("−", "-")
    text = re.sub(r"\\(?:textbf|textit|emph|texttt|mathrm|mathbf|mathit)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?", "", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text.strip(" \t\n\r.,;:!?\"'()[]{}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def review_unit_index(review_units: Path) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in read_jsonl(review_units):
        if row.get("kind") == "section":
            section_id = str(row.get("section_id") or "")
            if section_id:
                text = str(row.get("text") or "")
                record = {"anchor": section_id, "level": "section", "section_id": section_id, "text": text, "norm": normalize_text(text)}
                index[section_id] = record
                aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
                for alias in aliases:
                    alias_text = str(alias or "")
                    if alias_text:
                        index[alias_text] = record
            continue
        if row.get("kind") != "paragraph":
            continue
        paragraph_id = str(row.get("paragraph_id") or "")
        sentences = [item for item in row.get("sentences", []) if isinstance(item, dict)]
        paragraph_text = " ".join(str(item.get("text") or item.get("rendered_text_initial") or "") for item in sentences)
        section_id = str(row.get("section_id") or "")
        if paragraph_id:
            index[paragraph_id] = {
                "anchor": paragraph_id,
                "level": "paragraph",
                "section_id": section_id,
                "text": paragraph_text,
                "norm": normalize_text(paragraph_text),
            }
            label = str(row.get("label") or "")
            if label:
                index[label] = index[paragraph_id]
        for sentence in sentences:
            sentence_id = str(sentence.get("sentence_id") or "")
            if sentence_id:
                text = str(sentence.get("text") or sentence.get("rendered_text_initial") or "")
                index[sentence_id] = {
                    "anchor": sentence_id,
                    "level": "sentence",
                    "section_id": section_id,
                    "text": text,
                    "norm": normalize_text(text),
                }
            label = str(sentence.get("label") or "")
            if label and sentence_id:
                index[label] = index[sentence_id]
    return index


def target_level(anchor: str, units: dict[str, dict[str, str]]) -> str:
    if anchor == "paper" or anchor.startswith("page:"):
        return "paper"
    record = units.get(anchor)
    if record:
        return record["level"]
    if anchor.startswith("s-"):
        return "sentence"
    if anchor.startswith("p-"):
        return "paragraph"
    return "section"


def replacement_for_anchor(
    anchor: str,
    *,
    row: dict[str, Any],
    units: dict[str, dict[str, str]],
    threshold: float,
) -> tuple[str, float, str]:
    if not anchor or anchor == "paper" or anchor.startswith("page:"):
        return anchor, 1.0, "kept_special"
    if anchor in {"front-matter", "front_matter"}:
        return anchor, 1.0, "kept_special"
    if anchor in units:
        return units[anchor]["anchor"], 1.0, "kept_exact"

    level = target_level(anchor, units)
    snippet = compact_text(row.get("evidence_snippet") or row.get("snippet") or row.get("quote"), max_chars=1200)
    norm_snippet = normalize_text(snippet)
    if not norm_snippet:
        return anchor, 0.0, "missing_snippet"

    candidates = [unit for unit in units.values() if unit["level"] == level]
    if level == "section":
        source_section = compact_text(row.get("section_id"), max_chars=160)
        if source_section and source_section in units:
            return units[source_section]["anchor"], 1.0, "section_alias"
    best: tuple[float, str] = (0.0, "")
    seen: set[str] = set()
    for unit in candidates:
        candidate_anchor = unit["anchor"]
        if candidate_anchor in seen:
            continue
        seen.add(candidate_anchor)
        candidate = unit["norm"]
        if not candidate:
            continue
        score = 1.0 if norm_snippet in candidate else SequenceMatcher(None, norm_snippet, candidate).ratio()
        if score > best[0]:
            best = (score, candidate_anchor)
    if best[0] >= threshold and best[1]:
        return best[1], best[0], "snippet_match"
    return anchor, best[0], "unmatched"


def remap_render_hint(render_hint: Any, replacements: dict[str, str], units: dict[str, dict[str, str]]) -> Any:
    if not isinstance(render_hint, dict):
        return render_hint
    copied = dict(render_hint)
    anchor = str(copied.get("anchor") or "")
    if anchor in replacements:
        copied["anchor"] = replacements[anchor]
        level = target_level(copied["anchor"], units)
        if level != "paper":
            copied["target_level"] = level
    return copied


def remap_row(row: dict[str, Any], units: dict[str, dict[str, str]], *, threshold: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    copied = dict(row)
    changes: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    anchors = row.get("target_anchors")
    if isinstance(anchors, list):
        new_anchors: list[str] = []
        for item in anchors:
            old = str(item or "")
            new, score, method = replacement_for_anchor(old, row=row, units=units, threshold=threshold)
            replacements[old] = new
            if new not in new_anchors:
                new_anchors.append(new)
            if old != new or method == "unmatched":
                changes.append({"field": "target_anchors", "old": old, "new": new, "score": round(score, 3), "method": method})
        copied["target_anchors"] = new_anchors
    for field in ANCHOR_FIELDS:
        old = str(row.get(field) or "")
        if not old:
            continue
        new, score, method = replacement_for_anchor(old, row=row, units=units, threshold=threshold)
        replacements[old] = new
        copied[field] = new
        if old != new or method == "unmatched":
            changes.append({"field": field, "old": old, "new": new, "score": round(score, 3), "method": method})
    if "render_hint" in copied:
        copied["render_hint"] = remap_render_hint(copied.get("render_hint"), replacements, units)
    if changes:
        copied["anchor_remap"] = {"generated_by": "scripts/remap_issue_anchors.py", "changes": changes}
    return copied, changes


def remap_file(path: Path, out: Path, units: dict[str, dict[str, str]], *, threshold: float) -> dict[str, Any]:
    rows = read_jsonl(path)
    remapped: list[dict[str, Any]] = []
    changed = 0
    unmatched = 0
    for row in rows:
        new_row, changes = remap_row(row, units, threshold=threshold)
        if changes:
            changed += 1
            if any(change["method"] == "unmatched" for change in changes):
                unmatched += 1
        remapped.append(new_row)
    write_jsonl(out, remapped)
    return {"input": str(path), "output": str(out), "rows": len(rows), "changed_rows": changed, "unmatched_rows": unmatched}


def copy_issue_artifacts(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for path in src.iterdir():
        target = out / path.name
        if path.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(path, target)
        elif path.name not in {"prose_issues.jsonl", "whole_paper_findings.jsonl"}:
            shutil.copy2(path, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-units", required=True, type=Path)
    parser.add_argument("--issues-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args(argv)

    units = review_unit_index(args.review_units.expanduser().resolve())
    src = args.issues_dir.expanduser().resolve()
    out = args.out_dir.expanduser().resolve()
    copy_issue_artifacts(src, out)

    summaries: list[dict[str, Any]] = []
    for name in ("prose_issues.jsonl", "whole_paper_findings.jsonl"):
        path = src / name
        if path.exists():
            summaries.append(remap_file(path, out / name, units, threshold=args.threshold))

    payload = {
        "schema_version": 1,
        "generated_by": "scripts/remap_issue_anchors.py",
        "review_units": str(args.review_units.expanduser().resolve()),
        "issues_dir": str(src),
        "out_dir": str(out),
        "threshold": args.threshold,
        "files": summaries,
        "unmatched_rows": sum(int(item.get("unmatched_rows", 0) or 0) for item in summaries),
    }
    summary_out = args.summary_out.expanduser().resolve() if args.summary_out else out / "anchor_remap_summary.json"
    summary_out.parent.mkdir(parents=True, exist_ok=True)
    summary_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["unmatched_rows"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
