#!/usr/bin/env python3
"""Extract fallback Ariadne review units from a PDF when no TeX source is available."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？])\s+")
ABBREVIATIONS = {"al.", "e.g.", "i.e.", "vs.", "fig.", "eq.", "sec.", "tab.", "dr.", "prof."}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def run_pdftotext(pdf: Path) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is required for PDF-only review-unit extraction")
    result = subprocess.run(
        [pdftotext, "-layout", str(pdf), "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "pdftotext failed")
    return result.stdout


def split_pages(text: str) -> list[str]:
    pages = [page.strip() for page in text.split("\f")]
    return [page for page in pages if page]


def split_paragraphs(page_text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n+", page_text)
    paragraphs: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        text = compact_text(" ".join(lines))
        if text:
            paragraphs.append(text)
    return paragraphs


def split_sentences(text: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    for match in SENTENCE_END_RE.finditer(text):
        end = match.end()
        sentence = text[start:end].strip()
        last = sentence.split()[-1].lower() if sentence.split() else ""
        if last in ABBREVIATIONS:
            continue
        if sentence:
            pieces.append(sentence)
        start = end
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return pieces or [text]


def extract_units(pdf: Path) -> list[dict[str, Any]]:
    pages = split_pages(run_pdftotext(pdf))
    units: list[dict[str, Any]] = [
        {
            "kind": "section",
            "section_id": "pdf-only",
            "level": 1,
            "text": "PDF-only extracted text",
            "unit_kind": "section_heading",
            "source_file": str(pdf),
            "line_start": 1,
            "line_end": 1,
            "source_mode": "pdf_only",
        }
    ]
    paragraph_index = 0
    for page_no, page_text in enumerate(pages, 1):
        for paragraph_text in split_paragraphs(page_text):
            paragraph_index += 1
            paragraph_id = f"p-pdf-p{page_no:03d}-{paragraph_index:03d}"
            sentences = []
            for sentence_index, sentence_text in enumerate(split_sentences(paragraph_text), 1):
                sentence_id = f"s-pdf-p{page_no:03d}-{paragraph_index:03d}-s{sentence_index:03d}"
                sentences.append(
                    {
                        "sentence_id": sentence_id,
                        "unit_kind": "prose",
                        "text": sentence_text,
                        "rendered_text_initial": sentence_text,
                        "rendered_text_pdf": sentence_text,
                        "source_file": str(pdf),
                        "line_start": page_no,
                        "line_end": page_no,
                        "text_hash": sha256_text(sentence_text),
                        "source_mode": "pdf_only",
                        "page": page_no,
                    }
                )
            if sentences:
                units.append(
                    {
                        "kind": "paragraph",
                        "paragraph_id": paragraph_id,
                        "section_id": "pdf-only",
                        "section_title": "PDF-only extracted text",
                        "unit_kind": "prose",
                        "source_file": str(pdf),
                        "line_start": page_no,
                        "line_end": page_no,
                        "source_mode": "pdf_only",
                        "page": page_no,
                        "sentences": sentences,
                    }
                )
    return units


def write_jsonl(units: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for unit in units:
            handle.write(json.dumps(unit, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_markdown(units: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = ["# PDF-only extracted text {#pdf-only}", ""]
    for unit in units:
        if unit.get("kind") != "paragraph":
            continue
        lines.append(f"[{unit.get('paragraph_id', '')}]")
        for sentence in unit.get("sentences", []):
            rendered = sentence.get("rendered_text_initial") or sentence.get("text") or ""
            lines.append(f"{{{sentence['sentence_id']}}} {rendered}  [src: pdf-page:{sentence.get('page', '')}]")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--jsonl", type=Path)
    parser.add_argument("--markdown", "--md", dest="markdown", type=Path)
    args = parser.parse_args(argv)

    pdf = args.pdf.expanduser().resolve()
    if not pdf.exists():
        parser.error(f"PDF does not exist: {pdf}")
    units = extract_units(pdf)
    jsonl_path = args.jsonl or pdf.with_suffix(".review_units.jsonl")
    markdown_path = args.markdown or pdf.with_suffix(".review_units.md")
    write_jsonl(units, jsonl_path)
    write_markdown(units, markdown_path)
    paragraphs = [unit for unit in units if unit.get("kind") == "paragraph"]
    sentence_count = sum(len(unit.get("sentences", [])) for unit in paragraphs)
    print(f"PDF review units JSONL: {jsonl_path}")
    print(f"PDF review units Markdown: {markdown_path}")
    print(f"PDF hash: {sha256_path(pdf)}")
    print(f"Paragraphs: {len(paragraphs)}")
    print(f"Sentences: {sentence_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
