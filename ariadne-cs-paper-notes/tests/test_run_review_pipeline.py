#!/usr/bin/env python3
"""Regression tests for the top-level Ariadne pipeline coordinator."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import textwrap
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_review_pipeline.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_review_pipeline", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_review_pipeline")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tiny_tex(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                r"\documentclass{article}",
                r"\begin{document}",
                r"\section{Intro}",
                "Hello.",
                r"\end{document}",
            ]
        ),
        encoding="utf-8",
    )


def base_args(root: Path, tex: Path, bundle: Path, **overrides):
    values = {
        "input": tex,
        "bundle": bundle,
        "pdf": None,
        "report_html": bundle / "report.html",
        "review_units_source": "tex",
        "paper_view": "pdf-overlay",
        "domains": "all",
        "pages": "all",
        "force_specialists": False,
        "skip_specialists": True,
        "specialist_agent_cmd": None,
        "specialist_agent_domains": "all",
        "specialist_agent_out_dir": None,
        "specialist_agent_timeout": 30,
        "specialist_agent_dry_run": False,
        "use_specialist_agent_output": False,
        "vision_figure_agent_cmd": None,
        "vision_figure_pages": "all",
        "vision_figure_agent_timeout": 30,
        "vision_figure_dry_run": False,
        "prose_agent_cmd": None,
        "prose_phase": "all",
        "prose_max_iterations": 10,
        "prose_agent_timeout": 30,
        "prose_dry_run": False,
        "prose_shard_threshold": 40_000,
        "prose_shard_size": 35_000,
        "skip_pdf_build": True,
        "prepare_only": False,
        "allow_partial_compile": False,
        "full_report": False,
        "skip_final_render": True,
        "skip_audit": True,
        "pdf_overlay_dpi": 150,
        "bbox_timeout": 30,
        "evidence_threshold": 0.80,
        "rendered_text_warn_threshold": 0.72,
        "rendered_text_error_threshold": 0.45,
        "force_rebuild": [],
        "export_annotated_pdf": False,
        "pdf_timeout": 30,
        "render_timeout": 30,
        "specialist_timeout": 30,
    }
    values.update(overrides)
    return Namespace(**values)


def test_pipeline_prepare_checkpoint_writes_resume_packets() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        bundle = root / "bundle"
        result = module.run_pipeline(base_args(root, tex, bundle, prepare_only=True))
        status = json.loads((bundle / "pipeline_status.json").read_text(encoding="utf-8"))
        resume = json.loads((bundle / "phase_a_resume_status.json").read_text(encoding="utf-8"))
        next_step = json.loads((bundle / "phase_a_next_step.json").read_text(encoding="utf-8"))
        phase_a_packet = json.loads((bundle / "phase_a_prompt_packet.json").read_text(encoding="utf-8"))
        units_exists = (bundle / "main.review_units.jsonl").exists()

    if result["state"] != "prepared":
        raise AssertionError(f"Expected prepared checkpoint, got {result}")
    if not units_exists:
        raise AssertionError("Pipeline did not extract review units")
    if status["context_policy"] != "model_readable_pipeline_status_only":
        raise AssertionError(f"Missing compact context policy: {status}")
    if resume["coverage"]["sections_pending"] != 1:
        raise AssertionError(f"Expected one pending section, got {resume['coverage']}")
    if next_step["next_section"]["section_id"] != "intro":
        raise AssertionError(f"Unexpected next-step packet: {next_step}")
    if phase_a_packet["phase"] != "phase_a" or phase_a_packet["next_section"]["section_id"] != "intro":
        raise AssertionError(f"Unexpected Phase A prompt packet: {phase_a_packet}")
    if "phase_a_prompt_packet.json" not in result["next_action"]:
        raise AssertionError(f"Pipeline next action should point to Phase A packet, got {result}")


def test_pipeline_partial_compile_uses_available_specialist_issues() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        bundle = root / "bundle"
        write_json(
            bundle / "issue_artifacts" / "polish_issues.json",
            {
                "artifact_type": "ariadne_issue_artifact",
                "schema_version": 1,
                "domain": "polish",
                "context_policy": "model_readable_issue_only",
                "status": "completed",
                "source_artifacts": [],
                "coverage": {"checked": 1, "issues": 1, "skipped": 0},
                "issues": [
                    {
                        "local_id": "polish-001",
                        "severity": "Polish",
                        "issue_type": "copyedit",
                        "title": "Repeated word",
                        "diagnosis": "A repeated word creates surface friction.",
                        "reader_friction": "The reader notices avoidable copy-editing noise.",
                        "writing_principle": "surface consistency",
                        "self_check": "Remove repeated words.",
                        "evidence_refs": [{"source_artifact": "polish_audit.json", "observation_id": "polish-001"}],
                        "confidence": 0.9,
                        "render_hint": {"anchor": "page:polish", "display_group": "Polish"},
                    }
                ],
            },
        )
        result = module.run_pipeline(base_args(root, tex, bundle, allow_partial_compile=True))
        findings = json.loads((bundle / "findings.json").read_text(encoding="utf-8"))
        status = json.loads((bundle / "pipeline_status.json").read_text(encoding="utf-8"))

    if result["state"] != "complete":
        raise AssertionError(f"Expected complete partial compile, got {result}")
    if len(findings.get("findings", [])) != 1:
        raise AssertionError(f"Expected one compiled finding, got {findings}")
    step_names = [step["name"] for step in status["steps"]]
    if "compile_review_artifacts" not in step_names or "build_review_derivatives" not in step_names:
        raise AssertionError(f"Pipeline did not run compile/derivative stages: {step_names}")


def test_pipeline_writes_phase_b_packet_when_phase_a_artifacts_exist() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        bundle = root / "bundle"
        (bundle / "issue_artifacts").mkdir(parents=True)
        write_json(bundle / "cold_skim_frame.json", {"problem": "P", "gap": "G", "idea": "I", "evidence": "E", "boundary": "B"})
        write_json(
            bundle / "section_reflections.json",
            {"sections": [{"section_id": "intro", "one_line": "Intro works.", "role_in_argument": "sets up", "top_issue_ids": []}]},
        )
        write_json(bundle / "claim_candidates.json", {"claim_candidates": [{"id": "C1", "text": "Claim", "location": "Intro"}]})
        (bundle / "paragraph_decisions.jsonl").write_text(
            json.dumps({"paragraph_id": "p-intro-001", "section_id": "intro", "decision": "keep", "all_sentences_reviewed": True}) + "\n",
            encoding="utf-8",
        )
        result = module.run_pipeline(base_args(root, tex, bundle, prepare_only=True))
        phase_b_context = json.loads((bundle / "phase_b_context.json").read_text(encoding="utf-8"))
        phase_b_packet = json.loads((bundle / "phase_b_prompt_packet.json").read_text(encoding="utf-8"))

    if result["state"] != "prepared":
        raise AssertionError(f"Expected prepared checkpoint, got {result}")
    if phase_b_context["coverage"]["sections_summarized"] != 1:
        raise AssertionError(f"Unexpected Phase B context: {phase_b_context}")
    if phase_b_packet["phase"] != "phase_b" or phase_b_packet["coverage"]["sections_summarized"] != 1:
        raise AssertionError(f"Unexpected Phase B packet: {phase_b_packet}")


def test_pipeline_builds_shard_manifest_when_review_units_exceed_threshold() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\begin{document}",
                    r"\section{Intro}",
                    "Long sentence. " * 200,
                    r"\section{Method}",
                    "Another long sentence. " * 200,
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        bundle = root / "bundle"
        result = module.run_pipeline(
            base_args(root, tex, bundle, prepare_only=True, prose_shard_threshold=10, prose_shard_size=50)
        )
        manifest = json.loads((bundle / "phase_a_shard_manifest.json").read_text(encoding="utf-8"))

    if result["state"] != "prepared":
        raise AssertionError(f"Expected prepared checkpoint, got {result}")
    if manifest["coverage"]["shards_total"] < 1 or not manifest["packet_paths"]:
        raise AssertionError(f"Expected shard manifest with packets, got {manifest}")
    if "phase_a_shard_manifest.json" not in result["next_action"]:
        raise AssertionError(f"Next action should point to shard manifest, got {result}")


def test_pipeline_can_invoke_prose_agent_dry_run() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        bundle = root / "bundle"
        result = module.run_pipeline(
            base_args(
                root,
                tex,
                bundle,
                prepare_only=True,
                prose_agent_cmd="not-a-real-agent",
                prose_dry_run=True,
                prose_max_iterations=1,
            )
        )
        summary = json.loads((bundle / "prose_agent_summary.json").read_text(encoding="utf-8"))

    if result["state"] != "prepared":
        raise AssertionError(f"Expected prepared checkpoint after prose dry-run, got {result}")
    if summary["dry_run"] is not True or not summary["calls"]:
        raise AssertionError(f"Expected prose dry-run summary, got {summary}")


def test_pipeline_fake_agent_end_to_end_compile_render_audit() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        bundle = root / "bundle"
        fake_agent = root / "fake_prose_agent.py"
        fake_agent.write_text(
            textwrap.dedent(
                """
                #!/usr/bin/env python3
                from __future__ import annotations

                import json
                import os
                from pathlib import Path


                def read_json(path: Path) -> dict:
                    if not path.exists():
                        return {}
                    return json.loads(path.read_text(encoding="utf-8"))


                def write_json(path: Path, payload: dict) -> None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")


                def append_jsonl(path: Path, row: dict) -> None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
                    encoded = json.dumps(row, ensure_ascii=False)
                    if encoded not in existing:
                        with path.open("a", encoding="utf-8") as handle:
                            handle.write(encoded + "\\n")


                packet = read_json(Path(os.environ["ARIADNE_PROMPT_PACKET"]))
                bundle = Path(os.environ["ARIADNE_BUNDLE"])
                issues_dir = Path(os.environ["ARIADNE_ISSUE_ARTIFACTS"])
                phase = packet.get("phase")

                if phase == "phase_a":
                    next_section = packet.get("next_section") or {}
                    section_id = next_section.get("section_id") or "intro"
                    write_json(
                        bundle / "cold_skim_frame.json",
                        {
                            "problem": "The draft states a compact test problem.",
                            "gap": "The reader needs clearer motivation.",
                            "idea": "Use a minimal fake-agent review.",
                            "evidence": "One source sentence is available.",
                            "boundary": "This is a regression fixture, not a real review.",
                        },
                    )
                    append_jsonl(
                        bundle / "paragraph_decisions.jsonl",
                        {
                            "paragraph_id": "p-intro-001",
                            "section_id": section_id,
                            "decision": "revise",
                            "paragraph_job": "Introduce the core claim.",
                            "next_draft_task": "Make the contribution explicit in the first paragraph.",
                            "all_sentences_reviewed": True,
                        },
                    )
                    append_jsonl(
                        issues_dir / "prose_issues.jsonl",
                        {
                            "local_id": "P1",
                            "severity": "Minor",
                            "issue_type": "motivation_gap",
                            "title": "Opening claim is too compact",
                            "diagnosis": "The first sentence is grammatically clean but gives reviewers too little motivation to evaluate the contribution.",
                            "target_anchors": ["s-intro-p001-s001"],
                            "section_id": section_id,
                            "reader_friction": "The reader has to infer why the test contribution matters.",
                            "writing_principle": "early claim framing",
                            "self_check": "Can a reviewer name the paper's contribution after this sentence?",
                        },
                    )
                    reflections = read_json(bundle / "section_reflections.json")
                    sections = [row for row in reflections.get("sections", []) if row.get("section_id") != section_id]
                    sections.append(
                        {
                            "section_id": section_id,
                            "one_line": "The introduction is concise but under-motivated.",
                            "role_in_argument": "Frames the paper's contribution.",
                            "top_issue_ids": ["P1"],
                            "unresolved_questions": ["What is the concrete contribution?"],
                        }
                    )
                    write_json(bundle / "section_reflections.json", {"sections": sections})
                    write_json(
                        bundle / "claim_candidates.json",
                        {
                            "claim_candidates": [
                                {"id": "C1", "text": "The paper makes a compact test claim.", "location": "Intro"}
                            ]
                        },
                    )
                elif phase == "phase_b":
                    write_json(
                        bundle / "argument_map.json",
                        {
                            "central_claim": "The draft needs clearer claim-evidence framing.",
                            "supporting_evidence": ["Intro sentence"],
                            "main_risks": ["Motivation remains implicit"],
                        },
                    )
                    write_json(
                        bundle / "claims.json",
                        {
                            "claims": [
                                {
                                    "claim_id": "C1",
                                    "claim_text": "The paper makes a compact test claim.",
                                    "location": "Intro",
                                    "claim_type": "contribution",
                                    "strength": "modest",
                                    "required_evidence": "A precise statement of what is contributed.",
                                    "visible_evidence": "Only a compact sentence is visible in the fixture.",
                                    "status": "under-supported",
                                    "next_draft_task": "State the contribution and why it matters.",
                                    "linked_findings": [],
                                }
                            ]
                        },
                    )
                    write_json(
                        bundle / "salvageable_core.json",
                        {
                            "core": "The fixture keeps a clean minimal PDF overlay path.",
                            "must_fix": ["Make the first claim self-contained."],
                        },
                    )
                    append_jsonl(
                        issues_dir / "whole_paper_findings.jsonl",
                        {
                            "local_id": "W1",
                            "severity": "Major",
                            "issue_type": "claim_evidence_alignment",
                            "title": "The paper-level contribution is not yet self-contained",
                            "diagnosis": "Across the compact fixture, the contribution remains implicit rather than being stated as a reviewer-checkable claim.",
                            "source_issue_ids": ["prose:P1"],
                            "target_anchors": ["s-intro-p001-s001"],
                            "claim_ids": ["C1"],
                            "reader_friction": "A reviewer cannot tell what should be accepted on the basis of the visible text.",
                            "writing_principle": "claim-evidence alignment",
                            "self_check": "Can the abstract/introduction state one falsifiable contribution claim?",
                        },
                    )
                else:
                    raise SystemExit(f"unexpected phase: {phase}")
                """
            ).lstrip(),
            encoding="utf-8",
        )
        result = module.run_pipeline(
            base_args(
                root,
                tex,
                bundle,
                prose_agent_cmd=f"{sys.executable} {fake_agent}",
                prose_max_iterations=3,
                skip_final_render=False,
                skip_audit=False,
            )
        )
        findings = json.loads((bundle / "findings.json").read_text(encoding="utf-8"))
        annotations = json.loads((bundle / "annotations.json").read_text(encoding="utf-8"))
        manifest = json.loads((bundle / "render_manifest.json").read_text(encoding="utf-8"))
        status = json.loads((bundle / "pipeline_status.json").read_text(encoding="utf-8"))
        html = (bundle / "report.html").read_text(encoding="utf-8")

    if result["state"] != "complete":
        raise AssertionError(f"Expected full fake-agent pipeline to complete, got {result}")
    if len(findings.get("findings", [])) != 2:
        raise AssertionError(f"Expected prose + whole-paper findings, got {findings}")
    if len(annotations.get("annotations", [])) != 2:
        raise AssertionError(f"Expected two annotations, got {annotations}")
    step_names = [step["name"] for step in status["steps"]]
    for required in ("run_prose_agent", "compile_review_artifacts", "audit_html_report", "audit_review_artifacts"):
        if required not in step_names:
            raise AssertionError(f"Pipeline did not run {required}: {step_names}")
    if not ({"render_pdf_overlay_report", "render_issue_report"} & set(step_names)):
        raise AssertionError(f"Pipeline did not run a final HTML renderer: {step_names}")
    if "The paper-level contribution is not yet self-contained" not in html:
        raise AssertionError("Final report did not render the fake whole-paper finding")
    if 'data-report-kind="issue-report-only"' not in html:
        raise AssertionError("Default no-PDF pipeline render should fall back to issue-report-only")
    if 'id="issue-index"' in html:
        raise AssertionError("Default PDF overlay render should not append workbench issue tables")
    section_ids = [section["id"] for section in manifest.get("sections", []) if section.get("status") == "rendered"]
    if section_ids != ["issue-report", "coverage-receipt"]:
        raise AssertionError(f"Report-only manifest should declare issue report sections, got {section_ids}")


def test_report_only_render_uses_issue_report_renderer() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        bundle = root / "bundle"
        (bundle / "annotations.json").parent.mkdir(parents=True, exist_ok=True)
        write_json(bundle / "annotations.json", {"annotations": []})
        write_json(bundle / "findings.json", {"findings": []})
        write_json(bundle / "coverage.json", {"units": []})
        write_json(bundle / "pass_observations.json", {})
        ctx = module.PipelineContext(
            input_path=tex,
            entry_tex=tex,
            bundle=bundle,
            issue_artifacts=bundle / "issue_artifacts",
            pdf=None,
            report_html=bundle / "report.html",
            review_units_jsonl=bundle / "main.review_units.jsonl",
            review_units_md=bundle / "main.review_units.md",
            sentence_bbox=bundle / "sentence_bbox.json",
            pdf_overlay_html=bundle / "ariadne_review_pdf" / "index.html",
        )
        calls: list[list[str]] = []

        def fake_run_command(name, cmd, *, outputs=None, timeout=300):
            calls.append(cmd)
            return module.PipelineStep(name, "completed", command=cmd, outputs=[str(path) for path in outputs or []])

        original_run_command = module.run_command
        module.run_command = fake_run_command
        try:
            module.render_final(ctx, base_args(root, tex, bundle, skip_final_render=False, paper_view="report-only"))
            if "render_issue_report_html.py" not in calls[-1][1]:
                raise AssertionError(f"Report-only final render should use issue renderer, got {calls[-1]}")
            if "render_paper_html.py" in " ".join(calls[-1]):
                raise AssertionError(f"Report-only final render must not use legacy paper HTML renderer: {calls[-1]}")
        finally:
            module.run_command = original_run_command


def test_existing_pdf_with_missing_bibliography_is_rebuilt() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            r"""
\documentclass{article}
\begin{document}
Hello \citep{demo}.
\bibliography{refs}
\end{document}
""",
            encoding="utf-8",
        )
        (root / "refs.bib").write_text(
            "@article{demo,title={Demo},author={A},year={2026}}\n",
            encoding="utf-8",
        )
        pdf = tex.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\n")
        tex.with_suffix(".log").write_text(
            "No file main.bbl.\nPackage natbib Warning: There were undefined citations.\n",
            encoding="utf-8",
        )
        bundle = root / "bundle"
        ctx = module.PipelineContext(
            input_path=tex,
            entry_tex=tex,
            bundle=bundle,
            issue_artifacts=bundle / "issue_artifacts",
            pdf=pdf,
            report_html=bundle / "report.html",
            review_units_jsonl=bundle / "main.review_units.jsonl",
            review_units_md=bundle / "main.review_units.md",
            sentence_bbox=bundle / "sentence_bbox.json",
            pdf_overlay_html=bundle / "ariadne_review_pdf" / "index.html",
        )
        calls: list[list[str]] = []

        def fake_run_command(name, cmd, *, outputs=None, timeout=300):
            calls.append(cmd)
            return module.PipelineStep(
                name,
                "completed",
                command=cmd,
                stdout_tail=json.dumps({"ok": True, "pdf": str(pdf), "tool": "latexmk"}),
                outputs=[str(pdf)],
            )

        original_run_command = module.run_command
        module.run_command = fake_run_command
        try:
            module.build_pdf_if_needed(ctx, base_args(root, tex, bundle, skip_pdf_build=False))
        finally:
            module.run_command = original_run_command

    if not calls:
        raise AssertionError("Pipeline should rebuild an existing PDF when the bibliography pass is incomplete")
    if ctx.pdf != pdf.resolve():
        raise AssertionError(f"Rebuilt PDF should be retained, got {ctx.pdf}")
    if not any("missing a completed bibliography pass" in warning for warning in ctx.warnings):
        raise AssertionError(f"Expected bibliography rebuild warning, got {ctx.warnings}")


def test_biblatex_with_optional_resource_marks_existing_pdf_incomplete() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(
            "\n".join(
                [
                    r"\documentclass{article}",
                    r"\usepackage[backend=biber,style=authoryear]{biblatex}",
                    r"\addbibresource[location=local]{refs.bib}",
                    r"\begin{document}",
                    r"Hello \cite{demo}.",
                    r"\printbibliography",
                    r"\end{document}",
                ]
            ),
            encoding="utf-8",
        )
        pdf = tex.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\n")
        tex.with_suffix(".log").write_text("No file main.bbl.\n", encoding="utf-8")

        if not module.latex_uses_bibliography(tex):
            raise AssertionError("Pipeline should detect biblatex resources with options as bibliography usage")
        if not module.existing_pdf_has_incomplete_bibliography(tex, pdf):
            raise AssertionError("Existing PDF without a bbl should be treated as incomplete for biblatex papers")


def test_build_pdf_parses_full_stdout_not_truncated_tail() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        pdf = tex.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\n")
        bundle = root / "bundle"
        ctx = module.PipelineContext(
            input_path=tex,
            entry_tex=tex,
            bundle=bundle,
            issue_artifacts=bundle / "issue_artifacts",
            pdf=None,
            report_html=bundle / "report.html",
            review_units_jsonl=bundle / "main.review_units.jsonl",
            review_units_md=bundle / "main.review_units.md",
            sentence_bbox=bundle / "sentence_bbox.json",
            pdf_overlay_html=bundle / "ariadne_review_pdf" / "index.html",
        )

        def fake_run_command(name, cmd, *, outputs=None, timeout=300):
            payload = json.dumps({"ok": True, "pdf": str(pdf), "tool": "latexmk"})
            return module.PipelineStep(
                name,
                "completed",
                command=cmd,
                stdout=payload,
                stdout_tail=("x" * 2000) + payload[-20:],
                outputs=[str(pdf)],
            )

        original_run_command = module.run_command
        module.run_command = fake_run_command
        try:
            module.build_pdf_if_needed(ctx, base_args(root, tex, bundle, skip_pdf_build=False))
        finally:
            module.run_command = original_run_command

    if ctx.pdf != pdf.resolve():
        raise AssertionError(f"Pipeline should parse full build_pdf stdout, got {ctx.pdf}")


def test_stale_layout_audit_is_refreshed_against_current_pdf() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        pdf = tex.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\ncurrent")
        bundle = root / "bundle"
        issue_artifacts = bundle / "issue_artifacts"
        write_json(
            bundle / "layout_audit.json",
            {
                "pdf": str(pdf),
                "pdf_hash": "sha256:00000000",
                "pages_total": 1,
                "pages_checked": [1],
                "observations": [],
            },
        )
        write_json(
            issue_artifacts / "layout_issues.json",
            {
                "artifact_type": "ariadne_issue_artifact",
                "schema_version": 1,
                "domain": "layout",
                "context_policy": "model_readable_issue_only",
                "status": "skipped",
                "source_artifacts": [
                    {
                        "path": str(bundle / "layout_audit.json"),
                        "hash": "sha256:stale",
                        "context_policy": "tool_output_hash_only",
                    }
                ],
                "coverage": {"checked": 1, "issues": 0, "skipped": 1},
                "issues": [],
            },
        )
        ctx = module.PipelineContext(
            input_path=tex,
            entry_tex=tex,
            bundle=bundle,
            issue_artifacts=issue_artifacts,
            pdf=pdf,
            report_html=bundle / "report.html",
            review_units_jsonl=bundle / "main.review_units.jsonl",
            review_units_md=bundle / "main.review_units.md",
            sentence_bbox=bundle / "sentence_bbox.json",
            pdf_overlay_html=bundle / "ariadne_review_pdf" / "index.html",
        )
        calls: list[str] = []

        def fake_run_command(name, cmd, *, outputs=None, timeout=300):  # noqa: ARG001
            calls.append(name)
            out = Path(cmd[cmd.index("--out") + 1])
            if name == "refresh_layout_audit":
                write_json(
                    out,
                    {
                        "tool": "scripts/check_page_layout.py",
                        "tool_version": "1",
                        "script_hash": "sha256:11111111",
                        "pdf": str(pdf.resolve()),
                        "pdf_hash": module.sha256_path(pdf),
                        "pages_total": 1,
                        "pages_checked": [1],
                        "page_summaries": [],
                        "observations": [],
                    },
                )
            elif name == "refresh_layout_issues":
                raw = bundle / "layout_audit.json"
                write_json(
                    out,
                    {
                        "artifact_type": "ariadne_issue_artifact",
                        "schema_version": 1,
                        "domain": "layout",
                        "context_policy": "model_readable_issue_only",
                        "status": "skipped",
                        "source_artifacts": [
                            {
                                "path": str(raw),
                                "hash": module.sha256_path(raw),
                                "context_policy": "tool_output_hash_only",
                            }
                        ],
                        "coverage": {"checked": 1, "issues": 0, "skipped": 1},
                        "issues": [],
                    },
                )
            return module.PipelineStep(name, "completed", command=cmd, outputs=[str(path) for path in outputs or []])

        original_run_command = module.run_command
        original_which = module.shutil.which
        module.run_command = fake_run_command
        module.shutil.which = lambda name: "/usr/bin/pdftotext-test" if name == "pdftotext" else original_which(name)
        try:
            module.refresh_stale_layout_artifacts(ctx, base_args(root, tex, bundle))
        finally:
            module.run_command = original_run_command
            module.shutil.which = original_which

        refreshed_audit = json.loads((bundle / "layout_audit.json").read_text(encoding="utf-8"))
        refreshed_issues = json.loads((issue_artifacts / "layout_issues.json").read_text(encoding="utf-8"))
        expected_pdf_hash = module.sha256_path(pdf)
        expected_raw_hash = module.sha256_path(bundle / "layout_audit.json")

    if calls != ["refresh_layout_audit", "refresh_layout_issues"]:
        raise AssertionError(f"Expected stale layout audit and issues to refresh, got calls={calls}")
    if refreshed_audit["pdf_hash"] != expected_pdf_hash:
        raise AssertionError(f"Layout audit did not bind to current PDF: {refreshed_audit}")
    if refreshed_issues["source_artifacts"][0]["hash"] != expected_raw_hash:
        raise AssertionError(f"Layout issues did not bind to refreshed raw audit: {refreshed_issues}")
    if not any("compiled PDF changed" in warning for warning in ctx.warnings):
        raise AssertionError(f"Expected refresh warning, got {ctx.warnings}")


def test_pdf_overlay_path_uses_tex_units_and_overlay_renderer() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        pdf = tex.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\n")
        bundle = root / "bundle"
        calls: list[str] = []

        def fake_run_command(name, cmd, *, outputs=None, timeout=300):  # noqa: ARG001
            calls.append(name)
            for output in outputs or []:
                path = Path(output)
                if path.suffix:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.name.endswith(".jsonl"):
                        path.write_text(
                            json.dumps(
                                {
                                    "kind": "paragraph",
                                    "paragraph_id": "p-front-matter-001",
                                    "section_id": "front-matter",
                                    "sentences": [
                                        {
                                            "sentence_id": "s-front-matter-001-s001",
                                            "unit_kind": "prose",
                                            "text": "Hello.",
                                            "rendered_text_initial": "Hello.",
                                            "source_file": str(tex),
                                            "line_start": 1,
                                            "line_end": 1,
                                            "text_hash": "sha256:11111111",
                                        }
                                    ],
                                }
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                    elif path.name.endswith(".md"):
                        path.write_text("{s-front-matter-001-s001} Hello.\n", encoding="utf-8")
                    elif path.name == "findings.json":
                        write_json(path, {"findings": []})
                    elif path.name == "annotations.json":
                        write_json(path, {"annotations": []})
                    elif path.name == "sentence_bbox.json":
                        write_json(path, {"anchors": {}})
                    elif path.name.endswith(".html"):
                        path.write_text(
                            '<article class="review-report" data-report-kind="pdf-overlay"><section id="paper-reader"><div class="paper-pane pdf-paper-pane" data-paper-view="pdfjs-overlay" data-source-artifact="x" data-source-hash="sha256:11111111" data-sentence-id-scheme="section-paragraph-sentence-v2" data-annotation-mode="pdfjs-overlay"></div><aside id="annotation-panel"></aside></section><section id="bbox-diagnostics"></section><section id="coverage-receipt"></section></article>',
                            encoding="utf-8",
                        )
                    else:
                        write_json(path, {})
            return module.PipelineStep(name, "completed", command=cmd, outputs=[str(path) for path in outputs or []])

        original_run_command = module.run_command
        module.run_command = fake_run_command
        try:
            result = module.run_pipeline(
                base_args(
                    root,
                    tex,
                    bundle,
                    pdf=pdf,
                    review_units_source="tex",
                    paper_view="pdf-overlay",
                    allow_partial_compile=True,
                    skip_specialists=True,
                    skip_final_render=False,
                    skip_audit=True,
                )
            )
        finally:
            module.run_command = original_run_command

    if result["state"] != "complete":
        raise AssertionError(f"Expected complete pdf-overlay run, got {result}")
    if "extract_tex_review_units" not in calls:
        raise AssertionError(f"Expected TeX review-unit extraction, got {calls}")
    if "render_pdf_overlay_report" not in calls:
        raise AssertionError(f"Expected PDF overlay renderer, got {calls}")


def test_tex_review_units_source_artifact_is_entry_tex() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        bundle = root / "bundle"
        args = base_args(root, tex, bundle, review_units_source="tex")
        ctx = module.initialize_context(args)

    if module.current_source_artifact(ctx, args) != tex.resolve():
        raise AssertionError("TeX review-unit mode should bind audits to the entry .tex source")


def test_prepare_layout_audit_runs_before_tex_review_units_when_pdf_exists() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tiny_tex(tex)
        pdf = tex.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.4\n")
        bundle = root / "bundle"
        ctx = module.initialize_context(base_args(root, tex, bundle, pdf=pdf))
        calls: list[str] = []

        def fake_run_command(name, cmd, *, outputs=None, timeout=300):  # noqa: ARG001
            calls.append(name)
            for output in outputs or []:
                path = Path(output)
                write_json(
                    path,
                    {
                        "pdf_hash": module.sha256_path(pdf),
                        "pages_total": 1,
                        "pages_checked": [1],
                        "page_summaries": [],
                        "observations": [],
                    },
                )
            return module.PipelineStep(name, "completed", command=cmd, outputs=[str(path) for path in outputs or []])

        original_run_command = module.run_command
        original_which = module.shutil.which
        module.run_command = fake_run_command
        module.shutil.which = lambda name: "/usr/bin/pdftotext-test" if name == "pdftotext" else original_which(name)
        try:
            module.prepare_layout_audit_for_review_units(ctx, base_args(root, tex, bundle, pdf=pdf))
        finally:
            module.run_command = original_run_command
            module.shutil.which = original_which

    if calls != ["prepare_layout_audit_for_review_units"]:
        raise AssertionError(f"Expected layout audit prep call, got {calls}")


if __name__ == "__main__":
    test_pipeline_prepare_checkpoint_writes_resume_packets()
    test_pipeline_partial_compile_uses_available_specialist_issues()
    test_pipeline_writes_phase_b_packet_when_phase_a_artifacts_exist()
    test_pipeline_builds_shard_manifest_when_review_units_exceed_threshold()
    test_pipeline_can_invoke_prose_agent_dry_run()
    test_pipeline_fake_agent_end_to_end_compile_render_audit()
    test_report_only_render_uses_issue_report_renderer()
    test_existing_pdf_with_missing_bibliography_is_rebuilt()
    test_biblatex_with_optional_resource_marks_existing_pdf_incomplete()
    test_build_pdf_parses_full_stdout_not_truncated_tail()
    test_stale_layout_audit_is_refreshed_against_current_pdf()
    test_pdf_overlay_path_uses_tex_units_and_overlay_renderer()
    test_tex_review_units_source_artifact_is_entry_tex()
    test_prepare_layout_audit_runs_before_tex_review_units_when_pdf_exists()
    print("run_review_pipeline regression tests passed")
