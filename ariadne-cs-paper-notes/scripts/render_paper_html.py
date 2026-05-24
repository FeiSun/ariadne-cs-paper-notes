#!/usr/bin/env python3
"""Render a LaTeX paper into Ariadne's paper-reader HTML preview."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


SENTENCE_CONTAINER_TAGS = {"p", "li", "figcaption", "caption"}
SKIP_PARENT_TAGS = {"script", "style", "math", "svg", "table", "pre", "code"}
BLOCK_CHILD_TAGS = {"blockquote", "div", "figure", "ol", "p", "pre", "table", "ul"}
PANDOC_SOURCE = "pandoc"
SENTENCE_ID_SCHEME = "section-paragraph-sentence-v2"
PDF_ASSET_DPI = "144"
LAYOUT_PARAM_RE = re.compile(r"^(?:[rlc]\s*)?(?:max\s+width\s*=\s*)?(?:\d+(?:\.\d+)?)?$", re.IGNORECASE)
LATEX_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
LATEX_ENV_RE = re.compile(r"\\begin\{(figure\*?|table\*?|wrapfigure|wraptable|algorithm\*?)\}(?:\[[^\]]*\]|\{[^{}]*\})*.*?\\end\{\1\}", re.DOTALL)
LATEX_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
LATEX_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
LATEX_BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\{([^}]+)\}")
LATEX_ADD_BIB_RESOURCE_RE = re.compile(r"\\addbibresource(?:\[[^\]]*\])?\{([^}]+)\}")
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])(\s+)(?=[A-Z0-9\"'“‘(])")
SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
REVIEW_IMPORT_SECTION_LABELS = {
    "executive-diagnosis": "总评诊断",
    "paper-type-contract": "论文类型与审稿契约",
    "top-priorities": "修改优先级",
    "claim-evidence-map": "主张-证据对照",
    "story-logic-red-team": "逻辑红队检查",
    "section-comments": "分章批注",
    "local-comments": "共性问题汇总",
    "margin-notes": "句子级批注",
    "pdf-layout-notes": "版式批注",
    "keep-notes": "建议保留",
    "revision-plan": "修改路线",
}
SEVERITY_LABELS = {
    "blocker": "[!] Blocker",
    "major": "[^] Major",
    "minor": "[i] Minor",
    "polish": "[~] Polish",
}
SEVERITY_SHORT_LABELS = {
    "blocker": "Blocker",
    "major": "Major",
    "minor": "Minor",
    "polish": "Polish",
}
SEVERITY_RANK = {
    "blocker": 4,
    "major": 3,
    "minor": 2,
    "polish": 1,
}
ANCHOR_LEVELS = {"sentence", "paragraph", "section", "paper"}
WORKBENCH_SECTION_LABELS = {
    "executive-diagnosis": "总评诊断与可救骨架",
    "issue-index": "问题索引",
    "claim-evidence-audit": "主张与证据审计",
    "deep-reading-notes": "逐章精读批注",
    "submission-readiness": "提交就绪",
    "local-comments": "共性问题汇总",
    "revision-plan": "修改路线",
    "coverage-receipt": "覆盖回执",
}
SUBMISSION_DOMAINS = {"layout", "numeric", "reference", "symbol", "source_hygiene", "figure_caption", "polish"}
ANCHOR_LEVEL_LABELS = {
    "sentence": "句子",
    "paragraph": "段落",
    "section": "章节",
    "paper": "全文",
}
ANCHOR_LEVEL_CLASS = {
    "sentence": "sentence",
    "paragraph": "paragraph",
    "section": "section",
    "paper": "paper",
}


def strongest_severity(values: list[str]) -> str:
    severities = [value for value in values if value in SEVERITY_RANK]
    if not severities:
        return "major"
    return max(severities, key=lambda value: SEVERITY_RANK[value])


def ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def first_nonempty(item: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def normalize_anchor_level(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "sent": "sentence",
        "sentence": "sentence",
        "sentence-note": "sentence",
        "paragraph": "paragraph",
        "para": "paragraph",
        "paragraph-note": "paragraph",
        "section": "section",
        "sec": "section",
        "section-note": "section",
        "chapter": "section",
        "paper": "paper",
        "overall": "paper",
        "global": "paper",
        "whole-paper": "paper",
        "paper-note": "paper",
    }
    return aliases.get(text, "")


def infer_anchor_level(item: dict[str, object]) -> str:
    explicit = normalize_anchor_level(first_nonempty(item, "target_level", "anchor_level", "note_kind", "scope"))
    if explicit:
        return explicit
    target_anchors = item.get("target_anchors")
    first_anchor = ""
    if isinstance(target_anchors, list) and target_anchors:
        first_anchor = str(target_anchors[0]).strip()
    elif target_anchors:
        first_anchor = str(target_anchors).strip()
    if not first_anchor:
        first_anchor = str(first_nonempty(item, "primary_anchor", "anchor") or "").strip()
    if first_anchor.startswith("s-"):
        return "sentence"
    if first_anchor.startswith("p-"):
        return "paragraph"
    if first_anchor and not first_anchor.startswith("page:") and first_anchor != "paper":
        return "section"
    if first_nonempty(item, "paragraph_id", "paragraph_ids", "target_paragraph", "target_paragraphs", "paper_paragraph_id"):
        return "paragraph"
    if first_nonempty(item, "section_id", "section_ids", "target_section", "target_sections", "paper_section_id", "heading_id"):
        return "section"
    if str(first_nonempty(item, "is_paper_level", "paper_level") or "").strip().lower() in {"1", "true", "yes"}:
        return "paper"
    return "sentence"


def relative_or_absolute(path: Path, base_dir: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def bibliography_paths(tex_path: Path) -> list[Path]:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    raw_paths: list[str] = []
    for match in LATEX_BIBLIOGRAPHY_RE.finditer(expanded):
        raw_paths.extend(part.strip() for part in match.group(1).split(","))
    raw_paths.extend(match.group(1).strip() for match in LATEX_ADD_BIB_RESOURCE_RE.finditer(expanded))

    bibs: list[Path] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        if not raw_path:
            continue
        candidate = (tex_path.parent / raw_path).resolve()
        paths = [candidate]
        if candidate.suffix == "":
            paths.append(candidate.with_suffix(".bib"))
        for path in paths:
            if path.exists() and path.is_file() and path not in seen:
                bibs.append(path)
                seen.add(path)
                break
    return bibs


def run_pandoc(tex_path: Path, raw_html_path: Path) -> None:
    bibs = bibliography_paths(tex_path)
    command = [
        "pandoc",
        tex_path.name,
        "--from=latex",
        "--to=html5",
        "--mathml",
        "--standalone",
        "--resource-path=.",
        "-o",
        str(raw_html_path),
    ]
    if bibs:
        command.append("--citeproc")
        for bib in bibs:
            command.append(f"--bibliography={relative_or_absolute(bib, tex_path.parent)}")
    try:
        subprocess.run(command, cwd=tex_path.parent, check=True)
    except FileNotFoundError:
        raise SystemExit("pandoc is not installed or not on PATH") from None
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"pandoc failed with exit code {exc.returncode}") from exc


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def normalize_annotation_item(item: dict[str, object], idx: int, *, source: str) -> list[dict[str, str]]:
    anchor_level = infer_anchor_level(item)
    if anchor_level == "sentence":
        raw_ids = first_nonempty(
            item,
            "sentence_id",
            "sentence_ids",
            "paper_sentence_id",
            "paper_sentence_ids",
            "target_sentence",
            "target_sentences",
        )
        if raw_ids is None:
            raw_ids = first_nonempty(item, "target_anchors", "primary_anchor", "anchor")
        target_key = "sentence_id"
    elif anchor_level == "paragraph":
        raw_ids = first_nonempty(
            item,
            "paragraph_id",
            "paragraph_ids",
            "paper_paragraph_id",
            "paper_paragraph_ids",
            "target_paragraph",
            "target_paragraphs",
        )
        if raw_ids is None:
            raw_ids = first_nonempty(item, "target_anchors", "primary_anchor", "anchor")
        target_key = "paragraph_id"
    elif anchor_level == "section":
        raw_ids = first_nonempty(
            item,
            "section_id",
            "section_ids",
            "paper_section_id",
            "paper_section_ids",
            "target_section",
            "target_sections",
            "heading_id",
        )
        if raw_ids is None:
            raw_ids = first_nonempty(item, "target_anchors", "primary_anchor", "anchor")
        target_key = "section_id"
    else:
        raw_ids = first_nonempty(item, "paper_id", "target_paper") or "paper"
        target_key = "paper_id"
    if raw_ids is None:
        if source == "findings":
            return []
        raise SystemExit(f"annotation #{idx} missing target id for `{anchor_level}` annotation")
    anchor_ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
    severity = str(item.get("severity", "major")).strip().lower()
    if severity not in SEVERITY_LABELS:
        raise SystemExit(f"annotation #{idx} has invalid severity `{severity}`")
    base = {
        "issue_id": item.get("issue_id") or item.get("id") or f"A{idx}",
        "issue_type": item.get("issue_type") or item.get("type") or "prose",
        "target_level": anchor_level,
        "short": item.get("short") or item.get("short_comment") or item.get("one_line") or item.get("title") or item.get("diagnosis") or "",
        "title": item.get("title") or item.get("one_line") or item.get("diagnosis") or "句子问题",
        "problem": item.get("problem") or item.get("what") or item.get("diagnosis") or "",
        "diagnosis": item.get("diagnosis") or item.get("problem") or item.get("what") or "",
        "why": item.get("why") or item.get("reader_friction") or "",
        "reader_friction": item.get("reader_friction") or item.get("why") or "",
        "principle": item.get("principle") or item.get("writing_principle") or "",
        "writing_principle": item.get("writing_principle") or item.get("principle") or "",
        "task": item.get("task") or item.get("next_draft_task") or item.get("next_draft_task_or_question") or "",
        "next_draft_task": item.get("next_draft_task") or item.get("task") or item.get("next_draft_task_or_question") or "",
        "self_check": item.get("self_check") or item.get("next_draft_question") or item.get("revision_question") or "",
        "next_draft_question": item.get("next_draft_question") or item.get("self_check") or item.get("revision_question") or "",
        "severity_rationale": item.get("severity_rationale") or "",
        "downgrade_condition": item.get("downgrade_condition") or "",
        "confidence": item.get("confidence") or "",
        "location": item.get("location") or "",
        "snippet": item.get("snippet") or "",
        "evidence_basis": item.get("evidence_basis") or "",
        "verification_method": item.get("verification_method") or "",
        "reported_value": item.get("reported_value") or "",
        "visible_computed_value": item.get("visible_computed_value") or "",
        "delta": item.get("delta") or "",
        "aggregation_caveat": item.get("aggregation_caveat") or "",
        "source_section_label": item.get("source_section_label") or "",
    }
    annotations: list[dict[str, str]] = []
    for anchor_id in anchor_ids:
        normalized_id = str(anchor_id).strip()
        if not normalized_id and anchor_level != "paper":
            continue
        annotation = {key: str(value) for key, value in base.items()}
        annotation["severity"] = severity
        annotation[target_key] = normalized_id or "paper"
        annotations.append(annotation)
    if not annotations and source != "findings":
        raise SystemExit(f"annotation #{idx} missing target id for `{anchor_level}` annotation")
    return annotations


def load_annotations(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "annotations" in payload:
            source = "annotations"
            items = payload.get("annotations", [])
        elif "findings" in payload:
            source = "findings"
            items = payload.get("findings", [])
        else:
            source = "annotations"
            items = []
    else:
        source = "annotations"
        items = payload
    if not isinstance(items, list):
        raise SystemExit("annotations JSON must be a list or an object with an `annotations` or `findings` list")
    annotations: list[dict[str, str]] = []
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise SystemExit(f"annotation #{idx} must be an object")
        annotations.extend(normalize_annotation_item(item, idx, source=source))
    return annotations


def normalize_finding_content(item: dict[str, object], idx: int) -> dict[str, str]:
    severity = str(item.get("severity", "major")).strip().lower()
    if severity not in SEVERITY_LABELS:
        severity = "major"
    issue_id = str(item.get("id") or item.get("issue_id") or f"F{idx}")
    return {
        "issue_id": issue_id,
        "severity": severity,
        "issue_type": str(item.get("issue_type") or item.get("type") or "prose"),
        "short": str(item.get("short") or item.get("short_comment") or item.get("one_line") or item.get("title") or item.get("diagnosis") or ""),
        "title": str(item.get("title") or item.get("one_line") or item.get("diagnosis") or "批注"),
        "problem": str(item.get("problem") or item.get("what") or item.get("diagnosis") or ""),
        "diagnosis": str(item.get("diagnosis") or item.get("problem") or item.get("what") or ""),
        "why": str(item.get("why") or item.get("reader_friction") or ""),
        "reader_friction": str(item.get("reader_friction") or item.get("why") or ""),
        "principle": str(item.get("principle") or item.get("writing_principle") or ""),
        "writing_principle": str(item.get("writing_principle") or item.get("principle") or ""),
        "task": str(item.get("task") or item.get("next_draft_task") or item.get("next_draft_task_or_question") or ""),
        "next_draft_task": str(item.get("next_draft_task") or item.get("task") or item.get("next_draft_task_or_question") or ""),
        "self_check": str(item.get("self_check") or item.get("next_draft_question") or item.get("revision_question") or ""),
        "next_draft_question": str(item.get("next_draft_question") or item.get("self_check") or item.get("revision_question") or ""),
        "severity_rationale": str(item.get("severity_rationale") or ""),
        "downgrade_condition": str(item.get("downgrade_condition") or ""),
        "confidence": str(item.get("confidence") or ""),
        "location": str(item.get("location") or ""),
        "snippet": str(item.get("snippet") or ""),
        "evidence_basis": str(item.get("evidence_basis") or ""),
        "verification_method": str(item.get("verification_method") or ""),
        "reported_value": str(item.get("reported_value") or ""),
        "visible_computed_value": str(item.get("visible_computed_value") or ""),
        "delta": str(item.get("delta") or ""),
        "aggregation_caveat": str(item.get("aggregation_caveat") or ""),
        "source_section_label": str(item.get("source_section_label") or ""),
    }


def load_findings(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    findings = payload.get("findings", []) if isinstance(payload, dict) else payload
    if not isinstance(findings, list):
        raise SystemExit("findings JSON must be a list or an object with a `findings` list")
    output: dict[str, dict[str, str]] = {}
    for idx, item in enumerate(findings, 1):
        if not isinstance(item, dict):
            raise SystemExit(f"finding #{idx} must be an object")
        finding_id = str(item.get("id") or item.get("issue_id") or "").strip()
        if not finding_id:
            raise SystemExit(f"finding #{idx} missing `id`")
        normalized = normalize_annotation_item({**item, "issue_id": finding_id}, idx, source="findings")
        if normalized:
            output[finding_id] = normalized[0]
        else:
            output[finding_id] = normalize_finding_content({**item, "issue_id": finding_id}, idx)
    return output


def load_findings_rows(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("findings", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("findings JSON must be a list or an object with a `findings` list")
    return [row for row in rows if isinstance(row, dict)]


def load_claim_rows(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("claims", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("claims JSON must be a list or an object with a `claims` list")
    return [row for row in rows if isinstance(row, dict)]


def load_optional_json(path: Path | None) -> object:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def issue_artifact_paths(issues_dir: Path | None) -> list[Path]:
    if issues_dir is None or not issues_dir.exists():
        return []
    paths = sorted(issues_dir.glob("*_issues.json"))
    return [path for path in paths if path.is_file()]


def issue_artifact_to_annotations(path: Path) -> list[dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"issue artifact `{path}` is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"issue artifact `{path}` must be an object")
    domain = str(payload.get("domain") or path.stem.replace("_issues", ""))
    issues = payload.get("issues", [])
    if not isinstance(issues, list):
        raise SystemExit(f"issue artifact `{path}` must contain an `issues` list")
    annotations: list[dict[str, str]] = []
    for idx, issue in enumerate(issues, 1):
        if not isinstance(issue, dict):
            raise SystemExit(f"issue artifact `{path}` issue #{idx} must be an object")
        local_id = str(issue.get("local_id") or issue.get("id") or issue.get("issue_id") or f"{domain[:1].upper()}{idx}")
        issue_id = f"{domain}:{local_id}"
        render_hint = issue.get("render_hint") if isinstance(issue.get("render_hint"), dict) else {}
        anchor = str(render_hint.get("anchor") or issue.get("primary_anchor") or issue.get("location") or "").strip()
        target_level = str(render_hint.get("target_level") or issue.get("target_level") or "").strip().lower()
        if not target_level:
            if anchor.startswith("s-"):
                target_level = "sentence"
            elif anchor.startswith("p-"):
                target_level = "paragraph"
            elif anchor and not anchor.startswith("page:"):
                target_level = "section"
            else:
                target_level = "paper"
        annotation: dict[str, object] = {
            "issue_id": issue_id,
            "severity": issue.get("severity") or "minor",
            "issue_type": issue.get("issue_type") or domain,
            "target_level": target_level,
            "short": issue.get("short") or issue.get("title") or issue.get("diagnosis") or "",
            "title": issue.get("title") or f"{domain} issue",
            "problem": issue.get("problem") or issue.get("diagnosis") or "",
            "diagnosis": issue.get("diagnosis") or issue.get("problem") or "",
            "why": issue.get("why") or issue.get("reader_friction") or "",
            "reader_friction": issue.get("reader_friction") or issue.get("why") or "",
            "principle": issue.get("principle") or issue.get("writing_principle") or "",
            "writing_principle": issue.get("writing_principle") or issue.get("principle") or "",
            "task": issue.get("recommendation") or issue.get("next_draft_task") or "",
            "next_draft_task": issue.get("next_draft_task") or issue.get("recommendation") or "",
            "self_check": issue.get("self_check") or "",
            "severity_rationale": issue.get("severity_rationale") or "",
            "downgrade_condition": issue.get("downgrade_condition") or "",
            "confidence": issue.get("confidence") or "",
            "evidence_basis": "; ".join(str(item) for item in issue.get("evidence_refs", []) if item),
            "verification_method": f"issue_artifact:{path.name}",
            "source_section_label": render_hint.get("display_group") or domain,
        }
        if target_level == "sentence":
            annotation["sentence_id"] = anchor
        elif target_level == "paragraph":
            annotation["paragraph_id"] = anchor
        elif target_level == "section":
            annotation["section_id"] = anchor
        else:
            annotation["paper_id"] = "paper"
            if anchor:
                annotation["location"] = anchor
        normalized = normalize_annotation_item(annotation, idx, source="annotations")
        if not normalized:
            continue
        for item in normalized:
            if target_level == "paper" and anchor.startswith("page:"):
                item["unanchored"] = "true"
                item["paper_id"] = ""
            annotations.append(item)
    return annotations


def load_issue_artifact_annotations(issues_dir: Path | None) -> list[dict[str, str]]:
    annotations: list[dict[str, str]] = []
    for path in issue_artifact_paths(issues_dir):
        annotations.extend(issue_artifact_to_annotations(path))
    return annotations


def merge_annotation_findings(
    annotations: list[dict[str, str]],
    findings_by_id: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    if not findings_by_id:
        return annotations
    merged: list[dict[str, str]] = []
    for annotation in annotations:
        issue_id = annotation.get("issue_id", "")
        finding = findings_by_id.get(issue_id)
        if not finding:
            merged.append(annotation)
            continue
        # Anchor-only annotations override target/card fields; full teaching content
        # comes from findings so it is emitted once by the reviewer.
        merged_item = {**finding, **annotation}
        for key in (
            "severity",
            "issue_type",
            "title",
            "problem",
            "diagnosis",
            "why",
            "reader_friction",
            "principle",
            "writing_principle",
            "self_check",
            "next_draft_question",
            "task",
            "next_draft_task",
            "severity_rationale",
            "downgrade_condition",
            "confidence",
            "evidence_basis",
            "verification_method",
        ):
            if not annotation.get(key) and finding.get(key):
                merged_item[key] = finding[key]
        merged.append(merged_item)
    return merged


def severity_from_text(value: str) -> str:
    text = value.strip().lower()
    for severity in SEVERITY_LABELS:
        if severity in text:
            return severity
    return "major"


def issue_type_from_text(*parts: str) -> str:
    text = " ".join(part.lower() for part in parts if part)
    cues = [
        ("numeric", ("number", "numeric", "table", "benchmark", "percentage", "percent", "数字", "数值", "表格", "均值")),
        ("layout", ("pdf", "layout", "figure", "caption", "visual", "prompt", "版式", "图", "表", "链接框")),
        ("citation", ("reference", "citation", "bibtex", "related work", "引用", "文献")),
        ("checklist", ("checklist", "neurips", "license", "human annotation", "伦理", "自评")),
        ("evaluation", ("baseline", "judge", "reward", "seed", "error bar", "评估", "实验")),
        ("claim", ("claim", "overclaim", "mechanism", "scope", "interpretation", "主张", "机制", "范围")),
        ("prose", ("grammar", "diction", "sentence", "paragraph", "cognitive", "术语", "句子", "段落")),
    ]
    for issue_type, keywords in cues:
        if any(keyword in text for keyword in keywords):
            return issue_type
    return "prose"


def looks_like_review_row(row: Tag) -> bool:
    cells = row.find_all(["td", "th"], recursive=False)
    if len(cells) < 3:
        return False
    if all(cell.name == "th" for cell in cells):
        return False
    return bool(row.get("data-severity") or row.select_one(".badge"))


def review_row_annotation(row: Tag, idx: int, section_id: str, section_label: str) -> dict[str, str] | None:
    if not looks_like_review_row(row):
        return None
    cells = row.find_all(["td", "th"], recursive=False)
    cell_texts = [normalized_text(cell) for cell in cells]
    if not any(cell_texts):
        return None
    severity = severity_from_text(str(row.get("data-severity", "")) or cell_texts[-1])
    location = cell_texts[0] if cell_texts else section_label
    dimension = cell_texts[1] if len(cell_texts) > 1 else section_label
    snippet = cell_texts[2] if len(cell_texts) > 2 else ""
    problem = cell_texts[3] if len(cell_texts) > 3 else "；".join(text for text in cell_texts[1:] if text)
    why = cell_texts[4] if len(cell_texts) > 4 else ""
    task = cell_texts[5] if len(cell_texts) > 5 else ""
    issue_id = f"R{idx}"
    title = f"{location} / {dimension}".strip(" /")
    return {
        "issue_id": issue_id,
        "severity": severity,
        "issue_type": issue_type_from_text(section_id, location, dimension, snippet, problem),
        "title": title or f"{section_label}批注",
        "location": location or section_label,
        "snippet": snippet,
        "problem": problem,
        "why": why,
        "task": task,
        "evidence_basis": "imported from existing HTML review report",
        "verification_method": f"review-html section #{section_id}",
        "source_section": section_id,
        "source_section_label": section_label,
    }


def review_article_annotation(article: Tag, idx: int, section_id: str, section_label: str) -> dict[str, str] | None:
    if "finding" not in article.get("class", []):
        return None
    severity = severity_from_text(str(article.get("data-severity", "")) or normalized_text(article.select_one(".badge") or article))
    title_node = article.select_one(".finding-title")
    title = normalized_text(title_node) if title_node else normalized_text(article.find(["h3", "h4"]) or article)
    if title_node:
        for badge in title_node.select(".badge"):
            badge.extract()
        title = normalized_text(title_node)
    paragraphs = [normalized_text(p) for p in article.find_all("p")]
    text = "\n".join(part for part in paragraphs if part) or normalized_text(article)
    fields: dict[str, str] = {}
    for paragraph in article.find_all("p", class_="field"):
        strong = paragraph.find("strong")
        if strong:
            key = strong.get_text(" ", strip=True).rstrip("：:")
            value = paragraph.get_text(" ", strip=True).replace(strong.get_text(" ", strip=True), "", 1).strip("：: ")
            fields[key] = value
    issue_id = article.get("id") or f"R{idx}"
    location = fields.get("位置", section_label)
    snippet = fields.get("片段", "")
    problem = fields.get("问题", text)
    why = fields.get("读者影响", fields.get("为什么影响读者", ""))
    task = fields.get("修改建议", "")
    evidence = fields.get("依据", "imported from existing HTML review report")
    return {
        "issue_id": str(issue_id),
        "severity": severity,
        "issue_type": issue_type_from_text(section_id, title, location, snippet, problem),
        "title": title or f"{section_label}批注",
        "location": location,
        "snippet": snippet,
        "problem": problem,
        "why": why,
        "task": task,
        "evidence_basis": evidence,
        "verification_method": f"review-html section #{section_id}",
        "source_section": section_id,
        "source_section_label": section_label,
    }


def load_review_html_annotations(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    annotations: list[dict[str, str]] = []
    idx = 1
    for section_id, section_label in REVIEW_IMPORT_SECTION_LABELS.items():
        section = soup.find(id=section_id)
        if section is None:
            continue
        for article in section.find_all("article", recursive=False):
            annotation = review_article_annotation(article, idx, section_id, section_label)
            if annotation is None:
                continue
            annotations.append(annotation)
            idx += 1
        for row in section.find_all("tr"):
            annotation = review_row_annotation(row, idx, section_id, section_label)
            if annotation is None:
                continue
            annotations.append(annotation)
            idx += 1
    return annotations


def slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or fallback


def compact_section_slug(value: str, fallback: str, max_length: int = 30) -> str:
    slug = slugify(value, fallback)
    if len(slug) <= max_length:
        return slug
    return slug[:max_length].rstrip("-") or fallback


def normalized_text(tag: Tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()


def is_layout_parameter_text(value: str) -> bool:
    text = normalized_text(BeautifulSoup(f"<span>{html.escape(value)}</span>", "html.parser").span)
    if not text:
        return False
    if text.lower().startswith("max width="):
        return True
    return bool(LAYOUT_PARAM_RE.fullmatch(text))


def add_class(tag: Tag, class_name: str) -> None:
    classes = tag.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    if class_name not in classes:
        classes.append(class_name)
    tag["class"] = classes


def cleanup_pandoc_artifacts(soup: BeautifulSoup) -> None:
    """Remove LaTeX layout parameters that pandoc renders as visible text."""

    for div in soup.find_all("div"):
        classes = div.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        if "wrapfigure" in classes:
            add_class(div, "paper-float")
            add_class(div, "paper-figure")
        if "wraptable" in classes:
            add_class(div, "paper-float")
            add_class(div, "paper-table")
        if "table*" in classes or "table" in classes:
            add_class(div, "paper-table")

    for p in list(soup.find_all("p")):
        parent_classes: list[str] = []
        if isinstance(p.parent, Tag):
            parent_classes = p.parent.get("class", [])
            if isinstance(parent_classes, str):
                parent_classes = parent_classes.split()
        if any(name in parent_classes for name in ("wrapfigure", "wraptable")):
            for span in list(p.find_all("span", recursive=False)):
                if is_layout_parameter_text(span.get_text(" ", strip=True)):
                    span.decompose()
            if not normalized_text(p) and p.find(["embed", "img", "svg"]):
                p.unwrap()
                continue
            if not normalized_text(p):
                p.decompose()
                continue
        if normalized_text(p).lower().startswith("max width="):
            p.decompose()

    for div in list(soup.select("div.adjustbox")):
        div.unwrap()

    for anchor in soup.select("pre a[aria-hidden='true']"):
        anchor.decompose()

    for figure in soup.find_all("figure"):
        if figure.select_one(".tcolorbox, .sourceCode, pre.sourceCode"):
            add_class(figure, "prompt-figure")
            for code_block in figure.select(".tcolorbox, .sourceCode, pre"):
                add_class(code_block, "prompt-block")


def strip_latex_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        escaped = False
        kept: list[str] = []
        for char in line:
            if char == "%" and not escaped:
                break
            kept.append(char)
            escaped = char == "\\" and not escaped
        lines.append("".join(kept))
    return "\n".join(lines)


def resolve_latex_path(base_dir: Path, raw_path: str) -> Path | None:
    candidate = (base_dir / raw_path).resolve()
    paths = [candidate]
    if candidate.suffix == "":
        paths.append(candidate.with_suffix(".tex"))
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def read_latex_tree(path: Path, seen: set[Path] | None = None, root_dir: Path | None = None) -> str:
    seen = seen or set()
    path = path.resolve()
    root_dir = (root_dir or path.parent).resolve()
    if path in seen:
        return ""
    seen.add(path)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")

    def replace_input(match: re.Match[str]) -> str:
        raw_path = match.group(1).strip()
        child = resolve_latex_path(path.parent, raw_path) or resolve_latex_path(root_dir, raw_path)
        if child is None:
            return match.group(0)
        return "\n" + read_latex_tree(child, seen, root_dir) + "\n"

    return LATEX_INPUT_RE.sub(replace_input, text)


def normalize_asset_path(raw_path: str) -> str:
    value = raw_path.strip()
    if not Path(value).suffix:
        value = f"{value}.pdf"
    return value.replace("\\", "/")


def latex_label_units(tex_path: Path) -> list[dict[str, str]]:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    units: list[dict[str, str]] = []
    for match in LATEX_ENV_RE.finditer(expanded):
        env = match.group(1)
        block = match.group(0)
        label_matches = list(LATEX_LABEL_RE.finditer(block))
        if not label_matches:
            continue
        graphics = [(graphic.start(), normalize_asset_path(graphic.group(1))) for graphic in LATEX_GRAPHICS_RE.finditer(block)]
        if "table" in env:
            kind = "table"
        elif "algorithm" in env:
            kind = "algorithm"
        else:
            kind = "figure"
        for label_match in label_matches:
            preceding_assets = [asset for offset, asset in graphics if offset < label_match.start()]
            following_assets = [asset for offset, asset in graphics if offset >= label_match.start()]
            asset = preceding_assets[-1] if preceding_assets else following_assets[0] if following_assets else ""
            label = label_match.group(1)
            units.append({"kind": kind, "label": label, "asset": asset})
    return units


def same_asset_path(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        return value.strip().replace("\\", "/").removeprefix("./")

    return normalize(left) == normalize(right)


def find_asset_image(soup: BeautifulSoup, asset: str) -> Tag | None:
    if not asset:
        return None
    for image in soup.find_all("img"):
        if same_asset_path(str(image.get("data-source-pdf", "")), asset):
            return image
        if same_asset_path(str(image.get("src", "")), asset):
            return image
    return None


def add_label_anchor(soup: BeautifulSoup, target: Tag, label: str) -> Tag:
    anchor = soup.new_tag("span")
    anchor["id"] = label
    anchor["class"] = "paper-latex-label-anchor"
    anchor["aria-hidden"] = "true"
    target.insert(0, anchor)
    return anchor


def node_or_ancestor_has_id(node: Tag) -> bool:
    current: Tag | None = node
    while current is not None:
        if current.get("id"):
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


def table_label_targets(soup: BeautifulSoup) -> list[Tag]:
    targets: list[Tag] = []
    for container in soup.find_all(["div", "figure"]):
        classes = container.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        if any(class_name in {"table", "table*"} or class_name.startswith("table") for class_name in classes):
            if container not in targets:
                targets.append(container)
    for table in soup.find_all("table"):
        current: Tag | None = table
        target = table
        while current is not None:
            classes = current.get("class", [])
            if isinstance(classes, str):
                classes = classes.split()
            if current.name in {"figure", "div"} and any("table" in class_name for class_name in classes):
                target = current
                break
            current = current.parent if isinstance(current.parent, Tag) else None
        if target not in targets:
            targets.append(target)
    return targets


def restore_latex_labels(soup: BeautifulSoup, tex_path: Path) -> int:
    """Restore figure/table ids that pandoc drops for wrap/adjustbox layouts."""

    units = latex_label_units(tex_path)
    existing_ids = {str(tag.get("id")) for tag in soup.find_all(id=True)}
    restored = 0

    for unit in units:
        if unit["kind"] != "figure" or not unit.get("asset") or unit["label"] in existing_ids:
            continue
        image = find_asset_image(soup, unit["asset"])
        if image is None:
            continue
        target = image.find_parent(["figure", "div"]) or image
        if not node_or_ancestor_has_id(target):
            target["id"] = unit["label"]
        else:
            add_label_anchor(soup, target, unit["label"])
        existing_ids.add(unit["label"])
        restored += 1

    table_units = [unit for unit in units if unit["kind"] == "table"]
    for unit, target in zip(table_units, table_label_targets(soup)):
        if unit["label"] in existing_ids:
            continue
        if not node_or_ancestor_has_id(target):
            target["id"] = unit["label"]
        else:
            add_label_anchor(soup, target, unit["label"])
        existing_ids.add(unit["label"])
        restored += 1

    for unit in units:
        label = unit["label"]
        if label in existing_ids:
            continue
        link = soup.select_one(f'a[data-reference="{label}"], a[href="#{label}"]')
        anchor_parent = link.find_parent(["p", "li", "figcaption", "caption", "section", "div"]) if link else None
        if anchor_parent is None:
            anchor_parent = soup.body or soup
        add_label_anchor(soup, anchor_parent, label)
        existing_ids.add(label)
        restored += 1

    return restored


def render_pdf_first_page(pdf_path: Path, output_prefix: Path) -> Path | None:
    if shutil.which("pdftoppm") is None or not pdf_path.exists():
        return None
    command = ["pdftoppm", "-png", "-singlefile", "-r", PDF_ASSET_DPI, str(pdf_path), str(output_prefix)]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None
    png_path = output_prefix.with_suffix(".png")
    if not png_path.exists():
        return None
    return png_path


def pdf_embed_to_data_uri(pdf_path: Path) -> str | None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = Path(tmpdir) / "page"
        png_path = render_pdf_first_page(pdf_path, prefix)
        if png_path is None:
            return None
        encoded = base64.b64encode(png_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"


def safe_pdf_asset_name(src: str, pdf_path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(src).stem).strip(".-") or "asset"
    digest_source = f"{src}\n{pdf_path}".encode("utf-8", errors="ignore")
    digest = hashlib.sha256(digest_source).hexdigest()[:10]
    return f"{stem}-{digest}.png"


def html_asset_src(asset_path: Path, html_dir: Path, *, absolute: bool = False) -> str:
    if absolute:
        return str(asset_path).replace(os.sep, "/")
    try:
        value = os.path.relpath(asset_path, html_dir)
    except ValueError:
        value = str(asset_path)
    return value.replace(os.sep, "/")


def pdf_embed_to_png_asset(pdf_path: Path, output_png_path: Path) -> Path | None:
    with tempfile.TemporaryDirectory() as tmpdir:
        rendered_png = render_pdf_first_page(pdf_path, Path(tmpdir) / "page")
        if rendered_png is None:
            return None
        output_png_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rendered_png, output_png_path)
        return output_png_path


def rasterize_pdf_assets(
    soup: BeautifulSoup,
    tex_dir: Path,
    *,
    asset_dir: Path,
    html_dir: Path,
    inline_images: bool = False,
    absolute_asset_paths: bool = False,
) -> int:
    """Rasterize local PDF embeds while keeping image bytes out of HTML by default."""

    converted = 0
    for embed in list(soup.find_all("embed")):
        src = str(embed.get("src", ""))
        if not src.lower().endswith(".pdf") or src.startswith(("data:", "http://", "https://")):
            continue
        pdf_path = (tex_dir / src).resolve()
        if inline_images:
            rendered_src = pdf_embed_to_data_uri(pdf_path)
        else:
            png_path = pdf_embed_to_png_asset(pdf_path, asset_dir / safe_pdf_asset_name(src, pdf_path))
            rendered_src = html_asset_src(png_path, html_dir, absolute=absolute_asset_paths) if png_path is not None else None
        if rendered_src is None:
            add_class(embed, "paper-pdf-embed")
            continue
        img = soup.new_tag("img")
        img["src"] = rendered_src
        img["alt"] = f"Rendered PDF asset: {Path(src).name}"
        img["class"] = "paper-asset-image"
        img["data-source-pdf"] = src
        embed.replace_with(img)
        converted += 1
    return converted


def inline_pdf_assets(soup: BeautifulSoup, tex_dir: Path) -> int:
    """Backward-compatible self-contained PDF image conversion."""

    return rasterize_pdf_assets(soup, tex_dir, asset_dir=Path(), html_dir=Path(), inline_images=True)


def ensure_references_heading(soup: BeautifulSoup) -> None:
    refs = soup.find(id="refs")
    if refs is None:
        return
    previous = refs.find_previous_sibling()
    while previous is not None and isinstance(previous, Tag) and not normalized_text(previous):
        previous = previous.find_previous_sibling()
    if isinstance(previous, Tag) and previous.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        if "reference" in previous.get_text(" ", strip=True).lower():
            return
    heading = soup.new_tag("h1")
    heading["id"] = "references"
    heading.string = "References"
    refs.insert_before(heading)


def normalize_for_match(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"[“”\"'`‘’]", "", text)
    text = re.sub(r"[\s\u00a0]+", " ", text)
    text = re.sub(r"^[.。,:;，；\s]+|[.。,:;，；\s]+$", "", text)
    return text.lower()


def snippet_candidates(annotation: dict[str, str]) -> list[str]:
    raw_values = [
        annotation.get("snippet", ""),
        annotation.get("problem", ""),
        annotation.get("title", ""),
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        for value in re.findall(r"[“\"]([^“”\"]{8,220})[”\"]", raw_value):
            normalized = normalize_for_match(value)
            if len(normalized) >= 8 and normalized not in seen:
                candidates.append(normalized)
                seen.add(normalized)
        normalized = normalize_for_match(raw_value)
        if 8 <= len(normalized) <= 220 and normalized not in seen:
            candidates.append(normalized)
            seen.add(normalized)
    return candidates


def issue_label_text(annotation: dict[str, str], count: int = 1) -> str:
    severity = annotation.get("severity", "major")
    issue_type = annotation.get("issue_type", "prose") or "prose"
    short = annotation.get("short", "").strip() or annotation.get("title", "").strip()
    if short and len(short) <= 28 and count == 1:
        return short
    if count > 1:
        return f"{SEVERITY_SHORT_LABELS.get(severity, severity.title())} · {count} issues"
    return f"{SEVERITY_SHORT_LABELS.get(severity, severity.title())} · {issue_type}"


def annotation_target_id(annotation: dict[str, str]) -> str:
    level = annotation.get("target_level", "sentence")
    if level == "paragraph":
        return annotation.get("paragraph_id", "")
    if level == "section":
        return annotation.get("section_id", "")
    if level == "paper":
        return annotation.get("paper_id", "paper") or "paper"
    return annotation.get("sentence_id", "")


def card_target_attr(level: str) -> str:
    return f"data-target-{level}"


def card_id_for(level: str, target_id: str, idx: int) -> str:
    if level == "sentence":
        return f"ann-{target_id}-{idx}"
    safe_id = re.sub(r"[^A-Za-z0-9_.:-]+", "-", target_id or level).strip("-") or level
    return f"ann-{level}-{safe_id}-{idx}"


def annotate_anchor_node(target: Tag, annotations: list[dict[str, str]], *, level: str, soup: BeautifulSoup) -> None:
    severity = strongest_severity([item.get("severity", "major") for item in annotations])
    issue_types = ordered_unique([item.get("issue_type", "prose") or "prose" for item in annotations])
    issue_ids = ordered_unique([item.get("issue_id", "") for item in annotations])
    target_id = annotation_target_id(annotations[0])
    classes = target.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    marker_class = f"has-{level}-annotation"
    if level == "sentence" and "has-annotation" not in classes:
        classes.append("has-annotation")
    if marker_class not in classes:
        classes.append(marker_class)
    if level == "paragraph" and "paper-paragraph" not in classes:
        classes.append("paper-paragraph")
    target["class"] = classes
    target["data-has-issue"] = "true"
    target["data-severity"] = severity
    target["data-issue-type"] = issue_types[0] if len(issue_types) == 1 else "multiple"
    target["data-issue-ids"] = " ".join(issue_ids)
    target["aria-describedby"] = " ".join(card_id_for(level, target_id, idx) for idx, _ in enumerate(annotations, 1))
    if level in {"sentence", "paragraph"} and target_id and not target.get("id"):
        target["id"] = target_id
    if level != "paper":
        target["tabindex"] = "0"
        target["role"] = "button"
        target["onclick"] = f"AriadnePaperReaderOpenAnnotation('{level}', this.getAttribute('data-{level}-id') || this.id)"
        target["onkeydown"] = (
            "if(event.key==='Enter'||event.key===' '){event.preventDefault();"
            f"AriadnePaperReaderOpenAnnotation('{level}', this.getAttribute('data-{level}-id') || this.id);}}"
        )
    label = issue_label_text(annotations[0], len(annotations))
    if level == "sentence":
        target["data-inline-label"] = label
        return
    bubble = soup.new_tag("button")
    bubble["type"] = "button"
    bubble["class"] = f"annotation-bubble {ANCHOR_LEVEL_CLASS.get(level, level)}"
    bubble["data-anchor-level"] = level
    bubble[f"data-{level}-id"] = target_id
    bubble["data-severity"] = severity
    bubble["data-issue-type"] = issue_types[0] if len(issue_types) == 1 else "multiple"
    bubble["data-issue-ids"] = " ".join(issue_ids)
    bubble["aria-describedby"] = target.get("aria-describedby", "")
    bubble["onclick"] = f"AriadnePaperReaderOpenAnnotation('{level}', this.getAttribute('data-{level}-id'))"
    bubble.string = label
    if level == "section":
        target.append(NavigableString(" "))
        target.append(bubble)
    elif level == "paragraph":
        target.insert(0, bubble)
    else:
        target.append(bubble)


def ensure_paper_overview(soup: BeautifulSoup, annotations: list[dict[str, str]]) -> Tag | None:
    if not annotations:
        return None
    body = soup.body or soup
    overview = soup.new_tag("aside")
    overview["id"] = "paper-overview-annotations"
    overview["class"] = "paper-overview-annotations has-paper-annotation"
    overview["data-paper-id"] = "paper"
    overview["data-has-issue"] = "true"
    overview["data-severity"] = strongest_severity([item.get("severity", "major") for item in annotations])
    overview["data-issue-type"] = "paper"
    overview["data-issue-ids"] = " ".join(ordered_unique([item.get("issue_id", "") for item in annotations]))
    overview["aria-describedby"] = " ".join(card_id_for("paper", "paper", idx) for idx, _ in enumerate(annotations, 1))
    title = soup.new_tag("strong")
    title.string = "全文结构批注"
    overview.append(title)
    for idx, annotation in enumerate(annotations, 1):
        button = soup.new_tag("button")
        button["type"] = "button"
        button["class"] = "annotation-bubble paper"
        button["data-anchor-level"] = "paper"
        button["data-paper-id"] = "paper"
        button["data-severity"] = annotation.get("severity", "major")
        button["data-issue-type"] = annotation.get("issue_type", "paper")
        button["data-issue-ids"] = annotation.get("issue_id", f"A{idx}")
        button["onclick"] = "AriadnePaperReaderOpenAnnotation('paper', 'paper')"
        button.string = issue_label_text(annotation, len(annotations) if len(annotations) > 1 else 1)
        overview.append(button)
    first = body.find(["header", "h1", "p", "section", "article", "div"])
    if first is not None:
        first.insert_before(overview)
    else:
        body.append(overview)
    return overview


def assign_sentence_targets(soup: BeautifulSoup, annotations: list[dict[str, str]]) -> list[dict[str, str]]:
    sentence_nodes = list(soup.select(".paper-sentence[data-sentence-id]"))
    valid_sentence_ids = {str(node.get("data-sentence-id", "")) for node in sentence_nodes}
    valid_paragraph_ids = {str(node.get("data-paragraph-id", "")) for node in soup.select("[data-paragraph-id]")}
    valid_section_ids = {str(node.get("id", "")) for node in soup.select("h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]")}
    sentence_index: list[tuple[str, str]] = []
    for node in sentence_nodes:
        sentence_id = str(node.get("data-sentence-id", ""))
        text = normalize_for_match(node.get_text(" ", strip=True))
        if sentence_id and text:
            sentence_index.append((sentence_id, text))

    assigned: list[dict[str, str]] = []
    for annotation in annotations:
        level = annotation.get("target_level", "sentence")
        if level == "paper":
            assigned.append(annotation)
            continue
        existing_sentence_id = annotation.get("sentence_id", "")
        existing_paragraph_id = annotation.get("paragraph_id", "")
        existing_section_id = annotation.get("section_id", "")
        if level == "sentence" and existing_sentence_id and existing_sentence_id in valid_sentence_ids:
            assigned.append(annotation)
            continue
        if level == "paragraph" and existing_paragraph_id and existing_paragraph_id in valid_paragraph_ids:
            assigned.append(annotation)
            continue
        if level == "section" and existing_section_id and existing_section_id in valid_section_ids:
            assigned.append(annotation)
            continue
        if level != "sentence":
            assigned.append(annotation)
            continue
        target_id = ""
        for candidate in snippet_candidates(annotation):
            for sentence_id, sentence_text in sentence_index:
                if candidate in sentence_text or sentence_text in candidate:
                    target_id = sentence_id
                    break
            if target_id:
                break
        annotation = dict(annotation)
        if target_id:
            annotation["sentence_id"] = target_id
        assigned.append(annotation)
    return assigned


def apply_annotations(soup: BeautifulSoup, annotations: list[dict[str, str]]) -> list[dict[str, str]]:
    applied: list[dict[str, str]] = []
    target_groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for idx, annotation in enumerate(annotations, 1):
        level = annotation.get("target_level", "sentence")
        target_id = annotation_target_id(annotation)
        if not target_id:
            annotation = dict(annotation)
            annotation["card_id"] = f"ann-unanchored-{idx}"
            annotation["target_level"] = level
            annotation["unanchored"] = "true"
            applied.append(annotation)
            continue
        if level == "sentence":
            target = soup.select_one(f'.paper-sentence[data-sentence-id="{target_id}"]')
        elif level == "paragraph":
            target = soup.select_one(f'[data-paragraph-id="{target_id}"]')
        elif level == "section":
            target = soup.find(id=target_id)
        elif level == "paper":
            target = soup.body or soup
        else:
            target = None
        if target is None:
            annotation = dict(annotation)
            annotation["card_id"] = f"ann-unanchored-{idx}"
            annotation["target_level"] = level
            annotation["unanchored"] = "true"
            annotation["missing_target"] = target_id
            applied.append(annotation)
            continue
        annotation = dict(annotation)
        target_groups.setdefault((level, target_id), []).append(annotation)
        applied.append(annotation)

    paper_annotations: list[dict[str, str]] = []
    for (level, target_id), target_annotations in target_groups.items():
        if level == "sentence":
            target = soup.select_one(f'.paper-sentence[data-sentence-id="{target_id}"]')
        elif level == "paragraph":
            target = soup.select_one(f'[data-paragraph-id="{target_id}"]')
        elif level == "section":
            target = soup.find(id=target_id)
        elif level == "paper":
            paper_annotations.extend(target_annotations)
            target = None
        else:
            target = None
        if target is None:
            continue
        annotate_anchor_node(target, target_annotations, level=level, soup=soup)
        for card_idx, target_annotation in enumerate(target_annotations, 1):
            target_annotation.setdefault("issue_id", f"A{card_idx}")
            target_annotation.setdefault("issue_type", "prose")
            target_annotation["card_id"] = card_id_for(level, target_id, card_idx)
    if paper_annotations:
        ensure_paper_overview(soup, paper_annotations)
        for card_idx, target_annotation in enumerate(paper_annotations, 1):
            target_annotation.setdefault("issue_id", f"A{card_idx}")
            target_annotation.setdefault("issue_type", "paper")
            target_annotation["card_id"] = card_id_for("paper", "paper", card_idx)
            target_annotation["paper_id"] = "paper"
    return applied


def is_inside_skipped_tag(node: Tag) -> bool:
    parent = node
    while parent is not None:
        if isinstance(parent, Tag) and parent.name in SKIP_PARENT_TAGS:
            return True
        parent = parent.parent
    return False


def tag_text_ends_sentence(tag: Tag) -> bool:
    return normalized_text(tag).endswith(SENTENCE_ENDINGS)


def child_starts_new_sentence(child: object | None) -> bool:
    if child is None:
        return False
    text = str(child) if isinstance(child, NavigableString) else normalized_text(child) if isinstance(child, Tag) else ""
    text = text.lstrip()
    return bool(text and re.match(r"[A-Z0-9\"'“‘(]", text))


def wrap_sentence_container(node: Tag, soup: BeautifulSoup, section_slug: str, paragraph_index: int) -> int:
    counters = {"sentence": 0}
    current: Tag | None = None

    def ensure_sentence() -> Tag:
        nonlocal current
        if current is None:
            counters["sentence"] += 1
            sentence_id = f"s-{section_slug}-p{paragraph_index:03d}-s{counters['sentence']:03d}"
            current = soup.new_tag("span")
            current["class"] = "paper-sentence"
            current["data-sentence-id"] = sentence_id
            node.append(current)
        return current

    def finish_sentence() -> None:
        nonlocal current
        if current is not None and not current.get_text(" ", strip=True) and not current.find(True):
            current.decompose()
            counters["sentence"] -= 1
        current = None

    children = list(node.contents)
    for child in children:
        child.extract()

    for idx, child in enumerate(children):
        next_child = children[idx + 1] if idx + 1 < len(children) else None
        if isinstance(child, NavigableString):
            text = str(child)
            start = 0
            for match in SENTENCE_BOUNDARY_RE.finditer(text):
                sentence_part = text[start:match.start(1)]
                if sentence_part:
                    ensure_sentence().append(NavigableString(sentence_part))
                finish_sentence()
                node.append(NavigableString(match.group(1)))
                start = match.end(1)
            remainder = text[start:]
            if remainder:
                if remainder.strip():
                    ensure_sentence().append(NavigableString(remainder))
                else:
                    if current is None:
                        node.append(NavigableString(remainder))
                    else:
                        current.append(NavigableString(remainder))
            continue
        if isinstance(child, Tag) and child.name in BLOCK_CHILD_TAGS:
            finish_sentence()
            node.append(child)
            continue
        ensure_sentence().append(child)
        if isinstance(child, Tag) and tag_text_ends_sentence(child) and child_starts_new_sentence(next_child):
            finish_sentence()

    finish_sentence()
    return counters["sentence"]


def wrap_sentences(soup: BeautifulSoup) -> int:
    section_slug = "front"
    paragraph_index = 0
    total_sentences = 0
    for node in list(soup.body.descendants if soup.body else soup.descendants):
        if not isinstance(node, Tag):
            continue
        if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            section_slug = compact_section_slug(node.get("id") or node.get_text(" ", strip=True), f"section-{paragraph_index}")
            paragraph_index = 0
        if node.name not in SENTENCE_CONTAINER_TAGS or is_inside_skipped_tag(node):
            continue
        paragraph_index += 1
        if node.name in {"p", "li", "figcaption", "caption"} and not node.get("data-paragraph-id"):
            node["data-paragraph-id"] = f"p-{section_slug}-{paragraph_index:03d}"
        total_sentences += wrap_sentence_container(node, soup, section_slug, paragraph_index)
    return total_sentences


def body_inner_html(soup: BeautifulSoup) -> str:
    if soup.body is None:
        return str(soup)
    return "\n".join(str(child) for child in soup.body.children)


def source_artifact_shell(title: str, source_html: str) -> str:
    title_html = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Ariadne source paper HTML - {title_html}</title>
</head>
<body>
{source_html}
</body>
</html>
"""


