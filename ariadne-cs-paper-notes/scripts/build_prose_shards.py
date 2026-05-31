#!/usr/bin/env python3
"""Build section-sharded Prose Phase A packets for oversized review units."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prose_rule_refs import SHARD_BASE_PHASE_A_RULES, shard_rule_refs, sha256_path  # noqa: E402
from review_language_contract import CHINESE_OUTPUT_INSTRUCTIONS, TEACHING_FIELDS  # noqa: E402


PROSE_ISSUE_MINIMUM_FIELDS = [
    "local_id",
    "severity",
    "issue_type",
    "title",
    "diagnosis",
    "reader_friction",
    "writing_principle",
    "self_check",
    "confidence",
    "evidence_refs",
    "severity_rationale",
    "downgrade_condition",
    "target_anchors",
    "section_id",
]


def compact_text(value: Any, *, max_chars: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {line_no} invalid JSON: {exc}") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def section_rows(review_units_jsonl: Path) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(review_units_jsonl):
        if row.get("kind") == "section":
            section_id = compact_text(row.get("section_id") or row.get("id"))
            if section_id and section_id not in by_id:
                record = {
                    "section_id": section_id,
                    "title": compact_text(row.get("text") or row.get("title") or section_id),
                    "paragraphs": 0,
                    "sentences": 0,
                    "char_estimate": len(str(row.get("text") or "")),
                }
                sections.append(record)
                by_id[section_id] = record
            continue
        if row.get("kind") == "paragraph":
            section_id = compact_text(row.get("section_id") or "front-matter")
            record = by_id.get(section_id)
            if record is None:
                record = {
                    "section_id": section_id,
                    "title": compact_text(row.get("section_title") or section_id),
                    "paragraphs": 0,
                    "sentences": 0,
                    "char_estimate": 0,
                }
                sections.append(record)
                by_id[section_id] = record
            sentences = row.get("sentences")
            sentence_count = len(sentences) if isinstance(sentences, list) else 0
            record["paragraphs"] += 1
            record["sentences"] += sentence_count
            record["char_estimate"] += len(str(row.get("text") or "")) + sum(len(str(item.get("text") or "")) for item in sentences or [] if isinstance(item, dict))
    return sections


def estimate_tokens(chars: int) -> int:
    return max(1, int(chars / 4))


def build_shards(sections: list[dict[str, Any]], *, max_tokens: int) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    for section in sections:
        tokens = estimate_tokens(int(section.get("char_estimate", 0) or 0))
        if current and current_tokens + tokens > max_tokens:
            shards.append(make_shard(len(shards) + 1, current, current_tokens))
            current = []
            current_tokens = 0
        current.append({**section, "token_estimate": tokens})
        current_tokens += tokens
    if current:
        shards.append(make_shard(len(shards) + 1, current, current_tokens))
    return shards


def make_shard(index: int, sections: list[dict[str, Any]], token_estimate: int) -> dict[str, Any]:
    return {
        "shard_id": f"phase-a-shard-{index:03d}",
        "order": index,
        "section_ids": [section["section_id"] for section in sections],
        "section_titles": [section["title"] for section in sections],
        "sections": sections,
        "token_estimate": token_estimate,
    }


def packet_for_shard(*, bundle: Path, review_units_md: Path, review_units_jsonl: Path, shard: dict[str, Any]) -> dict[str, Any]:
    shard_id = shard["shard_id"]
    return {
        "schema_version": 1,
        "context_policy": "model_readable_prose_phase_packet",
        "generated_by": "scripts/build_prose_shards.py",
        "phase": "phase_a_shard",
        "objective": "Run Ariadne Prose Phase A on this explicit shard, preserving cross-section notes for the later mandatory synthesis pass.",
        "rule_refs": shard_rule_refs(shard),
        "read_inputs": [
            {
                "path": str(review_units_md),
                "hash": sha256_path(review_units_md),
                "context_policy": "model_readable_full_prose_input_sharded",
            },
            {
                "path": str(review_units_jsonl),
                "hash": sha256_path(review_units_jsonl),
                "context_policy": "model_readable_anchor_index",
            },
        ],
        "shard": shard,
        "write_targets": {
            "prose_issues": {
                "path": str(bundle / "issue_artifacts" / "prose_issues.jsonl"),
                "mode": "append_jsonl_by_section",
                "required": True,
            },
            "paragraph_decisions": {
                "path": str(bundle / "paragraph_decisions.jsonl"),
                "mode": "append_jsonl_by_section",
                "required": True,
            },
            "section_reflections": {
                "path": str(bundle / "section_reflections.json"),
                "mode": "update_json_after_each_section",
                "required": True,
            },
            "claim_candidates": {
                "path": str(bundle / "claim_candidates.json"),
                "mode": "create_or_update_json",
                "required": True,
            },
            "cold_skim_frame": {
                "path": str(bundle / "cold_skim_frame.json"),
                "mode": "create_once_or_update_before_section_work",
                "required": True,
            },
        },
        "output_contract": {
            "prose_issues_jsonl": {
                "minimum_fields": PROSE_ISSUE_MINIMUM_FIELDS,
                "teaching_fields": list(TEACHING_FIELDS),
                "cross_section_fields": ["target_anchors", "spans_sections", "related_issue_ids"],
            },
            "paragraph_decisions_jsonl": {
                "minimum_fields": [
                    "paragraph_id",
                    "section_id",
                    "decision",
                    "paragraph_job",
                    "next_draft_task",
                    "reviewed_sentence_ids or sentence_checks or all_sentences_reviewed",
                ],
            },
            "section_reflections_json": {
                "minimum_fields": ["section_id", "one_line", "role_in_argument", "top_issue_ids", "unresolved_questions"],
            },
        },
        "instructions": [
            "把 rule_refs 当作可执行 Prose shard 规则；run_prose_agent.py 或其他 prompt wrapper 必须在模型调用前解析这些规则。",
            *CHINESE_OUTPUT_INSTRUCTIONS,
            "只对 shard.section_ids 中列出的章节做完整句子/段落深读。",
            "跨章节疑问只能记录为 tentative signals，不要当作最终整篇判断。",
            "所有 shard 完成后，必须由 Phase B 综合 pass 读取 phase_b_context.json，再进入最终报告编译。",
            "不要写 HTML。",
        ],
    }


def build_manifest(
    *,
    bundle: Path,
    review_units_md: Path,
    review_units_jsonl: Path,
    max_tokens: int,
) -> dict[str, Any]:
    sections = section_rows(review_units_jsonl)
    total_tokens = sum(estimate_tokens(int(section.get("char_estimate", 0) or 0)) for section in sections)
    shards = build_shards(sections, max_tokens=max_tokens)
    shard_dir = bundle / "phase_a_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    packet_paths: list[str] = []
    for shard in shards:
        packet = packet_for_shard(bundle=bundle, review_units_md=review_units_md, review_units_jsonl=review_units_jsonl, shard=shard)
        packet_path = shard_dir / f"{shard['shard_id']}.json"
        packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        packet_paths.append(str(packet_path))
    return {
        "schema_version": 1,
        "context_policy": "model_readable_shard_manifest_only",
        "generated_by": "scripts/build_prose_shards.py",
        "review_units": {
            "markdown": str(review_units_md),
            "markdown_hash": sha256_path(review_units_md),
            "jsonl": str(review_units_jsonl),
            "jsonl_hash": sha256_path(review_units_jsonl),
        },
        "threshold": {
            "max_tokens_per_shard": max_tokens,
            "total_token_estimate": total_tokens,
        },
        "coverage": {
            "sections_total": len(sections),
            "shards_total": len(shards),
        },
        "shards": shards,
        "packet_paths": packet_paths,
        "mandatory_followup": "After all shard packets are reviewed, run phase_a_resume_status.py and build_phase_b_input.py; Phase B synthesis is required before final compilation.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--review-units-md", required=True, type=Path)
    parser.add_argument("--review-units-jsonl", required=True, type=Path)
    parser.add_argument("--max-tokens-per-shard", type=int, default=35_000)
    parser.add_argument("--out", type=Path, help="Default: <bundle>/phase_a_shard_manifest.json")
    args = parser.parse_args(argv)
    bundle = args.bundle.expanduser().resolve()
    manifest = build_manifest(
        bundle=bundle,
        review_units_md=args.review_units_md.expanduser().resolve(),
        review_units_jsonl=args.review_units_jsonl.expanduser().resolve(),
        max_tokens=args.max_tokens_per_shard,
    )
    out = args.out.expanduser().resolve() if args.out else bundle / "phase_a_shard_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote Phase A shard manifest: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
