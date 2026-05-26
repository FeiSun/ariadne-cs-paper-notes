#!/usr/bin/env python3
"""Audit source hygiene, anonymity, and submission-readiness signals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_paper_text import (  # noqa: E402
    ABS_PATH_RE,
    ACK_RE,
    AFFILIATION_RE,
    ANON_SWITCH_RE,
    AUTHOR_RE,
    CAMERA_READY_TEXT_RE,
    EMAIL_RE,
    GITHUB_RE,
    ORCID_RE,
    PLACEHOLDER_RE,
    THANKS_RE,
    TODO_RE,
    ExtractionState,
    collect_tex_roots,
    command_payloads,
    expand_inputs,
    latex_to_plain,
    one_line,
    project_root_for,
    signal_line_items,
)


TOOL_NAME = "scripts/check_source_hygiene.py"
TOOL_VERSION = "1"
ACL_REVIEW_PACKAGE_RE = re.compile(r"\\usepackage\s*\[[^\]]*\breview\b[^\]]*\]\s*\{[^}]*\bacl\b[^}]*\}", re.IGNORECASE)
PDF_TEXT_TIMEOUT_SECONDS = 60
ANONYMOUS_VISIBLE_RE = re.compile(
    r"\bAnonymous(?:\s+(?:ACL|ARR|EMNLP|NeurIPS|ICLR|ICML|submission|authors?|paper|manuscript)){0,4}\b|"
    r"\bsubmitted\s+anonymously\b|\banonymous\s+submission\b|\banonymous\s+authors?\b",
    re.IGNORECASE,
)
GENERIC_FRONT_MATTER_TERMS = {
    "affiliation",
    "address",
    "anonymous",
    "author",
    "authors",
    "department",
    "domain",
    "email",
    "institution",
    "institute",
    "laboratory",
    "school",
    "submission",
    "university",
}


def has_acl_review_mode(raw: str) -> bool:
    return bool(ACL_REVIEW_PACKAGE_RE.search(raw))


def normalize_visible_text(value: str) -> str:
    value = re.sub(r"https?://\S+", " ", value or "")
    value = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[^A-Za-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def identity_fragments(values: list[str], *, max_items: int = 100) -> list[str]:
    fragments: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = re.sub(r"\\(?:and|And|AND)\b", "\n", value)
        for fragment in re.split(r"\\\\|\n|;|\s{2,}|\band\b", value):
            text = one_line(fragment)
            normalized = normalize_visible_text(text)
            if len(normalized) < 5 or not re.search(r"[a-z]", normalized):
                continue
            tokens = normalized.split()
            if len(tokens) == 1 and (len(tokens[0]) < 5 or tokens[0] in GENERIC_FRONT_MATTER_TERMS):
                continue
            if all(token in GENERIC_FRONT_MATTER_TERMS for token in tokens):
                continue
            if normalized not in seen:
                fragments.append(text)
                seen.add(normalized)
            if len(fragments) >= max_items:
                return fragments
    return fragments


def text_contains_identity_fragment(text: str, fragment: str) -> bool:
    haystack = normalize_visible_text(text)
    needle = normalize_visible_text(fragment)
    return bool(needle and needle in haystack)


def visible_front_matter_fragments(compiled_text: str, authors: list[str], affiliations: list[str], *, max_items: int) -> list[str]:
    visible: list[str] = []
    for fragment in identity_fragments(authors + affiliations, max_items=max_items):
        if text_contains_identity_fragment(compiled_text, fragment):
            visible.append(fragment)
        if len(visible) >= max_items:
            break
    return visible


def extract_pdf_text(pdf: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            result = subprocess.run(
                [pdftotext, "-layout", str(pdf), "-"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=PDF_TEXT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            warnings.append(f"pdftotext timed out after {PDF_TEXT_TIMEOUT_SECONDS}s; PDF visibility check skipped.")
        else:
            if result.stderr.strip():
                warnings.append("pdftotext warning: " + result.stderr.strip().splitlines()[0][:300])
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout, warnings
            warnings.append(f"pdftotext failed with exit code {result.returncode}; trying pdfplumber.")
    try:
        import pdfplumber  # type: ignore
    except Exception:
        warnings.append("pdfplumber is unavailable; PDF visibility check skipped.")
        return "", warnings
    try:
        with pdfplumber.open(pdf) as handle:
            return "\n".join(page.extract_text() or "" for page in handle.pages), warnings
    except Exception as exc:
        warnings.append(f"pdfplumber failed during PDF visibility check: {exc}")
        return "", warnings


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


def add_observation(
    observations: list[dict[str, Any]],
    *,
    issue_type: str,
    severity: str,
    title: str,
    evidence: str,
    recommendation: str,
    confidence: float,
    visibility_basis: str = "source_only",
) -> None:
    observations.append(
        {
            "observation_id": f"source-{len(observations) + 1:03d}",
            "issue_type": issue_type,
            "severity": severity,
            "title": title,
            "evidence": compact_text(evidence, max_chars=1200),
            "recommendation": recommendation,
            "confidence": confidence,
            "visibility_basis": visibility_basis,
        }
    )


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


def audit_source(
    raw: str,
    text: str,
    *,
    max_items: int = 100,
    compiled_text: str = "",
    compiled_source: str = "",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    observations: list[dict[str, Any]] = []
    acl_review_mode = has_acl_review_mode(raw)
    placeholders = signal_line_items(PLACEHOLDER_RE, raw)
    todos = [(raw.count("\n", 0, match.start()) + 1, compact_text(match.group(0), max_chars=240)) for match in TODO_RE.finditer(raw)]
    authors = command_payloads(AUTHOR_RE, raw, max_items)
    affiliations = command_payloads(AFFILIATION_RE, raw, max_items)
    front_matter_identity_text = "\n".join(authors + affiliations)
    identity_search_text = raw + "\n" + text
    emails_all = set(EMAIL_RE.findall(identity_search_text))
    compiled_text_available = bool(compiled_text.strip())
    compiled_has_anonymous_front_matter = bool(compiled_text_available and ANONYMOUS_VISIBLE_RE.search(compiled_text[:4000]))
    compiled_front_matter_visible = (
        visible_front_matter_fragments(compiled_text, authors, affiliations, max_items=max_items)
        if compiled_text_available
        else []
    )
    suppress_source_front_matter = compiled_text_available and not compiled_front_matter_visible
    if suppress_source_front_matter or acl_review_mode:
        emails_all = {item for item in emails_all if item not in front_matter_identity_text}
    emails = sorted(emails_all)
    githubs = sorted(set(GITHUB_RE.findall(identity_search_text)))
    abs_paths = sorted(set(ABS_PATH_RE.findall(identity_search_text)))
    thanks = [one_line(match.group(1)) for match in THANKS_RE.finditer(raw)]
    orcids = sorted(set(ORCID_RE.findall(raw + "\n" + text)))
    anon_switches = sorted(set(match.group(1) for match in ANON_SWITCH_RE.finditer(raw + "\n" + text)))
    camera_ready_mentions = sorted(set(match.group(0) for match in CAMERA_READY_TEXT_RE.finditer(raw + "\n" + text)))
    has_ack = bool(ACK_RE.search(raw) or re.search(r"\bAcknowledg(?:e)?ments?\b", text, re.IGNORECASE))

    if placeholders:
        preview = "; ".join(f"line {line}: {item}" for line, item in placeholders[:max_items])
        add_observation(
            observations,
            issue_type="placeholder",
            severity="high",
            title="Placeholder or broken-reference markers remain in the source",
            evidence=preview,
            recommendation="Resolve `??`, placeholder citations, and broken refs before review submission.",
            confidence=0.96,
        )
    if todos:
        preview = "; ".join(f"line {line}: {todo}" for line, todo in todos[:max_items])
        add_observation(
            observations,
            issue_type="todo_marker",
            severity="high",
            title="TODO/TBD/FIXME markers remain in the source",
            evidence=preview,
            recommendation="Remove or resolve draft TODO/TBD/FIXME markers before submission.",
            confidence=0.95,
        )

    identity_parts: list[str] = []
    identity_parts.extend(f"email: {item}" for item in emails[:max_items])
    identity_parts.extend(f"github: {item}" for item in githubs[:max_items])
    if compiled_text_available:
        identity_parts.extend(f"compiled front matter: {item[:240]}" for item in compiled_front_matter_visible[:max_items])
    elif not acl_review_mode:
        identity_parts.extend(f"author command: {item[:240]}" for item in authors[:max_items])
        identity_parts.extend(f"affiliation/institute command: {item[:240]}" for item in affiliations[:max_items])
    identity_parts.extend(f"thanks: {item[:240]}" for item in thanks[:max_items])
    identity_parts.extend(f"ORCID: {item}" for item in orcids[:max_items])
    if has_ack:
        identity_parts.append("acknowledgments section/header detected")
    if identity_parts:
        add_observation(
            observations,
            issue_type="anonymity",
            severity="high",
            title=(
                "Compiled submission still exposes identity/anonymity signals"
                if compiled_front_matter_visible
                else "Review-mode source still contains non-front-matter identity signals"
                if suppress_source_front_matter or acl_review_mode
                else "Identity/anonymity signals are visible in the source"
            ),
            evidence="; ".join(identity_parts[:max_items]),
            recommendation=(
                "Use the compiled PDF as the source of truth for double-blind checks; remove any identity text that is visible in the PDF and separately verify repository links, acknowledgments, thanks, ORCID, and other metadata."
                if compiled_text_available
                else "Review mode appears to anonymize the compiled front matter; separately verify repository links, acknowledgments, thanks, ORCID, and other non-front-matter metadata."
                if acl_review_mode
                else "For double-blind submission, remove or anonymize visible author, affiliation, email, ORCID, thanks, acknowledgment, and repository identity signals."
            ),
            confidence=0.92 if compiled_front_matter_visible else 0.82 if (compiled_text_available or acl_review_mode) else 0.94,
            visibility_basis="compiled_pdf" if compiled_front_matter_visible else "source_only",
        )

    if anon_switches:
        add_observation(
            observations,
            issue_type="anonymous_switch",
            severity="high",
            title="Final/non-anonymous template switch is present",
            evidence="; ".join(f"anonymous/final switch: {item}" for item in anon_switches[:max_items]),
            recommendation="Verify the venue mode. For double-blind review, use anonymous review mode rather than final/camera-ready switches.",
            confidence=0.9,
        )
    if abs_paths:
        add_observation(
            observations,
            issue_type="local_path",
            severity="medium",
            title="Local absolute paths appear in source or extracted text",
            evidence="; ".join(abs_paths[:max_items]),
            recommendation="Remove local machine paths from source, comments, logs, or visible text.",
            confidence=0.88,
        )
    if camera_ready_mentions:
        add_observation(
            observations,
            issue_type="camera_ready_text",
            severity="low",
            title="Camera-ready wording appears in source/text",
            evidence="; ".join(camera_ready_mentions[:max_items]),
            recommendation="Check whether camera-ready wording is historical context or accidental submission-mode text.",
            confidence=0.72,
        )

    coverage = {
        "placeholders": len(placeholders),
        "todos": len(todos),
        "identity_items": len(identity_parts),
        "compiled_visibility_checked": int(compiled_text_available),
        "compiled_front_matter_identity_items": len(compiled_front_matter_visible),
        "compiled_anonymous_front_matter": int(compiled_has_anonymous_front_matter),
        "anonymous_switches": len(anon_switches),
        "local_paths": len(abs_paths),
        "camera_ready_mentions": len(camera_ready_mentions),
        "acl_review_mode": int(acl_review_mode),
        "front_matter_identity_items_suppressed": len(authors) + len(affiliations) if suppress_source_front_matter or acl_review_mode else 0,
    }
    if compiled_source:
        coverage["compiled_source"] = 1
    return observations, coverage


def build_payload(source: Path, *, max_items: int = 100, pdf: Path | None = None) -> dict[str, Any]:
    raw, text, tex_roots, warnings = load_source(source)
    compiled_text = ""
    compiled_source = ""
    if pdf is not None and pdf.exists():
        compiled_source = str(pdf)
        extracted, pdf_warnings = extract_pdf_text(pdf)
        compiled_text = extracted
        warnings.extend(pdf_warnings)
    observations, coverage = audit_source(
        raw,
        text,
        max_items=max_items,
        compiled_text=compiled_text,
        compiled_source=compiled_source,
    )
    source_artifacts = [{"path": str(path), "hash": sha256_path(path)} for path in tex_roots if path.exists()]
    if source not in tex_roots and source.exists():
        source_artifacts.insert(0, {"path": str(source), "hash": sha256_path(source)})
    if pdf is not None and pdf.exists():
        source_artifacts.append({"path": str(pdf), "hash": sha256_path(pdf), "context_policy": "compiled_visibility_source"})
    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "script_hash": sha256_path(Path(__file__).resolve()),
        "checked_source": str(source),
        "checked_pdf": str(pdf) if pdf is not None else "",
        "source_artifacts": source_artifacts,
        "coverage": coverage,
        "observations": observations,
        "warnings": warnings,
        "limitations": [
            "Identity/anonymity checks surface visible source/text signals; they do not prove the authors' real identity.",
            "Venue compliance cannot be fully verified without the target venue's current rules.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="LaTeX entry file or project directory")
    parser.add_argument("--pdf", type=Path, help="Compiled PDF used as the source of truth for visible anonymity checks")
    parser.add_argument("--out", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--max-items", type=int, default=100)
    args = parser.parse_args(argv)

    source = args.source.expanduser().resolve()
    if not source.exists():
        parser.error(f"source does not exist: {source}")
    pdf = args.pdf.expanduser().resolve() if args.pdf else None
    if pdf is not None and not pdf.exists():
        parser.error(f"PDF does not exist: {pdf}")
    try:
        payload = build_payload(source, max_items=args.max_items, pdf=pdf)
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
