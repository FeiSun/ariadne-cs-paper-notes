#!/usr/bin/env python3
"""Run the PDF-overlay migration checker over named paper bundles."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def run_check(
    bundles: list[Path],
    summary_out: Path | None,
    *,
    allow_deterministic_preview: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT_DIR / "check_pdf_overlay_migration.py")]
    for bundle in bundles:
        cmd.extend(["--bundle", str(bundle)])
    if summary_out:
        cmd.extend(["--summary-out", str(summary_out)])
    if allow_deterministic_preview:
        cmd.append("--allow-deterministic-preview")
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hidden", type=Path, required=True, help="Hidden_Knowledge-style PDF-overlay review bundle")
    parser.add_argument("--neurips", type=Path, required=True, help="NeurIPS/ICLR-style PDF-overlay review bundle")
    parser.add_argument("--acl", type=Path, required=True, help="ACL-style PDF-overlay review bundle")
    parser.add_argument("--summary-out", type=Path, required=True)
    parser.add_argument(
        "--allow-deterministic-preview",
        action="store_true",
        help="Run a renderer smoke matrix without requiring complete Phase A/B prose artifacts.",
    )
    args = parser.parse_args(argv)

    labels = {
        "hidden": args.hidden.expanduser().resolve(),
        "neurips": args.neurips.expanduser().resolve(),
        "acl": args.acl.expanduser().resolve(),
    }
    result = run_check(
        list(labels.values()),
        args.summary_out.expanduser().resolve(),
        allow_deterministic_preview=args.allow_deterministic_preview,
    )
    payload: dict[str, Any]
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {
            "schema_version": 1,
            "generated_by": "scripts/run_pdf_overlay_migration_matrix.py",
            "passed": False,
            "error": "migration checker did not emit JSON",
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    payload["matrix_labels"] = {label: str(path) for label, path in labels.items()}
    payload["matrix_complete"] = bool(payload.get("passed")) and int(payload.get("bundles_passed", 0) or 0) == 3
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["matrix_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
