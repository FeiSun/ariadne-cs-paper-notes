#!/usr/bin/env python3
"""Audit Ariadne HTML reports for coverage/body consistency."""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


REQUIRED_SECTIONS = {
    "executive-diagnosis",
    "issue-index",
    "claim-evidence-audit",
    "deep-reading-notes",
    "submission-readiness",
    "local-comments",
    "revision-plan",
    "coverage-receipt",
}

NUMERIC_CONTEXT_RE = re.compile(
    r"(Safety Score|Avg|Average|Mean|均值|平均|delta|reported|computed|复算|表中写|偏差|隐藏小数|需核对|需要核对|需复查|建议复查)",
    re.IGNORECASE,
)
VAGUE_NUMERIC_RE = re.compile(r"(有偏差|需核对|需要核对|需复查|建议复查|可能来自隐藏小数|hidden decimals?)", re.IGNORECASE)
NUMERIC_VALUE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
CONCRETE_NUMERIC_CUE_RE = re.compile(
    r"(reported|computed|visible_computed|visible computed|visible arithmetic mean|复算|表中写|不是|delta|差值)",
    re.IGNORECASE,
)
NUMERIC_TEXT_TAGS = {"p", "li", "td", "th", "article", "section"}

TEACHING_SECTIONS = {
    "deep-reading-notes",
    "local-comments",
}

LEGACY_SPLIT_NOTE_SECTIONS = {
    "top-priorities",
    "section-review",
    "paragraph-surgery",
    "margin-notes",
    "keep-notes",
}


class AriadneHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.href_anchors: set[str] = set()
        self.section_stack: list[str] = []
        self.counts = {
            "margin_rows": 0,
            "surgery_rows": 0,
            "section_review_rows": 0,
            "pdf_pages": 0,
            "severity_items": 0,
        }
        self.text_stack: list[tuple[str, list[str]]] = []
        self.current_text_parts: list[str] = []
        self.numeric_texts: list[str] = []
        self.defined_finding_ids: set[str] = set()
        self.linked_finding_refs: list[tuple[str, str]] = []
        self.raw_schema_key_texts: list[str] = []
        self.tables: list[dict[str, object]] = []
        self.table_stack: list[dict[str, object]] = []
        self.section_text_stack: list[tuple[str, list[str]]] = []
        self.section_texts: dict[str, str] = {}
        self.issue_item_stack: list[dict[str, str | list[str]]] = []
        self.issue_items: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        element_id = attr.get("id")
        if element_id:
            self.ids.add(element_id)
        href = attr.get("href", "")
        if href.startswith("#") and len(href) > 1:
            self.href_anchors.add(href[1:])

        if tag == "section":
            self.section_stack.append(element_id or "")
            self.section_text_stack.append((element_id or "", []))
            if "pdf-anchor" in attr.get("class", "").split():
                self.counts["pdf_pages"] += 1
        elif tag == "tr":
            note_kind = attr.get("data-note-kind", "")
            if "deep-reading-notes" in self.section_stack:
                if note_kind == "sentence" and "data-severity" in attr:
                    self.counts["margin_rows"] += 1
                if note_kind == "paragraph" and ("data-decision" in attr or "data-severity" in attr):
                    self.counts["surgery_rows"] += 1
                if note_kind == "section" and "data-severity" in attr:
                    self.counts["section_review_rows"] += 1
        elif tag == "article":
            note_kind = attr.get("data-note-kind", "")
            if "deep-reading-notes" in self.section_stack:
                if note_kind == "sentence":
                    self.counts["margin_rows"] += 1
                if note_kind == "paragraph":
                    self.counts["surgery_rows"] += 1
                if note_kind == "section":
                    self.counts["section_review_rows"] += 1

        if "data-severity" in attr:
            self.counts["severity_items"] += 1
            if attr.get("data-issue-type"):
                self.issue_item_stack.append(
                    {
                        "severity": attr.get("data-severity", ""),
                        "issue_type": attr.get("data-issue-type", ""),
                        "tag": tag,
                        "text_parts": [],
                    }
                )
        if tag == "table":
            self.table_stack.append({"has_caption": False, "header_without_scope": 0, "id": element_id or ""})
        elif tag == "caption" and self.table_stack:
            self.table_stack[-1]["has_caption"] = True
        elif tag == "th" and self.table_stack:
            if "scope" not in attr:
                self.table_stack[-1]["header_without_scope"] = int(self.table_stack[-1]["header_without_scope"]) + 1
        if element_id and re.fullmatch(r"[FBMLN]\d+[A-Za-z]?", element_id):
            self.defined_finding_ids.add(element_id)
        if tag == "a":
            text_ref = attr.get("href", "")
            if text_ref.startswith("#") and re.fullmatch(r"#[FBMLN]\d+[A-Za-z]?", text_ref):
                self.linked_finding_refs.append((text_ref[1:], text_ref))
        if tag in NUMERIC_TEXT_TAGS:
            self.text_stack.append((tag, []))

    def handle_endtag(self, tag: str) -> None:
        if tag in NUMERIC_TEXT_TAGS and self.text_stack and self.text_stack[-1][0] == tag:
            _, parts = self.text_stack.pop()
            text = "".join(parts).strip()
            if NUMERIC_CONTEXT_RE.search(text):
                self.numeric_texts.append(re.sub(r"\s+", " ", text))
            if re.search(r"\b(reported_value|visible_computed_value|aggregation_caveat)\b", text):
                self.raw_schema_key_texts.append(re.sub(r"\s+", " ", text))
            if self.text_stack and text:
                self.text_stack[-1][1].append(" " + text)
        if tag == "section" and self.section_stack and self.section_stack[-1] == (self.section_text_stack[-1][0] if self.section_text_stack else ""):
            section_id, parts = self.section_text_stack.pop() if self.section_text_stack else ("", [])
            if section_id:
                section_text = re.sub(r"\s+", " ", "".join(parts)).strip()
                self.section_texts[section_id] = section_text
            if self.section_text_stack and parts:
                self.section_text_stack[-1][1].append(" ".join(parts))
            self.section_stack.pop()
        if tag == "table" and self.table_stack:
            self.tables.append(self.table_stack.pop())
        if self.issue_item_stack and tag == self.issue_item_stack[-1].get("tag"):
            item = self.issue_item_stack.pop()
            parts = item.get("text_parts", [])
            text = re.sub(r"\s+", " ", "".join(parts if isinstance(parts, list) else [])).strip()
            self.issue_items.append(
                {
                    "severity": str(item.get("severity", "")),
                    "issue_type": str(item.get("issue_type", "")),
                    "text": text,
                }
            )

    def handle_data(self, data: str) -> None:
        if self.text_stack:
            self.text_stack[-1][1].append(data)
        if self.section_text_stack:
            self.section_text_stack[-1][1].append(data)
        for item in self.issue_item_stack:
            parts = item.get("text_parts")
            if isinstance(parts, list):
                parts.append(data)


