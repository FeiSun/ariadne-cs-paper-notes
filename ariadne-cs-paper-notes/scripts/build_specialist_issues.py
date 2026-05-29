#!/usr/bin/env python3
"""Build curated specialist issue artifacts from deterministic raw audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ISSUE_ARTIFACT_TYPE = "ariadne_issue_artifact"
CONTEXT_POLICY = "model_readable_issue_only"
TOOL_ONLY_POLICY = "tool_only"
SEVERITY_MAP = {
    "high": "Major",
    "medium": "Minor",
    "low": "Polish",
    "polish": "Polish",
    "minor": "Minor",
    "major": "Major",
    "blocker": "Blocker",
    "Blocker": "Blocker",
    "Major": "Major",
    "Minor": "Minor",
    "Polish": "Polish",
}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_text(value: Any, *, max_chars: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def source_record(path: Path, *, context_policy: str = TOOL_ONLY_POLICY) -> dict[str, str]:
    return {"path": str(path), "hash": sha256_path(path), "context_policy": context_policy}


def severity(value: Any, *, default: str = "Minor") -> str:
    text = compact_text(value)
    return SEVERITY_MAP.get(text, SEVERITY_MAP.get(text.lower(), default))


def base_artifact(
    *,
    domain: str,
    raw_path: Path,
    status: str,
    issues: list[dict[str, Any]],
    checked: int,
    skip_reason: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_type": ISSUE_ARTIFACT_TYPE,
        "schema_version": 1,
        "domain": domain,
        "context_policy": CONTEXT_POLICY,
        "status": status,
        "source_artifacts": [source_record(raw_path)],
        "coverage": {"checked": checked, "issues": len(issues), "skipped": 1 if status == "skipped" else 0},
        "issues": issues,
    }
    if skip_reason:
        payload["skip_reason"] = skip_reason
    return payload


def high_risk_fields(domain: str, recommendation: str = "") -> dict[str, str]:
    defaults = {
        "layout": (
            "The visual presentation makes evidence harder to inspect at review speed.",
            "low cognitive load",
            "Can a reviewer inspect this page/table/figure without zooming or reconstructing layout intent?",
        ),
        "numeric": (
            "The reader cannot verify the reported quantitative evidence without reconciling values manually.",
            "auditable quantitative reporting",
            "Does the manuscript state the aggregation/denominator that explains the reported number?",
        ),
        "reference": (
            "The bibliography makes cited evidence harder to verify cleanly.",
            "verifiable citation metadata",
            "Do cited entries render identifiers, author names, years, and title capitalization consistently?",
        ),
        "source_hygiene": (
            "Submission-source hygiene issues can expose identity or leave draft artifacts in front of reviewers.",
            "submission readiness",
            "Would this source package satisfy double-blind and camera-ready hygiene expectations without manual cleanup?",
        ),
        "polish": (
            "Mechanical style drift interrupts the reader and makes the manuscript feel less production-ready.",
            "surface consistency",
            "Can a reviewer read the manuscript without noticing avoidable copy-editing inconsistencies?",
        ),
        "symbol": (
            "Notation drift forces the reader to infer whether similarly named symbols or macros still mean the same thing.",
            "stable notation",
            "Can a reader build one consistent notation registry from the manuscript without guessing?",
        ),
        "figure_caption": (
            "Figures and tables lose force when captions, labels, or assets do not carry evidence cleanly.",
            "self-contained evidence display",
            "Can a reviewer inspect each figure/table and recover its setup, metric, and takeaway without hunting?",
        ),
    }
    friction, principle, self_check = defaults.get(domain, defaults["reference"])
    return {
        "reader_friction": friction,
        "writing_principle": principle,
        "self_check": recommendation or self_check,
        "severity_rationale": f"Derived from deterministic {domain} audit severity signal.",
        "downgrade_condition": f"Downgrade after the {domain} audit no longer reports this issue.",
    }


def checked_count(payload: Any, *keys: str) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, int):
                    return nested
    return 0


def int_sum(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(int_sum(item) for item in value.values())
    return 0


def build_layout(raw_path: Path) -> dict[str, Any]:
    payload = load_json(raw_path)
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    actionable = [
        item
        for item in observations
        if isinstance(item, dict)
        and (item.get("needs_main_review") or severity(item.get("severity"), default="Polish") in {"Blocker", "Major", "Minor"})
    ]
    issues: list[dict[str, Any]] = []
    for idx, item in enumerate(actionable, 1):
        local_id = f"L{idx}"
        page = item.get("page", "")
        issue = {
            "local_id": local_id,
            "severity": severity(item.get("severity"), default="Polish"),
            "issue_type": item.get("issue_type") or "layout",
            "title": compact_text(item.get("observation"), max_chars=180) or "Layout issue",
            "diagnosis": compact_text(item.get("evidence") or item.get("observation"), max_chars=700),
            "evidence_refs": [item.get("observation_id") or f"layout-p{page}-{idx}"],
            "confidence": "medium",
            "recommendation": "Inspect the compiled PDF page and adjust float/page-break/layout choices if this is not intentional.",
            "render_hint": {"anchor": f"page:{page}" if page else "page:layout", "display_group": "Layout"},
        }
        if issue["severity"] in {"Blocker", "Major"}:
            issue.update(high_risk_fields("layout", issue["recommendation"]))
        issues.append(issue)
    status = "completed" if issues else "skipped"
    return base_artifact(
        domain="layout",
        raw_path=raw_path,
        status=status,
        issues=issues,
        checked=checked_count(payload, "pages_checked"),
        skip_reason="" if issues else "layout_audit has no observations requiring main review",
    )


def build_numeric(raw_path: Path) -> dict[str, Any]:
    payload = load_json(raw_path)
    signals = payload.get("signals", []) if isinstance(payload, dict) else []
    actionable = [item for item in signals if isinstance(item, dict) and item.get("render_required", True)]
    issues: list[dict[str, Any]] = []
    for idx, signal in enumerate(actionable, 1):
        local_id = signal.get("signal_id") or f"N{idx}"
        table_id = compact_text(signal.get("table_id"), max_chars=120) or "table"
        row = compact_text(signal.get("row_label"), max_chars=160)
        reported = compact_text(signal.get("reported_value"), max_chars=80)
        computed = compact_text(signal.get("visible_computed_value"), max_chars=80)
        delta = compact_text(signal.get("delta"), max_chars=80)
        diagnosis = (
            f"{table_id} {row}: reported {reported}; visible recomputation gives {computed}; delta {delta}. "
            f"{compact_text(signal.get('aggregation_caveat'), max_chars=420)}"
        )
        issue = {
            "local_id": local_id,
            "severity": "Blocker",
            "issue_type": "numeric",
            "title": f"{table_id} numeric recomputation mismatch",
            "diagnosis": compact_text(diagnosis, max_chars=900),
            "reported_value": reported,
            "visible_computed_value": computed,
            "delta": delta,
            "aggregation_caveat": compact_text(signal.get("aggregation_caveat"), max_chars=700),
            "evidence_refs": [local_id],
            "confidence": "medium",
            "recommendation": "State the denominator/weighting/aggregation rule or correct the reported value.",
            "render_hint": {"anchor": f"page:{table_id}", "display_group": "Numeric Audit"},
        }
        issue.update(high_risk_fields("numeric", issue["recommendation"]))
        issues.append(issue)
    status = "completed" if issues else "skipped"
    return base_artifact(
        domain="numeric",
        raw_path=raw_path,
        status=status,
        issues=issues,
        checked=checked_count(payload, "signal_count"),
        skip_reason="" if issues else "numeric_audit.signal_count == 0",
    )


def build_reference(raw_path: Path) -> dict[str, Any]:
    payload = load_json(raw_path)
    raw_findings = payload.get("findings", []) if isinstance(payload, dict) else []
    issues: list[dict[str, Any]] = []
    for idx, finding in enumerate(raw_findings, 1):
        if not isinstance(finding, dict):
            continue
        local_id = finding.get("observation_id") or f"R{idx}"
        rec = compact_text(finding.get("recommendation"), max_chars=700)
        issue = {
            "local_id": local_id,
            "severity": severity(finding.get("severity"), default="Minor"),
            "issue_type": "reference_format",
            "title": compact_text(finding.get("title"), max_chars=200) or "Reference hygiene issue",
            "diagnosis": compact_text(finding.get("evidence") or finding.get("title"), max_chars=1000),
            "evidence_refs": [{"source_artifact": raw_path.name, "observation_id": local_id, "field": "findings"}],
            "confidence": finding.get("confidence", 0.8),
            "recommendation": rec,
            "render_hint": {"anchor": "page:references", "display_group": "Reference Hygiene"},
        }
        if issue["severity"] in {"Blocker", "Major"}:
            issue.update(high_risk_fields("reference", rec))
        issues.append(issue)
    status = "completed" if issues else "skipped"
    estimate = payload.get("reference_count_estimate") if isinstance(payload, dict) else {}
    return base_artifact(
        domain="reference",
        raw_path=raw_path,
        status=status,
        issues=issues,
        checked=checked_count({"estimate": estimate}, "estimate"),
        skip_reason="" if issues else "reference audit produced no findings",
    )


def build_source_hygiene(raw_path: Path) -> dict[str, Any]:
    payload = load_json(raw_path)
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    issues: list[dict[str, Any]] = []
    for idx, observation in enumerate(observations, 1):
        if not isinstance(observation, dict):
            continue
        local_id = observation.get("observation_id") or f"S{idx}"
        rec = compact_text(observation.get("recommendation"), max_chars=700)
        visibility_basis = compact_text(observation.get("visibility_basis"), max_chars=80) or "source_only"
        issue = {
            "local_id": local_id,
            "severity": severity(observation.get("severity"), default="Minor"),
            "issue_type": observation.get("issue_type") or "source_hygiene",
            "title": compact_text(observation.get("title"), max_chars=200) or "Source hygiene issue",
            "diagnosis": compact_text(observation.get("evidence") or observation.get("title"), max_chars=1000),
            "evidence_refs": [{"source_artifact": raw_path.name, "observation_id": local_id, "field": "observations"}],
            "confidence": observation.get("confidence", 0.8),
            "recommendation": rec,
            "render_hint": {"anchor": "page:submission", "display_group": "Source Hygiene"},
            "visibility_basis": visibility_basis,
        }
        if issue["severity"] in {"Blocker", "Major"}:
            issue.update(high_risk_fields("source_hygiene", rec))
        issues.append(issue)
    status = "completed" if issues else "skipped"
    coverage = payload.get("coverage") if isinstance(payload, dict) else {}
    return base_artifact(
        domain="source_hygiene",
        raw_path=raw_path,
        status=status,
        issues=issues,
        checked=int_sum(coverage),
        skip_reason="" if issues else "source hygiene audit produced no observations",
    )


def build_polish(raw_path: Path) -> dict[str, Any]:
    payload = load_json(raw_path)
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    issues: list[dict[str, Any]] = []
    for idx, observation in enumerate(observations, 1):
        if not isinstance(observation, dict):
            continue
        local_id = observation.get("observation_id") or f"PL{idx}"
        rec = compact_text(observation.get("recommendation"), max_chars=700)
        issue = {
            "local_id": local_id,
            "severity": severity(observation.get("severity"), default="Polish"),
            "issue_type": observation.get("issue_type") or "polish",
            "title": compact_text(observation.get("title"), max_chars=200) or "Polish consistency issue",
            "diagnosis": compact_text(observation.get("evidence") or observation.get("title"), max_chars=1000),
            "evidence_refs": [{"source_artifact": raw_path.name, "observation_id": local_id, "field": "observations"}],
            "confidence": observation.get("confidence", 0.75),
            "recommendation": rec,
            "render_hint": {"anchor": "page:polish", "display_group": "Polish Sweep"},
        }
        if issue["severity"] in {"Blocker", "Major"}:
            issue.update(high_risk_fields("polish", rec))
        issues.append(issue)
    status = "completed" if issues else "skipped"
    coverage = payload.get("coverage") if isinstance(payload, dict) else {}
    checked = checked_count(coverage, "words_checked", "signals_checked") or int_sum(coverage)
    return base_artifact(
        domain="polish",
        raw_path=raw_path,
        status=status,
        issues=issues,
        checked=checked,
        skip_reason="" if issues else "polish audit produced no observations",
    )


def build_symbol(raw_path: Path) -> dict[str, Any]:
    payload = load_json(raw_path)
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    issues: list[dict[str, Any]] = []
    for idx, observation in enumerate(observations, 1):
        if not isinstance(observation, dict):
            continue
        local_id = observation.get("observation_id") or f"SYM{idx}"
        rec = compact_text(observation.get("recommendation"), max_chars=700)
        issue = {
            "local_id": local_id,
            "severity": severity(observation.get("severity"), default="Minor"),
            "issue_type": observation.get("issue_type") or "symbol",
            "title": compact_text(observation.get("title"), max_chars=200) or "Symbol consistency issue",
            "diagnosis": compact_text(observation.get("evidence") or observation.get("title"), max_chars=1000),
            "evidence_refs": [{"source_artifact": raw_path.name, "observation_id": local_id, "field": "observations"}],
            "confidence": observation.get("confidence", 0.75),
            "recommendation": rec,
            "render_hint": {"anchor": "page:symbols", "display_group": "Symbol Consistency"},
        }
        if issue["severity"] in {"Blocker", "Major"}:
            issue.update(high_risk_fields("symbol", rec))
        issues.append(issue)
    status = "completed" if issues else "skipped"
    coverage = payload.get("coverage") if isinstance(payload, dict) else {}
    checked = checked_count(coverage, "display_equations", "signals_checked") or int_sum(coverage)
    return base_artifact(
        domain="symbol",
        raw_path=raw_path,
        status=status,
        issues=issues,
        checked=checked,
        skip_reason="" if issues else "symbol audit produced no observations",
    )


def build_figure_caption(raw_path: Path) -> dict[str, Any]:
    payload = load_json(raw_path)
    observations = payload.get("observations", []) if isinstance(payload, dict) else []
    issues: list[dict[str, Any]] = []
    for idx, observation in enumerate(observations, 1):
        if not isinstance(observation, dict):
            continue
        local_id = observation.get("observation_id") or f"FC{idx}"
        rec = compact_text(observation.get("recommendation"), max_chars=700)
        details = observation.get("details") if isinstance(observation.get("details"), dict) else {}
        target_label = compact_text(details.get("target_label"), max_chars=160) if isinstance(details, dict) else ""
        render_hint = {"anchor": "page:figures", "display_group": "Figure/Caption"}
        if target_label:
            render_hint = {
                "anchor": target_label,
                "target_level": "section",
                "display_group": "Figure/Caption",
                "target_kind": compact_text(details.get("target_kind"), max_chars=40),
            }
        issue = {
            "local_id": local_id,
            "severity": severity(observation.get("severity"), default="Minor"),
            "issue_type": observation.get("issue_type") or "figure_caption",
            "title": compact_text(observation.get("title"), max_chars=200) or "Figure/caption issue",
            "diagnosis": compact_text(observation.get("evidence") or observation.get("title"), max_chars=1000),
            "evidence_refs": [{"source_artifact": raw_path.name, "observation_id": local_id, "field": "observations"}],
            "confidence": observation.get("confidence", 0.75),
            "recommendation": rec,
            "render_hint": render_hint,
        }
        if issue["issue_type"] == "rendered_caption_label_only" or (not target_label and issue["issue_type"] in {
            "rendered_caption_count_mismatch",
            "rendered_caption_missing",
        }):
            issue["render_visibility"] = "artifact_only"
        if issue["severity"] in {"Blocker", "Major"}:
            issue.update(high_risk_fields("figure_caption", rec))
        issues.append(issue)
    status = "completed" if issues else "skipped"
    coverage = payload.get("coverage") if isinstance(payload, dict) else {}
    checked = int_sum(coverage) or checked_count(coverage, "floats", "captions", "rendered_pages_checked", "signals_checked")
    return base_artifact(
        domain="figure_caption",
        raw_path=raw_path,
        status=status,
        issues=issues,
        checked=checked,
        skip_reason="" if issues else "figure/caption audit produced no observations",
    )


def build_for_domain(domain: str, raw_path: Path) -> dict[str, Any]:
    if domain == "layout":
        return build_layout(raw_path)
    if domain == "numeric":
        return build_numeric(raw_path)
    if domain == "reference":
        return build_reference(raw_path)
    if domain == "source_hygiene":
        return build_source_hygiene(raw_path)
    if domain == "polish":
        return build_polish(raw_path)
    if domain == "symbol":
        return build_symbol(raw_path)
    if domain == "figure_caption":
        return build_figure_caption(raw_path)
    raise ValueError(f"unsupported domain: {domain}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--domain",
        required=True,
        choices=("layout", "numeric", "reference", "source_hygiene", "polish", "symbol", "figure_caption"),
    )
    parser.add_argument("--raw-audit", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    raw_path = args.raw_audit.resolve()
    if not raw_path.exists():
        parser.error(f"raw audit does not exist: {raw_path}")
    try:
        payload = build_for_domain(args.domain, raw_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.domain}_issues: "
        f"status={payload['status']} issues={payload['coverage']['issues']} checked={payload['coverage']['checked']} "
        f"to {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
