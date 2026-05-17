#!/usr/bin/env python3
"""Regression tests for Ariadne calibration drift comparison."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "calibrate_review_runs.py"


def load_module():
    spec = importlib.util.spec_from_file_location("calibrate_review_runs", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load calibrate_review_runs module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_findings(findings: list[dict[str, object]]) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    with tmp:
        json.dump({"findings": findings}, tmp)
    return Path(tmp.name)


def finding(finding_id: str, severity: str) -> dict[str, object]:
    return {
        "id": finding_id,
        "severity": severity,
        "location": "Table 1",
        "verification_method": "visible-cell arithmetic signal",
        "severity_rationale": "main evidence table",
    }


def test_calibration_detects_severity_drift() -> None:
    module = load_module()
    first = write_findings([finding("F1", "Blocker")])
    second = write_findings([finding("F1", "Major")])
    try:
        errors, warnings = module.compare_runs(first, second)
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
    if not any("severity drift" in error for error in errors):
        raise AssertionError(f"Expected severity drift error, got errors={errors}, warnings={warnings}")


def test_calibration_allows_stable_shared_findings() -> None:
    module = load_module()
    first = write_findings([finding("F1", "Blocker")])
    second = write_findings([finding("F1", "Blocker")])
    try:
        errors, _ = module.compare_runs(first, second)
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected no calibration errors, got {errors}")


def main() -> int:
    test_calibration_detects_severity_drift()
    test_calibration_allows_stable_shared_findings()
    print("calibrate_review_runs regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
