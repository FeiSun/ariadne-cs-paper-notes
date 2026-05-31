#!/usr/bin/env python3
"""Shared Chinese teaching-note contract for Ariadne review artifacts."""

from __future__ import annotations

import re
from typing import Any


CLOSED_WRITING_PRINCIPLES = {
    "改变读者理解状态",
    "特定读者共同体",
    "problem-solution text",
    "加入并推动已有对话",
    "argument, not explanation or research log",
    "一文一核",
    "显式逻辑，不让读者猜",
    "文字精确性先于 flow",
    "结构决定意义",
    "低认知负担 / reader-first",
    "知识的诅咒",
    "洞察 ≠ 机制",
    "一段只做一件事",
    "句首接旧信息，句尾放新信息",
    "caption 首句告诉读者该看见什么",
    "不要让读者做翻译题/查字典题/算术题",
    "红队式自查",
}

TEACHING_FIELDS = (
    "reader_friction",
    "writing_principle",
    "self_check",
    "confidence",
    "evidence_refs",
    "severity_rationale",
    "downgrade_condition",
)

VISIBLE_PROSE_DOMAINS = {"prose", "whole_paper"}

CHINESE_OUTPUT_INSTRUCTIONS = [
    "可见给学生的批注意见默认必须用中文书写。",
    "每条可见实质性批注都必须保留这个教学结构：读者卡点 -> 单一违反原则 -> 自改问题。",
    "`reader_friction` 必须用中文写出具体读者卡点。",
    "`writing_principle` 必须严格使用 `core_principles.md` 闭合原则表中的一个标签，或该标签的直接中文细化版本。",
    "`self_check` 必须是作者下一稿可以直接用来修改的中文自检问题。",
    "不能只写 title+diagnosis 交差；可见 Prose/whole-paper finding 不能使用通用英文兜底模板。",
]


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def cjk_ratio(value: Any) -> float:
    text = compact_text(value)
    chars = [char for char in text if not char.isspace()]
    if not chars:
        return 0.0
    cjk = sum(1 for char in chars if "\u4e00" <= char <= "\u9fff")
    return cjk / len(chars)


def has_chinese(value: Any, *, min_chars: int = 2) -> bool:
    return sum(1 for char in compact_text(value) if "\u4e00" <= char <= "\u9fff") >= min_chars


def is_closed_principle(value: Any) -> bool:
    text = compact_text(value)
    if not text:
        return False
    if text in CLOSED_WRITING_PRINCIPLES:
        return True
    return any(text.startswith(f"{principle}：") or text.startswith(f"{principle}:") for principle in CLOSED_WRITING_PRINCIPLES)


def is_student_visible_prose_issue(row: dict[str, Any], *, domain: str | None = None) -> bool:
    issue_domain = compact_text(domain or row.get("domain") or row.get("issue_type"))
    issue_type = compact_text(row.get("issue_type"))
    if issue_domain not in VISIBLE_PROSE_DOMAINS and issue_type not in VISIBLE_PROSE_DOMAINS:
        return False
    visibility = compact_text(row.get("render_visibility")).lower()
    return visibility != "artifact_only"


def visible_teaching_text(row: dict[str, Any]) -> str:
    fields = (
        "title",
        "diagnosis",
        "reader_friction",
        "writing_principle",
        "self_check",
        "next_draft_task",
        "severity_rationale",
        "downgrade_condition",
    )
    return " ".join(compact_text(row.get(field)) for field in fields)


def teaching_contract_errors(row: dict[str, Any], *, prefix: str, domain: str | None = None) -> list[str]:
    if not is_student_visible_prose_issue(row, domain=domain):
        return []
    errors: list[str] = []
    for field in ("reader_friction", "writing_principle", "self_check", "confidence", "severity_rationale", "downgrade_condition"):
        if not compact_text(row.get(field)):
            errors.append(f"{prefix}: visible Prose finding missing `{field}`")
    evidence_refs = row.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        errors.append(f"{prefix}: visible Prose finding missing non-empty `evidence_refs`")
    for field in ("diagnosis", "reader_friction", "self_check"):
        if compact_text(row.get(field)) and not has_chinese(row.get(field)):
            errors.append(f"{prefix}: `{field}` must be written in Chinese for visible Prose critique")
    if not is_closed_principle(row.get("writing_principle")):
        errors.append(f"{prefix}: `writing_principle` must use one closed Ariadne principle label")
    if cjk_ratio(visible_teaching_text(row)) < 0.18:
        errors.append(f"{prefix}: visible Prose critique is not predominantly Chinese")
    return errors