def is_source_artifact_shell(soup: BeautifulSoup) -> bool:
    title = soup.find("title")
    if not title:
        return False
    return "Ariadne source paper HTML" in title.get_text(" ", strip=True)


def prepare_source_soup(
    tex_path: Path,
    raw_html_path: Path,
    *,
    output_path: Path,
    asset_dir: Path,
    inline_images: bool,
    reuse_raw_html: bool,
) -> tuple[BeautifulSoup, str, int]:
    if reuse_raw_html:
        if not raw_html_path.exists():
            raise SystemExit(f"--reuse-raw-html requires an existing --raw-html file: {raw_html_path}")
        soup = BeautifulSoup(raw_html_path.read_text(encoding="utf-8"), "lxml")
        title = extract_title(soup, tex_path)
        sentence_count = len(soup.select(".paper-sentence[data-sentence-id]"))
        if sentence_count == 0:
            sentence_count = wrap_sentences(soup)
            title = extract_title(soup, tex_path)
            raw_html_path.write_text(source_artifact_shell(title, body_inner_html(soup)), encoding="utf-8")
        return soup, title, sentence_count

    run_pandoc(tex_path, raw_html_path)
    soup = BeautifulSoup(raw_html_path.read_text(encoding="utf-8"), "lxml")
    cleanup_pandoc_artifacts(soup)
    rasterize_pdf_assets(
        soup,
        tex_path.parent,
        asset_dir=asset_dir,
        html_dir=output_path.parent,
        inline_images=inline_images,
        absolute_asset_paths=output_path.parent != raw_html_path.parent,
    )
    restore_latex_labels(soup, tex_path)
    ensure_references_heading(soup)
    title = extract_title(soup, tex_path)
    sentence_count = wrap_sentences(soup)
    raw_html_path.write_text(source_artifact_shell(title, body_inner_html(soup)), encoding="utf-8")
    return soup, title, sentence_count


