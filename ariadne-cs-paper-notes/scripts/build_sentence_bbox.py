#!/usr/bin/env python3
"""Map Ariadne review-unit anchors to PDF text bounding boxes."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")
MATH_COMMAND_TOKEN_MAP = {
    "alpha": "alpha",
    "beta": "beta",
    "gamma": "gamma",
    "delta": "delta",
    "epsilon": "epsilon",
    "varepsilon": "epsilon",
    "zeta": "zeta",
    "eta": "eta",
    "theta": "theta",
    "vartheta": "theta",
    "iota": "iota",
    "kappa": "kappa",
    "lambda": "lambda",
    "mu": "mu",
    "nu": "nu",
    "xi": "xi",
    "pi": "pi",
    "rho": "rho",
    "sigma": "sigma",
    "tau": "tau",
    "upsilon": "upsilon",
    "phi": "phi",
    "varphi": "phi",
    "chi": "chi",
    "psi": "psi",
    "omega": "omega",
    "sim": "sim",
    "approx": "approx",
    "leq": "leq",
    "le": "leq",
    "geq": "geq",
    "ge": "geq",
    "times": "times",
    "cdot": "cdot",
    "pm": "pm",
    "infty": "infty",
}
MATH_GLYPH_TOKEN_MAP = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "θ": "theta",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "π": "pi",
    "ρ": "rho",
    "σ": "sigma",
    "τ": "tau",
    "φ": "phi",
    "χ": "chi",
    "ψ": "psi",
    "ω": "omega",
    "∼": "sim",
    "≈": "approx",
    "≤": "leq",
    "≥": "geq",
    "×": "times",
    "·": "cdot",
    "±": "pm",
    "∞": "infty",
}


@dataclass(frozen=True)
class WordBox:
    page: int
    text: str
    norm: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class SearchScope:
    words: list[WordBox]
    token_values: list[str]
    positions_by_token: dict[str, list[int]]

    @classmethod
    def build(cls, words: list[WordBox]) -> "SearchScope":
        positions: dict[str, list[int]] = {}
        token_values = [word.norm for word in words]
        for index, token in enumerate(token_values):
            positions.setdefault(token, []).append(index)
        return cls(words=words, token_values=token_values, positions_by_token=positions)


class WordSearchIndex:
    def __init__(self, words: list[WordBox]) -> None:
        self.all_scope = SearchScope.build(words)
        by_page: dict[int, list[WordBox]] = {}
        for word in words:
            by_page.setdefault(word.page, []).append(word)
        self.page_scopes = {page: SearchScope.build(page_words) for page, page_words in by_page.items()}

    def scope(self, page: int | None = None) -> SearchScope:
        if page is None:
            return self.all_scope
        scope = self.page_scopes.get(page)
        return scope if scope is not None else SearchScope.build([])

    def pages_scope(self, pages: list[int]) -> SearchScope:
        words: list[WordBox] = []
        seen: set[int] = set()
        for page in pages:
            if page in seen:
                continue
            seen.add(page)
            words.extend(self.scope(page).words)
        return SearchScope.build(words)

    def y_band_scope(self, page: int, y: float, *, tolerance: float = 80.0) -> SearchScope:
        page_scope = self.scope(page)
        if not page_scope.words:
            return page_scope
        band_words = [word for word in page_scope.words if abs(word.y0 - y) <= tolerance or abs(word.y1 - y) <= tolerance]
        return SearchScope.build(band_words)

    def region_scope(
        self,
        page: int,
        *,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        padding: float = 24.0,
    ) -> SearchScope:
        page_scope = self.scope(page)
        if not page_scope.words:
            return page_scope
        left = min(x0, x1) - padding
        right = max(x0, x1) + padding
        top = min(y0, y1) - padding
        bottom = max(y0, y1) + padding
        region_words = [
            word
            for word in page_scope.words
            if word.x1 >= left and word.x0 <= right and word.y1 >= top and word.y0 <= bottom
        ]
        return SearchScope.build(region_words)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def normalize_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = text.replace("−", "-")
    for glyph, token in MATH_GLYPH_TOKEN_MAP.items():
        text = text.replace(glyph, f" {token} ")
    for command, token in MATH_COMMAND_TOKEN_MAP.items():
        text = re.sub(rf"\\{command}\b", f" {token} ", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?", "", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def tokens(value: Any) -> list[str]:
    return TOKEN_RE.findall(normalize_text(value))


def compact_text(value: Any, *, max_chars: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def review_unit_texts(review_units: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(review_units):
        if row.get("kind") == "section":
            section_id = str(row.get("section_id") or "")
            if section_id:
                section_unit = {
                    "unit_kind": "section_heading",
                    "text": row.get("text") or "",
                    "rendered_text_initial": row.get("text") or "",
                    "source_file": row.get("source_file") or "",
                    "line_start": row.get("line_start") or 0,
                    "line_end": row.get("line_end") or row.get("line_start") or 0,
                }
                index[section_id] = section_unit
                aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
                for alias in aliases:
                    alias_text = str(alias or "")
                    if alias_text and alias_text not in index:
                        index[alias_text] = section_unit
            continue
        if row.get("kind") != "paragraph":
            continue
        paragraph_id = str(row.get("paragraph_id") or "")
        sentences = [item for item in row.get("sentences", []) if isinstance(item, dict)]
        paragraph_text = " ".join(str(item.get("rendered_text_initial") or item.get("text") or "") for item in sentences)
        if paragraph_id:
            paragraph_unit = {
                "unit_kind": str(row.get("unit_kind") or "prose"),
                "text": " ".join(str(item.get("text") or "") for item in sentences),
                "rendered_text_initial": paragraph_text,
                "source_file": row.get("source_file") or (sentences[0].get("source_file") if sentences else ""),
                "line_start": row.get("line_start") or (sentences[0].get("line_start") if sentences else 0),
                "line_end": row.get("line_end") or (sentences[-1].get("line_end") if sentences else 0),
                "sentence_ids": [str(item.get("sentence_id") or "") for item in sentences if item.get("sentence_id")],
            }
            for key in ("label", "float_kind"):
                if row.get(key):
                    paragraph_unit[key] = row.get(key)
            index[paragraph_id] = paragraph_unit
            label = str(row.get("label") or "")
            if label:
                index[label] = paragraph_unit
        for sentence in sentences:
            sentence_id = str(sentence.get("sentence_id") or "")
            if sentence_id:
                index[sentence_id] = sentence
            label = str(sentence.get("label") or "")
            if label and label not in index:
                index[label] = sentence
    return index


def pdftotext_bbox(pdf: Path) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext is unavailable")
    with tempfile.NamedTemporaryFile(suffix=".html") as tmp:
        result = subprocess.run(
            ["pdftotext", "-bbox-layout", str(pdf), tmp.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "pdftotext -bbox-layout failed")
        return Path(tmp.name).read_text(encoding="utf-8", errors="replace")


def clean_bbox_xml(xhtml: str) -> str:
    return "".join(
        char
        for char in xhtml
        if char in "\t\n\r" or ord(char) >= 0x20
    )


def parse_word_boxes(xhtml: str) -> tuple[list[WordBox], dict[int, tuple[float, float]]]:
    root = ET.fromstring(clean_bbox_xml(xhtml).encode("utf-8"))
    words: list[WordBox] = []
    page_sizes: dict[int, tuple[float, float]] = {}
    page_no = 0
    for page in root.iter():
        if not page.tag.endswith("page"):
            continue
        page_no += 1
        width = float(page.attrib.get("width", "0") or 0)
        height = float(page.attrib.get("height", "0") or 0)
        page_sizes[page_no] = (width, height)
        for word in page.iter():
            if not word.tag.endswith("word"):
                continue
            text = "".join(word.itertext()).strip()
            norm = "".join(tokens(text))
            if not norm:
                continue
            words.append(
                WordBox(
                    page=page_no,
                    text=text,
                    norm=norm,
                    x0=float(word.attrib.get("xMin", "0") or 0),
                    y0=float(word.attrib.get("yMin", "0") or 0),
                    x1=float(word.attrib.get("xMax", "0") or 0),
                    y1=float(word.attrib.get("yMax", "0") or 0),
                )
            )
    return words, page_sizes


def synctex_sidecar_exists(pdf: Path) -> bool:
    return pdf.with_suffix(".synctex.gz").exists() or pdf.with_suffix(".synctex").exists()


def synctex_hint(pdf: Path, source_file: str, line_start: int, *, enabled: bool = True) -> dict[str, Any] | None:
    if not enabled or not source_file or not line_start or not shutil.which("synctex"):
        return None
    result = subprocess.run(
        ["synctex", "view", "-i", f"{line_start}:1:{source_file}", "-o", str(pdf)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        return {"status": "error", "message": compact_text(output)}
    page_match = re.search(r"\bPage:(\d+)", output)
    x_match = re.search(r"\bx:([-0-9.]+)", output)
    y_match = re.search(r"\by:([-0-9.]+)", output)
    width_match = re.search(r"\b(?:W|Width|w):([-0-9.]+)", output)
    height_match = re.search(r"\b(?:H|Height|h):([-0-9.]+)", output)
    if not page_match:
        return {"status": "no_page", "message": compact_text(output)}
    x = float(x_match.group(1)) if x_match else None
    y = float(y_match.group(1)) if y_match else None
    width = float(width_match.group(1)) if width_match else None
    height = float(height_match.group(1)) if height_match else None
    region = None
    if x is not None and y is not None and width is not None and height is not None:
        region = {
            "x0": x,
            "y0": y,
            "x1": x + max(width, 1.0),
            "y1": y + max(height, 1.0),
        }
    return {
        "status": "ok",
        "page": int(page_match.group(1)),
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "region": region,
    }


def rect_for_words(words: list[WordBox], page_sizes: dict[int, tuple[float, float]]) -> list[dict[str, float | int]]:
    by_line: dict[tuple[int, int], list[WordBox]] = {}
    for word in words:
        line_key = (word.page, int(round(word.y0 / 3.0)))
        by_line.setdefault(line_key, []).append(word)
    rects: list[dict[str, float | int]] = []
    for (_page, _line), line_words in sorted(by_line.items()):
        page = line_words[0].page
        x0 = min(word.x0 for word in line_words)
        y0 = min(word.y0 for word in line_words)
        x1 = max(word.x1 for word in line_words)
        y1 = max(word.y1 for word in line_words)
        width, height = page_sizes.get(page, (0.0, 0.0))
        rect: dict[str, float | int] = {"page": page, "x0": x0, "y0": y0, "x1": x1, "y1": y1}
        if width > 0 and height > 0:
            rect.update(
                {
                    "x0_pct": x0 / width,
                    "y0_pct": y0 / height,
                    "x1_pct": x1 / width,
                    "y1_pct": y1 / height,
                }
            )
        rects.append(rect)
    return rects


CAPTION_PREFIX_RE = re.compile(r"^(figure|fig|table|algorithm|alg|equation|eq)\.?$", re.IGNORECASE)


def same_pdf_line(left: WordBox, right: WordBox, *, tolerance: float = 4.0) -> bool:
    return left.page == right.page and abs(left.y0 - right.y0) <= tolerance


def expand_caption_prefix(words: list[WordBox], search: WordSearchIndex) -> list[WordBox]:
    if not words:
        return words
    first = words[0]
    page_words = search.scope(first.page).words
    first_index: int | None = None
    for index, word in enumerate(page_words):
        if word is first or (
            word.text == first.text
            and word.x0 == first.x0
            and word.y0 == first.y0
            and word.x1 == first.x1
            and word.y1 == first.y1
        ):
            first_index = index
            break
    if first_index is None:
        return words

    prefix_start: int | None = None
    for index in range(max(0, first_index - 4), first_index):
        candidate = page_words[index]
        if same_pdf_line(candidate, first) and CAPTION_PREFIX_RE.match(candidate.norm):
            prefix_start = index
            break
    if prefix_start is None:
        return words
    return page_words[prefix_start:first_index] + words


def merge_rects(rects: list[dict[str, float | int]], page_sizes: dict[int, tuple[float, float]]) -> list[dict[str, float | int]]:
    by_line: dict[tuple[int, int], list[dict[str, float | int]]] = {}
    for rect in rects:
        page = int(rect.get("page") or 0)
        if page <= 0:
            continue
        y0 = float(rect.get("y0") or 0.0)
        line_key = (page, int(round(y0 / 5.0)))
        by_line.setdefault(line_key, []).append(rect)
    merged: list[dict[str, float | int]] = []
    for (page, _line), line_rects in sorted(by_line.items()):
        x0 = min(float(rect.get("x0") or 0.0) for rect in line_rects)
        y0 = min(float(rect.get("y0") or 0.0) for rect in line_rects)
        x1 = max(float(rect.get("x1") or 0.0) for rect in line_rects)
        y1 = max(float(rect.get("y1") or 0.0) for rect in line_rects)
        width, height = page_sizes.get(page, (0.0, 0.0))
        merged_rect: dict[str, float | int] = {"page": page, "x0": x0, "y0": y0, "x1": x1, "y1": y1}
        if width > 0 and height > 0:
            merged_rect.update(
                {
                    "x0_pct": x0 / width,
                    "y0_pct": y0 / height,
                    "x1_pct": x1 / width,
                    "y1_pct": y1 / height,
                }
            )
        merged.append(merged_rect)
    return merged


def vertical_overlap(left: dict[str, float | int], right: dict[str, float | int], *, tolerance: float = 6.0) -> bool:
    if int(left.get("page") or 0) != int(right.get("page") or 0):
        return False
    left_top = float(left.get("y0") or 0.0) - tolerance
    left_bottom = float(left.get("y1") or 0.0) + tolerance
    right_top = float(right.get("y0") or 0.0) - tolerance
    right_bottom = float(right.get("y1") or 0.0) + tolerance
    return max(left_top, right_top) <= min(left_bottom, right_bottom)


def augment_math_rects_with_synctex(
    word_rects: list[dict[str, float | int]],
    hint_rects: list[dict[str, float | int]],
    page_sizes: dict[int, tuple[float, float]],
) -> list[dict[str, float | int]]:
    if not word_rects or not hint_rects:
        return word_rects
    additions = [
        hint_rect
        for hint_rect in hint_rects
        if any(vertical_overlap(hint_rect, word_rect) for word_rect in word_rects)
    ]
    if not additions:
        return word_rects
    return merge_rects(word_rects + additions, page_sizes)


def candidate_starts(query_tokens: list[str], scope: SearchScope, *, limit: int = 96) -> list[int]:
    if not query_tokens or not scope.words:
        return []
    votes: dict[int, float] = {}

    def add(start: int, weight: float) -> None:
        if 0 <= start < len(scope.words):
            votes[start] = votes.get(start, 0.0) + weight

    first_token = query_tokens[0]
    for position in scope.positions_by_token.get(first_token, []):
        add(position, 4.0)

    seen: set[str] = set()
    token_frequencies: list[tuple[int, str, int]] = []
    for query_index, token in enumerate(query_tokens):
        if token in seen:
            continue
        seen.add(token)
        positions = scope.positions_by_token.get(token)
        if positions:
            token_frequencies.append((len(positions), token, query_index))
    for frequency, token, query_index in sorted(token_frequencies)[:10]:
        positions = scope.positions_by_token.get(token, [])
        if frequency > 1000 and query_index != 0:
            continue
        weight = 2.0 if query_index == 0 else 1.0 + (1.0 / max(frequency, 1))
        for position in positions:
            start = position - query_index
            add(start, weight)
            add(start - 1, weight * 0.15)
            add(start + 1, weight * 0.15)

    return [
        start
        for start, _score in sorted(votes.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def exact_window(query_tokens: list[str], scope: SearchScope, starts: list[int]) -> tuple[int, int] | None:
    query_len = len(query_tokens)
    for start in starts:
        end = start + query_len
        if end <= len(scope.token_values) and scope.token_values[start:end] == query_tokens:
            return start, end
    return None


def find_token_window(
    query_tokens: list[str],
    search: WordSearchIndex | list[WordBox],
    *,
    page: int | None = None,
    pages: list[int] | None = None,
    y: float | None = None,
    region: dict[str, Any] | None = None,
) -> tuple[list[WordBox], float]:
    if not query_tokens:
        return [], 0.0
    if isinstance(search, WordSearchIndex):
        if page is not None and isinstance(region, dict):
            scope = search.region_scope(
                page,
                x0=float(region.get("x0") or 0.0),
                y0=float(region.get("y0") or 0.0),
                x1=float(region.get("x1") or 0.0),
                y1=float(region.get("y1") or 0.0),
            )
        elif page is not None and y is not None:
            scope = search.y_band_scope(page, y)
        elif pages is not None:
            scope = search.pages_scope(pages)
        else:
            scope = search.scope(page)
    else:
        page_filter = set(pages or [])
        scope_words = [
            word
            for word in search
            if (page is None or word.page == page) and (not page_filter or word.page in page_filter)
        ]
        if page is not None and isinstance(region, dict):
            left = min(float(region.get("x0") or 0.0), float(region.get("x1") or 0.0)) - 24.0
            right = max(float(region.get("x0") or 0.0), float(region.get("x1") or 0.0)) + 24.0
            top = min(float(region.get("y0") or 0.0), float(region.get("y1") or 0.0)) - 24.0
            bottom = max(float(region.get("y0") or 0.0), float(region.get("y1") or 0.0)) + 24.0
            scope_words = [
                word
                for word in scope_words
                if word.x1 >= left and word.x0 <= right and word.y1 >= top and word.y0 <= bottom
            ]
        if y is not None:
            scope_words = [word for word in scope_words if abs(word.y0 - y) <= 80.0 or abs(word.y1 - y) <= 80.0]
        scope = SearchScope.build(scope_words)
    if not scope.words:
        return [], 0.0
    starts = candidate_starts(query_tokens, scope)
    if not starts:
        return [], 0.0
    exact = exact_window(query_tokens, scope, starts)
    if exact is not None:
        start, end = exact
        return scope.words[start:end], 1.0

    query_joined = "".join(query_tokens)
    best: tuple[int, int, float] = (0, 0, 0.0)
    max_window = max(len(query_tokens) + 6, 8)
    min_window = max(1, len(query_tokens) - 3)
    for start in starts:
        max_end = min(len(scope.words), start + max_window)
        for end in range(start + min_window, max_end + 1):
            window_tokens = scope.token_values[start:end]
            window_joined = "".join(window_tokens)
            token_ratio = SequenceMatcher(None, query_tokens, window_tokens).ratio()
            char_ratio = SequenceMatcher(None, query_joined, window_joined).ratio()
            ratio = max(token_ratio, char_ratio)
            current_len = end - start
            best_len = best[1] - best[0]
            if ratio > best[2] or (ratio == best[2] and (not best_len or current_len < best_len)):
                best = (start, end, ratio)
            if ratio >= 0.995:
                return scope.words[start:end], ratio
    return scope.words[best[0] : best[1]], best[2]


def query_token_variants(unit: dict[str, Any], rendered: str) -> list[list[str]]:
    variants: list[list[str]] = []
    base = tokens(rendered)
    if base:
        variants.append(base)
    source = str(unit.get("text") or "")
    if math_heavy(source) or math_heavy(rendered):
        source_tokens = tokens(source)
        if source_tokens and source_tokens not in variants:
            variants.append(source_tokens)
    return variants


def find_best_token_window(
    query_variants: list[list[str]],
    search: WordSearchIndex | list[WordBox],
    **kwargs: Any,
) -> tuple[list[WordBox], float]:
    best_words: list[WordBox] = []
    best_ratio = 0.0
    for query_tokens in query_variants:
        matched_words, ratio = find_token_window(query_tokens, search, **kwargs)
        if ratio > best_ratio or (ratio == best_ratio and matched_words and (not best_words or len(matched_words) < len(best_words))):
            best_words = matched_words
            best_ratio = ratio
        if ratio >= 0.995:
            break
    return best_words, best_ratio


def rect_from_synctex_hint(
    hint: dict[str, Any] | None,
    page_sizes: dict[int, tuple[float, float]],
) -> list[dict[str, float | int]]:
    if not isinstance(hint, dict) or hint.get("status") != "ok" or not isinstance(hint.get("page"), int):
        return []
    page = int(hint["page"])
    width, height = page_sizes.get(page, (0.0, 0.0))
    if width <= 0 or height <= 0:
        return []
    region = hint.get("region")
    if isinstance(region, dict):
        x0 = max(0.0, min(float(region.get("x0") or 0.0), float(region.get("x1") or 0.0)) - 8.0)
        y0 = max(0.0, min(float(region.get("y0") or 0.0), float(region.get("y1") or 0.0)) - 8.0)
        x1 = min(width, max(float(region.get("x0") or 0.0), float(region.get("x1") or 0.0)) + 8.0)
        y1 = min(height, max(float(region.get("y0") or 0.0), float(region.get("y1") or 0.0)) + 8.0)
    elif isinstance(hint.get("y"), (int, float)):
        y = float(hint["y"])
        x0 = 0.0
        y0 = max(0.0, y - 10.0)
        x1 = width
        y1 = min(height, y + 18.0)
    else:
        return []
    rect: dict[str, float | int] = {"page": page, "x0": x0, "y0": y0, "x1": x1, "y1": y1}
    rect.update({"x0_pct": x0 / width, "y0_pct": y0 / height, "x1_pct": x1 / width, "y1_pct": y1 / height})
    return [rect]


def words_from_synctex_hint(
    search: WordSearchIndex,
    hint: dict[str, Any] | None,
) -> list[WordBox]:
    if not isinstance(hint, dict) or hint.get("status") != "ok" or not isinstance(hint.get("page"), int):
        return []
    page = int(hint["page"])
    region = hint.get("region")
    if isinstance(region, dict):
        return search.region_scope(
            page,
            x0=float(region.get("x0") or 0.0),
            y0=float(region.get("y0") or 0.0),
            x1=float(region.get("x1") or 0.0),
            y1=float(region.get("y1") or 0.0),
            padding=36.0,
        ).words
    if isinstance(hint.get("y"), (int, float)):
        return search.y_band_scope(page, float(hint["y"]), tolerance=24.0).words
    return []


def whole_page_rect(page: int, page_sizes: dict[int, tuple[float, float]]) -> list[dict[str, float | int]]:
    width, height = page_sizes.get(page, (0.0, 0.0))
    if width <= 0 or height <= 0:
        return []
    return [{"page": page, "x0": 0.0, "y0": 0.0, "x1": width, "y1": height, "x0_pct": 0.0, "y0_pct": 0.0, "x1_pct": 1.0, "y1_pct": 1.0}]


def page_marker(value: Any) -> int | None:
    text = str(value or "")
    if not text.startswith("page:"):
        return None
    try:
        return int(text.split(":", 1)[1])
    except ValueError:
        return None


def math_heavy(value: Any) -> bool:
    text = str(value or "")
    return bool(
        "$" in text
        or "\\(" in text
        or "\\[" in text
        or "\\begin{equation" in text
        or re.search(r"\\(?:frac|sum|prod|int|alpha|beta|gamma|theta|lambda|sim|approx|leq|geq|cdot|times)\b", text)
    )


def review_units_pdf_text_payload(sentence_bbox_payload: dict[str, Any]) -> dict[str, Any]:
    anchors = sentence_bbox_payload.get("anchors")
    sidecar_anchors: dict[str, Any] = {}
    if isinstance(anchors, dict):
        for anchor_id, anchor in anchors.items():
            if not isinstance(anchor, dict):
                continue
            sidecar_anchors[str(anchor_id)] = {
                "rendered_text_pdf": anchor.get("rendered_text_pdf") or "",
                "confidence": anchor.get("confidence") or "",
                "method": anchor.get("method") or "",
                "match_ratio": anchor.get("match_ratio") or 0,
                "unmappable": bool(anchor.get("unmappable")),
            }
            if anchor.get("reason"):
                sidecar_anchors[str(anchor_id)]["reason"] = anchor.get("reason")
    return {
        "schema_version": 1,
        "generated_by": "scripts/build_sentence_bbox.py",
        "pdf_hash": sentence_bbox_payload.get("pdf_hash") or "",
        "review_units_hash": sentence_bbox_payload.get("review_units_hash") or "",
        "anchors": sidecar_anchors,
    }


def build_sentence_bbox(pdf: Path, review_units: Path) -> dict[str, Any]:
    unit_index = review_unit_texts(review_units)
    words, page_sizes = parse_word_boxes(pdftotext_bbox(pdf))
    search = WordSearchIndex(words)
    use_synctex = synctex_sidecar_exists(pdf)
    anchors: dict[str, Any] = {}
    confidence_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "unmappable": 0}
    last_mapped_page: int | None = None
    unit_items = list(unit_index.items())
    ordered_units = [
        (unit_id, unit) for unit_id, unit in unit_items if not unit.get("sentence_ids")
    ] + [
        (unit_id, unit) for unit_id, unit in unit_items if unit.get("sentence_ids")
    ]
    for unit_id, unit in ordered_units:
        layout_page = page_marker(unit.get("line_start")) if str(unit.get("unit_kind") or "") == "page_layout" else None
        if layout_page is not None:
            rects = whole_page_rect(layout_page, page_sizes)
            if rects:
                rendered = str(unit.get("rendered_text_pdf") or unit.get("rendered_text_initial") or unit.get("text") or "")
                anchors[unit_id] = {
                    "unit_kind": "page_layout",
                    "confidence": "low",
                    "method": "page_layout_whole_page",
                    "match_ratio": 1.0,
                    "source_file": unit.get("source_file") or "",
                    "line_start": unit.get("line_start") or 0,
                    "line_end": unit.get("line_end") or 0,
                    "rendered_text_pdf": rendered,
                    "rects": rects,
                    "unmappable": False,
                    "synctex": None,
                }
                confidence_counts["low"] += 1
                last_mapped_page = layout_page
                continue
        sentence_ids = [str(item) for item in unit.get("sentence_ids", []) if item]
        if sentence_ids:
            sentence_anchors = [anchors.get(sentence_id) for sentence_id in sentence_ids]
            mapped_sentence_anchors = [
                anchor
                for anchor in sentence_anchors
                if isinstance(anchor, dict) and not anchor.get("unmappable") and anchor.get("rects")
            ]
            if mapped_sentence_anchors:
                rects = merge_rects(
                    [rect for anchor in mapped_sentence_anchors for rect in anchor.get("rects", []) if isinstance(rect, dict)],
                    page_sizes,
                )
                rendered_pdf = " ".join(str(anchor.get("rendered_text_pdf") or "") for anchor in mapped_sentence_anchors).strip()
                ratio = len(mapped_sentence_anchors) / max(len(sentence_ids), 1)
                confidence = "medium" if ratio >= 0.80 else "low"
                anchors[unit_id] = {
                    "unit_kind": unit.get("unit_kind") or "prose",
                    "confidence": confidence,
                    "method": "sentence_anchor_union",
                    "match_ratio": round(ratio, 3),
                    "source_file": unit.get("source_file") or "",
                    "line_start": unit.get("line_start") or 0,
                    "line_end": unit.get("line_end") or 0,
                    "rendered_text_pdf": rendered_pdf,
                    "rects": rects,
                    "unmappable": False,
                    "synctex": None,
                }
                confidence_counts[confidence] += 1
                if rects:
                    last_mapped_page = int(rects[-1]["page"])
                continue
        rendered = str(unit.get("rendered_text_pdf") or unit.get("rendered_text_initial") or unit.get("text") or "")
        query_variants = query_token_variants(unit, rendered)
        query_tokens = query_variants[0] if query_variants else []
        try:
            line_start = int(unit.get("line_start") or 0)
        except (TypeError, ValueError):
            line_start = 0
        hint = synctex_hint(pdf, str(unit.get("source_file") or ""), line_start, enabled=use_synctex)
        hinted_page = hint.get("page") if isinstance(hint, dict) and hint.get("status") == "ok" else None
        source_page = int(unit["page"]) if isinstance(unit.get("page"), int) else None
        matched_words: list[WordBox] = []
        ratio = 0.0
        method = "poppler_full_pdf_fuzzy"
        if isinstance(hinted_page, int):
            hint_y = hint.get("y") if isinstance(hint, dict) and isinstance(hint.get("y"), (int, float)) else None
            hint_region = hint.get("region") if isinstance(hint, dict) and isinstance(hint.get("region"), dict) else None
            if hint_region is not None:
                matched_words, ratio = find_best_token_window(query_variants, search, page=hinted_page, region=hint_region)
                method = "synctex_region+poppler_word_match"
            if hint_y is not None:
                y_words, y_ratio = find_best_token_window(query_variants, search, page=hinted_page, y=float(hint_y))
                if y_ratio > ratio:
                    matched_words, ratio = y_words, y_ratio
                    method = "synctex_y_band+poppler_word_match"
            if ratio < 0.80:
                matched_words, ratio = find_best_token_window(query_variants, search, page=hinted_page)
                method = "synctex_page+poppler_word_match"
        elif isinstance(source_page, int) and source_page in search.page_scopes:
            matched_words, ratio = find_best_token_window(query_variants, search, page=source_page)
            method = "source_page+poppler_word_match"
        elif isinstance(last_mapped_page, int):
            nearby_pages = [
                page
                for page in (last_mapped_page, last_mapped_page + 1, last_mapped_page - 1, last_mapped_page + 2)
                if page in search.page_scopes
            ]
            seen_pages: set[int] = set()
            for page in nearby_pages:
                if page in seen_pages:
                    continue
                seen_pages.add(page)
                page_words, page_ratio = find_best_token_window(query_variants, search, page=page)
                if page_ratio > ratio:
                    matched_words, ratio = page_words, page_ratio
                    method = "nearby_page+poppler_word_match"
                if ratio >= 0.90:
                    break
            if len(nearby_pages) >= 2 and ratio < 0.80:
                cross_page_words, cross_page_ratio = find_best_token_window(query_variants, search, pages=nearby_pages[:2])
                if cross_page_ratio > ratio:
                    matched_words, ratio = cross_page_words, cross_page_ratio
                    method = "nearby_pages+poppler_word_match"
        if ratio < 0.80:
            fallback_words, fallback_ratio = find_best_token_window(query_variants, search)
            if fallback_ratio > ratio:
                matched_words, ratio = fallback_words, fallback_ratio
                method = "poppler_full_pdf_fuzzy"
        hint_rects = rect_from_synctex_hint(hint if isinstance(hint, dict) else None, page_sizes)
        allow_hint_fallback = (
            not query_tokens
            or str(unit.get("unit_kind") or "") in {"caption", "section_heading", "footnote"}
            or math_heavy(unit.get("text") or unit.get("rendered_text_initial"))
        )
        if ratio >= 0.80 and matched_words:
            if str(unit.get("unit_kind") or "") == "caption":
                matched_words = expand_caption_prefix(matched_words, search)
            confidence = "high" if method.startswith("synctex") and ratio >= 0.90 else "medium"
            rects = rect_for_words(matched_words, page_sizes)
            if hint_rects and math_heavy(unit.get("text") or unit.get("rendered_text_initial")):
                augmented_rects = augment_math_rects_with_synctex(rects, hint_rects, page_sizes)
                if len(augmented_rects) != len(rects) or augmented_rects != rects:
                    rects = augmented_rects
                    method += "+synctex_math_region"
            rendered_pdf = " ".join(word.text for word in matched_words)
            anchors[unit_id] = {
                "unit_kind": unit.get("unit_kind") or "prose",
                "confidence": confidence,
                "method": method,
                "match_ratio": round(ratio, 3),
                "source_file": unit.get("source_file") or "",
                "line_start": unit.get("line_start") or 0,
                "line_end": unit.get("line_end") or 0,
                "rendered_text_pdf": rendered_pdf,
                "rects": rects,
                "unmappable": False,
                "synctex": hint,
            }
            confidence_counts[confidence] += 1
            if rects:
                last_mapped_page = int(rects[-1]["page"])
        elif allow_hint_fallback and hint_rects:
            fallback_words = words_from_synctex_hint(search, hint if isinstance(hint, dict) else None)
            fallback_rects = rect_for_words(fallback_words, page_sizes) if fallback_words else hint_rects
            fallback_text = " ".join(word.text for word in fallback_words)
            anchors[unit_id] = {
                "unit_kind": unit.get("unit_kind") or "prose",
                "confidence": "low",
                "method": "synctex_region_word_fallback" if fallback_words else "synctex_region_fallback",
                "match_ratio": round(ratio, 3),
                "source_file": unit.get("source_file") or "",
                "line_start": unit.get("line_start") or 0,
                "line_end": unit.get("line_end") or 0,
                "rendered_text_pdf": fallback_text,
                "rects": fallback_rects,
                "unmappable": False,
                "synctex": hint,
            }
            confidence_counts["low"] += 1
            last_mapped_page = int(fallback_rects[-1]["page"])
        else:
            anchors[unit_id] = {
                "unit_kind": unit.get("unit_kind") or "prose",
                "confidence": "unmappable",
                "method": method,
                "match_ratio": round(ratio, 3),
                "source_file": unit.get("source_file") or "",
                "line_start": unit.get("line_start") or 0,
                "line_end": unit.get("line_end") or 0,
                "rendered_text_pdf": "",
                "rects": [],
                "unmappable": True,
                "reason": "no sufficiently similar PDF text window",
                "synctex": hint,
            }
            confidence_counts["unmappable"] += 1
    return {
        "schema_version": 1,
        "generated_by": "scripts/build_sentence_bbox.py",
        "pdf_path": str(pdf),
        "pdf_hash": sha256_path(pdf),
        "review_units": str(review_units),
        "review_units_hash": sha256_path(review_units),
        "page_sizes": {str(page): {"width": width, "height": height} for page, (width, height) in page_sizes.items()},
        "anchors": anchors,
        "coverage": {
            "anchors_total": len(anchors),
            "confidence_counts": confidence_counts,
            "mapped": len(anchors) - confidence_counts["unmappable"],
            "unmappable": confidence_counts["unmappable"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--review-units", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--review-units-pdf-text-out", type=Path)
    args = parser.parse_args(argv)

    payload = build_sentence_bbox(args.pdf.expanduser().resolve(), args.review_units.expanduser().resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.review_units_pdf_text_out:
        sidecar = review_units_pdf_text_payload(payload)
        args.review_units_pdf_text_out.parent.mkdir(parents=True, exist_ok=True)
        args.review_units_pdf_text_out.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    coverage = payload["coverage"]
    print(
        "Sentence bbox: "
        f"mapped={coverage['mapped']} unmappable={coverage['unmappable']} "
        f"confidence={coverage['confidence_counts']} out={args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
