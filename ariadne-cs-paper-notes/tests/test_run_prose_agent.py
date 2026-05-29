#!/usr/bin/env python3
"""Regression tests for the pluggable Prose Phase agent runner."""

from __future__ import annotations

import importlib.util
import json
import shlex
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
                    "packet=json.load(open(os.environ['ARIADNE_PROMPT_PACKET']))",
                    "section=packet['next_section']['section_id']",
                    "bundle=pathlib.Path(os.environ['ARIADNE_BUNDLE'])",
                    "issues=bundle/'issue_artifacts'/'prose_issues.jsonl'",
                    "paras=bundle/'paragraph_decisions.jsonl'",
                    "refs=bundle/'section_reflections.json'",
                    "issues.parent.mkdir(parents=True, exist_ok=True)",
                    "with open(issues, 'a') as f: f.write(json.dumps({'local_id':'P-'+section,'section_id':section,'title':'ok'})+'\\n')",
                    "with open(paras, 'a') as f: f.write(json.dumps({'paragraph_id':'p-'+section,'section_id':section,'decision':'keep','all_sentences_reviewed':True})+'\\n')",
                    "payload={'sections': []}",
                    "if refs.exists(): payload=json.load(open(refs))",
                    "payload.setdefault('sections', []).append({'section_id': section, 'one_line': 'done', 'top_issue_ids': ['P-'+section]})",
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


def test_phase_a_runner_can_use_prompt_packet_command_bridge() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir) / "bundle"
        issues_dir = bundle / "issue_artifacts"
        issues_dir.mkdir(parents=True)
        md, jsonl = make_review_units(bundle)
        agent = Path(tempdir) / "stdin_phase_a_agent.py"
        agent.write_text(
            "\n".join(
                [
                    "import json, os, pathlib, sys",
                    "prompt=sys.stdin.read()",
                    "if '# Ariadne Agent Packet:' not in prompt: raise SystemExit(2)",
                    "packet=json.load(open(os.environ['ARIADNE_PACKET']))",
                    "section=packet['next_section']['section_id']",
                    "bundle=pathlib.Path(os.environ['ARIADNE_BUNDLE'])",
                    "issues=bundle/'issue_artifacts'/'prose_issues.jsonl'",
                    "paras=bundle/'paragraph_decisions.jsonl'",
                    "refs=bundle/'section_reflections.json'",
                    "issues.parent.mkdir(parents=True, exist_ok=True)",
                    "with open(issues, 'a') as f: f.write(json.dumps({'local_id':'P-'+section,'section_id':section,'title':'ok'})+'\\n')",
                    "with open(paras, 'a') as f: f.write(json.dumps({'paragraph_id':'p-'+section,'section_id':section,'decision':'keep','all_sentences_reviewed':True})+'\\n')",
                    "payload={'sections': []}",
                    "if refs.exists(): payload=json.load(open(refs))",
                    "payload.setdefault('sections', []).append({'section_id': section, 'one_line': 'done', 'top_issue_ids': ['P-'+section]})",
                    "json.dump(payload, open(refs, 'w'))",
                    "json.dump({'frame':'cold'}, open(bundle/'cold_skim_frame.json', 'w'))",
                    "json.dump({'claims': []}, open(bundle/'claim_candidates.json', 'w'))",
                ]
            ),
            encoding="utf-8",
        )
        bridge = ROOT / "scripts" / "run_agent_command.py"
        bridge_cmd = (
            f"{shlex.quote(sys.executable)} {shlex.quote(str(bridge))} "
            "--packet-env ARIADNE_PROMPT_PACKET --stdin-prompt "
            f"--command {shlex.quote(f'{sys.executable} {agent}')}"
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
                bridge_cmd,
                "--max-iterations",
                "4",
            ]
        )
        summary = json.loads((bundle / "prose_agent_summary.json").read_text(encoding="utf-8"))
        prompt = bundle / "phase_a_prompt_packet.json.prompt.md"
        if status != 0:
            raise AssertionError(f"Expected bridge-driven Phase A status 0, got {status}")
        if not summary["phase_a_complete"] or len(summary["calls"]) != 2:
            raise AssertionError(f"Expected bridge calls to complete Phase A, got {summary}")
        if not prompt.exists():
            raise AssertionError("Expected bridge to write a prompt file beside the packet")


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
                    "with open(issues, 'a') as f: f.write(json.dumps({'local_id':'P-'+section,'section_id':section,'title':'ok'})+'\\n')",
                    "with open(paras, 'a') as f: f.write(json.dumps({'paragraph_id':'p-'+section,'section_id':section,'decision':'keep','all_sentences_reviewed':True})+'\\n')",
                    "payload={'sections': []}",
                    "if refs.exists(): payload=json.load(open(refs))",
                    "payload.setdefault('sections', []).append({'section_id': section, 'one_line': 'done'})",
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
                    "with open(out, 'w') as f: f.write(json.dumps({'local_id':'W1','severity':'Major','issue_type':'claim','title':'whole','diagnosis':'diag','source_issue_ids':[]})+'\\n')",
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
    test_phase_a_runner_can_use_prompt_packet_command_bridge()
    test_phase_a_runner_stops_on_no_progress()
    test_phase_a_runner_can_execute_shard_manifest()
    test_phase_b_runner_builds_compact_context_and_checks_outputs()
    print("run_prose_agent regression tests passed")
