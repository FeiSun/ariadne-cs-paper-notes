#!/usr/bin/env python3
"""Audit notation, macro, and display-equation symbol consistency signals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_paper_text import (  # noqa: E402
    COMMON_LATEX_COMMANDS,
    GREEK_COMMANDS,
    MATH_COMMAND_RE,
    VARIANT_SYMBOL_PAIRS,
    ExtractionState,
    collect_display_math,
    collect_tex_roots,
    expand_inputs,
    macro_definitions,
    project_root_for,
    signal_snippet,
    strip_latex_comments,
)


TOOL_NAME = "scripts/check_symbol.py"
TOOL_VERSION = "1"


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def compact_text(value: Any, *, max_chars: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def add_observation(
    observations: list[dict[str, Any]],
    *,
    issue_type: str,
    severity: str,
    title: str,
    evidence: str,
    recommendation: str,
    confidence: float,
    details: dict[str, Any] | None = None,
) -> None:
    observation: dict[str, Any] = {
        "observation_id": f"symbol-{len(observations) + 1:03d}",
        "issue_type": issue_type,
        "severity": severity,
        "title": title,
        "evidence": compact_text(evidence, max_chars=1400),
        "recommendation": recommendation,
        "confidence": confidence,
    }
    if details:
        observation["details"] = details
    observations.append(observation)


def load_source(source: Path) -> tuple[str, list[Path], list[str]]:
    state = ExtractionState()
    tex_roots = collect_tex_roots(source, state) if source.suffix.lower() == ".tex" or source.is_dir() else [source]
    root = project_root_for(source)
    raw_chunks: list[str] = []
    for path in tex_roots:
        raw = expand_inputs(path, state, root=root) if path.suffix.lower() == ".tex" else path.read_text(encoding="utf-8", errors="replace")
        raw_chunks.append(raw)
    return "\n\n".join(raw_chunks), tex_roots, state.warnings


def command_locations(equations: list[tuple[str, str]], definitions: dict[str, list[str]]) -> dict[str, list[str]]:
    locations: dict[str, list[str]] = {}
    custom_names = set(definitions)
    allowed = COMMON_LATEX_COMMANDS | GREEK_COMMANDS | custom_names
    for label, body in equations:
        for match in MATH_COMMAND_RE.finditer(strip_latex_comments(body)):
            command = match.group(1)
            if command in allowed:
                continue
            locations.setdefault(command, []).append(label)
    return {command: unique_in_order(labels) for command, labels in locations.items()}


def all_command_locations(equations: list[tuple[str, str]]) -> dict[str, list[str]]:
    locations: dict[str, list[str]] = {}
    for label, body in equations:
        for match in MATH_COMMAND_RE.finditer(strip_latex_comments(body)):
            locations.setdefault(match.group(1), []).append(label)
    return {command: unique_in_order(labels) for command, labels in locations.items()}


def audit_symbols(raw: str, *, max_items: int = 80) -> tuple[list[dict[str, Any]], dict[str, int]]:
    observations: list[dict[str, Any]] = []
    definitions = macro_definitions(raw)
    equations = collect_display_math(raw)

    macro_redefinitions = 0
    for name, expansions in sorted(definitions.items()):
        unique_expansions = unique_in_order([signal_snippet(expansion) for expansion in expansions])
        if len(unique_expansions) <= 1:
            continue
        macro_redefinitions += 1
        add_observation(
            observations,
            issue_type="macro_redefinition",
            severity="medium",
            title=f"Macro \\{name} has multiple distinct expansions",
            evidence="; ".join(repr(item[:160]) for item in unique_expansions[:max_items]),
            recommendation="Check whether the notation intentionally changes. If not, use one macro definition or rename distinct concepts.",
            confidence=0.9,
            details={"macro": name, "expansions": unique_expansions[:max_items]},
        )

    unknown_locations = command_locations(equations, definitions)
    for command, labels in sorted(unknown_locations.items())[:max_items]:
        add_observation(
            observations,
            issue_type="unknown_math_command",
            severity="medium",
            title=f"Command-like math token \\{command} is not defined in visible source",
            evidence=f"\\{command} appears in {', '.join(labels[:max_items])}; it is not defined by \\newcommand/\\def/\\DeclareMathOperator and is not on the common LaTeX allowlist.",
            recommendation="Check whether the command is package-provided, undefined, or a notation typo. If it is semantic notation, define it explicitly near first use.",
            confidence=0.78,
            details={"command": command, "locations": labels[:max_items]},
        )

    locations = all_command_locations(equations)
    variant_pairs = 0
    for base, variant in VARIANT_SYMBOL_PAIRS:
        if base not in locations or variant not in locations:
            continue
        variant_pairs += 1
        add_observation(
            observations,
            issue_type="variant_symbol_pair",
            severity="low",
            title=f"Variant symbol pair \\{base} and \\{variant} both appear",
            evidence=f"\\{base}: {', '.join(locations[base][:max_items])}; \\{variant}: {', '.join(locations[variant][:max_items])}",
            recommendation="Verify that the paper intentionally distinguishes these glyphs; otherwise normalize to one symbol.",
            confidence=0.74,
            details={"base": base, "variant": variant, "base_locations": locations[base], "variant_locations": locations[variant]},
        )

    coverage = {
        "display_equations": len(equations),
        "macro_definitions": sum(len(items) for items in definitions.values()),
        "macro_redefinitions": macro_redefinitions,
        "unknown_math_commands": len(unknown_locations),
        "variant_symbol_pairs": variant_pairs,
    }
    coverage["signals_checked"] = coverage["macro_redefinitions"] + coverage["unknown_math_commands"] + coverage["variant_symbol_pairs"]
    return observations, coverage


def build_payload(source: Path, *, max_items: int = 80) -> dict[str, Any]:
    raw, tex_roots, warnings = load_source(source)
    observations, coverage = audit_symbols(raw, max_items=max_items)
    source_artifacts = [{"path": str(path), "hash": sha256_path(path)} for path in tex_roots if path.exists()]
    if source not in tex_roots and source.exists():
        source_artifacts.insert(0, {"path": str(source), "hash": sha256_path(source)})
    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "script_hash": sha256_path(Path(__file__).resolve()),
        "checked_source": str(source),
        "source_artifacts": source_artifacts,
        "coverage": coverage,
        "observations": observations,
        "warnings": warnings,
        "limitations": [
            "Symbol checks are notation signals only; they do not prove an equation is mathematically wrong.",
            "Package-provided commands may be reported as unknown when the source does not define them explicitly.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="LaTeX entry file or project directory")
    parser.add_argument("--out", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--max-items", type=int, default=80)
    args = parser.parse_args(argv)

    source = args.source.expanduser().resolve()
    if not source.exists():
        parser.error(f"source does not exist: {source}")
    try:
        payload = build_payload(source, max_items=args.max_items)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
