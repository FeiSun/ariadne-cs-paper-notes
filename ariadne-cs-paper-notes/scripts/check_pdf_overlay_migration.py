#!/usr/bin/env python3
"""Check PDF-overlay migration readiness across review bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def phase_a_complete(bundle: Path) -> bool:
    payload = load_json(bundle / "phase_a_resume_status.json")
    coverage = payload.get("coverage") if isinstance(payload, dict) and isinstance(payload.get("coverage"), dict) else {}
    return bool(coverage.get("phase_a_complete")) and bool(coverage.get("sentence_review_receipt_complete"))


def phase_b_outputs_present(bundle: Path) -> bool:
    return all(
        nonempty(path)
        for path in (
            bundle / "argument_map.json",
            bundle / "claims.json",
            bundle / "salvageable_core.json",
            bundle / "issue_artifacts" / "whole_paper_findings.jsonl",
        )
    )


def source_domains(rows: list[Any]) -> set[str]:
    domains: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("source_domain", "domain", "source"):
            value = str(row.get(key) or "").strip().lower()
            if value:
                domains.add(value)
    return domains


def bundle_status(bundle: Path, *, require_full_review: bool = True) -> dict[str, Any]:
    manifest = load_json(bundle / "render_manifest.json")
    bbox_audit = load_json(bundle / "sentence_bbox_audit.json")
    drift_audit = load_json(bundle / "rendered_text_drift_audit.json")
    status = load_json(bundle / "pipeline_status.json")
    findings = load_json(bundle / "findings.json")
    annotations = load_json(bundle / "annotations.json")
    rows = findings.get("findings") if isinstance(findings, dict) and isinstance(findings.get("findings"), list) else []
    annotation_rows = annotations.get("annotations") if isinstance(annotations, dict) and isinstance(annotations.get("annotations"), list) else []
    false_positive_types = {"figure_reference", "rendered_caption_label_only", "table_caption_mismatch", "table caption mismatch"}
    visible_false_positive_ids = [
        str(item.get("id"))
        for item in rows
        if isinstance(item, dict)
        and str(item.get("issue_type") or "").lower() in false_positive_types
        and str(item.get("render_visibility") or item.get("visibility") or "").lower() != "artifact_only"
    ]
    pdf_overlay = manifest.get("pdf_overlay") if isinstance(manifest, dict) and isinstance(manifest.get("pdf_overlay"), dict) else {}
    mapped = int(bbox_audit.get("mapped_annotations", 0) or 0) if isinstance(bbox_audit, dict) else 0
    unmappable = int(bbox_audit.get("unmappable_annotations", 0) or 0) if isinstance(bbox_audit, dict) else 0
    mapping_rate = mapped / max(mapped + unmappable, 1)
    domains = source_domains(rows)
    has_full_phase_a = phase_a_complete(bundle)
    has_phase_b_outputs = phase_b_outputs_present(bundle)
    has_prose_findings = bool(domains.intersection({"prose", "whole_paper"}))
    errors: list[str] = []
    if pdf_overlay.get("mode") != "pdf-overlay":
        errors.append("render_manifest missing pdf_overlay.mode=pdf-overlay")
    if isinstance(bbox_audit, dict) and int(bbox_audit.get("errors", 0) or 0) > 0:
        errors.append("sentence_bbox_audit has errors")
    if isinstance(drift_audit, dict) and int(drift_audit.get("errors", 0) or 0) > 0:
        errors.append("rendered_text_drift_audit has errors")
    if visible_false_positive_ids:
        errors.append(f"visible renderer false positives remain: {', '.join(visible_false_positive_ids)}")
    if not annotation_rows:
        errors.append("no compiled annotations available for migration mapping check")
    if mapping_rate < 0.90 and (mapped + unmappable) > 0:
        errors.append(f"annotation mapping rate {mapping_rate:.1%} below 90%")
    if require_full_review:
        if not has_full_phase_a:
            errors.append("Phase A prose review is not complete")
        if not has_phase_b_outputs:
            errors.append("Phase B whole-paper synthesis artifacts are missing")
        if not has_prose_findings:
            errors.append("compiled findings lack prose/whole-paper review output")
    return {
        "bundle": str(bundle),
        "state": status.get("state") if isinstance(status, dict) else "",
        "mapping_rate": round(mapping_rate, 4),
        "mapped_annotations": mapped,
        "unmappable_annotations": unmappable,
        "compiled_annotations": len(annotation_rows),
        "phase_a_complete": has_full_phase_a,
        "phase_b_outputs_present": has_phase_b_outputs,
        "prose_or_whole_paper_findings_present": has_prose_findings,
        "visible_renderer_false_positive_ids": visible_false_positive_ids,
        "errors": errors,
        "passed": not errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", action="append", required=True, type=Path, help="A review artifact bundle to check")
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument(
        "--allow-deterministic-preview",
        action="store_true",
        help="Do not require complete Phase A/B prose artifacts. Use only for renderer smoke checks, not migration exit.",
    )
    args = parser.parse_args(argv)

    rows = [
        bundle_status(path.expanduser().resolve(), require_full_review=not args.allow_deterministic_preview)
        for path in args.bundle
    ]
    passed = all(row["passed"] for row in rows)
    payload = {
        "schema_version": 1,
        "generated_by": "scripts/check_pdf_overlay_migration.py",
        "bundles_checked": len(rows),
        "bundles_passed": sum(1 for row in rows if row["passed"]),
        "passed": passed,
        "bundles": rows,
    }
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
