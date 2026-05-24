#!/usr/bin/env python3
"""Build compact Phase B synthesis context from Ariadne phase/issue artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CONTEXT_POLICY = "model_readable_compact_synthesis_input"
DEFAULT_MAX_SECTIONS = 80
DEFAULT_MAX_CLAIMS = 120
DEFAULT_MAX_ISSUES = 240
DEFAULT_MAX_TEXT_CHARS = 420
PROSE_DOMAINS = {"prose", "whole_paper"}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_text(value: Any, *, max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def first_nonempty(mapping: dict[str, Any], keys: tuple[str, ...], *, max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = "; ".join(compact_text(item, max_chars=max_chars) for item in value if compact_text(item))
        text = compact_text(value, max_chars=max_chars)
        if text:
            return text
    return ""


def stable_id(text: str, prefix: str = "section") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or prefix


def as_list(payload: Any, preferred_keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        keyed_items = []
        for key, value in payload.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("section_id", key)
                keyed_items.append(item)
        if keyed_items:
            return keyed_items
    return []


def normalize_id_list(value: Any, *, max_items: int = 8) -> list[str]:
    if value is None:
        return []
    values: list[Any]
    if isinstance(value, list):
        values = value
    elif isinstance(value, tuple):
        values = list(value)
    else:
        values = [value]
    ids: list[str] = []
    for item in values:
        if isinstance(item, dict):
            text = first_nonempty(item, ("id", "local_id", "issue_id", "finding_id", "claim_id"))
        else:
            text = compact_text(item, max_chars=80)
        if text and text not in ids:
            ids.append(text)
        if len(ids) >= max_items:
            break
    return ids


def normalize_cold_skim(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "problem": "",
            "gap": "",
            "idea": "",
            "evidence": "",
            "boundary": "",
            "first_reader_breaks": [],
        }
    return {
        "problem": first_nonempty(payload, ("problem", "what_problem", "paper_problem")),
        "gap": first_nonempty(payload, ("gap", "missing_gap", "research_gap")),
        "idea": first_nonempty(payload, ("idea", "approach", "core_idea", "method")),
        "evidence": first_nonempty(payload, ("evidence", "visible_evidence", "main_evidence")),
        "boundary": first_nonempty(payload, ("boundary", "scope", "limitation", "limits")),
        "first_reader_breaks": normalize_id_list(
            payload.get("first_reader_breaks")
            or payload.get("reader_breaks")
            or payload.get("what_tripped_me")
            or payload.get("breaks"),
            max_items=12,
        ),
    }


def normalize_section_reflections(payload: Any, *, max_sections: int, max_chars: int) -> list[dict[str, Any]]:
    items = as_list(payload, ("sections", "section_reflections", "reflections"))
    sections: list[dict[str, Any]] = []
    for idx, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            continue
        title = first_nonempty(raw, ("title", "section_title", "section", "heading"), max_chars=160)
        section_id = first_nonempty(raw, ("section_id", "id", "anchor", "slug"), max_chars=120)
        if not section_id:
            section_id = stable_id(title or f"section-{idx}")
        one_line = first_nonempty(
            raw,
            (
                "one_line",
                "one_line_summary",
                "summary",
                "section_summary",
                "read_after_one_sentence",
                "读后一句话",
                "observation",
                "reflection",
            ),
            max_chars=max_chars,
        )
        role = first_nonempty(
            raw,
            (
                "role_in_argument",
                "section_job",
                "job",
                "task_alignment",
                "章节任务是否对齐",
            ),
            max_chars=max_chars,
        )
        top_ids = (
            raw.get("top_issue_ids")
            or raw.get("linked_issue_ids")
            or raw.get("linked_findings")
            or raw.get("issue_ids")
            or raw.get("关联问题")
        )
        sections.append(
            {
                "section_id": section_id,
                "title": title or section_id,
                "one_line": one_line,
                "role_in_argument": role,
                "top_issue_ids": normalize_id_list(top_ids),
            }
        )
        if len(sections) >= max_sections:
            break
    return sections


def normalize_claim_candidates(payload: Any, *, max_claims: int, max_chars: int) -> list[dict[str, Any]]:
    items = as_list(payload, ("claim_candidates", "claims", "items"))
    claims: list[dict[str, Any]] = []
    for idx, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            continue
        claim_id = first_nonempty(raw, ("id", "claim_id", "local_id"), max_chars=80) or f"C{idx}"
        text = first_nonempty(raw, ("text", "claim_text", "claim", "promise"), max_chars=max_chars)
        if not text:
            continue
        claims.append(
            {
                "id": claim_id,
                "text": text,
                "location": first_nonempty(raw, ("location", "anchor", "section", "source"), max_chars=180),
                "strength": first_nonempty(raw, ("strength", "claim_strength", "status"), max_chars=120),
                "claim_type": first_nonempty(raw, ("claim_type", "type"), max_chars=120),
                "source_issue_ids": normalize_id_list(raw.get("source_issue_ids") or raw.get("linked_issue_ids") or raw.get("linked_findings")),
            }
        )
        if len(claims) >= max_claims:
            break
    return claims


def normalize_cross_section_terms(*payloads: Any, max_chars: int) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        raw_terms = payload.get("cross_section_terms") or payload.get("terms") or payload.get("term_signals")
        if not isinstance(raw_terms, list):
            continue
        for raw in raw_terms:
            if not isinstance(raw, dict):
                continue
            term = first_nonempty(raw, ("term", "symbol", "name"), max_chars=80)
            if not term:
                continue
            definitions = []
            raw_defs = raw.get("definitions") or raw.get("uses") or raw.get("locations") or []
            if isinstance(raw_defs, list):
                for item in raw_defs[:8]:
                    if isinstance(item, dict):
                        definitions.append(
                            {
                                "section_id": first_nonempty(item, ("section_id", "section", "location"), max_chars=120),
                                "anchor": first_nonempty(item, ("anchor", "sentence_id", "paragraph_id"), max_chars=160),
                                "meaning": first_nonempty(item, ("meaning", "definition", "value", "text"), max_chars=max_chars),
                            }
                        )
                    else:
                        definitions.append({"section_id": "", "anchor": "", "meaning": compact_text(item, max_chars=max_chars)})
            terms.append(
                {
                    "term": term,
                    "definitions": definitions,
                    "issue_ids": normalize_id_list(raw.get("issue_ids") or raw.get("linked_issue_ids") or raw.get("source_issue_ids")),
                }
            )
    return terms


def issue_artifact_paths(issues_dir: Path | None, explicit_paths: list[Path]) -> list[Path]:
    paths: list[Path] = []
    if issues_dir is not None and issues_dir.exists():
        paths.extend(sorted(issues_dir.glob("*_issues.json")))
    paths.extend(explicit_paths)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen and path.exists():
            unique.append(path)
            seen.add(resolved)
    return unique


def normalize_issue_artifacts(paths: list[Path], *, max_issues: int, max_chars: int) -> tuple[list[dict[str, Any]], set[str]]:
    compact_issues: list[dict[str, Any]] = []
    domains: set[str] = set()
    for path in paths:
        try:
            payload = load_json(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        domain = compact_text(payload.get("domain") or path.stem.replace("_issues", ""), max_chars=80)
        if domain:
            domains.add(domain)
        if domain in PROSE_DOMAINS:
            continue
        issues = payload.get("issues")
        if not isinstance(issues, list):
            continue
        for raw in issues:
            if not isinstance(raw, dict):
                continue
            local_id = first_nonempty(raw, ("local_id", "id", "issue_id"), max_chars=80)
            title = first_nonempty(raw, ("title", "short", "summary", "diagnosis"), max_chars=220)
            if not local_id or not title:
                continue
            render_hint = raw.get("render_hint") if isinstance(raw.get("render_hint"), dict) else {}
            anchor = first_nonempty(
                render_hint,
                ("anchor", "target", "display_anchor"),
                max_chars=160,
            ) or first_nonempty(raw, ("primary_anchor", "anchor", "location", "page"), max_chars=160)
            compact_issues.append(
                {
                    "domain": domain,
                    "local_id": local_id,
                    "severity": first_nonempty(raw, ("severity",), max_chars=80),
                    "issue_type": first_nonempty(raw, ("issue_type", "type"), max_chars=100),
                    "title": title,
                    "anchor": anchor,
                    "source_artifact": str(path),
                }
            )
            if len(compact_issues) >= max_issues:
                return compact_issues, domains
    return compact_issues, domains


def source_artifact_record(path: Path, *, context_policy: str | None = None) -> dict[str, str]:
    record = {"path": str(path), "hash": sha256_path(path)}
    if context_policy:
        record["context_policy"] = context_policy
    return record


def build_phase_b_context(
    *,
    cold_skim_path: Path,
    section_reflections_path: Path,
    claim_candidates_path: Path,
    issues_dir: Path | None,
    issue_artifacts: list[Path],
    max_sections: int = DEFAULT_MAX_SECTIONS,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    max_issues: int = DEFAULT_MAX_ISSUES,
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
) -> dict[str, Any]:
    cold_payload = load_json(cold_skim_path)
    section_payload = load_json(section_reflections_path)
    claim_payload = load_json(claim_candidates_path)
    issue_paths = issue_artifact_paths(issues_dir, issue_artifacts)

    compact_issues, domains = normalize_issue_artifacts(issue_paths, max_issues=max_issues, max_chars=max_text_chars)
    source_artifacts = [
        source_artifact_record(cold_skim_path),
        source_artifact_record(section_reflections_path),
        source_artifact_record(claim_candidates_path),
    ]
    source_artifacts.extend(source_artifact_record(path, context_policy="model_readable_issue_only") for path in issue_paths)

    section_summaries = normalize_section_reflections(section_payload, max_sections=max_sections, max_chars=max_text_chars)
    claim_candidates = normalize_claim_candidates(claim_payload, max_claims=max_claims, max_chars=max_text_chars)
    cross_section_terms = normalize_cross_section_terms(section_payload, claim_payload, max_chars=max_text_chars)

    return {
        "schema_version": SCHEMA_VERSION,
        "context_policy": CONTEXT_POLICY,
        "source_artifacts": source_artifacts,
        "cold_skim": normalize_cold_skim(cold_payload),
        "section_summaries": section_summaries,
        "claim_candidates": claim_candidates,
        "cross_section_terms": cross_section_terms,
        "specialist_issues_compact": compact_issues,
        "coverage": {
            "sections_summarized": len(section_summaries),
            "specialist_domains": len(domains - PROSE_DOMAINS),
            "issue_count": len(compact_issues),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cold-skim", required=True, type=Path, help="Path to cold_skim_frame.json")
    parser.add_argument("--section-reflections", required=True, type=Path, help="Path to section_reflections.json")
    parser.add_argument("--claim-candidates", required=True, type=Path, help="Path to claim_candidates.json")
    parser.add_argument("--issues-dir", type=Path, help="Directory containing specialist *_issues.json artifacts")
    parser.add_argument("--issue-artifact", action="append", type=Path, default=[], help="Additional *_issues.json artifact path")
    parser.add_argument("--out", required=True, type=Path, help="Output phase_b_context.json path")
    parser.add_argument("--max-sections", type=int, default=DEFAULT_MAX_SECTIONS)
    parser.add_argument("--max-claims", type=int, default=DEFAULT_MAX_CLAIMS)
    parser.add_argument("--max-issues", type=int, default=DEFAULT_MAX_ISSUES)
    parser.add_argument("--max-text-chars", type=int, default=DEFAULT_MAX_TEXT_CHARS)
    args = parser.parse_args(argv)

    try:
        context = build_phase_b_context(
            cold_skim_path=args.cold_skim,
            section_reflections_path=args.section_reflections,
            claim_candidates_path=args.claim_candidates,
            issues_dir=args.issues_dir,
            issue_artifacts=args.issue_artifact,
            max_sections=args.max_sections,
            max_claims=args.max_claims,
            max_issues=args.max_issues,
            max_text_chars=args.max_text_chars,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "Wrote phase_b_context: "
        f"sections={context['coverage']['sections_summarized']} "
        f"domains={context['coverage']['specialist_domains']} "
        f"issues={context['coverage']['issue_count']} "
        f"to {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
