#!/usr/bin/env python3
"""Regression tests for run_pdf_overlay_migration_matrix.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_pdf_overlay_migration_matrix.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_pdf_overlay_migration_matrix", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_pdf_overlay_migration_matrix")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_matrix_marks_three_passed_bundles_complete() -> None:
    module = load_module()

    class Result:
        returncode = 0
        stdout = json.dumps({"passed": True, "bundles_passed": 3})
        stderr = ""

    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        out = root / "matrix.json"
        original = module.run_check
        module.run_check = lambda bundles, summary_out, allow_deterministic_preview=False: Result()  # noqa: ARG005
        try:
            code = module.main(
                [
                    "--hidden",
                    str(root / "hidden"),
                    "--neurips",
                    str(root / "neurips"),
                    "--acl",
                    str(root / "acl"),
                    "--summary-out",
                    str(out),
                ]
            )
        finally:
            module.run_check = original
        payload = json.loads(out.read_text(encoding="utf-8"))

    if code != 0 or not payload["matrix_complete"]:
        raise AssertionError(f"Expected complete matrix, got code={code}, payload={payload}")


if __name__ == "__main__":
    test_matrix_marks_three_passed_bundles_complete()
    print("run_pdf_overlay_migration_matrix regression tests passed")
