#!/usr/bin/env python3
"""Run Ariadne Prose Phase A/B through a pluggable external agent command.

The deterministic pipeline prepares prompt packets and validates artifacts.
This runner supplies the missing orchestration loop without hard-coding a
specific LLM provider. The external command receives environment variables
pointing at the packet and write targets, and is responsible for writing the
JSON/JSONL artifacts named in the packet.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def script(name: str) -> str:
    return str(SCRIPT_DIR / name)


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def text_stats(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {"bytes": 0, "estimated_tokens": 0}
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    return {"bytes": len(data), "estimated_tokens": estimate_tokens(text)}


def compact_tail(value: str, *, max_chars: int = 2000) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def command_parts(agent_cmd: str) -> list[str]:
    parts = shlex.split(agent_cmd)
    if not parts:
        raise ValueError("--agent-cmd cannot be empty")
    return parts


def load_agent_command_module() -> Any:
    path = SCRIPT_DIR / "run_agent_command.py"
    spec = importlib.util.spec_from_file_location("ariadne_run_agent_command", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load prompt renderer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rule_receipts(packet: dict[str, Any]) -> list[dict[str, str]]:
    renderer = load_agent_command_module()
    resolved = renderer.resolve_rule_refs(packet)
    if hasattr(renderer, "rule_receipts"):
        return renderer.rule_receipts(resolved)
    return [
        {
            "id": rule["id"],
            "path": rule["path"],
            "hash": rule["hash"],
            **text_stats(Path(rule["path"])),
            "purpose": rule.get("purpose", ""),
        }
        for rule in resolved
    ]


def build_prompt_file(packet_path: Path) -> Path:
    packet = read_json(packet_path)
    if not isinstance(packet, dict):
        raise RuntimeError(f"packet is not valid JSON object: {packet_path}")
    renderer = load_agent_command_module()
    prompt_path = packet_path.with_suffix(packet_path.suffix + ".prompt.md")
    write_text(prompt_path, renderer.render_prompt(packet))
    return prompt_path


def packet_target(packet: dict[str, Any], key: str) -> Path | None:
    targets = packet.get("write_targets") if isinstance(packet, dict) else None
    if not isinstance(targets, dict):
        return None
    record = targets.get(key)
    if not isinstance(record, dict) or not record.get("path"):
        return None
    return Path(str(record["path"]))


def count_jsonl(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def count_json_target(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    if path.suffix == ".jsonl":
        return count_jsonl(path)
    try:
        payload = read_json(path)
    except Exception:
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("sections", "section_reflections", "claim_candidates", "claims", "findings"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        return len(payload) if payload else 0
    return 1 if payload else 0


def path_receipt(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": "", "exists": False}
    receipt: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists() and path.is_file():
        receipt["hash"] = sha256_path(path)
        receipt.update(text_stats(path))
        receipt["rows"] = count_json_target(path)
    return receipt


def input_receipts(packet: dict[str, Any]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    inputs = packet.get("read_inputs")
    if not isinstance(inputs, list):
        return receipts
    for item in inputs:
        if not isinstance(item, dict):
            continue
        path_text = str(item.get("path") or "")
        receipt = path_receipt(Path(path_text) if path_text else None)
        if item.get("hash"):
            receipt["declared_hash"] = str(item.get("hash"))
        if item.get("context_policy"):
            receipt["context_policy"] = str(item.get("context_policy"))
        receipts.append(receipt)
    return receipts


def output_receipts(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    targets = packet.get("write_targets") if isinstance(packet, dict) else None
    if not isinstance(targets, dict):
        return receipts
    for key in targets:
        receipts[key] = path_receipt(packet_target(packet, key))
    return receipts


def context_receipt(packet_path: Path, prompt_path: Path, packet: dict[str, Any], rules: list[dict[str, Any]], inputs: list[dict[str, Any]]) -> dict[str, Any]:
    rule_tokens = sum(int(item.get("estimated_tokens") or 0) for item in rules)
    input_tokens = sum(int(item.get("estimated_tokens") or 0) for item in inputs)
    packet_stats = text_stats(packet_path)
    prompt_stats = text_stats(prompt_path)
    shard_count = 0
    if packet.get("phase") == "phase_a":
        shard = packet.get("shard") if isinstance(packet.get("shard"), dict) else None
        shard_count = 1 if shard else 0
    return {
        "packet_bytes": packet_stats["bytes"],
        "packet_estimated_tokens": packet_stats["estimated_tokens"],
        "prompt_bytes": prompt_stats["bytes"],
        "prompt_estimated_tokens": prompt_stats["estimated_tokens"],
        "rule_bytes": sum(int(item.get("bytes") or 0) for item in rules),
        "rule_estimated_tokens": rule_tokens,
        "input_bytes": sum(int(item.get("bytes") or 0) for item in inputs),
        "input_estimated_tokens": input_tokens,
        "read_input_count": len(inputs),
        "shard_count": shard_count,
        "orchestrator_read_full_review_units": False,
    }


@dataclass
class AgentCall:
    phase: str
    status: str
    packet: str
    packet_hash: str = ""
    prompt_file: str = ""
    prompt_hash: str = ""
    resolved_rule_refs: list[dict[str, str]] = field(default_factory=list)
    read_inputs: list[dict[str, Any]] = field(default_factory=list)
    output_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    context_receipt: dict[str, Any] = field(default_factory=dict)
    command: list[str] = field(default_factory=list)
    returncode: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    before_rows: dict[str, int] = field(default_factory=dict)
    after_rows: dict[str, int] = field(default_factory=dict)
    message: str = ""

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "phase": self.phase,
            "status": self.status,
            "packet": self.packet,
        }
        if self.prompt_file:
            payload["prompt_file"] = self.prompt_file
        if self.packet_hash:
            payload["packet_hash"] = self.packet_hash
        if self.prompt_hash:
            payload["prompt_hash"] = self.prompt_hash
        if self.resolved_rule_refs:
            payload["resolved_rule_refs"] = self.resolved_rule_refs
        if self.read_inputs:
            payload["read_inputs"] = self.read_inputs
        if self.output_artifacts:
            payload["output_artifacts"] = self.output_artifacts
        if self.context_receipt:
            payload["context_receipt"] = self.context_receipt
        if self.command:
            payload["command"] = self.command
        if self.returncode is not None:
            payload["returncode"] = self.returncode
        if self.stdout_tail:
            payload["stdout_tail"] = self.stdout_tail
        if self.stderr_tail:
            payload["stderr_tail"] = self.stderr_tail
        if self.before_rows:
            payload["before_rows"] = self.before_rows
        if self.after_rows:
            payload["after_rows"] = self.after_rows
        if self.message:
            payload["message"] = self.message
        return payload


def run_command(cmd: list[str], *, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
        env=merged_env,
    )


def build_phase_a_status(bundle: Path, review_units_jsonl: Path) -> dict[str, Any]:
    status = bundle / "phase_a_resume_status.json"
    next_step = bundle / "phase_a_next_step.json"
    cmd = [
        sys.executable,
        script("phase_a_resume_status.py"),
        "--review-units",
        str(review_units_jsonl),
        "--prose-issues",
        str(bundle / "issue_artifacts" / "prose_issues.jsonl"),
        "--paragraph-decisions",
        str(bundle / "paragraph_decisions.jsonl"),
        "--section-reflections",
        str(bundle / "section_reflections.json"),
        "--cold-skim",
        str(bundle / "cold_skim_frame.json"),
        "--claim-candidates",
        str(bundle / "claim_candidates.json"),
        "--out",
        str(status),
        "--next-out",
        str(next_step),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"phase_a_resume_status failed: {result.stderr or result.stdout}")
    payload = read_json(status)
    return payload if isinstance(payload, dict) else {}


def build_phase_a_packet(bundle: Path, review_units_md: Path, review_units_jsonl: Path) -> Path:
    packet = bundle / "phase_a_prompt_packet.json"
    cmd = [
        sys.executable,
        script("build_prose_phase_packet.py"),
        "--phase",
        "phase_a",
        "--bundle",
        str(bundle),
        "--review-units-md",
        str(review_units_md),
        "--review-units-jsonl",
        str(review_units_jsonl),
        "--out",
        str(packet),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"build phase_a packet failed: {result.stderr or result.stdout}")
    return packet


def build_phase_b_context(bundle: Path) -> Path:
    context = bundle / "phase_b_context.json"
    cmd = [
        sys.executable,
        script("build_phase_b_input.py"),
        "--cold-skim",
        str(bundle / "cold_skim_frame.json"),
        "--section-reflections",
        str(bundle / "section_reflections.json"),
        "--claim-candidates",
        str(bundle / "claim_candidates.json"),
        "--issues-dir",
        str(bundle / "issue_artifacts"),
        "--out",
        str(context),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"build_phase_b_input failed: {result.stderr or result.stdout}")
    return context


def build_phase_b_packet(bundle: Path, phase_b_context: Path) -> Path:
    packet = bundle / "phase_b_prompt_packet.json"
    cmd = [
        sys.executable,
        script("build_prose_phase_packet.py"),
        "--phase",
        "phase_b",
        "--bundle",
        str(bundle),
        "--phase-b-context",
        str(phase_b_context),
        "--out",
        str(packet),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"build phase_b packet failed: {result.stderr or result.stdout}")
    return packet


def target_counts(packet: dict[str, Any]) -> dict[str, int]:
    rows: dict[str, int] = {}
    targets = packet.get("write_targets") if isinstance(packet, dict) else None
    if not isinstance(targets, dict):
        return rows
    for key in targets:
        path = packet_target(packet, key)
        if path is not None:
            rows[key] = count_json_target(path)
    return rows


def status_counts(status_payload: dict[str, Any]) -> dict[str, int]:
    coverage = status_payload.get("coverage") if isinstance(status_payload, dict) else {}
    if not isinstance(coverage, dict):
        return {}
    return {
        "sections_completed": int(coverage.get("sections_completed", 0) or 0),
        "sections_pending": int(coverage.get("sections_pending", 0) or 0),
        "sections_partial": int(coverage.get("sections_partial", 0) or 0),
        "sentences_reviewed": int(coverage.get("sentences_reviewed", 0) or 0),
        "paragraphs_reviewed": int(coverage.get("paragraphs_reviewed", 0) or 0),
    }


def completed_section_ids(status_payload: dict[str, Any]) -> set[str]:
    completed = status_payload.get("completed_sections") if isinstance(status_payload, dict) else []
    if not isinstance(completed, list):
        return set()
    return {str(row.get("section_id")) for row in completed if isinstance(row, dict) and row.get("section_id")}


def made_progress(before_status: dict[str, Any], after_status: dict[str, Any], call: AgentCall) -> bool:
    before = status_counts(before_status)
    after = status_counts(after_status)
    if after.get("sections_completed", 0) > before.get("sections_completed", 0):
        return True
    if after.get("sections_pending", 0) < before.get("sections_pending", 0):
        return True
    for key, after_count in call.after_rows.items():
        if after_count > call.before_rows.get(key, 0):
            return True
    return False


def call_agent(
    *,
    phase: str,
    packet_path: Path,
    agent_cmd: str,
    bundle: Path,
    dry_run: bool,
    timeout: int,
) -> AgentCall:
    packet = read_json(packet_path)
    if not isinstance(packet, dict):
        raise RuntimeError(f"packet is not valid JSON object: {packet_path}")
    before = target_counts(packet)
    cmd = command_parts(agent_cmd)
    prompt_path = build_prompt_file(packet_path)
    rules = rule_receipts(packet)
    inputs = input_receipts(packet)
    context = context_receipt(packet_path, prompt_path, packet, rules, inputs)
    env = {
        "ARIADNE_PROSE_PHASE": phase,
        "ARIADNE_PROMPT_PACKET": str(packet_path),
        "ARIADNE_PROMPT_FILE": str(prompt_path),
        "ARIADNE_BUNDLE": str(bundle),
        "ARIADNE_ISSUE_ARTIFACTS": str(bundle / "issue_artifacts"),
    }
    if dry_run:
        return AgentCall(
            phase=phase,
            status="dry_run",
            packet=str(packet_path),
            packet_hash=sha256_path(packet_path),
            prompt_file=str(prompt_path),
            prompt_hash=sha256_path(prompt_path),
            resolved_rule_refs=rules,
            read_inputs=inputs,
            output_artifacts=output_receipts(packet),
            context_receipt=context,
            command=cmd,
            before_rows=before,
            after_rows=before,
            message="agent command not executed; prompt file rendered with resolved rule_refs",
        )
    result = run_command(cmd, env=env, timeout=timeout)
    after_packet = read_json(packet_path)
    after = target_counts(after_packet if isinstance(after_packet, dict) else packet)
    return AgentCall(
        phase=phase,
        status="completed" if result.returncode == 0 else "error",
        packet=str(packet_path),
        packet_hash=sha256_path(packet_path),
        prompt_file=str(prompt_path),
        prompt_hash=sha256_path(prompt_path),
        resolved_rule_refs=rules,
        read_inputs=inputs,
        output_artifacts=output_receipts(after_packet if isinstance(after_packet, dict) else packet),
        context_receipt=context,
        command=cmd,
        returncode=result.returncode,
        stdout_tail=compact_tail(result.stdout),
        stderr_tail=compact_tail(result.stderr),
        before_rows=before,
        after_rows=after,
    )


def phase_a_complete(status_payload: dict[str, Any]) -> bool:
    coverage = status_payload.get("coverage") if isinstance(status_payload, dict) else {}
    return isinstance(coverage, dict) and bool(coverage.get("phase_a_complete"))


def run_phase_a(args: argparse.Namespace, calls: list[AgentCall]) -> bool:
    if not args.review_units_md or not args.review_units_jsonl:
        raise ValueError("--review-units-md and --review-units-jsonl are required for Phase A")
    review_units_md = args.review_units_md.expanduser().resolve()
    review_units_jsonl = args.review_units_jsonl.expanduser().resolve()
    shard_manifest = resolve_shard_manifest(args)
    if shard_manifest is not None:
        return run_phase_a_shards(args, calls, review_units_jsonl=review_units_jsonl, shard_manifest=shard_manifest)
    for _iteration in range(args.max_iterations):
        status = build_phase_a_status(args.bundle, review_units_jsonl)
        packet_path = build_phase_a_packet(args.bundle, review_units_md, review_units_jsonl)
        if phase_a_complete(status):
            return True
        call = call_agent(
            phase="phase_a",
            packet_path=packet_path,
            agent_cmd=args.agent_cmd,
            bundle=args.bundle,
            dry_run=args.dry_run,
            timeout=args.agent_timeout,
        )
        calls.append(call)
        if call.status != "completed":
            return False
        refreshed = build_phase_a_status(args.bundle, review_units_jsonl)
        if not made_progress(status, refreshed, call):
            call.status = "no_progress"
            call.message = "agent command exited successfully but did not advance Phase A resume status or write targets"
            return False
        if phase_a_complete(refreshed):
            return True
    return False


def resolve_shard_manifest(args: argparse.Namespace) -> Path | None:
    explicit = getattr(args, "shard_manifest", None)
    if explicit:
        path = explicit.expanduser().resolve()
        return path if path.exists() else None
    return None


def load_shard_manifest(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"shard manifest is not a JSON object: {path}")
    if payload.get("context_policy") != "model_readable_shard_manifest_only":
        raise RuntimeError(f"unexpected shard manifest context policy: {payload.get('context_policy')}")
    return payload


def next_incomplete_shard(manifest: dict[str, Any], status_payload: dict[str, Any]) -> tuple[dict[str, Any], Path] | None:
    completed = completed_section_ids(status_payload)
    shards = manifest.get("shards")
    packet_paths = manifest.get("packet_paths")
    if not isinstance(shards, list) or not isinstance(packet_paths, list):
        raise RuntimeError("shard manifest must contain shards[] and packet_paths[]")
    for idx, shard in enumerate(shards):
        if not isinstance(shard, dict):
            continue
        section_ids = [str(item) for item in shard.get("section_ids", [])]
        if section_ids and all(section_id in completed for section_id in section_ids):
            continue
        packet_path = Path(str(packet_paths[idx])) if idx < len(packet_paths) else Path("")
        if not packet_path.exists():
            raise RuntimeError(f"missing shard packet for {shard.get('shard_id')}: {packet_path}")
        return shard, packet_path
    return None


def run_phase_a_shards(
    args: argparse.Namespace,
    calls: list[AgentCall],
    *,
    review_units_jsonl: Path,
    shard_manifest: Path,
) -> bool:
    manifest = load_shard_manifest(shard_manifest)
    iterations = 0
    while iterations < args.max_iterations:
        status = build_phase_a_status(args.bundle, review_units_jsonl)
        if phase_a_complete(status):
            return True
        next_shard = next_incomplete_shard(manifest, status)
        if next_shard is None:
            return phase_a_complete(status)
        shard, packet_path = next_shard
        call = call_agent(
            phase="phase_a_shard",
            packet_path=packet_path,
            agent_cmd=args.agent_cmd,
            bundle=args.bundle,
            dry_run=args.dry_run,
            timeout=args.agent_timeout,
        )
        call.message = f"shard_id={shard.get('shard_id')}; sections={','.join(str(item) for item in shard.get('section_ids', []))}"
        calls.append(call)
        iterations += 1
        if call.status != "completed":
            return False
        refreshed = build_phase_a_status(args.bundle, review_units_jsonl)
        if not made_progress(status, refreshed, call):
            call.status = "no_progress"
            call.message += "; agent command exited successfully but did not advance shard coverage"
            return False
        if phase_a_complete(refreshed):
            return True
    return False


def phase_b_outputs_present(bundle: Path) -> bool:
    return all(
        path.exists()
        for path in (
            bundle / "argument_map.json",
            bundle / "claims.json",
            bundle / "salvageable_core.json",
            bundle / "issue_artifacts" / "whole_paper_findings.jsonl",
        )
    )


def run_phase_b(args: argparse.Namespace, calls: list[AgentCall]) -> bool:
    if phase_b_outputs_present(args.bundle):
        return True
    context = args.phase_b_context.expanduser().resolve() if args.phase_b_context else build_phase_b_context(args.bundle)
    packet_path = build_phase_b_packet(args.bundle, context)
    call = call_agent(
        phase="phase_b",
        packet_path=packet_path,
        agent_cmd=args.agent_cmd,
        bundle=args.bundle,
        dry_run=args.dry_run,
        timeout=args.agent_timeout,
    )
    calls.append(call)
    return call.status == "completed" and (args.dry_run or phase_b_outputs_present(args.bundle))


def build_summary(args: argparse.Namespace, calls: list[AgentCall], *, phase_a_done: bool, phase_b_done: bool) -> dict[str, Any]:
    resume_payload = read_json(args.bundle / "phase_a_resume_status.json")
    resume_coverage = resume_payload.get("coverage") if isinstance(resume_payload, dict) and isinstance(resume_payload.get("coverage"), dict) else {}
    return {
        "schema_version": 1,
        "context_policy": "model_readable_prose_runner_status_only",
        "generated_by": "scripts/run_prose_agent.py",
        "bundle": str(args.bundle),
        "phase": args.phase,
        "shard_manifest": str(args.shard_manifest) if getattr(args, "shard_manifest", None) else "",
        "dry_run": args.dry_run,
        "phase_a_complete": phase_a_done,
        "phase_b_complete": phase_b_done,
        "phase_a_resume_coverage": resume_coverage,
        "phase_a_completed_section_ids": sorted(completed_section_ids(resume_payload if isinstance(resume_payload, dict) else {})),
        "calls": [call.to_json() for call in calls],
        "next_action": next_action(args, phase_a_done=phase_a_done, phase_b_done=phase_b_done),
    }


def build_agent_provenance(args: argparse.Namespace, summary: dict[str, Any]) -> dict[str, Any]:
    calls = summary.get("calls") if isinstance(summary.get("calls"), list) else []
    return {
        "schema_version": 1,
        "context_policy": "model_readable_agent_provenance_only",
        "generated_by": "scripts/run_prose_agent.py",
        "bundle": str(args.bundle),
        "single_agent": False,
        "mode": "dry_run" if args.dry_run else "external_agent",
        "agents": [
            {
                "kind": "prose",
                "phase": args.phase,
                "command": command_parts(args.agent_cmd),
                "dry_run": args.dry_run,
                "summary": str(args.summary_out or args.bundle / "prose_agent_summary.json"),
                "phase_a_complete": summary.get("phase_a_complete", False),
                "phase_b_complete": summary.get("phase_b_complete", False),
                "calls": calls,
            }
        ],
    }


def next_action(args: argparse.Namespace, *, phase_a_done: bool, phase_b_done: bool) -> str:
    if args.dry_run:
        return "Dry run only; inspect packets and run again without --dry-run to invoke the agent command."
    if not phase_a_done and args.phase in {"phase_a", "all"}:
        return f"Continue Phase A with `{args.bundle / 'phase_a_prompt_packet.json'}`."
    if phase_a_done and not phase_b_done and args.phase in {"phase_b", "all"}:
        return f"Run or continue Phase B with `{args.bundle / 'phase_b_prompt_packet.json'}`."
    return "Prose phases complete; run run_review_pipeline.py again to compile/render/audit."


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path, help="Ariadne artifact bundle")
    parser.add_argument("--phase", default="all", choices=("phase_a", "phase_b", "all"))
    parser.add_argument("--agent-cmd", required=True, help="External agent command. It receives ARIADNE_PROMPT_FILE with resolved rule text plus ARIADNE_PROMPT_PACKET for structured metadata.")
    parser.add_argument("--review-units-md", type=Path, help="Phase A review_units Markdown path")
    parser.add_argument("--review-units-jsonl", type=Path, help="Phase A review_units JSONL path")
    parser.add_argument("--phase-b-context", type=Path, help="Existing phase_b_context.json")
    parser.add_argument("--shard-manifest", type=Path, help="Optional phase_a_shard_manifest.json for sharded Phase A execution")
    parser.add_argument("--max-iterations", type=int, default=200, help="Max Phase A section iterations")
    parser.add_argument("--agent-timeout", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true", help="Build packets and summary without invoking --agent-cmd")
    parser.add_argument("--allow-incomplete", action="store_true", help="Return success even when prose phases remain pending")
    parser.add_argument("--summary-out", type=Path, help="Default: <bundle>/prose_agent_summary.json")
    parser.add_argument("--provenance-out", type=Path, help="Default: <bundle>/agent_provenance.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    args.bundle = args.bundle.expanduser().resolve()
    args.bundle.mkdir(parents=True, exist_ok=True)
    (args.bundle / "issue_artifacts").mkdir(parents=True, exist_ok=True)
    calls: list[AgentCall] = []
    phase_a_done = False
    phase_b_done = False
    try:
        if args.phase in {"phase_a", "all"}:
            phase_a_done = run_phase_a(args, calls)
        else:
            phase_a_done = True
        if args.phase in {"phase_b", "all"} and phase_a_done:
            phase_b_done = run_phase_b(args, calls)
        elif args.phase == "phase_a":
            phase_b_done = phase_b_outputs_present(args.bundle)
    except Exception as exc:
        summary = build_summary(args, calls, phase_a_done=phase_a_done, phase_b_done=phase_b_done)
        summary["error"] = str(exc)
        out = args.summary_out or args.bundle / "prose_agent_summary.json"
        write_json(out, summary)
        provenance_out = args.provenance_out or args.bundle / "agent_provenance.json"
        write_json(provenance_out, build_agent_provenance(args, summary))
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"Summary: {out}", file=sys.stderr)
        return 1
    out = args.summary_out or args.bundle / "prose_agent_summary.json"
    summary = build_summary(args, calls, phase_a_done=phase_a_done, phase_b_done=phase_b_done)
    write_json(out, summary)
    provenance_out = args.provenance_out or args.bundle / "agent_provenance.json"
    write_json(provenance_out, build_agent_provenance(args, summary))
    print(
        "Prose agent runner: "
        f"phase_a={'complete' if phase_a_done else 'pending'}, "
        f"phase_b={'complete' if phase_b_done else 'pending'}, "
        f"calls={len(calls)}"
    )
    print(f"Summary: {out}")
    print(f"Provenance: {provenance_out}")
    print(f"Next action: {summary['next_action']}")
    complete = phase_a_done and (args.phase == "phase_a" or phase_b_done or args.phase != "all")
    return 0 if complete or args.allow_incomplete else 1


if __name__ == "__main__":
    raise SystemExit(main())
