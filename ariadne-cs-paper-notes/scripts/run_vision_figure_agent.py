#!/usr/bin/env python3
"""Prepare page images for an optional vision figure/caption specialist."""

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
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_page_layout import parse_pages, pdf_page_count  # noqa: E402


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command_parts(command: str) -> list[str]:
    parts = shlex.split(command)
    if not parts:
        raise ValueError("--agent-cmd cannot be empty")
    return parts


def render_page(pdf: Path, page: int, out_dir: Path, pdftoppm: str, *, dpi: int) -> Path:
    prefix = out_dir / f"page-{page:03d}"
    result = subprocess.run(
        [pdftoppm, "-f", str(page), "-l", str(page), "-singlefile", "-png", "-r", str(dpi), str(pdf), str(prefix)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"pdftoppm exited with {result.returncode}")
    image = prefix.with_suffix(".png")
    if not image.exists():
        raise RuntimeError(f"pdftoppm did not write {image}")
    return image


def build_packet(*, pdf: Path, figure_issues: Path | None, image_manifest: Path, output: Path) -> dict[str, Any]:
    read_inputs: list[dict[str, Any]] = [
        {"path": str(image_manifest), "context_policy": "model_readable_image_manifest_only"},
    ]
    if figure_issues and figure_issues.exists():
        read_inputs.append({"path": str(figure_issues), "context_policy": "model_readable_issue_only"})
    return {
        "schema_version": 1,
        "context_policy": "model_readable_vision_specialist_packet",
        "generated_by": "scripts/run_vision_figure_agent.py",
        "domain": "figure_caption",
        "pdf": str(pdf),
        "read_inputs": read_inputs,
        "write_target": {
            "path": str(output),
            "mode": "create_or_replace_issue_artifact",
            "required": True,
        },
        "instructions": [
            "Inspect the page images named in image_manifest.json for figure/table semantic support, caption-image agreement, and visual readability.",
            "Write a valid ariadne_issue_artifact JSON with domain figure_caption and context_policy model_readable_issue_only.",
            "Do not copy page images or raw OCR text into the issue artifact; cite image_manifest page ids and concise visual evidence.",
        ],
    }


def run_agent(agent_cmd: str, *, packet: Path, manifest: Path, output: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "ARIADNE_VISION_PACKET": str(packet),
            "ARIADNE_IMAGE_MANIFEST": str(manifest),
            "ARIADNE_VISION_OUTPUT": str(output),
        }
    )
    return subprocess.run(command_parts(agent_cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=timeout, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="Vision figure/caption issue artifact output")
    parser.add_argument("--agent-cmd", required=True)
    parser.add_argument("--pages", default="all")
    parser.add_argument("--figure-issues", type=Path, help="Optional existing figure_caption_issues.json")
    parser.add_argument("--image-dir", type=Path, help="Default: <out parent>/vision_pages")
    parser.add_argument("--pdftoppm", help="Path to pdftoppm")
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agent-timeout", type=int, default=1200)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args(argv)

    pdf = args.pdf.expanduser().resolve()
    if not pdf.exists():
        parser.error(f"PDF does not exist: {pdf}")
    pdftoppm = args.pdftoppm or shutil.which("pdftoppm")
    if not pdftoppm:
        parser.error("pdftoppm is required to render page images")
    out = args.out.expanduser().resolve()
    image_dir = args.image_dir.expanduser().resolve() if args.image_dir else out.parent / "vision_pages"
    image_dir.mkdir(parents=True, exist_ok=True)
    total_pages = pdf_page_count(pdf)
    pages = parse_pages(args.pages, total_pages)
    images = []
    for page in pages:
        image = render_page(pdf, page, image_dir, pdftoppm, dpi=args.dpi)
        images.append({"page": page, "image_path": str(image), "context_policy": "tool_only_page_image"})
    manifest = out.parent / "vision_image_manifest.json"
    write_json(
        manifest,
        {
            "schema_version": 1,
            "context_policy": "model_readable_image_manifest_only",
            "generated_by": "scripts/run_vision_figure_agent.py",
            "pdf": str(pdf),
            "pages_total": total_pages,
            "pages_requested": pages,
            "images": images,
        },
    )
    packet_path = out.with_suffix(".vision_packet.json")
    packet = build_packet(pdf=pdf, figure_issues=args.figure_issues, image_manifest=manifest, output=out)
    write_json(packet_path, packet)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "context_policy": "model_readable_vision_runner_status_only",
        "generated_by": "scripts/run_vision_figure_agent.py",
        "packet": str(packet_path),
        "image_manifest": str(manifest),
        "output": str(out),
        "pages_rendered": len(images),
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        summary["status"] = "dry_run"
    else:
        result = run_agent(args.agent_cmd, packet=packet_path, manifest=manifest, output=out, timeout=args.agent_timeout)
        summary.update(
            {
                "status": "completed" if result.returncode == 0 and out.exists() else "error",
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-2000:],
                "stderr_tail": result.stderr[-2000:],
            }
        )
    summary_out = args.summary_out or out.parent / "vision_figure_agent_summary.json"
    write_json(summary_out, summary)
    print(f"Vision figure agent status: {summary['status']}")
    print(f"Summary: {summary_out}")
    return 0 if summary["status"] in {"completed", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
