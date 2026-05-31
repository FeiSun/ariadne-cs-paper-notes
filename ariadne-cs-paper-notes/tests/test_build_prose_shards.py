#!/usr/bin/env python3
"""Regression tests for oversized Prose Phase A shard manifest builder."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_prose_shards.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_prose_shards", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load build_prose_shards")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_build_prose_shards_writes_manifest_and_packets() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bundle = root / "bundle"
        bundle.mkdir()
        md = bundle / "review_units.md"
        jsonl = bundle / "review_units.jsonl"
        md.write_text("# A\ntext\n# B\ntext\n", encoding="utf-8")
        long_text = "word " * 200
        write_jsonl(
            jsonl,
            [
                {"kind": "section", "section_id": "a", "text": "A"},
                {"kind": "paragraph", "section_id": "a", "text": long_text, "sentences": [{"text": long_text}]},
                {"kind": "section", "section_id": "b", "text": "B"},
                {"kind": "paragraph", "section_id": "b", "text": long_text, "sentences": [{"text": long_text}]},
            ],
        )
        manifest = module.build_manifest(bundle=bundle, review_units_md=md, review_units_jsonl=jsonl, max_tokens=250)
        out = bundle / "phase_a_shard_manifest.json"
        status = module.main(
            [
                "--bundle",
                str(bundle),
                "--review-units-md",
                str(md),
                "--review-units-jsonl",
                str(jsonl),
                "--max-tokens-per-shard",
                "250",
                "--out",
                str(out),
            ]
        )
        written = json.loads(out.read_text(encoding="utf-8"))
        if status != 0:
            raise AssertionError(f"build_prose_shards CLI returned {status}")
        if manifest["coverage"]["shards_total"] < 2:
            raise AssertionError(f"Expected multiple shards, got {manifest}")
        if written["context_policy"] != "model_readable_shard_manifest_only":
            raise AssertionError(f"Unexpected manifest context policy: {written}")
        for packet_path in written["packet_paths"]:
            packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
            if packet["phase"] != "phase_a_shard" or not packet["shard"]["section_ids"]:
                raise AssertionError(f"Bad shard packet: {packet}")
            rule_ids = [item["id"] for item in packet["rule_refs"]]
            base_rule_ids = [name for name, _purpose in module.SHARD_BASE_PHASE_A_RULES]
            if rule_ids != base_rule_ids:
                raise AssertionError(f"Shard packet missing base prose rules: {packet}")
            if "method_rules" in rule_ids or "experiment_rules" in rule_ids or "related_work_rules" in rule_ids:
                raise AssertionError(f"Generic shard should not load section-specific rules: {rule_ids}")
            minimum_fields = packet["output_contract"]["prose_issues_jsonl"]["minimum_fields"]
            for required in ("reader_friction", "writing_principle", "self_check", "confidence", "evidence_refs", "severity_rationale", "downgrade_condition"):
                if required not in minimum_fields:
                    raise AssertionError(f"Shard prose contract missing {required}: {minimum_fields}")
            if not any("读者卡点 -> 单一违反原则 -> 自改问题" in instruction for instruction in packet["instructions"]):
                raise AssertionError(f"Shard instructions missing Chinese teaching contract: {packet['instructions']}")


def test_build_prose_shards_adds_section_specific_rule_refs() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bundle = root / "bundle"
        bundle.mkdir()
        md = bundle / "review_units.md"
        jsonl = bundle / "review_units.jsonl"
        md.write_text("# Method\ntext\n# Experiments\ntext\n# Related Work\ntext\n", encoding="utf-8")
        write_jsonl(
            jsonl,
            [
                {"kind": "section", "section_id": "method", "text": "Method"},
                {"kind": "paragraph", "section_id": "method", "text": "m", "sentences": [{"text": "m"}]},
                {"kind": "section", "section_id": "experiments", "text": "Experiments"},
                {"kind": "paragraph", "section_id": "experiments", "text": "e", "sentences": [{"text": "e"}]},
                {"kind": "section", "section_id": "related-work", "text": "Related Work"},
                {"kind": "paragraph", "section_id": "related-work", "text": "r", "sentences": [{"text": "r"}]},
            ],
        )
        manifest = module.build_manifest(bundle=bundle, review_units_md=md, review_units_jsonl=jsonl, max_tokens=10000)
        packet = json.loads(Path(manifest["packet_paths"][0]).read_text(encoding="utf-8"))
    rule_ids = [item["id"] for item in packet["rule_refs"]]
    for expected in ("method_rules", "experiment_rules", "related_work_rules"):
        if expected not in rule_ids:
            raise AssertionError(f"Expected {expected} in section-specific shard rules: {rule_ids}")


if __name__ == "__main__":
    test_build_prose_shards_writes_manifest_and_packets()
    test_build_prose_shards_adds_section_specific_rule_refs()
    print("build_prose_shards regression tests passed")
