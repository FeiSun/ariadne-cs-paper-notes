#!/usr/bin/env python3
"""Extract Ariadne review units directly from a LaTeX source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_paper_pdf import find_entry_tex, is_within_root, project_root_for


INPUT_RE = re.compile(r"\\(?:input|include|subfile)\{([^{}]+)\}|\\(?:import|subimport)\{([^{}]+)\}\{([^{}]+)\}")
SECTION_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*\{")
CAPTION_RE = re.compile(r"\\caption(?:\s*\[[^\]]*\])?\s*\{")
FOOTNOTE_RE = re.compile(r"\\footnote\s*\{")
LABEL_RE = re.compile(r"\\label\{([^{}]+)\}")
BEGIN_RE = re.compile(r"\\begin\{([^{}]+)\}")
END_RE = re.compile(r"\\end\{([^{}]+)\}")
ITEM_RE = re.compile(r"\\item(?:\s*\[[^\]]*\])?\s*")
REF_RE = re.compile(r"\\(?:eqref|[vV]?ref|autoref|Cref|cref)\{([^{}]+)\}")
CITE_RE = re.compile(r"\\(?:cite|citet|citep|citealp|citeauthor|citeyear)(?:\s*\[[^\]]*\]){0,2}\{([^{}]+)\}")
INLINE_COMMAND_WITH_TEXT_RE = re.compile(
    r"\\(?:textbf|textit|emph|texttt|mathrm|mathbf|mathit|underline|mbox|href|url)\s*\{([^{}]*)\}"
)
COMMAND_WITH_OPT_RE = re.compile(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?")
ABBREVIATIONS = {
    "al.",
    "e.g.",
    "i.e.",
    "vs.",
    "Fig.",
    "Figs.",
    "Eq.",
    "Eqs.",
    "Sec.",
    "Secs.",
    "Tab.",
    "Tabs.",
    "Dr.",
    "Prof.",
}
SECTION_LEVELS = {
    "part": 1,
    "chapter": 1,
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
    "subparagraph": 5,
}
SKIP_PROSE_ENVS = {
    "figure",
    "figure*",
    "wrapfigure",
    "table",
    "table*",
    "wraptable",
    "algorithm",
    "algorithm*",
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "tikzpicture",
    "tabular",
    "tabular*",
}


@dataclass(frozen=True)
class SourceLine:
    path: Path
    line_no: int
    text: str


def strip_latex_comment(line: str) -> str:
    escaped = False
    kept: list[str] = []
    for char in line:
        if char == "%" and not escaped:
            break
        kept.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    return "".join(kept)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def resolve_tex_child(current: Path, root: Path, raw: str) -> Path | None:
    for base in (current.parent, root):
        target = (base / raw).resolve()
        if target.suffix != ".tex":
            target = target.with_suffix(".tex")
        if target.exists() and target.is_file() and is_within_root(target, root):
            return target
    return None


def expand_latex_lines(path: Path, *, root: Path, seen: set[Path] | None = None) -> list[SourceLine]:
    seen = seen or set()
    path = path.resolve()
    if path in seen or not path.exists() or not is_within_root(path, root):
        return []
    seen.add(path)
    expanded: list[SourceLine] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = strip_latex_comment(raw_line)
        pos = 0
        matched = False
        for match in INPUT_RE.finditer(line):
            prefix = line[pos : match.start()].strip()
            if prefix:
                expanded.append(SourceLine(path, line_no, prefix))
            if match.group(1):
                child_raw = match.group(1)
            else:
                child_raw = str(Path(match.group(2) or "") / (match.group(3) or ""))
            child = resolve_tex_child(path, root, child_raw)
            if child is not None:
                expanded.extend(expand_latex_lines(child, root=root, seen=seen))
            pos = match.end()
            matched = True
        suffix = line[pos:].strip()
        if suffix or not matched:
            expanded.append(SourceLine(path, line_no, suffix))
    return expanded


def document_lines(lines: list[SourceLine]) -> list[SourceLine]:
    in_document = False
    selected: list[SourceLine] = []
    for line in lines:
        text = line.text
        if "\\begin{document}" in text:
            in_document = True
            text = text.split("\\begin{document}", 1)[1]
        if "\\end{document}" in text:
            text = text.split("\\end{document}", 1)[0]
            if text.strip():
                selected.append(SourceLine(line.path, line.line_no, text.strip()))
            break
        if in_document:
            selected.append(line)
    return selected if selected else lines


def extract_braced(text: str, open_index: int) -> tuple[str, int] | None:
    if open_index >= len(text) or text[open_index] != "{":
        return None
    depth = 0
    escaped = False
    start = open_index + 1
    for idx in range(open_index, len(text)):
        char = text[idx]
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "{" and not escaped:
            depth += 1
        elif char == "}" and not escaped:
            depth -= 1
            if depth == 0:
                return text[start:idx], idx + 1
        escaped = False
    return None


def slugify(value: str, fallback: str) -> str:
    text = render_tex_text(value)
    tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
    return "-".join(tokens[:8]) or fallback


def parse_aux_labels(entry: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    aux = entry.with_suffix(".aux")
    if not aux.exists():
        return labels
    pattern = re.compile(r"\\newlabel\{([^{}]+)\}\{\{([^{}]*)\}")
    for match in pattern.finditer(aux.read_text(encoding="utf-8", errors="replace")):
        labels[match.group(1)] = match.group(2)
    return labels


def strip_math_delimiters(text: str) -> str:
    text = re.sub(r"\$\$([^$]+)\$\$", r"\1", text)
    text = re.sub(r"\$([^$]+)\$", r"\1", text)
    text = re.sub(r"\\\((.*?)\\\)", r"\1", text)
    text = re.sub(r"\\\[(.*?)\\\]", r"\1", text, flags=re.DOTALL)
    return text


def render_tex_text(text: str, labels: dict[str, str] | None = None) -> str:
    labels = labels or {}
    rendered = text.replace("~", " ")
    rendered = strip_math_delimiters(rendered)
    rendered = REF_RE.sub(lambda m: labels.get(m.group(1), f"[{m.group(1)}]"), rendered)
    rendered = CITE_RE.sub(lambda m: "[" + ", ".join(item.strip() for item in m.group(1).split(",") if item.strip()) + "]", rendered)
    previous = None
    while previous != rendered:
        previous = rendered
        rendered = INLINE_COMMAND_WITH_TEXT_RE.sub(r"\1", rendered)
    rendered = re.sub(r"\\%", "%", rendered)
    rendered = re.sub(r"\\&", "&", rendered)
    rendered = re.sub(r"\\_", "_", rendered)
    rendered = re.sub(r"\\#", "#", rendered)
    rendered = COMMAND_WITH_OPT_RE.sub("", rendered)
    rendered = rendered.replace("{", "").replace("}", "")
    rendered = re.sub(r"\s+", " ", rendered)
    return rendered.strip()


def split_sentences(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    start = 0
    idx = 0
    while idx < len(text):
        char = text[idx]
        if char not in ".!?。！？":
            idx += 1
            continue
        fragment = text[start : idx + 1].strip()
        last_token = fragment.split()[-1] if fragment.split() else ""
        if last_token in ABBREVIATIONS:
            idx += 1
            continue
        next_char = text[idx + 1] if idx + 1 < len(text) else ""
        if next_char and not next_char.isspace() and next_char not in "\"')]}”’":
            idx += 1
            continue
        end = idx + 1
        sentence = text[start:end].strip()
        if sentence:
            leading = len(text[start:end]) - len(text[start:end].lstrip())
            spans.append((sentence, start + leading, end))
        start = end
        idx += 1
    tail = text[start:].strip()
    if tail:
        leading = len(text[start:]) - len(text[start:].lstrip())
        spans.append((tail, start + leading, len(text)))
    return spans


def line_range_for_text(lines: list[SourceLine]) -> tuple[str, int, int]:
    nonempty = [line for line in lines if line.text.strip()]
    if not nonempty:
        line = lines[0]
        return str(line.path), line.line_no, line.line_no
    return str(nonempty[0].path), nonempty[0].line_no, nonempty[-1].line_no


def make_sentence(
    *,
    sentence_id: str,
    unit_kind: str,
    text: str,
    rendered: str,
    source_lines: list[SourceLine],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_file, line_start, line_end = line_range_for_text(source_lines)
    line_start_value: int | str = line_start
    line_end_value: int | str = line_end
    source_line = source_lines[0] if source_lines else None
    if source_line is not None and source_line.path.suffix == ".json" and str(source_line.text).startswith("page:"):
        page_marker = str(source_line.text).split(":", 1)[1]
        line_start_value = page_marker
        line_end_value = page_marker
    payload: dict[str, Any] = {
        "sentence_id": sentence_id,
        "unit_kind": unit_kind,
        "text": text,
        "rendered_text_initial": rendered,
        "rendered_text_pdf": None,
        "source_file": source_file,
        "line_start": line_start_value,
        "line_end": line_end_value,
        "text_hash": sha256_text(text),
    }
    if extra:
        payload.update(extra)
    return payload


def paragraph_id(section_id: str, index: int, unit_kind: str) -> str:
    prefix = {"caption": "cap", "footnote": "fn"}.get(unit_kind, "p")
    return f"{prefix}-{section_id}-{index:03d}"


def sentence_id(paragraph: str, index: int) -> str:
    return f"s-{paragraph.removeprefix('p-').removeprefix('cap-').removeprefix('fn-')}-s{index:03d}"


def flush_paragraph(
    *,
    units: list[dict[str, Any]],
    paragraphs: OrderedDict[str, dict[str, Any]],
    section_id: str,
    section_title: str,
    para_lines: list[SourceLine],
    para_counter: dict[str, int],
    labels: dict[str, str],
    unit_kind: str = "prose",
    extra: dict[str, Any] | None = None,
) -> None:
    text = " ".join(line.text.strip() for line in para_lines if line.text.strip())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return
    rendered = render_tex_text(text, labels)
    if not rendered:
        return
    para_counter[section_id] = para_counter.get(section_id, 0) + 1
    pid = paragraph_id(section_id, para_counter[section_id], unit_kind)
    paragraph = {
        "kind": "paragraph",
        "paragraph_id": pid,
        "section_id": section_id,
        "section_title": section_title,
        "unit_kind": unit_kind,
        "source_file": str(para_lines[0].path),
        "line_start": para_lines[0].line_no,
        "line_end": para_lines[-1].line_no,
        "sentences": [],
    }
    if extra:
        paragraph.update(extra)
    for idx, (raw_sentence, _start, _end) in enumerate(split_sentences(text), 1):
        rendered_sentence = render_tex_text(raw_sentence, labels)
        if not rendered_sentence:
            continue
        paragraph["sentences"].append(
            make_sentence(
                sentence_id=sentence_id(pid, idx),
                unit_kind=unit_kind,
                text=raw_sentence,
                rendered=rendered_sentence,
                source_lines=para_lines,
                extra=extra,
            )
        )
    if paragraph["sentences"]:
        paragraphs[pid] = paragraph
        units.append(paragraph)


def float_kind_for_env(env_stack: list[str]) -> str:
    for env in reversed(env_stack):
        if "table" in env:
            return "table"
        if "figure" in env:
            return "figure"
        if "algorithm" in env:
            return "algorithm"
    return "caption"


def assign_label_to_caption_unit(unit: dict[str, Any] | None, label: str) -> bool:
    if not label or not isinstance(unit, dict) or unit.get("unit_kind") != "caption" or unit.get("label"):
        return False
    unit["label"] = label
    for sentence in unit.get("sentences", []):
        if isinstance(sentence, dict):
            sentence["label"] = label
    return True


def assign_label_to_recent_caption(units: list[dict[str, Any]], label: str) -> None:
    if not label:
        return
    for unit in reversed(units):
        if unit.get("kind") != "paragraph":
            continue
        if unit.get("unit_kind") != "caption":
            return
        assign_label_to_caption_unit(unit, label)
        return


def extract_footnotes(text: str) -> tuple[str, list[str]]:
    footnotes: list[str] = []
    pieces: list[str] = []
    pos = 0
    while True:
        match = FOOTNOTE_RE.search(text, pos)
        if not match:
            pieces.append(text[pos:])
            break
        pieces.append(text[pos : match.start()])
        braced = extract_braced(text, match.end() - 1)
        if braced is None:
            pieces.append(text[match.start() : match.end()])
            pos = match.end()
            continue
        footnotes.append(braced[0])
        pos = braced[1]
    return "".join(pieces), footnotes


def extract_units(entry: Path) -> list[dict[str, Any]]:
    entry = find_entry_tex(entry.expanduser().resolve())
    root = project_root_for(entry)
    labels = parse_aux_labels(entry)
    lines = document_lines(expand_latex_lines(entry, root=root))
    units: list[dict[str, Any]] = []
    paragraphs: OrderedDict[str, dict[str, Any]] = OrderedDict()
    para_lines: list[SourceLine] = []
    para_counter: dict[str, int] = {}
    current_section_id = "front-matter"
    current_section_title = "Front matter"
    seen_sections: set[str] = set()
    env_stack: list[str] = []
    pending_caption_unit: dict[str, Any] | None = None
    pending_section_unit: dict[str, Any] | None = None

    def add_section(command: str, title: str, source_line: SourceLine) -> None:
        nonlocal current_section_id, current_section_title, pending_section_unit
        current_section_id = slugify(title, f"section-{len(seen_sections) + 1}")
        current_section_title = render_tex_text(title, labels)
        pending_section_unit = None
        if current_section_id not in seen_sections:
            unit = {
                "kind": "section",
                "section_id": current_section_id,
                "level": SECTION_LEVELS.get(command, 1),
                "text": current_section_title,
                "unit_kind": "section_heading",
                "source_file": str(source_line.path),
                "line_start": source_line.line_no,
                "line_end": source_line.line_no,
                "aliases": [],
            }
            units.append(unit)
            pending_section_unit = unit
            seen_sections.add(current_section_id)

    for source_line in lines:
        text = source_line.text.strip()
        if not text:
            flush_paragraph(
                units=units,
                paragraphs=paragraphs,
                section_id=current_section_id,
                section_title=current_section_title,
                para_lines=para_lines,
                para_counter=para_counter,
                labels=labels,
            )
            para_lines = []
            continue

        label_only_match = LABEL_RE.fullmatch(text)
        if label_only_match and pending_section_unit is not None and not any(env != "document" for env in env_stack):
            label = label_only_match.group(1)
            aliases = pending_section_unit.setdefault("aliases", [])
            if isinstance(aliases, list) and label not in aliases:
                aliases.append(label)
            pending_section_unit = None
            continue
        if pending_section_unit is not None:
            pending_section_unit = None

        section_match = SECTION_RE.search(text)
        if section_match:
            flush_paragraph(
                units=units,
                paragraphs=paragraphs,
                section_id=current_section_id,
                section_title=current_section_title,
                para_lines=para_lines,
                para_counter=para_counter,
                labels=labels,
            )
            para_lines = []
            braced = extract_braced(text, section_match.end() - 1)
            if braced:
                add_section(section_match.group(1), braced[0], source_line)
                label_match = LABEL_RE.search(text[braced[1] :])
                if label_match and pending_section_unit is not None:
                    aliases = pending_section_unit.setdefault("aliases", [])
                    label = label_match.group(1)
                    if isinstance(aliases, list) and label not in aliases:
                        aliases.append(label)
                    pending_section_unit = None
            continue

        for begin in BEGIN_RE.finditer(text):
            env_stack.append(begin.group(1))

        text_without_footnotes, footnotes = extract_footnotes(text)
        if footnotes:
            text = text_without_footnotes.strip()
            source_line = SourceLine(source_line.path, source_line.line_no, text)
            for footnote_text in footnotes:
                flush_paragraph(
                    units=units,
                    paragraphs=paragraphs,
                    section_id=current_section_id,
                    section_title=current_section_title,
                    para_lines=[SourceLine(source_line.path, source_line.line_no, footnote_text)],
                    para_counter=para_counter,
                    labels=labels,
                    unit_kind="footnote",
                )
            if not text:
                continue

        caption_match = CAPTION_RE.search(text)
        if caption_match:
            braced = extract_braced(text, caption_match.end() - 1)
            if braced:
                label_match = LABEL_RE.search(text[braced[1] :])
                label = label_match.group(1) if label_match else ""
                before_units = len(units)
                flush_paragraph(
                    units=units,
                    paragraphs=paragraphs,
                    section_id=current_section_id,
                    section_title=current_section_title,
                    para_lines=[SourceLine(source_line.path, source_line.line_no, braced[0])],
                    para_counter=para_counter,
                    labels=labels,
                    unit_kind="caption",
                    extra={"float_kind": float_kind_for_env(env_stack), "label": label},
                )
                pending_caption_unit = units[-1] if len(units) > before_units and units[-1].get("unit_kind") == "caption" else None
        elif float_kind_for_env(env_stack) in {"figure", "table", "algorithm"}:
            label_match = LABEL_RE.search(text)
            if label_match:
                label = label_match.group(1)
                if not assign_label_to_caption_unit(pending_caption_unit, label):
                    assign_label_to_recent_caption(units, label)

        item_match = ITEM_RE.match(text)
        if item_match:
            flush_paragraph(
                units=units,
                paragraphs=paragraphs,
                section_id=current_section_id,
                section_title=current_section_title,
                para_lines=para_lines,
                para_counter=para_counter,
                labels=labels,
            )
            para_lines = []
            item_text = text[item_match.end() :].strip()
            if item_text:
                flush_paragraph(
                    units=units,
                    paragraphs=paragraphs,
                    section_id=current_section_id,
                    section_title=current_section_title,
                    para_lines=[SourceLine(source_line.path, source_line.line_no, item_text)],
                    para_counter=para_counter,
                    labels=labels,
                    unit_kind="item",
                )
        elif not any(env in SKIP_PROSE_ENVS for env in env_stack):
            if not text.startswith("\\"):
                para_lines.append(source_line)

        for end in END_RE.finditer(text):
            env = end.group(1)
            if env in env_stack:
                env_stack = env_stack[: len(env_stack) - 1 - env_stack[::-1].index(env)]
                if float_kind_for_env(env_stack) == "caption":
                    pending_caption_unit = None

    flush_paragraph(
        units=units,
        paragraphs=paragraphs,
        section_id=current_section_id,
        section_title=current_section_title,
        para_lines=para_lines,
        para_counter=para_counter,
        labels=labels,
    )
    return units


def append_layout_units(units: list[dict[str, Any]], layout_audit: Path | None) -> None:
    if layout_audit is None or not layout_audit.exists():
        return
    try:
        payload = json.loads(layout_audit.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    page_summaries = payload.get("page_summaries") if isinstance(payload.get("page_summaries"), list) else []
    observations = payload.get("observations") if isinstance(payload.get("observations"), list) else []
    observations_by_page: dict[int, list[dict[str, Any]]] = {}
    for observation in observations:
        if isinstance(observation, dict) and isinstance(observation.get("page"), int):
            observations_by_page.setdefault(int(observation["page"]), []).append(observation)
    if page_summaries or observations_by_page:
        units.append(
            {
                "kind": "section",
                "section_id": "layout",
                "level": 1,
                "text": "Rendered PDF layout",
                "unit_kind": "section_heading",
                "source_file": str(layout_audit),
                "line_start": 1,
                "line_end": 1,
            }
        )
    for summary in page_summaries:
        if not isinstance(summary, dict) or not isinstance(summary.get("page"), int):
            continue
        page = int(summary["page"])
        page_observations = observations_by_page.get(page, [])
        metrics = {
            "line_count": summary.get("line_count", 0),
            "word_count": summary.get("word_count", 0),
            "observations": summary.get("observations", len(page_observations)),
            "needs_main_review": bool(summary.get("needs_main_review")),
            "observation_ids": [str(item.get("observation_id")) for item in page_observations if item.get("observation_id")],
        }
        text = (
            f"Page {page} layout has {metrics['line_count']} text lines, "
            f"{metrics['word_count']} words, and {metrics['observations']} layout observations."
        )
        pid = f"layout-page-{page:03d}"
        units.append(
            {
                "kind": "paragraph",
                "paragraph_id": pid,
                "section_id": "layout",
                "section_title": "Rendered PDF layout",
                "unit_kind": "page_layout",
                "source_file": str(layout_audit),
                "line_start": f"page:{page}",
                "line_end": f"page:{page}",
                "page": page,
                "metrics": metrics,
                "sentences": [
                    {
                        "sentence_id": f"s-{pid}-s001",
                        "unit_kind": "page_layout",
                        "text": text,
                        "rendered_text_initial": text,
                        "rendered_text_pdf": text,
                        "source_file": str(layout_audit),
                        "line_start": f"page:{page}",
                        "line_end": f"page:{page}",
                        "text_hash": sha256_text(text),
                        "page": page,
                        "metrics": metrics,
                    }
                ],
            }
        )


def write_jsonl(units: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
            current_section = str(section_id)
            continue
        if unit.get("kind") != "paragraph" or not unit.get("sentences"):
            continue
        section_id = str(unit.get("section_id", ""))
        if section_id and section_id != current_section:
            lines.append(f"## {unit.get('section_title', section_id)} {{#{section_id}}}")
            lines.append("")
            current_section = section_id
        lines.append(f"[{unit.get('paragraph_id', '')}]")
        for sentence in unit.get("sentences", []):
            source = Path(str(sentence.get("source_file") or "")).name
            line_start = sentence.get("line_start", "")
            rendered = sentence.get("rendered_text_initial") or sentence.get("text") or ""
            lines.append(f"{{{sentence['sentence_id']}}} {rendered}  [src: {source}:{line_start}]")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tex", type=Path, help="LaTeX project directory or entry .tex file")
    parser.add_argument("--jsonl", type=Path, help="Write machine-readable review units")
    parser.add_argument("--markdown", "--md", dest="markdown", type=Path, help="Write compact model-facing Markdown")
    parser.add_argument("--layout-audit", type=Path, help="Append page_layout review units from layout_audit.json")
    args = parser.parse_args(argv)

    entry = find_entry_tex(args.tex.expanduser().resolve())
    units = extract_units(entry)
    append_layout_units(units, args.layout_audit.expanduser().resolve() if args.layout_audit else None)
    jsonl_path = args.jsonl or entry.with_suffix(".review_units.jsonl")
    markdown_path = args.markdown or entry.with_suffix(".review_units.md")
    write_jsonl(units, jsonl_path)
    write_markdown(units, markdown_path)

    paragraphs = [unit for unit in units if unit.get("kind") == "paragraph" and unit.get("sentences")]
    sentence_count = sum(len(unit.get("sentences", [])) for unit in paragraphs)
    print(f"Review units JSONL: {jsonl_path}")
    print(f"Review units Markdown: {markdown_path}")
    print(f"Sections: {sum(1 for unit in units if unit.get('kind') == 'section')}")
    print(f"Paragraphs: {len(paragraphs)}")
    print(f"Sentences: {sentence_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
