#!/usr/bin/env python3
"""Minimal regression tests for extract_paper_text.py."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import importlib.util
import os
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_paper_text.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_paper_text", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load extract_paper_text module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_extract(path: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path), "-o", "-", "--max-items", "50"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def assert_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"Missing expected text: {needle}\n--- output ---\n{text[:4000]}")


def assert_not_contains(text: str, needle: str) -> None:
    if needle in text:
        raise AssertionError(f"Unexpected text present: {needle}\n--- output ---\n{text[:4000]}")


def test_latex_signals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "refs.bib").write_text("@article{x2024,title={X},year={2024}}\n", encoding="utf-8")
        (root / "main.tex").write_text(
            "\n".join(
                [
                    r"\documentclass[anonymous=false]{article}",
                    r"\title{A Precise Paper}",
                    r"\author{Jane Doe \and John Smith}",
                    r"\affiliation{University of Somewhere}",
                    r"\begin{document}",
                    r"\maketitle",
                    r"\begin{abstract}We improve performance.\end{abstract}",
                    r"\section[Short Intro]{Long Introduction with \texttt{Macro}}",
                    r"Really?? This should not be treated as a broken reference. See \ref{??}.",
                    r"\section{Method}",
                    r"\begin{equation}",
                    r"s_i = f(q, d_i)",
                    r"\end{equation}",
                    r"\section{Why This Matters}",
                    r"Smith et al. [3] show a related result.",
                    r"\bibliography{refs}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        output = run_extract(root)

    assert_contains(output, "section: Long Introduction with Macro")
    assert_contains(output, "section: Why This Matters")
    assert_contains(output, "equation: s_i = f(q, d_i)")
    assert_contains(output, "author command: Jane Doe John Smith")
    assert_contains(output, "affiliation/institute command: University of Somewhere")
    assert_contains(output, "anonymous/final switch: anonymous=false")
    assert_contains(output, "Long Introduction with Macro:")
    assert_contains(output, "Why This Matters:")


def test_latex_signal_scans_ignore_commented_template_commands() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "custom.bib").write_text("@article{x2024,title={X},year={2024}}\n", encoding="utf-8")
        (root / "anthology.bib").write_text("@article{unused2024,title={Unused},year={2024}}\n", encoding="utf-8")
        (root / "main.tex").write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"% Template note: both \title{} and \workshoptitle{} are required.",
                    r"% \bibliography{anthology,custom}",
                    r"\title{Actual Paper Title}",
                    r"\begin{document}",
                    r"\begin{abstract}Short abstract.\end{abstract}",
                    r"\section{Intro}",
                    r"\caption{Real caption}",
                    r"\bibliography{custom}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        output = run_extract(root)

    assert_contains(output, "Title: Actual Paper Title")
    assert_contains(output, "Caption 1: Real caption")
    assert_contains(output, "custom.bib: 1 entries")
    assert_not_contains(output, "Title: \n")
    assert_not_contains(output, "anthology.bib")


def test_latex_signals_without_pandoc() -> None:
    module = load_module()
    real_which = module.shutil.which
    raw = "\n".join(
        [
            r"\documentclass{article}",
            r"\begin{document}",
            r"\section[Short]{Fallback Introduction}",
            r"Intro text.",
            r"\section{Fallback Method}",
            r"Method text.",
            r"\end{document}",
        ]
    )
    state = module.ExtractionState()
    with mock.patch.object(module.shutil, "which", lambda name: None if name == "pandoc" else real_which(name)):
        plain = module.latex_to_plain(raw, state)
    sections = [(m.group(1), module.one_line(m.group(2))) for m in module.SECTION_CMD_RE.finditer(raw)]
    stats = module.section_word_stats(plain, [title for _, title in sections], 50)

    assert_contains(plain, "## SECTION: Fallback Introduction")
    if stats == [("Whole extracted text", len(plain.split()), 0)]:
        raise AssertionError(f"Fallback stats degraded to whole text: {stats}\n{plain}")
    if not any(title == "Fallback Introduction" for title, _, _ in stats):
        raise AssertionError(f"Missing fallback introduction stats: {stats}\n{plain}")
    if not any(title == "Fallback Method" for title, _, _ in stats):
        raise AssertionError(f"Missing fallback method stats: {stats}\n{plain}")


def test_pandoc_runs_with_sandbox_and_temp_cwd() -> None:
    module = load_module()
    state = module.ExtractionState()
    calls = []

    class Result:
        returncode = 0
        stdout = "Plain text"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    with mock.patch.object(module.shutil, "which", lambda name: "/usr/bin/pandoc" if name == "pandoc" else None):
        with mock.patch.object(module.subprocess, "run", fake_run):
            text = module.run_pandoc_latex(r"\input{/etc/passwd}", state)

    if text != "Plain text":
        raise AssertionError(text)
    if not calls:
        raise AssertionError("Expected pandoc subprocess call")
    cmd, kwargs = calls[0]
    if "--sandbox" not in cmd:
        raise AssertionError(f"Expected --sandbox in pandoc command, got {cmd}")
    cwd = kwargs.get("cwd")
    if not cwd or Path(cwd) == Path.cwd():
        raise AssertionError(f"Expected pandoc to run from an isolated temp cwd, got {cwd}")


def test_pdf_heading_heuristic_no_generic_noise() -> None:
    sample = "\n".join(
        [
            "A Tiny Paper",
            "",
            "Abstract",
            "We improve a method on two tasks.",
            "",
            "1 Introduction",
            "Large models fail in a narrow setting [1].",
            "",
            "John Smith",
            "Boston University",
            "Table 1",
            "",
            "2 Method",
            "The method uses a selector.",
            "",
            "References",
            "[1] A. Author. Example. 2024.",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "paper.txt"
        path.write_text(sample, encoding="utf-8")
        module = load_module()
        state = module.ExtractionState()
        output = "\n".join(module.summarize_pdf(sample, path, state, 50))

    assert_contains(output, "1 Introduction")
    assert_contains(output, "2 Method")
    assert_not_contains(output, "- John Smith")
    assert_not_contains(output, "- Boston University")
    assert_not_contains(output, "- Table 1")


def test_pdf_heading_heuristic_skips_submission_line_numbers_and_table_fragments() -> None:
    sample = "\n".join(
        [
            "Abstract",
            "We improve a method.",
            "80   Our main contributions are summarized as follows:",
            "204   further examine whether the improvement in factual recall",
            "4",
            "\f                                                 Base           Voting         CoT               RL",
            "67.9",
            "      Total Cases",
            "1 Introduction",
            "Body text [Zhang et al., 2026].",
            "2 Method",
            "More text [Guo et al., 2025, Wen et al., 2026].",
        ]
    )
    module = load_module()
    state = module.ExtractionState()
    output = "\n".join(module.summarize_pdf(sample, Path("paper.pdf"), state, 50))

    assert_contains(output, "- Abstract")
    assert_contains(output, "- 1 Introduction")
    assert_contains(output, "- 2 Method")
    assert_contains(output, "Citation-like markers detected: 2")
    assert_not_contains(output, "80   Our main contributions")
    assert_not_contains(output, "204   further examine")
    assert_not_contains(output, "Base           Voting")
    assert_not_contains(output, "Total Cases")


def test_pdf_coverage_metadata_uses_detected_page_count() -> None:
    module = load_module()
    state = module.ExtractionState(pdf_page_count=7, pdf_page_count_source="test")
    output = "\n".join(module.summarize_pdf("Abstract\nText.", Path("paper.pdf"), state, 50))

    assert_contains(output, "## PDF Coverage Metadata")
    assert_contains(output, "Page count: 7 (source: test)")
    assert_contains(output, "must use this page count")


def test_pdf_numeric_audit_uses_visible_grouped_score_and_header_avg() -> None:
    module = load_module()
    sample = "\n".join(
        [
            "Table 1: Performance comparison of Method A with baselines.",
            "                         MSSBench   SIUO   SafeRLHF   VLGuard   MMSafetyBench   VLSafe",
            "Model       Method                                                     Score X",
            "                          (DSRp)    (DSRp)  (DSRp)     (DSRp)    (DSRh)          (DSRh)",
            "Model X     Method A          98.00     91.62   89.50      90.00     100.00          97.50     95.77",
            "",
            "Table 3: Performance of Method A on general capability benchmarks.",
            "                         MMMU                                      LiveBench",
            "Model       Method      Art     Business  Science  Tech   Health  Humanities  Avg.  Recognition  Analysis Thinking Realworld Avg.",
            "Qwen        Origin      67.78   28.89     37.50    25.00  31.11   35.56       47.7  77.10       82.40    89.00    77.90     81.60",
            "Model Y     Method A       64.44   28.89     45.50    23.20  35.56   40.80       45.4  75.20       80.98    86.5     76.6      79.82",
        ]
    )
    signals = module.pdf_line_numeric_audit(sample, 50)

    table1_resam = next(
        signal for signal in signals if signal["table_id"] == "Table 1" and signal["row_label"].endswith("Method A")
    )
    if table1_resam["reported_value"] != "95.77":
        raise AssertionError(table1_resam)
    if table1_resam["visible_computed_value"] != "95.52":
        raise AssertionError(table1_resam)
    if table1_resam["delta"] != "+0.25":
        raise AssertionError(table1_resam)
    if table1_resam["formula"] != "component_mean_of_means":
        raise AssertionError(table1_resam)
    if table1_resam["required_severity"] != "Blocker":
        raise AssertionError(table1_resam)

    table3_origin = next(
        signal for signal in signals if signal["table_id"] == "Table 3" and signal["row_label"].endswith("Origin") and signal["reported_value"] == "47.7"
    )
    if table3_origin["visible_computed_value"] != "37.64" or table3_origin["delta"] != "+10.06":
        raise AssertionError(table3_origin)

    table3_resam = next(
        signal for signal in signals if signal["table_id"] == "Table 3" and signal["row_label"].endswith("Method A") and signal["reported_value"] == "45.4"
    )
    if table3_resam["visible_computed_value"] != "39.73" or table3_resam["delta"] != "+5.67":
        raise AssertionError(table3_resam)
    if table3_resam["required_severity"] != "Blocker":
        raise AssertionError(table3_resam)


def test_pdfinfo_timeout_falls_back_with_warning() -> None:
    module = load_module()
    state = module.ExtractionState()
    real_which = module.shutil.which

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    with mock.patch.object(module.shutil, "which", lambda name: "/usr/bin/pdfinfo" if name == "pdfinfo" else real_which(name)):
        with mock.patch.object(module.subprocess, "run", fake_run):
            with mock.patch.dict(sys.modules, {"pypdf": None, "pdfplumber": None}):
                page_count = module.detect_pdf_page_count(Path("paper.pdf"), state)

    if page_count is not None:
        raise AssertionError(f"Expected no page count after mocked fallbacks, got {page_count}")
    warnings = "\n".join(state.warnings)
    assert_contains(warnings, "pdfinfo timed out")
    assert_contains(warnings, "Could not determine PDF page count")


def test_table_sanity_surfaces_blank_cells() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\begin{tabular}{lccc}",
            r"Method & A & B & C \\",
            r"Mean Log Prob. & 0.1 & 0.2 & 0.3 \\",
            r"Verbalized Conf. & 0.5985 & & \\",
            r"Semantic Entropy & 0.4 & -- & 0.6 \\",
            r"\end{tabular}",
        ]
    )
    output = "\n".join(module.summarize_table_sanity(raw, 50))

    assert_contains(output, "Table Completeness and Blank-Cell Signals")
    assert_contains(output, "Table 1, row 3")
    assert_contains(output, "blank/placeholder cell")
    assert_contains(output, "Verbalized Conf.")
    assert_contains(output, "do not claim a baseline is covered on all settings")


def test_table_parser_handles_escaped_ampersands_and_dash_placeholders() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\begin{tabular}{lcc}",
            r"Method \& Variant & A & B \\",
            "Model A & – & — \\\\",
            r"Model B & 1.0 & 2.0 \\",
            r"\end{tabular}",
        ]
    )
    rows = module.visible_table_rows(module.TABULAR_ENV_RE.search(raw).group(2))
    if rows[0][1][0] != "Method & Variant":
        raise AssertionError(rows)
    output = "\n".join(module.summarize_table_sanity(raw, 50))
    assert_contains(output, "blank/placeholder cell")
    assert_contains(output, "Model A")


def test_table_sanity_does_not_treat_multirow_scaffolding_as_blank_data() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\begin{tabular}{llrr}",
            r"& & \textbf{A} & \textbf{B} \\",
            r"\multirow{2}{*}{Group} & TP & 43 & 45 \\",
            r"& TN & 44 & 44 \\",
            r"Model & Missing & & 0.6 \\",
            r"\end{tabular}",
        ]
    )
    output = "\n".join(module.summarize_table_sanity(raw, 50))

    assert_contains(output, "Model")
    assert_contains(output, "blank/placeholder cell")
    assert_not_contains(output, "row 1: blank/placeholder")
    assert_not_contains(output, "row 3: blank/placeholder")


def test_table_numeric_signals_surface_reported_computed_delta() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\begin{tabular}{lcccc}",
            r"Method & MM-Vet & POPE & MME & Score X \\",
            r"Method A & 95.00 & 96.00 & 95.56 & 95.77 \\",
            r"ECSO & 90.00 & 91.00 & 92.00 & 91.00 \\",
            r"\end{tabular}",
        ]
    )
    output = "\n".join(module.summarize_table_sanity(raw, 50))

    assert_contains(output, "Table Numeric Recalculation Signals")
    assert_contains(output, "Method A")
    assert_contains(output, "Score X")
    assert_contains(output, "Signal (ambiguous gap 0.25pp")
    assert_contains(output, "reported 95.77")
    assert_contains(output, "visible arithmetic mean of column(s) 2, 3, 4 = 95.52")
    assert_contains(output, "delta +0.25")
    assert_contains(output, "Rendered finding must be Blocker")
    assert_contains(output, "state the concrete reported value")
    assert_contains(output, "instead of using vague")
    assert_not_contains(output.lower(), "wrong")


def test_numeric_no_signal_message_is_a_caveat_not_a_clean_bill() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\begin{tabular}{lrr}",
            r"Method & A & B \\",
            r"Model & 1.0 & 2.0 \\",
            r"\end{tabular}",
        ]
    )
    output = "\n".join(module.summarize_table_sanity(raw, 50))
    assert_contains(output, "not a proof that tables are numerically correct")

    pdf_lines, _ = module.summarize_pdf_table_numeric_signals("Table 1\nModel A 1.0 2.0", 50)
    assert_contains("\n".join(pdf_lines), "not a proof that tables are numerically correct")


def test_table_numeric_signals_classify_large_gap_as_deterministic() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\begin{tabular}{lccccccc}",
            r"Model & A & B & C & D & E & F & Avg \\",
            r"Qwen2.5-32B & 35.00 & 36.00 & 37.00 & 38.00 & 39.00 & 40.84 & 47.70 \\",
            r"\end{tabular}",
        ]
    )
    output = "\n".join(module.summarize_table_sanity(raw, 50))

    assert_contains(output, "Signal (deterministic gap")
    assert_contains(output, "reported 47.70")
    assert_contains(output, "visible arithmetic mean of column(s) 2, 3, 4, 5, 6, 7 = 37.64")
    assert_contains(output, "Rendered finding must be Blocker")
    assert_contains(output, "Gap exceeds the broad plausible aggregation range")


def test_expand_inputs_ignores_commented_inputs_before_real_include() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        section = root / "Section"
        tables = root / "Tables"
        section.mkdir()
        tables.mkdir()
        (root / "main.tex").write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\input{Section/background}",
                    r"\input{Section/appendix}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        (section / "background.tex").write_text(r"% \input{Tables/data_split}", encoding="utf-8")
        (section / "appendix.tex").write_text(r"\input{Tables/data_split}", encoding="utf-8")
        (tables / "data_split.tex").write_text("REAL TABLE CONTENT", encoding="utf-8")
        state = module.ExtractionState()
        text = module.expand_inputs(root / "main.tex", state, root=root)

    assert_contains(text, "REAL TABLE CONTENT")
    assert_not_contains("\n".join(state.warnings), "Skipped recursive input")


def test_placeholder_captions_are_marked_not_ranked_as_normal_takeaways() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\documentclass{article}",
            r"\begin{document}",
            r"\caption{Caption}",
            r"\caption{A real evidence-bearing caption.}",
            r"\end{document}",
        ]
    )
    state = module.ExtractionState()
    output = "\n".join(module.summarize_latex(raw, module.latex_to_plain(raw, state), Path("paper.tex"), state, 50))

    assert_contains(output, "Caption 1: Caption [placeholder caption]")
    assert_contains(output, "Caption 2: A real evidence-bearing caption.")


def test_symbol_consistency_signals_surface_macro_and_variant_drift() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\newcommand{\risk}{R}",
            r"\renewcommand{\risk}{\mathcal{R}}",
            r"\begin{equation}",
            r"\epsilon = \varepsilon + \mystery(x)",
            r"\end{equation}",
        ]
    )
    output = "\n".join(module.summarize_symbol_consistency(raw, 50))

    assert_contains(output, r"Macro \risk has 2 distinct expansions")
    assert_contains(output, r"Command-like math token \mystery")
    assert_contains(output, r"Variant symbol pair \epsilon and \varepsilon")
    assert_contains(output, "Signal only")
    assert_not_contains(output.lower(), "equation is wrong")


def test_placeholder_and_identity_signals() -> None:
    module = load_module()
    raw = "\n".join(
        [
            r"\documentclass{article}",
            r"\author{A. Author \thanks{Supported by a grant. ORCID: 0000-0002-1825-0097}}",
            r"\iclrfinalcopy",
            r"\begin{document}",
            r"Really?? This should not count as a broken reference.",
            r"Page ?? should be reviewed manually but is not a LaTeX ref.",
            r"Broken ref: \ref{??}. Broken cite: \cite{?}.",
            r"This paragraph discusses a prior camera-ready version.",
            r"\end{document}",
        ]
    )
    state = module.ExtractionState()
    output = "\n".join(module.summarize_common(raw, raw, state, 50))

    assert_contains(output, r"\ref{??}")
    assert_contains(output, r"\cite{?}")
    assert_contains(output, r"anonymous/final switch: \iclrfinalcopy")
    assert_contains(output, "ORCID: 0000-0002-1825-0097")
    assert_contains(output, "thanks: Supported by a grant. ORCID: 0000-0002-1825-0097")
    assert_contains(output, "informational camera-ready text: camera-ready")
    assert_not_contains(output, "anonymous/final switch: camera-ready")
    assert_not_contains(output, "author command: A. Author Supported by a grant")


def test_plain_placeholder_pass_does_not_duplicate_raw_latex_signal() -> None:
    module = load_module()
    raw = r"Broken ref: \ref{??}. Broken cite: \cite{?}."
    plain = "Broken ref: ??. Broken cite: ?."
    state = module.ExtractionState()
    output = "\n".join(module.summarize_common(plain, raw, state, 50))

    assert_contains(output, r"\ref{??}")
    assert_contains(output, r"\cite{?}")
    assert_not_contains(output, "- Line 1: ??")
    if output.count("- Line 1:") != 2:
        raise AssertionError(f"Expected only two raw placeholder signals:\n{output}")


def test_cli_default_writes_to_temp_file_not_stdout() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.tex").write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Intro}",
                    r"Body.",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(root), "--max-items", "5"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    prefix = "Wrote signals to "
    if result.stdout:
        raise AssertionError(f"Default extraction should not write to stdout:\n{result.stdout[:1000]}")
    if prefix not in result.stderr:
        raise AssertionError(f"Missing default output path in stderr:\n{result.stderr}")
    generated = Path(result.stderr.strip().split(prefix, 1)[1])
    try:
        mode = generated.stat().st_mode & 0o777
        if mode != 0o600:
            raise AssertionError(f"Expected private default output mode 0600, got {oct(mode)} for {generated}")
        text = generated.read_text(encoding="utf-8")
        assert_contains(text, "# Review Signals")
        assert_contains(text, "# Extracted LaTeX Text")
    finally:
        generated.unlink(missing_ok=True)


def test_cli_refuses_existing_output_without_force() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper"
        root.mkdir()
        (root / "main.tex").write_text(r"\documentclass{article}\begin{document}Body.\end{document}", encoding="utf-8")
        output = Path(tmp) / "extract.md"
        output.write_text("existing", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(root), "-o", str(output), "--max-items", "5"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    if result.returncode == 0:
        raise AssertionError("Expected existing --output to fail without --force")
    assert_contains(result.stderr, "File exists")


def test_cli_force_overwrites_private_output_and_numeric_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper"
        root.mkdir()
        (root / "main.tex").write_text(r"\documentclass{article}\begin{document}Body.\end{document}", encoding="utf-8")
        output = Path(tmp) / "extract.md"
        numeric = Path(tmp) / "numeric.json"
        output.write_text("existing", encoding="utf-8")
        numeric.write_text("existing", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(root),
                "-o",
                str(output),
                "--numeric-json",
                str(numeric),
                "--force",
                "--max-items",
                "5",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        output_mode = output.stat().st_mode & 0o777
        numeric_mode = numeric.stat().st_mode & 0o777

    if result.stdout:
        raise AssertionError(result.stdout)
    if output_mode != 0o600 or numeric_mode != 0o600:
        raise AssertionError(f"Expected private modes, got output={oct(output_mode)} numeric={oct(numeric_mode)}")


def test_default_output_path_uses_source_hash_to_avoid_collisions() -> None:
    module = load_module()
    first = Path("/tmp/first/main.tex")
    second = Path("/tmp/second/main.tex")

    first_output = module.default_output_path(first)
    second_output = module.default_output_path(second)

    if first_output == second_output:
        raise AssertionError(f"Expected distinct output paths, got {first_output}")
    assert_contains(first_output.name, "paper_review_extract_main_")
    assert_contains(second_output.name, "paper_review_extract_main_")
    if module.default_output_path(first) == first_output:
        raise AssertionError("Expected default output path to include a random suffix")


def test_input_recursion_warning() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.tex").write_text(r"\input{child}", encoding="utf-8")
        (root / "child.tex").write_text(r"\input{main}", encoding="utf-8")
        state = module.ExtractionState()
        module.expand_inputs(root / "main.tex", state)

    warnings = "\n".join(state.warnings)
    assert_contains(warnings, "Skipped recursive input")
    assert_contains(warnings, "as traversal boundary")


def test_expand_inputs_without_root_uses_project_boundary() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.tex").write_text("Body", encoding="utf-8")
        state = module.ExtractionState()
        module.expand_inputs(root / "main.tex", state)

    assert_contains("\n".join(state.warnings), "as traversal boundary")


def test_tilde_input_is_not_expanded_outside_project_tree() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper"
        fake_home = Path(tmp) / "home"
        root.mkdir()
        fake_home.mkdir()
        home_secret = fake_home / "ariadne_should_not_read.tex"
        main = root / "main.tex"
        main.write_text(r"\input{~/ariadne_should_not_read}", encoding="utf-8")
        state = module.ExtractionState()
        with mock.patch.dict(os.environ, {"HOME": str(fake_home)}):
            home_secret.write_text("HOME SECRET", encoding="utf-8")
            text = module.expand_inputs(main, state, root=root)

    assert_not_contains(text, "HOME SECRET")
    assert_contains("\n".join(state.warnings), "Missing input file")


def test_input_outside_project_tree_is_refused() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper"
        root.mkdir()
        outside = Path(tmp) / "sensitive.tex"
        outside.write_text("SECRET OUTSIDE CONTENT", encoding="utf-8")
        main = root / "main.tex"
        main.write_text(r"\input{../sensitive}", encoding="utf-8")
        state = module.ExtractionState()
        text = module.expand_inputs(main, state, root=root)

    assert_not_contains(text, "SECRET OUTSIDE CONTENT")
    assert_contains("\n".join(state.warnings), "Refused to read input outside project tree")


def test_legitimate_parent_input_from_src_entry_is_allowed() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        src = project / "src"
        src.mkdir(parents=True)
        (project / "intro.tex").write_text("INTRO CONTENT", encoding="utf-8")
        main = src / "main.tex"
        main.write_text(r"\input{../intro}", encoding="utf-8")
        state = module.ExtractionState()
        root = module.project_root_for(main)
        text = module.expand_inputs(main, state, root=root)

    assert_contains(text, "INTRO CONTENT")
    assert_not_contains("\n".join(state.warnings), "Refused to read input outside project tree")


def test_absolute_input_outside_project_tree_is_refused() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper"
        root.mkdir()
        outside = Path(tmp) / "sensitive.tex"
        outside.write_text("ABSOLUTE SECRET", encoding="utf-8")
        main = root / "main.tex"
        main.write_text(rf"\input{{{outside}}}", encoding="utf-8")
        state = module.ExtractionState()
        text = module.expand_inputs(main, state, root=root)

    assert_not_contains(text, "ABSOLUTE SECRET")
    assert_contains("\n".join(state.warnings), "Refused to read input outside project tree")


def test_missing_bib_warning_reaches_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.tex").write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Intro}",
                    r"\bibliography{this_bib_does_not_exist}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        output = run_extract(root)

    assert_contains(output, "## Extraction Warnings")
    assert_contains(output, "Missing bibliography file referenced in TeX")
    assert_not_contains(output, "## Extraction Warnings\n- None.")


def test_bibliography_file_count_excludes_non_publication_bibtex_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "refs.bib").write_text(
            "\n".join(
                [
                    "@string{acl = {ACL}}",
                    "@comment{ignored note}",
                    "@preamble{ignored preamble}",
                    "@article{x2024,title={X},year={2024}}",
                    "@inproceedings{y2025,title={Y},booktitle=acl,year={2025}}",
                ]
            ),
            encoding="utf-8",
        )
        (root / "main.tex").write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\bibliography{refs}",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        output = run_extract(root)

    assert_contains(output, "refs.bib: 2 entries")
    assert_not_contains(output, "refs.bib: 5 entries")


def test_dotted_bib_filename_not_false_missing() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "acl.2024.bib").write_text("@article{x2024,title={X}}\n", encoding="utf-8")
        raw = r"\bibliography{acl.2024}"
        state = module.ExtractionState()
        bibs = module.find_bib_files(root, raw, state)

    warnings = "\n".join(state.warnings)
    if not any(bib.name == "acl.2024.bib" for bib in bibs):
        raise AssertionError(f"Expected acl.2024.bib in bibs, got {bibs}")
    assert_not_contains(warnings, "Missing bibliography file")


def test_bib_path_is_resolved_relative_to_entry_parent_with_project_root_boundary() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        src = project / "src"
        bib_dir = project / "bib"
        src.mkdir(parents=True)
        bib_dir.mkdir()
        (bib_dir / "refs.bib").write_text("@article{x2024,title={X}}\n", encoding="utf-8")
        entry = src / "main.tex"
        entry.write_text(r"\bibliography{../bib/refs}", encoding="utf-8")
        state = module.ExtractionState()
        bibs = module.find_bib_files(entry, entry.read_text(encoding="utf-8"), state)

    if not any(bib.name == "refs.bib" for bib in bibs):
        raise AssertionError(f"Expected refs.bib in bibs, got {bibs}")
    assert_not_contains("\n".join(state.warnings), "Refused to read bibliography outside project tree")


def test_reference_style_signals_surface_bib_drift() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bib = root / "refs.bib"
        bib.write_text(
            "\n".join(
                [
                    "@inproceedings{short,",
                    "  title={Short},",
                    "  booktitle={ACL},",
                    "  pages={1-2},",
                    "  url={https://example.com/short}",
                    "}",
                    "@inproceedings{long,",
                    "  title={Long},",
                    "  booktitle={Proceedings of the Annual Meeting of the Association for Computational Linguistics},",
                    "  pages={3--4},",
                    "  doi={10.1000/example}",
                    "}",
                    "@article{preprint,",
                    "  title={Preprint},",
                    "  journal={arXiv preprint},",
                    "  eprint={2401.00001}",
                    "}",
                ]
            ),
            encoding="utf-8",
        )
        state = module.ExtractionState()
        output = "\n".join(module.summarize_bib_style([bib], state, 50))

    assert_contains(output, "Reference Style Signals")
    assert_contains(output, "Reference Entry Coverage")
    assert_contains(output, "short (inproceedings):")
    assert_contains(output, "long (inproceedings):")
    assert_contains(output, "preprint (article):")
    assert_contains(output, "`url` field present in 1/3 entries")
    assert_contains(output, "`doi` field present in 1/3 entries")
    assert_contains(output, "`eprint` field present in 1/3 entries")
    assert_contains(output, "`booktitle` style mix")
    assert_contains(output, "Pages separator drift")


def test_reference_style_handles_single_line_bib_entries() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bib = root / "compact.bib"
        bib.write_text(
            "\n".join(
                [
                    "@inproceedings{vaswani2017attention, title={Attention is all you need}, booktitle={NIPS}, year={2017}, pages={5998--6008}, url={https://example.com/attention}}",
                    "@inproceedings{devlin2018bert, title={BERT}, booktitle={Proceedings of NAACL}, year={2019}, pages={4171-4186}}",
                    "@inproceedings{brown2020language, title={Language Models are Few-Shot Learners}, booktitle={NeurIPS}, year={2020}, doi={10.5555/123456}}",
                ]
            ),
            encoding="utf-8",
        )
        state = module.ExtractionState()
        output = "\n".join(module.summarize_bib_style([bib], state, 50))

    assert_contains(output, "vaswani2017attention (inproceedings):")
    assert_contains(output, "venue='NIPS'")
    assert_contains(output, "url=yes")
    assert_contains(output, "doi=yes")
    assert_contains(output, "`url` field present in 1/3 entries")
    assert_contains(output, "`doi` field present in 1/3 entries")
    assert_contains(output, "Pages separator drift")


def test_reference_style_reports_no_drift_when_uniform() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bib = root / "uniform.bib"
        bib.write_text(
            "\n".join(
                [
                    "@article{a, title={A}, journal={Journal}, year={2024}, pages={1--2}}",
                    "@article{b, title={B}, journal={Journal}, year={2025}, pages={3--4}}",
                ]
            ),
            encoding="utf-8",
        )
        state = module.ExtractionState()
        output = "\n".join(module.summarize_bib_style([bib], state, 50))

    assert_contains(output, "No obvious URL/DOI/eprint, booktitle, entry-type, or page-format drift detected.")


def test_bib_outside_project_tree_is_refused() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper"
        root.mkdir()
        outside = Path(tmp) / "outside.bib"
        outside.write_text("@article{x,title={X}}\n", encoding="utf-8")
        state = module.ExtractionState()
        bibs = module.find_bib_files(root, rf"\bibliography{{{outside}}}", state)

    if bibs:
        raise AssertionError(f"Expected no outside bibs, got {bibs}")
    assert_contains("\n".join(state.warnings), "Refused to read bibliography outside project tree")


def test_tilde_bib_path_is_not_expanded_outside_project_tree() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper"
        fake_home = Path(tmp) / "home"
        root.mkdir()
        fake_home.mkdir()
        home_bib = fake_home / "ariadne_should_not_read.bib"
        state = module.ExtractionState()
        with mock.patch.dict(os.environ, {"HOME": str(fake_home)}):
            home_bib.write_text("@article{secret,title={Secret}}\n", encoding="utf-8")
            bibs = module.find_bib_files(root, r"\bibliography{~/ariadne_should_not_read}", state)

    if bibs:
        raise AssertionError(f"Expected no home bibs, got {bibs}")
    assert_contains("\n".join(state.warnings), "Missing bibliography file referenced in TeX")


def test_non_utf8_source_warns_about_replacement() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.tex"
        path.write_bytes(b"Author: S\xe9bastien")
        state = module.ExtractionState()
        text = module.read_text(path, state)

    assert_contains(text, "\ufffd")
    assert_contains("\n".join(state.warnings), "Non-UTF-8 bytes")


def test_cli_rejects_nonpositive_max_items() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "main.tex").write_text(
            "\n".join([r"\documentclass{article}", r"\begin{document}", "Body.", r"\end{document}"]),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(root), "-o", "-", "--max-items", "0"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    if result.returncode == 0:
        raise AssertionError("Expected --max-items 0 to fail")
    assert_contains(result.stderr, "must be a positive integer")


def main() -> int:
    test_latex_signals()
    test_latex_signals_without_pandoc()
    test_pandoc_runs_with_sandbox_and_temp_cwd()
    test_pdf_heading_heuristic_no_generic_noise()
    test_pdf_coverage_metadata_uses_detected_page_count()
    test_pdfinfo_timeout_falls_back_with_warning()
    test_table_sanity_surfaces_blank_cells()
    test_table_parser_handles_escaped_ampersands_and_dash_placeholders()
    test_table_numeric_signals_surface_reported_computed_delta()
    test_table_numeric_signals_classify_large_gap_as_deterministic()
    test_symbol_consistency_signals_surface_macro_and_variant_drift()
    test_placeholder_and_identity_signals()
    test_plain_placeholder_pass_does_not_duplicate_raw_latex_signal()
    test_cli_default_writes_to_temp_file_not_stdout()
    test_default_output_path_uses_source_hash_to_avoid_collisions()
    test_input_recursion_warning()
    test_expand_inputs_without_root_uses_project_boundary()
    test_tilde_input_is_not_expanded_outside_project_tree()
    test_input_outside_project_tree_is_refused()
    test_legitimate_parent_input_from_src_entry_is_allowed()
    test_absolute_input_outside_project_tree_is_refused()
    test_missing_bib_warning_reaches_output()
    test_dotted_bib_filename_not_false_missing()
    test_bib_path_is_resolved_relative_to_entry_parent_with_project_root_boundary()
    test_reference_style_signals_surface_bib_drift()
    test_reference_style_handles_single_line_bib_entries()
    test_reference_style_reports_no_drift_when_uniform()
    test_bib_outside_project_tree_is_refused()
    test_tilde_bib_path_is_not_expanded_outside_project_tree()
    test_non_utf8_source_warns_about_replacement()
    test_cli_rejects_nonpositive_max_items()
    print("extract_paper_text regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
