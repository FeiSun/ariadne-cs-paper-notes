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


def compact_tail(value: str, *, max_chars: int = 2000) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def command_parts(agent_cmd: str) -> list[str]:
    parts = shlex.split(agent_cmd)
    if not parts:
        raise ValueError("--agent-cmd cannot be empty")
    return parts


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


@dataclass
class AgentCall:
    phase: str
    status: str
    packet: str
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
    env = {
        "ARIADNE_PROSE_PHASE": phase,
        "ARIADNE_PROMPT_PACKET": str(packet_path),
        "ARIADNE_BUNDLE": str(bundle),
        "ARIADNE_ISSUE_ARTIFACTS": str(bundle / "issue_artifacts"),
    }
    if dry_run:
        return AgentCall(
            phase=phase,
            status="dry_run",
            packet=str(packet_path),
            command=cmd,
            before_rows=before,
            after_rows=before,
            message="agent command not executed",
        )
    result = run_command(cmd, env=env, timeout=timeout)
    after_packet = read_json(packet_path)
    after = target_counts(after_packet if isinstance(after_packet, dict) else packet)
    return AgentCall(
        phase=phase,
        status="completed" if result.returncode == 0 else "error",
        packet=str(packet_path),
        command=cmd,
        returncode=result.returncode,
        stdout_tail=compact_tail(result.stdout),
        stderr_tail=compact_tail(result.stderr),
        before_rows=before,
        after_rows=after,
    )


def phase_a_complete(status_payload: dict[str, Any]) -> bool:
    coverage = status_payload.get("coverage") if isinstance(status_payload, dict) else {}
    return isinstance(coverage, dict) and int(coverage.get("sections_pending", 0) or 0) == 0


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
    parser.add_argument("--agent-cmd", required=True, help="External agent command. It receives ARIADNE_PROMPT_PACKET env var.")
    parser.add_argument("--review-units-md", type=Path, help="Phase A review_units Markdown path")
    parser.add_argument("--review-units-jsonl", type=Path, help="Phase A review_units JSONL path")
    parser.add_argument("--phase-b-context", type=Path, help="Existing phase_b_context.json")
    parser.add_argument("--shard-manifest", type=Path, help="Optional phase_a_shard_manifest.json for sharded Phase A execution")
    parser.add_argument("--max-iterations", type=int, default=200, help="Max Phase A section iterations")
    parser.add_argument("--agent-timeout", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true", help="Build packets and summary without invoking --agent-cmd")
    parser.add_argument("--allow-incomplete", action="store_true", help="Return success even when prose phases remain pending")
    parser.add_argument("--summary-out", type=Path, help="Default: <bundle>/prose_agent_summary.json")
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
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"Summary: {out}", file=sys.stderr)
        return 1
    out = args.summary_out or args.bundle / "prose_agent_summary.json"
    summary = build_summary(args, calls, phase_a_done=phase_a_done, phase_b_done=phase_b_done)
    write_json(out, summary)
    print(
        "Prose agent runner: "
        f"phase_a={'complete' if phase_a_done else 'pending'}, "
        f"phase_b={'complete' if phase_b_done else 'pending'}, "
        f"calls={len(calls)}"
    )
    print(f"Summary: {out}")
    print(f"Next action: {summary['next_action']}")
    complete = phase_a_done and (args.phase == "phase_a" or phase_b_done or args.phase != "all")
    return 0 if complete or args.allow_incomplete else 1


if __name__ == "__main__":
    raise SystemExit(main())
