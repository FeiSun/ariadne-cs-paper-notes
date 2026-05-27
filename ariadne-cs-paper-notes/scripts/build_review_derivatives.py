#!/usr/bin/env python3
"""Derive Ariadne coverage, render manifest, and pass observations from JSON artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


PAPER_READER_GLOBAL_SECTIONS = [
    "paper-reader",
    "global-findings",
    "coverage-receipt",
]
PAPER_READER_ONLY_SECTIONS = [
    "paper-reader",
    "coverage-receipt",
]
RENDER_MODES = {
    "paper-reader-with-global-findings": PAPER_READER_GLOBAL_SECTIONS,
    "paper-reader-only": PAPER_READER_ONLY_SECTIONS,
}
PASS_KEYS = {
    "pass_0_engagement_contract": "Pass 0",
    "pass_1_cold_start_skim": "Pass 1",
    "pass_2_linear_deep_read": "Pass 2",
    "pass_3_section_reflections": "Pass 3",
    "pass_4_whole_paper_argument": "Pass 4",
    "pass_5_submission_walk": "Pass 5",
    "pass_6_output_calibration": "Pass 6",
}

PROSE_DOMAINS = {"prose", "whole_paper"}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_list_payload(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [item for item in payload[key] if isinstance(item, dict)]
    return []


def compact_text(value: Any, *, max_chars: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def severity_counts(findings: list[dict[str, Any]]) -> Counter[str]:
    return Counter(compact_text(item.get("severity")) for item in findings if compact_text(item.get("severity")))


def is_artifact_only(item: dict[str, Any]) -> bool:
    return compact_text(
        item.get("render_visibility")
        or item.get("visibility")
        or item.get("student_visibility"),
        max_chars=80,
    ).lower() in {"artifact_only", "audit_only", "hidden"}


def annotation_counts(annotations: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in annotations:
        level = compact_text(item.get("target_level")).lower()
        if not level:
            if item.get("sentence_id") or item.get("target_sentence"):
                level = "sentence"
            elif item.get("paragraph_id") or item.get("target_paragraph"):
                level = "paragraph"
            elif item.get("section_id") or item.get("target_section"):
                level = "section"
            else:
                level = "paper"
        counts[level] += 1
    return counts


def issue_artifact_paths(issues_dir: Path | None) -> list[Path]:
    if issues_dir is None or not issues_dir.exists():
        return []
    return sorted(path for path in issues_dir.glob("*_issues.json") if path.name != "compiled_issue_index.json")


def load_issue_artifacts(issues_dir: Path | None) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in issue_artifact_paths(issues_dir):
        payload = load_json(path)
        if isinstance(payload, dict):
            payload["_path"] = str(path)
            artifacts.append(payload)
    return artifacts


def issue_artifact_summary(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in artifacts:
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        rows.append(
            {
                "domain": compact_text(payload.get("domain")),
                "status": compact_text(payload.get("status")) or "unknown",
                "checked": coverage.get("checked", 0),
                "issues": coverage.get("issues", len(payload.get("issues", []) if isinstance(payload.get("issues"), list) else [])),
                "skip_reason": compact_text(payload.get("skip_reason")),
            }
        )
    return rows


def unit_row(unit: str, total: int, reviewed: int, with_issues: int, *, pending_in: str = "") -> dict[str, Any]:
    clean = max(reviewed - with_issues, 0)
    skipped = max(total - reviewed, 0)
    row: dict[str, Any] = {
        "unit": unit,
        "total": total,
        "reviewed": reviewed,
        "with_issues": with_issues,
        "clean": clean,
        "skipped": skipped,
    }
    if skipped:
        row["pending_in"] = pending_in or "not available in compiled artifacts"
    return row


def issue_count_by_domain(issue_artifacts: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for artifact in issue_artifacts:
        domain = compact_text(artifact.get("domain"))
        issues = artifact.get("issues") if isinstance(artifact.get("issues"), list) else []
        counts[domain] += len([issue for issue in issues if isinstance(issue, dict)])
    return counts


def has_completed_specialist_artifact(issue_artifacts: list[dict[str, Any]]) -> bool:
    for artifact in issue_artifacts:
        domain = compact_text(artifact.get("domain"))
        if not domain or domain in PROSE_DOMAINS:
            continue
        status = compact_text(artifact.get("status")).lower()
        coverage = artifact.get("coverage") if isinstance(artifact.get("coverage"), dict) else {}
        checked = int(coverage.get("checked", 0) or 0)
        if status in {"completed", "partial"} or checked > 0:
            return True
    return False


def phase_a_coverage(phase_a_status: dict[str, Any] | None) -> dict[str, Any]:
    coverage = phase_a_status.get("coverage") if isinstance(phase_a_status, dict) else {}
    return coverage if isinstance(coverage, dict) else {}


def build_reader_journey_passes(
    *,
    phase_a_status: dict[str, Any] | None,
    phase_b_context: dict[str, Any] | None,
    findings: list[dict[str, Any]],
    issue_artifacts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    coverage = phase_a_coverage(phase_a_status)
    phase_b_coverage = phase_b_context.get("coverage") if isinstance(phase_b_context, dict) else {}
    if not isinstance(phase_b_coverage, dict):
        phase_b_coverage = {}
    source_domains = set()
    for finding in findings:
        source_ids = finding.get("source_issue_ids")
        if isinstance(source_ids, list):
            for source_id in source_ids:
                text = compact_text(source_id)
                if ":" in text:
                    source_domains.add(text.split(":", 1)[0])
    pass_statuses = {
        "Pass 0": "done",
        "Pass 1": "done" if coverage.get("cold_skim_present") else "pending",
        "Pass 2": "done" if coverage.get("sentence_review_receipt_complete") else "pending",
        "Pass 3": "done" if int(coverage.get("sections_pending", 0) or 0) == 0 and int(coverage.get("sections_total", 0) or 0) > 0 else "pending",
        "Pass 4": "done"
        if phase_b_coverage.get("sections_summarized") or "whole_paper" in source_domains
        else "pending",
        "Pass 5": "done" if has_completed_specialist_artifact(issue_artifacts) else "skipped",
        "Pass 6": "pending",
    }
    return [{"pass": pass_name, "status": pass_statuses[pass_name]} for pass_name in PASS_KEYS.values()]


def build_coverage(
    *,
    findings: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    issue_artifacts: list[dict[str, Any]],
    layout_audit: dict[str, Any] | None,
    phase_a_status: dict[str, Any] | None,
    phase_b_context: dict[str, Any] | None,
    requested_scope: str,
) -> dict[str, Any]:
    counts = annotation_counts(annotations)
    phase_a = phase_a_coverage(phase_a_status)
    domain_counts = issue_count_by_domain(issue_artifacts)
    sentence_total = int(phase_a.get("sentences_total", 0) or 0)
    sentence_reviewed = int(phase_a.get("sentences_reviewed", 0) or 0)
    paragraph_total = int(phase_a.get("paragraphs_total", 0) or 0)
    paragraph_reviewed = int(phase_a.get("paragraphs_reviewed", 0) or 0)
    section_total = int(phase_a.get("sections_total", 0) or 0)
    section_reviewed = int(phase_a.get("sections_completed", 0) or 0)
    units = [
        unit_row("Findings", len(findings), len(findings), len(findings)),
        unit_row(
            "Sentences",
            sentence_total or counts.get("sentence", 0),
            sentence_reviewed or counts.get("sentence", 0),
            domain_counts.get("prose", counts.get("sentence", 0)),
            pending_in="phase_a_resume_status.json",
        ),
        unit_row(
            "Paragraphs",
            paragraph_total or counts.get("paragraph", 0),
            paragraph_reviewed or counts.get("paragraph", 0),
            counts.get("paragraph", 0),
            pending_in="phase_a_resume_status.json",
        ),
        unit_row(
            "Sections/headings",
            section_total or counts.get("section", 0),
            section_reviewed or counts.get("section", 0),
            counts.get("section", 0),
            pending_in="phase_a_resume_status.json",
        ),
        unit_row("Paper-level notes", counts.get("paper", 0), counts.get("paper", 0), counts.get("paper", 0)),
    ]
    issue_rows = issue_artifact_summary(issue_artifacts)
    if issue_rows:
        total_checked = sum(int(row.get("checked") or 0) for row in issue_rows)
        issue_count = sum(int(row.get("issues") or 0) for row in issue_rows)
        units.append(unit_row("Specialist issue artifacts", total_checked, total_checked, issue_count))

    payload: dict[str, Any] = {
        "generated_by": "scripts/build_review_derivatives.py",
        "schema_version": 1,
        "requested_scope": requested_scope,
        "units": units,
        "reader_journey_passes": build_reader_journey_passes(
            phase_a_status=phase_a_status,
            phase_b_context=phase_b_context,
            findings=findings,
            issue_artifacts=issue_artifacts,
        ),
        "issue_artifact_coverage": issue_rows,
        "severity_counts": dict(severity_counts(findings)),
        "known_blind_spots": [],
    }
    if not phase_a:
        payload["known_blind_spots"].append("No phase_a_resume_status.json was provided; prose sentence/paragraph clean coverage is not certified.")
    if not phase_b_context:
        payload["known_blind_spots"].append("No phase_b_context.json was provided; whole-paper synthesis coverage is not certified.")
    if layout_audit:
        pages_total = layout_audit.get("pages_total") if isinstance(layout_audit.get("pages_total"), int) else 0
        pages_checked = layout_audit.get("pages_checked") if isinstance(layout_audit.get("pages_checked"), list) else []
        escalated = []
        for observation in layout_audit.get("observations", []) if isinstance(layout_audit.get("observations"), list) else []:
            if isinstance(observation, dict) and observation.get("needs_main_review") and isinstance(observation.get("page"), int):
                escalated.append(int(observation["page"]))
        payload["layout"] = {
            "pages_total": pages_total,
            "pages_checked": len(pages_checked),
            "pages_sampled": pages_checked,
            "pages_escalated": sorted(set(escalated)),
            "full_layout_coverage": bool(pages_total and len(set(pages_checked)) >= pages_total),
        }
    else:
        payload["known_blind_spots"].append("No layout_audit.json was provided; rendered page coverage is not certified.")
    return payload


def build_render_manifest(
    *,
    output_files: list[str],
    source_artifact: Path | None,
    source_hash: str,
    source_fidelity: str,
    html_source: str,
    visible_scope: str,
    deferred_findings: list[str],
    source_integrity_check: str = "skipped",
    rendered_sections: list[str] | None = None,
) -> dict[str, Any]:
    sections = [{"id": section_id, "status": "rendered"} for section_id in (rendered_sections or PAPER_READER_GLOBAL_SECTIONS)]
    paper_reader: dict[str, Any] = {
        "html_source": html_source,
        "source_fidelity": source_fidelity,
        "source_artifact": str(source_artifact) if source_artifact else "",
        "source_hash": source_hash,
        "sentence_id_scheme": "section-paragraph-sentence-v2",
        "annotation_mode": "overlay-only",
        "source_integrity_check": source_integrity_check,
    }
    if visible_scope:
        paper_reader["visible_scope"] = visible_scope
    if source_artifact and source_artifact.exists() and not source_hash:
        paper_reader["source_hash"] = sha256_path(source_artifact)
    return {
        "generated_by": "scripts/build_review_derivatives.py",
        "schema_version": 1,
        "output_files": output_files,
        "sections": sections,
        "deferred_findings": deferred_findings,
        "deferred_findings_with_reason": [
            {"id": finding_id, "reason": "artifact_only"} for finding_id in deferred_findings
        ],
        "paper_reader": paper_reader,
        "pdf_linkage_level": "Level 0",
    }


def sample_findings(findings: list[dict[str, Any]], *, issue_type: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
    rows = []
    for finding in findings:
        if issue_type and compact_text(finding.get("issue_type")).lower() != issue_type.lower():
            continue
        rows.append(
            {
                "location": compact_text(finding.get("location")) or "finding",
                "observation": compact_text(finding.get("title") or finding.get("diagnosis")),
                "linked_findings": [finding.get("id")] if finding.get("id") else [],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def build_pass_observations(
    *,
    findings: list[dict[str, Any]],
    issue_artifacts: list[dict[str, Any]],
    requested_scope: str,
) -> dict[str, Any]:
    first = findings[0] if findings else {}
    whole_paper = [item for item in findings if compact_text(item.get("snippet")).lower() == "whole paper" or compact_text(item.get("location")) in {"全文结构", "whole paper"}]
    specialist_rows = []
    for artifact in issue_artifacts:
        domain = compact_text(artifact.get("domain")) or "specialist"
        for issue in artifact.get("issues", []) if isinstance(artifact.get("issues"), list) else []:
            if not isinstance(issue, dict):
                continue
            specialist_rows.append(
                {
                    "location": compact_text(issue.get("render_hint", {}).get("anchor") if isinstance(issue.get("render_hint"), dict) else "") or domain,
                    "observation": compact_text(issue.get("title") or issue.get("diagnosis")),
                    "source": "issue_artifact",
                    "domain": domain,
                    "source_issue_id": f"{domain}:{issue.get('local_id')}",
                }
            )
    payload = {
        "generated_by": "scripts/build_review_derivatives.py",
        "pass_0_engagement_contract": [
            {
                "location": "review scope",
                "observation": f"Derived artifact bundle for {requested_scope}; final findings and issue artifacts are JSON sources of truth.",
            }
        ],
        "pass_1_cold_start_skim": sample_findings(findings, limit=1)
        or [{"location": "paper", "observation": "No compiled finding was available for cold-start skim."}],
        "pass_2_linear_deep_read": sample_findings(findings, limit=3),
        "pass_3_section_reflections": sample_findings([item for item in findings if compact_text(item.get("location")).lower() not in {"全文结构", "whole paper"}], limit=3),
        "pass_4_whole_paper_argument": sample_findings(whole_paper or findings, limit=3),
        "pass_5_submission_walk": specialist_rows[:10]
        or sample_findings(findings, issue_type="submission", limit=3)
        or [{"location": "submission walk", "observation": "No specialist issue artifacts reported submission-walk issues."}],
        "pass_6_output_calibration": [
            {
                "location": "artifact bundle",
                "observation": "Coverage, render manifest, and pass observations were derived by deterministic script and should be audited before delivery.",
            }
        ],
    }
    if first and not payload["pass_1_cold_start_skim"][0].get("linked_findings"):
        payload["pass_1_cold_start_skim"][0]["linked_findings"] = [first.get("id")]
    return payload


def build_all(
    *,
    findings_path: Path,
    annotations_path: Path | None,
    issues_dir: Path | None,
    layout_audit_path: Path | None,
    source_artifact: Path | None,
    source_hash: str,
    requested_scope: str,
    output_files: list[str],
    source_fidelity: str,
    html_source: str,
    visible_scope: str,
    source_integrity_check: str = "skipped",
    render_mode: str = "paper-reader-with-global-findings",
    phase_a_status_path: Path | None = None,
    phase_b_context_path: Path | None = None,
) -> dict[str, Any]:
    findings_payload = load_json(findings_path)
    annotations_payload = load_json(annotations_path)
    layout_audit = load_json(layout_audit_path)
    phase_a_status = load_json(phase_a_status_path)
    phase_b_context = load_json(phase_b_context_path)
    findings = as_list_payload(findings_payload, "findings")
    student_visible_findings = [finding for finding in findings if not is_artifact_only(finding)]
    artifact_only_finding_ids = [compact_text(finding.get("id"), max_chars=80) for finding in findings if is_artifact_only(finding)]
    annotations = as_list_payload(annotations_payload, "annotations")
    artifacts = load_issue_artifacts(issues_dir)
    rendered_sections = RENDER_MODES[render_mode]
    coverage = build_coverage(
        findings=student_visible_findings,
        annotations=annotations,
        issue_artifacts=artifacts,
        layout_audit=layout_audit if isinstance(layout_audit, dict) else None,
        phase_a_status=phase_a_status if isinstance(phase_a_status, dict) else None,
        phase_b_context=phase_b_context if isinstance(phase_b_context, dict) else None,
        requested_scope=requested_scope,
    )
    manifest = build_render_manifest(
        output_files=output_files,
        source_artifact=source_artifact,
        source_hash=source_hash,
        source_fidelity=source_fidelity,
        html_source=html_source,
        visible_scope=visible_scope,
        source_integrity_check=source_integrity_check,
        deferred_findings=[finding_id for finding_id in artifact_only_finding_ids if finding_id],
        rendered_sections=rendered_sections,
    )
    pass_observations = build_pass_observations(findings=student_visible_findings, issue_artifacts=artifacts, requested_scope=requested_scope)
    return {"coverage": coverage, "render_manifest": manifest, "pass_observations": pass_observations}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--issues-dir", type=Path)
    parser.add_argument("--layout-audit", type=Path)
    parser.add_argument("--phase-a-status", type=Path)
    parser.add_argument("--phase-b-context", type=Path)
    parser.add_argument("--source-artifact", type=Path)
    parser.add_argument("--source-hash", default="")
    parser.add_argument("--requested-scope", default="compiled Ariadne review")
    parser.add_argument("--output-file", action="append", default=[])
    parser.add_argument("--source-fidelity", default="deterministic", choices=("deterministic", "limited-scope", "fixture"))
    parser.add_argument("--html-source", default="pandoc", choices=("latexml", "ar5iv", "pandoc", "extracted-text", "manual-fixture"))
    parser.add_argument("--visible-scope", default="")
    parser.add_argument("--source-integrity-check", default="skipped", choices=("verified", "mismatch", "skipped"))
    parser.add_argument(
        "--render-mode",
        default="paper-reader-with-global-findings",
        choices=tuple(RENDER_MODES),
        help="Sections expected in the final HTML render.",
    )
    parser.add_argument("--coverage-out", required=True, type=Path)
    parser.add_argument("--manifest-out", required=True, type=Path)
    parser.add_argument("--pass-observations-out", required=True, type=Path)
    args = parser.parse_args(argv)

    payloads = build_all(
        findings_path=args.findings,
        annotations_path=args.annotations,
        issues_dir=args.issues_dir,
        layout_audit_path=args.layout_audit,
        phase_a_status_path=args.phase_a_status,
        phase_b_context_path=args.phase_b_context,
        source_artifact=args.source_artifact,
        source_hash=args.source_hash,
        requested_scope=args.requested_scope,
        output_files=args.output_file,
        source_fidelity=args.source_fidelity,
        html_source=args.html_source,
        visible_scope=args.visible_scope,
        source_integrity_check=args.source_integrity_check,
        render_mode=args.render_mode,
    )
    write_json(args.coverage_out, payloads["coverage"])
    write_json(args.manifest_out, payloads["render_manifest"])
    write_json(args.pass_observations_out, payloads["pass_observations"])
    print(
        "Wrote derivatives: "
        f"coverage={args.coverage_out} manifest={args.manifest_out} "
        f"pass_observations={args.pass_observations_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