def find_declared_count(text: str, labels: list[str]) -> int | None:
    for label in labels:
        pattern = rf"<td>\s*{re.escape(label)}\s*</td>\s*<td>\s*(\d+)\s*</td>"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def audit(path: Path) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    parser = AriadneHTMLParser()
    parser.feed(text)

    errors: list[str] = []
    warnings: list[str] = []

    missing_sections = sorted(REQUIRED_SECTIONS - parser.ids)
    for section_id in missing_sections:
        errors.append(f"missing required section #{section_id}")

    if parser.section_stack or parser.issue_item_stack or parser.text_stack or parser.table_stack:
        errors.append("HTML appears structurally incomplete or misnested; parser stacks were not fully closed")

    missing_teaching = sorted(TEACHING_SECTIONS - parser.ids)
    for section_id in missing_teaching:
        errors.append(f"missing teaching-layer section #{section_id}")

    for anchor in sorted(parser.href_anchors):
        if anchor not in parser.ids:
            errors.append(f"nav/link target #{anchor} has no matching element id")

    if parser.counts["margin_rows"] == 0:
        errors.append("#deep-reading-notes has no sentence rows (`data-note-kind=\"sentence\"`)")
    if parser.counts["surgery_rows"] == 0:
        errors.append("#deep-reading-notes has no paragraph rows (`data-note-kind=\"paragraph\"`)")
    if parser.counts["section_review_rows"] == 0:
        errors.append("#deep-reading-notes has no section reflection rows (`data-note-kind=\"section\"`)")
    legacy = sorted(LEGACY_SPLIT_NOTE_SECTIONS & parser.ids)
    if legacy or "section-comments" in parser.ids or "section-reflections" in parser.ids:
        errors.append(
            "use ordered #deep-reading-notes instead of separate/repeated sections: "
            + ", ".join(legacy + [item for item in ("section-comments", "section-reflections") if item in parser.ids])
        )

    declared_margin = find_declared_count(
        text,
        [
            "Visible sentence issue notes",
            "Visible sentence notes",
            "Visible sentence-like issue rows",
            "Sentence notes",
            "句子级批注",
            "Margin notes",
            "逐句批注",
        ],
    )
    if declared_margin is not None and declared_margin != parser.counts["margin_rows"]:
        errors.append(
            f"declared sentence/margin-note count {declared_margin} != body count {parser.counts['margin_rows']}"
        )

    declared_surgery = find_declared_count(
        text,
        [
            "Visible paragraph issue rows",
            "Visible paragraph rows",
            "Paragraph rows",
            "Paragraph surgery rows",
            "逐段手术",
            "Paragraph surgery",
            "段落级批注",
        ],
    )
    if declared_surgery is not None and declared_surgery != parser.counts["surgery_rows"]:
        errors.append(f"declared paragraph row count {declared_surgery} != body count {parser.counts['surgery_rows']}")

    declared_section_reflections = find_declared_count(
        text,
        [
            "Section reflection rows",
            "章节读后反思",
            "章节反思",
        ],
    )
    if declared_section_reflections is not None and declared_section_reflections != parser.counts["section_review_rows"]:
        errors.append(
            f"declared section-reflection count {declared_section_reflections} != body count {parser.counts['section_review_rows']}"
        )

    if "Coverage consistency" not in text and "coverage consistency" not in text:
        warnings.append("coverage receipt does not mention Coverage consistency gate")
    if "pending in" in text and "Pending in" not in text:
        warnings.append("pending units are mentioned outside the standard Pending in receipt column")
    issue_index_text = parser.section_texts.get("issue-index", "")
    if "降级条件" in issue_index_text or "下一稿任务" in issue_index_text:
        errors.append("#issue-index should be compact; move 降级条件/下一稿任务 to findings.json, deep-reading rows, or Revision Plan")

    for numeric_text in parser.numeric_texts:
        if not VAGUE_NUMERIC_RE.search(numeric_text):
            continue
        numbers = NUMERIC_VALUE_RE.findall(numeric_text)
        has_concrete_cue = bool(CONCRETE_NUMERIC_CUE_RE.search(numeric_text))
        if len(numbers) < 2 or not has_concrete_cue:
            preview = numeric_text[:240]
            errors.append(
                "vague numeric language without concrete reported/computed/delta values: "
                f"{preview!r}"
            )

    for raw_text in parser.raw_schema_key_texts:
        preview = raw_text[:240]
        errors.append(
            "Chinese-facing HTML body renders raw numerical schema keys; use 表中数值 / 可见复算值 / 差值 / 口径说明: "
            f"{preview!r}"
        )

    for ref, source in parser.linked_finding_refs:
        if ref not in parser.defined_finding_ids:
            errors.append(f"linked finding `{ref}` has no matching finding/id anchor")

    for table in parser.tables:
        if not table.get("has_caption"):
            errors.append("table is missing <caption>")
        if int(table.get("header_without_scope", 0)) > 0:
            errors.append("table has <th> without scope attribute")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    args = parser.parse_args(argv)

    errors, warnings = audit(args.html)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Ariadne HTML report audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
