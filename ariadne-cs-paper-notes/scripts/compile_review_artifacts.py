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
        "reader_friction": "The prose makes the reader do extra reconstruction work before the claim is clear.",
        "writing_principle": "reader-first prose",
        "verification_method": "compiled from Prose Phase A issue shard",
    },
    "whole_paper": {
        "reader_friction": "The paper-level argument leaves an important reviewer question unresolved.",
        "writing_principle": "claim-evidence alignment",
        "verification_method": "compiled from Prose Phase B finding shard",
    },
    "layout": {
        "reader_friction": "The visual presentation makes the evidence harder to inspect or compare.",
        "writing_principle": "low cognitive load",
        "verification_method": "compiled from layout issue artifact",
    },
    "numeric": {
        "reader_friction": "The reader cannot verify the reported quantitative evidence without extra reconciliation.",
        "writing_principle": "auditable quantitative reporting",
        "verification_method": "compiled from numeric issue artifact",
    },
    "reference": {
        "reader_friction": "The bibliography makes cited evidence harder to verify cleanly.",
        "writing_principle": "verifiable citation metadata",
        "verification_method": "compiled from reference issue artifact",
    },
    "symbol": {
        "reader_friction": "Notation drift forces the reader to infer whether terms still mean the same thing.",
        "writing_principle": "stable terminology",
        "verification_method": "compiled from symbol issue artifact",
    },
    "source_hygiene": {
        "reader_friction": "Submission-source hygiene issues can distract reviewers or break venue expectations.",
        "writing_principle": "submission readiness",
        "verification_method": "compiled from source hygiene issue artifact",
    },
    "figure_caption": {
        "reader_friction": "The figure or table does not make its evidence easy to interpret at the point of use.",
        "writing_principle": "self-contained evidence display",
        "verification_method": "compiled from figure/caption issue artifact",
    },
    "polish": {
        "reader_friction": "Small consistency issues create unnecessary surface friction for the reader.",
        "writing_principle": "consistent manuscript polish",
        "verification_method": "compiled from polish issue artifact",
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
    self_check = (
        merged_field(group, "self_check", "next_draft_question", "revision_question", max_chars=900)
        or recommendation
        or f"Can the next draft remove this {domain.replace('_', ' ')} friction point?"
    )
    reader_friction = merged_field(group, "reader_friction", "why", max_chars=900) or default_for(domain, "reader_friction")
    writing_principle = merged_field(group, "writing_principle", "principle", max_chars=260) or default_for(domain, "writing_principle")
    confidence = merged_field(group, "confidence", max_chars=120) or "medium"
    severity_rationale = (
        merged_field(group, "severity_rationale", max_chars=700)
        or f"Compiled severity is {severity} from source issue artifact severity."
    )
    downgrade_condition = (
        merged_field(group, "downgrade_condition", max_chars=700)
        or "Downgrade after the next compiled artifacts no longer contain this source issue."
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
