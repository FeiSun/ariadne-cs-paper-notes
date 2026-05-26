#!/usr/bin/env python3
"""Extract compact model-facing review units from Ariadne source paper HTML.

This script intentionally converts the source-derived paper HTML into a small
plain-text/JSONL view for reviewer context. The HTML remains the rendering
base; the model should read these units instead of reading rendered HTML.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from collections import OrderedDict
from typing import Any

from bs4 import BeautifulSoup, Tag


HEADING_SELECTOR = "h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]"
CHECKLIST_BOILERPLATE_PREFIXES = (
    "Question:",
    "Guidelines:",
    "The answer means",
    "The paper should",
    "Please refer",
    "Depending on",
    "We recognize",
    "For initial submissions",
    "This includes",
)


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def heading_level(tag: Tag) -> int:
    try:
        return int(str(tag.name or "h1")[1:])
    except ValueError:
        return 1


def class_names(tag: Tag) -> list[str]:
    classes = tag.get("class", [])
    if isinstance(classes, str):
        return classes.split()
    return [str(item) for item in classes]


def skip_review_node(tag: Tag) -> bool:
    current: Tag | None = tag
    while current is not None:
        if current.get("data-review-skip"):
            return True
        if "paper-title" in class_names(current) or "paper-author" in class_names(current):
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


def keep_sentence(section_id: str, text: str, *, include_checklist_boilerplate: bool) -> bool:
    if include_checklist_boilerplate or section_id != "neurips-paper-checklist":
        return True
    return text.startswith(("Answer:", "Justification:", "Declaration of LLM usage"))


def extract_units(source_html: Path, *, include_checklist_boilerplate: bool = False) -> list[dict[str, Any]]:
    soup = BeautifulSoup(source_html.read_text(encoding="utf-8"), "lxml")
    body = soup.body or soup
    units: list[dict[str, Any]] = []
    paragraphs: OrderedDict[str, dict[str, Any]] = OrderedDict()
    current_section_id = "front-matter"
    current_section_title = "Front matter"
    seen_sections: set[str] = set()
    seen_sentence_ids: set[str] = set()

    for node in body.descendants:
        if not isinstance(node, Tag):
            continue
        if node.name in {"script", "style"}:
            continue
        if skip_review_node(node):
            continue
        if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"} and node.get("id"):
            current_section_id = str(node.get("id") or "")
            current_section_title = compact_text(node.get_text(" ", strip=True))
            if current_section_id and current_section_id not in seen_sections:
                units.append(
                    {
                        "kind": "section",
                        "section_id": current_section_id,
                        "level": heading_level(node),
                        "text": current_section_title,
                    }
                )
                seen_sections.add(current_section_id)
            continue
        sentence_id = str(node.get("data-sentence-id") or "")
        if not sentence_id or sentence_id in seen_sentence_ids:
            continue
        paragraph_node = node.find_parent(attrs={"data-paragraph-id": True})
        paragraph_id = (
            str(paragraph_node.get("data-paragraph-id") or "")
            if isinstance(paragraph_node, Tag)
            else f"p-{current_section_id}-unparagraphized"
        )
        if paragraph_id not in paragraphs:
            paragraph = {
                "kind": "paragraph",
                "paragraph_id": paragraph_id,
                "section_id": current_section_id,
                "section_title": current_section_title,
                "sentences": [],
            }
            paragraphs[paragraph_id] = paragraph
            units.append(paragraph)
        text = compact_text(node.get_text(" ", strip=True))
        if text and keep_sentence(current_section_id, text, include_checklist_boilerplate=include_checklist_boilerplate):
            paragraphs[paragraph_id]["sentences"].append({"sentence_id": sentence_id, "text": text})
            seen_sentence_ids.add(sentence_id)
    return units


def write_jsonl(units: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for unit in units:
            if unit.get("kind") == "paragraph" and not unit.get("sentences"):
                continue
            handle.write(json.dumps(unit, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_markdown(units: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = []
    current_section = ""
    for unit in units:
        if unit.get("kind") == "section":
            level = max(1, min(int(unit.get("level", 1)), 6))
            section_id = unit.get("section_id", "")
            text = unit.get("text", "")
            lines.append(f"{'#' * level} {text} {{#{section_id}}}")
            lines.append("")
            current_section = section_id
            continue
        if unit.get("kind") != "paragraph":
            continue
        if not unit.get("sentences"):
            continue
        section_id = str(unit.get("section_id", ""))
        if section_id and section_id != current_section:
            lines.append(f"## {unit.get('section_title', section_id)} {{#{section_id}}}")
            lines.append("")
            current_section = section_id
        paragraph_id = unit.get("paragraph_id", "")
        lines.append(f"[{paragraph_id}]")
        for sentence in unit.get("sentences", []):
            lines.append(f"{{{sentence['sentence_id']}}} {sentence['text']}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_html", type=Path, help="Canonical <stem>.source.html from render_paper_html.py")
    parser.add_argument("--jsonl", type=Path, help="Write machine-readable review units")
    parser.add_argument("--markdown", "--md", dest="markdown", type=Path, help="Write compact model-facing Markdown")
    parser.add_argument(
        "--include-checklist-boilerplate",
        action="store_true",
        help="Keep venue checklist question/guideline template text in review units",
    )
    args = parser.parse_args(argv)

    units = extract_units(args.source_html, include_checklist_boilerplate=args.include_checklist_boilerplate)
    jsonl_path = args.jsonl or args.source_html.with_suffix(".review_units.jsonl")
    markdown_path = args.markdown or args.source_html.with_suffix(".review_units.md")
    write_jsonl(units, jsonl_path)
    write_markdown(units, markdown_path)

    reviewable_paragraphs = [unit for unit in units if unit.get("kind") == "paragraph" and unit.get("sentences")]
    sentence_count = sum(len(unit.get("sentences", [])) for unit in reviewable_paragraphs)
    paragraph_count = len(reviewable_paragraphs)
    section_count = sum(1 for unit in units if unit.get("kind") == "section")
    print(f"Review units JSONL: {jsonl_path}")
    print(f"Review units Markdown: {markdown_path}")
    print(f"Sections: {section_count}")
    print(f"Paragraphs: {paragraph_count}")
    print(f"Sentences: {sentence_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
