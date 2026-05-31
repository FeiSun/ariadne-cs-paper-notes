#!/usr/bin/env python3
"""Compile Ariadne issue artifacts into final findings and annotations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_language_contract import is_student_visible_prose_issue  # noqa: E402


SCHEMA_VERSION = 1
ISSUE_ARTIFACT_TYPE = "ariadne_issue_artifact"
COMPILED_INDEX_TYPE = "ariadne_compiled_issue_index"
SEVERITY_ORDER = {"Polish": 0, "Minor": 1, "Major": 2, "Blocker": 3}
DEFAULT_STUDENT_VISIBLE_DOMAINS = {"prose", "whole_paper", "layout", "numeric", "figure_caption"}
JSONL_DOMAINS = {
    "prose_issues": "prose",
    "whole_paper_findings": "whole_paper",
}
DOMAIN_DEFAULTS = {
    "prose": {
        "reader_friction": "读者需要额外重建这句话或段落和中心主张的关系，才能判断作者想让自己相信什么。",
        "writing_principle": "显式逻辑，不让读者猜",
        "self_check": "下一稿能否让陌生读者不靠脑补就说出这处文字服务哪个 claim？",
        "severity_rationale": "严重度来自 Prose Phase A 源 issue；若源 issue 未给出具体理由，需要回到批注阶段补齐。",
        "downgrade_condition": "当源 issue 补齐具体读者卡点、闭合原则、自改问题，并且下一稿消除该阅读摩擦后可降级。",
        "verification_method": "由 Prose Phase A issue shard 编译",
    },
    "whole_paper": {
        "reader_friction": "读者在整篇层面仍无法判断中心主张、证据和边界是否对齐。",
        "writing_principle": "改变读者理解状态",
        "self_check": "如果不补新证据，下一稿必须收窄哪一个中心 claim 才诚实？",
        "severity_rationale": "严重度来自 Prose Phase B 综合 finding；若源 finding 未给出具体理由，需要回到综合阶段补齐。",
        "downgrade_condition": "当全稿 claim、证据和边界重新对齐，并且源 finding 不再出现时可降级。",
        "verification_method": "由 Prose Phase B finding shard 编译",
    },
    "layout": {
        "reader_friction": "版面呈现提高了读者检查或比较证据的成本。",
        "writing_principle": "低认知负担 / reader-first",
        "self_check": "正常 PDF zoom 下，审稿人能否快速看见并比较这处证据？",
        "severity_rationale": "严重度来自 layout issue artifact。",
        "downgrade_condition": "当版面核查不再报告该问题，或该对象不再影响主阅读路径时可降级。",
        "verification_method": "由 layout issue artifact 编译",
    },
    "numeric": {
        "reader_friction": "读者无法在不额外重算或猜测口径的情况下验证这处定量证据。",
        "writing_principle": "不要让读者做翻译题/查字典题/算术题",
        "self_check": "表中 reported value、可见复算值、delta 和 aggregation caveat 是否都写清？",
        "severity_rationale": "严重度来自 numeric issue artifact。",
        "downgrade_condition": "当 reported/computed/delta 对齐，或 aggregation caveat 解释差异后可降级。",
        "verification_method": "由 numeric issue artifact 编译",
    },
    "reference": {
        "reader_friction": "参考文献元数据让读者更难干净地核验引用证据。",
        "writing_principle": "特定读者共同体",
        "self_check": "审稿人能否只凭渲染出的 bibliography 找到并核验该引用？",
        "severity_rationale": "严重度来自 reference issue artifact。",
        "downgrade_condition": "当参考文献元数据规范且渲染结果可核验后可降级。",
        "verification_method": "由 reference issue artifact 编译",
    },
    "symbol": {
        "reader_friction": "符号或记号漂移迫使读者猜测两个形式是否仍表示同一对象。",
        "writing_principle": "不要让读者做翻译题/查字典题/算术题",
        "self_check": "读者能否不用猜就建立一张稳定符号表？",
        "severity_rationale": "严重度来自 symbol issue artifact。",
        "downgrade_condition": "当符号首次定义和跨处使用一致后可降级。",
        "verification_method": "由 symbol issue artifact 编译",
    },
    "source_hygiene": {
        "reader_friction": "投稿源文件卫生问题会分散 reviewer 注意力，或违反匿名/投稿预期。",
        "writing_principle": "特定读者共同体",
        "self_check": "这份 source package 能否直接通过匿名审稿和投稿卫生检查？",
        "severity_rationale": "严重度来自 source_hygiene issue artifact。",
        "downgrade_condition": "当 source hygiene audit 不再报告该问题后可降级。",
        "verification_method": "由 source hygiene issue artifact 编译",
    },
    "figure_caption": {
        "reader_friction": "图表或 caption 没有在使用点帮助读者理解它支持的证据。",
        "writing_principle": "caption 首句告诉读者该看见什么",
        "self_check": "只看图表和 caption，读者能否说出它支持哪个 claim？",
        "severity_rationale": "严重度来自 figure/caption issue artifact。",
        "downgrade_condition": "当图表和 caption 能自解释其 takeaway、setting、metric 和 comparator 后可降级。",
        "verification_method": "由 figure/caption issue artifact 编译",
    },
    "polish": {
        "reader_friction": "表面一致性问题给读者制造了不必要的阅读摩擦。",
        "writing_principle": "文字精确性先于 flow",
        "self_check": "这处表面问题是真实正文问题，还是表格/公式抽取噪声？",
        "severity_rationale": "严重度来自 polish issue artifact。",
        "downgrade_condition": "当 source polish audit 不再报告该问题，或确认是解析噪声后可降级。",
        "verification_method": "由 polish issue artifact 编译",
    },
}


@dataclass
class SourceIssue:
    source_id: str
    domain: str
    local_id: str
    source_path: Path
    source_hash: str
    row: dict[str, Any]
    source_artifacts: list[dict[str, Any]] = field(default_factory=list)
    order: int = 0


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_text(value: Any, *, max_chars: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def normalized_match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def source_only_identity_false_positive(row: dict[str, Any]) -> bool:
    if compact_text(row.get("visibility_basis"), max_chars=80).lower() == "compiled_pdf":
        return False
    joined = normalized_match_text(
        " ".join(
            first_nonempty(row, key, max_chars=1000)
            for key in (
                "title",
                "short",
                "diagnosis",
                "problem",
                "reader_friction",
                "self_check",
                "severity_rationale",
            )
        )
    )
    if not joined:
        return False
    front_matter_visible_claim = any(
        token in joined
        for token in (
            "暴露作者身份",
            "首页身份",
            "首页作者",
            "首页作者姓名",
            "作者姓名已经可见",
            "首页显示作者",
            "review 模式首页显示作者",
            "front matter exposes identity",
            "author identity",
        )
    )
    anonymous_context = any(
        token in joined
        for token in ("匿名评审", "acl review", "review 模式", "double-blind", "双盲", "anonymous review")
    )
    return front_matter_visible_claim and (anonymous_context or "首页" in joined)


def first_nonempty(mapping: dict[str, Any], *keys: str, max_chars: int = 1200) -> str:
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


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return compact_text(value).lower() in {"1", "true", "yes", "y", "student_visible", "visible", "render"}


def visibility_for_group(group: list[SourceIssue]) -> str:
    if any(source_only_identity_false_positive(issue.row) for issue in group):
        return "artifact_only"
    for issue in group:
        explicit = compact_text(
            issue.row.get("render_visibility")
            or issue.row.get("visibility")
            or issue.row.get("student_visibility"),
            max_chars=80,
        ).lower()
        if explicit in {"student_visible", "visible", "render"}:
            return "student_visible"
        if explicit in {"artifact_only", "audit_only", "hidden"}:
            return "artifact_only"
        if truthy(issue.row.get("student_visible")) or truthy(issue.row.get("render_in_html")):
            return "student_visible"
    return "student_visible" if group[0].domain in DEFAULT_STUDENT_VISIBLE_DOMAINS else "artifact_only"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def severity_rank(value: Any) -> int:
    return SEVERITY_ORDER.get(compact_text(value), 1)


def strongest_severity(values: list[Any]) -> str:
    severities = [compact_text(value) for value in values if compact_text(value) in SEVERITY_ORDER]
    if not severities:
        return "Minor"
    return max(severities, key=severity_rank)


def path_sort_key(path: Path) -> tuple[int, str]:
    name = path.name
    if name == "prose_issues.jsonl":
        return (0, name)
    if name == "whole_paper_findings.jsonl":
        return (1, name)
    return (2, name)


def issue_paths(issues_dir: Path) -> list[Path]:
    paths = [path for path in issues_dir.glob("*_issues.json") if path.is_file()]
    paths.extend(path for path in issues_dir.glob("*_issues.jsonl") if path.is_file())
    paths.extend(path for path in issues_dir.glob("whole_paper_findings.jsonl") if path.is_file())
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in sorted(paths, key=path_sort_key):
        resolved = path.resolve()
        if resolved not in seen:
            unique.append(path)
            seen.add(resolved)
    return unique


def domain_for_jsonl(path: Path) -> str:
    return JSONL_DOMAINS.get(path.stem, path.stem.replace("_issues", ""))


def read_jsonl_issues(path: Path, *, start_order: int) -> tuple[list[SourceIssue], dict[str, Any]]:
    issues: list[SourceIssue] = []
    source_hash = sha256_path(path)
    for line_idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {line_idx} is not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}: line {line_idx} must be a JSON object")
        domain = compact_text(row.get("domain")) or domain_for_jsonl(path)
        local_id = first_nonempty(row, "local_id", "id", "issue_id", max_chars=120) or f"{domain[:1].upper()}{line_idx}"
        issues.append(
            SourceIssue(
                source_id=f"{domain}:{local_id}",
                domain=domain,
                local_id=local_id,
                source_path=path,
                source_hash=source_hash,
                row=row,
                order=start_order + len(issues),
            )
        )
    metadata = {"path": str(path), "hash": source_hash, "rows": len(issues)}
    return issues, metadata


def read_json_issue_artifact(path: Path, *, start_order: int) -> tuple[list[SourceIssue], dict[str, Any] | None]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: issue artifact must be an object")
    if payload.get("artifact_type") != ISSUE_ARTIFACT_TYPE:
        return [], None
    domain = compact_text(payload.get("domain")) or path.stem.replace("_issues", "")
    issues_payload = payload.get("issues")
    if not isinstance(issues_payload, list):
        raise ValueError(f"{path}: issue artifact must contain an issues list")
    source_hash = sha256_path(path)
    source_artifacts = payload.get("source_artifacts") if isinstance(payload.get("source_artifacts"), list) else []
    issues: list[SourceIssue] = []
    for idx, row in enumerate(issues_payload, 1):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: issue #{idx} must be an object")
        local_id = first_nonempty(row, "local_id", "id", "issue_id", max_chars=120) or f"{domain[:1].upper()}{idx}"
        issues.append(
            SourceIssue(
                source_id=f"{domain}:{local_id}",
                domain=domain,
                local_id=local_id,
                source_path=path,
                source_hash=source_hash,
                row=row,
                source_artifacts=[item for item in source_artifacts if isinstance(item, dict)],
                order=start_order + len(issues),
            )
        )
    return issues, None


def load_source_issues(issues_dir: Path) -> tuple[list[SourceIssue], list[dict[str, Any]], list[dict[str, Any]]]:
    all_issues: list[SourceIssue] = []
    normalized_jsonl: list[dict[str, Any]] = []
    source_artifacts: list[dict[str, Any]] = []
    order = 0
    for path in issue_paths(issues_dir):
        if path.suffix == ".jsonl":
            issues, metadata = read_jsonl_issues(path, start_order=order)
            normalized_jsonl.append(metadata)
        else:
            issues, _metadata = read_json_issue_artifact(path, start_order=order)
        if issues:
            source_artifacts.append({"path": str(path), "hash": sha256_path(path)})
        all_issues.extend(issues)
        order += len(issues)
    return all_issues, normalized_jsonl, source_artifacts


def load_source_soup(source_artifact: str) -> BeautifulSoup | None:
    if not source_artifact:
        return None
    path = Path(source_artifact)
    if not path.exists() or not path.is_file():
        return None
    return BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")


def source_anchor_node(soup: BeautifulSoup, anchor: str) -> Tag | None:
    if not anchor:
        return None
    if anchor.startswith("s-"):
        node = soup.find(attrs={"data-sentence-id": anchor})
        return node if isinstance(node, Tag) else None
    if anchor.startswith("p-"):
        node = soup.find(attrs={"data-paragraph-id": anchor})
        return node if isinstance(node, Tag) else None
    node = soup.find(id=anchor)
    return node if isinstance(node, Tag) else None


def float_container_for_reference(target: Tag) -> Tag:
    current: Tag | None = target
    fallback = target
    while current is not None:
        if current.name in {"body", "html"}:
            break
        if current.name in {"figure", "table"}:
            return current
        classes = current.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        node_id = str(current.get("id") or "")
        if any(str(item).startswith(("paper-float", "paper-table", "paper-figure")) for item in classes):
            fallback = current
        elif node_id.startswith(("fig:", "tab:")):
            fallback = current
        current = current.parent if isinstance(current.parent, Tag) else None
    return fallback


def caption_number_for_reference(soup: BeautifulSoup, ref: str) -> str:
    target = soup.find(id=ref)
    if not isinstance(target, Tag):
        return ""
    container = float_container_for_reference(target)
    caption = container.find("figcaption") or container.find("caption")
    if not isinstance(caption, Tag):
        return ""
    match = re.search(r"\b(?:Figure|Table)\s+(\d+)\s*:", caption.get_text(" ", strip=True))
    return match.group(1) if match else ""


def stale_resolved_float_reference_issue(issue: SourceIssue, soup: BeautifulSoup | None) -> bool:
    if soup is None:
        return False
    issue_type = first_nonempty(issue.row, "issue_type", "type", max_chars=120).lower()
    if issue_type not in {"figure_reference", "table_reference", "float_reference"}:
        return False
    node = source_anchor_node(soup, primary_anchor(issue.row))
    if not isinstance(node, Tag):
        return False
    checked = 0
    for link in node.find_all("a"):
        if not isinstance(link, Tag):
            continue
        ref = str(link.get("data-reference") or "").strip()
        href = str(link.get("href") or "").strip()
        if not ref and href.startswith("#"):
            ref = href[1:]
        if not ref.startswith(("fig:", "tab:")):
            continue
        caption_number = caption_number_for_reference(soup, ref)
        link_text = compact_text(link.get_text(" ", strip=True), max_chars=80)
        if not caption_number or link_text != caption_number:
            return False
        checked += 1
    return checked > 0


def filter_stale_source_issues(
    issues: list[SourceIssue],
    *,
    source_soup: BeautifulSoup | None,
) -> tuple[list[SourceIssue], list[str]]:
    kept: list[SourceIssue] = []
    stale_ids: list[str] = []
    for issue in issues:
        if stale_resolved_float_reference_issue(issue, source_soup):
            stale_ids.append(issue.source_id)
            continue
        kept.append(issue)
    return kept, stale_ids


def evidence_refs(row: dict[str, Any]) -> list[Any]:
    value = row.get("evidence_refs") or row.get("evidence_ref") or []
    return as_list(value)


def anchors_for_issue(row: dict[str, Any]) -> list[str]:
    anchors: list[str] = []
    for key in ("target_anchors", "anchors"):
        for item in as_list(row.get(key)):
            text = compact_text(item, max_chars=160)
            if text and text not in anchors:
                anchors.append(text)
    render_hint = row.get("render_hint") if isinstance(row.get("render_hint"), dict) else {}
    for value in (
        row.get("primary_anchor"),
        row.get("anchor"),
        render_hint.get("anchor") if isinstance(render_hint, dict) else "",
        row.get("sentence_id"),
        row.get("paragraph_id"),
        row.get("section_id"),
    ):
        text = compact_text(value, max_chars=160)
        if text and text not in anchors:
            anchors.append(text)
    return anchors


def primary_anchor(row: dict[str, Any]) -> str:
    explicit = first_nonempty(row, "primary_anchor", "anchor", "sentence_id", "paragraph_id", "section_id", max_chars=160)
    if explicit:
        return explicit
    render_hint = row.get("render_hint") if isinstance(row.get("render_hint"), dict) else {}
    if isinstance(render_hint, dict):
        hinted = compact_text(render_hint.get("anchor"), max_chars=160)
        if hinted:
            return hinted
    anchors = anchors_for_issue(row)
    return anchors[0] if anchors else ""


def dedup_key(issue: SourceIssue) -> tuple[str, str, str] | None:
    row = issue.row
    evidence = evidence_refs(row)
    if evidence:
        return (issue.domain, first_nonempty(row, "issue_type", "type", max_chars=120), canonical_json(evidence))
    anchor = primary_anchor(row)
    diagnosis = first_nonempty(row, "diagnosis", "title", "short", max_chars=180).lower()
    if anchor and diagnosis:
        return (issue.domain, first_nonempty(row, "issue_type", "type", max_chars=120), f"{anchor}:{diagnosis}")
    return None


def deduplicate(issues: list[SourceIssue]) -> list[list[SourceIssue]]:
    groups: list[list[SourceIssue]] = []
    key_to_idx: dict[tuple[str, str, str], int] = {}
    for issue in issues:
        key = dedup_key(issue)
        if key is not None and key in key_to_idx:
            groups[key_to_idx[key]].append(issue)
            continue
        key_to_idx[key] = len(groups) if key is not None else len(groups)
        groups.append([issue])
    return groups


def default_for(domain: str, field_name: str) -> str:
    return DOMAIN_DEFAULTS.get(domain, DOMAIN_DEFAULTS["prose"]).get(field_name, "")


def merged_field(group: list[SourceIssue], *keys: str, max_chars: int = 1200) -> str:
    for issue in group:
        text = first_nonempty(issue.row, *keys, max_chars=max_chars)
        if text:
            return text
    return ""


def merge_source_artifacts(group: list[SourceIssue]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in group:
        artifact = {"path": str(issue.source_path), "hash": issue.source_hash, "context_policy": "model_readable_issue_only"}
        for item in [artifact, *issue.source_artifacts]:
            key = canonical_json(item)
            if key not in seen:
                merged.append(item)
                seen.add(key)
    return merged


def compile_finding(group: list[SourceIssue], final_id: str) -> dict[str, Any]:
    primary = group[0]
    domain = primary.domain
    severity = strongest_severity([issue.row.get("severity") for issue in group])
    title = merged_field(group, "title", "short", "summary", "diagnosis", max_chars=220) or f"{domain} issue"
    diagnosis = merged_field(group, "diagnosis", "problem", "what", "title", max_chars=1200) or title
    issue_type = merged_field(group, "issue_type", "type", max_chars=120) or domain
    anchors: list[str] = []
    refs: list[Any] = []
    for issue in group:
        for anchor in anchors_for_issue(issue.row):
            if anchor not in anchors:
                anchors.append(anchor)
        for ref in evidence_refs(issue.row):
            if canonical_json(ref) not in {canonical_json(item) for item in refs}:
                refs.append(ref)
    anchor = primary_anchor(primary.row) or (anchors[0] if anchors else "")
    location = merged_field(group, "location", max_chars=220) or anchor or domain.replace("_", " ")
    recommendation = merged_field(group, "recommendation", "next_draft_task", "task", max_chars=900)
    self_check = merged_field(group, "self_check", "next_draft_question", "revision_question", max_chars=900) or recommendation or default_for(domain, "self_check")
    reader_friction = merged_field(group, "reader_friction", "why", max_chars=900) or default_for(domain, "reader_friction")
    writing_principle = merged_field(group, "writing_principle", "principle", max_chars=260) or default_for(domain, "writing_principle")
    confidence = merged_field(group, "confidence", max_chars=120) or "medium"
    severity_rationale = (
        merged_field(group, "severity_rationale", max_chars=700)
        or default_for(domain, "severity_rationale")
        or f"严重度由源 issue artifact 的 {severity} 级别编译而来。"
    )
    downgrade_condition = (
        merged_field(group, "downgrade_condition", max_chars=700)
        or default_for(domain, "downgrade_condition")
        or "当下一轮编译 artifact 不再包含该源 issue 后可降级。"
    )
    source_issue_ids = [issue.source_id for issue in group]
    render_visibility = visibility_for_group(group)
    finding: dict[str, Any] = {
        "id": final_id,
        "domain": domain,
        "render_visibility": render_visibility,
        "severity": severity,
        "issue_type": issue_type,
        "location": location,
        "snippet": merged_field(group, "snippet", "quote", max_chars=500),
        "title": title,
        "diagnosis": diagnosis,
        "reader_friction": reader_friction,
        "writing_principle": writing_principle,
        "self_check": self_check,
        "next_draft_task": recommendation,
        "evidence_basis": merged_field(group, "evidence_basis", max_chars=900) or canonical_json(refs or source_issue_ids),
        "verification_method": merged_field(group, "verification_method", max_chars=300) or default_for(domain, "verification_method"),
        "confidence": confidence,
        "severity_rationale": severity_rationale,
        "downgrade_condition": downgrade_condition,
        "source_issue_ids": source_issue_ids,
        "evidence_refs": refs,
        "source_artifacts": merge_source_artifacts(group),
    }
    if is_student_visible_prose_issue(finding, domain=domain):
        fallback_fields = [
            field
            for field in ("reader_friction", "writing_principle", "self_check", "severity_rationale", "downgrade_condition")
            if not merged_field(group, field, max_chars=80)
        ]
        if fallback_fields:
            finding["compiler_fallback_fields"] = fallback_fields
    if anchors:
        finding["target_anchors"] = anchors
        finding["primary_anchor"] = anchor or anchors[0]
        finding["spans_sections"] = bool(group[0].row.get("spans_sections")) or len(anchors) > 1
    for key in ("reported_value", "visible_computed_value", "delta", "aggregation_caveat"):
        value = merged_field(group, key, max_chars=160)
        if value:
            finding[key] = value
    return finding


def infer_target(anchor: str, row: dict[str, Any]) -> tuple[str, str]:
    render_hint = row.get("render_hint") if isinstance(row.get("render_hint"), dict) else {}
    target_level = compact_text(render_hint.get("target_level") if isinstance(render_hint, dict) else "", max_chars=80).lower()
    if target_level in {"sentence", "paragraph", "section", "paper"}:
        level = target_level
    elif anchor.startswith("s-"):
        level = "sentence"
    elif anchor.startswith("p-"):
        level = "paragraph"
    elif anchor and not anchor.startswith("page:") and anchor != "paper":
        level = "section"
    else:
        level = "paper"
    if level == "paper":
        return level, "paper"
    return level, anchor


def annotation_for_finding(finding: dict[str, Any], *, source_artifact: str = "", source_hash: str = "") -> dict[str, Any]:
    anchor = compact_text(finding.get("primary_anchor")) or first_nonempty(finding, "target_anchors", max_chars=160)
    level, target = infer_target(anchor, finding)
    annotation: dict[str, Any] = {
        "issue_id": finding["id"],
        "target_level": level,
        "render_visibility": finding.get("render_visibility") or "student_visible",
        "short": finding.get("title") or finding.get("diagnosis") or finding["id"],
        "title": finding.get("title") or finding["id"],
    }
    if level == "sentence":
        annotation["sentence_id"] = target
    elif level == "paragraph":
        annotation["paragraph_id"] = target
    elif level == "section":
        annotation["section_id"] = target
    else:
        annotation["paper_id"] = "paper"
    if source_artifact:
        annotation["source_artifact"] = source_artifact
    if source_hash:
        annotation["source_hash"] = source_hash
    return annotation


def add_anchor_cross_links(findings: list[dict[str, Any]]) -> None:
    by_anchor: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        anchor = compact_text(finding.get("primary_anchor"))
        if anchor:
            by_anchor.setdefault(anchor, []).append(finding)
    for group in by_anchor.values():
        if len(group) < 2:
            continue
        ids = [str(item["id"]) for item in group]
        for item in group:
            related = sorted(existing for existing in ids if existing != item["id"])
            if related:
                item["related_issue_ids"] = sorted(set(as_list(item.get("related_issue_ids")) + related))


def compile_artifacts(
    *,
    issues_dir: Path,
    source_artifact: str = "",
    source_hash: str = "",
    start_index: int = 1,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_issues, normalized_jsonl, source_artifacts = load_source_issues(issues_dir)
    source_soup = load_source_soup(source_artifact)
    source_issues, stale_source_issue_ids = filter_stale_source_issues(source_issues, source_soup=source_soup)
    groups = deduplicate(source_issues)
    findings: list[dict[str, Any]] = []
    source_to_finding: dict[str, str] = {}
    dedup_groups: list[dict[str, Any]] = []
    for offset, group in enumerate(groups):
        final_id = f"F{start_index + offset}"
        finding = compile_finding(group, final_id)
        findings.append(finding)
        for issue in group:
            source_to_finding[issue.source_id] = final_id
        if len(group) > 1:
            dedup_groups.append({"finding_id": final_id, "source_issue_ids": [issue.source_id for issue in group]})
    add_anchor_cross_links(findings)
    annotations = [
        annotation_for_finding(finding, source_artifact=source_artifact, source_hash=source_hash)
        for finding in findings
        if compact_text(finding.get("render_visibility")) != "artifact_only"
    ]
    findings_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "compile_review_artifacts.py",
        "findings": findings,
    }
    annotations_payload = {
        "annotation_schema": "anchor-only",
        "source_artifact": source_artifact,
        "source_hash": source_hash,
        "annotations": annotations,
    }
    index_payload = {
        "artifact_type": COMPILED_INDEX_TYPE,
        "schema_version": SCHEMA_VERSION,
        "context_policy": "tool_derived_index",
        "source_artifacts": source_artifacts,
        "normalized_jsonl_shards": normalized_jsonl,
        "source_issue_count": len(source_issues),
        "stale_source_issue_ids": stale_source_issue_ids,
        "finding_count": len(findings),
        "annotation_count": len(annotations),
        "artifact_only_finding_ids": [
            finding["id"] for finding in findings if compact_text(finding.get("render_visibility")) == "artifact_only"
        ],
        "source_to_finding_id": source_to_finding,
        "dedup_groups": dedup_groups,
    }
    return findings_payload, annotations_payload, index_payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues-dir", required=True, type=Path, help="Directory containing *_issues.json/jsonl artifacts")
    parser.add_argument("--findings-out", required=True, type=Path, help="Output compiled findings.json path")
    parser.add_argument("--annotations-out", required=True, type=Path, help="Output compiled annotations.json path")
    parser.add_argument("--index-out", type=Path, help="Output compiled issue index path")
    parser.add_argument("--source-artifact", default="", help="Optional current paper-reader source artifact for annotations")
    parser.add_argument("--source-hash", default="", help="Optional current paper-reader source hash for annotations")
    parser.add_argument("--start-index", type=int, default=1, help="First generated finding number")
    args = parser.parse_args(argv)

    index_out = args.index_out or args.issues_dir / "compiled_issue_index.json"
    try:
        findings, annotations, index = compile_artifacts(
            issues_dir=args.issues_dir,
            source_artifact=args.source_artifact,
            source_hash=args.source_hash,
            start_index=args.start_index,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    write_json(args.findings_out, findings)
    write_json(args.annotations_out, annotations)
    write_json(index_out, index)
    print(
        "Compiled review artifacts: "
        f"source_issues={index['source_issue_count']} "
        f"findings={index['finding_count']} "
        f"annotations={index['annotation_count']} "
        f"jsonl_shards={len(index['normalized_jsonl_shards'])}"
    )
    print(f"Findings: {args.findings_out}")
    print(f"Annotations: {args.annotations_out}")
    print(f"Index: {index_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
