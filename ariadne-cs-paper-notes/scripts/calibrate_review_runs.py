#!/usr/bin/env python3
"""Compare two Ariadne findings.json runs for calibration drift."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SEVERITY_ORDER = {"Polish": 0, "Minor": 1, "Major": 2, "Blocker": 3}


def load_findings(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        findings = payload
    elif isinstance(payload, dict) and isinstance(payload.get("findings"), list):
        findings = payload["findings"]
    else:
        raise ValueError(f"{path} must be a list or object with findings list")
    return [finding for finding in findings if isinstance(finding, dict)]


def finding_key(finding: dict[str, Any]) -> str:
    if finding.get("id"):
        return str(finding["id"])
    location = str(finding.get("location", "")).strip().lower()
    dimension = str(finding.get("check_dimension") or finding.get("claim_type") or finding.get("verification_method") or "").strip().lower()
    return f"{location}::{dimension}"


def severity_counts(findings: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(finding.get("severity", "<missing>")) for finding in findings)


def compare_runs(first: Path, second: Path) -> tuple[list[str], list[str]]:
    first_findings = load_findings(first)
    second_findings = load_findings(second)
    first_by_key = {finding_key(finding): finding for finding in first_findings}
    second_by_key = {finding_key(finding): finding for finding in second_findings}

    warnings: list[str] = []
    errors: list[str] = []

    first_keys = set(first_by_key)
    second_keys = set(second_by_key)
    for key in sorted(first_keys - second_keys):
        warnings.append(f"finding present only in first run: {key}")
    for key in sorted(second_keys - first_keys):
        warnings.append(f"finding present only in second run: {key}")

    for key in sorted(first_keys & second_keys):
        sev_a = first_by_key[key].get("severity")
        sev_b = second_by_key[key].get("severity")
        if sev_a != sev_b:
            rank_a = SEVERITY_ORDER.get(str(sev_a), -1)
            rank_b = SEVERITY_ORDER.get(str(sev_b), -1)
            drift = abs(rank_a - rank_b) if rank_a >= 0 and rank_b >= 0 else "unknown"
            errors.append(f"severity drift for {key}: {sev_a} -> {sev_b} (distance {drift})")

        rationale_a = bool(first_by_key[key].get("severity_rationale"))
        rationale_b = bool(second_by_key[key].get("severity_rationale"))
        if rationale_a != rationale_b:
            warnings.append(f"severity rationale presence drift for {key}: {rationale_a} -> {rationale_b}")

    counts_a = severity_counts(first_findings)
    counts_b = severity_counts(second_findings)
    warnings.append(f"first severity counts: {dict(sorted(counts_a.items()))}")
    warnings.append(f"second severity counts: {dict(sorted(counts_b.items()))}")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path, help="First findings.json run")
    parser.add_argument("second", type=Path, help="Second findings.json run")
    args = parser.parse_args(argv)

    errors, warnings = compare_runs(args.first, args.second)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Ariadne calibration comparison passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
