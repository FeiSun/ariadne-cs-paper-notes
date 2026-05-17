#!/usr/bin/env python3
"""Build a rendered PDF from a LaTeX entry file or project directory."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


MAIN_NAMES = {"main.tex", "paper.tex", "ms.tex", "manuscript.tex"}
INPUT_RE = re.compile(r"\\(?:input|include|subfile)\{([^{}]+)\}|\\(?:import|subimport)\{([^{}]+)\}\{([^{}]+)\}")
PROJECT_MARKERS = {".git", ".latexmkrc", "latexmkrc", "Makefile", "makefile"}
RESOURCE_DIRS = {"bib", "bibs", "bibliography", "references", "figures", "figure", "fig", "tables", "sections"}
TEX_CONTAINER_DIRS = {"src", "tex", "source", "sources", "latex", "paper"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def relative_depth(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return 99


def project_root_for(source: Path) -> Path:
    resolved = source.resolve()
    if not resolved.is_file():
        return resolved

    parent = resolved.parent
    grandparent = parent.parent
    if grandparent == parent:
        return parent

    if parent.name.lower() in TEX_CONTAINER_DIRS:
        return grandparent
    if any((grandparent / marker).exists() for marker in PROJECT_MARKERS):
        return grandparent
    if any((grandparent / dirname).is_dir() for dirname in RESOURCE_DIRS):
        return grandparent
    if len(list(grandparent.glob("*.tex"))) > 0:
        return grandparent
    return parent


def is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def rank_tex_candidate(path: Path, root: Path, text: str | None = None) -> tuple[int, int, str]:
    if text is None:
        text = read_text(path)
    name = path.name.lower()
    score = 0
    if name in MAIN_NAMES:
        score -= 100
    if relative_depth(path, root) == 1:
        score -= 20
    if "\\begin{document}" in text:
        score -= 10
    if "\\documentclass" in text:
        score -= 5
    if any(term in name for term in ("appendix", "supp", "supplement", "rebuttal", "response")):
        score += 30
    return score, relative_depth(path, root), str(path)


def find_entry_tex(source: Path) -> Path:
    if source.is_file():
        if source.suffix.lower() != ".tex":
            raise ValueError(f"Expected a .tex file or directory, got {source}")
        return source

    tex_files = sorted(source.rglob("*.tex"))
    if not tex_files:
        raise ValueError(f"No .tex files found under {source}")
    cached = [(path, read_text(path)) for path in tex_files]
    candidates = [(path, text) for path, text in cached if "\\documentclass" in text or "\\begin{document}" in text]
    if not candidates:
        candidates = cached
    return sorted(candidates, key=lambda item: rank_tex_candidate(item[0], source, item[1]))[0][0]


def run_command(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
    )


def expanded_latex_for_tool_detection(entry: Path, seen: set[Path] | None = None, root: Path | None = None) -> str:
    seen = seen or set()
    root = root or project_root_for(entry)
    entry = entry.resolve()
    if entry in seen or not entry.exists() or not is_within_root(entry, root):
        return ""
    seen.add(entry)
    text = read_text(entry)

    def repl(match: re.Match[str]) -> str:
        if match.group(1):
            target = entry.parent / match.group(1)
        else:
            target = entry.parent / (match.group(2) or "") / (match.group(3) or "")
        if target.suffix != ".tex":
            tex_target = target.with_suffix(".tex")
            if tex_target.exists():
                target = tex_target
        if not is_within_root(target, root):
            return ""
        return "\n" + expanded_latex_for_tool_detection(target, seen, root) + "\n"

    return INPUT_RE.sub(repl, text)


def bibliography_tool(entry: Path) -> tuple[str, str] | None:
    text = expanded_latex_for_tool_detection(entry)
    if "\\addbibresource" in text or "biblatex" in text:
        biber = shutil.which("biber")
        if biber:
            return biber, "biber"
    bibtex = shutil.which("bibtex")
    if bibtex:
        return bibtex, "bibtex"
    biber = shutil.which("biber")
    if biber:
        return biber, "biber"
    return None


def build_pdf(entry: Path, timeout: int) -> tuple[bool, Path, str, list[str]]:
    cwd = entry.parent
    output = entry.with_suffix(".pdf")
    logs: list[str] = []

    latexmk = shutil.which("latexmk")
    if latexmk:
        result = run_command([latexmk, "-pdf", "-interaction=nonstopmode", "-halt-on-error", entry.name], cwd, timeout)
        logs.append(result.stdout[-4000:] + result.stderr[-4000:])
        return result.returncode == 0 and output.exists(), output, "latexmk", logs

    pdflatex = shutil.which("pdflatex")
    if pdflatex:
        commands: list[tuple[list[str], bool]] = [
            ([pdflatex, "-interaction=nonstopmode", entry.name], True),
        ]
        bib_tool = bibliography_tool(entry)
        tool_name = "pdflatex"
        if bib_tool:
            bib_cmd, bib_name = bib_tool
            commands.append(([bib_cmd, entry.stem], False))
            tool_name = f"pdflatex+{bib_name}"
        else:
            logs.append("No bibtex or biber found on PATH; citations may remain unresolved.")
        commands.extend(
            [
                ([pdflatex, "-interaction=nonstopmode", entry.name], True),
                ([pdflatex, "-interaction=nonstopmode", entry.name], True),
            ]
        )

        ok = False
        for cmd, fatal in commands:
            result = run_command(cmd, cwd, timeout)
            logs.append(result.stdout[-4000:] + result.stderr[-4000:])
            if fatal and result.returncode != 0:
                ok = False
                break
            ok = output.exists()
        return ok, output, tool_name, logs

    return False, output, "none", ["No latexmk or pdflatex found on PATH."]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="LaTeX project directory or entry .tex file")
    parser.add_argument("--timeout", type=int, default=300, help="Build timeout in seconds")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    if not source.exists():
        parser.error(f"Input does not exist: {source}")

    try:
        entry = find_entry_tex(source)
        ok, pdf, tool, logs = build_pdf(entry, args.timeout)
        payload = {
            "ok": ok,
            "entry": str(entry),
            "pdf": str(pdf) if pdf.exists() else None,
            "expected_pdf": str(pdf),
            "tool": tool,
            "log_tail": "\n".join(logs)[-4000:],
        }
    except Exception as exc:
        payload = {"ok": False, "entry": None, "pdf": None, "tool": None, "error": str(exc)}

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