GENERIC_SEVERITY_RATIONALES = {"blocker", "major", "minor", "polish"}
MECHANICAL_EVIDENCE_CUES = (
    "source-derived paper-reader",
    "data-sentence-id",
    "data-paragraph-id",
    "section-paragraph-sentence",
    "generated by render_paper_html.py",
    "sentence span generated",
    "paragraph id generated",
    "heading id generated",
    "review-html section",
    "imported from existing html review report",
)
MEANINGFUL_EVIDENCE_TYPES = {"numeric", "math", "layout", "citation", "source", "submission"}
MEANINGFUL_EVIDENCE_CUES = (
    "pdf page",
    "table",
    "figure",
    "caption",
    "human",
    "audit",
    "computed",
    "recomputed",
    "reported",
    "visible",
    "bib",
    "reference",
    "checklist",
    "source line",
)


def informative_severity_rationale(value: str, severity: str) -> str:
    text = value.strip()
    if not text:
        return ""
    normalized = text.lower().strip(" .:;")
    if normalized in GENERIC_SEVERITY_RATIONALES or normalized == severity:
        return ""
    return text


def meaningful_evidence_text(item: dict[str, str]) -> str:
    evidence_basis = item.get("evidence_basis", "").strip()
    verification_method = item.get("verification_method", "").strip()
    text = "；".join(part for part in (evidence_basis, verification_method) if part)
    if not text:
        return ""
    lowered = text.lower()
    issue_type = item.get("issue_type", "prose")
    has_meaningful_type = issue_type in MEANINGFUL_EVIDENCE_TYPES
    has_meaningful_cue = any(cue in lowered for cue in MEANINGFUL_EVIDENCE_CUES)
    is_mechanical = any(cue in lowered for cue in MECHANICAL_EVIDENCE_CUES)
    if is_mechanical:
        return ""
    if has_meaningful_type and has_meaningful_cue:
        return text
    return ""


