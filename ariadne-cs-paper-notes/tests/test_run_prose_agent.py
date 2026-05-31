#!/usr/bin/env python3
"""Regression tests for the pluggable Prose Phase agent runner."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_prose_agent.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_prose_agent", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load run_prose_agent")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def make_review_units(bundle: Path) -> tuple[Path, Path]:
    md = bundle / "main.review_units.md"
    jsonl = bundle / "main.review_units.jsonl"
    md.write_text("# Intro\n{s1} Sentence.\n\n# Method\n{s2} Sentence.\n", encoding="utf-8")
    write_jsonl(
        jsonl,
        [
            {"kind": "section", "section_id": "intro", "text": "Introduction"},
            {"kind": "paragraph", "paragraph_id": "p-intro", "section_id": "intro", "sentences": [{"sentence_id": "s1"}]},
            {"kind": "section", "section_id": "method", "text": "Method"},
            {"kind": "paragraph", "paragraph_id": "p-method", "section_id": "method", "sentences": [{"sentence_id": "s2"}]},
        ],
    )
    return md, jsonl


def prose_issue_expr(local_id: str, section_expr: str, paragraph_expr: str, anchor_expr: str) -> str:
    return (
        "{"
        f"'local_id':{local_id},"
        "'severity':'Minor',"
        "'issue_type':'claim_boundary',"
        "'title':'开头主张缺少证据边界',"
        "'diagnosis':'这个句子给出主张，但没有说明对象、范围和证据边界。',"
        "'reader_friction':'读者还不知道证据边界，就被要求接受这个主张。',"
        "'writing_principle':'文字精确性先于 flow',"
        "'self_check':'下一稿能否在这里写清对象、范围和证据边界？',"
        "'confidence':'high',"
        f"'evidence_refs':[{{'source_artifact':'review_units.jsonl','anchor':{anchor_expr}}}],"
        "'severity_rationale':'该问题影响读者判断 claim 的可信度。',"
        "'downgrade_condition':'补齐范围和证据边界后可降级。',"
        f"'section_id':{section_expr},"
        f"'paragraph_id':{paragraph_expr},"
        f"'target_anchors':[{anchor_expr}]"
        "}"
    )


def test_dry_run_builds_phase_a_packet_without_calling_agent() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        bundle.mkdir()
        md, jsonl = make_review_units(bundle)
        status = module.main(
            [
                "--bundle",
                str(bundle),
                "--phase",
                "phase_a",
                "--review-units-md",
                str(md),
                "--review-units-jsonl",
                str(jsonl),
                "--agent-cmd",
                "definitely-not-a-real-agent",
                "--dry-run",
            ]
        )
        summary = json.loads((bundle / "prose_agent_summary.json").read_text(encoding="utf-8"))
        if status != 1:
            raise AssertionError(f"Dry-run pending Phase A should return 1, got {status}")
        if not (bundle / "phase_a_prompt_packet.json").exists():
            raise AssertionError("Phase A prompt packet was not written")
        if summary["calls"][0]["status"] != "dry_run":
            raise AssertionError(f"Expected dry-run call summary, got {summary}")
        prompt_file = Path(summary["calls"][0]["prompt_file"])
        prompt_text = prompt_file.read_text(encoding="utf-8")
        if "## Resolved Rule References" not in prompt_text or "Ariadne 核心批注原则" not in prompt_text:
            raise AssertionError(f"Dry-run prompt should resolve Prose rule refs: {prompt_text[:500]}")
        if "读者卡点 -> 单一违反原则 -> 自改问题" not in prompt_text:
            raise AssertionError(f"Dry-run prompt should include Chinese teaching contract: {prompt_text[:500]}")
        provenance = json.loads((bundle / "agent_provenance.json").read_text(encoding="utf-8"))
        call = provenance["agents"][0]["calls"][0]
        if not call.get("prompt_hash") or not call.get("resolved_rule_refs"):
            raise AssertionError(f"Prose dry-run should write prompt/rule receipts, got {provenance}")


def test_phase_a_runner_refreshes_resume_until_complete() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        issues_dir = bundle / "issue_artifacts"
        issues_dir.mkdir(parents=True)
        md, jsonl = make_review_units(bundle)
        agent = Path(tempdir) / "fake_phase_a_agent.py"
        agent.write_text(
            "\n".join(
                [
                    "import json, os, pathlib",
                    "prompt=pathlib.Path(os.environ['ARIADNE_PROMPT_FILE'])",
                    "assert prompt.exists() and 'Ariadne 核心批注原则' in prompt.read_text()",
                    "packet=json.load(open(os.environ['ARIADNE_PROMPT_PACKET']))",
                    "section=packet['next_section']['section_id']",
                    "bundle=pathlib.Path(os.environ['ARIADNE_BUNDLE'])",
                    "issues=bundle/'issue_artifacts'/'prose_issues.jsonl'",
                    "paras=bundle/'paragraph_decisions.jsonl'",
                    "refs=bundle/'section_reflections.json'",
                    "issues.parent.mkdir(parents=True, exist_ok=True)",
                    "anchor='s1' if section == 'intro' else 's2'",
                    "issue=" + prose_issue_expr("'P-'+section", "section", "'p-'+section", "anchor"),
                    "with open(issues, 'a') as f: f.write(json.dumps(issue, ensure_ascii=False)+'\\n')",
                    "with open(paras, 'a') as f: f.write(json.dumps({'paragraph_id':'p-'+section,'section_id':section,'decision':'keep','paragraph_job':'fixture','next_draft_task':'补齐边界。','all_sentences_reviewed':True,'linked_issue_ids':['P-'+section]}, ensure_ascii=False)+'\\n')",
                    "payload={'sections': []}",
                    "if refs.exists(): payload=json.load(open(refs))",
                    "payload.setdefault('sections', []).append({'section_id': section, 'one_line': 'done', 'role_in_argument':'fixture','unresolved_questions':[],'top_issue_ids': ['P-'+section]})",
                    "json.dump(payload, open(refs, 'w'))",
                    "json.dump({'frame':'cold'}, open(bundle/'cold_skim_frame.json', 'w'))",
                    "json.dump({'claims': []}, open(bundle/'claim_candidates.json', 'w'))",
                ]
            ),
            encoding="utf-8",
        )
        status = module.main(
            [
                "--bundle",
                str(bundle),
                "--phase",
                "phase_a",
                "--review-units-md",
                str(md),
                "--review-units-jsonl",
                str(jsonl),
                "--agent-cmd",
                f"{sys.executable} {agent}",
                "--max-iterations",
                "4",
            ]
        )
        summary = json.loads((bundle / "prose_agent_summary.json").read_text(encoding="utf-8"))
        if status != 0:
            raise AssertionError(f"Expected completed Phase A status 0, got {status}")
        if not summary["phase_a_complete"] or len(summary["calls"]) != 2:
            raise AssertionError(f"Expected two section calls and Phase A complete, got {summary}")


def test_phase_a_runner_stops_on_no_progress() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        bundle.mkdir()
        md, jsonl = make_review_units(bundle)
        agent = Path(tempdir) / "no_progress_agent.py"
        agent.write_text("pass\n", encoding="utf-8")
        status = module.main(
            [
                "--bundle",
                str(bundle),
                "--phase",
                "phase_a",
                "--review-units-md",
                str(md),
                "--review-units-jsonl",
                str(jsonl),
                "--agent-cmd",
                f"{sys.executable} {agent}",
                "--max-iterations",
                "3",
            ]
        )
        summary = json.loads((bundle / "prose_agent_summary.json").read_text(encoding="utf-8"))
        if status != 1:
            raise AssertionError(f"No-progress Phase A should return 1, got {status}")
        if summary["calls"][0]["status"] != "no_progress":
            raise AssertionError(f"Expected no_progress call status, got {summary}")


def test_phase_a_runner_can_execute_shard_manifest() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        bundle.mkdir()
        md, jsonl = make_review_units(bundle)
        shard_manifest = bundle / "phase_a_shard_manifest.json"
        shard_dir = bundle / "phase_a_shards"
        shard_dir.mkdir()
        packets = []
        for idx, section_id in enumerate(("intro", "method"), 1):
            packet = {
                "schema_version": 1,
                "context_policy": "model_readable_prose_phase_packet",
                "phase": "phase_a_shard",
                "shard": {"shard_id": f"phase-a-shard-{idx:03d}", "section_ids": [section_id]},
                "write_targets": {
                    "prose_issues": {"path": str(bundle / "issue_artifacts" / "prose_issues.jsonl")},
                    "paragraph_decisions": {"path": str(bundle / "paragraph_decisions.jsonl")},
                    "section_reflections": {"path": str(bundle / "section_reflections.json")},
                    "cold_skim_frame": {"path": str(bundle / "cold_skim_frame.json")},
                    "claim_candidates": {"path": str(bundle / "claim_candidates.json")},
                },
            }
            path = shard_dir / f"phase-a-shard-{idx:03d}.json"
            write_json(path, packet)
            packets.append(str(path))
        write_json(
            shard_manifest,
            {
                "schema_version": 1,
                "context_policy": "model_readable_shard_manifest_only",
                "shards": [
                    {"shard_id": "phase-a-shard-001", "section_ids": ["intro"]},
                    {"shard_id": "phase-a-shard-002", "section_ids": ["method"]},
                ],
                "packet_paths": packets,
            },
        )
        agent = Path(tempdir) / "fake_shard_agent.py"
        agent.write_text(
            "\n".join(
                [
                    "import json, os, pathlib",
                    "packet=json.load(open(os.environ['ARIADNE_PROMPT_PACKET']))",
                    "section=packet['shard']['section_ids'][0]",
                    "bundle=pathlib.Path(os.environ['ARIADNE_BUNDLE'])",
                    "issues=bundle/'issue_artifacts'/'prose_issues.jsonl'",
                    "paras=bundle/'paragraph_decisions.jsonl'",
                    "refs=bundle/'section_reflections.json'",
                    "issues.parent.mkdir(parents=True, exist_ok=True)",
                    "anchor='s1' if section == 'intro' else 's2'",
                    "issue=" + prose_issue_expr("'P-'+section", "section", "'p-'+section", "anchor"),
                    "with open(issues, 'a') as f: f.write(json.dumps(issue, ensure_ascii=False)+'\\n')",
                    "with open(paras, 'a') as f: f.write(json.dumps({'paragraph_id':'p-'+section,'section_id':section,'decision':'keep','paragraph_job':'fixture','next_draft_task':'补齐边界。','all_sentences_reviewed':True,'linked_issue_ids':['P-'+section]}, ensure_ascii=False)+'\\n')",
                    "payload={'sections': []}",
                    "if refs.exists(): payload=json.load(open(refs))",
                    "payload.setdefault('sections', []).append({'section_id': section, 'one_line': 'done', 'role_in_argument':'fixture','unresolved_questions':[],'top_issue_ids':['P-'+section]})",
                    "json.dump(payload, open(refs, 'w'))",
                    "json.dump({'frame':'cold'}, open(bundle/'cold_skim_frame.json', 'w'))",
                    "json.dump({'claims': []}, open(bundle/'claim_candidates.json', 'w'))",
                ]
            ),
            encoding="utf-8",
        )
        status = module.main(
            [
                "--bundle",
                str(bundle),
                "--phase",
                "phase_a",
                "--review-units-md",
                str(md),
                "--review-units-jsonl",
                str(jsonl),
                "--shard-manifest",
                str(shard_manifest),
                "--agent-cmd",
                f"{sys.executable} {agent}",
                "--max-iterations",
                "4",
            ]
        )
        summary = json.loads((bundle / "prose_agent_summary.json").read_text(encoding="utf-8"))
        if status != 0:
            raise AssertionError(f"Expected sharded Phase A completion, got status {status}")
        if not summary["phase_a_complete"] or [call["phase"] for call in summary["calls"]] != ["phase_a_shard", "phase_a_shard"]:
            raise AssertionError(f"Unexpected shard summary: {summary}")


def test_phase_b_runner_builds_compact_context_and_checks_outputs() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        (bundle / "issue_artifacts").mkdir(parents=True)
        write_json(bundle / "cold_skim_frame.json", {"one_line": "cold"})
        write_json(bundle / "section_reflections.json", {"sections": [{"section_id": "intro", "one_line": "done"}]})
        write_json(bundle / "claim_candidates.json", {"claims": [{"id": "C1", "text": "claim"}]})
        write_json(bundle / "issue_artifacts" / "layout_issues.json", {"domain": "layout", "status": "skipped", "issues": []})
        agent = Path(tempdir) / "fake_phase_b_agent.py"
        agent.write_text(
            "\n".join(
                [
                    "import json, os, pathlib",
                    "bundle=pathlib.Path(os.environ['ARIADNE_BUNDLE'])",
                    "json.dump({'argument':'ok'}, open(bundle/'argument_map.json', 'w'))",
                    "json.dump({'claims': []}, open(bundle/'claims.json', 'w'))",
                    "json.dump({'core':'ok'}, open(bundle/'salvageable_core.json', 'w'))",
                    "out=bundle/'issue_artifacts'/'whole_paper_findings.jsonl'",
                    "with open(out, 'w') as f: f.write(json.dumps({'local_id':'W1','severity':'Major','issue_type':'claim','title':'整篇主张缺少边界','diagnosis':'全稿主张没有和可见证据边界清楚对齐。','reader_friction':'读者无法判断中心 claim 的可信范围。','writing_principle':'改变读者理解状态','self_check':'如果不补新证据，下一稿必须收窄哪一个中心 claim？','confidence':'high','evidence_refs':[{'source_artifact':'phase_b_context.json','anchor':'paper'}],'severity_rationale':'整篇 claim/evidence 边界不清会影响审稿人判断贡献强度。','downgrade_condition':'当全稿 claim、证据和边界一致后可降级。','source_issue_ids':[]}, ensure_ascii=False)+'\\n')",
                ]
            ),
            encoding="utf-8",
        )
        status = module.main(
            [
                "--bundle",
                str(bundle),
                "--phase",
                "phase_b",
                "--agent-cmd",
                f"{sys.executable} {agent}",
            ]
        )
        summary = json.loads((bundle / "prose_agent_summary.json").read_text(encoding="utf-8"))
        if status != 0:
            raise AssertionError(f"Expected completed Phase B status 0, got {status}")
        if not summary["phase_b_complete"] or not (bundle / "phase_b_context.json").exists():
            raise AssertionError(f"Expected phase_b_context and complete summary, got {summary}")


if __name__ == "__main__":
    test_dry_run_builds_phase_a_packet_without_calling_agent()
    test_phase_a_runner_refreshes_resume_until_complete()
    test_phase_a_runner_stops_on_no_progress()
    test_phase_a_runner_can_execute_shard_manifest()
    test_phase_b_runner_builds_compact_context_and_checks_outputs()
    print("run_prose_agent regression tests passed")
