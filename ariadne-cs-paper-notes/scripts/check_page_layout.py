#!/usr/bin/env python3
"""Run a page-local PDF layout audit and emit compact JSON observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


TOOL_NAME = "scripts/check_page_layout.py"
TOOL_VERSION = "1"
SEVERITY_POLISH = "polish"
SUBPROCESS_TIMEOUT_SECONDS = 90
MAX_OBSERVATIONS_PER_PAGE = 12
IGNORED_SINGLE_WORDS = {
    "abstract",
    "acknowledgments",
    "acknowledgements",
    "affiliation",
    "address",
    "appendix",
    "conclusion",
    "introduction",
    "method",
    "methods",
    "results",
    "discussion",
    "email",
    "references",
}
NUMERIC_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\.?$")
MARGIN_LINE_NUMBER_RE = re.compile(r"^\d{1,5}$")
CAPTION_LABEL_RE = re.compile(r"^(?:Figure|Fig|Table|Eq|Eqn|Equation|Algorithm|Alg)\.?\s*\d+", re.IGNORECASE)
TRAILING_PUNCT_RE = re.compile(r"[,.;:]\s*$")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def parse_pages(value: str, total_pages: int) -> list[int]:
    if value.strip().lower() in {"", "all"}:
        return list(range(1, total_pages + 1))
    pages: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"invalid page range `{part}`")
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    invalid = sorted(page for page in pages if page < 1 or page > total_pages)
    if invalid:
        raise ValueError(f"page numbers outside 1-{total_pages}: {invalid}")
    return sorted(pages)


def pdf_page_count(path: Path) -> int:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        pdfinfo = shutil.which("pdfinfo")
        if not pdfinfo:
            raise RuntimeError("pypdf or pdfinfo is required for page counting")
        result = subprocess.run(
            [pdfinfo, str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "pdfinfo failed")
        match = re.search(r"^Pages:\s*(\d+)\s*$", result.stdout, flags=re.MULTILINE)
        if not match:
            raise RuntimeError("pdfinfo did not report a page count")
        return int(match.group(1))
    return len(PdfReader(str(path)).pages)


def float_attr(attrs: dict[str, str], key: str) -> float:
    value = attrs.get(key)
    if value is None:
        value = attrs.get(key.lower())
    try:
        return float(value or "0")
    except ValueError:
        return 0.0


class BBoxParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.pages: list[dict[str, Any]] = []
        self._current_page: dict[str, Any] | None = None
        self._current_line: dict[str, Any] | None = None
        self._in_word = False
        self._word_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "page":
            self._current_page = {
                "width": float_attr(attr, "width"),
                "height": float_attr(attr, "height"),
                "lines": [],
            }
            self.pages.append(self._current_page)
        elif tag == "line" and self._current_page is not None:
            self._current_line = {
                "xMin": float_attr(attr, "xMin"),
                "yMin": float_attr(attr, "yMin"),
                "xMax": float_attr(attr, "xMax"),
                "yMax": float_attr(attr, "yMax"),
                "words": [],
            }
            self._current_page["lines"].append(self._current_line)
        elif tag == "word" and self._current_line is not None:
            self._in_word = True
            self._word_text_parts = []
            self._current_line["words"].append(
                {
                    "xMin": float_attr(attr, "xMin"),
                    "yMin": float_attr(attr, "yMin"),
                    "xMax": float_attr(attr, "xMax"),
                    "yMax": float_attr(attr, "yMax"),
                    "text": "",
                }
            )

    def handle_data(self, data: str) -> None:
        if self._in_word:
            self._word_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "word" and self._in_word and self._current_line is not None and self._current_line["words"]:
            self._current_line["words"][-1]["text"] = "".join(self._word_text_parts).strip()
            self._in_word = False
            self._word_text_parts = []
        elif tag == "line":
            self._current_line = None
        elif tag == "page":
            self._current_page = None


def run_pdftotext_bbox(pdf: Path, pages: list[int], pdftotext: str) -> str:
    if not pages:
        return ""
    chunks: list[str] = []
    for page in pages:
        result = subprocess.run(
            [pdftotext, "-f", str(page), "-l", str(page), "-bbox-layout", str(pdf), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pdftotext failed on page {page}: {result.stderr.strip()[:300]}")
        chunks.append(result.stdout)
    return "\n".join(chunks)


def line_text(line: dict[str, Any]) -> str:
    return " ".join(str(word.get("text", "")).strip() for word in line.get("words", []) if str(word.get("text", "")).strip())


def is_probable_page_number(text: str) -> bool:
    stripped = text.strip()
    return stripped.isdigit() or (stripped.startswith("-") and stripped.endswith("-") and stripped.strip("-").isdigit())


def is_probable_margin_line_number(text: str, x_min: float, x_max: float, width: float) -> bool:
    stripped = text.strip()
    if not MARGIN_LINE_NUMBER_RE.match(stripped):
        return False
    span = max(0.0, x_max - x_min)
    marker_band = max(36.0, width * 0.07)
    marker_width = max(24.0, width * 0.045)
    return span <= marker_width and (x_max <= marker_band or x_min >= width - marker_band)


def is_probable_intentional_short_line(text: str) -> bool:
    stripped = text.strip()
    return (
        bool(NUMERIC_HEADING_RE.match(stripped))
        or bool(CAPTION_LABEL_RE.match(stripped))
        or bool(TRAILING_PUNCT_RE.search(stripped))
    )


def observation(
    *,
    page: int,
    issue_type: str,
    severity: str,
    bbox: list[float],
    observation_text: str,
    evidence: str,
    needs_main_review: bool,
    script_hash: str,
) -> dict[str, Any]:
    return {
        "page": page,
        "region_or_bbox": [round(value, 2) for value in bbox],
        "issue_type": issue_type,
        "severity": severity,
        "observation": observation_text,
        "evidence": evidence,
        "needs_main_review": needs_main_review,
        "produced_by": TOOL_NAME,
        "script_hash": script_hash,
    }


def analyze_page(page_number: int, page: dict[str, Any], script_hash: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    width = float(page.get("width") or 0)
    height = float(page.get("height") or 0)
    lines = [line for line in page.get("lines", []) if line_text(line)]
    lines.sort(key=lambda item: (float(item.get("yMin", 0)), float(item.get("xMin", 0))))
    observations: list[dict[str, Any]] = []

    if not lines:
        observations.append(
            observation(
                page=page_number,
                issue_type="blank_page",
                severity=SEVERITY_POLISH,
                bbox=[0, 0, width, height],
                observation_text="Page contains no extractable text; verify whether this is an intentional blank or image-only page.",
                evidence="pdftotext -bbox-layout returned no text lines for this page.",
                needs_main_review=True,
                script_hash=script_hash,
            )
        )
        return observations, {"page": page_number, "line_count": 0, "word_count": 0, "needs_main_review": True}

    body_top = height * 0.20
    body_bottom = height * 0.84
    edge_margin = max(18.0, width * 0.035)
    large_gap = max(72.0, height * 0.10)

    previous_ymax: float | None = None
    word_count = 0
    for line in lines:
        words = [word for word in line.get("words", []) if str(word.get("text", "")).strip()]
        word_count += len(words)
        text = line_text(line)
        x_min = float(line.get("xMin", 0))
        y_min = float(line.get("yMin", 0))
        x_max = float(line.get("xMax", 0))
        y_max = float(line.get("yMax", 0))

        if previous_ymax is not None:
            gap = y_min - previous_ymax
            if gap >= large_gap and body_top < y_min < body_bottom:
                observations.append(
                    observation(
                        page=page_number,
                        issue_type="large_vertical_gap",
                        severity=SEVERITY_POLISH,
                        bbox=[0, previous_ymax, width, y_min],
                        observation_text="Large vertical gap inside the page text area may indicate float or page-break rhythm trouble.",
                        evidence=f"Vertical gap is {gap:.1f} pt before line `{text[:80]}`.",
                        needs_main_review=gap >= height * 0.18,
                        script_hash=script_hash,
                    )
                )
        previous_ymax = max(previous_ymax or y_max, y_max)

        normalized_single = text.strip().strip(".,;:").lower()
        if (
            len(words) == 1
            and body_top < y_min < body_bottom
            and normalized_single not in IGNORED_SINGLE_WORDS
            and not is_probable_page_number(text)
            and not is_probable_intentional_short_line(text)
            and len(text) <= 24
        ):
            observations.append(
                observation(
                    page=page_number,
                    issue_type="isolated_word_line",
                    severity=SEVERITY_POLISH,
                    bbox=[x_min, y_min, x_max, y_max],
                    observation_text="Single-word line in the body area; verify whether it is an orphaned word or intentional label.",
                    evidence=f"Line text: `{text}`.",
                    needs_main_review=False,
                    script_hash=script_hash,
                )
            )

        if (x_min < edge_margin or x_max > width - edge_margin) and not is_probable_margin_line_number(
            text, x_min, x_max, width
        ):
            observations.append(
                observation(
                    page=page_number,
                    issue_type="edge_text",
                    severity=SEVERITY_POLISH,
                    bbox=[x_min, y_min, x_max, y_max],
                    observation_text="Text is close to the page edge; verify margin/overfull layout.",
                    evidence=f"Line bbox x=({x_min:.1f}, {x_max:.1f}) on width {width:.1f}.",
                    needs_main_review=True,
                    script_hash=script_hash,
                )
            )

    summary = {
        "page": page_number,
        "line_count": len(lines),
        "word_count": word_count,
        "observations": len(observations),
        "needs_main_review": any(item.get("needs_main_review") for item in observations),
    }
    if len(observations) > MAX_OBSERVATIONS_PER_PAGE:
        observations = observations[:MAX_OBSERVATIONS_PER_PAGE]
        summary["truncated_observations"] = True
    return observations, summary


def build_payload(pdf: Path, pages: list[int], pdftotext: str) -> dict[str, Any]:
    script_hash = sha256_path(Path(__file__).resolve())
    raw = run_pdftotext_bbox(pdf, pages, pdftotext)
    parser = BBoxParser()
    parser.feed(raw)

    observations: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for page_number, page in zip(pages, parser.pages):
        page_observations, summary = analyze_page(page_number, page, script_hash)
        for idx, item in enumerate(page_observations, 1):
            item["observation_id"] = f"layout-p{page_number:03d}-{idx:03d}"
        observations.extend(page_observations)
        summaries.append(summary)

    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "script_hash": script_hash,
        "pdf": str(pdf),
        "pdf_hash": sha256_path(pdf),
        "pages_total": pdf_page_count(pdf),
        "pages_checked": pages,
        "page_summaries": summaries,
        "observations": observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", default="all", help="Page list/ranges such as `1-3,8`; default: all")
    parser.add_argument("--out", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--pdftotext", help="Path to pdftotext; defaults to PATH lookup")
    args = parser.parse_args(argv)

    pdf = args.pdf.expanduser().resolve()
    if not pdf.exists():
        parser.error(f"PDF does not exist: {pdf}")
    pdftotext = args.pdftotext or shutil.which("pdftotext")
    if not pdftotext:
        parser.error("pdftotext is required for layout bbox extraction")

    try:
        pages_total = pdf_page_count(pdf)
        pages = parse_pages(args.pages, pages_total)
        payload = build_payload(pdf, pages, pdftotext)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
