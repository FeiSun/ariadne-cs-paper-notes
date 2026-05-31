#!/usr/bin/env python3
"""Regression tests for runtime dependency self-check output."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_runtime_deps.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_runtime_deps", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load check_runtime_deps")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dependency_payload_names_supported_install_path() -> None:
    module = load_module()
    payload = module.build_payload()
    if payload["generated_by"] != "check_runtime_deps.py":
        raise AssertionError(f"Missing provenance: {payload}")
    if "modules" not in payload or "bs4" not in payload["modules"] or "pdfplumber" not in payload["modules"]:
        raise AssertionError(f"Dependency payload should include expected modules: {payload}")
    if payload["missing_python_packages"] and "requirements.txt" not in payload["supported_install"]:
        raise AssertionError(f"Missing supported install path: {payload}")


def main() -> int:
    test_dependency_payload_names_supported_install_path()
    print("check_runtime_deps regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
