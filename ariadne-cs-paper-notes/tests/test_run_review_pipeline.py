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


def prose_issue(local_id: str = "P1", *, section_id: str = "intro", paragraph_id: str = "p-intro-001", anchor: str = "s-intro-p001-s001") -> dict[str, object]:
    return {
        "local_id": local_id,
        "severity": "Minor",
        "issue_type": "claim_boundary",
        "title": "开头主张缺少证据边界",
        "diagnosis": "这个句子给出主张，但没有说明对象、范围和证据边界。",
        "target_anchors": [anchor],
        "section_id": section_id,
        "paragraph_id": paragraph_id,
        "reader_friction": "读者还不知道证据边界，就被要求接受这个主张。",
        "writing_principle": "文字精确性先于 flow",
        "self_check": "下一稿能否在这里写清对象、范围和证据边界？",
        "evidence_refs": [{"source_artifact": "review_units.jsonl", "anchor": anchor}],
        "confidence": "high",
        "severity_rationale": "该问题影响读者判断 claim 的可信度。",
        "downgrade_condition": "补齐范围和证据边界后可降级。",
    }


def whole_paper_issue(local_id: str = "W1", *, anchor: str = "s-intro-p001-s001") -> dict[str, object]:
    return {
        "local_id": local_id,
        "severity": "Minor",
        "issue_type": "claim",
        "title": "整篇主张缺少可见证据边界",
        "diagnosis": "全稿主张没有和可见证据边界清楚对齐。",
        "target_anchors": [anchor],
        "source_issue_ids": ["prose:P1"],
        "reader_friction": "读者无法判断这个中心 claim 的可信范围。",
        "writing_principle": "改变读者理解状态",
        "self_check": "如果不补新证据，下一稿必须收窄哪一个中心 claim？",
        "evidence_refs": [{"source_artifact": "phase_b_context.json", "anchor": anchor}],
        "confidence": "medium",
        "severity_rationale": "整篇 claim/evidence 边界不清会影响审稿人判断贡献强度。",
        "downgrade_condition": "当摘要、实验和结论的 claim 边界一致后可降级。",
    }


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
        "allow_single_agent": False,
        "full_report": False,
        "skip_final_render": True,
        "skip_audit": True,
        "inline_images": False,
        "paper_layout": "source",
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
    prose_steps = [step for step in status["steps"] if step["name"] == "run_prose_agent"]
    if not prose_steps or "code-level rule_refs resolution did not run" not in prose_steps[0].get("message", ""):
        raise AssertionError(f"Pipeline should make skipped Prose rule resolution explicit: {status['steps']}")
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
                        "reader_friction": "读者会注意到不必要的表面重复词噪声。",
                        "writing_principle": "文字精确性先于 flow",
                        "self_check": "下一稿是否已经移除真实重复词，并确认这不是表格抽取噪声？",
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
            json.dumps({"paragraph_id": "p-intro-001", "section_id": "intro", "decision": "keep", "all_sentences_reviewed": True}) + "\n",
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


