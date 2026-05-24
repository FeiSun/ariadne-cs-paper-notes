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


def tiny_source_html(path: Path) -> None:
    path.write_text(
        """
<!doctype html>
<html><body>
<h1 id="intro">Intro</h1>
<p data-paragraph-id="p-intro-001">
  <span data-sentence-id="s-intro-p001-s001">A compact test sentence.</span>
</p>
</body></html>
""",
        encoding="utf-8",
    )


def base_args(root: Path, tex: Path, bundle: Path, source: Path, **overrides):
    values = {
        "input": tex,
        "bundle": bundle,
        "pdf": None,
        "source_html": source,
        "report_html": bundle / "report.html",
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
        "skip_render": True,
        "prepare_only": False,
        "allow_partial_compile": False,
        "skip_final_render": True,
        "skip_audit": True,
        "inline_images": False,
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
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
        bundle = root / "bundle"
        source = root / "main.source.html"
        tiny_source_html(source)
        result = module.run_pipeline(base_args(root, tex, bundle, source, prepare_only=True))
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
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
        bundle = root / "bundle"
        source = root / "main.source.html"
        tiny_source_html(source)
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
        result = module.run_pipeline(base_args(root, tex, bundle, source, allow_partial_compile=True))
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
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
        bundle = root / "bundle"
        source = root / "main.source.html"
        tiny_source_html(source)
        (bundle / "issue_artifacts").mkdir(parents=True)
        write_json(bundle / "cold_skim_frame.json", {"problem": "P", "gap": "G", "idea": "I", "evidence": "E", "boundary": "B"})
        write_json(
            bundle / "section_reflections.json",
            {"sections": [{"section_id": "intro", "one_line": "Intro works.", "role_in_argument": "sets up", "top_issue_ids": []}]},
        )
        write_json(bundle / "claim_candidates.json", {"claim_candidates": [{"id": "C1", "text": "Claim", "location": "Intro"}]})
        (bundle / "paragraph_decisions.jsonl").write_text(
            json.dumps({"paragraph_id": "p-intro-001", "section_id": "intro", "decision": "keep"}) + "\n",
            encoding="utf-8",
        )
        result = module.run_pipeline(base_args(root, tex, bundle, source, prepare_only=True))
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
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
        bundle = root / "bundle"
        source = root / "main.source.html"
        source.write_text(
            """
<!doctype html>
<html><body>
<h1 id="intro">Intro</h1>
<p data-paragraph-id="p-intro-001"><span data-sentence-id="s-intro-p001-s001">"""
            + ("Long sentence. " * 200)
            + """</span></p>
<h1 id="method">Method</h1>
<p data-paragraph-id="p-method-001"><span data-sentence-id="s-method-p001-s001">"""
            + ("Another long sentence. " * 200)
            + """</span></p>
</body></html>
""",
            encoding="utf-8",
        )
        result = module.run_pipeline(
            base_args(root, tex, bundle, source, prepare_only=True, prose_shard_threshold=10, prose_shard_size=50)
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
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
        bundle = root / "bundle"
        source = root / "main.source.html"
        tiny_source_html(source)
        result = module.run_pipeline(
            base_args(
                root,
                tex,
                bundle,
                source,
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
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
        bundle = root / "bundle"
        source = root / "main.source.html"
        tiny_source_html(source)
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
                            "core": "The fixture keeps a clean minimal paper-reader path.",
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
                source,
                prose_agent_cmd=f"{sys.executable} {fake_agent}",
                prose_max_iterations=3,
                skip_final_render=False,
                skip_audit=False,
            )
        )
        findings = json.loads((bundle / "findings.json").read_text(encoding="utf-8"))
        annotations = json.loads((bundle / "annotations.json").read_text(encoding="utf-8"))
        status = json.loads((bundle / "pipeline_status.json").read_text(encoding="utf-8"))
        html = (bundle / "report.html").read_text(encoding="utf-8")

    if result["state"] != "complete":
        raise AssertionError(f"Expected full fake-agent pipeline to complete, got {result}")
    if len(findings.get("findings", [])) != 2:
        raise AssertionError(f"Expected prose + whole-paper findings, got {findings}")
    if len(annotations.get("annotations", [])) != 2:
        raise AssertionError(f"Expected two annotations, got {annotations}")
    step_names = [step["name"] for step in status["steps"]]
    for required in ("run_prose_agent", "compile_review_artifacts", "render_final_report", "audit_html_report", "audit_review_artifacts"):
        if required not in step_names:
            raise AssertionError(f"Pipeline did not run {required}: {step_names}")
    if "The paper-level contribution is not yet self-contained" not in html:
        raise AssertionError("Final report did not render the fake whole-paper finding")


if __name__ == "__main__":
    test_pipeline_prepare_checkpoint_writes_resume_packets()
    test_pipeline_partial_compile_uses_available_specialist_issues()
    test_pipeline_writes_phase_b_packet_when_phase_a_artifacts_exist()
    test_pipeline_builds_shard_manifest_when_review_units_exceed_threshold()
    test_pipeline_can_invoke_prose_agent_dry_run()
    test_pipeline_fake_agent_end_to_end_compile_render_audit()
    print("run_review_pipeline regression tests passed")
