#!/usr/bin/env python3
"""Audit Ariadne structured review artifacts and optional rendered HTML."""

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

from audit_html_report import AriadneHTMLParser, audit as audit_html  # noqa: E402


SEVERITIES = {"Blocker", "Major", "Minor", "Polish"}
HIGH_RISK = {"Blocker", "Major"}

REQUIRED_FINDING_FIELDS = {
    "id",
    "severity",
    "location",
    "reader_friction",
    "writing_principle",
    "next_draft_task",
    "evidence_basis",
    "verification_method",
}

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


def audit_findings(payload: Any) -> tuple[list[str], list[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    findings = list_from_payload(payload, "findings")
    ids: set[str] = set()

    for idx, finding in enumerate(findings, 1):
        prefix = f"finding #{idx}"
        finding_id = finding.get("id", f"<missing-{idx}>")
        if finding_id in ids:
            errors.append(f"duplicate finding id: {finding_id}")
        ids.add(str(finding_id))

        missing = sorted(field for field in REQUIRED_FINDING_FIELDS if not nonempty(finding.get(field)))
        for field in missing:
            errors.append(f"{prefix} {finding_id}: missing required field `{field}`")

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

    return errors, warnings, ids


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
    return errors, warnings


def audit_pass_observations(payload: Any) -> tuple[list[str], list[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return ["pass_observations payload must be an object"], warnings, set()
    missing = sorted(key for key in PASS_OBSERVATION_KEYS if key not in payload)
    for key in missing:
        errors.append(f"pass_observations missing `{key}`")
    linked_ids: set[str] = set()
    observation_count = 0
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


def html_ids(path: Path) -> tuple[set[str], list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    parser = AriadneHTMLParser()
    parser.feed(text)
    errors, warnings = audit_html(path)
    return parser.ids, errors, warnings


def audit_artifacts(
    findings_path: Path,
    claims_path: Path | None = None,
    numeric_audit_path: Path | None = None,
    coverage_path: Path | None = None,
    manifest_path: Path | None = None,
    pass_observations_path: Path | None = None,
    html_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    finding_errors, finding_warnings, finding_ids = audit_findings(load_json(findings_path))
    errors.extend(finding_errors)
    warnings.extend(finding_warnings)

    deferred: set[str] = set()
    rendered_section_ids: set[str] = set()
    required_numeric_signals: list[dict[str, Any]] = []
    if claims_path:
        claim_errors, claim_warnings = audit_claims(load_json(claims_path), finding_ids)
        errors.extend(claim_errors)
        warnings.extend(claim_warnings)
    if numeric_audit_path:
        numeric_errors, numeric_warnings, required_numeric_signals = audit_numeric_signal_payload(load_json(numeric_audit_path))
        errors.extend(numeric_errors)
        warnings.extend(numeric_warnings)
    if coverage_path:
        coverage_errors, coverage_warnings = audit_coverage(load_json(coverage_path))
        errors.extend(coverage_errors)
        warnings.extend(coverage_warnings)
    if manifest_path:
        manifest_errors, manifest_warnings, deferred, rendered_section_ids = audit_manifest(load_json(manifest_path), finding_ids)
        errors.extend(manifest_errors)
        warnings.extend(manifest_warnings)
    if pass_observations_path:
        pass_errors, pass_warnings, linked_ids = audit_pass_observations(load_json(pass_observations_path))
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
    parser.add_argument("--bundle", type=Path, help="Directory containing findings.json, claims.json, numeric_audit.json, coverage.json, render_manifest.json, and pass_observations.json")
    parser.add_argument("--findings", type=Path)
    parser.add_argument("--claims", type=Path)
    parser.add_argument("--numeric-audit", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pass-observations", type=Path)
    parser.add_argument("--html", type=Path)
    args = parser.parse_args(argv)

    findings = args.findings
    claims = args.claims
    numeric_audit = args.numeric_audit
    coverage = args.coverage
    manifest = args.manifest
    pass_observations = args.pass_observations
    if args.bundle:
        bundle = args.bundle
        findings = findings or bundle / "findings.json"
        claims = claims or bundle / "claims.json"
        numeric_audit = numeric_audit or bundle / "numeric_audit.json"
        coverage = coverage or bundle / "coverage.json"
        manifest = manifest or bundle / "render_manifest.json"
        pass_observations = pass_observations or bundle / "pass_observations.json"
    if findings is None:
        parser.error("--findings is required unless --bundle is provided")

    errors, warnings = audit_artifacts(findings, claims, numeric_audit, coverage, manifest, pass_observations, args.html)
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
