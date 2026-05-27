#!/usr/bin/env python3
"""Extract readable text and reviewer-facing signals from a LaTeX project or PDF."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


MAX_DEFAULT_ITEMS = 100
SUBPROCESS_TIMEOUT_SECONDS = 60
PROJECT_MARKERS = {".git", ".latexmkrc", "latexmkrc", "Makefile", "makefile"}
RESOURCE_DIRS = {"bib", "bibs", "bibliography", "references", "figures", "figure", "fig", "tables", "sections"}
TEX_CONTAINER_DIRS = {"src", "tex", "source", "sources", "latex", "paper"}

SECTION_CMD_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
CAPTION_CMD_RE = re.compile(r"\\caption(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
TABULAR_ENV_RE = re.compile(r"\\begin\{(tabular\*?|tabularx|array|longtable|tabu)\}(.*?)\\end\{\1\}", re.DOTALL)
TITLE_CMD_RE = re.compile(r"\\title\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
ABSTRACT_ENV_RE = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.DOTALL)
DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^{}]+)\}")
INPUT_RE = re.compile(r"\\(?:input|include|subfile)\{([^{}]+)\}|\\(?:import|subimport)\{([^{}]+)\}\{([^{}]+)\}")
REF_CMD_RE = re.compile(r"\\(?:ref|cref|Cref|autoref|eqref)\{([^{}]*)\}")
CITE_CMD_RE = re.compile(r"\\(?:cite|citep|citet|parencite|textcite|citeauthor|citeyear)\*?(?:\[[^\]]*\])?(?:\[[^\]]*\])?\{([^{}]*)\}")
BIB_CMD_RE = re.compile(r"\\(?:bibliography|addbibresource|addglobalbib|addsectionbib)\{([^{}]+)\}")
BIB_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n\s*@\w+\s*\{|\Z)", re.DOTALL)
BIB_PUBLICATION_ENTRY_RE = re.compile(r"@(?!string|comment|preamble)\w+\s*\{", re.IGNORECASE)
BIB_FIELD_RE = re.compile(
    r"(?i)(?:^|[,\s])([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|\"([^\"]*)\")\s*,?"
)
TODO_RE = re.compile(r"(\\todo(?:\[[^\]]*\])?\{[^{}]*\}|\bTODO\b|\bTBD\b|\bFIXME\b)", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(
    r"(lorem ipsum|\bXXX\b|"
    r"\\(?:cite|citep|citet|parencite|textcite)\{[^{}?]*\?[^{}]*\}|"
    r"\\(?:ref|cref|Cref|autoref|eqref)\{[^{}?]*\?\?[^{}]*\}|"
    r"(?<![A-Za-z0-9])\?\?(?![A-Za-z0-9]))",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?")
ABS_PATH_RE = re.compile(r"(/Users/[^ \n{}]+|/home/[^ \n{}]+|C:\\Users\\[^ \n{}]+)")
AUTHOR_RE = re.compile(r"\\author(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
AFFILIATION_RE = re.compile(r"\\(?:affil|affiliation|institute)(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
THANKS_RE = re.compile(r"\\thanks\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
ACK_RE = re.compile(r"\\(?:section|subsection)\*?\{Acknowledg(?:e)?ments?\}", re.IGNORECASE)
ORCID_RE = re.compile(r"(?:ORCID|orcid)[^A-Za-z0-9]*(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")
ANON_SWITCH_RE = re.compile(
    r"(\\(?:final|cameraready|iclrfinalcopy|icmlfinalcopy)\b|anonymous\s*=\s*false|nonanonymous|(?<![A-Za-z\\])finalcopy\b)",
    re.IGNORECASE,
)
CAMERA_READY_TEXT_RE = re.compile(r"\bcamera[- ]ready\b", re.IGNORECASE)
EQUATION_ENV_RE = re.compile(r"\\begin\{(equation|align|gather|multline|split|flalign)[*]?\}(.*?)\\end\{\1[*]?\}", re.DOTALL)
DISPLAY_MATH_RE = re.compile(r"\\\[(.*?)\\\]|\$\$(.*?)\$\$", re.DOTALL)
NEWCOMMAND_RE = re.compile(
    r"\\(?:re)?newcommand\*?\s*\{\\([A-Za-z]+)\}(?:\[[^\]]+\]){0,2}\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
    re.DOTALL,
)
DEF_RE = re.compile(r"\\def\\([A-Za-z]+)(?:\s*#\d)*\s*\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
DECLARE_MATH_OPERATOR_RE = re.compile(r"\\DeclareMathOperator\*?\s*\{\\([A-Za-z]+)\}\s*\{([^{}]*)\}", re.DOTALL)
MATH_COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
COMMON_LATEX_COMMANDS = {
    "begin",
    "end",
    "label",
    "ref",
    "eqref",
    "cite",
    "citep",
    "citet",
    "text",
    "textnormal",
    "textrm",
    "textit",
    "textbf",
    "mathrm",
    "mathbf",
    "mathit",
    "mathsf",
    "mathtt",
    "mathcal",
    "mathbb",
    "mathfrak",
    "operatorname",
    "left",
    "right",
    "middle",
    "big",
    "Big",
    "bigg",
    "Bigg",
    "frac",
    "dfrac",
    "tfrac",
    "sqrt",
    "sum",
    "prod",
    "int",
    "iint",
    "iiint",
    "lim",
    "log",
    "ln",
    "exp",
    "min",
    "max",
    "argmin",
    "argmax",
    "sin",
    "cos",
    "tan",
    "Pr",
    "mathop",
    "overline",
    "underline",
    "widehat",
    "widetilde",
    "hat",
    "tilde",
    "bar",
    "vec",
    "dot",
    "ddot",
    "cdot",
    "times",
    "otimes",
    "oplus",
    "leq",
    "geq",
    "neq",
    "approx",
    "sim",
    "simeq",
    "propto",
    "in",
    "notin",
    "subset",
    "supset",
    "subseteq",
    "supseteq",
    "cup",
    "cap",
    "forall",
    "exists",
    "nabla",
    "partial",
    "infty",
    "ldots",
    "cdots",
    "dots",
    "quad",
    "qquad",
}
GREEK_COMMANDS = {
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "varepsilon",
    "zeta",
    "eta",
    "theta",
    "vartheta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "pi",
    "varpi",
    "rho",
    "varrho",
    "sigma",
    "varsigma",
    "tau",
    "upsilon",
    "phi",
    "varphi",
    "chi",
    "psi",
    "omega",
    "Gamma",
    "Delta",
    "Theta",
    "Lambda",
    "Xi",
    "Pi",
    "Sigma",
    "Upsilon",
    "Phi",
    "Psi",
    "Omega",
}
VARIANT_SYMBOL_PAIRS = (
    ("epsilon", "varepsilon"),
    ("theta", "vartheta"),
    ("pi", "varpi"),
    ("rho", "varrho"),
    ("sigma", "varsigma"),
    ("phi", "varphi"),
)
SECTION_HEADING_WORDS = (
    "Abstract|Introduction|Related Work|Background|Method|Methods|Approach|"
    "Experiments|Evaluation|Results|Analysis|Discussion|Limitations|Conclusion|References|Appendix"
)
GENERIC_NUMBERED_HEADING = r"\d+(?:\.\d+)*[^\S\n]+([A-Z][^,.\n!?]{2,60}|[\u4e00-\u9fff][^\n。！？,.]{1,60})"
COMMON_SECTION_HEADING = rf"(?:\d+(?:\.\d+)*\s+)?({SECTION_HEADING_WORDS})\b[^\n]{{0,60}}"
PDF_SECTION_RE = re.compile(rf"^[^\S\n]*(?:({GENERIC_NUMBERED_HEADING})|{COMMON_SECTION_HEADING})[^\S\n]*$", re.IGNORECASE | re.MULTILINE)
GENERAL_HEADING_RE = re.compile(
    rf"^#{{1,3}}\s+(.+)$|"
    rf"^[^\S\n]*(?:({GENERIC_NUMBERED_HEADING})|{COMMON_SECTION_HEADING})[^\S\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
PDF_CAPTION_RE = re.compile(r"\b(?:Figure|Fig\.|Table)\s+\d+[:.]\s+([^\n]{10,500})", re.IGNORECASE)
PDF_CITE_RE = re.compile(
    r"\[(?:\d+(?:,\s*\d+)*(?:-\d+)?)\]|"
    r"\[[A-Z][^\]\n]{0,180}\b\d{4}[a-z]?[^\]\n]*\]|"
    r"\[[A-Za-z][A-Za-z0-9:_-]*\d{4}[A-Za-z0-9:_-]*\]|"
    r"\([A-Z][A-Za-z-]+(?: et al\.)?,\s*\d{4}\)|"
    r"\b[A-Z][A-Za-z-]+ et al\.\s*\[\d+\]"
)
PDF_LINE_NUMBER_HEADING_RE = re.compile(r"^\s*\d{1,4}\s{2,}\S")
PLACEHOLDER_CAPTIONS = {"caption", "figure caption", "table caption"}


@dataclass
class ExtractionState:
    warnings: list[str] = field(default_factory=list)
    source_files: list[Path] = field(default_factory=list)
    bib_files: list[Path] = field(default_factory=list)
    pdf_page_count: int | None = None
    pdf_page_count_source: str | None = None


@dataclass(frozen=True)
class ParsedNumber:
    value: float
    text: str
    decimals: int


@dataclass(frozen=True)
class PositionedNumber:
    value: float
    text: str
    decimals: int
    start: int
    end: int


def read_text(path: Path, state: ExtractionState | None = None) -> str:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    if state is not None and "\ufffd" in text:
        state.warnings.append(f"Non-UTF-8 bytes in {path}; replaced undecodable characters with U+FFFD.")
    return text


def one_line(text: str) -> str:
    text = strip_latex_comments(text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", text)
    text = re.sub(r"[{}]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def nonempty_command_payloads(pattern: re.Pattern[str], raw: str) -> list[str]:
    payloads: list[str] = []
    for match in pattern.finditer(raw):
        payload = one_line(match.group(1))
        if payload:
            payloads.append(payload)
    return payloads


def command_payloads(pattern: re.Pattern[str], raw: str, max_items: int) -> list[str]:
    payloads = []
    for match in pattern.finditer(raw):
        payload = THANKS_RE.sub("", match.group(1))
        payloads.append(one_line(payload))
    return payloads[:max_items]


def signal_snippet(text: str) -> str:
    return re.sub(r"\s+", " ", strip_latex_comments(text)).strip()


def signal_line_items(pattern: re.Pattern[str], text: str) -> list[tuple[int, str]]:
    return [(text.count("\n", 0, match.start()) + 1, signal_snippet(match.group(0))) for match in pattern.finditer(text)]


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def is_pdf_noise_heading(line: str) -> bool:
    stripped = re.sub(r"\s+", " ", line).strip()
    if not stripped:
        return True
    if "\f" in line:
        return True
    if PDF_LINE_NUMBER_HEADING_RE.match(line):
        return True
    if re.fullmatch(r"[\d\s.,%+-]+", stripped):
        return True
    if re.match(r"^\d+(?:\.\d+)?\s+[A-Z][A-Za-z0-9./%+-]+(?:\s+[A-Z][A-Za-z0-9./%+-]+){1,}$", stripped):
        return True
    return False


def split_unescaped_ampersand(row: str) -> list[str]:
    cells: list[str] = []
    start = 0
    for match in re.finditer("&", row):
        slash_count = 0
        idx = match.start() - 1
        while idx >= 0 and row[idx] == "\\":
            slash_count += 1
            idx -= 1
        if slash_count % 2 == 0:
            cells.append(row[start : match.start()])
            start = match.end()
    cells.append(row[start:])
    return cells


def normalized_cell_text(cell: str) -> str:
    cell = re.sub(r"\\(?:toprule|midrule|bottomrule|hline)\b", "", cell)
    cell = re.sub(r"\\(?:cmidrule|cline)(?:\([^)]*\))?\{[^{}]*\}", "", cell)
    cell = cell.replace(r"\&", "&")
    return one_line(cell)


def parse_visible_number(cell: str) -> ParsedNumber | None:
    match = re.search(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?", cell)
    if not match:
        return None
    raw = match.group(0)
    cleaned = raw.rstrip("%").replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    decimals = len(cleaned.split(".", 1)[1]) if "." in cleaned else 0
    return ParsedNumber(value=value, text=raw, decimals=decimals)


def parse_positioned_numbers(line: str) -> list[PositionedNumber]:
    numbers: list[PositionedNumber] = []
    for match in re.finditer(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?", line):
        raw = match.group(0)
        cleaned = raw.rstrip("%").replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        decimals = len(cleaned.split(".", 1)[1]) if "." in cleaned else 0
        numbers.append(PositionedNumber(value=value, text=raw, decimals=decimals, start=match.start(), end=match.end()))
    return numbers


def pdf_component_group_markers(line: str) -> list[str]:
    """Return visible per-column group markers such as DSRp/DSRh from PDF text.

    Method-A-style Score X tables print six dataset columns but define the
    final score as the mean of two component means (DSRp and DSRh), not as a
    direct six-cell mean. Capturing the visible group markers lets the PDF-only
    audit reproduce that table-local formula instead of emitting the wrong
    direct mean.
    """

    return [match.group(1).upper() for match in re.finditer(r"\(\s*(DSRp|DSRh)\s*\)", line, re.IGNORECASE)]


def pdf_summary_header_indices(line: str) -> list[int]:
    """Infer summary-column positions from a PDF-extracted table header line.

    Example: ``Art Business ... Humanities Avg. Recognition ... Realworld Avg.``
    maps to summary columns 7 and 12 in the numeric rows that follow. This
    prevents wide multi-metric tables from being audited as if the final value
    were the mean of the whole row.
    """

    if parse_positioned_numbers(line):
        return []
    if re.search(r"\b(?:Table|Figure|Section|Appendix|References)\b", line, re.IGNORECASE):
        return []
    if not re.search(r"\b(?:Avg\.?|Average|Mean|Score|Total|Overall)\b|平均|总|總", line, re.IGNORECASE):
        return []
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9./-]*|平均|总|總", line)
    if len(tokens) < 4:
        return []
    leading_text_columns = 0
    for token in tokens:
        if token.strip(".").lower() in {"model", "method", "dataset", "data", "type"}:
            leading_text_columns += 1
            continue
        break
    indices: list[int] = []
    for idx, token in enumerate(tokens):
        cleaned = token.strip(".").lower()
        if cleaned in {"avg", "average", "mean", "score", "total", "overall"} or token in {"平均", "总", "總"}:
            numeric_idx = idx - leading_text_columns
            if numeric_idx >= 0:
                indices.append(numeric_idx)
    return indices


STRUCTURAL_TABLE_CELL_RE = re.compile(r"\\(?:multirow|multicolumn|cline|cmidrule|toprule|midrule|bottomrule|hline)\b")
SUMMARY_COLUMN_RE = re.compile(
    r"\b(?:avg|average|mean|macro\s*avg|micro\s*avg|overall|total|sum|score|safety\s*score)\b|平均|总|總",
    re.IGNORECASE,
)
SUMMARY_ROW_RE = re.compile(r"^(?:avg|average|mean|macro avg|micro avg|overall|total|sum|平均|总|總)$", re.IGNORECASE)


def format_number(value: float, decimals: int) -> str:
    decimals = max(2, min(decimals, 4))
    return f"{value:.{decimals}f}"


def classify_arithmetic_gap(reported: float, computed: float) -> tuple[str, float, float]:
    gap_abs = abs(reported - computed)
    gap_rel = gap_abs / max(abs(computed), 1e-9) * 100
    if gap_abs >= 2.0 or gap_rel >= 5.0:
        return "deterministic", gap_abs, gap_rel
    if gap_abs >= 0.5 or gap_rel >= 1.0:
        return "likely_error", gap_abs, gap_rel
    return "ambiguous", gap_abs, gap_rel


def numeric_tolerance(decimals: int) -> float:
    return 0.5 * 10 ** (-max(decimals, 0))


def visible_table_rows(raw_body: str) -> list[tuple[int, list[str]]]:
    body = re.sub(r"^\s*(?:\{[^{}]*\}){1,2}", "", raw_body)
    rows: list[tuple[int, list[str]]] = []
    for row_idx, row in enumerate(re.split(r"(?<!\\)\\\\", body), 1):
        row_clean = re.sub(r"%.*", "", row).strip()
        if not row_clean or re.fullmatch(r"\\(?:toprule|midrule|bottomrule|hline)\s*", row_clean):
            continue
        cells = [normalized_cell_text(cell) for cell in split_unescaped_ampersand(row_clean)]
        rows.append((row_idx, cells))
    return rows


def structural_table_row(cells: list[str]) -> bool:
    nonempty = [cell for cell in cells if cell.strip()]
    if not nonempty:
        return True
    structural_cells = sum(1 for cell in nonempty if STRUCTURAL_TABLE_CELL_RE.search(cell))
    numeric_cells = sum(1 for cell in cells if parse_visible_number(cell) is not None)
    return bool(structural_cells and numeric_cells == 0)


def table_blank_positions(cells: list[str]) -> list[int]:
    if structural_table_row(cells):
        return []
    first_nonempty = next((idx for idx, cell in enumerate(cells) if cell.strip()), len(cells))
    return [
        idx + 1
        for idx, cell in enumerate(cells)
        if idx >= first_nonempty and (not cell or cell in {"-", "--", "–", "—", "N/A", "NA", "n/a", "?"})
    ]


def table_numeric_signals(table_idx: int, rows: list[tuple[int, list[str]]]) -> list[str]:
    signals: list[str] = []
    latest_header: list[str] | None = None
    prior_numeric_rows: list[tuple[int, list[str], list[ParsedNumber | None]]] = []

    for row_idx, cells in rows:
        parsed = [parse_visible_number(cell) for cell in cells]
        numeric_count = sum(1 for number in parsed if number is not None)
        if cells and any(SUMMARY_COLUMN_RE.search(cell) for cell in cells) and numeric_count < max(1, len(cells) // 2):
            latest_header = cells
            continue

        if latest_header:
            for col_idx, number in enumerate(parsed):
                if number is None or col_idx >= len(latest_header):
                    continue
                header = latest_header[col_idx]
                if not SUMMARY_COLUMN_RE.search(header):
                    continue
                component_numbers = [
                    component.value
                    for idx, component in enumerate(parsed[:col_idx])
                    if idx > 0 and component is not None
                ]
                if len(component_numbers) < 2:
                    continue
                visible_mean = sum(component_numbers) / len(component_numbers)
                delta = number.value - visible_mean
                if abs(delta) <= numeric_tolerance(number.decimals):
                    continue
                row_label = cells[0] if cells else f"row {row_idx}"
                component_cols = ", ".join(str(idx + 1) for idx, component in enumerate(parsed[:col_idx]) if idx > 0 and component is not None)
                tier, gap_abs, gap_rel = classify_arithmetic_gap(number.value, visible_mean)
                signals.append(
                    f"Signal ({tier} gap {gap_abs:.2f}pp / {gap_rel:.2f}%): "
                    f"Table {table_idx}, row {row_idx} ({row_label!r}), column {col_idx + 1} ({header!r}): "
                    f"reported {number.text}; visible arithmetic mean of column(s) {component_cols} = "
                    f"{format_number(visible_mean, number.decimals)}; delta {delta:+.{max(2, min(number.decimals, 4))}f}. "
                    + (
                        "Rendered finding must be Blocker. Gap exceeds the broad plausible aggregation range; render as a directive numeric finding unless the manuscript gives a specific denominator/weighting explanation."
                        if tier == "deterministic"
                        else "Rendered finding must be Blocker and state the concrete reported value, visible computed value, and delta; if weighted/micro aggregation could explain it, name that as the rebuttal instead of using vague 'needs checking' language."
                    )
                )

        row_label = cells[0].strip().lower() if cells else ""
        if SUMMARY_ROW_RE.fullmatch(row_label or "") and len(prior_numeric_rows) >= 2:
            for col_idx, number in enumerate(parsed):
                if col_idx == 0 or number is None:
                    continue
                components = [
                    prev_parsed[col_idx].value
                    for _, prev_cells, prev_parsed in prior_numeric_rows
                    if col_idx < len(prev_parsed) and prev_parsed[col_idx] is not None and prev_cells
                ]
                if len(components) < 2:
                    continue
                visible_mean = sum(components) / len(components)
                delta = number.value - visible_mean
                if abs(delta) <= numeric_tolerance(number.decimals):
                    continue
                col_label = latest_header[col_idx] if latest_header and col_idx < len(latest_header) else f"column {col_idx + 1}"
                tier, gap_abs, gap_rel = classify_arithmetic_gap(number.value, visible_mean)
                signals.append(
                    f"Signal ({tier} gap {gap_abs:.2f}pp / {gap_rel:.2f}%): "
                    f"Table {table_idx}, row {row_idx} ({cells[0]!r}), column {col_idx + 1} ({col_label!r}): "
                    f"reported {number.text}; visible arithmetic mean of previous data rows = "
                    f"{format_number(visible_mean, number.decimals)}; delta {delta:+.{max(2, min(number.decimals, 4))}f}. "
                    + (
                        "Rendered finding must be Blocker. Gap exceeds the broad plausible aggregation range; render as a directive numeric finding unless the manuscript gives a specific denominator/weighting explanation."
                        if tier == "deterministic"
                        else "Rendered finding must be Blocker and state the concrete reported value, visible computed value, and delta; if weighted/micro aggregation could explain it, name that as the rebuttal instead of using vague 'needs checking' language."
                    )
                )

        if numeric_count >= 2 and (not cells or not SUMMARY_ROW_RE.fullmatch(row_label or "")):
            prior_numeric_rows.append((row_idx, cells, parsed))
    return signals


def source_text_from_line(line: str, first_number_start: int | None) -> str:
    if first_number_start is None:
        prefix = line.strip()
    else:
        prefix = line[:first_number_start].strip()
    prefix = re.sub(r"\s{2,}", " ", prefix)
    prefix = re.sub(r"^\d+\s+", "", prefix)
    return prefix or "(row label unavailable)"


def infer_pdf_table_id(lines: list[str], line_idx: int) -> str:
    for idx in range(line_idx, max(-1, line_idx - 30), -1):
        match = re.search(r"\bTable\s+\d+[A-Za-z]?\b", lines[idx], re.IGNORECASE)
        if match:
            return match.group(0)
    return "PDF table"


def pdf_line_numeric_audit(text: str, max_items: int) -> list[dict[str, object]]:
    """Return visible PDF-text numeric signals for row summaries.

    This is intentionally conservative: it only checks lines with many visible numbers
    and treats the final number as a summary of preceding row numbers. It emits signals,
    not final manuscript verdicts.
    """

    signals: list[dict[str, object]] = []
    lines = text.splitlines()
    current_group_markers: list[str] = []
    current_summary_indices: list[int] = []
    for line_idx, line in enumerate(lines):
        if re.search(r"\bTable\s+\d+[A-Za-z]?\b", line, re.IGNORECASE):
            current_group_markers = []
            current_summary_indices = []
        elif re.search(r"\b(?:Figure|Fig\.|Section|Appendix|References)\b", line, re.IGNORECASE):
            current_summary_indices = []
        group_markers = pdf_component_group_markers(line)
        if group_markers:
            current_group_markers = group_markers
            current_summary_indices = []
            continue
        summary_indices = pdf_summary_header_indices(line)
        if summary_indices:
            current_summary_indices = summary_indices
            continue
        numbers = parse_positioned_numbers(line)
        if len(numbers) < 4:
            continue
        if re.match(r"\s*\d+\s+", line) and len(numbers) < 5:
            # Likely numbered prose rather than a table row.
            continue
        prefix = source_text_from_line(line, numbers[0].start if numbers else None)
        if re.search(r"\b(line|section|figure|fig\.|page|eq\.|equation)\b", prefix, re.IGNORECASE):
            continue
        if not re.search(r"[A-Za-z\u4e00-\u9fff]", prefix):
            continue

        candidates: list[tuple[PositionedNumber, list[PositionedNumber], str, dict[str, list[float]] | None, int | None]] = []
        if current_group_markers and len(current_group_markers) == len(numbers) - 1 and len(set(current_group_markers)) > 1:
            reported = numbers[-1]
            components = numbers[:-1]
            group_components: dict[str, list[float]] = {}
            for marker, component in zip(current_group_markers, components):
                group_components.setdefault(marker, []).append(component.value)
            candidates.append((reported, components, "component_mean_of_means", group_components, None))
        elif current_summary_indices and max(current_summary_indices) < len(numbers):
            previous_summary_idx = -1
            for summary_idx in current_summary_indices:
                reported = numbers[summary_idx]
                components = numbers[previous_summary_idx + 1 : summary_idx]
                previous_summary_idx = summary_idx
                if len(components) >= 2:
                    candidates.append((reported, components, "header_summary_mean", None, summary_idx))

        table_id = infer_pdf_table_id(lines, line_idx)
        for reported, components, formula, group_components, summary_idx in candidates:
            # Skip obvious prose lines with a year/page-like final number.
            if reported.value > 500 and reported.decimals == 0:
                continue
            if len(components) < 2:
                continue
            if formula == "component_mean_of_means" and group_components:
                visible_mean = sum(sum(values) / len(values) for values in group_components.values()) / len(group_components)
            else:
                visible_mean = sum(number.value for number in components) / len(components)
            delta = reported.value - visible_mean
            if abs(delta) <= numeric_tolerance(reported.decimals):
                continue

            tier, gap_abs, gap_rel = classify_arithmetic_gap(reported.value, visible_mean)
            signal = {
                "signal_id": f"N{len(signals) + 1}",
                "source": "pdf-layout-text",
                "table_id": table_id,
                "line_number": line_idx + 1,
                "row_label": prefix,
                "reported_value": reported.text,
                "visible_computed_value": format_number(visible_mean, reported.decimals),
                "delta": f"{delta:+.{max(2, min(reported.decimals, 4))}f}",
                "gap_tier": tier,
                "gap_abs": round(gap_abs, 4),
                "gap_rel_percent": round(gap_rel, 4),
                "component_values": [number.text for number in components],
                "component_count": len(components),
                "formula": formula,
                "render_required": True,
                "required_severity": "Blocker",
                "summary_column_index": summary_idx,
                "component_groups": group_components or {},
                "aggregation_caveat": (
                    "PDF text row audit treats a visible summary value as a row summary over nearby printed cells. "
                    + (
                        "Visible group markers were used to compute a mean of component means; denominator/grouping should still be stated in the paper."
                        if formula == "component_mean_of_means"
                        else "If the paper uses grouped, weighted, micro, or hidden-decimal aggregation, the denominator/weights must be stated."
                    )
                ),
                "rendering_instruction": (
                    "Rendered finding must be Blocker and state table/row, reported value, visible recomputed value, and delta. "
                    "Do not collapse this into vague wording such as 'average differs' or 'needs checking'."
                ),
            }
            signals.append(signal)
            if len(signals) >= max_items:
                break
        if len(signals) >= max_items:
            break
    return signals


NUMERIC_NO_SIGNAL_CAVEAT = (
    "No deterministic row-summary recomputation signal was detected by this conservative parser. "
    "This is not a proof that tables are numerically correct; manually inspect averages, totals, rates, and formulas in claim-critical tables."
)


def format_pdf_numeric_signal(signal: dict[str, object]) -> str:
    tier = signal["gap_tier"]
    gap_abs = float(signal["gap_abs"])
    gap_rel = float(signal["gap_rel_percent"])
    row_label = str(signal["row_label"])
    component_count = int(signal["component_count"])
    report = str(signal["reported_value"])
    computed = str(signal["visible_computed_value"])
    delta = str(signal["delta"])
    table_id = str(signal["table_id"])
    formula = str(signal.get("formula", "direct_mean"))
    formula_labels = {
        "component_mean_of_means": "visible grouped component mean",
        "header_summary_mean": "visible header-scoped arithmetic mean",
    }
    formula_label = formula_labels.get(formula, "visible arithmetic mean")
    return (
        f"Signal ({tier} gap {gap_abs:.2f}pp / {gap_rel:.2f}%): "
        f"{table_id}, line {signal['line_number']}, row {row_label!r}: "
        f"reported {report}; {formula_label} of {component_count} preceding numeric cell(s) = {computed}; "
        f"delta {delta}. Rendered finding must be Blocker and state the concrete reported value, visible computed value, and delta; "
        "if grouped/weighted/micro aggregation could explain it, name that rebuttal and require the denominator/weights."
    )


def summarize_pdf_table_numeric_signals(text: str, max_items: int) -> tuple[list[str], list[dict[str, object]]]:
    lines = ["\n## PDF Table Numeric Recalculation Signals"]
    signals = pdf_line_numeric_audit(text, max_items)
    if signals:
        lines.extend(f"- {format_pdf_numeric_signal(signal)}" for signal in signals)
        lines.append(
            "- Reviewer instruction: these are PDF-text row signals. Cite the concrete reported/computed/delta values, "
            "then decide severity from the paper's metric definition and claim role."
        )
    else:
        lines.append(f"- {NUMERIC_NO_SIGNAL_CAVEAT}")
    return lines, signals


def detect_pdf_page_count(path: Path, state: ExtractionState) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        try:
            result = subprocess.run(
                [pdfinfo, str(path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            state.warnings.append(f"pdfinfo timed out after {SUBPROCESS_TIMEOUT_SECONDS}s; trying Python PDF fallbacks.")
            result = None
        if result is None:
            pass
        else:
            match = re.search(r"^Pages:\s*(\d+)\s*$", result.stdout, re.MULTILINE)
            if match:
                state.pdf_page_count = int(match.group(1))
                state.pdf_page_count_source = "pdfinfo"
                return state.pdf_page_count

    try:
        from pypdf import PdfReader  # type: ignore

        state.pdf_page_count = len(PdfReader(str(path)).pages)
        state.pdf_page_count_source = "pypdf"
        return state.pdf_page_count
    except Exception:
        pass

    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(path) as pdf:
            state.pdf_page_count = len(pdf.pages)
            state.pdf_page_count_source = "pdfplumber"
            return state.pdf_page_count
    except Exception:
        state.warnings.append("Could not determine PDF page count; coverage receipt must not claim full-page coverage.")
        return None


def strip_latex_comments(text: str) -> str:
    lines: list[str] = []
    verbatim_depth = 0
    verbatim_begin = re.compile(r"\\begin\{(verbatim|lstlisting|minted)\}")
    verbatim_end = re.compile(r"\\end\{(verbatim|lstlisting|minted)\}")
    for line in text.splitlines():
        if verbatim_begin.search(line):
            verbatim_depth += 1
            lines.append(line)
            continue
        if verbatim_depth:
            lines.append(line)
            if verbatim_end.search(line):
                verbatim_depth = max(0, verbatim_depth - 1)
            continue
        out = []
        escaped = False
        for ch in line:
            if ch == "%" and not escaped:
                break
            out.append(ch)
            escaped = ch == "\\" and not escaped
        lines.append("".join(out))
    return "\n".join(lines)


def candidate_path(base: Path, target: str) -> Path:
    target_path = Path(target)
    if target_path.is_absolute():
        return target_path
    return base / target_path


def with_latex_suffix_candidates(path: Path) -> list[Path]:
    candidates = [path]
    if path.suffix != ".tex":
        candidates.append(path.with_suffix(".tex"))
        candidates.append(Path(str(path) + ".tex"))
    return candidates


def resolve_tex_path(base: Path, target: str, state: ExtractionState, root: Path | None = None) -> Path:
    candidate = candidate_path(base, target)
    for option in with_latex_suffix_candidates(candidate):
        if root is not None and not is_within_root(option, root):
            continue
        if option.exists():
            return option
    return candidate


def project_root_for(source: Path) -> Path:
    resolved = source.resolve()
    if not resolved.is_file():
        return resolved

    parent = resolved.parent
    grandparent = parent.parent
    if grandparent == parent:
        return parent

    if parent.name.lower() in TEX_CONTAINER_DIRS:
        return grandparent
    if any((grandparent / marker).exists() for marker in PROJECT_MARKERS):
        return grandparent
    if any((grandparent / dirname).is_dir() for dirname in RESOURCE_DIRS):
        return grandparent
    if len(list(grandparent.glob("*.tex"))) > 0:
        return grandparent
    return parent


def is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def resolve_import_path(path: Path, match: re.Match[str], state: ExtractionState, root: Path | None = None) -> Path:
    if match.group(1):
        target = match.group(1)
        candidate = resolve_tex_path(path.parent, target, state, root)
        if candidate.exists() or root is None:
            return candidate
        fallback = resolve_tex_path(root, target, state, root)
        return fallback if fallback.exists() else candidate
    import_dir = match.group(2) or ""
    import_file = match.group(3) or ""
    candidate = resolve_tex_path(path.parent / import_dir, import_file, state, root)
    if candidate.exists() or root is None:
        return candidate
    fallback_target = str(Path(import_dir) / import_file) if import_dir else import_file
    fallback = resolve_tex_path(root, fallback_target, state, root)
    return fallback if fallback.exists() else candidate


def relative_depth(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return 99


def rank_main_candidate(path: Path, root: Path, text: str) -> tuple[int, int, str]:
    name = path.name.lower()
    root_distance = relative_depth(path, root)
    score = 0
    if name in {"main.tex", "paper.tex", "ms.tex", "manuscript.tex"}:
        score -= 100
    if root_distance == 1:
        score -= 20
    if "\\begin{document}" in text:
        score -= 10
    if "\\documentclass" in text:
        score -= 5
    if any(term in name for term in ("appendix", "supp", "supplement", "rebuttal", "response")):
        score += 30
    return score, root_distance, str(path)


def collect_tex_roots(root: Path, state: ExtractionState) -> list[Path]:
    if root.is_file():
        return [root]

    tex_files = sorted(root.rglob("*.tex"))
    if not tex_files:
        state.warnings.append(f"No .tex files found under {root}.")
        return []

    candidates: list[tuple[tuple[int, int, str], Path]] = []
    for path in tex_files:
        text = read_text(path, state)
        if "\\documentclass" in text or "\\begin{document}" in text:
            candidates.append((rank_main_candidate(path, root, text), path))

    if candidates:
        candidates.sort()
        main = candidates[0][1]
        if len(candidates) > 1:
            state.warnings.append(
                "Multiple standalone TeX files detected; using "
                f"{main}. Other candidates: "
                + ", ".join(str(path) for _, path in candidates[1:6])
            )
        return [main]

    state.warnings.append("No standalone main TeX file detected; extracting all .tex files.")
    return tex_files


def expand_inputs(path: Path, state: ExtractionState, seen: set[Path] | None = None, root: Path | None = None) -> str:
    seen = seen or set()
    path = path.resolve()
    if root is None:
        if not seen:
            root = project_root_for(path).resolve()
            state.warnings.append(f"expand_inputs called without project root; using {root} as traversal boundary.")
        else:
            root = path.parent.resolve()
    if not is_within_root(path, root):
        state.warnings.append(f"Refused to read input outside project tree: {path}")
        return ""
    if path in seen:
        state.warnings.append(f"Skipped recursive input: {path}")
        return ""
    if not path.exists():
        state.warnings.append(f"Missing input file: {path}")
        return ""
    seen.add(path)
    state.source_files.append(path)
    text = read_text(path, state)
    active_text = strip_latex_comments(text)

    def repl(match: re.Match[str]) -> str:
        child = resolve_import_path(path, match, state, root)
        return "\n" + expand_inputs(child, state, seen, root) + "\n"

    return INPUT_RE.sub(repl, active_text)


def run_pandoc_latex(raw: str, state: ExtractionState) -> str | None:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        state.warnings.append("pandoc not found; using regex fallback for LaTeX-to-text conversion.")
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="ariadne-pandoc-") as cwd:
            result = subprocess.run(
                [pandoc, "--sandbox", "-f", "latex", "-t", "plain", "--wrap=none"],
                input=raw,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
                cwd=cwd,
            )
    except subprocess.TimeoutExpired:
        state.warnings.append(f"pandoc timed out after {SUBPROCESS_TIMEOUT_SECONDS}s; using regex fallback.")
        return None
    if result.stderr.strip():
        warning = " | ".join(line.strip() for line in result.stderr.strip().splitlines()[:3])
        state.warnings.append("pandoc warning: " + warning[:600])
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    state.warnings.append("pandoc LaTeX conversion failed; using regex fallback.")
    return None


def latex_to_plain(raw: str, state: ExtractionState) -> str:
    pandoc_text = run_pandoc_latex(raw, state)
    if pandoc_text:
        return pandoc_text

    text = strip_latex_comments(raw)
    text = TITLE_CMD_RE.sub(lambda m: "\n\n# TITLE: " + one_line(m.group(1)) + "\n", text)
    text = re.sub(r"\\begin\{abstract\}", "\n\n## ABSTRACT\n", text)
    text = re.sub(r"\\end\{abstract\}", "\n", text)
    text = re.sub(r"\\begin\{(figure|table|algorithm|equation|align|gather|multline)[*]?\}", r"\n[\1]\n", text)
    text = re.sub(r"\\end\{(figure|table|algorithm|equation|align|gather|multline)[*]?\}", "\n", text)
    text = SECTION_CMD_RE.sub(lambda m: f"\n\n## {m.group(1).upper()}: {one_line(m.group(2))}\n", text)
    text = CAPTION_CMD_RE.sub(lambda m: "\nCAPTION: " + one_line(m.group(1)) + "\n", text)
    text = re.sub(r"\\item(?:\[[^\]]*\])?", "\n- ", text)
    text = re.sub(r"\\(?:textbf|emph|textit|underline|small|footnotesize|scriptsize)\{((?:[^{}]|\{[^{}]*\})*)\}", lambda m: one_line(m.group(1)), text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf(path: Path, state: ExtractionState) -> str:
    detect_pdf_page_count(path, state)
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            result = subprocess.run(
                [pdftotext, "-layout", str(path), "-"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            state.warnings.append(f"pdftotext timed out after {SUBPROCESS_TIMEOUT_SECONDS}s; trying pdfplumber.")
            result = None
        if result is None:
            pass
        else:
            if result.stderr.strip():
                state.warnings.append("pdftotext warning: " + result.stderr.strip().splitlines()[0][:300])
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
            state.warnings.append(f"pdftotext failed with exit code {result.returncode}; trying pdfplumber.")

    try:
        import pdfplumber  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise RuntimeError("Could not extract PDF text: install pdftotext or pdfplumber") from exc

    pages = []
    with pdfplumber.open(path) as pdf:
        for idx, page in enumerate(pdf.pages, 1):
            pages.append(f"\n\n[PAGE {idx}]\n{page.extract_text() or ''}")
    return "\n".join(pages)


def summarize_pdf_metadata(source: Path, state: ExtractionState) -> list[str]:
    lines = ["\n## PDF Coverage Metadata"]
    lines.append(f"- PDF file: {source}")
    if state.pdf_page_count is not None:
        lines.append(f"- Page count: {state.pdf_page_count} (source: {state.pdf_page_count_source})")
        lines.append(
            "- Coverage instruction: HTML/report coverage receipts must use this page count; "
            "do not claim fewer/more pages unless the review scope is explicitly limited."
        )
    else:
        lines.append("- Page count: unknown. Do not claim full PDF page coverage without visual/rendered verification.")
    return lines


def find_bib_files(source: Path, raw: str, state: ExtractionState) -> list[Path]:
    root = project_root_for(source)
    base = source.resolve().parent if source.is_file() else root
    candidates: list[Path] = []
    active_raw = strip_latex_comments(raw)
    for match in BIB_CMD_RE.finditer(active_raw):
        for item in match.group(1).split(","):
            name = item.strip()
            if not name:
                continue
            path = candidate_path(base, name)
            path_candidates = [path]
            if path.suffix != ".bib":
                path_candidates.extend([path.with_suffix(".bib"), Path(str(path) + ".bib")])
            path = next(
                (candidate for candidate in path_candidates if is_within_root(candidate, root) and candidate.exists()),
                path_candidates[0],
            )
            if not is_within_root(path, root):
                state.warnings.append(f"Refused to read bibliography outside project tree: {path.resolve()}")
                continue
            if path.exists():
                candidates.append(path)
            else:
                state.warnings.append(f"Missing bibliography file referenced in TeX: {path}")
    candidates = unique_paths(candidates)
    if not candidates and not BIB_CMD_RE.search(active_raw) and root.exists() and root.is_dir():
        candidates = sorted(root.rglob("*.bib"))[:20]
        candidates = unique_paths(candidates)
    state.bib_files.extend(candidates)
    return candidates


def parse_bib_entries(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for match in BIB_ENTRY_RE.finditer(text):
        entry_type = match.group(1).lower()
        key = match.group(2).strip()
        body = match.group(3)
        fields = {
            field_match.group(1).lower(): one_line(field_match.group(2) or field_match.group(3) or "")
            for field_match in BIB_FIELD_RE.finditer(body)
        }
        entries.append({"type": entry_type, "key": key, "fields": fields})
    return entries


def summarize_bib_style(bib_files: list[Path], state: ExtractionState, max_items: int) -> list[str]:
    lines = ["\n## Reference Style Signals"]
    if not bib_files:
        lines.append("- No .bib files to inspect.")
        return lines

    entries: list[dict[str, object]] = []
    for bib in bib_files[:max_items]:
        entries.extend(parse_bib_entries(read_text(bib, state)))

    if not entries:
        lines.append("- No parseable BibTeX/BibLaTeX entries detected.")
        return lines

    lines.append(f"- Parsed bibliography entries: {len(entries)}")
    lines.append("\n### Reference Entry Coverage")
    for entry in entries[:max_items]:
        fields = entry["fields"]  # type: ignore[assignment]
        venue = fields.get("booktitle") or fields.get("journal") or fields.get("publisher") or ""
        pages = fields.get("pages", "")
        url = "yes" if fields.get("url") else "no"  # type: ignore[union-attr]
        doi = "yes" if fields.get("doi") else "no"  # type: ignore[union-attr]
        eprint = "yes" if fields.get("eprint") else "no"  # type: ignore[union-attr]
        lines.append(
            "- "
            f"{entry['key']} ({entry['type']}): "
            f"venue={str(venue)[:80]!r}, url={url}, doi={doi}, eprint={eprint}, pages={str(pages)!r}"
        )
    if len(entries) > max_items:
        lines.append(
            f"- Entry coverage incomplete because --max-items={max_items} is smaller than parsed entries; "
            "rerun with a larger --max-items before claiming full reference coverage."
        )

    lines.append("\n### Reference Style Drift Summary")
    drift_signals_emitted = 0
    for field_name in ("url", "doi", "eprint"):
        with_field = [entry for entry in entries if field_name in entry["fields"]]  # type: ignore[operator]
        if 0 < len(with_field) < len(entries):
            lines.append(
                f"- `{field_name}` field present in {len(with_field)}/{len(entries)} entries; possible reference-style drift."
            )
            drift_signals_emitted += 1

    entry_types: dict[str, int] = {}
    booktitles: list[str] = []
    page_formats: dict[str, list[str]] = {}
    for entry in entries:
        entry_type = str(entry["type"])
        fields = entry["fields"]  # type: ignore[assignment]
        entry_types[entry_type] = entry_types.get(entry_type, 0) + 1
        if entry_type == "inproceedings":
            booktitle = fields.get("booktitle", "")  # type: ignore[union-attr]
            if booktitle:
                booktitles.append(str(booktitle))
        pages = str(fields.get("pages", ""))  # type: ignore[union-attr]
        if pages:
            if "--" in pages:
                page_formats.setdefault("double-dash", []).append(str(entry["key"]))
            elif "-" in pages:
                page_formats.setdefault("single-dash", []).append(str(entry["key"]))

    if len(entry_types) > 1:
        summary = ", ".join(f"{kind}={count}" for kind, count in sorted(entry_types.items())[:max_items])
        lines.append(f"- Entry type mix: {summary}. Check that entry types match publication venues.")
        drift_signals_emitted += 1

    short_titles = [title for title in booktitles if 0 < len(title) <= 14]
    long_titles = [title for title in booktitles if len(title) >= 35]
    if short_titles and long_titles:
        lines.append(
            "- `booktitle` style mix: "
            f"{len(short_titles)} short form(s), e.g. {short_titles[0]!r}; "
            f"{len(long_titles)} long form(s), e.g. {long_titles[0][:80]!r}."
        )
        drift_signals_emitted += 1

    if len(page_formats) > 1:
        summary = ", ".join(f"{kind}={len(keys)}" for kind, keys in sorted(page_formats.items()))
        lines.append(f"- Pages separator drift: {summary}. Prefer one page-range convention.")
        drift_signals_emitted += 1

    if drift_signals_emitted == 0:
        lines.append("- No obvious URL/DOI/eprint, booktitle, entry-type, or page-format drift detected.")
    return lines


def section_word_stats(plain_text: str, headings: list[str] | None = None, max_items: int = MAX_DEFAULT_ITEMS) -> list[tuple[str, int, int]]:
    if headings:
        escaped = [re.escape(title) for title in headings if title]
        if escaped:
            heading_alt = "|".join(escaped)
            matches = list(
                re.finditer(
                    r"^\s*(?:#{1,3}\s+(?:[A-Za-z]+\s*:\s*)?)?("
                    + heading_alt
                    + r")\s*$",
                    plain_text,
                    re.MULTILINE,
                )
            )
        else:
            matches = []
    else:
        matches = [match for match in GENERAL_HEADING_RE.finditer(plain_text) if not is_pdf_noise_heading(match.group(0))]
    if not matches:
        words = len(re.findall(r"\b\w+\b", plain_text))
        cites = len(PDF_CITE_RE.findall(plain_text))
        return [("Whole extracted text", words, cites)]
    stats = []
    for idx, match in enumerate(matches[:max_items]):
        title = next((group for group in match.groups() if group), "").strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(plain_text)
        chunk = plain_text[start:end]
        words = len(re.findall(r"\b\w+\b", chunk))
        cites = len(PDF_CITE_RE.findall(chunk))
        if words > 0:
            stats.append((title, words, cites))
    return stats


def summarize_common(text: str, raw: str, state: ExtractionState, max_items: int) -> list[str]:
    lines: list[str] = []

    placeholders = signal_line_items(PLACEHOLDER_RE, raw)
    todos = [(raw.count("\n", 0, m.start()) + 1, one_line(m.group(0))) for m in TODO_RE.finditer(raw)]
    emails = sorted(set(EMAIL_RE.findall(raw + "\n" + text)))
    githubs = sorted(set(GITHUB_RE.findall(raw + "\n" + text)))
    abs_paths = sorted(set(ABS_PATH_RE.findall(raw + "\n" + text)))
    authors = command_payloads(AUTHOR_RE, raw, max_items)
    affiliations = command_payloads(AFFILIATION_RE, raw, max_items)
    thanks = [one_line(m.group(1)) for m in THANKS_RE.finditer(raw)]
    orcids = sorted(set(ORCID_RE.findall(raw + "\n" + text)))
    anon_switches = sorted(set(match.group(1) for match in ANON_SWITCH_RE.finditer(raw + "\n" + text)))
    camera_ready_mentions = sorted(set(match.group(0) for match in CAMERA_READY_TEXT_RE.finditer(raw + "\n" + text)))
    has_ack = bool(ACK_RE.search(raw) or re.search(r"\bAcknowledg(?:e)?ments?\b", text, re.IGNORECASE))

    lines.append("\n## Placeholders and Broken Refs")
    if placeholders:
        for line, item in placeholders[:max_items]:
            lines.append(f"- Line {line}: {item}")
    else:
        lines.append("- No placeholder or broken-reference signals detected.")

    lines.append("\n## TODO/TBD Signals")
    if todos:
        for line, todo in todos[:max_items]:
            lines.append(f"- Source line {line}: {todo}")
    else:
        lines.append("- No TODO/TBD/FIXME markers detected.")

    lines.append("\n## Anonymity and Identity Signals")
    identity_items = []
    identity_items.extend(f"email: {item}" for item in emails[:max_items])
    identity_items.extend(f"github: {item}" for item in githubs[:max_items])
    identity_items.extend(f"path: {item}" for item in abs_paths[:max_items])
    identity_items.extend(f"author command: {item[:300]}" for item in authors[:max_items])
    identity_items.extend(f"affiliation/institute command: {item[:300]}" for item in affiliations[:max_items])
    identity_items.extend(f"thanks: {item[:300]}" for item in thanks[:max_items])
    identity_items.extend(f"ORCID: {item}" for item in orcids[:max_items])
    identity_items.extend(f"anonymous/final switch: {item}" for item in anon_switches[:max_items])
    identity_items.extend(f"informational camera-ready text: {item}" for item in camera_ready_mentions[:max_items])
    if has_ack:
        identity_items.append("acknowledgments section/header detected")
    if identity_items:
        for item in identity_items[:max_items]:
            lines.append(f"- {item}")
    else:
        lines.append("- No obvious identity/anonymity signals detected.")

    return lines


def summarize_equations(raw: str, max_items: int) -> list[str]:
    lines = ["\n## Equations Detected"]
    equations: list[str] = []
    for match in EQUATION_ENV_RE.finditer(raw):
        env = match.group(1)
        body = one_line(match.group(2))
        equations.append(f"{env}: {body[:500]}")
    for match in DISPLAY_MATH_RE.finditer(raw):
        body = one_line(match.group(1) or match.group(2) or "")
        if body:
            equations.append(f"display math: {body[:500]}")
    if equations:
        for item in equations[:max_items]:
            lines.append(f"- {item}")
    else:
        lines.append("- No display equation environments detected.")
    return lines


def collect_display_math(raw: str) -> list[tuple[str, str]]:
    equations: list[tuple[str, str]] = []
    for idx, match in enumerate(EQUATION_ENV_RE.finditer(raw), 1):
        env = match.group(1)
        equations.append((f"{env} {idx}", match.group(2)))
    for idx, match in enumerate(DISPLAY_MATH_RE.finditer(raw), 1):
        body = match.group(1) or match.group(2) or ""
        if body.strip():
            equations.append((f"display math {idx}", body))
    return equations


def macro_definitions(raw: str) -> dict[str, list[str]]:
    definitions: dict[str, list[str]] = {}
    for pattern in (NEWCOMMAND_RE, DEF_RE, DECLARE_MATH_OPERATOR_RE):
        for match in pattern.finditer(raw):
            name = match.group(1)
            expansion = signal_snippet(match.group(2))
            definitions.setdefault(name, []).append(expansion)
    return definitions


def summarize_symbol_consistency(raw: str, max_items: int) -> list[str]:
    lines = ["\n## Symbol and Macro Consistency Signals"]
    signals: list[str] = []

    definitions = macro_definitions(raw)
    for name, expansions in sorted(definitions.items()):
        unique_expansions = []
        for expansion in expansions:
            if expansion not in unique_expansions:
                unique_expansions.append(expansion)
        if len(unique_expansions) > 1:
            preview = "; ".join(repr(item[:80]) for item in unique_expansions[:3])
            signals.append(
                f"Macro \\{name} has {len(unique_expansions)} distinct expansions: {preview}. "
                "Signal only: inspect whether the notation intentionally changes or drifted across the source."
            )

    equations = collect_display_math(raw)
    command_locations: dict[str, list[str]] = {}
    custom_names = set(definitions)
    allowed = COMMON_LATEX_COMMANDS | GREEK_COMMANDS | custom_names
    for label, body in equations:
        for match in MATH_COMMAND_RE.finditer(strip_latex_comments(body)):
            command = match.group(1)
            command_locations.setdefault(command, []).append(label)

    for command, locations in sorted(command_locations.items()):
        if command in allowed:
            continue
        unique_locations = []
        for location in locations:
            if location not in unique_locations:
                unique_locations.append(location)
        signals.append(
            f"Command-like math token \\{command} appears in {', '.join(unique_locations[:5])} but is not defined by "
            "\\newcommand/\\def/\\DeclareMathOperator in the visible source and is not on the common LaTeX allowlist. "
            "Signal only: inspect whether it is package-provided, undefined, or a notation typo."
        )

    for base, variant in VARIANT_SYMBOL_PAIRS:
        if base in command_locations and variant in command_locations:
            base_locs = ", ".join(dict.fromkeys(command_locations[base]).keys())
            variant_locs = ", ".join(dict.fromkeys(command_locations[variant]).keys())
            signals.append(
                f"Variant symbol pair \\{base} and \\{variant} both appear in display equations "
                f"(\\{base}: {base_locs}; \\{variant}: {variant_locs}). "
                "Signal only: inspect whether the paper intentionally distinguishes them or uses two glyphs for one quantity."
            )

    if signals:
        lines.extend(f"- {item}" for item in signals[:max_items])
        if len(signals) > max_items:
            lines.append(
                f"- Symbol signal coverage incomplete because --max-items={max_items} is smaller than detected signals; "
                "rerun with a larger --max-items before claiming full symbol/macro coverage."
            )
    else:
        lines.append("- No macro redefinition, unknown command-like math token, or common variant-symbol drift signals detected.")
    lines.append(
        "- Reviewer instruction: use these as notation signals, not equation-correctness verdicts. "
        "For method-critical equations, still build the notation/shape registry by reading the prose and algorithms."
    )
    return lines


def summarize_table_sanity(raw: str, max_items: int) -> list[str]:
    lines = ["\n## Table Completeness and Blank-Cell Signals"]
    table_signals: list[str] = []
    numeric_signals: list[str] = []
    for table_idx, match in enumerate(TABULAR_ENV_RE.finditer(raw), 1):
        rows = visible_table_rows(match.group(2))
        numeric_signals.extend(table_numeric_signals(table_idx, rows))
        expected_cols = 0
        for row_idx, cells in rows:
            if len(cells) > expected_cols:
                expected_cols = len(cells)
            blank_positions = table_blank_positions(cells)
            if blank_positions:
                table_signals.append(
                    f"Table {table_idx}, row {row_idx}: blank/placeholder cell(s) at column(s) "
                    f"{', '.join(str(pos) for pos in blank_positions)}; row={cells}"
                )
            if expected_cols and len(cells) < expected_cols:
                table_signals.append(
                    f"Table {table_idx}, row {row_idx}: fewer cells than earlier rows "
                    f"({len(cells)} vs {expected_cols}); row={cells}"
                )
    if table_signals:
        lines.extend(f"- {item}" for item in table_signals[:max_items])
        if len(table_signals) > max_items:
            lines.append(
                f"- Table signal coverage incomplete because --max-items={max_items} is smaller than detected signals; "
                "rerun with a larger --max-items before claiming full table completeness coverage."
            )
    else:
        lines.append("- No blank/placeholder table cells detected in LaTeX tabular-like environments.")
    lines.append(
        "- Reviewer instruction: treat blank cells in main evidence tables as possible Blocker/Major issues; "
        "do not claim a baseline is covered on all settings when its row/column has missing cells."
    )
    lines.append("\n## Table Numeric Recalculation Signals")
    if numeric_signals:
        lines.extend(f"- {item}" for item in numeric_signals[:max_items])
        if len(numeric_signals) > max_items:
            lines.append(
                f"- Numeric signal coverage incomplete because --max-items={max_items} is smaller than detected signals; "
                "rerun with a larger --max-items before claiming full numerical coverage."
            )
    else:
        lines.append(f"- {NUMERIC_NO_SIGNAL_CAVEAT}")
    lines.append(
        "- Reviewer instruction: cite concrete reported/computed/delta values from these signals when writing table findings; "
        "do not collapse them into vague wording such as 'the average seems off'. Treat script output as evidence signals, not final judgment."
    )
    return lines


def summarize_latex(raw: str, plain_text: str, source: Path, state: ExtractionState, max_items: int) -> list[str]:
    lines = ["# Review Signals", ""]
    active_raw = strip_latex_comments(raw)

    bib_files = find_bib_files(source, active_raw, state)
    bib_entries: list[tuple[Path, int]] = []
    for bib in bib_files[:max_items]:
        text = read_text(bib, state)
        entries = len(BIB_PUBLICATION_ENTRY_RE.findall(text))
        bib_entries.append((bib, entries))

    if state.warnings:
        lines.append("## Extraction Warnings")
        for warning in state.warnings[:max_items]:
            lines.append(f"- {warning}")
    else:
        lines.append("## Extraction Warnings\n- None.")

    docs = [m.group(1) for m in DOCUMENTCLASS_RE.finditer(active_raw)]
    lines.append("\n## Template/Class Signals")
    if docs:
        for doc in docs[:max_items]:
            lines.append(f"- documentclass: {doc}")
    else:
        lines.append("- No documentclass detected.")

    titles = nonempty_command_payloads(TITLE_CMD_RE, active_raw)
    abstracts = nonempty_command_payloads(ABSTRACT_ENV_RE, active_raw)
    abstract_words = len(re.findall(r"\b\w+\b", abstracts[0])) if abstracts else 0
    lines.append("\n## Title and Abstract")
    lines.append(f"- Title: {titles[0] if titles else 'Not detected'}")
    lines.append(f"- Abstract words: {abstract_words}")

    sections = [(m.group(1), one_line(m.group(2))) for m in SECTION_CMD_RE.finditer(active_raw)]
    lines.append("\n## Sections")
    if sections:
        for level, title in sections[:max_items]:
            lines.append(f"- {level}: {title}")
    else:
        lines.append("- No LaTeX section commands detected.")

    captions = [one_line(m.group(1)) for m in CAPTION_CMD_RE.finditer(active_raw)]
    lines.append("\n## Captions")
    if captions:
        for idx, caption in enumerate(captions[:max_items], 1):
            normalized_caption = caption.lower().strip(" .:")
            if not caption:
                label = "empty caption"
            elif normalized_caption in PLACEHOLDER_CAPTIONS:
                label = f"{caption[:500]} [placeholder caption]"
            else:
                label = caption[:500]
            lines.append(f"- Caption {idx}: {label}")
    else:
        lines.append("- No captions detected.")

    lines.extend(summarize_table_sanity(active_raw, max_items))
    lines.extend(summarize_equations(active_raw, max_items))
    lines.extend(summarize_symbol_consistency(active_raw, max_items))

    refs = [item.strip() for match in REF_CMD_RE.finditer(active_raw) for item in match.group(1).split(",") if item.strip()]
    cites = [item.strip() for match in CITE_CMD_RE.finditer(active_raw) for item in match.group(1).split(",") if item.strip()]
    lines.append("\n## Reference and Citation Signals")
    lines.append(f"- Reference command/items detected: {len(refs)}")
    lines.append(f"- Citation command/items detected: {len(cites)}")
    if cites:
        unique_cites = len(set(cites))
        lines.append(f"- Unique citation keys detected: {unique_cites}")

    lines.append("\n## Bibliography Files")
    if bib_entries:
        for bib, entries in bib_entries:
            lines.append(f"- {bib}: {entries} entries")
    else:
        lines.append("- No .bib files detected.")

    lines.extend(summarize_bib_style(bib_files, state, max_items))

    section_titles = [title for _, title in sections]
    stats = section_word_stats(plain_text, section_titles, max_items)
    lines.append("\n## Section Word/Citation Rough Stats")
    for title, words, cite_count in stats[:max_items]:
        density = cite_count / max(words, 1) * 1000
        lines.append(f"- {title}: {words} words, {cite_count} citation-like markers, {density:.1f}/1k words")

    lines.extend(summarize_common(plain_text, active_raw, state, max_items))
    return lines


def summarize_pdf_with_numeric(
    text: str,
    source: Path,
    state: ExtractionState,
    max_items: int,
) -> tuple[list[str], list[dict[str, object]]]:
    lines = ["# Review Signals", ""]
    numeric_json_signals: list[dict[str, object]] = []

    lines.extend(summarize_pdf_metadata(source, state))

    if state.warnings:
        lines.append("## Extraction Warnings")
        for warning in state.warnings[:max_items]:
            lines.append(f"- {warning}")
    else:
        lines.append("## Extraction Warnings\n- None.")

    sections = [m.group(0).strip() for m in PDF_SECTION_RE.finditer(text) if not is_pdf_noise_heading(m.group(0))]
    captions = [one_line(m.group(0)) for m in PDF_CAPTION_RE.finditer(text)]
    citations = PDF_CITE_RE.findall(text)

    lines.append("\n## PDF Section-Like Headings")
    if sections:
        for item in sections[:max_items]:
            lines.append(f"- {item}")
    else:
        lines.append("- No common section headings detected in extracted PDF text.")

    lines.append("\n## PDF Figure/Table Caption-Like Lines")
    if captions:
        for idx, caption in enumerate(captions[:max_items], 1):
            lines.append(f"- Caption-like {idx}: {caption[:500]}")
    else:
        lines.append("- No Figure/Table caption-like lines detected.")

    lines.append("\n## PDF Citation-Like Marker Count")
    lines.append(f"- Citation-like markers detected: {len(citations)}")

    numeric_lines, pdf_numeric_signals = summarize_pdf_table_numeric_signals(text, max_items)
    lines.extend(numeric_lines)
    numeric_json_signals.extend(pdf_numeric_signals)

    stats = section_word_stats(text, max_items=max_items)
    lines.append("\n## Section Word/Citation Rough Stats")
    for title, words, cite_count in stats[:max_items]:
        density = cite_count / max(words, 1) * 1000
        lines.append(f"- {title}: {words} words, {cite_count} citation-like markers, {density:.1f}/1k words")

    lines.extend(summarize_common(text, text, state, max_items))
    return lines, numeric_json_signals


def summarize_pdf(
    text: str,
    source: Path,
    state: ExtractionState,
    max_items: int,
) -> list[str]:
    """Return human-readable PDF extraction signals.

    Keep this list-returning API stable for tests and import-as-library users.
    Call summarize_pdf_with_numeric when the caller also needs structured
    numeric audit JSON signals.
    """

    lines, _ = summarize_pdf_with_numeric(text, source, state, max_items)
    return lines


def default_output_path(source: Path) -> Path:
    stem = source.stem if source.suffix.lower() in {".pdf", ".tex"} else source.name
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("_") or "paper"
    source_hash = hashlib.sha1(str(source.resolve()).encode("utf-8")).hexdigest()[:6]
    random_suffix = secrets.token_hex(4)
    return Path(tempfile.gettempdir()) / f"paper_review_extract_{safe}_{source_hash}_{random_suffix}.md"


def write_private_text(path: Path, text: str, *, force: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if force:
        flags |= os.O_TRUNC
    else:
        flags |= os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="PDF file, .tex file, or LaTeX project directory")
    parser.add_argument("-o", "--output", type=Path, help="Write extraction markdown to this file; use '-' for stdout")
    parser.add_argument("--numeric-json", type=Path, help="Write structured numerical audit signals to this JSON file")
    parser.add_argument("--force", action="store_true", help="Allow --output or --numeric-json to overwrite an existing file")
    parser.add_argument("--max-items", type=positive_int, default=MAX_DEFAULT_ITEMS, help="Maximum items per signal category")
    args = parser.parse_args()

    source = args.input.expanduser()
    if not source.exists():
        parser.error(f"Input does not exist: {source}")

    state = ExtractionState()
    output_path = str(args.output) if args.output is not None else str(default_output_path(source))
    numeric_json_signals: list[dict[str, object]] = []

    if source.suffix.lower() == ".pdf":
        text = extract_pdf(source, state)
        signals, numeric_json_signals = summarize_pdf_with_numeric(text, source, state, args.max_items)
        output = "\n".join(signals) + "\n\n# Extracted PDF Text\n\n" + text.strip() + "\n"
    else:
        tex_roots = collect_tex_roots(source, state)
        chunks = []
        combined_raw = []
        for path in tex_roots:
            raw = expand_inputs(path, state, root=project_root_for(source))
            combined_raw.append(raw)
            plain = latex_to_plain(raw, state)
            chunks.append(f"# Source: {path}\n\n" + plain)
        raw_all = "\n\n".join(combined_raw)
        plain_all = "\n\n".join(chunk.split("\n\n", 1)[-1] for chunk in chunks)
        signals = summarize_latex(raw_all, plain_all, source, state, args.max_items)
        output = "\n".join(signals) + "\n\n# Extracted LaTeX Text\n\n" + "\n\n".join(chunks).strip() + "\n"

    if args.numeric_json:
        payload = {
            "input": str(source),
            "signal_count": len(numeric_json_signals),
            "signals": numeric_json_signals,
            "note": "Signals only. Rendered reports must cite reported_value, visible_computed_value, and delta. Table-number discrepancies are required-severity Blocker unless a signal is explicitly marked render_required=false with a parser-false-positive reason.",
        }
        write_private_text(args.numeric_json, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", force=args.force)

    if output_path == "-":
        sys.stdout.write(output)
    else:
        path = Path(output_path)
        write_private_text(path, output, force=args.force)
        print(f"Wrote signals to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
