#!/usr/bin/env python3
"""Run deterministic P1 specialist reducers with input-aware gating."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


def run_command(cmd: list[str], *, cwd: Path | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def issue_status(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    coverage = payload.get("coverage") if isinstance(payload, dict) else {}
    return {
        "status": payload.get("status") if isinstance(payload, dict) else "unknown",
        "issues": coverage.get("issues") if isinstance(coverage, dict) else None,
        "checked": coverage.get("checked") if isinstance(coverage, dict) else None,
    }


def skipped_stub(domain: str, reason: str, checked: int = 0) -> dict[str, Any]:
    return {
        "artifact_type": "ariadne_issue_artifact",
        "schema_version": 1,
        "domain": domain,
        "context_policy": "model_readable_issue_only",
        "status": "skipped",
        "skip_reason": reason,
        "source_artifacts": [],
        "coverage": {"checked": checked, "issues": 0, "skipped": 1},
        "issues": [],
    }


def script(name: str) -> str:
    return str(SCRIPT_DIR / name)


def run_builder(domain: str, raw_audit: Path, out: Path) -> dict[str, Any]:
    cmd = [
        sys.executable,
        script("build_specialist_issues.py"),
        "--domain",
        domain,
        "--raw-audit",
        str(raw_audit),
        "--out",
        str(out),
    ]
    result = run_command(cmd)
    if result.returncode != 0:
        return {
            "domain": domain,
            "status": "error",
            "raw_audit": str(raw_audit),
            "issues": str(out),
            "error": (result.stderr or result.stdout).strip()[:1000],
            "command": cmd,
        }
    status = issue_status(out)
    return {
        "domain": domain,
        "status": status["status"],
        "raw_audit": str(raw_audit),
        "issues": str(out),
        "issue_count": status["issues"],
        "checked": status["checked"],
    }


def run_layout(pdf: Path | None, bundle: Path, issues_dir: Path, *, force: bool, pages: str) -> dict[str, Any]:
    out = issues_dir / "layout_issues.json"
    raw = bundle / "layout_audit.json"
    if raw.exists() and not force:
        return run_builder("layout", raw, out)
    if pdf is None:
        write_json(out, skipped_stub("layout", "no PDF provided for layout audit"))
        return {"domain": "layout", "status": "skipped", "issues": str(out), "skip_reason": "no PDF provided"}
    if not raw.exists() or force:
        if not shutil.which("pdftotext"):
            write_json(out, skipped_stub("layout", "pdftotext is unavailable"))
            return {"domain": "layout", "status": "skipped", "issues": str(out), "skip_reason": "pdftotext unavailable"}
        cmd = [
            sys.executable,
            script("check_page_layout.py"),
            str(pdf),
            "--pages",
            pages,
            "--out",
            str(raw),
        ]
        result = run_command(cmd, timeout=240)
        if result.returncode != 0:
            write_json(out, skipped_stub("layout", "layout raw audit failed"))
            return {
                "domain": "layout",
                "status": "error",
                "raw_audit": str(raw),
                "issues": str(out),
                "error": (result.stderr or result.stdout).strip()[:1000],
                "command": cmd,
            }
    return run_builder("layout", raw, out)


def run_numeric(pdf: Path | None, bundle: Path, issues_dir: Path, *, force: bool) -> dict[str, Any]:
    out = issues_dir / "numeric_issues.json"
    raw = bundle / "numeric_audit.json"
    if raw.exists() and not force:
        return run_builder("numeric", raw, out)
    if pdf is None:
        write_json(out, skipped_stub("numeric", "no PDF provided for numeric audit"))
        return {"domain": "numeric", "status": "skipped", "issues": str(out), "skip_reason": "no PDF provided"}
    if not raw.exists() or force:
        cmd = [
            sys.executable,
            script("extract_paper_text.py"),
            str(pdf),
            "--numeric-json",
            str(raw),
            "--force",
        ]
        result = run_command(cmd, timeout=240)
        if result.returncode != 0:
            write_json(out, skipped_stub("numeric", "numeric raw audit failed"))
            return {
                "domain": "numeric",
                "status": "error",
                "raw_audit": str(raw),
                "issues": str(out),
                "error": (result.stderr or result.stdout).strip()[:1000],
                "command": cmd,
            }
    return run_builder("numeric", raw, out)


def run_reference(tex: Path | None, bundle: Path, issues_dir: Path, *, force: bool, aux: Path | None, bbl: Path | None) -> dict[str, Any]:
    out = issues_dir / "reference_issues.json"
    raw = bundle / "references_audit.json"
    if raw.exists() and not force:
        return run_builder("reference", raw, out)
    if tex is None:
        write_json(out, skipped_stub("reference", "no TeX/BibTeX source provided for reference audit"))
        return {"domain": "reference", "status": "skipped", "issues": str(out), "skip_reason": "no TeX/BibTeX source provided"}
    if not raw.exists() or force:
        cmd = [sys.executable, script("check_references.py"), str(tex), "--out", str(raw)]
        if aux is not None:
            cmd.extend(["--aux", str(aux)])
        if bbl is not None:
            cmd.extend(["--bbl", str(bbl)])
        result = run_command(cmd, timeout=180)
        if result.returncode != 0:
            write_json(out, skipped_stub("reference", "reference raw audit failed"))
            return {
                "domain": "reference",
                "status": "error",
                "raw_audit": str(raw),
                "issues": str(out),
                "error": (result.stderr or result.stdout).strip()[:1000],
                "command": cmd,
            }
    return run_builder("reference", raw, out)


def run_source_hygiene(tex: Path | None, bundle: Path, issues_dir: Path, *, force: bool) -> dict[str, Any]:
    out = issues_dir / "source_hygiene_issues.json"
    raw = bundle / "source_hygiene_audit.json"
    if raw.exists() and not force:
        return run_builder("source_hygiene", raw, out)
    if tex is None:
        write_json(out, skipped_stub("source_hygiene", "no TeX source provided for source hygiene audit"))
        return {"domain": "source_hygiene", "status": "skipped", "issues": str(out), "skip_reason": "no TeX source provided"}
    if not raw.exists() or force:
        cmd = [sys.executable, script("check_source_hygiene.py"), str(tex), "--out", str(raw)]
        result = run_command(cmd, timeout=180)
        if result.returncode != 0:
            write_json(out, skipped_stub("source_hygiene", "source hygiene raw audit failed"))
            return {
                "domain": "source_hygiene",
                "status": "error",
                "raw_audit": str(raw),
                "issues": str(out),
                "error": (result.stderr or result.stdout).strip()[:1000],
                "command": cmd,
            }
    return run_builder("source_hygiene", raw, out)


def run_polish(tex: Path | None, bundle: Path, issues_dir: Path, *, force: bool) -> dict[str, Any]:
    out = issues_dir / "polish_issues.json"
    raw = bundle / "polish_audit.json"
    if raw.exists() and not force:
        return run_builder("polish", raw, out)
    if tex is None:
        write_json(out, skipped_stub("polish", "no TeX source provided for polish audit"))
        return {"domain": "polish", "status": "skipped", "issues": str(out), "skip_reason": "no TeX source provided"}
    if not raw.exists() or force:
        cmd = [sys.executable, script("check_polish.py"), str(tex), "--out", str(raw)]
        result = run_command(cmd, timeout=180)
        if result.returncode != 0:
            write_json(out, skipped_stub("polish", "polish raw audit failed"))
            return {
                "domain": "polish",
                "status": "error",
                "raw_audit": str(raw),
                "issues": str(out),
                "error": (result.stderr or result.stdout).strip()[:1000],
                "command": cmd,
            }
    return run_builder("polish", raw, out)


def run_symbol(tex: Path | None, bundle: Path, issues_dir: Path, *, force: bool) -> dict[str, Any]:
    out = issues_dir / "symbol_issues.json"
    raw = bundle / "symbol_audit.json"
    if raw.exists() and not force:
        return run_builder("symbol", raw, out)
    if tex is None:
        write_json(out, skipped_stub("symbol", "no TeX source provided for symbol audit"))
        return {"domain": "symbol", "status": "skipped", "issues": str(out), "skip_reason": "no TeX source provided"}
    if not raw.exists() or force:
        cmd = [sys.executable, script("check_symbol.py"), str(tex), "--out", str(raw)]
        result = run_command(cmd, timeout=180)
        if result.returncode != 0:
            write_json(out, skipped_stub("symbol", "symbol raw audit failed"))
            return {
                "domain": "symbol",
                "status": "error",
                "raw_audit": str(raw),
                "issues": str(out),
                "error": (result.stderr or result.stdout).strip()[:1000],
                "command": cmd,
            }
    return run_builder("symbol", raw, out)


def run_figure_caption(
    tex: Path | None,
    pdf: Path | None,
    bundle: Path,
    issues_dir: Path,
    *,
    force: bool,
    pages: str,
    pdftoppm: str | None = None,
) -> dict[str, Any]:
    out = issues_dir / "figure_caption_issues.json"
    raw = bundle / "figure_caption_audit.json"
    if raw.exists() and not force:
        return run_builder("figure_caption", raw, out)
    if tex is None:
        write_json(out, skipped_stub("figure_caption", "no TeX source provided for figure/caption audit"))
        return {"domain": "figure_caption", "status": "skipped", "issues": str(out), "skip_reason": "no TeX source provided"}
    if not raw.exists() or force:
        cmd = [sys.executable, script("check_figure_caption.py"), str(tex), "--out", str(raw)]
        if pdf is not None:
            cmd.extend(["--pdf", str(pdf), "--pages", pages])
        if pdftoppm:
            cmd.extend(["--pdftoppm", pdftoppm])
        result = run_command(cmd, timeout=180)
        if result.returncode != 0:
            write_json(out, skipped_stub("figure_caption", "figure/caption raw audit failed"))
            return {
                "domain": "figure_caption",
                "status": "error",
                "raw_audit": str(raw),
                "issues": str(out),
                "error": (result.stderr or result.stdout).strip()[:1000],
                "command": cmd,
            }
    return run_builder("figure_caption", raw, out)


def companion(path: Path | None, suffix: str, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    if path is None:
        return None
    candidate = path.with_suffix(suffix)
    return candidate if candidate.exists() else None


def default_pdf(tex: Path | None, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    if tex is None:
        return None
    candidate = tex.with_suffix(".pdf")
    return candidate if candidate.exists() else None


def run_specialists(
    *,
    bundle: Path,
    tex: Path | None,
    pdf: Path | None,
    aux: Path | None,
    bbl: Path | None,
    domains: list[str],
    force: bool,
    pages: str,
    pdftoppm: str | None = None,
) -> dict[str, Any]:
    issues_dir = bundle / "issue_artifacts"
    issues_dir.mkdir(parents=True, exist_ok=True)
    pdf = default_pdf(tex, pdf)
    aux = companion(tex, ".aux", aux)
    bbl = companion(tex, ".bbl", bbl)

    results: list[dict[str, Any]] = []
    if "layout" in domains:
        results.append(run_layout(pdf, bundle, issues_dir, force=force, pages=pages))
    if "numeric" in domains:
        results.append(run_numeric(pdf, bundle, issues_dir, force=force))
    if "reference" in domains:
        results.append(run_reference(tex, bundle, issues_dir, force=force, aux=aux, bbl=bbl))
    if "source_hygiene" in domains:
        results.append(run_source_hygiene(tex, bundle, issues_dir, force=force))
    if "polish" in domains:
        results.append(run_polish(tex, bundle, issues_dir, force=force))
    if "symbol" in domains:
        results.append(run_symbol(tex, bundle, issues_dir, force=force))
    if "figure_caption" in domains:
        results.append(run_figure_caption(tex, pdf, bundle, issues_dir, force=force, pages=pages, pdftoppm=pdftoppm))

    return {
        "schema_version": 1,
        "generated_by": "run_p1_specialists.py",
        "bundle": str(bundle),
        "inputs": {
            "tex": str(tex) if tex else "",
            "pdf": str(pdf) if pdf else "",
            "aux": str(aux) if aux else "",
            "bbl": str(bbl) if bbl else "",
        },
        "domains_requested": domains,
        "results": results,
    }


def parse_domains(value: str) -> list[str]:
    if value.strip().lower() == "all":
        return ["layout", "numeric", "reference", "source_hygiene", "polish", "symbol", "figure_caption"]
    domains = [item.strip().lower() for item in value.split(",") if item.strip()]
    valid = {"layout", "numeric", "reference", "source_hygiene", "polish", "symbol", "figure_caption"}
    invalid = [domain for domain in domains if domain not in valid]
    if invalid:
        raise ValueError(f"invalid domain(s): {invalid}")
    return domains


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path, help="Artifact bundle directory")
    parser.add_argument("--tex", type=Path, help="LaTeX entry file or .bib file for reference audit")
    parser.add_argument("--pdf", type=Path, help="Compiled PDF for layout/numeric audits")
    parser.add_argument("--aux", type=Path, help="Optional .aux file for reference cited-key coverage")
    parser.add_argument("--bbl", type=Path, help="Optional .bbl file for rendered-reference coverage")
    parser.add_argument(
        "--domains",
        default="all",
        help="Comma-separated domains: layout,numeric,reference,source_hygiene,polish,symbol,figure_caption or all",
    )
    parser.add_argument("--pages", default="all", help="Layout page range; default all")
    parser.add_argument("--pdftoppm", help="Path to pdftoppm for PDF figure asset previews")
    parser.add_argument("--force", action="store_true", help="Regenerate raw audits even if they already exist")
    parser.add_argument("--summary-out", type=Path, help="Write run summary JSON here; default <bundle>/p1_specialists_summary.json")
    args = parser.parse_args(argv)

    try:
        domains = parse_domains(args.domains)
    except ValueError as exc:
        parser.error(str(exc))
    bundle = args.bundle.resolve()
    bundle.mkdir(parents=True, exist_ok=True)
    summary = run_specialists(
        bundle=bundle,
        tex=args.tex.resolve() if args.tex else None,
        pdf=args.pdf.resolve() if args.pdf else None,
        aux=args.aux.resolve() if args.aux else None,
        bbl=args.bbl.resolve() if args.bbl else None,
        domains=domains,
        force=args.force,
        pages=args.pages,
        pdftoppm=args.pdftoppm,
    )
    summary_out = args.summary_out or bundle / "p1_specialists_summary.json"
    write_json(summary_out, summary)
    errors = [item for item in summary["results"] if item.get("status") == "error"]
    print(
        "Deterministic specialists: "
        + ", ".join(
            f"{item['domain']}={item.get('status')}({item.get('issue_count', 0)} issues)"
            for item in summary["results"]
        )
    )
    print(f"Summary: {summary_out}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
