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
import hashlib
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_language_contract import CHINESE_OUTPUT_INSTRUCTIONS  # noqa: E402


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def resolve_rule_refs(packet: dict[str, Any]) -> list[dict[str, str]]:
    refs = packet.get("rule_refs")
    if refs is None:
        return []
    if not isinstance(refs, list):
        raise ValueError("packet rule_refs must be a list")
    resolved: list[dict[str, str]] = []
    for index, ref in enumerate(refs, 1):
        if not isinstance(ref, dict):
            raise ValueError(f"packet rule_refs[{index}] must be an object")
        raw_path = ref.get("path")
        if not raw_path:
            raise ValueError(f"packet rule_refs[{index}] is missing path")
        path = Path(str(raw_path)).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"packet rule_refs[{index}] does not exist: {path}")
        expected_hash = str(ref.get("hash") or "")
        actual_hash = sha256_path(path)
        if expected_hash and expected_hash != actual_hash:
            raise ValueError(f"packet rule_refs[{index}] hash mismatch for {path}: expected {expected_hash}, got {actual_hash}")
        resolved.append(
            {
                "id": str(ref.get("id") or path.stem),
                "path": str(path),
                "hash": actual_hash,
                "purpose": str(ref.get("purpose") or ""),
                "content": path.read_text(encoding="utf-8"),
            }
        )
    return resolved


def rule_receipts(resolved_rules: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "id": rule["id"],
            "path": rule["path"],
            "hash": rule["hash"],
            "purpose": rule.get("purpose", ""),
        }
        for rule in resolved_rules
    ]


def render_rules(resolved_rules: list[dict[str, str]]) -> list[str]:
    if not resolved_rules:
        return []
    lines = [
        "## Resolved Rule References",
        "",
        "The following rule_refs are executable review rules for this packet. Apply them together with the packet contract.",
        "",
    ]
    for rule in resolved_rules:
        title = f"### {rule['id']}"
        if rule["purpose"]:
            title += f" -- {rule['purpose']}"
        lines.extend(
            [
                title,
                "",
                f"Source: `{rule['path']}`",
                f"Hash: `{rule['hash']}`",
                "",
                rule["content"].rstrip(),
                "",
            ]
        )
    return lines


def render_language_contract() -> list[str]:
    return [
        "## 可见批注语言合同",
        "",
        *[f"- {instruction}" for instruction in CHINESE_OUTPUT_INSTRUCTIONS],
        "",
    ]


def render_prompt(packet: dict[str, Any]) -> str:
    phase = packet.get("phase") or packet.get("domain") or "ariadne-agent"
    resolved_rules = resolve_rule_refs(packet)
    lines = [
        f"# Ariadne Agent Packet: {phase}",
        "",
        "你正在执行一个 Ariadne packet。只读取 packet 中列出的输入，只写入 packet 中列出的目标 artifact。",
        "如果 packet 包含 rule_refs，下方已解析的规则文本就是可执行指令的一部分。",
        "不要写 HTML。严格保持 JSON/JSONL 合同。",
        "",
        *render_language_contract(),
        *render_rules(resolved_rules),
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
    try:
        resolved_rules = resolve_rule_refs(packet)
        prompt_text = render_prompt(packet)
    except Exception as exc:
        parser.error(str(exc))
    write_text(prompt_path, prompt_text)
    cmd = command_parts(args.command)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "context_policy": "model_readable_agent_command_status_only",
        "generated_by": "scripts/run_agent_command.py",
        "packet": str(packet_path),
        "prompt_file": str(prompt_path),
        "prompt_hash": sha256_path(prompt_path),
        "resolved_rule_refs": rule_receipts(resolved_rules),
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
