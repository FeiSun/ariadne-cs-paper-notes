#!/usr/bin/env python3
"""Run optional LLM specialist refinement over curated issue artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
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


def compact_tail(value: str, *, max_chars: int = 1600) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def command_parts(agent_cmd: str) -> list[str]:
    parts = shlex.split(agent_cmd)
    if not parts:
        raise ValueError("--agent-cmd cannot be empty")
    return parts


def domain_from_path(path: Path) -> str:
    name = path.name
    if name.endswith("_issues.json"):
        return name[: -len("_issues.json")]
    if name.endswith("_issues.jsonl"):
        return name[: -len("_issues.jsonl")]
    return path.stem


def issue_paths(issues_dir: Path, domains: list[str] | None) -> list[Path]:
    paths = sorted(issues_dir.glob("*_issues.json"))
    if domains:
        wanted = set(domains)
        paths = [path for path in paths if domain_from_path(path) in wanted]
    return paths


def audit_one(path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, script("audit_review_artifacts.py"), "--issue-artifacts", str(path.parent)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, compact_tail(result.stdout)
    return False, compact_tail(result.stderr or result.stdout)


def run_specialist(
    *,
    source_path: Path,
    out_path: Path,
    agent_cmd: str,
    dry_run: bool,
    timeout: int,
) -> dict[str, Any]:
    domain = domain_from_path(source_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    packet = {
        "schema_version": 1,
        "context_policy": "model_readable_specialist_packet",
        "generated_by": "scripts/run_specialist_agent.py",
        "domain": domain,
        "read_inputs": [
            {
                "path": str(source_path),
                "context_policy": "model_readable_issue_only",
            }
        ],
        "write_target": {
            "path": str(out_path),
            "mode": "create_or_replace_issue_artifact",
            "required": True,
        },
        "instructions": [
            "Read only the curated issue artifact for this specialist domain.",
            "Do not read raw *_audit.json unless the packet is explicitly extended by a future workflow.",
            "Write a valid ariadne_issue_artifact JSON file with the same domain and context_policy.",
            "Preserve evidence_refs/source issue provenance when revising or grouping issues.",
            "For every sentence- or paragraph-anchored issue, include evidence_snippet: a verbatim 3-15 word quote from the anchored review unit.",
        ],
    }
    packet_path = out_path.with_suffix(".packet.json")
    write_json(packet_path, packet)
    cmd = command_parts(agent_cmd)
    if dry_run:
        shutil.copy2(source_path, out_path)
        return {
            "domain": domain,
            "status": "dry_run",
            "source": str(source_path),
            "output": str(out_path),
            "packet": str(packet_path),
            "command": cmd,
        }
    env = os.environ.copy()
    env.update(
        {
            "ARIADNE_SPECIALIST_PACKET": str(packet_path),
            "ARIADNE_SPECIALIST_DOMAIN": domain,
            "ARIADNE_SPECIALIST_INPUT": str(source_path),
            "ARIADNE_SPECIALIST_OUTPUT": str(out_path),
        }
    )
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=timeout, env=env)
    status = "completed" if result.returncode == 0 and out_path.exists() else "error"
    return {
        "domain": domain,
        "status": status,
        "source": str(source_path),
        "output": str(out_path),
        "packet": str(packet_path),
        "command": cmd,
        "returncode": result.returncode,
        "stdout_tail": compact_tail(result.stdout),
        "stderr_tail": compact_tail(result.stderr),
    }


def parse_domains(value: str) -> list[str] | None:
    if not value or value.strip().lower() == "all":
        return None
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues-dir", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, help="Default: sibling issue_artifacts_llm")
    parser.add_argument("--agent-cmd", required=True)
    parser.add_argument("--domains", default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agent-timeout", type=int, default=900)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--audit", action="store_true", help="Audit the output issue directory after refinement")
    args = parser.parse_args(argv)

    issues_dir = args.issues_dir.expanduser().resolve()
    if not issues_dir.is_dir():
        parser.error(f"issues dir does not exist: {issues_dir}")
    out_dir = args.out_dir.expanduser().resolve() if args.out_dir else issues_dir.parent / "issue_artifacts_llm"
    domains = parse_domains(args.domains)
    results = [
        run_specialist(
            source_path=path,
            out_path=out_dir / path.name,
            agent_cmd=args.agent_cmd,
            dry_run=args.dry_run,
            timeout=args.agent_timeout,
        )
        for path in issue_paths(issues_dir, domains)
    ]
    audit_result: dict[str, Any] | None = None
    if args.audit:
        ok, output = audit_one(out_dir)
        audit_result = {"status": "passed" if ok else "failed", "output_tail": output}
    summary = {
        "schema_version": 1,
        "context_policy": "model_readable_specialist_runner_status_only",
        "generated_by": "scripts/run_specialist_agent.py",
        "issues_dir": str(issues_dir),
        "out_dir": str(out_dir),
        "dry_run": args.dry_run,
        "domains_requested": domains or "all",
        "results": results,
        "audit": audit_result,
    }
    out = args.summary_out or out_dir / "specialist_agent_summary.json"
    write_json(out, summary)
    print(
        "Specialist agent runner: "
        + ", ".join(f"{item['domain']}={item['status']}" for item in results)
    )
    print(f"Summary: {out}")
    if any(item["status"] == "error" for item in results):
        return 1
    if audit_result and audit_result["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
