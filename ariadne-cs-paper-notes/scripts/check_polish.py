#!/usr/bin/env python3
"""Audit mechanical polish and consistency signals in LaTeX source."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_paper_text import (  # noqa: E402
    ExtractionState,
    collect_tex_roots,
    expand_inputs,
    latex_to_plain,
    project_root_for,
)


TOOL_NAME = "scripts/check_polish.py"
TOOL_VERSION = "1"

REPEATED_WORD_RE = re.compile(r"\b([A-Za-z][A-Za-z'-]{1,})\s+\1\b", re.IGNORECASE)
ET_AL_MISSING_DOT_RE = re.compile(r"\bet\s+al(?!\.)\b", re.IGNORECASE)
LATIN_ABBREV_MISSING_DOT_RE = re.compile(r"\b(?:e\.g|i\.e|eg|ie)(?!\.)\b", re.IGNORECASE)
UNICODE_PUNCT_RE = re.compile("[\u2018\u2019\u201c\u201d\u2013\u2014\u00a0]")
BREAKABLE_REF_SPACE_RE = re.compile(
    r"\b(?:Figure|Fig\.|Table|Section|Sec\.|Equation|Eq\.)\s+\\(?:ref|cref|Cref|autoref|eqref)\{"
)

HYPHENATION_GROUPS: dict[str, dict[str, str]] = {
    "fine-tuning": {
        "fine-tuning": r"\bfine-tun(?:e|ed|es|ing)\b",
        "fine tuning": r"\bfine tun(?:e|ed|es|ing)\b",
        "finetuning": r"\bfinetun(?:e|ed|es|ing)\b",
    },
    "pre-trained": {
        "pre-trained": r"\bpre-train(?:ed|ing)?\b",
        "pre trained": r"\bpre train(?:ed|ing)?\b",
        "pretrained": r"\bpretrain(?:ed|ing)?\b",
    },
    "zero-shot": {
        "zero-shot": r"\bzero-shot\b",
        "zero shot": r"\bzero shot\b",
        "zeroshot": r"\bzeroshot\b",
    },
    "few-shot": {
        "few-shot": r"\bfew-shot\b",
        "few shot": r"\bfew shot\b",
        "fewshot": r"\bfewshot\b",
    },
    "multi-agent": {
        "multi-agent": r"\bmulti-agent\b",
        "multi agent": r"\bmulti agent\b",
        "multiagent": r"\bmultiagent\b",
    },
}

SPELLING_GROUPS: dict[str, dict[str, str]] = {
    "behavior": {"behavior": r"\bbehavior(?:al)?\b", "behaviour": r"\bbehaviour(?:al)?\b"},
    "optimization": {"optimization": r"\boptimiz(?:ation|e|ed|ing)\b", "optimisation": r"\boptimis(?:ation|e|ed|ing)\b"},
    "modeling": {"modeling": r"\bmodeling\b", "modelling": r"\bmodelling\b"},
    "generalization": {"generalization": r"\bgeneraliz(?:ation|e|ed|ing)\b", "generalisation": r"\bgeneralis(?:ation|e|ed|ing)\b"},
}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def compact_text(value: Any, *, max_chars: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def snippet_around(text: str, start: int, end: int, *, window: int = 90) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    return compact_text(text[left:right], max_chars=240)


def line_matches(pattern: re.Pattern[str], text: str, *, max_items: int) -> list[str]:
    items: list[str] = []
    for match in pattern.finditer(text):
        items.append(f"line {line_number(text, match.start())}: {snippet_around(text, match.start(), match.end())}")
        if len(items) >= max_items:
            break
    return items


def add_observation(
    observations: list[dict[str, Any]],
    *,
    issue_type: str,
    severity: str,
    title: str,
    evidence: str,
    recommendation: str,
    confidence: float,
    examples: list[str] | None = None,
) -> None:
    observation: dict[str, Any] = {
        "observation_id": f"polish-{len(observations) + 1:03d}",
        "issue_type": issue_type,
        "severity": severity,
        "title": title,
        "evidence": compact_text(evidence, max_chars=1400),
        "recommendation": recommendation,
        "confidence": confidence,
    }
    if examples:
        observation["examples"] = examples
    observations.append(observation)


def load_source(source: Path) -> tuple[str, str, list[Path], list[str]]:
    state = ExtractionState()
    tex_roots = collect_tex_roots(source, state) if source.suffix.lower() == ".tex" or source.is_dir() else [source]
    raw_chunks: list[str] = []
    plain_chunks: list[str] = []
    root = project_root_for(source)
    for path in tex_roots:
        raw = expand_inputs(path, state, root=root) if path.suffix.lower() == ".tex" else path.read_text(encoding="utf-8", errors="replace")
        raw_chunks.append(raw)
        plain_chunks.append(latex_to_plain(raw, state))
    return "\n\n".join(raw_chunks), "\n\n".join(plain_chunks), tex_roots, state.warnings


def count_variants(text: str, variants: dict[str, str]) -> dict[str, int]:
    lower = text.lower()
    counts: dict[str, int] = {}
    for label, pattern in variants.items():
        count = len(re.findall(pattern, lower, flags=re.IGNORECASE))
        if count:
            counts[label] = count
    return counts


def variant_evidence(name: str, counts: dict[str, int]) -> str:
    rendered = ", ".join(f"{variant}={count}" for variant, count in sorted(counts.items()))
    return f"{name}: {rendered}"


def audit_polish(raw: str, text: str, *, max_items: int = 80) -> tuple[list[dict[str, Any]], dict[str, int]]:
    observations: list[dict[str, Any]] = []
    repeated_words = line_matches(REPEATED_WORD_RE, text, max_items=max_items)
    et_al = line_matches(ET_AL_MISSING_DOT_RE, text, max_items=max_items)
    latin_abbrev = line_matches(LATIN_ABBREV_MISSING_DOT_RE, text, max_items=max_items)
    unicode_punctuation = line_matches(UNICODE_PUNCT_RE, raw, max_items=max_items)
    breakable_refs = line_matches(BREAKABLE_REF_SPACE_RE, raw, max_items=max_items)

    hyphenation_groups: list[str] = []
    for name, variants in HYPHENATION_GROUPS.items():
        counts = count_variants(text, variants)
        if len(counts) > 1:
            hyphenation_groups.append(variant_evidence(name, counts))

    spelling_groups: list[str] = []
    for name, variants in SPELLING_GROUPS.items():
        counts = count_variants(text, variants)
        if len(counts) > 1:
            spelling_groups.append(variant_evidence(name, counts))

    if repeated_words:
        add_observation(
            observations,
            issue_type="repeated_word",
            severity="medium",
            title="Repeated adjacent words appear in the extracted prose",
            evidence="; ".join(repeated_words),
            recommendation="Inspect the listed repeated-word candidates and remove accidental duplicates.",
            confidence=0.86,
            examples=repeated_words,
        )
    if et_al:
        add_observation(
            observations,
            issue_type="latin_abbreviation",
            severity="low",
            title="`et al.` appears without the final period",
            evidence="; ".join(et_al),
            recommendation="Use `et al.` consistently unless the venue style explicitly says otherwise.",
            confidence=0.9,
            examples=et_al,
        )
    if latin_abbrev:
        add_observation(
            observations,
            issue_type="latin_abbreviation",
            severity="low",
            title="Latin abbreviations have inconsistent or missing periods",
            evidence="; ".join(latin_abbrev),
            recommendation="Use `e.g.` and `i.e.` consistently, or follow the venue's house style.",
            confidence=0.78,
            examples=latin_abbrev,
        )
    if hyphenation_groups:
        add_observation(
            observations,
            issue_type="hyphenation_consistency",
            severity="low",
            title="Hyphenation variants are used for the same term family",
            evidence="; ".join(hyphenation_groups[:max_items]),
            recommendation="Choose one spelling/hyphenation form for each term family and apply it consistently.",
            confidence=0.82,
            examples=hyphenation_groups[:max_items],
        )
    if spelling_groups:
        add_observation(
            observations,
            issue_type="spelling_consistency",
            severity="low",
            title="US/UK spelling variants are mixed",
            evidence="; ".join(spelling_groups[:max_items]),
            recommendation="Choose one spelling convention and normalize the manuscript unless variants are quoted names.",
            confidence=0.72,
            examples=spelling_groups[:max_items],
        )
    if unicode_punctuation:
        add_observation(
            observations,
            issue_type="unicode_punctuation",
            severity="low",
            title="Unicode punctuation appears in LaTeX source",
            evidence="; ".join(unicode_punctuation),
            recommendation="Replace smart quotes, nonbreaking spaces, and long dashes with explicit LaTeX forms if the build or venue style requires ASCII-safe source.",
            confidence=0.8,
            examples=unicode_punctuation,
        )
    if breakable_refs:
        add_observation(
            observations,
            issue_type="reference_spacing",
            severity="low",
            title="Breakable spaces appear before LaTeX reference commands",
            evidence="; ".join(breakable_refs),
            recommendation="Use nonbreaking spaces such as `Figure~\\ref{...}` where a label and number should stay together.",
            confidence=0.74,
            examples=breakable_refs,
        )

    coverage = {
        "words_checked": len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", text)),
        "repeated_word_candidates": len(repeated_words),
        "et_al_missing_period": len(et_al),
        "latin_abbreviation_candidates": len(latin_abbrev),
        "hyphenation_variant_groups": len(hyphenation_groups),
        "spelling_variant_groups": len(spelling_groups),
        "unicode_punctuation_items": len(unicode_punctuation),
        "breakable_ref_spacing": len(breakable_refs),
    }
    coverage["signals_checked"] = sum(value for key, value in coverage.items() if key != "words_checked")
    return observations, coverage


def build_payload(source: Path, *, max_items: int = 80) -> dict[str, Any]:
    raw, text, tex_roots, warnings = load_source(source)
    observations, coverage = audit_polish(raw, text, max_items=max_items)
    source_artifacts = [{"path": str(path), "hash": sha256_path(path)} for path in tex_roots if path.exists()]
    if source not in tex_roots and source.exists():
        source_artifacts.insert(0, {"path": str(source), "hash": sha256_path(source)})
    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "script_hash": sha256_path(Path(__file__).resolve()),
        "checked_source": str(source),
        "source_artifacts": source_artifacts,
        "coverage": coverage,
        "observations": observations,
        "warnings": warnings,
        "limitations": [
            "Polish checks are grouped mechanical signals; they are not a substitute for sentence-level prose review.",
            "Some style choices are venue-dependent, so low-severity findings may be intentionally acceptable.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="LaTeX entry file or project directory")
    parser.add_argument("--out", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--max-items", type=int, default=80)
    args = parser.parse_args(argv)

    source = args.source.expanduser().resolve()
    if not source.exists():
        parser.error(f"source does not exist: {source}")
    try:
        payload = build_payload(source, max_items=args.max_items)
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
