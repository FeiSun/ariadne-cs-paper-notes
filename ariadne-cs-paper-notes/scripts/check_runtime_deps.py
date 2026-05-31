#!/usr/bin/env python3
"""Check optional Ariadne runtime dependencies and print one supported setup path."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from typing import Any


PYTHON_MODULES = {
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "pdfplumber": "pdfplumber",
}
BINARIES = ("pdftotext", "pdfinfo", "pdftoppm", "pandoc")


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def build_payload() -> dict[str, Any]:
    modules = {
        name: {"available": module_available(name), "pip_package": package}
        for name, package in PYTHON_MODULES.items()
    }
    binaries = {name: {"available": shutil.which(name) is not None, "path": shutil.which(name) or ""} for name in BINARIES}
    missing_modules = [item["pip_package"] for item in modules.values() if not item["available"]]
    missing_binaries = [name for name, item in binaries.items() if not item["available"]]
    return {
        "schema_version": 1,
        "generated_by": "check_runtime_deps.py",
        "status": "passed" if not missing_modules else "missing_python_modules",
        "python": sys.executable,
        "modules": modules,
        "binaries": binaries,
        "missing_python_packages": missing_modules,
        "missing_binaries": missing_binaries,
        "supported_install": (
            f"{sys.executable} -m pip install -r ariadne-cs-paper-notes/requirements.txt"
            if missing_modules
            else ""
        ),
        "notes": [
            "Poppler binaries are optional but improve PDF/layout/numeric extraction.",
            "Install Python packages into the active runtime before running full paper-reader workflows.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="Return nonzero when Python modules are missing")
    args = parser.parse_args(argv)
    payload = build_payload()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Runtime dependency status: {payload['status']}")
        if payload["missing_python_packages"]:
            print("Missing Python packages: " + ", ".join(payload["missing_python_packages"]))
            print("Supported install:")
            print(f"  {payload['supported_install']}")
        if payload["missing_binaries"]:
            print("Optional binaries not found: " + ", ".join(payload["missing_binaries"]))
    if args.strict and payload["missing_python_packages"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
