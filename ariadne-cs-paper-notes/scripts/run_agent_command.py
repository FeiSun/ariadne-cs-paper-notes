#!/usr/bin/env python3
"""Generic packet-to-command adapter for Ariadne external agents.

This helper turns an Ariadne prompt/specialist packet into a plain prompt file,
invokes an arbitrary command, and optionally writes stdout as JSON. It is meant
as a small provider-neutral bridge for local Codex/Claude/OpenAI CLI adapters.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_prompt(packet: dict[str, Any]) -> str:
    phase = packet.get("phase") or packet.get("domain") or "ariadne-agent"
    lines = [
        f"# Ariadne Agent Packet: {phase}",
        "",
        "You are executing an Ariadne packet. Read only the inputs named in the packet and write only the target artifacts named in the packet.",
        "Do not write HTML. Preserve JSON/JSONL contracts exactly.",
        "",
        "## Packet",
        "```json",
        compact_json(packet),
        "```",
        "",
    ]
    return "\n".join(lines)


def command_parts(command: str) -> list[str]:
    parts = shlex.split(command)
    if not parts:
        raise ValueError("--command cannot be empty")
    return parts


def parse_stdout_json(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--command", required=True, help="Command to run. It receives ARIADNE_PACKET and ARIADNE_PROMPT_FILE.")
    parser.add_argument("--prompt-out", type=Path, help="Default: <packet>.prompt.md")
    parser.add_argument("--stdout-json-out", type=Path, help="Parse stdout as JSON and write it here")
    parser.add_argument("--summary-out", type=Path, help="Default: <packet>.agent_command_summary.json")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    packet_path = args.packet.expanduser().resolve()
    packet = read_json(packet_path)
    if not isinstance(packet, dict):
        parser.error("--packet must be a JSON object")
    prompt_path = args.prompt_out.expanduser().resolve() if args.prompt_out else packet_path.with_suffix(packet_path.suffix + ".prompt.md")
    write_text(prompt_path, render_prompt(packet))
    cmd = command_parts(args.command)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "context_policy": "model_readable_agent_command_status_only",
        "generated_by": "scripts/run_agent_command.py",
        "packet": str(packet_path),
        "prompt_file": str(prompt_path),
        "command": cmd,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        summary["status"] = "dry_run"
        out = args.summary_out or packet_path.with_suffix(packet_path.suffix + ".agent_command_summary.json")
        write_text(out, compact_json(summary) + "\n")
        print(f"Agent command dry-run prompt: {prompt_path}")
        print(f"Summary: {out}")
        return 0
    env = os.environ.copy()
    env.update({"ARIADNE_PACKET": str(packet_path), "ARIADNE_PROMPT_FILE": str(prompt_path)})
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=args.timeout, env=env)
    summary.update(
        {
            "status": "completed" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
        }
    )
    if args.stdout_json_out and result.returncode == 0:
        try:
            parsed = parse_stdout_json(result.stdout)
            args.stdout_json_out.parent.mkdir(parents=True, exist_ok=True)
            args.stdout_json_out.write_text(compact_json(parsed) + "\n", encoding="utf-8")
            summary["stdout_json_out"] = str(args.stdout_json_out)
        except Exception as exc:
            summary["status"] = "error"
            summary["parse_error"] = str(exc)
    out = args.summary_out or packet_path.with_suffix(packet_path.suffix + ".agent_command_summary.json")
    write_text(out, compact_json(summary) + "\n")
    print(f"Agent command status: {summary['status']}")
    print(f"Summary: {out}")
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
