#!/usr/bin/env python3
"""Shared executable Prose rule references for Ariadne prompt packets."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT_DIR / "references" / "rules"

CORE_RULE = ("core_principles", "中文导师式批注、闭合原则表、严重度和教学字段合同。")
PHASE_A_RULE = ("prose_phase_a_rules", "Phase A cold skim、线性深读、段落决策和 section reflection。")
PHASE_B_RULE = ("prose_phase_b_rules", "整篇 claim-evidence synthesis、红队诊断和跨域整合。")
METHOD_RULE = ("method_rules", "Method 地图、novelty、定义、假设、机制和公式解释。")
EXPERIMENT_RULE = ("experiment_rules", "实验 evidence-chain、证据口径、公平比较和边界。")
RELATED_WORK_RULE = ("related_work_rules", "Related Work 坐标系、假设、定位和 baseline 呼应。")
PROSE_STYLE_RULE = ("prose_style_rules", "句子精确性、old-new flow、连接词真实性和段落任务。")

PROSE_PHASE_A_RULES = [CORE_RULE, PHASE_A_RULE, METHOD_RULE, EXPERIMENT_RULE, RELATED_WORK_RULE, PROSE_STYLE_RULE]
PROSE_PHASE_B_RULES = [CORE_RULE, PHASE_B_RULE, METHOD_RULE, EXPERIMENT_RULE, RELATED_WORK_RULE]
SHARD_BASE_PHASE_A_RULES = [CORE_RULE, PHASE_A_RULE, PROSE_STYLE_RULE]
SECTION_RULES = {
    "method": METHOD_RULE,
    "experiment": EXPERIMENT_RULE,
    "related": RELATED_WORK_RULE,
}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def rule_record(name: str, purpose: str) -> dict[str, str]:
    path = RULES_DIR / f"{name}.md"
    return {
        "id": name,
        "path": str(path),
        "hash": sha256_path(path),
        "context_policy": "model_readable_rule_ref",
        "purpose": purpose,
    }


def rule_records(rules: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [rule_record(name, purpose) for name, purpose in rules]


def prose_rule_refs(phase: str) -> list[dict[str, str]]:
    rules = PROSE_PHASE_A_RULES if phase == "phase_a" else PROSE_PHASE_B_RULES
    return rule_records(rules)


def section_rule_keys(shard: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    sections = shard.get("sections")
    if not isinstance(sections, list):
        return keys
    for section in sections:
        if not isinstance(section, dict):
            continue
        text = f"{section.get('section_id', '')} {section.get('title', '')}".lower()
        if any(term in text for term in ("method", "approach", "model", "algorithm")):
            keys.add("method")
        if any(term in text for term in ("experiment", "evaluation", "result", "analysis", "ablation", "study")):
            keys.add("experiment")
        if any(term in text for term in ("related", "background", "prior work")):
            keys.add("related")
    return keys


def shard_rule_refs(shard: dict[str, Any]) -> list[dict[str, str]]:
    rules = list(SHARD_BASE_PHASE_A_RULES)
    for key in ("method", "experiment", "related"):
        if key in section_rule_keys(shard):
            rules.append(SECTION_RULES[key])
    return rule_records(rules)
