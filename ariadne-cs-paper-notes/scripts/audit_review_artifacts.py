#!/usr/bin/env python3
"""Audit Ariadne structured review artifacts and optional rendered HTML."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_html_report import AriadneHTMLParser, audit as audit_html  # noqa: E402


SEVERITIES = {"Blocker", "Major", "Minor", "Polish"}
HIGH_RISK = {"Blocker", "Major"}

REQUIRED_FINDING_FIELDS = {
    "id",
    "severity",
    "location",
    "reader_friction",
    "writing_principle",
    "evidence_basis",
    "verification_method",
}
ANNOTATION_CONTENT_FIELDS = {
    "problem",
    "diagnosis",
    "why",
    "reader_friction",
    "location",
    "snippet",
    "evidence_basis",
    "verification_method",
    "severity_rationale",
    "downgrade_condition",
    "self_check",
    "next_draft_question",
    "task",
    "next_draft_task",
    "confidence",
    "principle",
    "writing_principle",
}
ANCHOR_ONLY_ANNOTATION_FIELDS = {
    "issue_id",
    "id",
    "target_level",
    "anchor_level",
    "sentence_id",
    "target_sentence",
    "paragraph_id",
    "target_paragraph",
    "section_id",
    "target_section",
    "heading_id",
    "paper_id",
    "target_paper",
    "short",
    "title",
    "source_artifact",
    "source_hash",
    "render_visibility",
}
FINDING_SELF_CHECK_FIELDS = {"self_check", "next_draft_question", "next_draft_task"}

HIGH_RISK_FIELDS = {
    "confidence",
    "severity_rationale",
    "downgrade_condition",
}

REQUIRED_CLAIM_FIELDS = {
    "claim_id",
    "claim_text",
    "location",
    "claim_type",
    "strength",
    "required_evidence",
    "visible_evidence",
    "status",
    "next_draft_task",
}

REQUIRED_MANIFEST_FIELDS = {"output_files", "sections", "deferred_findings"}
PDF_OVERLAY_MANIFEST_FIELDS = {
    "mode",
    "source_artifact",
    "source_hash",
    "annotation_mode",
    "source_integrity_check",
}
SOURCE_INTEGRITY_CHECKS = {"verified", "mismatch", "skipped"}
HASH_RE = re.compile(r"^(sha1|sha256):[0-9a-fA-F]{8,}$")
PASS_OBSERVATION_KEYS = {
    "pass_0_engagement_contract",
    "pass_1_cold_start_skim",
    "pass_2_linear_deep_read",
    "pass_3_section_reflections",
    "pass_4_whole_paper_argument",
    "pass_5_submission_walk",
    "pass_6_output_calibration",
}
VAGUE_NUMERIC_PHRASES = (
    "有偏差",
    "需复查",
    "需要核对",
    "建议复查",
    "可能有问题",
    "check",
    "recheck",
)
DIRECTIVE_NUMERIC_WORDS = ("wrong", "incorrect", "错误", "算错", "不是")
FULL_REVIEW_CUES = ("full", "全文", "逐句", "no sampling", "不抽样", "not sample", "main.tex")
SENTENCE_UNIT_CUES = ("sentence", "sentences", "句")
PARAGRAPH_UNIT_CUES = ("paragraph", "paragraphs", "段")
SECTION_UNIT_CUES = ("section", "sections", "heading", "headings", "章节", "标题")
FORBIDDEN_BUNDLE_FILENAMES = {
    "build_overlay_artifacts.py",
    "build_main_overlay_annotations.py",
}
FORBIDDEN_SIBLING_NAMES = {
    "main_pdftotext.txt",
    "paper.txt",
}
FORBIDDEN_PREVIEW_PATTERNS = ("*.source_preview.html", "*_preview.html")
LAYOUT_AUDIT_TOOL = "scripts/check_page_layout.py"
LAYOUT_AUDIT_FIELDS = ("produced_by", "script_hash", "page")
ISSUE_ARTIFACT_TYPE = "ariadne_issue_artifact"
COMPILED_ISSUE_INDEX_TYPE = "ariadne_compiled_issue_index"
ISSUE_ARTIFACT_CONTEXT_POLICY = "model_readable_issue_only"
TOOL_ONLY_CONTEXT_POLICY = "tool_only"
ISSUE_DOMAINS = {
    "prose",
    "whole_paper",
    "layout",
    "numeric",
    "reference",
    "symbol",
    "source_hygiene",
    "figure_caption",
    "polish",
}
ISSUE_STATUSES = {"completed", "skipped", "partial"}
REQUIRED_ISSUE_FIELDS = {
    "local_id",
    "severity",
    "issue_type",
    "title",
    "diagnosis",
    "evidence_refs",
    "confidence",
}
HIGH_RISK_ISSUE_FIELDS = {
    "reader_friction",
    "writing_principle",
    "self_check",
    "severity_rationale",
    "downgrade_condition",
}


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def list_from_payload(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    raise ValueError(f"Expected a list or object with `{key}` list.")


def nonempty(value: Any) -> bool:
    return value is not None and value != "" and value != []


def annotation_target_level(annotation: dict[str, Any]) -> str:
    level = compact_text(annotation.get("target_level")).lower()
    if level:
        return level
    if nonempty(annotation.get("sentence_id")) or nonempty(annotation.get("target_sentence")):
        return "sentence"
    if nonempty(annotation.get("paragraph_id")) or nonempty(annotation.get("target_paragraph")):
        return "paragraph"
    if nonempty(annotation.get("section_id")) or nonempty(annotation.get("target_section")):
        return "section"
    if nonempty(annotation.get("paper_id")) or nonempty(annotation.get("target_paper")):
        return "paper"
    return ""


def unit_by_cues(payload: dict[str, Any], cues: tuple[str, ...]) -> dict[str, Any] | None:
    units = payload.get("units", [])
    if not isinstance(units, list):
        return None
    for unit in units:
        if not isinstance(unit, dict):
            continue
        name = compact_text(unit.get("unit")).lower()
        if any(cue in name for cue in cues):
            return unit
    return None


def int_field(payload: dict[str, Any] | None, field: str) -> int | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(field)
    return value if isinstance(value, int) else None


def int_list_field(payload: dict[str, Any], field: str) -> list[int] | None:
    value = payload.get(field)
    if not isinstance(value, list):
        return None
    if not all(isinstance(item, int) for item in value):
        return None
    return value


def annotation_source_artifact(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return compact_text(payload.get("source_artifact"))


def annotation_source_hash(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return compact_text(payload.get("source_hash"))


def sha256_path(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def layout_observation_index(layout_audit_payload: Any) -> tuple[set[str], set[tuple[int, str]], str]:
    observation_ids: set[str] = set()
    page_issue_pairs: set[tuple[int, str]] = set()
    script_hash = ""
    if not isinstance(layout_audit_payload, dict):
        return observation_ids, page_issue_pairs, script_hash
    script_hash = compact_text(layout_audit_payload.get("script_hash"))
    observations = layout_audit_payload.get("observations", [])
    if not isinstance(observations, list):
        return observation_ids, page_issue_pairs, script_hash
    for item in observations:
        if not isinstance(item, dict):
            continue
        observation_id = compact_text(item.get("observation_id"))
        if observation_id:
            observation_ids.add(observation_id)
        page = item.get("page")
        issue_type = compact_text(item.get("issue_type"))
        if isinstance(page, int) and issue_type:
            page_issue_pairs.add((int(page), issue_type))
    return observation_ids, page_issue_pairs, script_hash


def is_layout_reference(item: dict[str, Any]) -> bool:
    return (
        compact_text(item.get("issue_type")).lower() == "layout"
        or compact_text(item.get("source")).lower() == "layout_audit"
        or nonempty(item.get("layout_audit_observation"))
        or nonempty(item.get("layout_audit_observation_id"))
    )


def audit_layout_reference(
    item: dict[str, Any],
    *,
    prefix: str,
    layout_audit_payload: Any | None,
    layout_observation_ids: set[str],
    layout_observation_keys: set[tuple[int, str]],
    layout_script_hash: str,
) -> list[str]:
    errors: list[str] = []
    if not layout_audit_payload:
        return [f"{prefix} is a layout observation but no layout_audit.json was provided"]

    for field in LAYOUT_AUDIT_FIELDS:
        if not nonempty(item.get(field)):
            errors.append(f"{prefix} missing `{field}` layout provenance")
    produced_by = compact_text(item.get("produced_by"))
    script_hash = compact_text(item.get("script_hash"))
    if produced_by and produced_by != LAYOUT_AUDIT_TOOL:
        errors.append(f"{prefix} produced_by must be `{LAYOUT_AUDIT_TOOL}`")
    if script_hash and layout_script_hash and script_hash != layout_script_hash:
        errors.append(f"{prefix} script_hash does not match layout_audit.script_hash")

    observation_id = compact_text(item.get("layout_audit_observation_id") or item.get("layout_audit_observation"))
    if observation_id:
        if observation_id not in layout_observation_ids:
            errors.append(f"{prefix} does not match a layout_audit observation_id")
        return errors

    page = item.get("page")
    issue_type = compact_text(item.get("layout_issue_type") or item.get("layout_observation_type"))
    if not isinstance(page, int):
        errors.append(f"{prefix} missing integer `page` for layout_audit linkage")
    if not issue_type:
        errors.append(f"{prefix} missing `layout_issue_type` for layout_audit linkage")
    if isinstance(page, int) and issue_type and (page, issue_type) not in layout_observation_keys:
        errors.append(f"{prefix} does not match a layout_audit observation")
    return errors


def audit_findings(payload: Any, layout_audit_payload: Any | None = None) -> tuple[list[str], list[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    findings = list_from_payload(payload, "findings")
    ids: set[str] = set()
    layout_observation_ids, layout_observation_keys, layout_script_hash = layout_observation_index(layout_audit_payload)

    for idx, finding in enumerate(findings, 1):
        prefix = f"finding #{idx}"
        finding_id = finding.get("id", f"<missing-{idx}>")
        if finding_id in ids:
            errors.append(f"duplicate finding id: {finding_id}")
        ids.add(str(finding_id))

        missing = sorted(field for field in REQUIRED_FINDING_FIELDS if not nonempty(finding.get(field)))
        for field in missing:
            errors.append(f"{prefix} {finding_id}: missing required field `{field}`")
        if not any(nonempty(finding.get(field)) for field in FINDING_SELF_CHECK_FIELDS):
            errors.append(f"{prefix} {finding_id}: missing required self-check field (`self_check` or `next_draft_question`)")

        severity = finding.get("severity")
        if severity not in SEVERITIES:
            errors.append(f"{prefix} {finding_id}: invalid severity `{severity}`")
        if severity in HIGH_RISK:
            for field in sorted(HIGH_RISK_FIELDS):
                if not nonempty(finding.get(field)):
                    errors.append(f"{prefix} {finding_id}: high-risk finding missing `{field}`")

        if "reported_value" in finding or "visible_computed_value" in finding or "delta" in finding:
            if severity != "Blocker":
                errors.append(f"{prefix} {finding_id}: numerical/table-value discrepancy must use severity `Blocker`, got `{severity}`")
            for field in ("reported_value", "visible_computed_value", "delta", "aggregation_caveat"):
                if not nonempty(finding.get(field)):
                    errors.append(f"{prefix} {finding_id}: numerical finding missing `{field}`")
            diagnosis = str(finding.get("diagnosis", ""))
            reported = str(finding.get("reported_value", ""))
            computed = str(finding.get("visible_computed_value", ""))
            if reported and computed and (reported not in diagnosis or computed not in diagnosis):
                errors.append(
                    f"{prefix} {finding_id}: numerical diagnosis must include both reported_value `{reported}` "
                    f"and visible_computed_value `{computed}`"
                )
            if any(word in diagnosis.lower() for word in DIRECTIVE_NUMERIC_WORDS) and reported and computed:
                if reported not in diagnosis or computed not in diagnosis:
                    errors.append(
                        f"{prefix} {finding_id}: numerical finding uses directive verdict language but omits the concrete reported/computed comparison"
                    )
            if any(phrase in diagnosis for phrase in VAGUE_NUMERIC_PHRASES):
                if reported not in diagnosis or computed not in diagnosis:
                    errors.append(
                        f"{prefix} {finding_id}: numerical finding uses vague language without concrete reported/computed values"
                    )

        if is_layout_reference(finding):
            errors.extend(
                audit_layout_reference(
                    finding,
                    prefix=f"{prefix} {finding_id}",
                    layout_audit_payload=layout_audit_payload,
                    layout_observation_ids=layout_observation_ids,
                    layout_observation_keys=layout_observation_keys,
                    layout_script_hash=layout_script_hash,
                )
            )

    return errors, warnings, ids


def artifact_only_finding_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return set()
    ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_id = compact_text(finding.get("id"))
        visibility = compact_text(finding.get("render_visibility")).lower()
        if finding_id and visibility == "artifact_only":
            ids.add(finding_id)
    return ids


def audit_annotations(
    payload: Any,
    *,
    coverage_payload: Any | None = None,
    manifest_payload: Any | None = None,
    finding_ids: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        annotations = list_from_payload(payload, "annotations")
    except ValueError as exc:
        return [str(exc)], warnings
    if not annotations:
        return ["annotations payload must contain at least one annotation"], warnings
    anchor_only_required = False
    if isinstance(payload, dict):
        schema_text = compact_text(
            payload.get("annotation_schema")
            or payload.get("annotations_schema")
            or payload.get("content_policy")
            or payload.get("mode")
        ).lower()
        anchor_only_required = schema_text in {"anchor-only", "anchor_only", "anchor-only-overlay"}

    by_level: Counter[str] = Counter()
    ids: set[str] = set()
    for idx, annotation in enumerate(annotations, 1):
        if not isinstance(annotation, dict):
            errors.append(f"annotation #{idx} must be an object")
            continue
        issue_id = compact_text(annotation.get("issue_id") or annotation.get("id"))
        if not issue_id:
            errors.append(f"annotation #{idx}: missing `issue_id`")
        elif issue_id in ids:
            errors.append(f"duplicate annotation issue_id: {issue_id}")
        ids.add(issue_id)
        has_matching_finding = bool(finding_ids and issue_id in finding_ids)
        duplicated_content_fields = sorted(
            field for field in ANNOTATION_CONTENT_FIELDS if nonempty(annotation.get(field))
        )
        if anchor_only_required and has_matching_finding and duplicated_content_fields:
            message = (
                f"annotation #{idx} {issue_id}: anchor-only annotations must not duplicate finding fields "
                f"{duplicated_content_fields}; keep review prose in findings.json and join at render time"
            )
            errors.append(message)
        unknown_fields = sorted(
            key
            for key, value in annotation.items()
            if nonempty(value) and key not in ANCHOR_ONLY_ANNOTATION_FIELDS and key not in ANNOTATION_CONTENT_FIELDS
        )
        if anchor_only_required and has_matching_finding and unknown_fields:
            warnings.append(
                f"annotation #{idx} {issue_id}: unexpected anchor-only fields {unknown_fields}; "
                "renderer will preserve them but they may cost context"
            )

        level = annotation_target_level(annotation)
        if level not in {"sentence", "paragraph", "section", "paper"}:
            errors.append(f"annotation #{idx} {issue_id or '<missing>'}: invalid or missing target level")
            continue
        by_level[level] += 1
        target_fields = {
            "sentence": ("sentence_id", "target_sentence"),
            "paragraph": ("paragraph_id", "target_paragraph"),
            "section": ("section_id", "target_section", "heading_id"),
            "paper": ("paper_id", "target_paper"),
        }[level]
        if not any(nonempty(annotation.get(field)) for field in target_fields):
            errors.append(f"annotation #{idx} {issue_id or '<missing>'}: missing target id for `{level}` annotation")
        if not has_matching_finding:
            for field in ("severity", "issue_type", "problem", "why"):
                if not nonempty(annotation.get(field)):
                    errors.append(f"annotation #{idx} {issue_id or '<missing>'}: missing `{field}`")
            if not any(nonempty(annotation.get(field)) for field in ("principle", "writing_principle")):
                errors.append(f"annotation #{idx} {issue_id or '<missing>'}: missing `principle` / `writing_principle`")
            if not any(nonempty(annotation.get(field)) for field in ("self_check", "next_draft_question", "task", "next_draft_task")):
                errors.append(f"annotation #{idx} {issue_id or '<missing>'}: missing self-check/task field")

    full_scope = False
    sentence_reviewed: int | None = None
    if isinstance(coverage_payload, dict):
        scope_text = " ".join(
            compact_text(value)
            for value in (
                coverage_payload.get("requested_scope"),
                coverage_payload.get("scope"),
                coverage_payload.get("review_scope"),
            )
        ).lower()
        full_scope = any(cue in scope_text for cue in FULL_REVIEW_CUES)
        if full_scope:
            sentence_unit = unit_by_cues(coverage_payload, SENTENCE_UNIT_CUES)
            paragraph_unit = unit_by_cues(coverage_payload, PARAGRAPH_UNIT_CUES)
            section_unit = unit_by_cues(coverage_payload, SECTION_UNIT_CUES)
            sentence_reviewed = int_field(sentence_unit, "reviewed")
            sentence_issues = int_field(sentence_unit, "with_issues")
            paragraph_reviewed = int_field(paragraph_unit, "reviewed")
            paragraph_issues = int_field(paragraph_unit, "with_issues")
            section_reviewed = int_field(section_unit, "reviewed")
            section_issues = int_field(section_unit, "with_issues")

            if sentence_reviewed and sentence_reviewed >= 100:
                minimum_sentence_annotations = max(1, int(sentence_reviewed * 0.15))
                if by_level["sentence"] < minimum_sentence_annotations:
                    errors.append(
                        "full-paper/逐句 coverage reports "
                        f"{sentence_reviewed} reviewed sentences, but annotations.json has only "
                        f"{by_level['sentence']} sentence annotations; this looks like top-issue sampling"
                    )
            if sentence_issues is not None and by_level["sentence"] < sentence_issues:
                errors.append(
                    f"coverage reports {sentence_issues} sentence issues, but annotations.json has "
                    f"{by_level['sentence']} sentence annotations"
                )
            if paragraph_reviewed and paragraph_reviewed >= 50:
                minimum_paragraph_annotations = max(1, int(paragraph_reviewed * 0.15))
                if by_level["paragraph"] < minimum_paragraph_annotations:
                    errors.append(
                        "full-paper paragraph coverage reports "
                        f"{paragraph_reviewed} reviewed paragraphs, but annotations.json has only "
                        f"{by_level['paragraph']} paragraph annotations"
                    )
            if paragraph_issues is not None and by_level["paragraph"] < paragraph_issues:
                errors.append(
                    f"coverage reports {paragraph_issues} paragraph issues, but annotations.json has "
                    f"{by_level['paragraph']} paragraph annotations"
                )
            if section_issues is not None and by_level["section"] < section_issues:
                errors.append(
                    f"coverage reports {section_issues} section issues, but annotations.json has "
                    f"{by_level['section']} section annotations"
                )

    if isinstance(manifest_payload, dict):
        overlay_source = manifest_payload.get("pdf_overlay")
        if isinstance(overlay_source, dict) and overlay_source.get("annotation_mode") in {"overlay-only", "pdfjs-overlay"}:
            manifest_source_hash = compact_text(overlay_source.get("source_hash"))
            manifest_source_artifact = compact_text(overlay_source.get("source_artifact"))
            annotations_source_hash = annotation_source_hash(payload)
            annotations_source_artifact = annotation_source_artifact(payload)
            if manifest_source_artifact and not annotations_source_artifact:
                errors.append(
                    "annotations.json missing `source_artifact`; overlay annotations must name the current source artifact"
                )
            if manifest_source_hash and not annotations_source_hash:
                errors.append(
                    "annotations.json missing `source_hash`; overlay annotations must be tied to the current source"
                )
            elif manifest_source_hash and annotations_source_hash and annotations_source_hash != manifest_source_hash:
                errors.append(
                    "annotations.json `source_hash` does not match render_manifest overlay source_hash; "
                    "regenerate annotations from the current manuscript instead of reusing a prior review"
                )
            if full_scope and sentence_reviewed and sentence_reviewed >= 100 and len(annotations) <= 50:
                warnings.append(
                    "PDF overlay has 50 or fewer annotations; verify this is not a sampled/top-issues run"
                )
    return errors, warnings


def audit_claims(payload: Any, finding_ids: set[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    claims = list_from_payload(payload, "claims")
    seen: set[str] = set()
    for idx, claim in enumerate(claims, 1):
        prefix = f"claim #{idx}"
        claim_id = claim.get("claim_id", f"<missing-{idx}>")
        if claim_id in seen:
            errors.append(f"duplicate claim id: {claim_id}")
        seen.add(str(claim_id))
        for field in sorted(REQUIRED_CLAIM_FIELDS):
            if not nonempty(claim.get(field)):
                errors.append(f"{prefix} {claim_id}: missing required field `{field}`")
        for linked in claim.get("linked_findings", []):
            if linked not in finding_ids:
                warnings.append(f"{prefix} {claim_id}: linked finding `{linked}` not present in findings")
    return errors, warnings


def audit_coverage(payload: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return ["coverage payload must be an object"], warnings
    units = payload.get("units", [])
    if not isinstance(units, list) or not units:
        errors.append("coverage.units must be a non-empty list")
    for idx, unit in enumerate(units, 1):
        for field in ("unit", "total", "reviewed", "with_issues", "clean", "skipped"):
            if field not in unit:
                errors.append(f"coverage unit #{idx}: missing `{field}`")
        skipped = unit.get("skipped")
        pending = unit.get("pending_in")
        if isinstance(skipped, int) and skipped > 0 and not pending:
            errors.append(f"coverage unit #{idx} {unit.get('unit')}: skipped > 0 without pending_in")
        total = unit.get("total")
        reviewed = unit.get("reviewed")
        if isinstance(total, int) and isinstance(reviewed, int) and reviewed > total:
            errors.append(f"coverage unit #{idx} {unit.get('unit')}: reviewed > total")
    passes = payload.get("reader_journey_passes", [])
    if passes:
        statuses = {item.get("pass"): item.get("status") for item in passes if isinstance(item, dict)}
        for pass_name in ("Pass 0", "Pass 1", "Pass 2", "Pass 3", "Pass 4", "Pass 5", "Pass 6"):
            if pass_name not in statuses:
                warnings.append(f"coverage.reader_journey_passes missing {pass_name}")
    else:
        warnings.append("coverage.reader_journey_passes absent")
    layout = payload.get("layout")
    if isinstance(layout, dict):
        pages_total = layout.get("pages_total")
        pages_checked = layout.get("pages_checked")
        pages_sampled = int_list_field(layout, "pages_sampled")
        pages_escalated = int_list_field(layout, "pages_escalated")
        full_layout_coverage = layout.get("full_layout_coverage")
        for field in ("pages_total", "pages_checked", "full_layout_coverage"):
            if field not in layout:
                errors.append(f"coverage.layout missing `{field}`")
        for field, value in (("pages_total", pages_total), ("pages_checked", pages_checked)):
            if value is not None and (not isinstance(value, int) or value < 0):
                errors.append(f"coverage.layout.{field} must be a non-negative integer")
        if "full_layout_coverage" in layout and not isinstance(full_layout_coverage, bool):
            errors.append("coverage.layout.full_layout_coverage must be true or false")
        if "pages_sampled" in layout and pages_sampled is None:
            errors.append("coverage.layout.pages_sampled must be a list of page numbers")
        if "pages_escalated" in layout and pages_escalated is None:
            errors.append("coverage.layout.pages_escalated must be a list of page numbers")
        if isinstance(pages_total, int) and isinstance(pages_checked, int) and pages_checked > pages_total:
            errors.append("coverage.layout.pages_checked > pages_total")
        if full_layout_coverage is True and isinstance(pages_total, int) and isinstance(pages_checked, int) and pages_checked < pages_total:
            errors.append("coverage.layout.full_layout_coverage is true but pages_checked < pages_total")
        if pages_sampled and full_layout_coverage is True and isinstance(pages_total, int) and len(set(pages_sampled)) < pages_total:
            errors.append("coverage.layout lists sampled pages but also claims full_layout_coverage")
        if full_layout_coverage is False and isinstance(pages_total, int) and isinstance(pages_checked, int) and pages_checked == pages_total:
            warnings.append("coverage.layout checked every page but full_layout_coverage is false")
    return errors, warnings


def int_set(values: list[Any]) -> set[int]:
    return {int(value) for value in values if isinstance(value, int)}


def resolve_layout_pdf_path(payload: dict[str, Any], layout_audit_path: Path | None = None) -> Path | None:
    pdf_text = compact_text(payload.get("pdf"))
    if not pdf_text:
        return None
    pdf_path = Path(pdf_text)
    if pdf_path.is_absolute():
        return pdf_path
    candidates: list[Path] = []
    if layout_audit_path:
        candidates.extend(parent / pdf_path for parent in (layout_audit_path.parent, *layout_audit_path.parents))
    candidates.append(Path.cwd() / pdf_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve() if candidates else pdf_path


def audit_layout_replay(payload: dict[str, Any], pdf_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not pdf_path.exists():
        return [f"layout_audit referenced PDF does not exist: {pdf_path}"], warnings
    pages_checked = payload.get("pages_checked")
    if not isinstance(pages_checked, list) or not all(isinstance(page, int) for page in pages_checked):
        return errors, warnings
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        warnings.append("layout_audit replay skipped because pdftotext is unavailable")
        return errors, warnings
    try:
        checker = importlib.import_module("check_page_layout")
        expected = checker.build_payload(pdf_path.resolve(), list(pages_checked), pdftotext)
    except Exception as exc:
        if "pypdf is required" in str(exc):
            warnings.append(f"layout_audit replay skipped: {exc}")
        else:
            errors.append(f"layout_audit replay failed: {exc}")
        return errors, warnings

    for field in ("tool", "tool_version", "script_hash", "pdf_hash", "pages_total", "pages_checked", "page_summaries", "observations"):
        if payload.get(field) != expected.get(field):
            errors.append(f"layout_audit.{field} does not match a fresh scripts/check_page_layout.py run")
    return errors, warnings


def audit_layout_audit_payload(
    payload: Any,
    coverage_payload: Any | None = None,
    layout_audit_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return ["layout_audit payload must be an object"], warnings
    if payload.get("tool") != LAYOUT_AUDIT_TOOL:
        errors.append(f"layout_audit.tool must be `{LAYOUT_AUDIT_TOOL}`")
    declared_script_hash = compact_text(payload.get("script_hash"))
    script_path = SCRIPT_DIR / "check_page_layout.py"
    if not declared_script_hash:
        errors.append("layout_audit missing `script_hash`")
    elif script_path.exists():
        actual_hash = sha256_path(script_path)
        if declared_script_hash != actual_hash:
            errors.append("layout_audit.script_hash does not match scripts/check_page_layout.py")
    for field in ("pdf", "pdf_hash", "pages_total", "pages_checked", "observations"):
        if field not in payload:
            errors.append(f"layout_audit missing `{field}`")
    declared_pdf_hash = compact_text(payload.get("pdf_hash"))
    if declared_pdf_hash and not re.fullmatch(r"sha256:[0-9a-fA-F]{8,}", declared_pdf_hash):
        errors.append("layout_audit.pdf_hash must look like sha256:<hex>")
    pdf_path = resolve_layout_pdf_path(payload, layout_audit_path)
    if declared_pdf_hash and pdf_path:
        if pdf_path.exists():
            actual_pdf_hash = sha256_path(pdf_path)
            if declared_pdf_hash != actual_pdf_hash:
                errors.append("layout_audit.pdf_hash does not match the referenced PDF")
    pages_total = payload.get("pages_total")
    pages_checked = payload.get("pages_checked")
    if not isinstance(pages_total, int) or pages_total < 0:
        errors.append("layout_audit.pages_total must be a non-negative integer")
    if not isinstance(pages_checked, list) or not all(isinstance(page, int) for page in pages_checked):
        errors.append("layout_audit.pages_checked must be a list of page numbers")
        pages_checked_set: set[int] = set()
    else:
        pages_checked_set = int_set(pages_checked)
        if isinstance(pages_total, int):
            invalid = sorted(page for page in pages_checked_set if page < 1 or page > pages_total)
            for page in invalid:
                errors.append(f"layout_audit page {page} outside 1-{pages_total}")
    observations = payload.get("observations", [])
    if not isinstance(observations, list):
        errors.append("layout_audit.observations must be a list")
        observations = []
    for idx, item in enumerate(observations, 1):
        if not isinstance(item, dict):
            errors.append(f"layout_audit observation #{idx} must be an object")
            continue
        for field in ("observation_id", "page", "issue_type", "severity", "observation", "evidence", "needs_main_review", "produced_by", "script_hash"):
            if field not in item:
                errors.append(f"layout_audit observation #{idx} missing `{field}`")
        observation_id = compact_text(item.get("observation_id"))
        if observation_id and not re.fullmatch(r"layout-p\d{3}-\d{3}", observation_id):
            errors.append(f"layout_audit observation #{idx} observation_id must look like `layout-p001-001`")
        page = item.get("page")
        if not isinstance(page, int):
            errors.append(f"layout_audit observation #{idx} page must be an integer")
        elif pages_checked_set and page not in pages_checked_set:
            errors.append(f"layout_audit observation #{idx} page {page} not in pages_checked")
        if item.get("produced_by") != LAYOUT_AUDIT_TOOL:
            errors.append(f"layout_audit observation #{idx} produced_by must be `{LAYOUT_AUDIT_TOOL}`")
        if declared_script_hash and item.get("script_hash") != declared_script_hash:
            errors.append(f"layout_audit observation #{idx} script_hash does not match layout_audit.script_hash")
        if "needs_main_review" in item and not isinstance(item.get("needs_main_review"), bool):
            errors.append(f"layout_audit observation #{idx} needs_main_review must be true or false")

    if isinstance(coverage_payload, dict) and isinstance(coverage_payload.get("layout"), dict):
        layout = coverage_payload["layout"]
        coverage_total = layout.get("pages_total")
        coverage_checked = layout.get("pages_checked")
        if isinstance(coverage_total, int) and isinstance(pages_total, int) and coverage_total != pages_total:
            errors.append("coverage.layout.pages_total does not match layout_audit.pages_total")
        if isinstance(coverage_checked, int) and len(pages_checked_set) != coverage_checked:
            errors.append("coverage.layout.pages_checked does not match layout_audit.pages_checked length")
        coverage_sampled = layout.get("pages_sampled")
        if isinstance(coverage_sampled, list) and coverage_sampled and int_set(coverage_sampled) != pages_checked_set:
            errors.append("coverage.layout.pages_sampled does not match layout_audit.pages_checked")
    if not errors and pdf_path:
        replay_errors, replay_warnings = audit_layout_replay(payload, pdf_path)
        errors.extend(replay_errors)
        warnings.extend(replay_warnings)
    return errors, warnings


def audit_pass_observations(payload: Any, layout_audit_payload: Any | None = None) -> tuple[list[str], list[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return ["pass_observations payload must be an object"], warnings, set()
    missing = sorted(key for key in PASS_OBSERVATION_KEYS if key not in payload)
    for key in missing:
        errors.append(f"pass_observations missing `{key}`")
    linked_ids: set[str] = set()
    observation_count = 0
    layout_observation_ids, layout_observation_keys, layout_script_hash = layout_observation_index(layout_audit_payload)
    for key in sorted(PASS_OBSERVATION_KEYS):
        items = payload.get(key, [])
        if not isinstance(items, list):
            errors.append(f"pass_observations.{key} must be a list")
            continue
        observation_count += len(items)
        for idx, item in enumerate(items, 1):
            if not isinstance(item, dict):
                errors.append(f"pass_observations.{key} item #{idx} must be an object")
                continue
            if not nonempty(item.get("location")):
                errors.append(f"pass_observations.{key} item #{idx} missing `location`")
            if key == "pass_5_submission_walk" and is_layout_reference(item):
                errors.extend(
                    audit_layout_reference(
                        item,
                        prefix=f"pass_observations.{key} item #{idx}",
                        layout_audit_payload=layout_audit_payload,
                        layout_observation_ids=layout_observation_ids,
                        layout_observation_keys=layout_observation_keys,
                        layout_script_hash=layout_script_hash,
                    )
                )
            for linked in item.get("linked_findings", []):
                linked_ids.add(str(linked))
    if observation_count == 0:
        warnings.append("pass_observations contains no observations")
    return errors, warnings, linked_ids


def audit_manifest(payload: Any, finding_ids: set[str]) -> tuple[list[str], list[str], set[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return ["render manifest must be an object"], warnings, set(), set()
    for field in sorted(REQUIRED_MANIFEST_FIELDS):
        if field not in payload:
            errors.append(f"render manifest missing `{field}`")
    deferred = set(str(item) for item in payload.get("deferred_findings", []) if item)
    detailed_deferred = payload.get("deferred_findings_with_reason", [])
    if detailed_deferred:
        if not isinstance(detailed_deferred, list):
            errors.append("render manifest `deferred_findings_with_reason` must be a list")
        else:
            detailed_ids: set[str] = set()
            for idx, item in enumerate(detailed_deferred, 1):
                if not isinstance(item, dict):
                    errors.append(f"render manifest deferred_findings_with_reason item #{idx} must be an object")
                    continue
                finding_id = compact_text(item.get("id"))
                reason = compact_text(item.get("reason"))
                if not finding_id:
                    errors.append(f"render manifest deferred_findings_with_reason item #{idx} missing `id`")
                else:
                    detailed_ids.add(finding_id)
                    deferred.add(finding_id)
                if not reason:
                    errors.append(f"render manifest deferred_findings_with_reason item #{idx} missing `reason`")
            missing_detail = sorted(item for item in deferred if item not in detailed_ids)
            if missing_detail:
                warnings.append(
                    "render manifest deferred_findings should include reason details for: "
                    + ", ".join(missing_detail)
                )
    unknown_deferred = sorted(item for item in deferred if item not in finding_ids)
    for item in unknown_deferred:
        errors.append(f"render manifest defers unknown finding id `{item}`")
    rendered_section_ids: set[str] = set()
    sections = payload.get("sections", [])
    if isinstance(sections, list):
        rendered = [section for section in sections if isinstance(section, dict) and section.get("status") == "rendered"]
        rendered_section_ids = {str(section.get("id")) for section in rendered if section.get("id")}
        if not rendered:
            warnings.append("render manifest has no rendered sections")
    if "paper-reader" in rendered_section_ids:
        pdf_overlay = payload.get("pdf_overlay")
        if isinstance(pdf_overlay, dict):
            for field in sorted(PDF_OVERLAY_MANIFEST_FIELDS):
                if not nonempty(pdf_overlay.get(field)):
                    errors.append(f"render manifest pdf_overlay missing `{field}`")
            if pdf_overlay.get("mode") != "pdf-overlay":
                errors.append("render manifest pdf_overlay mode must be `pdf-overlay`")
            if pdf_overlay.get("annotation_mode") not in {"overlay-only", "pdfjs-overlay"}:
                errors.append("render manifest pdf_overlay annotation_mode must be `pdfjs-overlay`")
            source_hash = compact_text(pdf_overlay.get("source_hash"))
            if source_hash and not HASH_RE.fullmatch(source_hash):
                errors.append("render manifest pdf_overlay source_hash must look like sha1:<hex> or sha256:<hex>")
            integrity_check = compact_text(pdf_overlay.get("source_integrity_check"))
            if integrity_check not in SOURCE_INTEGRITY_CHECKS:
                errors.append(
                    "render manifest pdf_overlay source_integrity_check must be one of "
                    "`verified`, `mismatch`, or `skipped`"
                )
            elif integrity_check == "mismatch":
                errors.append("render manifest pdf_overlay source_integrity_check reports `mismatch`")
        else:
            errors.append("render manifest marks #paper-reader as rendered but missing `pdf_overlay` provenance object")
    return errors, warnings, deferred, rendered_section_ids


def html_text(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def signal_render_key(signal: dict[str, Any], idx: int) -> str:
    signal_id = compact_text(signal.get("signal_id")) or f"signal #{idx}"
    table = compact_text(signal.get("table_id"))
    row = compact_text(signal.get("row_label"))
    reported = compact_text(signal.get("reported_value"))
    computed = compact_text(signal.get("visible_computed_value"))
    return f"{signal_id} {table} {row} reported={reported} computed={computed}".strip()


def audit_numeric_signal_payload(payload: Any) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    warnings: list[str] = []
    render_required: list[dict[str, Any]] = []
    if not isinstance(payload, dict) or not isinstance(payload.get("signals"), list):
        return ["numeric_audit.json must be an object with a `signals` list"], warnings, render_required

    count = payload.get("signal_count")
    if isinstance(count, int) and count != len(payload["signals"]):
        errors.append(f"numeric_audit.json signal_count {count} != signals length {len(payload['signals'])}")
    for idx, signal in enumerate(payload["signals"], 1):
        if not isinstance(signal, dict):
            errors.append(f"numeric_audit.json signal #{idx} must be an object")
            continue
        for field in ("table_id", "row_label", "reported_value", "visible_computed_value", "delta", "aggregation_caveat"):
            if not nonempty(signal.get(field)):
                errors.append(f"numeric_audit.json signal #{idx} missing `{field}`")
        render_required_value = signal.get("render_required", True)
        if render_required_value not in {True, False}:
            errors.append(f"numeric_audit.json signal #{idx} `render_required` must be true or false")
        if render_required_value:
            required_severity = signal.get("required_severity")
            if required_severity != "Blocker":
                errors.append(
                    f"numeric_audit.json signal #{idx} render_required signal must set `required_severity` to `Blocker`, got `{required_severity}`"
                )
            render_required.append(signal)
    return errors, warnings, render_required


def audit_numeric_signal_rendering(signals: list[dict[str, Any]], html: str) -> list[str]:
    errors: list[str] = []
    parser = AriadneHTMLParser()
    parser.feed(html)
    for idx, signal in enumerate(signals, 1):
        reported = compact_text(signal.get("reported_value"))
        computed = compact_text(signal.get("visible_computed_value"))
        table = compact_text(signal.get("table_id"))
        row = compact_text(signal.get("row_label"))
        signal_id = compact_text(signal.get("signal_id"))
        missing: list[str] = []
        for label, needle in (("table_id", table), ("reported_value", reported), ("visible_computed_value", computed)):
            if needle and needle not in html:
                missing.append(f"{label} `{needle}`")
        row_tokens = [token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", row) if len(token) >= 3]
        if row_tokens and not any(token in html for token in row_tokens[:4]):
            missing.append(f"row_label token from `{row}`")
        if missing:
            errors.append(
                "numeric signal not rendered in HTML: "
                + signal_render_key(signal, idx)
                + " missing "
                + ", ".join(missing)
            )
            continue
        required_severity = compact_text(signal.get("required_severity"))
        if required_severity == "Blocker":
            matching_items = []
            for item in parser.issue_items:
                if item.get("issue_type") != "numeric":
                    continue
                item_text = compact_text(item.get("text", ""))
                has_values = bool(reported and reported in item_text and computed and computed in item_text)
                has_location = bool((table and table in item_text) or any(token in item_text for token in row_tokens[:4]))
                if has_values and has_location:
                    matching_items.append(item)
            if not any(item.get("severity", "").lower() == "blocker" for item in matching_items):
                errors.append(
                    "numeric signal rendered without nearby Blocker severity: "
                    + signal_render_key(signal, idx)
                )
    return errors


def audit_issue_artifact_payload(payload: Any, path: Path) -> tuple[list[str], list[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    issue_ids: set[str] = set()
    label = path.name
    if not isinstance(payload, dict):
        return [f"{label}: issue artifact must be an object"], warnings, issue_ids

    if payload.get("artifact_type") != ISSUE_ARTIFACT_TYPE:
        errors.append(f"{label}: artifact_type must be `{ISSUE_ARTIFACT_TYPE}`")
    domain = compact_text(payload.get("domain"))
    if domain not in ISSUE_DOMAINS:
        errors.append(f"{label}: invalid or missing domain `{domain}`")
    if payload.get("context_policy") != ISSUE_ARTIFACT_CONTEXT_POLICY:
        errors.append(f"{label}: context_policy must be `{ISSUE_ARTIFACT_CONTEXT_POLICY}`")
    status = compact_text(payload.get("status") or "completed")
    if status not in ISSUE_STATUSES:
        errors.append(f"{label}: invalid status `{status}`")

    source_artifacts = payload.get("source_artifacts")
    if source_artifacts is None:
        source_artifacts = []
    if not isinstance(source_artifacts, list):
        errors.append(f"{label}: source_artifacts must be a list")
    else:
        for idx, item in enumerate(source_artifacts, 1):
            prefix = f"{label}: source_artifacts #{idx}"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            if not nonempty(item.get("path")):
                errors.append(f"{prefix} missing path")
            source_hash = compact_text(item.get("hash"))
            if not source_hash:
                errors.append(f"{prefix} missing hash")
            elif not HASH_RE.match(source_hash):
                errors.append(f"{prefix} hash must look like sha1:<hex> or sha256:<hex>")
            else:
                source_path_text = compact_text(item.get("path"))
                if source_path_text:
                    source_path = Path(source_path_text)
                    if not source_path.is_absolute():
                        source_path = (path.parent / source_path).resolve()
                    if source_path.exists() and source_path.is_file():
                        actual_hash = sha256_path(source_path)
                        if source_hash.startswith("sha256:") and source_hash != actual_hash:
                            errors.append(f"{prefix} hash mismatch for {source_path}")
            policy = item.get("context_policy")
            if policy and policy not in {TOOL_ONLY_CONTEXT_POLICY, ISSUE_ARTIFACT_CONTEXT_POLICY}:
                errors.append(f"{prefix} invalid context_policy `{policy}`")

    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        errors.append(f"{label}: coverage must be an object")
    else:
        for field in ("checked", "issues", "skipped"):
            value = coverage.get(field)
            if not isinstance(value, int) or value < 0:
                errors.append(f"{label}: coverage.{field} must be a non-negative integer")

    issues = payload.get("issues")
    if not isinstance(issues, list):
        errors.append(f"{label}: issues must be a list")
        return errors, warnings, issue_ids
    if status == "skipped":
        if issues:
            errors.append(f"{label}: skipped issue artifact must have an empty issues list")
        if not nonempty(payload.get("skip_reason")):
            errors.append(f"{label}: skipped issue artifact missing skip_reason")
    if isinstance(coverage, dict):
        issue_count = coverage.get("issues")
        if isinstance(issue_count, int) and issue_count != len(issues):
            warnings.append(f"{label}: coverage.issues={issue_count} but issues list has {len(issues)} item(s)")

    for idx, issue in enumerate(issues, 1):
        prefix = f"{label}: issue #{idx}"
        if not isinstance(issue, dict):
            errors.append(f"{prefix} must be an object")
            continue
        local_id = compact_text(issue.get("local_id") or issue.get("id") or issue.get("issue_id"))
        if not local_id:
            errors.append(f"{prefix} missing local_id")
        elif local_id in issue_ids:
            errors.append(f"{label}: duplicate local_id `{local_id}`")
        issue_ids.add(local_id)

        severity = issue.get("severity")
        if severity not in SEVERITIES:
            errors.append(f"{prefix} {local_id or '<missing>'}: invalid severity `{severity}`")
        for field in sorted(REQUIRED_ISSUE_FIELDS):
            if not nonempty(issue.get(field)):
                errors.append(f"{prefix} {local_id or '<missing>'}: missing `{field}`")
        evidence_refs = issue.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            errors.append(f"{prefix} {local_id or '<missing>'}: evidence_refs must be a non-empty list")
        render_hint = issue.get("render_hint")
        if not isinstance(render_hint, dict):
            errors.append(f"{prefix} {local_id or '<missing>'}: render_hint must be an object")
        elif not nonempty(render_hint.get("display_group")):
            errors.append(f"{prefix} {local_id or '<missing>'}: render_hint missing display_group")
        if severity in HIGH_RISK:
            for field in sorted(HIGH_RISK_ISSUE_FIELDS):
                if not nonempty(issue.get(field)):
                    errors.append(f"{prefix} {local_id or '<missing>'}: high-risk issue missing `{field}`")
    return errors, warnings, issue_ids


def audit_issue_artifacts(issue_artifacts_dir: Path | None, *, legacy_allowed: bool = True) -> tuple[list[str], list[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    ids: set[str] = set()
    if issue_artifacts_dir is None:
        return errors, warnings, ids
    if not issue_artifacts_dir.exists():
        if legacy_allowed:
            warnings.append("legacy bundle: issue_artifacts/ absent; recommend migration")
            return errors, warnings, ids
        return [f"issue_artifacts directory does not exist: {issue_artifacts_dir}"], warnings, ids
    if not issue_artifacts_dir.is_dir():
        return [f"issue_artifacts path is not a directory: {issue_artifacts_dir}"], warnings, ids
    paths = sorted(issue_artifacts_dir.glob("*_issues.json"))
    paths.extend(sorted(issue_artifacts_dir.glob("*_issues.jsonl")))
    compiled_jsonl_shards: set[str] = set()
    compiled_index = issue_artifacts_dir / "compiled_issue_index.json"
    if compiled_index.exists():
        try:
            index_payload = load_json(compiled_index)
        except Exception as exc:
            errors.append(f"compiled_issue_index.json: could not read JSON: {exc}")
        else:
            if not isinstance(index_payload, dict):
                errors.append("compiled_issue_index.json: compiled issue index must be an object")
            elif index_payload.get("artifact_type") != COMPILED_ISSUE_INDEX_TYPE:
                errors.append(f"compiled_issue_index.json: artifact_type must be `{COMPILED_ISSUE_INDEX_TYPE}`")
            else:
                raw_shards = index_payload.get("normalized_jsonl_shards")
                if isinstance(raw_shards, list):
                    for item in raw_shards:
                        if isinstance(item, dict) and nonempty(item.get("path")):
                            compiled_jsonl_shards.add(Path(compact_text(item.get("path"))).name)
                elif raw_shards is not None:
                    errors.append("compiled_issue_index.json: normalized_jsonl_shards must be a list")
    if not paths:
        warnings.append("issue_artifacts/ exists but contains no *_issues.json or *_issues.jsonl files")
    for path in paths:
        if path.suffix == ".jsonl":
            if path.name not in compiled_jsonl_shards:
                warnings.append(f"{path.name}: JSONL issue shard not schema-audited yet; compiler should normalize it")
            continue
        try:
            payload = load_json(path)
        except Exception as exc:
            errors.append(f"{path.name}: could not read issue artifact JSON: {exc}")
            continue
        artifact_errors, artifact_warnings, local_ids = audit_issue_artifact_payload(payload, path)
        errors.extend(artifact_errors)
        warnings.extend(artifact_warnings)
        domain = compact_text(payload.get("domain"))
        for local_id in local_ids:
            scoped = f"{domain}:{local_id}"
            if scoped in ids:
                errors.append(f"duplicate scoped issue id `{scoped}`")
            ids.add(scoped)
    return errors, warnings, ids


def html_ids(path: Path) -> tuple[set[str], list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    parser = AriadneHTMLParser()
    parser.feed(text)
    errors, warnings = audit_html(path)
    return parser.ids, errors, warnings


def audit_forbidden_artifacts(
    *,
    bundle_path: Path | None = None,
    html_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    checked_dirs: set[Path] = set()
    if bundle_path:
        checked_dirs.add(bundle_path.resolve())
        reported_bundle_paths: set[Path] = set()
        for filename in FORBIDDEN_BUNDLE_FILENAMES:
            candidate = bundle_path / filename
            if candidate.exists():
                errors.append(f"artifact bundle contains generated helper script `{filename}`; write JSON artifacts directly or use versioned scripts/")
                reported_bundle_paths.add(candidate.resolve())
        for candidate in bundle_path.glob("*.py"):
            if candidate.name not in {"__init__.py"} and candidate.resolve() not in reported_bundle_paths:
                errors.append(f"artifact bundle contains Python helper `{candidate.name}`; generated bundle-local scripts are not allowed")
    for path in (html_path,):
        if path:
            checked_dirs.add(path.resolve().parent)
    for directory in sorted(checked_dirs):
        if not directory.exists() or not directory.is_dir():
            continue
        preview_candidates: set[Path] = set()
        for pattern in FORBIDDEN_PREVIEW_PATTERNS:
            for candidate in directory.glob(pattern):
                preview_candidates.add(candidate.resolve())
        for candidate in sorted(preview_candidates):
            errors.append(f"forbidden duplicate paper HTML artifact exists: {candidate}")
        for filename in FORBIDDEN_SIBLING_NAMES:
            candidate = directory / filename
            if candidate.exists():
                errors.append(f"forbidden plaintext paper dump exists next to artifacts: {candidate}")
    return errors, warnings


def audit_sharded_phase_completion(bundle_path: Path | None, *, issue_artifacts_dir: Path | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if bundle_path is None:
        return errors, warnings
    shard_manifest = bundle_path / "phase_a_shard_manifest.json"
    if not shard_manifest.exists():
        return errors, warnings
    try:
        payload = load_json(shard_manifest)
    except Exception as exc:
        return [f"phase_a_shard_manifest.json could not be read: {exc}"], warnings
    if not isinstance(payload, dict):
        return ["phase_a_shard_manifest.json must be a JSON object"], warnings
    if payload.get("context_policy") != "model_readable_shard_manifest_only":
        errors.append("phase_a_shard_manifest.json has unexpected context_policy")
    phase_b_context = bundle_path / "phase_b_context.json"
    issue_dir = issue_artifacts_dir or bundle_path / "issue_artifacts"
    whole_paper = issue_dir / "whole_paper_findings.jsonl"
    if not phase_b_context.exists():
        errors.append("sharded Phase A was used but phase_b_context.json is missing; mandatory Phase B synthesis was not prepared")
    if not whole_paper.exists():
        errors.append("sharded Phase A was used but whole_paper_findings.jsonl is missing; mandatory Phase B synthesis was not completed")
    return errors, warnings


def audit_artifacts(
    findings_path: Path,
    claims_path: Path | None = None,
    numeric_audit_path: Path | None = None,
    coverage_path: Path | None = None,
    manifest_path: Path | None = None,
    pass_observations_path: Path | None = None,
    html_path: Path | None = None,
    annotations_path: Path | None = None,
    bundle_path: Path | None = None,
    layout_audit_path: Path | None = None,
    issue_artifacts_dir: Path | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if issue_artifacts_dir is None and bundle_path is not None:
        issue_artifacts_dir = bundle_path / "issue_artifacts"

    forbidden_errors, forbidden_warnings = audit_forbidden_artifacts(
        bundle_path=bundle_path,
        html_path=html_path,
    )
    errors.extend(forbidden_errors)
    warnings.extend(forbidden_warnings)
    sharded_errors, sharded_warnings = audit_sharded_phase_completion(bundle_path, issue_artifacts_dir=issue_artifacts_dir)
    errors.extend(sharded_errors)
    warnings.extend(sharded_warnings)

    deferred: set[str] = set()
    rendered_section_ids: set[str] = set()
    required_numeric_signals: list[dict[str, Any]] = []
    coverage_payload: Any | None = None
    manifest_payload: Any | None = None
    layout_audit_payload: Any | None = None
    if issue_artifacts_dir:
        issue_errors, issue_warnings, _ = audit_issue_artifacts(issue_artifacts_dir)
        errors.extend(issue_errors)
        warnings.extend(issue_warnings)
    if coverage_path:
        coverage_payload = load_json(coverage_path)
        coverage_errors, coverage_warnings = audit_coverage(coverage_payload)
        errors.extend(coverage_errors)
        warnings.extend(coverage_warnings)
    if layout_audit_path:
        layout_audit_payload = load_json(layout_audit_path)
        layout_errors, layout_warnings = audit_layout_audit_payload(layout_audit_payload, coverage_payload, layout_audit_path)
        errors.extend(layout_errors)
        warnings.extend(layout_warnings)
    elif isinstance(coverage_payload, dict) and isinstance(coverage_payload.get("layout"), dict):
        layout = coverage_payload["layout"]
        pages_checked = layout.get("pages_checked")
        if isinstance(pages_checked, int) and pages_checked > 0:
            errors.append("coverage.layout declares checked pages but no layout_audit.json was provided")

    findings_payload = load_json(findings_path)
    finding_errors, finding_warnings, finding_ids = audit_findings(findings_payload, layout_audit_payload)
    errors.extend(finding_errors)
    warnings.extend(finding_warnings)
    deferred.update(artifact_only_finding_ids(findings_payload))

    if claims_path:
        claim_errors, claim_warnings = audit_claims(load_json(claims_path), finding_ids)
        errors.extend(claim_errors)
        warnings.extend(claim_warnings)
    if numeric_audit_path:
        numeric_errors, numeric_warnings, required_numeric_signals = audit_numeric_signal_payload(load_json(numeric_audit_path))
        errors.extend(numeric_errors)
        warnings.extend(numeric_warnings)
    if manifest_path:
        manifest_payload = load_json(manifest_path)
        manifest_errors, manifest_warnings, manifest_deferred, rendered_section_ids = audit_manifest(manifest_payload, finding_ids)
        deferred.update(manifest_deferred)
        errors.extend(manifest_errors)
        warnings.extend(manifest_warnings)
    if annotations_path:
        annotation_errors, annotation_warnings = audit_annotations(
            load_json(annotations_path),
            coverage_payload=coverage_payload,
            manifest_payload=manifest_payload,
            finding_ids=finding_ids,
        )
        errors.extend(annotation_errors)
        warnings.extend(annotation_warnings)
    if pass_observations_path:
        pass_errors, pass_warnings, linked_ids = audit_pass_observations(load_json(pass_observations_path), layout_audit_payload)
        errors.extend(pass_errors)
        warnings.extend(pass_warnings)
        for linked in sorted(linked_ids):
            if linked not in finding_ids:
                warnings.append(f"pass_observations linked finding `{linked}` not present in findings")
    if html_path:
        rendered_text = html_text(html_path)
        ids, html_errors, html_warnings = html_ids(html_path)
        errors.extend(f"html: {item}" for item in html_errors)
        warnings.extend(f"html: {item}" for item in html_warnings)
        errors.extend(audit_numeric_signal_rendering(required_numeric_signals, rendered_text))
        missing_sections = sorted(section_id for section_id in rendered_section_ids if section_id not in ids)
        for section_id in missing_sections:
            errors.append(f"render manifest marks section `#{section_id}` as rendered, but HTML has no matching id")
        missing = sorted(finding_id for finding_id in finding_ids if finding_id not in ids and finding_id not in deferred)
        for finding_id in missing:
            errors.append(f"finding `{finding_id}` is in findings.json but not rendered in HTML and not deferred")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Directory containing findings.json, annotations.json, claims.json, numeric_audit.json, layout_audit.json, coverage.json, render_manifest.json, and pass_observations.json")
    parser.add_argument("--findings", type=Path)
    parser.add_argument("--claims", type=Path)
    parser.add_argument("--numeric-audit", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pass-observations", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--layout-audit", type=Path)
    parser.add_argument("--issue-artifacts", type=Path, help="Directory containing curated *_issues.json artifacts")
    parser.add_argument("--html", type=Path)
    args = parser.parse_args(argv)

    findings = args.findings
    claims = args.claims
    numeric_audit = args.numeric_audit
    coverage = args.coverage
    manifest = args.manifest
    pass_observations = args.pass_observations
    annotations = args.annotations
    layout_audit = args.layout_audit
    issue_artifacts = args.issue_artifacts
    if args.bundle:
        bundle = args.bundle
        findings = findings or bundle / "findings.json"
        claims = claims or bundle / "claims.json"
        numeric_audit = numeric_audit or bundle / "numeric_audit.json"
        coverage = coverage or bundle / "coverage.json"
        manifest = manifest or bundle / "render_manifest.json"
        pass_observations = pass_observations or bundle / "pass_observations.json"
        annotations = annotations or bundle / "annotations.json"
        layout_candidate = bundle / "layout_audit.json"
        layout_audit = layout_audit or (layout_candidate if layout_candidate.exists() else None)
        issue_artifacts = issue_artifacts or bundle / "issue_artifacts"
    if findings is None:
        if issue_artifacts is None:
            parser.error("--findings is required unless --bundle is provided")
        errors, warnings, _ids = audit_issue_artifacts(issue_artifacts, legacy_allowed=False)
        for warning in warnings:
            print(f"WARNING: {warning}")
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if errors:
            return 1
        print("Ariadne issue artifact audit passed.")
        return 0

    errors, warnings = audit_artifacts(
        findings,
        claims,
        numeric_audit,
        coverage,
        manifest,
        pass_observations,
        args.html,
        annotations,
        args.bundle,
        layout_audit,
        issue_artifacts,
    )
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Ariadne review artifact audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