def test_full_pipeline_without_prose_agent_stops_before_compile() -> None:
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
            {"sections": [{"section_id": "intro", "one_line": "done", "role_in_argument": "setup", "unresolved_questions": []}]},
        )
        write_json(bundle / "claim_candidates.json", {"claim_candidates": [{"id": "C1", "text": "Claim"}]})
        (bundle / "paragraph_decisions.jsonl").write_text(
            json.dumps(
                {
                    "paragraph_id": "p-intro-001",
                    "section_id": "intro",
                    "decision": "keep",
                    "paragraph_job": "setup",
                    "next_draft_task": "None",
                    "all_sentences_reviewed": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        write_json(bundle / "argument_map.json", {"central_claim": "Claim"})
        write_json(
            bundle / "claims.json",
            {
                "claims": [
                    {
                        "claim_id": "C1",
                        "claim_text": "Claim",
                        "location": "Intro",
                        "claim_type": "fixture",
                        "strength": "modest",
                        "required_evidence": "Evidence",
                        "visible_evidence": "Sentence",
                        "status": "supported",
                        "next_draft_task": "None",
                        "linked_findings": [],
                    }
                ]
            },
        )
        write_json(bundle / "salvageable_core.json", {"core": "ok"})
        (bundle / "issue_artifacts" / "whole_paper_findings.jsonl").write_text(
            json.dumps(whole_paper_issue())
            + "\n",
            encoding="utf-8",
        )
        result = module.run_pipeline(base_args(root, tex, bundle, source))

    if result["state"] != "needs_prose_agent":
        raise AssertionError(f"Expected strict provenance stop, got {result}")
    if (bundle / "findings.json").exists():
        raise AssertionError("Pipeline should not compile final artifacts without prose-agent provenance")


def test_full_pipeline_allow_single_agent_writes_provenance() -> None:
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
            {"sections": [{"section_id": "intro", "one_line": "done", "role_in_argument": "setup", "unresolved_questions": []}]},
        )
        write_json(bundle / "claim_candidates.json", {"claim_candidates": [{"id": "C1", "text": "Claim"}]})
        (bundle / "paragraph_decisions.jsonl").write_text(
            json.dumps(
                {
                    "paragraph_id": "p-intro-001",
                    "section_id": "intro",
                    "decision": "keep",
                    "paragraph_job": "setup",
                    "next_draft_task": "None",
                    "all_sentences_reviewed": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        write_json(bundle / "argument_map.json", {"central_claim": "Claim"})
        write_json(bundle / "salvageable_core.json", {"core": "ok"})
        write_json(
            bundle / "claims.json",
            {
                "claims": [
                    {
                        "claim_id": "C1",
                        "claim_text": "Claim",
                        "location": "Intro",
                        "claim_type": "fixture",
                        "strength": "modest",
                        "required_evidence": "Evidence",
                        "visible_evidence": "Sentence",
                        "status": "supported",
                        "next_draft_task": "None",
                        "linked_findings": [],
                    }
                ]
            },
        )
        (bundle / "issue_artifacts" / "whole_paper_findings.jsonl").write_text(
            json.dumps(whole_paper_issue())
            + "\n",
            encoding="utf-8",
        )
        result = module.run_pipeline(base_args(root, tex, bundle, source, allow_single_agent=True))
        provenance = json.loads((bundle / "agent_provenance.json").read_text(encoding="utf-8"))

    if result["state"] != "complete":
        raise AssertionError(f"Expected explicit single-agent mode to compile, got {result}")
    if provenance.get("single_agent") is not True:
        raise AssertionError(f"Expected single-agent provenance marker, got {provenance}")
    if provenance.get("context_receipt", {}).get("orchestrator_read_full_review_units") is not True:
        raise AssertionError(f"Single-agent provenance should expose context receipt, got {provenance}")


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


                prompt_file = Path(os.environ["ARIADNE_PROMPT_FILE"])
                assert prompt_file.exists()
                assert "Ariadne 核心批注原则" in prompt_file.read_text(encoding="utf-8")
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
                            "problem": "这个 fixture 只写了一个很短的测试问题。",
                            "gap": "读者需要更清楚的动机。",
                            "idea": "用一个最小 fake-agent review 验证流程。",
                            "evidence": "当前只有一个 source sentence。",
                            "boundary": "这是回归测试 fixture，不是真实论文评阅。",
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
                            "title": "开头主张缺少动机边界",
                            "diagnosis": "第一句语法上干净，但没有说明这个贡献为什么值得审稿人评估。",
                            "target_anchors": ["s-intro-p001-s001"],
                            "section_id": section_id,
                            "paragraph_id": "p-intro-001",
                            "reader_friction": "读者必须自己推断这个测试贡献为什么重要。",
                            "writing_principle": "改变读者理解状态",
                            "self_check": "审稿人读完这句话后能否说出本文贡献和它为什么重要？",
                            "evidence_refs": [{"source_artifact": "review_units.jsonl", "anchor": "s-intro-p001-s001"}],
                            "confidence": "high",
                            "severity_rationale": "动机缺失会削弱审稿人对贡献价值的判断。",
                            "downgrade_condition": "补齐贡献价值和证据边界后可降级。",
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
                            "title": "整篇贡献主张还没有自解释",
                            "diagnosis": "在这个精简 fixture 中，贡献仍然是隐含的，没有写成审稿人可检查的 claim。",
                            "source_issue_ids": ["prose:P1"],
                            "target_anchors": ["s-intro-p001-s001"],
                            "claim_ids": ["C1"],
                            "reader_friction": "读者无法判断可见文本到底要求自己接受哪个贡献主张。",
                            "writing_principle": "改变读者理解状态",
                            "self_check": "摘要和引言能否写出一个可检验的中心贡献主张？",
                            "evidence_refs": [{"source_artifact": "phase_b_context.json", "anchor": "s-intro-p001-s001"}],
                            "confidence": "high",
                            "severity_rationale": "整篇贡献仍隐含，会影响审稿人判断应该接受什么。",
                            "downgrade_condition": "当摘要/引言明确一个可检验贡献主张后可降级。",
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
        manifest = json.loads((bundle / "render_manifest.json").read_text(encoding="utf-8"))
        status = json.loads((bundle / "pipeline_status.json").read_text(encoding="utf-8"))
        provenance = json.loads((bundle / "agent_provenance.json").read_text(encoding="utf-8"))
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
    if "整篇贡献主张还没有自解释" not in html:
        raise AssertionError("Final report did not render the fake whole-paper finding")
    if 'data-report-kind="paper-reader-only"' not in html:
        raise AssertionError("Default pipeline render should be paper-reader-only")
    if 'id="issue-index"' in html:
        raise AssertionError("Default paper-reader render should not append workbench issue tables")
    section_ids = [section["id"] for section in manifest.get("sections", []) if section.get("status") == "rendered"]
    if section_ids != ["paper-reader", "coverage-receipt"]:
        raise AssertionError(f"Paper-reader manifest should only declare rendered overlay sections, got {section_ids}")
    first_call = provenance["agents"][0]["calls"][0]
    if not first_call.get("context_receipt", {}).get("packet_estimated_tokens"):
        raise AssertionError(f"Prose provenance should include measured context receipt, got {provenance}")


def test_full_report_flag_is_opt_in_for_final_render() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
        bundle = root / "bundle"
        source = root / "main.source.html"
        tiny_source_html(source)
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
            source_html=source,
            review_units_jsonl=bundle / "main.review_units.jsonl",
            review_units_md=bundle / "main.review_units.md",
        )
        calls: list[list[str]] = []

        def fake_run_command(name, cmd, *, outputs=None, timeout=300):
            calls.append(cmd)
            return module.PipelineStep(name, "completed", command=cmd, outputs=[str(path) for path in outputs or []])

        original_run_command = module.run_command
        module.run_command = fake_run_command
        try:
            module.render_final(ctx, base_args(root, tex, bundle, source, skip_final_render=False, full_report=False))
            if "--full-report" in calls[-1]:
                raise AssertionError("Default final render should not pass --full-report")
            if "--paper-layout" not in calls[-1] or calls[-1][calls[-1].index("--paper-layout") + 1] != "source":
                raise AssertionError(f"Default final render should pass source paper layout, got {calls[-1]}")
            module.render_final(ctx, base_args(root, tex, bundle, source, skip_final_render=False, full_report=True))
            if "--full-report" not in calls[-1]:
                raise AssertionError("Explicit full_report=True should pass --full-report")
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
            source_html=root / "main.source.html",
            review_units_jsonl=bundle / "main.review_units.jsonl",
            review_units_md=bundle / "main.review_units.md",
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
            module.build_pdf_if_needed(ctx, base_args(root, tex, bundle, root / "main.source.html", skip_pdf_build=False))
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
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
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
            source_html=root / "main.source.html",
            review_units_jsonl=bundle / "main.review_units.jsonl",
            review_units_md=bundle / "main.review_units.md",
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
            module.build_pdf_if_needed(ctx, base_args(root, tex, bundle, root / "main.source.html", skip_pdf_build=False))
        finally:
            module.run_command = original_run_command

    if ctx.pdf != pdf.resolve():
        raise AssertionError(f"Pipeline should parse full build_pdf stdout, got {ctx.pdf}")


def test_stale_layout_audit_is_refreshed_against_current_pdf() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        tex = root / "main.tex"
        tex.write_text(r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8")
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
            source_html=root / "main.source.html",
            review_units_jsonl=bundle / "main.review_units.jsonl",
            review_units_md=bundle / "main.review_units.md",
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
            module.refresh_stale_layout_artifacts(ctx, base_args(root, tex, bundle, root / "main.source.html"))
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


if __name__ == "__main__":
    test_pipeline_prepare_checkpoint_writes_resume_packets()
    test_pipeline_partial_compile_uses_available_specialist_issues()
    test_pipeline_writes_phase_b_packet_when_phase_a_artifacts_exist()
    test_pipeline_builds_shard_manifest_when_review_units_exceed_threshold()
    test_pipeline_can_invoke_prose_agent_dry_run()
    test_pipeline_fake_agent_end_to_end_compile_render_audit()
    test_full_report_flag_is_opt_in_for_final_render()
    test_existing_pdf_with_missing_bibliography_is_rebuilt()
    test_biblatex_with_optional_resource_marks_existing_pdf_incomplete()
    test_build_pdf_parses_full_stdout_not_truncated_tail()
    test_stale_layout_audit_is_refreshed_against_current_pdf()
    print("run_review_pipeline regression tests passed")
