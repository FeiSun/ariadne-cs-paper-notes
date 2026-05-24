#!/usr/bin/env python3
"""Audit BibTeX/reference hygiene and emit structured reference signals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_paper_text import (  # noqa: E402
    BIB_CMD_RE,
    ExtractionState,
    collect_tex_roots,
    expand_inputs,
    find_bib_files,
    parse_bib_entries,
    project_root_for,
    read_text,
)


TOOL_NAME = "scripts/check_references.py"
TOOL_VERSION = "1"
X_METADATA_FIELDS = {"xurl", "xdoi", "xeprint", "xxurl"}
METADATA_FIELDS = {"url", "doi", "eprint", "archiveprefix"}
ARXIV_RE = re.compile(r"arxiv\s*:?\s*([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", re.IGNORECASE)
ARXIV_ID_RE = re.compile(r"([0-9]{4}\.[0-9]{4,5})(?:v\d+)?")
YEAR_RE = re.compile(r"(19|20)\d{2}")
PROTECTED_TOKEN_RE = re.compile(r"\{[^{}]*(?:[A-Z]{2,}|[A-Za-z]+[-_][A-Za-z0-9]+)[^{}]*\}")
ACRONYM_RE = re.compile(r"\b(?:LLM|RLHF|RL|SFT|RAG|QA|NLP|BERT|GPT|LLaMA|Qwen|DeepSeek|MMLU|NQ|TQA|PopQA)\b")
ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.IGNORECASE)
AUTHOR_ANOMALY_RE = re.compile(r"\b[A-Z]{2,}\b|^[^{}]*:\s+and\b", re.IGNORECASE)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def compact_text(value: Any, *, max_chars: int = 1000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def entry_line_numbers(text: str) -> dict[str, int]:
    lines: dict[str, int] = {}
    for match in ENTRY_RE.finditer(text):
        key = match.group(2).strip()
        lines[key] = text.count("\n", 0, match.start()) + 1
    return lines


def cited_keys_from_aux(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    cited: set[str] = set()
    for match in re.finditer(r"\\citation\{([^{}]+)\}", path.read_text(encoding="utf-8", errors="ignore")):
        for item in match.group(1).split(","):
            key = item.strip()
            if key and key != "*":
                cited.add(key)
    return cited


def rendered_reference_keys_from_bbl(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="ignore")
    keys = set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^{}]+)\}", text))
    keys.update(re.findall(r"\\entry\{([^{}]+)\}", text))
    return keys


def locate_companion(path: Path, suffix: str, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    candidate = path.with_suffix(suffix)
    return candidate if candidate.exists() else None


def load_entries(tex: Path) -> tuple[str, list[Path], list[dict[str, Any]], dict[str, int], list[str]]:
    state = ExtractionState()
    if tex.suffix.lower() == ".bib":
        bib_files = [tex]
        raw_tex = ""
    else:
        chunks: list[str] = []
        for root in collect_tex_roots(tex, state):
            chunks.append(expand_inputs(root, state, root=project_root_for(tex)))
        raw_tex = "\n\n".join(chunks)
        bib_files = find_bib_files(tex, raw_tex, state)
    entries: list[dict[str, Any]] = []
    line_numbers: dict[str, int] = {}
    for bib in bib_files:
        text = read_text(bib, state)
        parsed = parse_bib_entries(text)
        local_lines = entry_line_numbers(text)
        for entry in parsed:
            entry["bib_file"] = str(bib)
            entry["line"] = local_lines.get(str(entry.get("key")), 0)
        line_numbers.update({str(key): value for key, value in local_lines.items()})
        entries.extend(parsed)
    return raw_tex, bib_files, entries, line_numbers, state.warnings


def add_finding(
    findings: list[dict[str, Any]],
    *,
    severity: str,
    title: str,
    evidence: str,
    recommendation: str,
    confidence: float,
    observation_id: str,
) -> None:
    findings.append(
        {
            "severity": severity,
            "title": title,
            "evidence": compact_text(evidence, max_chars=1400),
            "recommendation": recommendation,
            "confidence": confidence,
            "observation_id": observation_id,
        }
    )


def arxiv_year(arxiv_id: str) -> int | None:
    match = ARXIV_ID_RE.search(arxiv_id)
    if not match:
        return None
    prefix = match.group(1)[:2]
    try:
        year = int(prefix)
    except ValueError:
        return None
    return 2000 + year if year < 90 else 1900 + year


def field_year(value: Any) -> int | None:
    match = YEAR_RE.search(str(value or ""))
    return int(match.group(0)) if match else None


def audit_entries(
    entries: list[dict[str, Any]],
    *,
    cited_keys: set[str],
    rendered_keys: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    duplicate_candidates: list[dict[str, Any]] = []
    notes: list[str] = []
    if not entries:
        return findings, duplicate_candidates, ["No parseable BibTeX entries detected."]

    notes.append(f"Parsed {len(entries)} BibTeX entries.")
    if cited_keys:
        notes.append(f"Aux citation keys detected: {len(cited_keys)}.")
    if rendered_keys:
        notes.append(f"Rendered bibliography keys detected: {len(rendered_keys)}.")

    key_counts = Counter(str(entry.get("key")) for entry in entries)
    duplicate_keys = sorted(key for key, count in key_counts.items() if count > 1)
    if duplicate_keys:
        duplicate_candidates.append({"reason": "duplicate_bibtex_keys", "evidence": duplicate_keys[:20]})
        add_finding(
            findings,
            severity="high",
            title="Duplicate BibTeX keys",
            evidence=f"Duplicate keys detected: {duplicate_keys[:20]}",
            recommendation="Rename or remove duplicate BibTeX entries so citations resolve deterministically.",
            confidence=0.98,
            observation_id="reference-duplicate-keys",
        )

    title_index: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}
        title = compact_text(fields.get("title") if isinstance(fields, dict) else "")
        normalized = re.sub(r"[^a-z0-9]+", "", title.lower())
        if normalized:
            title_index[normalized].append(str(entry.get("key")))
    duplicate_titles = {title: keys for title, keys in title_index.items() if len(keys) > 1}
    if duplicate_titles:
        sample = list(duplicate_titles.values())[:8]
        duplicate_candidates.append({"reason": "duplicate_normalized_titles", "evidence": sample})
        add_finding(
            findings,
            severity="medium",
            title="Possible duplicate bibliography entries",
            evidence=f"Normalized title duplicates: {sample}",
            recommendation="Merge duplicate bibliography entries or clarify why multiple versions are intentionally cited.",
            confidence=0.82,
            observation_id="reference-duplicate-titles",
        )

    x_field_examples: list[str] = []
    x_counts: Counter[str] = Counter()
    cited_hidden = 0
    arxiv_spacing = 0
    arxiv_no_link: list[str] = []
    arxiv_year_mismatches: list[str] = []
    author_anomalies: list[str] = []
    unprotected_titles: list[str] = []
    entry_types: Counter[str] = Counter(str(entry.get("type")) for entry in entries)
    for entry in entries:
        key = str(entry.get("key"))
        line = int(entry.get("line") or 0)
        fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}
        if not isinstance(fields, dict):
            continue
        for field in sorted(set(fields) & X_METADATA_FIELDS):
            x_counts[field] += 1
            if len(x_field_examples) < 10:
                x_field_examples.append(f"{key} line {line}: {field}")
        has_hidden_metadata = bool(set(fields) & X_METADATA_FIELDS)
        has_standard_metadata = bool(set(fields) & METADATA_FIELDS)
        if has_hidden_metadata and (key in cited_keys or key in rendered_keys):
            cited_hidden += 1
        journal = compact_text(fields.get("journal"), max_chars=260)
        arxiv_match = ARXIV_RE.search(journal)
        eprint = compact_text(fields.get("eprint") or fields.get("xeprint"), max_chars=80)
        arxiv_id = arxiv_match.group(1) if arxiv_match else eprint
        if arxiv_match:
            if "arXiv: " in journal or "arxiv: " in journal:
                arxiv_spacing += 1
            if not has_standard_metadata and len(arxiv_no_link) < 10:
                arxiv_no_link.append(f"{key} line {line}: {journal}")
        arxiv_year_value = arxiv_year(arxiv_id)
        bib_year = field_year(fields.get("year"))
        if arxiv_year_value is not None and bib_year is not None and abs(arxiv_year_value - bib_year) > 1:
            if len(arxiv_year_mismatches) < 10:
                arxiv_year_mismatches.append(
                    f"{key} line {line}: arXiv {arxiv_id} implies {arxiv_year_value}, BibTeX year={bib_year}"
                )
        author = compact_text(fields.get("author"), max_chars=260)
        if AUTHOR_ANOMALY_RE.search(author):
            if len(author_anomalies) < 10:
                author_anomalies.append(f"{key} line {line}: author starts `{author[:80]}`")
        title = compact_text(fields.get("title"), max_chars=260)
        if ACRONYM_RE.search(title) and not PROTECTED_TOKEN_RE.search(title):
            if len(unprotected_titles) < 10:
                unprotected_titles.append(f"{key} line {line}: {title}")

    notes.append(f"Entry types: {dict(entry_types)}.")
    if x_counts:
        add_finding(
            findings,
            severity="high",
            title="Non-standard URL/DOI/eprint fields suppress bibliographic metadata",
            evidence=f"Found non-standard fields {dict(x_counts)}. Examples: {x_field_examples}.",
            recommendation="Rename intentional bibliographic metadata to standard fields (`url`, `doi`, `eprint`, `archivePrefix`) or document why links should be hidden.",
            confidence=0.95,
            observation_id="reference-hidden-metadata-fields",
        )
    if cited_hidden:
        add_finding(
            findings,
            severity="medium",
            title="Cited online identifiers are hidden in final references",
            evidence=f"{cited_hidden} cited/rendered entries use x-prefixed link/DOI/eprint metadata.",
            recommendation="For camera-ready bibliography, use standard `url`/`doi`/arXiv fields for cited items so identifiers render consistently.",
            confidence=0.9,
            observation_id="reference-hidden-cited-metadata",
        )
    if arxiv_spacing or arxiv_no_link:
        add_finding(
            findings,
            severity="medium",
            title="Inconsistent arXiv metadata style",
            evidence=f"{arxiv_spacing} arXiv journal strings use `arXiv: ` spacing; no-link examples: {arxiv_no_link}.",
            recommendation="Normalize arXiv entries to one style, preferably `archivePrefix={arXiv}` and `eprint={...}`.",
            confidence=0.86,
            observation_id="reference-arxiv-style",
        )
    if arxiv_year_mismatches:
        add_finding(
            findings,
            severity="medium",
            title="arXiv identifier year and BibTeX year appear inconsistent",
            evidence=f"Examples: {arxiv_year_mismatches}",
            recommendation="Verify whether these entries cite the intended arXiv version/year, then update either the arXiv identifier or the BibTeX year.",
            confidence=0.78,
            observation_id="reference-arxiv-year-mismatch",
        )
    if author_anomalies:
        add_finding(
            findings,
            severity="medium",
            title="Author-field formatting anomalies",
            evidence=f"Examples: {author_anomalies}",
            recommendation="Use BibTeX corporate author braces where needed and normalize personal-name initials.",
            confidence=0.82,
            observation_id="reference-author-format",
        )
    if unprotected_titles:
        add_finding(
            findings,
            severity="low",
            title="Acronyms and model names may be lowercased by the bibliography style",
            evidence=f"Cited title fields with unprotected acronyms/model names: {unprotected_titles}",
            recommendation="Brace important acronyms and product/model names in titles, e.g. `{LLM}`, `{RL}`, `{DeepSeek-R1}`, `{BERT}`.",
            confidence=0.88,
            observation_id="reference-unprotected-title-case",
        )

    if not duplicate_candidates:
        duplicate_candidates.append(
            {
                "reason": "no_strong_duplicate_candidate_detected",
                "evidence": "No duplicate BibTeX keys or identical normalized titles were found by local parsing.",
            }
        )
    return findings, duplicate_candidates, notes


def build_payload(tex: Path, *, aux: Path | None = None, bbl: Path | None = None) -> dict[str, Any]:
    _raw_tex, bib_files, entries, _line_numbers, warnings = load_entries(tex)
    aux_path = locate_companion(tex, ".aux", aux)
    bbl_path = locate_companion(tex, ".bbl", bbl)
    cited_keys = cited_keys_from_aux(aux_path)
    rendered_keys = rendered_reference_keys_from_bbl(bbl_path)
    findings, duplicate_candidates, notes = audit_entries(entries, cited_keys=cited_keys, rendered_keys=rendered_keys)
    uncited = max(0, len(entries) - len(cited_keys or rendered_keys)) if entries else 0
    source_artifacts = [{"path": str(tex), "hash": sha256_path(tex)}]
    for path in [*bib_files, aux_path, bbl_path]:
        if path and path.exists():
            source_artifacts.append({"path": str(path), "hash": sha256_path(path)})
    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "script_hash": sha256_path(Path(__file__).resolve()),
        "checked_source": str(tex),
        "source_artifacts": source_artifacts,
        "reference_count_estimate": {
            "bibtex_entries_in_bib_files": len(entries),
            "cited_keys_in_aux": len(cited_keys),
            "rendered_references_in_bbl": len(rendered_keys),
            "uncited_bib_entries_estimate": uncited,
        },
        "findings": findings,
        "duplicate_candidates": duplicate_candidates,
        "format_consistency_notes": notes,
        "warnings": warnings,
        "limitations": [
            "BibTeX parsing is local and conservative; complex nested BibTeX values may be summarized approximately.",
            "This checker reports reference hygiene signals, not citation relevance or factual correctness.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="LaTeX entry file or .bib file")
    parser.add_argument("--aux", type=Path, help="Optional .aux file for cited-key coverage")
    parser.add_argument("--bbl", type=Path, help="Optional .bbl file for rendered references")
    parser.add_argument("--out", type=Path, help="Write JSON to this path instead of stdout")
    args = parser.parse_args(argv)

    source = args.source.expanduser().resolve()
    if not source.exists():
        parser.error(f"source does not exist: {source}")
    try:
        payload = build_payload(source, aux=args.aux, bbl=args.bbl)
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
