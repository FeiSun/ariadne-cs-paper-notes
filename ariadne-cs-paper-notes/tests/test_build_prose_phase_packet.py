#!/usr/bin/env python3
"""Regression tests for compact Prose Phase prompt packets."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_prose_phase_packet.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_prose_phase_packet", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load build_prose_phase_packet")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_phase_a_packet_names_next_section_and_write_targets() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bundle = root / "bundle"
        bundle.mkdir()
        md = bundle / "main.review_units.md"
        jsonl = bundle / "main.review_units.jsonl"
        md.write_text("# Intro\n{s1} Sentence.\n", encoding="utf-8")
        jsonl.write_text(json.dumps({"kind": "section", "section_id": "intro", "text": "Intro"}) + "\n", encoding="utf-8")
        write_json(bundle / "phase_a_resume_status.json", {"coverage": {"sections_total": 1, "sections_pending": 1}})
        write_json(
            bundle / "phase_a_next_step.json",
            {"next_section": {"section_id": "intro", "title": "Intro", "order": 1, "paragraphs": 1, "sentences": 1}},
        )
        packet = module.build_phase_a_packet(
            review_units_md=md,
            review_units_jsonl=jsonl,
            resume_status=bundle / "phase_a_resume_status.json",
            next_step_path=bundle / "phase_a_next_step.json",
            prose_issues=bundle / "issue_artifacts" / "prose_issues.jsonl",
            paragraph_decisions=bundle / "paragraph_decisions.jsonl",
            section_reflections=bundle / "section_reflections.json",
            cold_skim=bundle / "cold_skim_frame.json",
            claim_candidates=bundle / "claim_candidates.json",
        )
    if packet["context_policy"] != "model_readable_prose_phase_packet":
        raise AssertionError(f"Missing packet context policy: {packet}")
    if packet["next_section"]["section_id"] != "intro":
        raise AssertionError(f"Unexpected next section: {packet}")
    if packet["write_targets"]["prose_issues"]["mode"] != "append_jsonl_by_section":
        raise AssertionError(f"Unexpected prose target: {packet['write_targets']}")


def test_phase_b_packet_uses_compact_context_only() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bundle = root / "bundle"
        bundle.mkdir()
        context = bundle / "phase_b_context.json"
        write_json(context, {"coverage": {"sections_summarized": 2, "specialist_domains": 3, "issue_count": 5}})
        packet = module.build_phase_b_packet(
            phase_b_context=context,
            argument_map=bundle / "argument_map.json",
            claims=bundle / "claims.json",
            salvageable_core=bundle / "salvageable_core.json",
            whole_paper_findings=bundle / "issue_artifacts" / "whole_paper_findings.jsonl",
        )
    if packet["phase"] != "phase_b":
        raise AssertionError(f"Expected phase_b packet, got {packet}")
    if packet["coverage"]["issue_count"] != 5:
        raise AssertionError(f"Coverage did not propagate: {packet}")
    if len(packet["read_inputs"]) != 1 or packet["read_inputs"][0]["path"].endswith("review_units.md"):
        raise AssertionError(f"Phase B packet should read compact context only: {packet['read_inputs']}")


if __name__ == "__main__":
    test_phase_a_packet_names_next_section_and_write_targets()
    test_phase_b_packet_uses_compact_context_only()
    print("build_prose_phase_packet regression tests passed")