def render_annotation_cards(annotations: list[dict[str, str]]) -> str:
    if not annotations:
        return '<p class="empty-state">尚未生成批注。下一步应让审阅逻辑只添加 <code>has-annotation</code> 属性和 annotation cards，不改写左侧论文正文。</p>'
    cards: list[str] = [
        '<p class="annotation-empty-state" data-annotation-empty>点击左侧带下划线的句子，这里会显示对应批注意见。</p>'
    ]
    unanchored_cards: list[str] = []
    for idx, item in enumerate(annotations, 1):
        severity = item.get("severity", "major")
        badge = SEVERITY_LABELS.get(severity, severity.title())
        short_badge = SEVERITY_SHORT_LABELS.get(severity, severity.title())
        card_id = html.escape(item.get("card_id", f"annotation-{idx}"))
        target_level = item.get("target_level", "sentence")
        target_id_raw = annotation_target_id(item)
        sentence_id = html.escape(item.get("sentence_id", ""))
        target_id = html.escape(target_id_raw)
        level_label = ANCHOR_LEVEL_LABELS.get(target_level, target_level)
        issue_id = html.escape(item.get("issue_id", f"A{idx}"))
        issue_type = html.escape(item.get("issue_type", "prose"))
        title = html.escape(item.get("title", "句子问题"))
        problem = html.escape(item.get("problem", item.get("what", "")))
        why = html.escape(item.get("why", ""))
        principle = html.escape(item.get("principle", ""))
        self_check = html.escape(
            item.get("self_check")
            or item.get("next_draft_question")
            or item.get("revision_question")
            or item.get("task", item.get("next_draft_task", ""))
        )
        severity_rationale = html.escape(informative_severity_rationale(item.get("severity_rationale", ""), severity))
        evidence_text = html.escape(meaningful_evidence_text(item))
        confidence = html.escape(item.get("confidence", ""))
        downgrade_condition = html.escape(item.get("downgrade_condition", ""))
        reported_value = html.escape(item.get("reported_value", ""))
        visible_computed_value = html.escape(item.get("visible_computed_value", ""))
        delta = html.escape(item.get("delta", ""))
        aggregation_caveat = html.escape(item.get("aggregation_caveat", ""))
        source_section_label = html.escape(item.get("source_section_label", ""))
        unanchored = item.get("unanchored") == "true" or not target_id_raw
        card_attrs = [
            f'id="{card_id}"',
            f'class="annotation-card{" is-unanchored" if unanchored else ""}"',
            f'data-issue-ids="{issue_id}"',
            f'data-severity="{severity}"',
            f'data-issue-type="{issue_type}"',
            f'data-target-level="{target_level}"',
        ]
        if unanchored:
            card_attrs.append('data-unanchored="true"')
        else:
            if target_level == "sentence":
                card_attrs.append(f'data-target-sentence="{sentence_id}"')
            else:
                card_attrs.append(f'{card_target_attr(target_level)}="{target_id}"')
            card_attrs.append("hidden")
        href_target = "paper-overview-annotations" if target_level == "paper" else target_id
        pointer = (
            f'<p class="annotation-pointer"><a href="#{href_target}" data-scroll-level="{target_level}" data-scroll-target="{target_id}" aria-label="回到被批注的{level_label}">指向{level_label}</a></p>'
            if not unanchored
            else '<p class="annotation-pointer annotation-unanchored">未定位到唯一原句，保留为全局/版式批注</p>'
        )
        numeric_details = ""
        if reported_value or visible_computed_value or delta or aggregation_caveat:
            numeric_details = f"""
            <dt>数值核查</dt>
            <dd>
              <ul class="annotation-sublist">
                {f"<li>表中数值：{reported_value}</li>" if reported_value else ""}
                {f"<li>可见复算值：{visible_computed_value}</li>" if visible_computed_value else ""}
                {f"<li>差值：{delta}</li>" if delta else ""}
                {f"<li>口径说明：{aggregation_caveat}</li>" if aggregation_caveat else ""}
              </ul>
            </dd>"""
        rendered_card = (
            f"""
        <article {' '.join(card_attrs)}>
          <p class="annotation-meta"><span class="badge {severity}">{badge}</span><span>{issue_type}</span><span>{issue_id}</span></p>
          <h3>{title}</h3>
          {pointer}
          <dl>
            {f"<dt>来源栏目</dt><dd>{source_section_label}</dd>" if source_section_label else ""}
            <dt>问题是什么</dt><dd>{problem or "未填写"}</dd>
            <dt>为什么有问题</dt><dd>{why or "未填写"}</dd>
            <dt>违反原则</dt><dd>{principle or "未填写"}</dd>
            {f"<dt>严重度理由</dt><dd>{severity_rationale}</dd>" if severity_rationale else ""}
            {f"<dt>置信度</dt><dd>{confidence}</dd>" if confidence and severity_rationale else ""}
            {f"<dt>核查依据</dt><dd>{evidence_text}</dd>" if evidence_text else ""}
            {numeric_details}
            {f"<dt>降级条件</dt><dd>{downgrade_condition}</dd>" if downgrade_condition else ""}
            <dt>自改问题</dt><dd>{self_check or "未填写"}</dd>
          </dl>
        </article>"""
        )
        if unanchored:
            unanchored_cards.append(rendered_card)
        else:
            cards.append(rendered_card)
    cards.append(
        """
        <div class="annotation-nav" aria-label="Annotation navigation">
          <button type="button" data-prev-annotation>上一条</button>
          <button type="button" data-next-annotation>下一条</button>
        </div>"""
    )
    if unanchored_cards:
        cards.append(
            f"""
        <details class="unanchored-drawer">
          <summary>未定位到具体句子的批注（{len(unanchored_cards)}）</summary>
          {''.join(unanchored_cards)}
        </details>"""
        )
    return "\n".join(cards)


