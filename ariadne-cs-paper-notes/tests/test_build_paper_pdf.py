#!/usr/bin/env python3
"""Minimal regression tests for build_paper_pdf.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_paper_pdf.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_paper_pdf", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load build_paper_pdf module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"Missing expected text: {needle}\n--- output ---\n{text[:4000]}")


def assert_not_contains(text: str, needle: str) -> None:
    if needle in text:
        raise AssertionError(f"Unexpected text present: {needle}\n--- output ---\n{text[:4000]}")


def test_find_entry_prefers_root_main() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.tex").write_text(
            "\n".join([r"\documentclass{article}", r"\begin{document}", "Main.", r"\end{document}"]),
            encoding="utf-8",
        )
        (root / "sections").mkdir()
        (root / "sections" / "appendix.tex").write_text(
            "\n".join([r"\documentclass{article}", r"\begin{document}", "Appendix.", r"\end{document}"]),
            encoding="utf-8",
        )
        entry = module.find_entry_tex(root)

    if entry.name != "main.tex":
        raise AssertionError(f"Expected main.tex, got {entry}")


def test_find_entry_rejects_directory_without_tex() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            module.find_entry_tex(root)
        except ValueError as exc:
            assert_contains(str(exc), "No .tex files")
        else:
            raise AssertionError("Expected missing .tex directory to fail")


def test_cli_reports_missing_latex_tools() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join([r"\documentclass{article}", r"\begin{document}", "Body.", r"\end{document}"]),
            encoding="utf-8",
        )
        with mock.patch.object(module.shutil, "which", lambda name: None):
            ok, pdf, tool, logs = module.build_pdf(tex, 10)

    if ok:
        raise AssertionError("Expected build to fail without latex tools")
    if tool != "none":
        raise AssertionError(f"Expected tool none, got {tool}")
    assert_contains("\n".join(logs), "No latexmk or pdflatex")
    if pdf.name != "main.pdf":
        raise AssertionError(f"Expected main.pdf path, got {pdf}")


def test_pdflatex_fallback_runs_bibtex_between_latex_passes() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"Body \cite{smith2024}.",
                    r"\bibliography{refs}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        calls: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            if name == "latexmk":
                return None
            if name in {"pdflatex", "bibtex"}:
                return f"/fake/{name}"
            return None

        def fake_run_command(cmd: list[str], cwd: Path, timeout: int):
            calls.append(cmd)
            if Path(cmd[0]).name == "pdflatex":
                tex.with_suffix(".pdf").write_text("%PDF fake", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with mock.patch.object(module.shutil, "which", fake_which), mock.patch.object(
            module, "run_command", fake_run_command
        ):
            ok, pdf, tool, _logs = module.build_pdf(tex, 10)

    if not ok:
        raise AssertionError("Expected pdflatex fallback build to succeed")
    if tool != "pdflatex+bibtex":
        raise AssertionError(f"Expected pdflatex+bibtex, got {tool}")
    command_names = [Path(call[0]).name for call in calls]
    if command_names != ["pdflatex", "bibtex", "pdflatex", "pdflatex"]:
        raise AssertionError(f"Unexpected command order: {command_names}")
    if not all("-synctex=1" in call for call in calls if Path(call[0]).name == "pdflatex"):
        raise AssertionError(f"Expected all pdflatex passes to enable SyncTeX, got {calls}")
    if pdf.name != "main.pdf":
        raise AssertionError(f"Expected main.pdf, got {pdf}")


def test_pdflatex_fallback_uses_biber_for_biblatex() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\usepackage{biblatex}",
                    r"\addbibresource{refs.bib}",
                    r"\begin{document}",
                    r"Body \cite{smith2024}.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        calls: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            if name == "latexmk":
                return None
            if name in {"pdflatex", "biber"}:
                return f"/fake/{name}"
            return None

        def fake_run_command(cmd: list[str], cwd: Path, timeout: int):
            calls.append(cmd)
            if Path(cmd[0]).name == "pdflatex":
                tex.with_suffix(".pdf").write_text("%PDF fake", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with mock.patch.object(module.shutil, "which", fake_which), mock.patch.object(
            module, "run_command", fake_run_command
        ):
            ok, _pdf, tool, _logs = module.build_pdf(tex, 10)

    if not ok:
        raise AssertionError("Expected pdflatex+biber fallback build to succeed")
    if tool != "pdflatex+biber":
        raise AssertionError(f"Expected pdflatex+biber, got {tool}")
    command_names = [Path(call[0]).name for call in calls]
    if command_names != ["pdflatex", "biber", "pdflatex", "pdflatex"]:
        raise AssertionError(f"Unexpected command order: {command_names}")
    if not all("-synctex=1" in call for call in calls if Path(call[0]).name == "pdflatex"):
        raise AssertionError(f"Expected all pdflatex passes to enable SyncTeX, got {calls}")


def test_pdflatex_fallback_detects_biblatex_in_input_preamble() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tex = root / "main.tex"
        (root / "preamble.tex").write_text(
            "\n".join([r"\usepackage{biblatex}", r"\addbibresource{refs.bib}"]),
            encoding="utf-8",
        )
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\input{preamble}",
                    r"\begin{document}",
                    r"Body \cite{smith2024}.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        calls: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            if name == "latexmk":
                return None
            if name in {"pdflatex", "biber"}:
                return f"/fake/{name}"
            return None

        def fake_run_command(cmd: list[str], cwd: Path, timeout: int):
            calls.append(cmd)
            if Path(cmd[0]).name == "pdflatex":
                tex.with_suffix(".pdf").write_text("%PDF fake", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with mock.patch.object(module.shutil, "which", fake_which), mock.patch.object(
            module, "run_command", fake_run_command
        ):
            ok, _pdf, tool, _logs = module.build_pdf(tex, 10)

    if not ok:
        raise AssertionError("Expected pdflatex+biber fallback build to succeed")
    if tool != "pdflatex+biber":
        raise AssertionError(f"Expected pdflatex+biber, got {tool}")
    command_names = [Path(call[0]).name for call in calls]
    if command_names != ["pdflatex", "biber", "pdflatex", "pdflatex"]:
        raise AssertionError(f"Unexpected command order: {command_names}")
    if not all("-synctex=1" in call for call in calls if Path(call[0]).name == "pdflatex"):
        raise AssertionError(f"Expected all pdflatex passes to enable SyncTeX, got {calls}")


def test_tool_detection_uses_project_root_for_src_entry_parent_inputs() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        src = project / "src"
        src.mkdir(parents=True)
        (project / "preamble.tex").write_text(
            "\n".join([r"\usepackage{biblatex}", r"\addbibresource{refs.bib}"]),
            encoding="utf-8",
        )
        entry = src / "main.tex"
        entry.write_text(
            "\n".join([r"\documentclass{article}", r"\input{../preamble}", r"\begin{document}", "Body.", r"\end{document}"]),
            encoding="utf-8",
        )

        expanded = module.expanded_latex_for_tool_detection(entry)

    assert_contains(expanded, r"\usepackage{biblatex}")
    assert_contains(expanded, r"\addbibresource{refs.bib}")


def test_tool_detection_expands_import_and_subimport_inputs() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        src = project / "src"
        shared = project / "shared"
        nested = shared / "nested"
        src.mkdir(parents=True)
        nested.mkdir(parents=True)
        (shared / "preamble.tex").write_text(r"\usepackage{biblatex}", encoding="utf-8")
        (nested / "bibconfig.tex").write_text(r"\addbibresource{refs.bib}", encoding="utf-8")
        entry = src / "main.tex"
        entry.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\import{../shared/}{preamble}",
                    r"\subimport{../shared/nested/}{bibconfig}",
                    r"\begin{document}",
                    "Body.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )

        expanded = module.expanded_latex_for_tool_detection(entry)

    assert_contains(expanded, r"\usepackage{biblatex}")
    assert_contains(expanded, r"\addbibresource{refs.bib}")


def test_tool_detection_refuses_inputs_outside_project_root() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        project.mkdir()
        outside_dir = Path(tmp) / "outside"
        outside_dir.mkdir()
        outside = outside_dir / "outside.tex"
        outside.write_text(r"\usepackage{biblatex}", encoding="utf-8")
        entry = project / "main.tex"
        entry.write_text(
            "\n".join([r"\documentclass{article}", rf"\input{{{outside}}}", r"\begin{document}", "Body.", r"\end{document}"]),
            encoding="utf-8",
        )

        expanded = module.expanded_latex_for_tool_detection(entry)

    assert_not_contains(expanded, r"\usepackage{biblatex}")


def test_cli_json_failure_for_non_tex_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "paper.md"
        path.write_text("not tex", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    if result.returncode == 0:
        raise AssertionError("Expected non-.tex input to fail")
    assert_contains(result.stdout, '"ok": false')
    assert_contains(result.stdout, "Expected a .tex file or directory")


def main() -> int:
    test_find_entry_prefers_root_main()
    test_find_entry_rejects_directory_without_tex()
    test_cli_reports_missing_latex_tools()
    test_pdflatex_fallback_runs_bibtex_between_latex_passes()
    test_pdflatex_fallback_uses_biber_for_biblatex()
    test_pdflatex_fallback_detects_biblatex_in_input_preamble()
    test_tool_detection_uses_project_root_for_src_entry_parent_inputs()
    test_tool_detection_expands_import_and_subimport_inputs()
    test_tool_detection_refuses_inputs_outside_project_root()
    test_cli_json_failure_for_non_tex_file()
    print("build_paper_pdf regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
