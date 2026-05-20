#!/usr/bin/env python3
"""Render a LaTeX paper into Ariadne's paper-reader HTML preview."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
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


def pdf_embed_to_data_uri(pdf_path: Path) -> str | None:
    if shutil.which("pdftoppm") is None or not pdf_path.exists():
        return None
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = Path(tmpdir) / "page"
        command = ["pdftoppm", "-png", "-singlefile", "-r", "144", str(pdf_path), str(prefix)]
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            return None
        png_path = prefix.with_suffix(".png")
        if not png_path.exists():
            return None
        encoded = base64.b64encode(png_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"


def inline_pdf_assets(soup: BeautifulSoup, tex_dir: Path) -> int:
    """Rasterize local PDF embeds so the preview is stable outside a PDF plugin."""

    converted = 0
    for embed in list(soup.find_all("embed")):
        src = str(embed.get("src", ""))
        if not src.lower().endswith(".pdf") or src.startswith(("data:", "http://", "https://")):
            continue
        data_uri = pdf_embed_to_data_uri((tex_dir / src).resolve())
        if data_uri is None:
            add_class(embed, "paper-pdf-embed")
            continue
        img = soup.new_tag("img")
        img["src"] = data_uri
        img["alt"] = f"Rendered PDF asset: {Path(src).name}"
        img["class"] = "paper-asset-image"
        img["data-source-pdf"] = src
        embed.replace_with(img)
        converted += 1
    return converted


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
            section_slug = slugify(node.get("id") or node.get_text(" ", strip=True), f"section-{paragraph_index}")
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
        severity_rationale = html.escape(item.get("severity_rationale", ""))
        location = html.escape(item.get("location", ""))
        snippet = html.escape(item.get("snippet", ""))
        evidence_basis = html.escape(item.get("evidence_basis", ""))
        verification_method = html.escape(item.get("verification_method", ""))
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
            <dt>层级</dt><dd>{level_label}</dd>
            <dt>位置</dt><dd>{location or target_id or source_section_label or "全局批注"}</dd>
            {f"<dt>来源栏目</dt><dd>{source_section_label}</dd>" if source_section_label else ""}
            {f"<dt>原句/片段</dt><dd>{snippet}</dd>" if snippet else ""}
            <dt>问题是什么</dt><dd>{problem or "未填写"}</dd>
            <dt>为什么有问题</dt><dd>{why or "未填写"}</dd>
            <dt>违反原则</dt><dd>{principle or "未填写"}</dd>
            <dt>严重度理由</dt><dd>{severity_rationale or short_badge}</dd>
            {f"<dt>置信度</dt><dd>{confidence}</dd>" if confidence else ""}
            <dt>证据/验证</dt><dd>{evidence_basis or "未填写"}{("；" + verification_method) if verification_method else ""}</dd>
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
) -> str:
    source_artifact = html.escape(str(raw_html_path))
    tex_display = html.escape(str(tex_path))
    raw_hash_attr = html.escape(raw_hash)
    title_html = html.escape(title)
    annotation_count = len(annotations)
    annotation_panel_state = ' data-empty="true"' if annotations else ""
    annotation_cards = render_annotation_cards(annotations)
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
<article class="review-report" data-report-kind="paper-reader-only">
  <header>
    <h1>Ariadne Paper Reader Preview</h1>
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
    <a href="#coverage-receipt">覆盖回执</a>
  </nav>
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
    <section id="coverage-receipt">
      <h2>覆盖回执与 artifacts</h2>
      <div class="table-wrap">
        <table class="report-table">
          <caption>Paper-reader rendering receipt</caption>
          <thead><tr><th scope="col">Unit</th><th scope="col">Value</th></tr></thead>
          <tbody>
            <tr><td>Source backend</td><td>{PANDOC_SOURCE}</td></tr>
            <tr><td>Source artifact</td><td>{source_artifact}</td></tr>
            <tr><td>Source hash</td><td>{raw_hash_attr}</td></tr>
            <tr><td>Sentence ID scheme</td><td>{SENTENCE_ID_SCHEME}</td></tr>
            <tr><td>Sentence spans</td><td>{sentence_count}</td></tr>
            <tr><td>Annotations</td><td>{annotation_count}</td></tr>
            <tr><td>Coverage consistency</td><td>paper-reader preview only; review artifacts not generated.</td></tr>
          </tbody>
        </table>
      </div>
    </section>
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
    review_html_path: Path | None = None,
) -> tuple[Path, Path, int]:
    tex_path = tex_path.resolve()
    output_path = (output_path or tex_path.with_name(f"ariadne_paper_reader_{tex_path.stem}.html")).resolve()
    raw_html_path = (raw_html_path or output_path.with_suffix(".source.html")).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_html_path.parent.mkdir(parents=True, exist_ok=True)
    run_pandoc(tex_path, raw_html_path)
    raw_hash = sha256_path(raw_html_path)
    soup = BeautifulSoup(raw_html_path.read_text(encoding="utf-8"), "lxml")
    cleanup_pandoc_artifacts(soup)
    inline_pdf_assets(soup, tex_path.parent)
    restore_latex_labels(soup, tex_path)
    ensure_references_heading(soup)
    title = extract_title(soup, tex_path)
    sentence_count = wrap_sentences(soup)
    imported_annotations = load_review_html_annotations(review_html_path)
    explicit_annotations = load_annotations(annotations_path)
    annotations = apply_annotations(soup, assign_sentence_targets(soup, imported_annotations + explicit_annotations))
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
    parser.add_argument("--review-html", type=Path, help="Optional existing Ariadne HTML report to import as annotation content")
    args = parser.parse_args(argv)
    output, raw, count = render(args.tex, args.output, args.raw_html, args.annotations, args.review_html)
    print(f"HTML report: {output}")
    print(f"Source HTML: {raw}")
    print(f"Sentence spans: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