def render_finding_anchor_index(annotations: list[dict[str, str]]) -> str:
    issue_ids = ordered_unique([item.get("issue_id", "") for item in annotations])
    if not issue_ids:
        return ""
    anchors = "".join(f'<span id="{html.escape(issue_id)}"></span>' for issue_id in issue_ids)
    return f'<div id="finding-anchor-index" hidden aria-hidden="true">{anchors}</div>'


def severity_key(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in SEVERITY_LABELS else "major"


def severity_badge(value: object) -> str:
    key = severity_key(value)
    return f'<span class="badge {key}">{html.escape(SEVERITY_LABELS[key])}</span>'


def finding_id_link(finding_id: object) -> str:
    text = str(finding_id or "").strip()
    if not text:
        return ""
    return f'<a class="finding-link" href="#{html.escape(text)}">{html.escape(text)}</a>'


def joined_links(values: object) -> str:
    if isinstance(values, list):
        ids = [str(item).strip() for item in values if str(item).strip()]
    else:
        ids = [str(values).strip()] if str(values or "").strip() else []
    return ", ".join(finding_id_link(item) for item in ids)


def display_text(value: object, *, fallback: str = "", max_chars: int = 480) -> str:
    if isinstance(value, list):
        text = "; ".join(display_text(item, max_chars=max_chars) for item in value if display_text(item, max_chars=max_chars))
    else:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        text = fallback
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "..."
    return html.escape(text)


def finding_anchor_text(finding: dict[str, object]) -> str:
    anchors = finding.get("target_anchors")
    if isinstance(anchors, list) and anchors:
        return str(anchors[0])
    return str(finding.get("primary_anchor") or finding.get("location") or "")


def render_issue_index(findings: list[dict[str, object]]) -> str:
    if not findings:
        body = '<p class="empty-state">当前 compiled findings 为空。</p>'
    else:
        articles = []
        rows = []
        for finding in findings:
            finding_id = display_text(finding.get("id"))
            severity = severity_key(finding.get("severity"))
            issue_type = display_text(finding.get("issue_type"), fallback="prose")
            title = display_text(finding.get("title") or finding.get("diagnosis"), fallback="Untitled finding")
            location = display_text(finding.get("location") or finding_anchor_text(finding), fallback="paper")
            diagnosis = display_text(finding.get("diagnosis"), fallback="No diagnosis supplied.")
            articles.append(
                f"""
      <article class="finding" id="{finding_id}" data-severity="{severity}" data-issue-type="{issue_type}">
        <div>{severity_badge(finding.get("severity"))} {finding_id} {title}</div>
        <p><strong>位置：</strong>{location}</p>
        <p><strong>诊断：</strong>{diagnosis}</p>
        <p><strong>读者卡点：</strong>{display_text(finding.get("reader_friction"), fallback="See diagnosis.")}</p>
      </article>"""
            )
            rows.append(
                f"<tr data-severity=\"{severity}\" data-issue-type=\"{issue_type}\"><td>{finding_id_link(finding.get('id'))}</td>"
                f"<td>{severity_badge(finding.get('severity'))}</td><td>{issue_type}</td><td>{title}</td>"
                f"<td>{location}</td><td>{display_text(finding.get('next_draft_task') or finding.get('self_check'), fallback='复查并修订。')}</td></tr>"
            )
        body = "".join(articles) + f"""
      <div class="table-wrap">
        <table class="report-table">
          <caption>Finding ledger</caption>
          <thead><tr><th scope="col">ID</th><th scope="col">严重度</th><th scope="col">类型</th><th scope="col">问题</th><th scope="col">位置</th><th scope="col">下一步</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>"""
    return f"""
    <section id="issue-index">
      <h2>{WORKBENCH_SECTION_LABELS['issue-index']}</h2>
      {body}
    </section>"""


def render_executive_diagnosis(findings: list[dict[str, object]]) -> str:
    top = findings[0] if findings else {}
    return f"""
    <section id="executive-diagnosis">
      <h2>{WORKBENCH_SECTION_LABELS['executive-diagnosis']}</h2>
      <p><strong>一句话 verdict：</strong>{display_text(top.get('title') or top.get('diagnosis'), fallback='当前报告由 JSON artifacts deterministic 生成，未检测到 compiled finding。')}</p>
      <article class="finding">
        <h3>可救骨架</h3>
        <p><strong>Minimal viable paper：</strong>{display_text(top.get('self_check'), fallback='保留核心贡献，但让主张、证据和读者路径显式对齐。')}</p>
        <p><strong>Next revision thread：</strong>{display_text(top.get('next_draft_task') or top.get('downgrade_condition'), fallback='优先处理最高严重度 finding。')}</p>
      </article>
    </section>"""


def render_claim_evidence(claims: list[dict[str, object]], findings: list[dict[str, object]]) -> str:
    if claims:
        rows = []
        for claim in claims:
            linked = claim.get("linked_findings") or claim.get("linked_finding_ids") or []
            rows.append(
                "<tr data-severity=\"major\" data-issue-type=\"claim\">"
                f"<td>{display_text(claim.get('claim_text') or claim.get('text'), fallback='Claim')}</td>"
                f"<td>{display_text(claim.get('claim_type'), fallback='claim')}</td>"
                f"<td>{display_text(claim.get('location'), fallback='paper')}</td>"
                f"<td>{display_text(claim.get('visible_evidence') or claim.get('evidence'), fallback='Evidence not specified.')}</td>"
                f"<td>{display_text(claim.get('status'), fallback='needs review')}</td>"
                f"<td>{joined_links(linked)}</td>"
                f"<td>{display_text(claim.get('next_draft_task'), fallback='Align claim and visible evidence.')}</td>"
                "</tr>"
            )
    else:
        rows = [
            "<tr data-severity=\"major\" data-issue-type=\"claim\">"
            f"<td>{display_text(findings[0].get('title') if findings else '', fallback='No explicit claim artifact')}</td>"
            "<td>claim</td><td>paper</td><td>Derived from compiled findings.</td><td>needs review</td><td></td><td>Write claims.json in Phase B.</td></tr>"
        ]
    return f"""
    <section id="claim-evidence-audit">
      <h2>{WORKBENCH_SECTION_LABELS['claim-evidence-audit']}</h2>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Abstract promise tracking and claim-evidence map</caption>
          <thead><tr><th scope="col">Claim</th><th scope="col">Type</th><th scope="col">Location</th><th scope="col">Visible evidence</th><th scope="col">Verdict</th><th scope="col">关联问题</th><th scope="col">下一稿任务</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>"""


def render_deep_reading(findings: list[dict[str, object]], annotations: list[dict[str, str]], pass_observations: object) -> str:
    sentence_notes = [item for item in annotations if item.get("target_level") == "sentence"]
    paragraph_notes = [item for item in annotations if item.get("target_level") == "paragraph"]
    section_notes = [item for item in annotations if item.get("target_level") == "section"]
    if not sentence_notes and findings:
        sentence_notes = [
            {
                "issue_id": str(findings[0].get("id") or "F1"),
                "sentence_id": str(finding_anchor_text(findings[0]) or "paper"),
                "severity": severity_key(findings[0].get("severity")),
                "issue_type": str(findings[0].get("issue_type") or "prose"),
                "diagnosis": str(findings[0].get("diagnosis") or findings[0].get("title") or ""),
                "self_check": str(findings[0].get("self_check") or ""),
            }
        ]
    if not paragraph_notes:
        paragraph_notes = [{"issue_id": "", "paragraph_id": "paper", "severity": "minor", "issue_type": "prose", "diagnosis": "Paragraph-level review is represented by compiled artifacts.", "self_check": "Check paragraph job and transitions."}]
    if not section_notes:
        section_notes = [{"issue_id": "", "section_id": "paper", "severity": "minor", "issue_type": "prose", "diagnosis": "Section reflection is represented by Phase A artifacts.", "self_check": "Check section role in the argument."}]
    sentence_rows = [
        f"<tr data-note-kind=\"sentence\" data-severity=\"{severity_key(item.get('severity'))}\" data-issue-type=\"{display_text(item.get('issue_type'), fallback='prose')}\"><td>句子</td><td>{display_text(item.get('sentence_id'), fallback='paper')}</td><td>{display_text(item.get('diagnosis') or item.get('title') or item.get('short'), fallback='See finding.')}</td><td>{finding_id_link(item.get('issue_id'))}</td><td>{display_text(item.get('self_check') or item.get('next_draft_task'), fallback='Revise this local unit.')}</td></tr>"
        for item in sentence_notes
    ]
    paragraph_rows = [
        f"<tr data-note-kind=\"paragraph\" data-decision=\"revise\" data-severity=\"{severity_key(item.get('severity'))}\" data-issue-type=\"{display_text(item.get('issue_type'), fallback='prose')}\"><td>段落</td><td>{display_text(item.get('paragraph_id'), fallback='paper')}</td><td>{display_text(item.get('diagnosis') or item.get('title') or item.get('short'), fallback='Paragraph needs review.')}</td><td>{finding_id_link(item.get('issue_id'))}</td><td>{display_text(item.get('self_check') or item.get('next_draft_task'), fallback='Check paragraph job.')}</td></tr>"
        for item in paragraph_notes
    ]
    section_rows = [
        f"<tr data-note-kind=\"section\" data-severity=\"{severity_key(item.get('severity'))}\" data-issue-type=\"{display_text(item.get('issue_type'), fallback='prose')}\"><td>{display_text(item.get('section_id'), fallback='paper')}</td><td>{display_text(item.get('diagnosis') or item.get('title') or item.get('short'), fallback='Section needs review.')}</td><td>{finding_id_link(item.get('issue_id'))}</td><td>{display_text(item.get('self_check') or item.get('next_draft_task'), fallback='Check section role.')}</td></tr>"
        for item in section_notes
    ]
    return f"""
    <section id="deep-reading-notes">
      <h2>{WORKBENCH_SECTION_LABELS['deep-reading-notes']}</h2>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Section reflection</caption>
          <thead><tr><th scope="col">章节</th><th scope="col">读后一句话</th><th scope="col">关联问题</th><th scope="col">下一稿任务</th></tr></thead>
          <tbody>{''.join(section_rows)}</tbody>
        </table>
      </div>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Paragraph and sentence notes</caption>
          <thead><tr><th scope="col">层级</th><th scope="col">位置</th><th scope="col">读者卡点</th><th scope="col">关联问题</th><th scope="col">下一稿任务 / 自改问题</th></tr></thead>
          <tbody>{''.join(paragraph_rows)}{''.join(sentence_rows)}</tbody>
        </table>
      </div>
    </section>"""


def render_submission_readiness(findings: list[dict[str, object]]) -> str:
    rows = []
    for finding in findings:
        issue_type = str(finding.get("issue_type") or "").lower()
        source_ids = " ".join(str(item) for item in finding.get("source_issue_ids", []) if item)
        domain = source_ids.split(":", 1)[0] if ":" in source_ids else issue_type
        if domain not in SUBMISSION_DOMAINS and issue_type not in SUBMISSION_DOMAINS:
            continue
        rows.append(
            f"<tr data-severity=\"{severity_key(finding.get('severity'))}\" data-issue-type=\"{display_text(finding.get('issue_type'), fallback='submission')}\"><td>{display_text(domain or issue_type, fallback='submission')}</td><td>{display_text(finding.get('location') or finding_anchor_text(finding), fallback='paper')}</td><td>{severity_badge(finding.get('severity'))}</td><td>{display_text(finding.get('diagnosis') or finding.get('title'), fallback='See finding.')}</td><td>{finding_id_link(finding.get('id'))}</td><td>{display_text(finding.get('next_draft_task') or finding.get('self_check'), fallback='Fix before submission.')}</td></tr>"
        )
    if not rows and findings:
        rows.append(
            f"<tr data-severity=\"{severity_key(findings[0].get('severity'))}\" data-issue-type=\"submission\"><td>compiled artifacts</td><td>{display_text(findings[0].get('location'), fallback='paper')}</td><td>{severity_badge(findings[0].get('severity'))}</td><td>{display_text(findings[0].get('diagnosis'), fallback='No specialist issues rendered.')}</td><td>{finding_id_link(findings[0].get('id'))}</td><td>Run or inspect specialist artifacts before submission.</td></tr>"
        )
    return f"""
    <section id="submission-readiness">
      <h2>{WORKBENCH_SECTION_LABELS['submission-readiness']}</h2>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Submission readiness checks</caption>
          <thead><tr><th scope="col">类别</th><th scope="col">位置</th><th scope="col">严重度</th><th scope="col">卡点</th><th scope="col">关联问题</th><th scope="col">下一稿任务</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>"""


def render_local_comments(findings: list[dict[str, object]]) -> str:
    rows = [
        f"<tr data-severity=\"{severity_key(finding.get('severity'))}\" data-issue-type=\"{display_text(finding.get('issue_type'), fallback='prose')}\"><td>{severity_badge(finding.get('severity'))}</td><td>{display_text(finding.get('title'), fallback='Finding')}</td><td>{display_text(finding.get('reader_friction') or finding.get('diagnosis'), fallback='See finding.')}</td><td>{display_text(finding.get('location') or finding_anchor_text(finding), fallback='paper')}</td><td>{finding_id_link(finding.get('id'))}</td></tr>"
        for finding in findings[:8]
    ]
    if not rows:
        rows.append("<tr data-severity=\"minor\" data-issue-type=\"prose\"><td><span class=\"badge minor\">[i] Minor</span></td><td>No recurring patterns</td><td>No compiled findings.</td><td>paper</td><td></td></tr>")
    return f"""
    <section id="local-comments">
      <h2>{WORKBENCH_SECTION_LABELS['local-comments']}</h2>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Recurring issue patterns</caption>
          <thead><tr><th scope="col">严重度</th><th scope="col">共性问题</th><th scope="col">读者卡点</th><th scope="col">代表位置</th><th scope="col">关联问题</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>"""


def render_revision_plan(findings: list[dict[str, object]]) -> str:
    rows = []
    for idx, finding in enumerate(findings[:10], 1):
        rows.append(
            f"<tr><td>P{0 if idx <= 3 else 1}</td><td>{display_text(finding.get('next_draft_task') or finding.get('self_check'), fallback='Resolve finding before resubmission.')}</td><td>{finding_id_link(finding.get('id'))}</td><td>{display_text(finding.get('issue_type'), fallback='writing')}</td><td>{'M' if severity_key(finding.get('severity')) in {'blocker', 'major'} else 'S'}</td><td>{display_text(finding.get('downgrade_condition'), fallback='Finding no longer appears in compiled artifacts.')}</td></tr>"
        )
    if not rows:
        rows.append("<tr><td>P1</td><td>No compiled findings.</td><td></td><td>Writing</td><td>S</td><td>Run Prose Phase A/B.</td></tr>")
    return f"""
    <section id="revision-plan">
      <h2>{WORKBENCH_SECTION_LABELS['revision-plan']}</h2>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Executable revision plan</caption>
          <thead><tr><th scope="col">优先级</th><th scope="col">任务</th><th scope="col">关联问题</th><th scope="col">区域</th><th scope="col">工作量</th><th scope="col">验收方式</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    </section>"""


def render_coverage_receipt(coverage: object, *, raw_hash_attr: str, source_artifact: str, sentence_count: int, annotation_count: int) -> str:
    units = coverage.get("units", []) if isinstance(coverage, dict) else []
    rows = []
    for unit in units if isinstance(units, list) else []:
        if not isinstance(unit, dict):
            continue
        rows.append(
            f"<tr><td>{display_text(unit.get('unit'))}</td><td>{display_text(unit.get('total'))}</td><td>{display_text(unit.get('reviewed'))}</td><td>{display_text(unit.get('with_issues'))}</td><td>{display_text(unit.get('clean'))}</td><td>{display_text(unit.get('skipped'))}</td><td>{display_text(unit.get('pending_in'))}</td></tr>"
        )
    if not rows:
        rows.append(
            f"<tr><td>Paper-reader annotations</td><td>{annotation_count}</td><td>{annotation_count}</td><td>{annotation_count}</td><td>0</td><td>0</td><td></td></tr>"
        )
    return f"""
    <section id="coverage-receipt">
      <h2>{WORKBENCH_SECTION_LABELS['coverage-receipt']}</h2>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Coverage receipt</caption>
          <thead><tr><th scope="col">Unit</th><th scope="col">Total</th><th scope="col">Reviewed</th><th scope="col">With issues</th><th scope="col">Clean</th><th scope="col">Skipped</th><th scope="col">Pending in</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Paper-reader rendering receipt</caption>
          <thead><tr><th scope="col">Unit</th><th scope="col">Value</th></tr></thead>
          <tbody>
            <tr><td>Source artifact</td><td>{source_artifact}</td></tr>
            <tr><td>Source hash</td><td>{raw_hash_attr}</td></tr>
            <tr><td>Sentence ID scheme</td><td>{SENTENCE_ID_SCHEME}</td></tr>
            <tr><td>Sentence spans</td><td>{sentence_count}</td></tr>
            <tr><td>Annotations</td><td>{annotation_count}</td></tr>
            <tr><td>Coverage consistency</td><td>derived from compiled JSON artifacts</td></tr>
          </tbody>
        </table>
      </div>
    </section>"""


def render_workbench_sections(
    *,
    findings: list[dict[str, object]],
    annotations: list[dict[str, str]],
    claims: list[dict[str, object]],
    coverage: object,
    pass_observations: object,
    raw_hash_attr: str,
    source_artifact: str,
    sentence_count: int,
) -> str:
    return "\n".join(
        [
            render_executive_diagnosis(findings),
            render_issue_index(findings),
            render_claim_evidence(claims, findings),
            render_deep_reading(findings, annotations, pass_observations),
            render_submission_readiness(findings),
            render_local_comments(findings),
            render_revision_plan(findings),
            render_coverage_receipt(
                coverage,
                raw_hash_attr=raw_hash_attr,
                source_artifact=source_artifact,
                sentence_count=sentence_count,
                annotation_count=len(annotations),
            ),
        ]
    )


def extract_title(soup: BeautifulSoup, tex_path: Path) -> str:
    title = soup.find("title")
    if title and title.get_text(strip=True):
        return title.get_text(" ", strip=True)
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        return heading.get_text(" ", strip=True)
    return tex_path.stem


def report_shell(
    title: str,
    source_html: str,
    *,
    tex_path: Path,
    raw_html_path: Path,
    raw_hash: str,
    sentence_count: int,
    annotations: list[dict[str, str]],
    findings: list[dict[str, object]] | None = None,
    claims: list[dict[str, object]] | None = None,
    coverage: object = None,
    pass_observations: object = None,
    full_report: bool = False,
) -> str:
    source_artifact = html.escape(str(raw_html_path))
    tex_display = html.escape(str(tex_path))
    raw_hash_attr = html.escape(raw_hash)
    title_html = html.escape(title)
    annotation_count = len(annotations)
    annotation_panel_state = ' data-empty="true"' if annotations else ""
    annotation_cards = render_annotation_cards(annotations)
    finding_anchor_index = render_finding_anchor_index(annotations)
    report_kind = "compiled-review" if full_report else "paper-reader-only"
    header_title = "Ariadne Compiled Review" if full_report else "Ariadne Paper Reader Preview"
    workbench_nav = (
        """
    <a href="#executive-diagnosis">总评诊断</a>
    <a href="#issue-index">问题索引</a>
    <a href="#claim-evidence-audit">主张证据</a>
    <a href="#deep-reading-notes">精读批注</a>
    <a href="#submission-readiness">提交就绪</a>
    <a href="#local-comments">共性问题</a>
    <a href="#revision-plan">修改路线</a>"""
        if full_report
        else ""
    )
    workbench_html = (
        render_workbench_sections(
            findings=findings or [],
            annotations=annotations,
            claims=claims or [],
            coverage=coverage,
            pass_observations=pass_observations,
            raw_hash_attr=raw_hash_attr,
            source_artifact=source_artifact,
            sentence_count=sentence_count,
        )
        if full_report
        else render_coverage_receipt(
            coverage,
            raw_hash_attr=raw_hash_attr,
            source_artifact=source_artifact,
            sentence_count=sentence_count,
            annotation_count=annotation_count,
        )
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ariadne Paper Reader - {title_html}</title>
  <style>
    :root {{ --bg:#f6f7f9; --paper:#fff; --ink:#1f2937; --muted:#607086; --line:#d7dde8; --soft:#eef2f7; --accent:#2449a7; --blocker:#b42318; --blocker-bg:#fff1f0; --major:#9a6700; --major-bg:#fff7df; --minor:#3451b2; --minor-bg:#edf2ff; --polish:#147d64; --polish-bg:#e9f8f3; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); line-height:1.65; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; }}
    .review-report {{ max-width:1320px; margin:0 auto; padding:24px; }}
    header, nav, section {{ background:var(--paper); border:1px solid var(--line); border-radius:8px; }}
    header {{ padding:24px; margin-bottom:14px; }}
    nav {{ position:sticky; top:10px; z-index:5; padding:12px 14px; margin-bottom:14px; }}
    nav a {{ margin-right:14px; color:var(--accent); text-decoration:none; white-space:nowrap; }}
    section {{ padding:22px; margin-bottom:16px; }}
    h1, h2, h3 {{ line-height:1.25; letter-spacing:0; }}
    .summary-band {{ display:grid; grid-template-columns:repeat(4, minmax(120px, 1fr)); gap:10px; margin-top:16px; }}
    .summary-cell {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:#fbfcfe; }}
    .summary-cell strong {{ display:block; font-size:12px; color:var(--muted); }}
    .badge {{ display:inline-flex; align-items:center; border-radius:999px; padding:2px 8px; font-size:12px; font-weight:700; border:1px solid transparent; }}
    .blocker {{ color:var(--blocker); background:var(--blocker-bg); border-color:#ffd3cf; }}
    .major {{ color:var(--major); background:var(--major-bg); border-color:#f2d98f; }}
    .minor {{ color:var(--minor); background:var(--minor-bg); border-color:#c8d4ff; }}
    .polish {{ color:var(--polish); background:var(--polish-bg); border-color:#bce7d8; }}
    .paper-reader {{ padding:0; overflow:visible; }}
    .reader-toolbar {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; padding:16px 18px; border-bottom:1px solid var(--line); background:#fafbfc; }}
    .reader-shell {{ display:grid; grid-template-columns:minmax(0, 1fr) 360px; gap:0; align-items:start; }}
    .paper-pane {{ padding:34px 44px; min-height:640px; background:#fff; border-right:1px solid var(--line); font-family:Georgia,"Times New Roman","Noto Serif",serif; font-size:17px; line-height:1.72; overflow-wrap:break-word; }}
    .paper-pane header {{ border:0; padding:0; margin:0 0 28px; }}
    .paper-pane > p, .paper-pane > ul, .paper-pane > ol, .paper-pane > blockquote, .paper-pane > h1, .paper-pane > h2, .paper-pane > h3, .paper-pane > h4, .paper-pane > h5, .paper-pane > h6, .paper-pane > .abstract, .paper-pane > #refs {{ max-width:760px; }}
    .paper-pane p {{ margin:1em 0; }}
    .paper-pane h1 {{ font-size:28px; }}
    .paper-pane h2 {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:22px; margin:24px 0 12px; }}
    .paper-pane h3 {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:18px; margin:20px 0 10px; }}
    .paper-pane h4 {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:17px; margin:18px 0 8px; }}
    .paper-pane ul, .paper-pane ol {{ padding-left:1.7em; margin:1em 0; max-width:760px; }}
    .paper-pane li {{ margin:.35em 0; padding-left:.2em; }}
    .paper-pane li > p {{ margin:.25em 0 .65em; }}
    .paper-pane li > ol, .paper-pane li > ul {{ margin-top:.25em; }}
    .paper-pane blockquote {{ margin:1em 0 1em 1.7em; padding-left:1em; border-left:2px solid #e6e6e6; color:#606060; }}
    .paper-pane .abstract {{ margin:2em 2em; text-align:left; font-size:85%; }}
    .paper-pane .abstract-title {{ font-weight:700; text-align:center; margin-bottom:.5em; }}
    .paper-pane table {{ width:100%; border-collapse:collapse; display:block; overflow-x:auto; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:14px; }}
    .paper-pane th, .paper-pane td {{ border:1px solid var(--line); padding:6px; vertical-align:top; }}
    .paper-pane img, .paper-pane svg {{ max-width:100%; height:auto; }}
    .paper-pane embed {{ display:block; width:100%; max-width:100%; min-height:240px; margin:10px auto; border:1px solid var(--line); }}
    .paper-pane .paper-asset-image {{ display:block; width:100%; max-width:100%; height:auto; margin:8px auto; border:1px solid var(--line); background:#fff; }}
    .paper-pane .paper-float {{ margin:18px 0; clear:both; }}
    .paper-pane .wrapfigure, .paper-pane .wraptable {{ max-width:46%; float:right; margin:2px 0 14px 22px; }}
    .paper-pane .wrapfigure img, .paper-pane .wraptable img {{ width:100%; }}
    .paper-pane .wraptable table {{ min-width:0; }}
    .paper-pane .table\\*, .paper-pane .figure\\* {{ clear:both; margin:24px 0; }}
    .paper-pane figure {{ margin:22px 0; max-width:920px; }}
    .paper-pane .prompt-figure {{ border:1px solid var(--line); border-radius:8px; background:#fbfcfe; padding:12px; }}
    .paper-pane figcaption, .paper-pane caption {{ color:var(--muted); font-size:14px; line-height:1.5; }}
    .paper-pane .tcolorbox, .paper-pane .sourceCode {{ border:1px solid var(--line); border-radius:8px; background:#f8fafc; margin:12px 0; max-width:100%; }}
    .paper-pane .tcolorbox {{ padding:0; overflow:hidden; }}
    .paper-pane pre {{ margin:0; padding:12px 14px; overflow:auto; white-space:pre-wrap; overflow-wrap:break-word; font-family:Menlo,Monaco,Consolas,"SFMono-Regular",monospace; font-size:12px; line-height:1.5; }}
    .paper-pane code {{ font-family:Menlo,Monaco,Consolas,"SFMono-Regular",monospace; }}
    .paper-pane pre > code.sourceCode > span {{ display:inline-block; line-height:1.25; }}
    .paper-pane pre > code.sourceCode > span:empty {{ height:1.2em; }}
    .paper-pane .sourceCode span {{ white-space:pre-wrap; }}
    .paper-pane code span.an, .paper-pane code span.co, .paper-pane code span.cv, .paper-pane code span.wa {{ color:#60a0b0; font-style:italic; }}
    .paper-pane code span.an, .paper-pane code span.cv, .paper-pane code span.wa {{ font-weight:700; }}
    .paper-pane code span.ot {{ color:#007020; }}
    .paper-pane code span.in {{ color:#60a0b0; font-weight:700; font-style:italic; }}
    .paper-pane #references {{ margin-top:42px; padding-top:18px; border-top:1px solid var(--line); }}
    .paper-pane #refs {{ margin:0 0 28px 1.4em; text-indent:-1.4em; font-size:13.5px; line-height:1.45; color:#273449; }}
    .paper-pane #refs .csl-entry {{ clear:both; margin:0 0 .65em; }}
    .paper-pane #refs em {{ color:#111827; }}
    .paper-pane #neurips-paper-checklist {{ margin-top:42px; padding-top:18px; border-top:1px solid var(--line); }}
    .paper-pane #neurips-paper-checklist ~ ol {{ font-size:14px; line-height:1.5; max-width:820px; }}
    .paper-pane #neurips-paper-checklist ~ ol ol {{ margin-top:.35em; }}
    .paper-pane #neurips-paper-checklist ~ ol li {{ margin:.25em 0; }}
    .paper-pane #neurips-paper-checklist ~ ol li > p {{ margin:.2em 0 .45em; }}
    .paper-overview-annotations {{ max-width:760px; margin:0 0 22px; padding:10px 12px; border-left:3px solid var(--accent); background:#f8fafc; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:13px; line-height:1.45; }}
    .paper-overview-annotations strong {{ display:block; margin-bottom:8px; color:#111827; }}
    .paper-pane h1.has-section-annotation, .paper-pane h2.has-section-annotation, .paper-pane h3.has-section-annotation, .paper-pane h4.has-section-annotation {{ position:relative; }}
    .paper-pane .has-paragraph-annotation {{ position:relative; padding-left:26px; }}
    .annotation-bubble {{ border:1px solid var(--line); border-radius:999px; background:#fff; color:var(--accent); cursor:pointer; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:11px; font-weight:800; line-height:1.25; padding:2px 7px; vertical-align:middle; box-shadow:0 1px 2px rgba(15,23,42,.08); }}
    .annotation-bubble:hover, .annotation-bubble:focus-visible {{ outline:2px solid rgba(36,73,167,.25); outline-offset:2px; }}
    .annotation-bubble.paragraph {{ position:absolute; left:0; top:.35em; width:18px; height:18px; padding:0; overflow:hidden; text-indent:24px; white-space:nowrap; border-color:#b6c4dd; background:#eef4ff; }}
    .annotation-bubble.paragraph::before {{ content:"¶"; position:absolute; left:0; top:0; width:100%; height:100%; text-indent:0; display:flex; align-items:center; justify-content:center; color:var(--accent); }}
    .annotation-bubble.section {{ margin-left:8px; }}
    .annotation-bubble.paper {{ margin:0 6px 6px 0; }}
    .paper-sentence {{ border-radius:4px; padding:1px 2px; scroll-margin-top:92px; }}
    .paper-sentence.has-annotation {{ position:relative; cursor:pointer; text-decoration-line:underline; text-decoration-thickness:2px; text-underline-offset:4px; transition:background-color .12s ease, outline-color .12s ease; }}
    .paper-sentence.has-annotation::after {{ content:attr(data-inline-label); display:inline-flex; align-items:center; max-width:160px; margin-left:6px; padding:1px 6px; border-radius:999px; border:1px solid currentColor; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:11px; font-weight:700; line-height:1.35; vertical-align:baseline; white-space:nowrap; pointer-events:none; }}
    .paper-sentence[data-severity="blocker"] {{ background:var(--blocker-bg); text-decoration-color:var(--blocker); }}
    .paper-sentence[data-severity="major"] {{ background:var(--major-bg); text-decoration-color:var(--major); }}
    .paper-sentence[data-severity="minor"] {{ background:var(--minor-bg); text-decoration-color:var(--minor); }}
    .paper-sentence[data-severity="polish"] {{ background:var(--polish-bg); text-decoration-color:var(--polish); }}
    .paper-sentence.is-active {{ outline:2px solid var(--accent); outline-offset:2px; box-shadow:0 0 0 4px rgba(36,73,167,.10); }}
    .annotation-panel {{ position:sticky; top:70px; max-height:calc(100vh - 86px); overflow:auto; padding:18px; background:#fbfcfe; }}
    .annotation-panel[data-empty="true"] {{ color:var(--muted); }}
    .annotation-empty-state {{ border:1px dashed var(--line); border-radius:8px; padding:14px; margin:0 0 12px; background:#fff; color:var(--muted); }}
    .annotation-card {{ position:relative; display:block; border:1px solid var(--line); border-radius:8px; padding:14px; margin-bottom:12px; background:#fff; }}
    .annotation-card[hidden] {{ display:none; }}
    .annotation-card::before {{ content:""; position:absolute; left:-9px; top:24px; border-top:9px solid transparent; border-bottom:9px solid transparent; border-right:9px solid var(--line); }}
    .annotation-card::after {{ content:""; position:absolute; left:-7px; top:25px; border-top:8px solid transparent; border-bottom:8px solid transparent; border-right:8px solid #fff; }}
    .annotation-card.is-active {{ border-color:var(--accent); box-shadow:0 0 0 2px rgba(36,73,167,.12); }}
    .annotation-meta {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:0 0 8px; color:var(--muted); font-size:12px; }}
    .annotation-card h3 {{ margin:0 0 10px; font-size:18px; }}
    .annotation-card dl {{ margin:0; }}
    .annotation-card dt {{ margin-top:10px; color:var(--muted); font-size:12px; font-weight:700; }}
    .annotation-card dd {{ margin:2px 0 0; }}
    .annotation-pointer {{ margin:0 0 10px; }}
    .annotation-pointer a {{ display:inline-flex; align-items:center; gap:6px; color:var(--accent); font-size:13px; font-weight:700; text-decoration:none; }}
    .annotation-pointer a::before {{ content:"←"; font-size:16px; line-height:1; }}
    .annotation-unanchored {{ color:var(--muted); font-size:13px; font-weight:700; }}
    .annotation-sublist {{ margin:0; padding-left:18px; }}
    .annotation-nav {{ display:flex; gap:8px; }}
    .annotation-nav button {{ border:1px solid var(--line); border-radius:6px; background:#fff; padding:7px 10px; cursor:pointer; }}
    .unanchored-drawer {{ margin-top:16px; border-top:1px solid var(--line); padding-top:14px; }}
    .unanchored-drawer summary {{ cursor:pointer; font-weight:800; color:var(--accent); }}
    .unanchored-drawer .annotation-card {{ margin-top:10px; }}
    .empty-state {{ color:var(--muted); font-style:italic; }}
    .table-wrap {{ overflow-x:auto; margin-top:10px; }}
    table.report-table {{ width:100%; border-collapse:collapse; min-width:760px; }}
    .report-table th, .report-table td {{ border:1px solid var(--line); padding:9px; vertical-align:top; text-align:left; }}
    .report-table th {{ background:var(--soft); }}
    .report-table caption {{ text-align:left; font-weight:700; margin:0 0 8px; }}
    @media (max-width: 920px) {{ .review-report {{ padding:12px; }} .summary-band {{ grid-template-columns:1fr 1fr; }} .reader-shell {{ grid-template-columns:1fr; }} .paper-pane {{ border-right:0; border-bottom:1px solid var(--line); padding:24px 18px; }} .paper-pane .wrapfigure, .paper-pane .wraptable {{ float:none; max-width:100%; margin:18px 0; }} .annotation-panel {{ position:static; max-height:none; }} }}
    @media print {{ nav, .reader-toolbar {{ display:none !important; }} .annotation-card {{ display:block; }} }}
  </style>
</head>
<body>
<article class="review-report" data-report-kind="{report_kind}">
  <header>
    <h1>{header_title}</h1>
    <p>入口：<code>{tex_display}</code></p>
    <p>转换：pandoc HTML5 + MathML；句子 ID：<code>{SENTENCE_ID_SCHEME}</code></p>
    <p>Source artifact：<code>{source_artifact}</code></p>
    <p>Source hash：<code>{raw_hash_attr}</code></p>
    <div class="summary-band">
      <div class="summary-cell"><strong>Title</strong>{title_html}</div>
      <div class="summary-cell"><strong>Paper HTML source</strong>{PANDOC_SOURCE}</div>
      <div class="summary-cell"><strong>Source fidelity</strong>deterministic</div>
      <div class="summary-cell"><strong>Sentence spans</strong>{sentence_count}</div>
      <div class="summary-cell"><strong>Annotations</strong>{annotation_count}</div>
    </div>
  </header>
  <nav aria-label="Review sections">
    <a href="#paper-reader">论文正文批注</a>
{workbench_nav}
    <a href="#coverage-receipt">覆盖回执</a>
  </nav>
  {finding_anchor_index}
  <section id="paper-reader" class="paper-reader" aria-label="Annotated paper">
    <div class="reader-toolbar">
      <div>
        <h2>论文正文批注</h2>
        <p class="empty-state">当前是 source-derived paper-reader；正文句子已获得稳定 <code>data-sentence-id</code>，批注以 overlay 方式添加。</p>
      </div>
      <div>
        <span class="badge blocker">■ Blocker</span>
        <span class="badge major">▲ Major</span>
        <span class="badge minor">● Minor</span>
        <span class="badge polish">◆ Polish</span>
      </div>
    </div>
    <div class="reader-shell">
      <article class="paper-pane" data-paper-html-source="{PANDOC_SOURCE}" data-source-fidelity="deterministic" data-source-artifact="{source_artifact}" data-source-hash="{raw_hash_attr}" data-sentence-id-scheme="{SENTENCE_ID_SCHEME}" data-annotation-mode="overlay-only">
{source_html}
      </article>
      <aside id="annotation-panel" class="annotation-panel" aria-label="批注详情" aria-live="polite"{annotation_panel_state}>
        <h2>批注详情</h2>
{annotation_cards}
      </aside>
    </div>
  </section>
  <main>
{workbench_html}
  </main>
</article>
<script>
  function AriadnePaperReaderClosestAnnotation(node) {{
    while (node && node !== document) {{
      if (node.classList && node.classList.contains("paper-sentence") && node.classList.contains("has-annotation")) return node;
      if (node.classList && node.classList.contains("has-paragraph-annotation")) return node;
      if (node.classList && node.classList.contains("has-section-annotation")) return node;
      node = node.parentNode;
    }}
    return null;
  }}
  function AriadnePaperReaderAnchorId(node) {{
    if (!node || !node.getAttribute) return "";
    return node.getAttribute("data-sentence-id") || node.getAttribute("data-paragraph-id") || node.id || "";
  }}
  function AriadnePaperReaderAnchorLevel(node) {{
    if (!node || !node.classList) return "sentence";
    if (node.classList.contains("has-paragraph-annotation")) return "paragraph";
    if (node.classList.contains("has-section-annotation")) return "section";
    return "sentence";
  }}
  function AriadnePaperReaderSetActive(level, targetId, options = {{}}) {{
    const panel = document.querySelector("#annotation-panel");
    let activeCard = null;
    const targetAttr = `data-target-${{level}}`;
    document.querySelectorAll(".annotation-card").forEach((card) => {{
      const isActive = card.getAttribute("data-target-level") === level && card.getAttribute(targetAttr) === targetId;
      if (card.getAttribute("data-unanchored") === "true") return;
      card.classList.toggle("is-active", isActive);
      card.hidden = !isActive;
      if (isActive) activeCard = card;
    }});
    document.querySelectorAll(".paper-sentence, [data-paragraph-id], .paper-pane h1, .paper-pane h2, .paper-pane h3, .paper-pane h4, #paper-overview-annotations").forEach((node) => {{
      const nodeLevel = node.id === "paper-overview-annotations" ? "paper" : AriadnePaperReaderAnchorLevel(node);
      const nodeId = node.id === "paper-overview-annotations" ? "paper" : AriadnePaperReaderAnchorId(node);
      node.classList.toggle("is-active", nodeLevel === level && nodeId === targetId);
    }});
    document.querySelectorAll("[data-annotation-empty]").forEach((node) => {{
      node.hidden = Boolean(activeCard);
    }});
    if (panel) panel.dataset.empty = activeCard ? "false" : "true";
    if (activeCard && options.focusCard) {{
      activeCard.scrollIntoView({{ block: "nearest", behavior: "smooth" }});
    }}
  }}
  function AriadnePaperReaderOpenAnnotation(level, targetId) {{
    AriadnePaperReaderSetActive(level || "sentence", targetId, {{ focusCard: true }});
  }}
  function AriadnePaperReaderVisibleSentences() {{
    return Array.from(document.querySelectorAll(".paper-sentence.has-annotation"));
  }}
  function AriadnePaperReaderStep(delta) {{
    const items = AriadnePaperReaderVisibleSentences();
    if (items.length === 0) return;
    const activeIndex = items.findIndex((item) => item.classList.contains("is-active"));
    const startIndex = activeIndex === -1 ? (delta > 0 ? -1 : 0) : activeIndex;
    const next = items[(startIndex + delta + items.length) % items.length];
    AriadnePaperReaderOpenAnnotation("sentence", next.getAttribute("data-sentence-id"));
    if (typeof next.scrollIntoView === "function") {{
      next.scrollIntoView({{ block: "center", behavior: "smooth" }});
    }}
  }}
  (() => {{
    document.addEventListener("click", (event) => {{
      const bubble = event.target && event.target.closest ? event.target.closest(".annotation-bubble") : null;
      if (bubble) {{
        event.preventDefault();
        AriadnePaperReaderOpenAnnotation(bubble.getAttribute("data-anchor-level") || "sentence", bubble.getAttribute("data-scroll-target") || bubble.getAttribute("data-sentence-id") || bubble.getAttribute("data-paragraph-id") || bubble.getAttribute("data-section-id") || bubble.getAttribute("data-paper-id"));
        return;
      }}
      const sentence = AriadnePaperReaderClosestAnnotation(event.target);
      if (!sentence) return;
      AriadnePaperReaderOpenAnnotation(AriadnePaperReaderAnchorLevel(sentence), AriadnePaperReaderAnchorId(sentence));
    }});
    document.addEventListener("keydown", (event) => {{
      const sentence = AriadnePaperReaderClosestAnnotation(event.target);
      if (!sentence || (event.key !== "Enter" && event.key !== " ")) return;
      event.preventDefault();
      AriadnePaperReaderOpenAnnotation(AriadnePaperReaderAnchorLevel(sentence), AriadnePaperReaderAnchorId(sentence));
    }});
    document.addEventListener("click", (event) => {{
      const target = event.target;
      if (!target || !target.getAttribute) return;
      const sentenceId = target.getAttribute("data-scroll-target");
      if (!sentenceId) return;
      const level = target.getAttribute("data-scroll-level") || "sentence";
      const selector = level === "sentence" ? `[data-sentence-id="${{CSS.escape(sentenceId)}}"]` : level === "paragraph" ? `[data-paragraph-id="${{CSS.escape(sentenceId)}}"]` : level === "paper" ? "#paper-overview-annotations" : `#${{CSS.escape(sentenceId)}}`;
      const sentence = document.querySelector(selector);
      if (sentence) {{
        event.preventDefault();
        AriadnePaperReaderSetActive(level, sentenceId);
        sentence.scrollIntoView({{ block: "center", behavior: "smooth" }});
      }}
    }});
    const prev = document.querySelector("[data-prev-annotation]");
    const next = document.querySelector("[data-next-annotation]");
    if (prev) prev.addEventListener("click", () => AriadnePaperReaderStep(-1));
    if (next) next.addEventListener("click", () => AriadnePaperReaderStep(1));
    const hashId = decodeURIComponent(location.hash || "").replace(/^#/, "");
    if (hashId && document.querySelector(`[data-sentence-id="${{CSS.escape(hashId)}}"].has-annotation`)) {{
      AriadnePaperReaderOpenAnnotation("sentence", hashId);
    }}
    if (typeof globalThis !== "undefined") {{
      globalThis.AriadnePaperReader = {{
        setActive: AriadnePaperReaderSetActive,
        openAnnotation: AriadnePaperReaderOpenAnnotation,
        step: AriadnePaperReaderStep,
        visibleSentences: AriadnePaperReaderVisibleSentences,
      }};
    }}
  }})();
</script>
</body>
</html>
"""


def render(
    tex_path: Path,
    output_path: Path | None = None,
    raw_html_path: Path | None = None,
    annotations_path: Path | None = None,
    findings_path: Path | None = None,
    issues_dir: Path | None = None,
    review_html_path: Path | None = None,
    asset_dir: Path | None = None,
    inline_images: bool = False,
    reuse_raw_html: bool = False,
    claims_path: Path | None = None,
    coverage_path: Path | None = None,
    pass_observations_path: Path | None = None,
    full_report: bool = False,
) -> tuple[Path, Path, int]:
    tex_path = tex_path.resolve()
    output_path = (output_path or tex_path.with_name(f"ariadne_paper_reader_{tex_path.stem}.html")).resolve()
    raw_html_path = (raw_html_path or output_path.with_suffix(".source.html")).resolve()
    asset_dir = (asset_dir or output_path.with_name(f"{output_path.stem}_assets")).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_html_path.parent.mkdir(parents=True, exist_ok=True)
    soup, title, sentence_count = prepare_source_soup(
        tex_path,
        raw_html_path,
        output_path=output_path,
        asset_dir=asset_dir,
        inline_images=inline_images,
        reuse_raw_html=reuse_raw_html,
    )
    raw_hash = sha256_path(raw_html_path)
    imported_annotations = load_review_html_annotations(review_html_path)
    explicit_annotations = load_annotations(annotations_path)
    issue_annotations = load_issue_artifact_annotations(issues_dir)
    findings_by_id = load_findings(findings_path)
    merged_annotations = merge_annotation_findings(imported_annotations + explicit_annotations + issue_annotations, findings_by_id)
    annotations = apply_annotations(soup, assign_sentence_targets(soup, merged_annotations))
    finding_rows = load_findings_rows(findings_path)
    claim_rows = load_claim_rows(claims_path)
    coverage_payload = load_optional_json(coverage_path)
    pass_observations_payload = load_optional_json(pass_observations_path)
    source_html = body_inner_html(soup)
    output_path.write_text(
        report_shell(
            title,
            source_html,
            tex_path=tex_path,
            raw_html_path=raw_html_path,
            raw_hash=raw_hash,
            sentence_count=sentence_count,
            annotations=annotations,
            findings=finding_rows,
            claims=claim_rows,
            coverage=coverage_payload,
            pass_observations=pass_observations_payload,
            full_report=full_report,
        ),
        encoding="utf-8",
    )
    return output_path, raw_html_path, sentence_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tex", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--raw-html", type=Path)
    parser.add_argument("--annotations", type=Path, help="Optional JSON list/object of sentence annotations to overlay")
    parser.add_argument("--findings", type=Path, help="Optional findings JSON to join with anchor-only annotations")
    parser.add_argument("--issues-dir", type=Path, help="Optional directory of curated *_issues.json artifacts to render as cards")
    parser.add_argument("--claims", type=Path, help="Optional claims.json for compiled review workbench")
    parser.add_argument("--coverage", type=Path, help="Optional coverage.json for compiled review workbench")
    parser.add_argument("--pass-observations", type=Path, help="Optional pass_observations.json for compiled review workbench")
    parser.add_argument("--review-html", type=Path, help="Optional existing Ariadne HTML report to import as annotation content")
    parser.add_argument("--asset-dir", type=Path, help="Directory for rendered local figure assets")
    parser.add_argument(
        "--inline-images",
        action="store_true",
        help="Inline rendered PDF figures as base64 data URIs for a self-contained HTML file",
    )
    parser.add_argument(
        "--reuse-raw-html",
        action="store_true",
        help="Use an existing --raw-html source artifact as the paper source instead of rerunning pandoc",
    )
    parser.add_argument(
        "--full-report",
        action="store_true",
        help="Render deterministic compiled-review workbench sections from JSON artifacts",
    )
    args = parser.parse_args(argv)
    output, raw, count = render(
        args.tex,
        args.output,
        args.raw_html,
        args.annotations,
        args.findings,
        args.issues_dir,
        args.review_html,
        args.asset_dir,
        args.inline_images,
        args.reuse_raw_html,
        args.claims,
        args.coverage,
        args.pass_observations,
        args.full_report,
    )
    print(f"HTML report: {output}")
    print(f"Source HTML: {raw}")
    print(f"Sentence spans: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
