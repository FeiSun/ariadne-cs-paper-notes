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
from collections import Counter
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
LATEX_USEPACKAGE_RE = re.compile(r"\\usepackage(?:\[(?P<options>[^\]]*)\])?\{(?P<packages>[^}]+)\}")
LATEX_ENV_RE = re.compile(r"\\begin\{(figure\*?|table\*?|wrapfigure|wraptable|algorithm\*?)\}(?:\[[^\]]*\]|\{[^{}]*\})*.*?\\end\{\1\}", re.DOTALL)
LATEX_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
LATEX_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
LATEX_BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\{([^}]+)\}")
LATEX_ADD_BIB_RESOURCE_RE = re.compile(r"\\addbibresource(?:\[[^\]]*\])?\{([^}]+)\}")
LATEX_APPENDIX_RE = re.compile(r"\\appendix\b")
LATEX_DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[(?P<options>[^\]]*)\])?\{(?P<class>[^}]+)\}")
LATEX_SECTION_WITH_LABEL_RE = re.compile(
    r"\\(?:section|subsection)\*?(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}"
    r"(?P<between>(?:\s|%[^\n]*(?:\n|$)|\\label\{[^{}]+\}){0,800})",
    re.DOTALL,
)
ANONYMOUS_FRONT_MATTER_RE = re.compile(
    r"\bAnonymous(?:\s+(?:ACL|ARR|EMNLP|NeurIPS|ICLR|ICML|submission|authors?|paper|manuscript)){0,4}\b|"
    r"\bsubmitted\s+anonymously\b|\banonymous\s+submission\b|\banonymous\s+authors?\b",
    re.IGNORECASE,
)
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])(\s+)(?=[A-Z0-9\"'“‘(])")
SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
LEGACY_REVIEW_IMPORT_SECTION_LABELS = {
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
REPORT_SECTION_LABELS = {
    "global-findings": "全局重要问题",
    "coverage-receipt": "覆盖回执",
}
RENDER_GROUP_LABELS = {
    "layout": "编译版式检查",
    "numeric": "表格数值检查",
    "figure_caption": "图表说明检查",
    "compiled-display-checks": "编译后展示检查",
    "submission-readiness": "编译后展示检查",
}
SUBMISSION_DOMAINS = {"layout", "numeric", "reference", "symbol", "source_hygiene", "figure_caption", "polish"}
ISSUE_ARTIFACT_RENDER_DOMAINS = {"layout", "numeric", "figure_caption"}
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


def is_artifact_only(item: dict[str, object]) -> bool:
    visibility = str(
        item.get("render_visibility")
        or item.get("visibility")
        or item.get("student_visibility")
        or ""
    ).strip().lower()
    if visibility in {"artifact_only", "audit_only", "hidden"}:
        return True
    if visibility in {"student_visible", "visible", "render"}:
        return False
    if str(item.get("student_visible") or "").strip().lower() in {"0", "false", "no"}:
        return True
    return False


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
                if str(item.get("render_visibility") or "").strip().lower() in {"student_visible", "visible", "render"}:
                    fallback = normalize_finding_content(item, idx)
                    fallback["target_level"] = "paper"
                    fallback["paper_id"] = "paper"
                    return [fallback]
                return []
            raise SystemExit(f"annotation #{idx} missing target id for `{anchor_level}` annotation")
    anchor_ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
    raw_severity = str(item.get("severity") or "").strip().lower()
    if raw_severity and raw_severity not in SEVERITY_LABELS:
        raise SystemExit(f"annotation #{idx} has invalid severity `{raw_severity}`")
    raw_issue_type = str(item.get("issue_type") or item.get("type") or "").strip()
    if not raw_issue_type and source == "findings":
        raw_issue_type = issue_type_from_text(
            str(item.get("location") or ""),
            str(item.get("title") or ""),
            str(item.get("diagnosis") or ""),
            str(item.get("evidence_basis") or ""),
            str(item.get("reported_value") or ""),
            str(item.get("visible_computed_value") or ""),
        )
    base = {
        "issue_id": item.get("issue_id") or item.get("id") or f"A{idx}",
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
        if raw_severity:
            annotation["severity"] = raw_severity
        if raw_issue_type:
            annotation["issue_type"] = raw_issue_type
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
        if is_artifact_only(item):
            continue
        annotations.extend(normalize_annotation_item(item, idx, source=source))
    return annotations


def normalize_finding_content(item: dict[str, object], idx: int) -> dict[str, str]:
    severity = str(item.get("severity", "major")).strip().lower()
    if severity not in SEVERITY_LABELS:
        severity = "major"
    issue_id = str(item.get("id") or item.get("issue_id") or f"F{idx}")
    issue_type = str(item.get("issue_type") or item.get("type") or "").strip()
    if not issue_type:
        issue_type = issue_type_from_text(
            str(item.get("location") or ""),
            str(item.get("title") or ""),
            str(item.get("diagnosis") or ""),
            str(item.get("evidence_basis") or ""),
            str(item.get("reported_value") or ""),
            str(item.get("visible_computed_value") or ""),
        )
    return {
        "issue_id": issue_id,
        "severity": severity,
        "issue_type": issue_type,
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
        if is_artifact_only(item):
            continue
        finding_id = str(item.get("id") or item.get("issue_id") or "").strip()
        if not finding_id:
            raise SystemExit(f"finding #{idx} missing `id`")
        normalized = normalize_annotation_item({**item, "issue_id": finding_id}, idx, source="findings")
        if normalized:
            finding = dict(normalized[0])
        else:
            finding = normalize_finding_content({**item, "issue_id": finding_id}, idx)
        source_issue_ids = item.get("source_issue_ids")
        if isinstance(source_issue_ids, list):
            finding["source_issue_ids"] = [str(value) for value in source_issue_ids if str(value or "").strip()]
        output[finding_id] = finding
    return output


def load_findings_rows(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("findings", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("findings JSON must be a list or an object with a `findings` list")
    return [row for row in rows if isinstance(row, dict) and not is_artifact_only(row)]


def render_group_label(value: object, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return RENDER_GROUP_LABELS.get(text, text)


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
    if domain not in ISSUE_ARTIFACT_RENDER_DOMAINS:
        return []
    issues = payload.get("issues", [])
    if not isinstance(issues, list):
        raise SystemExit(f"issue artifact `{path}` must contain an `issues` list")
    annotations: list[dict[str, str]] = []
    for idx, issue in enumerate(issues, 1):
        if not isinstance(issue, dict):
            raise SystemExit(f"issue artifact `{path}` issue #{idx} must be an object")
        if is_artifact_only(issue):
            continue
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
            "source_section_label": render_group_label(render_hint.get("display_group"), domain),
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
            if anchor.startswith("page:"):
                annotation["page_anchor"] = anchor
        normalized = normalize_annotation_item(annotation, idx, source="annotations")
        if not normalized:
            continue
        for item in normalized:
            if target_level == "paper" and anchor.startswith("page:"):
                item["paper_id"] = paper_target_id(item, idx)
                item["page_anchor"] = anchor
                item["source_section_label"] = item.get("source_section_label") or render_group_label(domain, domain)
            annotations.append(item)
    return annotations


def load_issue_artifact_annotations(issues_dir: Path | None) -> list[dict[str, str]]:
    annotations: list[dict[str, str]] = []
    for path in issue_artifact_paths(issues_dir):
        annotations.extend(issue_artifact_to_annotations(path))
    return annotations


def compiled_source_issue_ids(findings_by_id: dict[str, dict[str, str]]) -> set[str]:
    source_ids: set[str] = set()
    for finding in findings_by_id.values():
        values = finding.get("source_issue_ids")
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text:
                    source_ids.add(text)
    return source_ids


def filter_compiled_issue_artifact_annotations(
    annotations: list[dict[str, str]],
    findings_by_id: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    source_ids = compiled_source_issue_ids(findings_by_id)
    if not source_ids:
        return annotations
    return [annotation for annotation in annotations if annotation.get("issue_id", "") not in source_ids]


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
    for section_id, section_label in LEGACY_REVIEW_IMPORT_SECTION_LABELS.items():
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


def class_names(tag: Tag) -> list[str]:
    classes = tag.get("class", [])
    if isinstance(classes, str):
        return classes.split()
    return [str(item) for item in classes]


def has_class(tag: Tag, class_name: str) -> bool:
    return class_name in class_names(tag)


def is_layout_parameter_text(value: str) -> bool:
    text = normalized_text(BeautifulSoup(f"<span>{html.escape(value)}</span>", "html.parser").span)
    if not text:
        return False
    if text.lower().startswith("max width="):
        return True
    return bool(LAYOUT_PARAM_RE.fullmatch(text))


def add_class(tag: Tag, class_name: str) -> None:
    classes = class_names(tag)
    if class_name not in classes:
        classes.append(class_name)
    tag["class"] = classes


def latex_package_options(tex_path: Path, package: str) -> set[str] | None:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    package = package.strip()
    for match in LATEX_USEPACKAGE_RE.finditer(expanded):
        packages = [item.strip() for item in match.group("packages").split(",")]
        if package not in packages:
            continue
        options = match.group("options") or ""
        return {item.strip().lower() for item in options.split(",") if item.strip()}
    return None


def latex_documentclass_options(tex_path: Path) -> set[str]:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    match = LATEX_DOCUMENTCLASS_RE.search(expanded)
    if match is None:
        return set()
    options = match.group("options") or ""
    return {item.strip().lower() for item in options.split(",") if item.strip()}


def latex_source_requests_two_column(tex_path: Path) -> bool:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    return "twocolumn" in latex_documentclass_options(tex_path) or bool(re.search(r"\\twocolumn\b", expanded))


PDF_BBOX_PAGE_RE = re.compile(r"<page\b(?P<attrs>[^>]*)>", re.IGNORECASE)
PDF_BBOX_LINE_RE = re.compile(r"<line\b(?P<attrs>[^>]*)>", re.IGNORECASE)
PDF_BBOX_ATTR_RE = re.compile(r'([A-Za-z][\w:-]*)="([^"]*)"')


def pdf_bbox_attrs(raw_attrs: str) -> dict[str, float]:
    attrs: dict[str, float] = {}
    for key, value in PDF_BBOX_ATTR_RE.findall(raw_attrs):
        try:
            attrs[key] = float(value)
        except ValueError:
            continue
    return attrs


def pdf_page_line_boxes(pdf_path: Path, *, max_pages: int = 6) -> list[dict[str, object]]:
    pdftotext = shutil.which("pdftotext")
    if not pdf_path.exists() or not pdftotext:
        return []
    pages: list[dict[str, object]] = []
    for page_number in range(1, max_pages + 1):
        try:
            result = subprocess.run(
                [pdftotext, "-f", str(page_number), "-l", str(page_number), "-bbox-layout", str(pdf_path), "-"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            break
        if result.returncode != 0:
            break
        page_match = PDF_BBOX_PAGE_RE.search(result.stdout)
        if page_match is None:
            continue
        page_attrs = pdf_bbox_attrs(page_match.group("attrs"))
        lines = [pdf_bbox_attrs(match.group("attrs")) for match in PDF_BBOX_LINE_RE.finditer(result.stdout)]
        lines = [line for line in lines if line.get("xMax", 0) > line.get("xMin", 0)]
        pages.append(
            {
                "width": page_attrs.get("width", 0.0),
                "height": page_attrs.get("height", 0.0),
                "lines": lines,
            }
        )
    return pages


def median_float(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def pdf_page_two_column_signal(page: dict[str, object]) -> bool | None:
    width = float(page.get("width") or 0)
    height = float(page.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    raw_lines = page.get("lines") or []
    if not isinstance(raw_lines, list):
        return None
    body_lines: list[dict[str, float]] = []
    for line in raw_lines:
        if not isinstance(line, dict):
            continue
        x_min = float(line.get("xMin") or 0)
        x_max = float(line.get("xMax") or 0)
        y_min = float(line.get("yMin") or 0)
        line_width = x_max - x_min
        if line_width <= width * 0.035:
            continue
        if height * 0.10 <= y_min <= height * 0.93:
            body_lines.append(
                {
                    "xMin": x_min,
                    "xMax": x_max,
                    "center": (x_min + x_max) / 2,
                    "width": line_width,
                }
            )
    if len(body_lines) < 12:
        return None
    narrow_lines = [line for line in body_lines if line["width"] <= width * 0.52]
    left_lines = [line for line in narrow_lines if line["center"] < width * 0.48 and line["xMax"] < width * 0.56]
    right_lines = [line for line in narrow_lines if line["center"] > width * 0.52 and line["xMin"] > width * 0.44]
    full_width_lines = [
        line
        for line in body_lines
        if line["width"] >= width * 0.58 and line["xMin"] < width * 0.32 and line["xMax"] > width * 0.68
    ]
    per_side_threshold = max(6, int(len(body_lines) * 0.18))
    if len(left_lines) >= per_side_threshold and len(right_lines) >= per_side_threshold:
        gutter = median_float([line["xMin"] for line in right_lines]) - median_float([line["xMax"] for line in left_lines])
        if gutter >= max(18.0, width * 0.04) and len(full_width_lines) <= max(8, int(len(body_lines) * 0.40)):
            return True
    if len(full_width_lines) >= max(6, int(len(body_lines) * 0.45)):
        return False
    if len(left_lines) < 4 or len(right_lines) < 4:
        return False
    return None


def compiled_pdf_two_column_signal(pdf_path: Path) -> bool | None:
    classified: list[bool] = []
    for page in pdf_page_line_boxes(pdf_path):
        signal = pdf_page_two_column_signal(page)
        if signal is not None:
            classified.append(signal)
    if not classified:
        return None
    two_column_pages = sum(1 for signal in classified if signal)
    if two_column_pages == 0:
        return False
    return two_column_pages >= 2 or two_column_pages / len(classified) >= 0.34


def pdf_looks_two_column(pdf_path: Path) -> bool:
    return compiled_pdf_two_column_signal(pdf_path) is True


def is_acl_review_mode(tex_path: Path) -> bool:
    options = latex_package_options(tex_path, "acl")
    return options is not None and "review" in options


def pdf_first_page_text(pdf_path: Path) -> str:
    if not pdf_path.exists() or shutil.which("pdftotext") is None:
        return ""
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "1", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout


def first_page_front_matter_text(pdf_path: Path) -> str:
    text = pdf_first_page_text(pdf_path)
    if not text.strip():
        return ""
    match = re.search(r"\b(Abstract|Introduction|1\s+Introduction)\b", text, re.IGNORECASE)
    return text[: match.start()] if match else text[:2000]


def pdf_front_matter_is_anonymous(tex_path: Path) -> bool:
    front_matter = first_page_front_matter_text(tex_path.with_suffix(".pdf"))
    return bool(front_matter and ANONYMOUS_FRONT_MATTER_RE.search(front_matter))


def compiled_front_matter_is_anonymous(soup: BeautifulSoup) -> bool:
    author = soup.select_one(".paper-author, .author")
    if not isinstance(author, Tag):
        return False
    text = normalize_for_match(normalized_text(author))
    anonymous_markers = {
        "anonymous acl submission",
        "anonymous submission",
        "anonymous authors",
        "anonymous author",
        "anonymous arr submission",
        "anonymous emnlp submission",
        "anonymous neurips submission",
        "submitted anonymously",
    }
    if any(str(author.get(attr) or "").strip().lower() == "true" for attr in ("data-acl-review-anonymous", "data-anonymous-front-matter")):
        return True
    return bool(text in anonymous_markers or text.startswith("anonymous ") or "submitted anonymously" in text)


def resolve_paper_layout(tex_path: Path, requested: str = "source") -> str:
    requested = (requested or "source").strip().lower()
    if requested in {"single", "two-column", "paged", "paged-two-column"}:
        return requested
    pdf_path = tex_path.with_suffix(".pdf")
    if pdf_path.exists():
        pdf_two_column = compiled_pdf_two_column_signal(pdf_path)
        return "paged-two-column" if pdf_two_column is True else "paged"
    return "two-column" if latex_source_requests_two_column(tex_path) else "single"


def front_matter_header(soup: BeautifulSoup) -> Tag | None:
    header = soup.find("header", id="title-block-header")
    if isinstance(header, Tag):
        return header
    header = soup.find(id="title-block-header")
    return header if isinstance(header, Tag) else None


def mark_front_matter_node(node: Tag, role: str) -> None:
    node["data-paper-role"] = role
    node["data-review-skip"] = "front-matter"


def normalize_front_matter(soup: BeautifulSoup, tex_path: Path) -> None:
    """Make pandoc's title block match venue review-mode front matter."""

    header = front_matter_header(soup)
    title = None
    if header is not None:
        title = header.find("h1", class_="title") or header.find("h1")
    if title is None:
        title = soup.find("h1", class_="title")
    if isinstance(title, Tag):
        add_class(title, "paper-title")
        mark_front_matter_node(title, "title")
        if not title.get("id"):
            title["id"] = compact_section_slug(normalized_text(title), "paper-title")

    if header is not None:
        insertion_point: Tag = header
        for abstract in list(header.find_all("div", class_="abstract", recursive=False)):
            extracted = abstract.extract()
            insertion_point.insert_after(extracted)
            insertion_point = extracted

    author_nodes: list[Tag] = []
    if header is not None:
        author_nodes.extend(tag for tag in header.find_all(["p", "div"], class_="author", recursive=False) if isinstance(tag, Tag))
    if not author_nodes:
        author_nodes.extend(tag for tag in soup.find_all(["p", "div"], class_="author") if isinstance(tag, Tag))

    if is_acl_review_mode(tex_path) or pdf_front_matter_is_anonymous(tex_path):
        if not author_nodes and isinstance(title, Tag):
            author = soup.new_tag("p")
            author["class"] = ["author"]
            title.insert_after(author)
            author_nodes = [author]
        for extra in author_nodes[1:]:
            extra.decompose()
        if author_nodes:
            author = author_nodes[0]
            author.clear()
            for attr in (
                "data-paragraph-id",
                "data-has-issue",
                "data-severity",
                "data-issue-type",
                "data-issue-ids",
                "aria-describedby",
                "onclick",
                "onkeydown",
                "role",
                "tabindex",
            ):
                if author.has_attr(attr):
                    del author[attr]
            add_class(author, "paper-author")
            add_class(author, "paper-anonymous-author")
            author["data-acl-review-anonymous"] = "true"
            author["data-anonymous-front-matter"] = "true"
            mark_front_matter_node(author, "author")
            author.string = "Anonymous ACL submission" if is_acl_review_mode(tex_path) else "Anonymous submission"
    else:
        for author in author_nodes:
            add_class(author, "paper-author")
            mark_front_matter_node(author, "author")


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
    text = strip_latex_comments(text)

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


def latex_braced_content(text: str, open_brace_idx: int) -> tuple[str, int] | None:
    if open_brace_idx < 0 or open_brace_idx >= len(text) or text[open_brace_idx] != "{":
        return None
    depth = 0
    escaped = False
    for idx in range(open_brace_idx, len(text)):
        char = text[idx]
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "{" and not escaped:
            depth += 1
        elif char == "}" and not escaped:
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1 : idx], idx + 1
        escaped = False
    return None


def latex_command_braced_arg(block: str, command: str) -> str:
    match = re.search(rf"\\{re.escape(command)}(?:\[[^\]]*\])?\s*\{{", block)
    if not match:
        return ""
    parsed = latex_braced_content(block, match.end() - 1)
    return parsed[0].strip() if parsed else ""


def tabular_content(block: str) -> str:
    match = re.search(r"\\begin\{tabular\}", block)
    if not match:
        return ""
    idx = match.end()
    while idx < len(block) and block[idx].isspace():
        idx += 1
    if idx < len(block) and block[idx] == "[":
        end_opt = block.find("]", idx + 1)
        if end_opt == -1:
            return ""
        idx = end_opt + 1
        while idx < len(block) and block[idx].isspace():
            idx += 1
    if idx >= len(block) or block[idx] != "{":
        return ""
    parsed_spec = latex_braced_content(block, idx)
    if parsed_spec is None:
        return ""
    content_start = parsed_spec[1]
    depth = 1
    env_re = re.compile(r"\\(begin|end)\{tabular\}")
    for env_match in env_re.finditer(block, content_start):
        if env_match.group(1) == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return block[content_start : env_match.start()]
    return ""


def latex_label_units(tex_path: Path) -> list[dict[str, object]]:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    units: list[dict[str, object]] = []
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
            units.append(
                {
                    "kind": kind,
                    "label": label,
                    "asset": asset,
                    "env": env,
                    "wide": env.endswith("*"),
                    "caption": latex_command_braced_arg(block, "caption"),
                    "tabular": tabular_content(block) if kind == "table" else "",
                }
            )
    return units


def mark_latex_float_widths(soup: BeautifulSoup, tex_path: Path) -> int:
    marked = 0
    for unit in latex_label_units(tex_path):
        label = str(unit.get("label") or "")
        if not label:
            continue
        kind = str(unit.get("kind") or "")
        target = latex_label_target(soup, label, "figure" if kind == "figure" else "table" if kind == "table" else None)
        if target is None:
            continue
        classes = [class_name for class_name in class_names(target) if class_name not in {"paper-float-single", "paper-float-wide"}]
        target["class"] = classes
        if bool(unit.get("wide")):
            add_class(target, "paper-float-wide")
        else:
            add_class(target, "paper-float-single")
        marked += 1
    return marked


def split_latex_table_rows(tabular: str) -> list[list[str]]:
    rows: list[list[str]] = []
    current: list[str] = []
    cell: list[str] = []
    brace_depth = 0
    env_depth = 0
    idx = 0
    while idx < len(tabular):
        if tabular.startswith("\\begin{tabular}", idx):
            env_depth += 1
            cell.append("\\begin{tabular}")
            idx += len("\\begin{tabular}")
            continue
        if tabular.startswith("\\end{tabular}", idx):
            env_depth = max(0, env_depth - 1)
            cell.append("\\end{tabular}")
            idx += len("\\end{tabular}")
            continue
        if tabular.startswith("\\\\", idx) and brace_depth == 0 and env_depth == 0:
            current.append("".join(cell).strip())
            cell = []
            if any(part.strip() for part in current):
                rows.append(current)
            current = []
            idx += 2
            continue
        char = tabular[idx]
        if char == "\\":
            command = re.match(r"\\[A-Za-z]+", tabular[idx:])
            if command and command.group(0) in {"\\toprule", "\\midrule", "\\bottomrule"} and brace_depth == 0 and env_depth == 0:
                idx += len(command.group(0))
                continue
            cell.append(char)
            if idx + 1 < len(tabular):
                cell.append(tabular[idx + 1])
                idx += 2
                continue
        if char == "{" and (idx == 0 or tabular[idx - 1] != "\\"):
            brace_depth += 1
        elif char == "}" and (idx == 0 or tabular[idx - 1] != "\\"):
            brace_depth = max(0, brace_depth - 1)
        if char == "&" and brace_depth == 0 and env_depth == 0:
            current.append("".join(cell).strip())
            cell = []
        else:
            cell.append(char)
        idx += 1
    trailing = "".join(cell).strip()
    if trailing:
        current.append(trailing)
    if any(part.strip() for part in current):
        rows.append(current)
    return rows


def strip_latex_environment_begin(text: str, env: str) -> str:
    pattern = re.compile(rf"\\begin\{{{re.escape(env)}\}}")
    parts: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        parts.append(text[cursor : match.start()])
        idx = match.end()
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx < len(text) and text[idx] == "[":
            opt_end = text.find("]", idx + 1)
            if opt_end != -1:
                idx = opt_end + 1
                while idx < len(text) and text[idx].isspace():
                    idx += 1
        if idx < len(text) and text[idx] == "{":
            parsed = latex_braced_content(text, idx)
            if parsed is not None:
                idx = parsed[1]
        cursor = idx
    parts.append(text[cursor:])
    return "".join(parts)


def latex_inline_to_html(soup: BeautifulSoup, value: str) -> list[object]:
    text = strip_latex_environment_begin(value.strip(), "tabular")
    text = text.replace("\\end{tabular}", "")
    text = text.replace("\\toprule", "").replace("\\midrule", "").replace("\\bottomrule", "")
    text = text.replace("\\textwidth", "")
    text = re.sub(r"@\{\}", "", text)
    text = re.sub(r"L\{[^{}]*\}", "", text)
    text = re.sub(r"\\(?:citet|citep|cite|ref)\{([^{}]*)\}", r"[\1]", text)
    text = re.sub(r"~", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text).strip()
    parts: list[object] = []
    cursor = 0

    def append_text_segment(segment: str) -> None:
        segment = segment.replace("\\%", "%").replace("\\_", "_").replace("\\&", "&")
        segment = segment.replace("\\{", "{").replace("\\}", "}").replace("\\$", "$").replace("\\#", "#")
        segment = segment.replace("\\,", " ").replace("\\;", " ")
        if segment:
            parts.append(NavigableString(segment))

    def math_text(segment: str) -> str:
        replacements = {
            r"\le": "≤",
            r"\ge": "≥",
            r"\in": "∈",
            r"\times": "×",
            r"\pm": "±",
        }
        for raw, rendered in replacements.items():
            segment = segment.replace(raw, rendered)
        segment = segment.replace("\\{", "{").replace("\\}", "}").replace("\\%", "%").replace("\\_", "_")
        segment = re.sub(r"\\(?:mathrm|text)\{([^{}]*)\}", r"\1", segment)
        segment = segment.replace("\\left", "").replace("\\right", "")
        return re.sub(r"\s+", " ", segment).strip()

    inline_re = re.compile(r"\$([^$]+)\$|\\\\|\\(textbf|textit|emph|texttt|num)\{([^{}]*)\}")
    for match in inline_re.finditer(text):
        if match.start() > cursor:
            append_text_segment(text[cursor : match.start()])
        if match.group(0) == "\\\\":
            parts.append(soup.new_tag("br"))
        elif match.group(1) is not None:
            span = soup.new_tag("span")
            span["class"] = "math-inline"
            span.string = math_text(match.group(1))
            parts.append(span)
        else:
            command = match.group(2)
            body = match.group(3) or ""
            if command == "textbf":
                node = soup.new_tag("strong")
                for child in latex_inline_to_html(soup, body):
                    node.append(child)
                parts.append(node)
            elif command in {"textit", "emph"}:
                node = soup.new_tag("em")
                for child in latex_inline_to_html(soup, body):
                    node.append(child)
                parts.append(node)
            elif command == "texttt":
                code = soup.new_tag("code")
                code.string = body
                parts.append(code)
            else:
                append_text_segment(body)
        cursor = match.end()
    if cursor < len(text):
        append_text_segment(text[cursor:])
    return parts or [NavigableString("")]


def append_latex_inline(soup: BeautifulSoup, tag: Tag, value: str) -> None:
    for part in latex_inline_to_html(soup, value):
        tag.append(part)


def rebuilt_table_from_latex(soup: BeautifulSoup, unit: dict[str, object], table_number: int) -> Tag | None:
    tabular = str(unit.get("tabular") or "")
    rows = split_latex_table_rows(tabular)
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return None
    wrapper = soup.new_tag("div")
    wrapper["class"] = ["table*" if unit.get("wide") else "table", "paper-table", "paper-table-rebuilt"]
    if unit.get("wide"):
        wrapper["class"].append("paper-float-wide")
    else:
        wrapper["class"].append("paper-float-single")
    label = str(unit.get("label") or "")
    if label:
        wrapper["id"] = label
    table = soup.new_tag("table")
    table["class"] = "paper-rebuilt-table"
    caption_text = str(unit.get("caption") or "").strip()
    if caption_text:
        caption = soup.new_tag("caption")
        strong = soup.new_tag("strong")
        strong.string = f"Table {table_number}: "
        caption.append(strong)
        append_latex_inline(soup, caption, caption_text)
        table.append(caption)
    header, body_rows = rows[0], rows[1:]
    thead = soup.new_tag("thead")
    tr = soup.new_tag("tr")
    for cell_text in header:
        th = soup.new_tag("th")
        append_latex_inline(soup, th, cell_text)
        tr.append(th)
    thead.append(tr)
    table.append(thead)
    tbody = soup.new_tag("tbody")
    for row in body_rows:
        tr = soup.new_tag("tr")
        for cell_text in row:
            td = soup.new_tag("td")
            append_latex_inline(soup, td, cell_text)
            tr.append(td)
        tbody.append(tr)
    table.append(tbody)
    wrapper.append(table)
    return wrapper


def replace_broken_latex_tables(soup: BeautifulSoup, tex_path: Path) -> int:
    replaced = 0
    table_number = 0
    for unit in latex_label_units(tex_path):
        if unit.get("kind") != "table":
            continue
        table_number += 1
        label = str(unit.get("label") or "")
        if not label:
            continue
        target = latex_label_target(soup, label, "table")
        if not isinstance(target, Tag):
            continue
        target_text = normalized_text(target)
        broken = target.find("table") is None or "@L" in target_text or " & " in target_text
        if not broken:
            continue
        rebuilt = rebuilt_table_from_latex(soup, unit, table_number)
        if rebuilt is None:
            continue
        target.replace_with(rebuilt)
        replaced += 1
    return replaced


def add_float_caption_numbers(soup: BeautifulSoup, tex_path: Path) -> int:
    counters = {"figure": 0, "table": 0}
    updated = 0
    for unit in latex_label_units(tex_path):
        kind = str(unit.get("kind") or "")
        if kind not in counters:
            continue
        counters[kind] += 1
        label = str(unit.get("label") or "")
        target = latex_label_target(soup, label, kind)
        if not isinstance(target, Tag):
            continue
        caption = target.find("figcaption") or target.find("caption")
        caption_text = str(unit.get("caption") or "").strip()
        if caption is None and caption_text:
            caption = soup.new_tag("figcaption" if kind == "figure" else "caption")
            if kind == "figure":
                target.append(caption)
            else:
                table = target.find("table")
                if isinstance(table, Tag):
                    table.insert(0, caption)
                else:
                    target.insert(0, caption)
        if not isinstance(caption, Tag):
            continue
        if caption_text:
            caption.clear()
            append_latex_inline(soup, caption, caption_text)
        prefix = f"{'Figure' if kind == 'figure' else 'Table'} {counters[kind]}:"
        if normalized_text(caption).lower().startswith(prefix.lower()):
            continue
        strong = soup.new_tag("strong")
        strong.string = f"{prefix} "
        caption.insert(0, strong)
        updated += 1
    return updated


def latex_float_number_map(tex_path: Path) -> dict[str, str]:
    counters = {"figure": 0, "table": 0}
    numbers: dict[str, str] = {}
    for unit in latex_label_units(tex_path):
        kind = str(unit.get("kind") or "")
        if kind not in counters:
            continue
        counters[kind] += 1
        label = str(unit.get("label") or "")
        if label:
            numbers[label] = str(counters[kind])
    return numbers


def sync_float_reference_numbers(soup: BeautifulSoup, tex_path: Path) -> int:
    float_numbers = latex_float_number_map(tex_path)
    updated = 0
    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue
        ref = str(link.get("data-reference") or "").strip()
        href = str(link.get("href") or "").strip()
        if not ref and href.startswith("#"):
            ref = href[1:]
        number = float_numbers.get(ref)
        if not number:
            continue
        current = normalized_text(link)
        if current and current not in {ref, f"[{ref}]"} and not re.fullmatch(r"\[?\d+\]?", current):
            continue
        link.clear()
        link.append(NavigableString(number))
        updated += 1
    return updated


def mark_latex_paragraph_headings(soup: BeautifulSoup, tex_path: Path) -> int:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    titles = {normalize_for_match(match.group(1)) for match in re.finditer(r"\\paragraph\{([^{}]+)\}", expanded)}
    marked = 0
    for heading in soup.find_all(["h4", "h5", "h6"]):
        if normalize_for_match(normalized_text(heading)) in titles:
            add_class(heading, "paper-run-in-heading")
            heading.attrs.pop("data-section-number", None)
            marked += 1
    return marked


def bibliography_before_appendix(tex_path: Path) -> bool:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    bib_match = LATEX_BIBLIOGRAPHY_RE.search(expanded) or re.search(r"\\printbibliography\b", expanded)
    appendix_match = LATEX_APPENDIX_RE.search(expanded)
    return bool(bib_match and appendix_match and bib_match.start() < appendix_match.start())


def latex_appendix_heading_ids(tex_path: Path) -> list[str]:
    expanded = strip_latex_comments(read_latex_tree(tex_path))
    appendix_match = LATEX_APPENDIX_RE.search(expanded)
    if appendix_match is None:
        return []
    heading_ids: list[str] = []
    for match in LATEX_SECTION_WITH_LABEL_RE.finditer(expanded, appendix_match.end()):
        labels = LATEX_LABEL_RE.findall(match.group("between") or "")
        if labels:
            heading_ids.extend(labels)
            continue
        heading_ids.append(compact_section_slug(match.group(1), f"appendix-{len(heading_ids) + 1}"))
    return ordered_unique(heading_ids)


def first_appendix_heading(soup: BeautifulSoup, tex_path: Path | None = None) -> Tag | None:
    appendix_ids = latex_appendix_heading_ids(tex_path) if tex_path is not None else []
    for heading_id in appendix_ids:
        heading = soup.find(id=heading_id)
        if isinstance(heading, Tag):
            return heading
    for heading in soup.find_all(["h1", "h2"]):
        heading_id = str(heading.get("id") or "").lower()
        text = normalized_text(heading).lower()
        if heading_id.startswith(("app:", "apd:", "appendix")) or text.startswith("appendix"):
            return heading
        if heading_id in {"sec:proof", "proof-of-the-theoretical-analysis"}:
            return heading
    return None


def restore_bibliography_position(soup: BeautifulSoup, tex_path: Path) -> bool:
    if not bibliography_before_appendix(tex_path):
        return False
    refs_heading = soup.find(id="references")
    refs_body = soup.find(id="refs")
    appendix_heading = first_appendix_heading(soup, tex_path)
    if not isinstance(refs_heading, Tag) or not isinstance(refs_body, Tag) or not isinstance(appendix_heading, Tag):
        return False
    if refs_heading.find_next_sibling(id="refs") is not refs_body:
        return False
    if refs_heading.find_next("h1") is appendix_heading:
        return False
    move_nodes: list[Tag] = [refs_heading.extract(), refs_body.extract()]
    footnotes = soup.find(id="footnotes")
    if isinstance(footnotes, Tag):
        move_nodes.append(footnotes.extract())
    for node in move_nodes:
        appendix_heading.insert_before(node)
    return True


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


def insert_label_anchor_before(soup: BeautifulSoup, target: Tag, label: str) -> Tag:
    anchor = soup.new_tag("span")
    anchor["id"] = label
    anchor["class"] = "paper-latex-label-anchor"
    anchor["aria-hidden"] = "true"
    target.insert_before(anchor)
    return anchor


def node_or_ancestor_has_id(node: Tag) -> bool:
    current: Tag | None = node
    while current is not None:
        if current.get("id"):
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


def is_float_container(node: Tag, kind: str | None = None) -> bool:
    classes = class_names(node)
    if node.name == "figure":
        return kind in {None, "figure"}
    if node.name == "table":
        return kind in {None, "table"}
    table_classes = {"table", "table*", "wraptable", "paper-table", "paper-table-rebuilt"}
    figure_classes = {"figure", "figure*", "wrapfigure", "paper-figure"}
    generic_float_classes = {"paper-float", "paper-float-single", "paper-float-wide"}
    if kind in {None, "table"} and any(
        class_name in table_classes or class_name.startswith("table") for class_name in classes
    ):
        return True
    if kind in {None, "figure"} and any(
        class_name in figure_classes or class_name.startswith("figure") for class_name in classes
    ):
        return True
    if any(class_name in generic_float_classes for class_name in classes):
        if kind == "table":
            return node.find("table") is not None or str(node.get("id") or "").startswith("tab:")
        if kind == "figure":
            return node.find(["img", "svg", "embed"]) is not None or str(node.get("id") or "").startswith("fig:")
        return True
    node_id = str(node.get("id") or "")
    return (kind == "table" and node_id.startswith("tab:")) or (kind == "figure" and node_id.startswith("fig:"))


def float_container_for_node(node: Tag, kind: str | None = None) -> Tag:
    current: Tag | None = node
    fallback = node
    while current is not None:
        if current.name in {"body", "html"}:
            break
        if is_float_container(current, kind):
            fallback = current
        current = current.parent if isinstance(current.parent, Tag) else None
    return fallback


def latex_label_target(soup: BeautifulSoup, label: str, kind: str | None = None) -> Tag | None:
    target = soup.find(id=label)
    if not isinstance(target, Tag):
        return None
    if kind in {"table", "figure", "algorithm"} or has_class(target, "paper-latex-label-anchor"):
        return float_container_for_node(target, "figure" if kind == "figure" else "table" if kind == "table" else None)
    return target


def table_label_targets(soup: BeautifulSoup) -> list[Tag]:
    targets: list[Tag] = []
    for node in soup.find_all(["div", "figure", "table"]):
        if node.name != "table" and not is_float_container(node, "table"):
            continue
        target = float_container_for_node(node, "table")
        if target not in targets:
            targets.append(target)
    return targets


def latex_table_plain_text(value: str) -> str:
    text = strip_latex_environment_begin(value.strip(), "tabular")
    text = text.replace("\\end{tabular}", "")
    text = re.sub(r"\\(?:toprule|midrule|bottomrule|centering|small|scriptsize)\b", " ", text)
    text = re.sub(r"\\(?:textbf|textit|texttt|emph|num)\{([^{}]*)\}", r" \1 ", text)
    text = re.sub(r"\\(?:multicolumn|multirow)\{[^{}]*\}\{[^{}]*\}\{([^{}]*)\}", r" \1 ", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", " ", text)
    text = text.replace("\\%", "%").replace("\\_", "_")
    text = re.sub(r"[{}$&]", " ", text)
    text = text.replace("\\\\", " ")
    return re.sub(r"\s+", " ", text).strip()


def table_match_tokens_from_text(value: str) -> Counter[str]:
    text = normalize_for_match(latex_table_plain_text(value))
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower())
    stopwords = {"and", "the", "for", "with", "from", "into", "under", "over"}
    return Counter(token for token in tokens if token not in stopwords and (len(token) >= 2 or token.isdigit()))


def latex_table_unit_counter(unit: dict[str, object]) -> Counter[str]:
    rows = split_latex_table_rows(str(unit.get("tabular") or ""))
    return table_match_tokens_from_text(" ".join(cell for row in rows for cell in row))


def html_table_target_counter(target: Tag) -> Counter[str]:
    table = target if target.name == "table" else target.find("table")
    if isinstance(table, Tag):
        cells = [cell.get_text(" ", strip=True) for cell in table.find_all(["th", "td"])]
        if cells:
            return table_match_tokens_from_text(" ".join(cells))
    clone = BeautifulSoup(str(target), "lxml")
    for caption in clone.find_all(["caption", "figcaption"]):
        caption.decompose()
    return table_match_tokens_from_text(clone.get_text(" ", strip=True))


def table_content_match_score(target_counter: Counter[str], unit_counter: Counter[str]) -> tuple[int, int, float]:
    if not target_counter or not unit_counter:
        return 0, 0, 0.0
    overlap = sum((target_counter & unit_counter).values())
    unique_overlap = len(set(target_counter) & set(unit_counter))
    coverage = overlap / max(1, min(sum(target_counter.values()), sum(unit_counter.values())))
    return overlap, unique_overlap, coverage


def matched_table_targets_by_latex_content(
    table_targets: list[Tag], table_units: list[dict[str, object]]
) -> dict[str, Tag]:
    target_counters = [html_table_target_counter(target) for target in table_targets]
    unit_counters = [latex_table_unit_counter(unit) for unit in table_units]
    candidates: list[tuple[int, int, float, int, int]] = []
    for target_idx, target_counter in enumerate(target_counters):
        for unit_idx, unit_counter in enumerate(unit_counters):
            overlap, unique_overlap, coverage = table_content_match_score(target_counter, unit_counter)
            if overlap < 4 or unique_overlap < 3 or coverage < 0.35:
                continue
            candidates.append((overlap, unique_overlap, coverage, target_idx, unit_idx))
    candidates.sort(reverse=True)
    matched_targets: set[int] = set()
    matched_units: set[int] = set()
    by_label: dict[str, Tag] = {}
    for _overlap, _unique_overlap, _coverage, target_idx, unit_idx in candidates:
        if target_idx in matched_targets or unit_idx in matched_units:
            continue
        label = str(table_units[unit_idx].get("label") or "")
        if not label:
            continue
        by_label[label] = table_targets[target_idx]
        matched_targets.add(target_idx)
        matched_units.add(unit_idx)
    return by_label


def assign_label_to_float(soup: BeautifulSoup, target: Tag, label: str) -> bool:
    changed = False
    for duplicate in list(soup.find_all(id=label)):
        if duplicate is target:
            continue
        if has_class(duplicate, "paper-latex-label-anchor"):
            duplicate.decompose()
        else:
            del duplicate["id"]
        changed = True
    if target.get("id") != label:
        target["id"] = label
        changed = True
    return changed


def restore_mathml_labels(soup: BeautifulSoup) -> int:
    """Restore equation labels that pandoc leaves only inside MathML annotations."""

    existing_ids = {str(tag.get("id")) for tag in soup.find_all(id=True)}
    restored = 0
    for math_node in soup.find_all("math"):
        if not isinstance(math_node, Tag):
            continue
        annotation_text = "\n".join(annotation.get_text("\n", strip=False) for annotation in math_node.find_all("annotation"))
        labels = ordered_unique([match.group(1) for match in LATEX_LABEL_RE.finditer(annotation_text)])
        for label in labels:
            if not label or label in existing_ids:
                continue
            if not math_node.get("id"):
                math_node["id"] = label
                add_class(math_node, "paper-latex-label-target")
            else:
                insert_label_anchor_before(soup, math_node, label)
            existing_ids.add(label)
            restored += 1
    return restored


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

    table_targets = table_label_targets(soup)
    used_table_targets: set[int] = set()
    table_cursor = 0
    table_units = [unit for unit in units if unit["kind"] == "table"]
    content_matched_targets = matched_table_targets_by_latex_content(table_targets, table_units)
    for unit in table_units:
        label = str(unit["label"])
        matched_target = content_matched_targets.get(label)
        if matched_target is not None:
            if assign_label_to_float(soup, matched_target, label):
                restored += 1
            used_table_targets.add(id(matched_target))
            existing_ids.add(label)
            continue
        existing = latex_label_target(soup, label, "table")
        if existing is not None:
            used_table_targets.add(id(existing))
            continue
        while table_cursor < len(table_targets) and id(table_targets[table_cursor]) in used_table_targets:
            table_cursor += 1
        if table_cursor >= len(table_targets):
            continue
        target = table_targets[table_cursor]
        table_cursor += 1
        if not node_or_ancestor_has_id(target) or str(target.get("id") or "").startswith("tab:"):
            assign_label_to_float(soup, target, label)
        else:
            add_label_anchor(soup, target, label)
        existing_ids.add(label)
        used_table_targets.add(id(target))
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
    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"-\s+", "", text)
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


def is_source_only_identity_false_positive(annotation: dict[str, str], soup: BeautifulSoup) -> bool:
    if not compiled_front_matter_is_anonymous(soup):
        return False
    joined = normalize_for_match(
        " ".join(
            str(annotation.get(key, ""))
            for key in (
                "title",
                "short",
                "problem",
                "diagnosis",
                "why",
                "reader_friction",
                "task",
                "self_check",
                "severity_rationale",
            )
        )
    )
    if not joined:
        return False
    has_identity_claim = any(token in joined for token in ("暴露作者身份", "首页身份", "作者姓名", "author identity", "front matter exposes identity"))
    has_anonymous_context = any(token in joined for token in ("匿名评审", "acl review", "review mode", "double blind", "双盲"))
    return has_identity_claim and has_anonymous_context


def issue_label_text(annotation: dict[str, str], count: int = 1) -> str:
    severity = annotation.get("severity", "major")
    issue_type = annotation.get("issue_type", "prose") or "prose"
    short = annotation.get("short", "").strip() or annotation.get("title", "").strip()
    if short and len(short) <= 28 and count == 1:
        return short
    if count > 1:
        return f"{SEVERITY_SHORT_LABELS.get(severity, severity.title())} · {count} issues"
    return f"{SEVERITY_SHORT_LABELS.get(severity, severity.title())} · {issue_type}"


def paper_issue_button_text(annotation: dict[str, str], idx: int) -> str:
    title = re.sub(r"\s+", " ", annotation.get("short", "").strip() or annotation.get("title", "").strip())
    if title:
        return title if len(title) <= 42 else title[:41].rstrip() + "..."
    severity = annotation.get("severity", "major")
    issue_type = annotation.get("issue_type", "paper") or "paper"
    return f"{idx}. {SEVERITY_SHORT_LABELS.get(severity, severity.title())} · {issue_type}"


def paper_target_id(annotation: dict[str, str], idx: int) -> str:
    issue_id = annotation.get("issue_id", "").strip()
    if issue_id:
        safe_issue_id = re.sub(r"[^A-Za-z0-9_.:-]+", "-", issue_id).strip("-")
        if safe_issue_id:
            return f"paper-{safe_issue_id}"
    return f"paper-{idx}"


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
    bubble["title"] = label
    bubble["onclick"] = f"AriadnePaperReaderOpenAnnotation('{level}', this.getAttribute('data-{level}-id'))"
    bubble.string = "§" if level == "section" else label
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
    overview["aria-describedby"] = " ".join(
        card_id_for("paper", paper_target_id(annotation, idx), idx)
        for idx, annotation in enumerate(annotations, 1)
    )
    title = soup.new_tag("strong")
    title.string = "全文结构批注"
    overview.append(title)
    for idx, annotation in enumerate(annotations, 1):
        target_id = paper_target_id(annotation, idx)
        button = soup.new_tag("button")
        button["type"] = "button"
        button["class"] = "annotation-bubble paper"
        button["data-anchor-level"] = "paper"
        button["data-paper-id"] = target_id
        button["data-has-issue"] = "true"
        button["data-severity"] = annotation.get("severity", "major")
        button["data-issue-type"] = annotation.get("issue_type", "paper")
        button["data-issue-ids"] = annotation.get("issue_id", f"A{idx}")
        button["aria-describedby"] = card_id_for("paper", target_id, idx)
        button["onclick"] = "AriadnePaperReaderOpenAnnotation('paper', this.getAttribute('data-paper-id'))"
        button.string = paper_issue_button_text(annotation, idx)
        overview.append(button)
    first = body.find(["header", "h1", "p", "section", "article", "div"])
    if first is not None:
        first.insert_before(overview)
    else:
        body.append(overview)
    return overview


def assign_sentence_targets(soup: BeautifulSoup, annotations: list[dict[str, str]]) -> list[dict[str, str]]:
    annotations = [annotation for annotation in annotations if not is_source_only_identity_false_positive(annotation, soup)]
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
        if annotation.get("unanchored") == "true":
            annotation = dict(annotation)
            annotation["card_id"] = f"ann-unanchored-{idx}"
            annotation["target_level"] = level
            applied.append(annotation)
            continue
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
            target_annotation["paper_id"] = paper_target_id(target_annotation, card_idx)
            target_annotation["card_id"] = card_id_for("paper", target_annotation["paper_id"], card_idx)
    return applied


def is_inside_skipped_tag(node: Tag) -> bool:
    parent = node
    while parent is not None:
        if isinstance(parent, Tag):
            if parent.name in SKIP_PARENT_TAGS:
                return True
            if parent.get("data-review-skip"):
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
            if not node.get("id"):
                node["id"] = section_slug
            paragraph_index = 0
            if is_inside_skipped_tag(node):
                continue
        if is_inside_skipped_tag(node):
            if node.name in SENTENCE_CONTAINER_TAGS and normalized_text(node):
                paragraph_index += 1
            continue
        if node.name not in SENTENCE_CONTAINER_TAGS:
            continue
        paragraph_index += 1
        if node.name in {"p", "li", "figcaption", "caption"} and not node.get("data-paragraph-id"):
            node["data-paragraph-id"] = f"p-{section_slug}-{paragraph_index:03d}"
        total_sentences += wrap_sentence_container(node, soup, section_slug, paragraph_index)
    return total_sentences


def heading_already_numbered(text: str) -> bool:
    return bool(re.match(r"^\s*(?:\d+(?:\.\d+)*|[A-Z])\.?\s+", text))


def integer_to_alpha(index: int) -> str:
    if index <= 0:
        return str(index)
    letters: list[str] = []
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters))


def is_appendix_heading(heading: Tag, appendix_ids: set[str], appendix_started: bool) -> bool:
    heading_id = str(heading.get("id") or "").strip().lower()
    text = normalized_text(heading).lower().strip()
    if heading_id in appendix_ids:
        return True
    if heading_id.startswith(("app:", "apd:", "appendix")):
        return True
    if text.startswith("appendix"):
        return True
    if appendix_started and heading.name == "h1" and heading_id not in {"references", "neurips-paper-checklist"}:
        return True
    return False


def ensure_display_section_numbers(soup: BeautifulSoup, tex_path: Path | None = None) -> None:
    body = soup.body or soup
    counters: dict[int, int] = {}
    appendix_counters: dict[int, int] = {}
    first_numbered_level: int | None = None
    appendix_first_level: int | None = None
    appendix_started = False
    appendix_ids = {value.lower() for value in latex_appendix_heading_ids(tex_path)} if tex_path is not None else set()
    skip_titles = {
        "abstract",
        "references",
        "acknowledgements",
        "acknowledgments",
        "neurips paper checklist",
    }
    for heading in body.find_all(["h1", "h2", "h3", "h4"], recursive=True):
        if not isinstance(heading, Tag):
            continue
        text = normalized_text(heading)
        if has_class(heading, "paper-title") or has_class(heading, "paper-run-in-heading") or heading.get("data-review-skip"):
            heading.attrs.pop("data-section-number", None)
            continue
        if not text or heading_already_numbered(text):
            continue
        heading_id = str(heading.get("id") or "").strip().lower()
        lowered = text.lower().strip()
        if lowered in skip_titles or heading_id in {"abstract", "references", "refs", "neurips-paper-checklist"}:
            continue
        if first_numbered_level is None and not heading_id:
            continue
        if first_numbered_level is None:
            first_numbered_level = int(heading.name[1])
        level = int(heading.name[1])
        if is_appendix_heading(heading, appendix_ids, appendix_started):
            appendix_started = True
            if appendix_first_level is None:
                appendix_first_level = level
            relative_level = max(1, level - appendix_first_level + 1)
            for key in list(appendix_counters):
                if key > relative_level:
                    del appendix_counters[key]
            appendix_counters[relative_level] = appendix_counters.get(relative_level, 0) + 1
            if relative_level > 1 and appendix_counters.get(relative_level - 1, 0) == 0:
                appendix_counters[relative_level - 1] = 1
            parts = [
                integer_to_alpha(appendix_counters.get(1, 1)),
                *[str(appendix_counters.get(idx, 1)) for idx in range(2, relative_level + 1)],
            ]
            heading["data-section-number"] = ".".join(parts)
            continue
        relative_level = max(1, level - first_numbered_level + 1)
        for key in list(counters):
            if key > relative_level:
                del counters[key]
        counters[relative_level] = counters.get(relative_level, 0) + 1
        parent_value = counters.get(relative_level - 1, 0)
        if relative_level > 1 and parent_value == 0:
            counters[relative_level - 1] = 1
        parts = [str(counters.get(idx, 1)) for idx in range(1, relative_level + 1)]
        heading["data-section-number"] = ".".join(parts)


def sync_section_reference_numbers(soup: BeautifulSoup) -> int:
    section_numbers: dict[str, str] = {}
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        if not isinstance(heading, Tag):
            continue
        heading_id = str(heading.get("id") or "")
        number = str(heading.get("data-section-number") or "")
        if heading_id and number:
            section_numbers[heading_id] = number
    updated = 0
    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue
        ref = str(link.get("data-reference") or "").strip()
        href = str(link.get("href") or "").strip()
        if not ref and href.startswith("#"):
            ref = href[1:]
        number = section_numbers.get(ref)
        if not number:
            continue
        current = normalized_text(link)
        if current and not re.fullmatch(r"\[?[A-Za-z]?\d+(?:\.\d+)*\]?", current):
            continue
        link.clear()
        link.append(NavigableString(number))
        updated += 1
    return updated


def body_inner_html(soup: BeautifulSoup) -> str:
    if soup.body is None:
        return str(soup)
    return "\n".join(str(child) for child in soup.body.children)


def text_without_citations(node: Tag) -> str:
    parts: list[str] = []

    def visit(child: object) -> None:
        if isinstance(child, NavigableString):
            parts.append(str(child))
            return
        if not isinstance(child, Tag):
            return
        if has_class(child, "citation") or child.get("data-cites"):
            return
        for grandchild in child.contents:
            visit(grandchild)

    visit(node)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def sentence_page_anchor_text(node: Tag, max_chars: int = 120) -> str:
    text = text_without_citations(node)
    text = re.sub(r"\([^)]*(?:\?{2,}|\bet al\.|\b\d{4}\b|;)[^)]*\)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\?{2,}", " ", text)
    text = normalize_for_match(text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] or text[:max_chars]


def text_match_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "this",
        "to",
        "we",
        "with",
    }
    return [token for token in tokens if len(token) >= 3 and token not in stopwords]


def sentence_page_phrases(node: Tag) -> list[str]:
    text = sentence_page_anchor_text(node, max_chars=260)
    tokens = text_match_tokens(text)
    phrases: list[str] = []
    seen: set[str] = set()
    for width in (8, 7, 6, 5, 4):
        if len(tokens) < width:
            continue
        for start in range(0, len(tokens) - width + 1):
            phrase = " ".join(tokens[start : start + width])
            if phrase not in seen:
                phrases.append(phrase)
                seen.add(phrase)
    return phrases


def page_match_score(phrases: list[str], page_text: str) -> int:
    score = 0
    for phrase in phrases:
        if phrase in page_text:
            score += len(phrase.split()) ** 2
    return score


def pdf_text_pages(pdf_path: Path) -> list[str]:
    if not pdf_path.exists() or shutil.which("pdftotext") is None:
        return []
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    pages: list[str] = []
    for raw_page in result.stdout.split("\f"):
        normalized = normalize_for_match(raw_page)
        normalized = " ".join(text_match_tokens(re.sub(r"[^a-z0-9]+", " ", normalized)))
        pages.append(normalized)
    while pages and not pages[-1]:
        pages.pop()
    return pages


def best_matching_page(
    phrases: list[str],
    pages: list[str],
    *,
    start_page: int = 1,
    max_lookahead: int | None = None,
    min_score: int = 16,
) -> int:
    if not phrases or not pages:
        return 0
    start_idx = max(start_page - 1, 0)
    end_idx = len(pages) if max_lookahead is None else min(len(pages), start_idx + max_lookahead + 1)
    matched_page = 0
    best_score = 0
    for idx in range(start_idx, end_idx):
        score = page_match_score(phrases, pages[idx])
        if score > best_score:
            best_score = score
            matched_page = idx + 1
    return matched_page if best_score >= min_score else 0


def monotone_page_alignment(score_rows: list[list[int]]) -> list[int]:
    if not score_rows or not score_rows[0]:
        return []

    page_count = len(score_rows[0])
    backrefs: list[list[int]] = [[-1] * page_count]
    previous = list(score_rows[0])
    negative_infinity = -(10**12)

    for row in score_rows[1:]:
        current = [negative_infinity] * page_count
        links = [0] * page_count
        best_score = negative_infinity
        best_page = 0
        for page_idx, prior_score in enumerate(previous):
            if prior_score > best_score:
                best_score = prior_score
                best_page = page_idx
            current[page_idx] = best_score + row[page_idx]
            links[page_idx] = best_page
        previous = current
        backrefs.append(links)

    final_page = max(range(page_count), key=lambda idx: (previous[idx], -idx))
    aligned_pages = [final_page] * len(score_rows)
    for row_idx in range(len(score_rows) - 1, 0, -1):
        aligned_pages[row_idx - 1] = backrefs[row_idx][aligned_pages[row_idx]]
    return [page_idx + 1 for page_idx in aligned_pages]


def sentence_page_assignments_from_pages(soup: BeautifulSoup, pages: list[str]) -> dict[str, int]:
    if not pages:
        return {}
    nodes: list[tuple[str, Tag]] = []
    for node in soup.select(".paper-sentence[data-sentence-id]"):
        if not isinstance(node, Tag):
            continue
        sentence_id = str(node.get("data-sentence-id") or "")
        if not sentence_id:
            continue
        nodes.append((sentence_id, node))
    score_rows = [
        [page_match_score(sentence_page_phrases(node), page_text) for page_text in pages]
        for _sentence_id, node in nodes
    ]
    aligned_pages = monotone_page_alignment(score_rows)
    assignments: dict[str, int] = {}
    for (sentence_id, _node), page in zip(nodes, aligned_pages):
        assignments[sentence_id] = page
    return assignments


def _greedy_sentence_page_assignments_from_pages(soup: BeautifulSoup, pages: list[str]) -> dict[str, int]:
    if not pages:
        return {}
    assignments: dict[str, int] = {}
    search_page = 1
    close_lookahead = 2
    for node in soup.select(".paper-sentence[data-sentence-id]"):
        if not isinstance(node, Tag):
            continue
        sentence_id = str(node.get("data-sentence-id") or "")
        if not sentence_id:
            continue
        phrases = sentence_page_phrases(node)
        matched_page = best_matching_page(phrases, pages, start_page=search_page, max_lookahead=close_lookahead)
        if not matched_page:
            matched_page = best_matching_page(phrases, pages, start_page=search_page, max_lookahead=None, min_score=64)
        if matched_page and matched_page >= search_page:
            search_page = matched_page
        assignments[sentence_id] = search_page
    return assignments


def sentence_page_assignments(soup: BeautifulSoup, pdf_path: Path) -> dict[str, int]:
    return sentence_page_assignments_from_pages(soup, pdf_text_pages(pdf_path))


def float_page_phrases(node: Tag) -> list[str]:
    caption = node.find("figcaption") or node.find("caption")
    anchor = caption if isinstance(caption, Tag) else node
    return sentence_page_phrases(anchor)


def assigned_caption_page(node: Tag, sentence_assignments: dict[str, int]) -> int:
    caption = node.find("figcaption") or node.find("caption")
    if not isinstance(caption, Tag):
        return 0
    for sentence in caption.select(".paper-sentence[data-sentence-id]"):
        sentence_id = str(sentence.get("data-sentence-id") or "")
        page = sentence_assignments.get(sentence_id, 0)
        if page:
            return page
    return 0


def block_page_assignments_from_pages(
    soup: BeautifulSoup,
    pages: list[str],
    sentence_assignments: dict[str, int] | None = None,
) -> dict[str, int]:
    if not pages:
        return {}
    sentence_assignments = sentence_assignments or {}
    assignments: dict[str, int] = {}
    search_page = 1
    for node in soup.find_all(True):
        if not isinstance(node, Tag) or not node.get("id") or not is_float_container(node):
            continue
        target = float_container_for_node(node)
        if target is not node:
            continue
        block_id = str(node.get("id") or "")
        caption_page = assigned_caption_page(node, sentence_assignments)
        if caption_page:
            assignments[block_id] = caption_page
            search_page = max(search_page, caption_page)
            continue
        phrases = float_page_phrases(node)
        matched_page = best_matching_page(phrases, pages, start_page=search_page)
        if not matched_page:
            continue
        assignments[block_id] = matched_page
        search_page = max(search_page, matched_page)
    return assignments


def explicit_block_page(tag: Tag, block_assignments: dict[str, int]) -> int:
    tag_id = str(tag.get("id") or "")
    if tag_id and tag_id in block_assignments:
        return block_assignments[tag_id]
    for descendant in tag.find_all(True):
        if not isinstance(descendant, Tag):
            continue
        descendant_id = str(descendant.get("id") or "")
        if descendant_id and descendant_id in block_assignments:
            return block_assignments[descendant_id]
    return 0


def infer_next_page_from_source_order(siblings: list[Tag], index: int, assignments: dict[str, int], block_assignments: dict[str, int]) -> int:
    for sibling in siblings[index + 1 :]:
        page = explicit_block_page(sibling, block_assignments)
        if page:
            return page
        first_sentence = sibling.select_one(".paper-sentence[data-sentence-id]")
        if first_sentence is not None:
            sentence_id = str(first_sentence.get("data-sentence-id") or "")
            page = assignments.get(sentence_id, 0)
            if page:
                return page
    return 0


def flow_block_page_assignments_from_pages(
    soup: BeautifulSoup,
    pages: list[str],
    sentence_assignments: dict[str, int],
    block_assignments: dict[str, int],
) -> dict[int, int]:
    if not pages:
        return {}
    body = soup.body or soup
    element_children = [child for child in body.contents if isinstance(child, Tag)]
    assignments: dict[int, int] = {}
    search_page = 1
    for idx, child in enumerate(element_children):
        if child.get("id") == "paper-overview-annotations":
            continue
        prior_search_page = search_page
        explicit_page = explicit_block_page(child, block_assignments)
        page = explicit_page
        if not page:
            first_sentence = child.select_one(".paper-sentence[data-sentence-id]")
            if first_sentence is not None:
                sentence_id = str(first_sentence.get("data-sentence-id") or "")
                page = sentence_assignments.get(sentence_id, 0)
        if not page:
            phrases = sentence_page_phrases(child)
            page = best_matching_page(phrases, pages, start_page=search_page, max_lookahead=2)
            if not page:
                page = best_matching_page(phrases, pages, start_page=search_page, max_lookahead=None, min_score=64)
        if page:
            if not (explicit_page and is_float_container(child)):
                search_page = max(search_page, page)
        else:
            page = search_page
        is_reference_block = str(child.get("id") or "") == "refs" or has_class(child, "csl-bib-body")
        is_list_block = child.name in {"ol", "ul"}
        if is_reference_block:
            parent_page = page
            entry_search_page = prior_search_page
            max_entry_page = page
            entries = [entry for entry in child.find_all(class_="csl-entry", recursive=False) if isinstance(entry, Tag)]
            for entry in entries:
                if not isinstance(entry, Tag):
                    continue
                phrases = sentence_page_phrases(entry)
                entry_page = best_matching_page(phrases, pages, start_page=entry_search_page, max_lookahead=2)
                if not entry_page:
                    entry_page = best_matching_page(phrases, pages, start_page=entry_search_page, max_lookahead=None, min_score=64)
                if entry_page:
                    entry_search_page = max(entry_search_page, entry_page)
                    max_entry_page = max(max_entry_page, entry_page)
                else:
                    entry_page = entry_search_page
                assignments[id(entry)] = entry_page
            page = assignments.get(id(entries[0]), page) if entries else page
            search_page = max(search_page, max_entry_page)
            if parent_page > page:
                search_page = max(search_page, parent_page)
        elif is_list_block:
            item_search_page = prior_search_page
            max_item_page = page
            for item in child.find_all("li", recursive=False):
                if not isinstance(item, Tag):
                    continue
                item_page = 0
                first_sentence = item.select_one(".paper-sentence[data-sentence-id]")
                if first_sentence is not None:
                    sentence_id = str(first_sentence.get("data-sentence-id") or "")
                    item_page = sentence_assignments.get(sentence_id, 0)
                if not item_page:
                    phrases = sentence_page_phrases(item)
                    item_page = best_matching_page(phrases, pages, start_page=item_search_page, max_lookahead=2)
                    if not item_page:
                        item_page = best_matching_page(phrases, pages, start_page=item_search_page, max_lookahead=None, min_score=64)
                if item_page:
                    item_search_page = max(item_search_page, item_page)
                    max_item_page = max(max_item_page, item_page)
                else:
                    item_page = item_search_page
                assignments[id(item)] = item_page
            search_page = max(search_page, max_item_page)
        next_page = infer_next_page_from_source_order(element_children, idx, sentence_assignments, block_assignments)
        if next_page and page > next_page and not is_reference_block and not is_list_block:
            page = next_page
        assignments[id(child)] = page
    for idx, child in enumerate(element_children):
        if not child.name or child.name not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            continue
        if sentence_page_phrases(child):
            continue
        for sibling in element_children[idx + 1 :]:
            page = assignments.get(id(sibling), 0)
            if page:
                assignments[id(child)] = page
                break
    return assignments


def split_children_into_pages(
    soup: BeautifulSoup,
    assignments: dict[str, int],
    block_assignments: dict[str, int] | None = None,
    flow_block_assignments: dict[int, int] | None = None,
    min_pages: int = 0,
) -> tuple[list[Tag], int]:
    block_assignments = block_assignments or {}
    flow_block_assignments = flow_block_assignments or {}
    body = soup.body or soup
    children = list(body.contents)
    for child in children:
        child.extract()

    page_external_children: list[Tag] = []
    pages: list[Tag] = []
    current_page = 1
    current_container = soup.new_tag("div")
    current_container["class"] = "paper-page"
    current_container["data-page"] = str(current_page)
    pages.append(current_container)

    def ensure_page(page_num: int) -> Tag:
        nonlocal current_page, current_container
        page_num = max(1, page_num)
        while current_page < page_num:
            current_page += 1
            current_container = soup.new_tag("div")
            current_container["class"] = "paper-page"
            current_container["data-page"] = str(current_page)
            pages.append(current_container)
        return pages[page_num - 1]

    def first_sentence_page(tag: Tag) -> int:
        first_sentence = tag.select_one(".paper-sentence[data-sentence-id]")
        if first_sentence is not None:
            sentence_id = str(first_sentence.get("data-sentence-id") or "")
            return assignments.get(sentence_id, current_page)
        return current_page

    def block_page(tag: Tag) -> int:
        return explicit_block_page(tag, block_assignments) or flow_block_assignments.get(id(tag), 0)

    def continuation_fragment(tag_name: str, attrs: dict[str, object], source_id: str) -> Tag:
        fragment = soup.new_tag(tag_name)
        fragment.attrs = dict(attrs)
        fragment.attrs.pop("id", None)
        fragment.attrs.pop("data-paragraph-id", None)
        fragment.attrs.pop("aria-describedby", None)
        fragment.attrs.pop("onclick", None)
        fragment.attrs.pop("onkeydown", None)
        fragment.attrs.pop("role", None)
        fragment.attrs.pop("tabindex", None)
        fragment.attrs.pop("data-has-issue", None)
        fragment.attrs.pop("data-severity", None)
        fragment.attrs.pop("data-issue-type", None)
        fragment.attrs.pop("data-issue-ids", None)
        classes = [value for value in class_names(fragment) if value not in {"has-paragraph-annotation", "paper-paragraph"}]
        fragment["class"] = classes
        if source_id:
            fragment["data-paragraph-fragment-of"] = source_id
        return fragment

    def reference_fragment(attrs: dict[str, object], source_id: str, *, first: bool) -> Tag:
        fragment = soup.new_tag("div")
        fragment.attrs = dict(attrs)
        if not first:
            fragment.attrs.pop("id", None)
            if source_id:
                fragment["data-block-fragment-of"] = source_id
        return fragment

    def append_sentence_container(child: Tag) -> None:
        sentence_nodes = child.select(".paper-sentence[data-sentence-id]")
        unique_pages = ordered_unique(
            [
                str(assignments.get(str(sentence.get("data-sentence-id") or ""), current_page))
                for sentence in sentence_nodes
            ]
        )
        if len(unique_pages) <= 1:
            ensure_page(int(unique_pages[0]) if unique_pages else first_sentence_page(child)).append(child)
            return

        original_tag_name = child.name
        original_attrs = dict(child.attrs)
        source_paragraph_id = str(original_attrs.get("data-paragraph-id") or "")
        active_page = int(unique_pages[0])
        active = soup.new_tag(original_tag_name)
        active.attrs = dict(original_attrs)
        ensure_page(active_page).append(active)
        for part in list(child.contents):
            if isinstance(part, Tag) and has_class(part, "paper-sentence"):
                sentence_id = str(part.get("data-sentence-id") or "")
                part_page = assignments.get(sentence_id, active_page)
                if part_page != active_page:
                    active_page = part_page
                    active = continuation_fragment(original_tag_name, original_attrs, source_paragraph_id)
                    ensure_page(active_page).append(active)
                active.append(part)
            else:
                active.append(part)

    def append_reference_container(child: Tag) -> None:
        entries = [entry for entry in child.find_all(class_="csl-entry", recursive=False) if isinstance(entry, Tag)]
        if not entries:
            ensure_page(block_page(child) or first_sentence_page(child)).append(child)
            return
        original_attrs = dict(child.attrs)
        source_id = str(original_attrs.get("id") or "")
        active_page = block_page(child) or flow_block_assignments.get(id(entries[0]), current_page)
        active = reference_fragment(original_attrs, source_id, first=True)
        ensure_page(active_page).append(active)
        for part in list(child.contents):
            if isinstance(part, Tag) and "csl-entry" in class_names(part):
                part_page = flow_block_assignments.get(id(part), active_page)
                if part_page != active_page:
                    active_page = part_page
                    active = reference_fragment(original_attrs, source_id, first=False)
                    ensure_page(active_page).append(active)
                active.append(part)
            else:
                active.append(part)

    def list_fragment(tag_name: str, attrs: dict[str, object], source_id: str, *, first: bool) -> Tag:
        fragment = soup.new_tag(tag_name)
        fragment.attrs = dict(attrs)
        if not first:
            fragment.attrs.pop("id", None)
            if source_id:
                fragment["data-list-fragment-of"] = source_id
        return fragment

    def append_list_container(child: Tag) -> None:
        items = [item for item in child.find_all("li", recursive=False) if isinstance(item, Tag)]
        if not items:
            ensure_page(block_page(child) or first_sentence_page(child)).append(child)
            return
        original_attrs = dict(child.attrs)
        source_id = str(original_attrs.get("id") or "")
        active_page = block_page(child) or flow_block_assignments.get(id(items[0]), current_page)
        active = list_fragment(child.name, original_attrs, source_id, first=True)
        ensure_page(active_page).append(active)
        for part in list(child.contents):
            if isinstance(part, Tag) and part.name == "li":
                part_page = flow_block_assignments.get(id(part), active_page)
                if part_page != active_page:
                    active_page = part_page
                    active = list_fragment(child.name, original_attrs, source_id, first=False)
                    ensure_page(active_page).append(active)
                active.append(part)
            else:
                active.append(part)

    def append_child(child: object) -> None:
        if isinstance(child, NavigableString):
            if str(child).strip():
                ensure_page(current_page).append(child)
            return
        if not isinstance(child, Tag):
            ensure_page(current_page).append(child)
            return
        if child.get("id") == "paper-overview-annotations":
            page_external_children.append(child)
            return
        if is_float_container(child):
            target_page = block_page(child)
            if target_page:
                ensure_page(target_page).append(child)
                return
        if str(child.get("id") or "") == "refs" or has_class(child, "csl-bib-body"):
            append_reference_container(child)
            return
        if child.name in {"ol", "ul"} and block_page(child):
            append_list_container(child)
            return
        sentence_nodes = child.select(".paper-sentence[data-sentence-id]")
        if not sentence_nodes:
            ensure_page(block_page(child) or first_sentence_page(child)).append(child)
            return
        if child.name in SENTENCE_CONTAINER_TAGS:
            append_sentence_container(child)
            return
        if (
            child.name in {"div", "section", "article"}
            and not child.get("id")
            and not has_class(child, "paper-float")
            and not has_class(child, "abstract")
        ):
            for part in list(child.contents):
                part.extract()
                append_child(part)
            return
        ensure_page(first_sentence_page(child)).append(child)

    for child in children:
        append_child(child)
    if min_pages:
        ensure_page(min_pages)

    for child in page_external_children:
        body.append(child)
    for page in pages:
        body.append(page)
    return pages, len(assignments)


def apply_paged_layout(soup: BeautifulSoup, tex_path: Path, page_map_path: Path | None = None) -> dict[str, object]:
    pdf_path = tex_path.with_suffix(".pdf")
    pdf_pages = pdf_text_pages(pdf_path)
    assignments = sentence_page_assignments_from_pages(soup, pdf_pages)
    if not assignments:
        return {"enabled": False, "pages": 0, "sentences": 0, "page_map": {}}
    block_assignments = block_page_assignments_from_pages(soup, pdf_pages, assignments)
    flow_block_assignments = flow_block_page_assignments_from_pages(soup, pdf_pages, assignments, block_assignments)
    pages, sentence_count = split_children_into_pages(
        soup,
        assignments,
        block_assignments=block_assignments,
        flow_block_assignments=flow_block_assignments,
        min_pages=len(pdf_pages),
    )
    payload: dict[str, object] = {
        "enabled": True,
        "source_pdf": str(pdf_path),
        "pdf_pages": len(pdf_pages),
        "pages": len(pages),
        "sentences": sentence_count,
        "sentence_pages": assignments,
        "block_pages": block_assignments,
    }
    if page_map_path is not None:
        page_map_path.parent.mkdir(parents=True, exist_ok=True)
        page_map_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


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


def unwrap_source_artifact_shell(soup: BeautifulSoup) -> BeautifulSoup:
    if not is_source_artifact_shell(soup):
        return soup
    body = soup.body
    if body is None:
        return soup
    unwrapped = BeautifulSoup("<html><body></body></html>", "lxml")
    assert unwrapped.body is not None
    for child in list(body.contents):
        unwrapped.body.append(child.extract())
    return unwrapped


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
        soup = unwrap_source_artifact_shell(BeautifulSoup(raw_html_path.read_text(encoding="utf-8"), "lxml"))
        normalize_front_matter(soup, tex_path)
        restore_mathml_labels(soup)
        ensure_references_heading(soup)
        restore_bibliography_position(soup, tex_path)
        title = extract_title(soup, tex_path)
        sentence_count = len(soup.select(".paper-sentence[data-sentence-id]"))
        if sentence_count == 0:
            stable_sentence_nodes = [node for node in soup.select("[data-sentence-id]") if isinstance(node, Tag)]
            if stable_sentence_nodes:
                for node in stable_sentence_nodes:
                    add_class(node, "paper-sentence")
                sentence_count = len(stable_sentence_nodes)
            else:
                sentence_count = wrap_sentences(soup)
                title = extract_title(soup, tex_path)
        ensure_display_section_numbers(soup, tex_path)
        sync_section_reference_numbers(soup)
        sync_float_reference_numbers(soup, tex_path)
        return soup, title, sentence_count

    run_pandoc(tex_path, raw_html_path)
    soup = BeautifulSoup(raw_html_path.read_text(encoding="utf-8"), "lxml")
    cleanup_pandoc_artifacts(soup)
    normalize_front_matter(soup, tex_path)
    restore_mathml_labels(soup)
    rasterize_pdf_assets(
        soup,
        tex_path.parent,
        asset_dir=asset_dir,
        html_dir=output_path.parent,
        inline_images=inline_images,
        absolute_asset_paths=output_path.parent != raw_html_path.parent,
    )
    restore_latex_labels(soup, tex_path)
    mark_latex_float_widths(soup, tex_path)
    replace_broken_latex_tables(soup, tex_path)
    add_float_caption_numbers(soup, tex_path)
    mark_latex_paragraph_headings(soup, tex_path)
    ensure_references_heading(soup)
    restore_bibliography_position(soup, tex_path)
    title = extract_title(soup, tex_path)
    sentence_count = wrap_sentences(soup)
    ensure_display_section_numbers(soup, tex_path)
    sync_section_reference_numbers(soup)
    sync_float_reference_numbers(soup, tex_path)
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


def render_annotation_cards(annotations: list[dict[str, str]], *, full_report: bool = False) -> str:
    if not annotations:
        warning = (
            "本报告没有可显示的 overlay 批注。若这是全文审阅结果，说明 Prose Phase A/B 或 findings 编译尚未完成；"
            "请不要把这份 HTML 当作已完成审阅。"
            if full_report
            else "当前预览尚未加载批注；左侧仅是由论文源码解析生成的正文。"
        )
        return f'<aside class="report-warning" role="status"><strong>审阅未完成</strong><p>{html.escape(warning)}</p></aside>'
    cards: list[str] = [
        '<p class="annotation-empty-state" data-annotation-empty>点击左侧带下划线的句子，这里会显示对应批注意见。</p>'
    ]
    unanchored_cards: list[str] = []
    page_level_cards: list[str] = []
    for idx, item in enumerate(annotations, 1):
        severity = item.get("severity", "major")
        badge = SEVERITY_LABELS.get(severity, severity.title())
        short_badge = SEVERITY_SHORT_LABELS.get(severity, severity.title())
        card_id = html.escape(item.get("card_id", f"annotation-{idx}"))
        target_level = item.get("target_level", "sentence")
        target_id_raw = annotation_target_id(item)
        sentence_id = html.escape(item.get("sentence_id", ""))
        target_id = html.escape(target_id_raw)
        issue_id = html.escape(item.get("issue_id", f"A{idx}"))
        issue_type_raw = item.get("issue_type", "prose")
        issue_type = html.escape(issue_type_raw)
        level_label = annotation_pointer_label(target_level, target_id_raw, issue_type_raw)
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
        page_anchor = html.escape(item.get("page_anchor", ""))
        unanchored = item.get("unanchored") == "true" or not target_id_raw
        page_level = target_level == "paper" and bool(item.get("page_anchor"))
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
            else '<p class="annotation-pointer annotation-unanchored">未定位到唯一原句，保留为全局批注</p>'
        )
        if page_level:
            pointer = f'<p class="annotation-pointer annotation-page-level">页级/版式批注：{page_anchor}</p>'
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
        if page_level:
            page_level_cards.append(rendered_card)
        elif unanchored:
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
          <summary>未定位到唯一原句的批注（{len(unanchored_cards)}）</summary>
          {''.join(unanchored_cards)}
        </details>"""
        )
    if page_level_cards:
        cards.append(
            f"""
        <details class="page-level-drawer">
          <summary>页级/版式批注（{len(page_level_cards)}）</summary>
          {''.join(page_level_cards)}
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


def annotation_pointer_label(target_level: str, target_id: str, issue_type: str) -> str:
    if target_level == "section":
        target_key = target_id.strip().lower()
        issue_key = issue_type.strip().lower()
        if target_key.startswith(("fig:", "tab:")) or "caption" in issue_key or issue_key.startswith(("figure", "table")):
            return "图表/Caption"
    return ANCHOR_LEVEL_LABELS.get(target_level, target_level)


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


def finding_source_domain(finding: dict[str, object]) -> str:
    source_ids = finding.get("source_issue_ids")
    if isinstance(source_ids, list):
        for source_id in source_ids:
            text = str(source_id or "")
            if ":" in text:
                return text.split(":", 1)[0]
    return str(finding.get("domain") or finding.get("issue_type") or "").strip()


def is_global_finding(finding: dict[str, object]) -> bool:
    domain = finding_source_domain(finding)
    if domain in SUBMISSION_DOMAINS:
        return False
    anchor = str(finding.get("primary_anchor") or "").strip()
    anchors = finding.get("target_anchors")
    anchor_values = [str(item).strip() for item in anchors] if isinstance(anchors, list) else []
    if anchor.startswith("page:") or any(value.startswith("page:") for value in anchor_values):
        return False
    if domain == "whole_paper":
        return True
    if anchor == "paper" or "paper" in anchor_values:
        return True
    location = str(finding.get("location") or "").strip().lower()
    snippet = str(finding.get("snippet") or "").strip().lower()
    return location in {"全文结构", "whole paper"} or snippet == "whole paper"


def render_global_findings(findings: list[dict[str, object]]) -> str:
    global_findings = [
        finding
        for finding in findings
        if is_global_finding(finding) and severity_key(finding.get("severity")) in {"blocker", "major"}
    ]
    if not global_findings:
        body = '<p class="empty-state">没有独立于具体句段的 Major/Blocker 全局意见；局部问题已保留在正文 overlay 批注中。</p>'
    else:
        articles = []
        for finding in global_findings:
            articles.append(
                f"""
      <article class="global-finding" id="global-{display_text(finding.get('id'))}" data-severity="{severity_key(finding.get('severity'))}" data-issue-type="{display_text(finding.get('issue_type'), fallback='whole_paper')}">
        <p class="annotation-meta">{severity_badge(finding.get('severity'))}<span>{display_text(finding.get('issue_type'), fallback='whole_paper')}</span><span>{finding_id_link(finding.get('id'))}</span></p>
        <h3>{display_text(finding.get('title') or finding.get('diagnosis'), fallback='全局问题')}</h3>
        <dl>
          <dt>问题是什么</dt><dd>{display_text(finding.get('diagnosis'), fallback='未填写')}</dd>
          <dt>为什么有问题</dt><dd>{display_text(finding.get('reader_friction'), fallback='未填写')}</dd>
          <dt>违反原则</dt><dd>{display_text(finding.get('writing_principle'), fallback='claim-evidence alignment')}</dd>
          <dt>下一稿任务</dt><dd>{display_text(finding.get('next_draft_task') or finding.get('self_check'), fallback='收束全稿主张与证据边界。')}</dd>
        </dl>
      </article>"""
            )
        body = "".join(articles)
    return f"""
    <section id="global-findings" class="global-findings">
      <h2>{REPORT_SECTION_LABELS['global-findings']}</h2>
      <p class="empty-state">这里仅保留不依附于具体句子或段落的全局结构意见；句子、段落和章节问题请直接看上方论文正文 overlay。</p>
      {body}
    </section>"""


def rendered_finding_ids(annotations: list[dict[str, str]], findings: list[dict[str, object]]) -> set[str]:
    ids = {str(item.get("issue_id") or "").strip() for item in annotations if str(item.get("issue_id") or "").strip()}
    ids.update(
        str(finding.get("id") or "").strip()
        for finding in findings
        if str(finding.get("id") or "").strip() and is_global_finding(finding) and severity_key(finding.get("severity")) in {"blocker", "major"}
    )
    return ids


def deferred_finding_rows(findings: list[dict[str, object]], annotations: list[dict[str, str]]) -> list[dict[str, object]]:
    rendered_ids = rendered_finding_ids(annotations, findings)
    rows: list[dict[str, object]] = []
    for finding in findings:
        finding_id = str(finding.get("id") or "").strip()
        if not finding_id or finding_id in rendered_ids:
            continue
        if is_artifact_only(finding):
            reason = "artifact_only"
        else:
            reason = "not anchored in overlay/global sections"
        rows.append({**finding, "_deferred_reason": reason})
    return rows


def render_deferred_findings_summary(findings: list[dict[str, object]], annotations: list[dict[str, str]]) -> str:
    rows = deferred_finding_rows(findings, annotations)
    if not rows:
        return ""
    body_rows = []
    for finding in rows:
        body_rows.append(
            f"<tr><td>{finding_id_link(finding.get('id'))}</td><td>{display_text(finding.get('_deferred_reason'))}</td><td>{display_text(finding.get('title') or finding.get('diagnosis'), fallback='未命名 finding')}</td></tr>"
        )
    return f"""
      <div class="table-wrap deferred-findings">
        <table class="report-table">
          <caption>未渲染 findings</caption>
          <thead><tr><th scope="col">ID</th><th scope="col">原因</th><th scope="col">标题</th></tr></thead>
          <tbody>{''.join(body_rows)}</tbody>
        </table>
      </div>"""


def render_coverage_receipt(
    coverage: object,
    *,
    raw_hash_attr: str,
    source_artifact: str,
    sentence_count: int,
    annotation_count: int,
    findings: list[dict[str, object]] | None = None,
    annotations: list[dict[str, str]] | None = None,
) -> str:
    units = coverage.get("units", []) if isinstance(coverage, dict) else []
    rows = []
    findings = findings or []
    annotations = annotations or []
    deferred_html = render_deferred_findings_summary(findings, annotations)
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
      <h2>{REPORT_SECTION_LABELS['coverage-receipt']}</h2>
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
      {deferred_html}
    </section>"""


def render_global_report_sections(
    *,
    findings: list[dict[str, object]],
    annotations: list[dict[str, str]],
    coverage: object,
    raw_hash_attr: str,
    source_artifact: str,
    sentence_count: int,
) -> str:
    return "\n".join(
        [
            render_global_findings(findings),
            render_coverage_receipt(
                coverage,
                raw_hash_attr=raw_hash_attr,
                source_artifact=source_artifact,
                sentence_count=sentence_count,
                annotation_count=len(annotations),
                findings=findings,
                annotations=annotations,
            ),
        ]
    )


def extract_title(soup: BeautifulSoup, tex_path: Path) -> str:
    title = None if is_source_artifact_shell(soup) else soup.find("title")
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
    coverage: object = None,
    full_report: bool = False,
    paper_layout: str = "single",
    page_map: dict[str, object] | None = None,
) -> str:
    source_artifact = html.escape(str(raw_html_path))
    tex_display = html.escape(str(tex_path))
    raw_hash_attr = html.escape(raw_hash)
    title_html = html.escape(title)
    annotation_count = len(annotations)
    annotation_panel_state = ' data-empty="true"' if annotations else ""
    annotation_cards = render_annotation_cards(annotations, full_report=full_report)
    finding_anchor_index = render_finding_anchor_index(annotations)
    report_kind = "paper-reader-with-global-findings" if full_report else "paper-reader-only"
    header_title = "Ariadne Paper Reader Review" if full_report else "Ariadne Paper Reader Preview"
    page_map = page_map or {}
    page_count = int(page_map.get("pages") or 0)
    paper_layout = paper_layout if paper_layout in {"single", "two-column", "paged", "paged-two-column"} else "single"
    paper_layout_label = (
        f"paged two-column · {page_count} pages"
        if paper_layout == "paged-two-column" and page_count
        else "paged two-column"
        if paper_layout == "paged-two-column"
        else f"paged single-column · {page_count} pages"
        if paper_layout == "paged" and page_count
        else "paged single-column"
        if paper_layout == "paged"
        else "two-column"
        if paper_layout == "two-column"
        else "single"
    )
    paper_pane_class = f"paper-pane paper-layout-{paper_layout}"
    global_nav = (
        """
    <a href="#global-findings">全局重要问题</a>"""
        if full_report
        else ""
    )
    companion_html = (
        render_global_report_sections(
            findings=findings or [],
            annotations=annotations,
            coverage=coverage,
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
            findings=findings or [],
            annotations=annotations,
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
    .report-warning {{ border:1px solid #f2d98f; border-left:4px solid var(--major); border-radius:8px; background:#fff8e6; color:#4d3a00; padding:12px 14px; margin:0 0 14px; }}
    .report-warning strong {{ display:block; margin-bottom:4px; color:#5b3b00; }}
    .report-warning p {{ margin:0; }}
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
    .paper-pane .paper-title {{ font-size:28px; text-align:center; margin:0 auto 24px; max-width:820px; }}
    .paper-pane .paper-author {{ text-align:center; font-weight:700; margin:0 auto 32px; max-width:720px; }}
    .paper-pane h2 {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:22px; margin:24px 0 12px; }}
    .paper-pane h3 {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:18px; margin:20px 0 10px; }}
    .paper-pane h4 {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:17px; margin:18px 0 8px; }}
    .paper-pane h1[data-section-number]::before, .paper-pane h2[data-section-number]::before, .paper-pane h3[data-section-number]::before, .paper-pane h4[data-section-number]::before {{ content:attr(data-section-number) " "; }}
    .paper-pane ul, .paper-pane ol {{ padding-left:1.7em; margin:1em 0; max-width:760px; }}
    .paper-pane li {{ margin:.35em 0; padding-left:.2em; }}
    .paper-pane li > p {{ margin:.25em 0 .65em; }}
    .paper-pane li > ol, .paper-pane li > ul {{ margin-top:.25em; }}
    .paper-pane blockquote {{ margin:1em 0 1em 1.7em; padding-left:1em; border-left:2px solid #e6e6e6; color:#606060; }}
    .paper-pane .abstract {{ margin:2em 2em; text-align:left; font-size:85%; }}
    .paper-pane .abstract-title {{ font-weight:700; text-align:center; margin-bottom:.5em; }}
    .paper-pane table {{ width:auto; max-width:100%; margin-left:auto; margin-right:auto; border-collapse:collapse; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:14px; }}
    .paper-pane th, .paper-pane td {{ border:1px solid var(--line); padding:6px; vertical-align:top; }}
    .paper-pane img, .paper-pane svg {{ max-width:100%; height:auto; }}
    .paper-pane embed {{ display:block; width:100%; max-width:100%; min-height:240px; margin:10px auto; border:1px solid var(--line); }}
    .paper-pane .paper-asset-image {{ display:block; width:100%; max-width:100%; height:auto; margin:8px auto; border:1px solid var(--line); background:#fff; }}
    .paper-pane .paper-float {{ margin:18px 0; clear:both; }}
    .paper-pane .wrapfigure, .paper-pane .wraptable {{ max-width:46%; float:right; margin:2px 0 14px 22px; }}
    .paper-pane .wrapfigure img, .paper-pane .wraptable img {{ width:100%; }}
    .paper-pane .wraptable table {{ min-width:0; }}
    .paper-pane .paper-table {{ max-width:100%; overflow-x:auto; }}
    .paper-pane .paper-table > table {{ margin-left:auto; margin-right:auto; }}
    .paper-pane .table\\*, .paper-pane .figure\\* {{ clear:both; margin:24px 0; }}
    .paper-pane figure {{ margin:22px 0; max-width:920px; }}
    .paper-pane .prompt-figure {{ border:1px solid var(--line); border-radius:8px; background:#fbfcfe; padding:12px; }}
    .paper-pane figcaption, .paper-pane caption {{ color:var(--muted); font-size:14px; line-height:1.5; }}
    .paper-pane caption {{ caption-side:top; text-align:left; margin:0 0 8px; }}
    .paper-pane .paper-run-in-heading {{ display:inline; font-family:Georgia,"Times New Roman","Noto Serif",serif; font-size:1em; margin:0; font-weight:700; }}
    .paper-pane .paper-run-in-heading::after {{ content:". "; }}
    .paper-pane .paper-run-in-heading + p {{ display:inline; }}
    .paper-pane .paper-run-in-heading + p::after {{ content:""; display:block; margin-bottom:1em; }}
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
    .paper-pane.paper-layout-two-column, .paper-pane.paper-layout-paged-two-column {{ max-width:1120px; }}
    .paper-pane.paper-layout-paged {{ max-width:900px; }}
    .paper-page {{ margin:0 0 28px; padding:26px 34px 30px; box-sizing:border-box; min-height:1120px; border:1px solid #e3e8f0; border-radius:6px; background:#fff; box-shadow:0 1px 2px rgba(15,23,42,.05); position:relative; overflow:hidden; }}
    .paper-page::before {{ content:"page " attr(data-page); position:absolute; right:14px; top:8px; color:#9aa5b1; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:11px; font-weight:700; letter-spacing:0; }}
    .paper-page > :first-child {{ margin-top:0; }}
    .paper-page > :last-child {{ margin-bottom:0; }}
    @media (min-width: 921px) {{
      .paper-pane.paper-layout-two-column {{ font-size:14px; line-height:1.42; column-count:2; column-gap:30px; column-rule:0; }}
      .paper-pane.paper-layout-paged {{ font-size:15px; line-height:1.55; padding:22px 28px; background:#f8fafc; }}
      .paper-pane.paper-layout-paged-two-column {{ font-size:14px; line-height:1.42; padding:22px 28px; background:#f8fafc; }}
      .paper-pane.paper-layout-paged-two-column > .paper-page {{ column-count:2; column-fill:balance; column-gap:30px; column-rule:0; }}
      .paper-pane.paper-layout-two-column > header,
      .paper-pane.paper-layout-two-column > .paper-title,
      .paper-pane.paper-layout-two-column > .paper-author,
      .paper-pane.paper-layout-two-column > .paper-abstract-wide,
      .paper-pane.paper-layout-two-column > .paper-overview-annotations,
      .paper-pane.paper-layout-two-column > .paper-float-wide,
      .paper-pane.paper-layout-two-column > .figure\\*,
      .paper-pane.paper-layout-two-column > .table\\* {{
        column-span:all;
      }}
      .paper-pane.paper-layout-paged-two-column > .paper-page > header,
      .paper-pane.paper-layout-paged-two-column > .paper-page > .paper-title,
      .paper-pane.paper-layout-paged-two-column > .paper-page > .paper-author,
      .paper-pane.paper-layout-paged-two-column > .paper-page > .paper-abstract-wide,
      .paper-pane.paper-layout-paged-two-column > .paper-page > .paper-overview-annotations,
      .paper-pane.paper-layout-paged-two-column > .paper-page > .paper-float-wide,
      .paper-pane.paper-layout-paged-two-column > .paper-page > .figure\\*,
      .paper-pane.paper-layout-paged-two-column > .paper-page > .table\\* {{
        column-span:all;
      }}
      .paper-pane.paper-layout-two-column > p,
      .paper-pane.paper-layout-two-column > ul,
      .paper-pane.paper-layout-two-column > ol,
      .paper-pane.paper-layout-two-column > blockquote,
      .paper-pane.paper-layout-two-column > h1,
      .paper-pane.paper-layout-two-column > h2,
      .paper-pane.paper-layout-two-column > h3,
      .paper-pane.paper-layout-two-column > h4,
      .paper-pane.paper-layout-two-column > h5,
      .paper-pane.paper-layout-two-column > h6,
      .paper-pane.paper-layout-two-column > .abstract,
      .paper-pane.paper-layout-two-column > #refs {{ max-width:none; }}
      .paper-pane.paper-layout-paged-two-column > .paper-page > p,
      .paper-pane.paper-layout-paged-two-column > .paper-page > ul,
      .paper-pane.paper-layout-paged-two-column > .paper-page > ol,
      .paper-pane.paper-layout-paged-two-column > .paper-page > blockquote,
      .paper-pane.paper-layout-paged-two-column > .paper-page > h1,
      .paper-pane.paper-layout-paged-two-column > .paper-page > h2,
      .paper-pane.paper-layout-paged-two-column > .paper-page > h3,
      .paper-pane.paper-layout-paged-two-column > .paper-page > h4,
      .paper-pane.paper-layout-paged-two-column > .paper-page > h5,
      .paper-pane.paper-layout-paged-two-column > .paper-page > h6,
      .paper-pane.paper-layout-paged-two-column > .paper-page > .abstract,
      .paper-pane.paper-layout-paged-two-column > .paper-page > #refs {{ max-width:none; }}
      .paper-pane.paper-layout-two-column h1:not(.paper-title) {{ font-size:20px; break-after:avoid; }}
      .paper-pane.paper-layout-paged h1:not(.paper-title) {{ font-size:22px; break-after:avoid; }}
      .paper-pane.paper-layout-paged-two-column h1:not(.paper-title) {{ font-size:20px; break-after:avoid; }}
      .paper-pane.paper-layout-two-column h2 {{ font-size:16px; margin:18px 0 8px; break-after:avoid; }}
      .paper-pane.paper-layout-paged h2 {{ font-size:18px; margin:20px 0 9px; break-after:avoid; }}
      .paper-pane.paper-layout-paged-two-column h2 {{ font-size:16px; margin:18px 0 8px; break-after:avoid; }}
      .paper-pane.paper-layout-two-column h3 {{ font-size:15px; margin:14px 0 7px; break-after:avoid; }}
      .paper-pane.paper-layout-paged h3 {{ font-size:16px; margin:16px 0 8px; break-after:avoid; }}
      .paper-pane.paper-layout-paged-two-column h3 {{ font-size:15px; margin:14px 0 7px; break-after:avoid; }}
      .paper-pane.paper-layout-two-column .paper-title {{ font-size:24px; line-height:1.18; }}
      .paper-pane.paper-layout-paged .paper-title {{ font-size:26px; line-height:1.2; }}
      .paper-pane.paper-layout-paged-two-column .paper-title {{ font-size:24px; line-height:1.18; }}
      .paper-pane.paper-layout-two-column .paper-author {{ font-size:16px; }}
      .paper-pane.paper-layout-paged .paper-author {{ font-size:16px; }}
      .paper-pane.paper-layout-paged-two-column .paper-author {{ font-size:16px; }}
      .paper-pane.paper-layout-two-column .abstract {{ margin:1.5em 0; }}
      .paper-pane.paper-layout-paged .abstract {{ margin:1.5em 0; }}
      .paper-pane.paper-layout-paged-two-column .abstract {{ margin:1.5em 0; }}
      .paper-pane.paper-layout-two-column .paper-overview-annotations {{ max-width:none; break-inside:avoid; }}
      .paper-pane.paper-layout-paged .paper-overview-annotations {{ max-width:none; break-inside:avoid; }}
      .paper-pane.paper-layout-paged-two-column .paper-overview-annotations {{ max-width:none; break-inside:avoid; }}
      .paper-pane.paper-layout-two-column figure,
      .paper-pane.paper-layout-two-column table,
      .paper-pane.paper-layout-two-column pre,
      .paper-pane.paper-layout-two-column .paper-float {{ break-inside:avoid; }}
      .paper-pane.paper-layout-paged figure,
      .paper-pane.paper-layout-paged table,
      .paper-pane.paper-layout-paged pre,
      .paper-pane.paper-layout-paged .paper-float {{ break-inside:avoid; }}
      .paper-pane.paper-layout-paged-two-column figure,
      .paper-pane.paper-layout-paged-two-column table,
      .paper-pane.paper-layout-paged-two-column pre,
      .paper-pane.paper-layout-paged-two-column .paper-float {{ break-inside:avoid; }}
    }}
    .paper-overview-annotations {{ max-width:760px; margin:0 0 22px; padding:10px 12px; border-left:3px solid var(--accent); background:#f8fafc; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:13px; line-height:1.45; }}
    .paper-overview-annotations strong {{ display:block; margin-bottom:8px; color:#111827; }}
    .paper-pane .has-section-annotation {{ position:relative; scroll-margin-top:92px; }}
    .paper-pane .has-paragraph-annotation {{ position:relative; padding-left:26px; }}
    .annotation-bubble {{ border:1px solid var(--line); border-radius:999px; background:#fff; color:var(--accent); cursor:pointer; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:11px; font-weight:800; line-height:1.25; padding:2px 7px; vertical-align:middle; box-shadow:0 1px 2px rgba(15,23,42,.08); }}
    .annotation-bubble:hover, .annotation-bubble:focus-visible {{ outline:2px solid rgba(36,73,167,.25); outline-offset:2px; }}
    .annotation-bubble.paragraph {{ position:absolute; left:0; top:.35em; width:18px; height:18px; padding:0; overflow:hidden; text-indent:24px; white-space:nowrap; border-color:#b6c4dd; background:#eef4ff; }}
    .annotation-bubble.paragraph::before {{ content:"¶"; position:absolute; left:0; top:0; width:100%; height:100%; text-indent:0; display:flex; align-items:center; justify-content:center; color:var(--accent); }}
    .annotation-bubble.section {{ display:inline-flex; align-items:center; justify-content:center; min-width:22px; max-width:96px; min-height:20px; margin-left:8px; padding:2px 6px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:middle; }}
    .annotation-bubble.paper {{ margin:0 6px 6px 0; }}
    .paper-sentence {{ border-radius:4px; padding:1px 2px; scroll-margin-top:92px; }}
    .paper-sentence.has-annotation {{ position:relative; cursor:pointer; text-decoration-line:underline; text-decoration-thickness:2px; text-underline-offset:4px; transition:background-color .12s ease, outline-color .12s ease; }}
    .paper-sentence.has-annotation::after {{ content:attr(data-inline-label); display:inline-flex; align-items:center; max-width:min(160px, 100%); margin-left:6px; padding:1px 6px; border-radius:999px; border:1px solid currentColor; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",Arial,sans-serif; font-size:11px; font-weight:700; line-height:1.35; vertical-align:baseline; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; pointer-events:none; }}
    .paper-overview-annotations .annotation-bubble.paper {{ max-width:100%; overflow-wrap:anywhere; text-align:left; border-radius:6px; white-space:normal; }}
    .paper-sentence[data-severity="blocker"] {{ background:var(--blocker-bg); text-decoration-color:var(--blocker); }}
    .paper-sentence[data-severity="major"] {{ background:var(--major-bg); text-decoration-color:var(--major); }}
    .paper-sentence[data-severity="minor"] {{ background:var(--minor-bg); text-decoration-color:var(--minor); }}
    .paper-sentence[data-severity="polish"] {{ background:var(--polish-bg); text-decoration-color:var(--polish); }}
    .paper-sentence.is-active {{ outline:2px solid var(--accent); outline-offset:2px; box-shadow:0 0 0 4px rgba(36,73,167,.10); }}
    .paper-pane .has-section-annotation.is-active, .paper-pane .has-paragraph-annotation.is-active {{ outline:2px solid var(--accent); outline-offset:4px; box-shadow:0 0 0 4px rgba(36,73,167,.10); }}
    .annotation-panel {{ position:sticky; top:70px; max-height:calc(100vh - 86px); overflow:auto; padding:18px; background:#fbfcfe; min-width:0; }}
    .annotation-panel[data-empty="true"] {{ color:var(--muted); }}
    .annotation-empty-state {{ border:1px dashed var(--line); border-radius:8px; padding:14px; margin:0 0 12px; background:#fff; color:var(--muted); }}
    .annotation-card {{ position:relative; display:block; border:1px solid var(--line); border-radius:8px; padding:14px; margin-bottom:12px; background:#fff; min-width:0; overflow-wrap:anywhere; word-break:break-word; }}
    .annotation-card[hidden] {{ display:none; }}
    .annotation-card::before {{ content:""; position:absolute; left:-9px; top:24px; border-top:9px solid transparent; border-bottom:9px solid transparent; border-right:9px solid var(--line); }}
    .annotation-card::after {{ content:""; position:absolute; left:-7px; top:25px; border-top:8px solid transparent; border-bottom:8px solid transparent; border-right:8px solid #fff; }}
    .annotation-card.is-active {{ border-color:var(--accent); box-shadow:0 0 0 2px rgba(36,73,167,.12); }}
    .annotation-meta {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:0 0 8px; color:var(--muted); font-size:12px; }}
    .annotation-card h3 {{ margin:0 0 10px; font-size:16px; line-height:1.32; overflow-wrap:anywhere; }}
    .annotation-card dl {{ margin:0; }}
    .annotation-card dt {{ margin-top:10px; color:var(--muted); font-size:12px; font-weight:700; }}
    .annotation-card dd {{ margin:2px 0 0; overflow-wrap:anywhere; }}
    .annotation-pointer {{ margin:0 0 10px; }}
    .annotation-pointer a {{ display:inline-flex; align-items:center; gap:6px; color:var(--accent); font-size:13px; font-weight:700; text-decoration:none; }}
    .annotation-pointer a::before {{ content:"←"; font-size:16px; line-height:1; }}
    .annotation-unanchored {{ color:var(--muted); font-size:13px; font-weight:700; }}
    .annotation-page-level {{ color:var(--muted); font-size:13px; font-weight:700; }}
    .annotation-sublist {{ margin:0; padding-left:18px; }}
    .annotation-nav {{ display:flex; gap:8px; }}
    .annotation-nav button {{ border:1px solid var(--line); border-radius:6px; background:#fff; padding:7px 10px; cursor:pointer; }}
    .unanchored-drawer {{ margin-top:16px; border-top:1px solid var(--line); padding-top:14px; }}
    .page-level-drawer {{ margin-top:16px; border-top:1px solid var(--line); padding-top:14px; }}
    .unanchored-drawer summary, .page-level-drawer summary {{ cursor:pointer; font-weight:800; color:var(--accent); }}
    .unanchored-drawer .annotation-card, .page-level-drawer .annotation-card {{ margin-top:10px; }}
    .empty-state {{ color:var(--muted); font-style:italic; }}
    .table-wrap {{ overflow-x:auto; margin-top:10px; }}
    table.report-table {{ width:100%; border-collapse:collapse; min-width:760px; }}
    .report-table th, .report-table td {{ border:1px solid var(--line); padding:9px; vertical-align:top; text-align:left; }}
    .report-table th {{ background:var(--soft); }}
    .report-table caption {{ text-align:left; font-weight:700; margin:0 0 8px; }}
    @media (max-width: 920px) {{ .review-report {{ padding:12px; }} .summary-band {{ grid-template-columns:1fr 1fr; }} .reader-shell {{ grid-template-columns:1fr; }} .paper-pane {{ border-right:0; border-bottom:1px solid var(--line); padding:24px 18px; }} .paper-page {{ height:auto; min-height:auto; padding:18px 14px; border-left:0; border-right:0; border-radius:0; }} .paper-pane .wrapfigure, .paper-pane .wraptable {{ float:none; max-width:100%; margin:18px 0; }} .annotation-panel {{ position:static; max-height:none; }} }}
    @media print {{ nav, .reader-toolbar {{ display:none !important; }} .annotation-card {{ display:block; }} .paper-page {{ break-after:page; box-shadow:none; }} }}
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
{global_nav}
    <a href="#coverage-receipt">覆盖回执</a>
  </nav>
  {finding_anchor_index}
  <section id="paper-reader" class="paper-reader" aria-label="Annotated paper">
    <div class="reader-toolbar">
      <div>
        <h2>论文正文批注</h2>
        <p class="empty-state">当前正文由论文源码解析生成；句子锚点保持稳定，批注以 overlay 方式添加。</p>
      </div>
      <div>
        <span class="badge blocker">■ Blocker</span>
        <span class="badge major">▲ Major</span>
        <span class="badge minor">● Minor</span>
        <span class="badge polish">◆ Polish</span>
        <span class="badge minor">Layout · {paper_layout_label}</span>
      </div>
    </div>
    <div class="reader-shell">
      <article class="{paper_pane_class}" data-paper-html-source="{PANDOC_SOURCE}" data-source-fidelity="deterministic" data-source-artifact="{source_artifact}" data-source-hash="{raw_hash_attr}" data-sentence-id-scheme="{SENTENCE_ID_SCHEME}" data-annotation-mode="overlay-only" data-paper-layout="{paper_layout}">
{source_html}
      </article>
      <aside id="annotation-panel" class="annotation-panel" aria-label="批注详情" aria-live="polite"{annotation_panel_state}>
        <h2>批注详情</h2>
{annotation_cards}
      </aside>
    </div>
  </section>
  <main>
{companion_html}
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
    document.querySelectorAll(".paper-sentence, [data-paragraph-id], .has-section-annotation, #paper-overview-annotations").forEach((node) => {{
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
    coverage_path: Path | None = None,
    full_report: bool = False,
    paper_layout: str = "source",
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
    ensure_display_section_numbers(soup, tex_path)
    raw_hash = sha256_path(raw_html_path)
    imported_annotations = load_review_html_annotations(review_html_path)
    explicit_annotations = load_annotations(annotations_path)
    findings_by_id = load_findings(findings_path)
    issue_annotations = filter_compiled_issue_artifact_annotations(
        load_issue_artifact_annotations(issues_dir),
        findings_by_id,
    )
    merged_annotations = merge_annotation_findings(imported_annotations + explicit_annotations + issue_annotations, findings_by_id)
    annotations = apply_annotations(soup, assign_sentence_targets(soup, merged_annotations))
    finding_rows = load_findings_rows(findings_path)
    coverage_payload = load_optional_json(coverage_path)
    resolved_layout = resolve_paper_layout(tex_path, paper_layout)
    page_map: dict[str, object] = {}
    if resolved_layout in {"paged", "paged-two-column"}:
        page_map = apply_paged_layout(soup, tex_path, output_path.with_suffix(".page_map.json"))
        if not page_map.get("enabled"):
            resolved_layout = "two-column" if resolved_layout == "paged-two-column" else "single"
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
            coverage=coverage_payload,
            full_report=full_report,
            paper_layout=resolved_layout,
            page_map=page_map,
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
    parser.add_argument("--coverage", type=Path, help="Optional coverage.json for the coverage receipt")
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
        help="Render global Major/Blocker paper-level findings after the paper-reader overlay",
    )
    parser.add_argument(
        "--paper-layout",
        choices=("source", "single", "two-column", "paged", "paged-two-column"),
        default="source",
        help="Paper pane layout; `source` infers single/two-column from generic LaTeX/PDF signals and uses PDF page wrappers when available",
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
        args.coverage,
        args.full_report,
        args.paper_layout,
    )
    print(f"HTML report: {output}")
    print(f"Source HTML: {raw}")
    print(f"Sentence spans: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
