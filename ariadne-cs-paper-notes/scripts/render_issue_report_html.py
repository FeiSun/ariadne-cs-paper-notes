#!/usr/bin/env python3
"""Render a compact Ariadne issue report without embedding the paper body."""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SEVERITIES = ("Blocker", "Major", "Minor", "Polish")


def load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [item for item in payload[key] if isinstance(item, dict)]
    return []


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def compact(value: Any, *, max_chars: int = 1000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def severity_of(finding: dict[str, Any]) -> str:
    severity = compact(finding.get("severity"), max_chars=40)
    return severity if severity in SEVERITIES else "Minor"


def render_finding(finding: dict[str, Any]) -> str:
    finding_id = compact(finding.get("id"), max_chars=80)
    severity = severity_of(finding)
    issue_type = compact(finding.get("issue_type") or finding.get("domain") or "prose", max_chars=80)
    title = compact(finding.get("title") or finding_id or issue_type, max_chars=180)
    details = [
        ("诊断", finding.get("diagnosis")),
        ("读者卡点", finding.get("reader_friction")),
        ("违反原则", finding.get("writing_principle") or finding.get("principle")),
        ("自改问题", finding.get("self_check") or finding.get("next_draft_task")),
    ]
    detail_html = "".join(
        f"<p><strong>{esc(label)}</strong> {esc(compact(value, max_chars=1200))}</p>"
        for label, value in details
        if compact(value)
    )
    return f"""
<article id="{esc(finding_id)}" class="finding-card severity-{esc(severity.lower())}" data-severity="{esc(severity)}" data-issue-type="{esc(issue_type)}">
  <h3><span>{esc(severity)}</span> {esc(title)}</h3>
  {detail_html}
</article>
"""


def coverage_table(coverage: Any) -> str:
    if not isinstance(coverage, dict) or not isinstance(coverage.get("units"), list):
        return ""
    body = ""
    for row in coverage["units"]:
        if not isinstance(row, dict):
            continue
        body += (
            f"<tr><td>{esc(row.get('unit'))}</td><td>{esc(row.get('total'))}</td>"
            f"<td>{esc(row.get('reviewed'))}</td><td>{esc(row.get('with_issues'))}</td>"
            f"<td>{esc(row.get('pending_in'))}</td></tr>"
        )
    return (
        '<table><caption>Coverage summary</caption><thead><tr><th scope="col">Unit</th>'
        '<th scope="col">Total</th><th scope="col">Reviewed</th><th scope="col">With issues</th>'
        f'<th scope="col">Pending in</th></tr></thead><tbody>{body}</tbody></table>'
    )


def render_issue_report(*, findings: Path, coverage: Path | None, output: Path, title: str) -> None:
    finding_rows = rows(load_json(findings), "findings")
    counts = Counter(severity_of(finding) for finding in finding_rows)
    summary = " ".join(f"{severity}: {counts.get(severity, 0)}" for severity in SEVERITIES)
    cards = "".join(render_finding(finding) for finding in finding_rows)
    coverage_html = coverage_table(load_json(coverage) if coverage else None)
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f6f7f9; color:#182236; }}
    .review-report {{ max-width:980px; margin:0 auto; padding:28px 20px 48px; }}
    header {{ margin-bottom:20px; }}
    .summary {{ color:#5d687a; }}
    .filters {{ display:flex; gap:8px; flex-wrap:wrap; margin:18px 0; }}
    button {{ border:1px solid #cfd6e2; background:white; border-radius:6px; padding:7px 10px; cursor:pointer; }}
    .finding-card {{ background:white; border:1px solid #d8deea; border-left:4px solid #6c778b; border-radius:8px; padding:14px 16px; margin:12px 0; }}
    .severity-blocker {{ border-left-color:#bd2d2d; }}
    .severity-major {{ border-left-color:#b8660d; }}
    .severity-minor {{ border-left-color:#2f65a7; }}
    .severity-polish {{ border-left-color:#327447; }}
    h1 {{ font-size:28px; margin:0 0 8px; }}
    h2 {{ margin-top:28px; }}
    h3 {{ margin:0 0 10px; font-size:18px; }}
    h3 span {{ font-size:12px; color:#667085; margin-right:6px; }}
    p {{ line-height:1.55; }}
    table {{ border-collapse:collapse; width:100%; background:white; }}
    th,td {{ border:1px solid #d8deea; padding:7px 9px; text-align:left; }}
  </style>
</head>
<body>
<article class="review-report" data-report-kind="issue-report-only">
  <header id="issue-report">
    <h1>{esc(title)}</h1>
    <p class="summary">{esc(summary)}</p>
    <div class="filters">
      <button type="button" data-filter="all">All</button>
      <button type="button" data-filter="Blocker">Blocker</button>
      <button type="button" data-filter="Major">Major</button>
      <button type="button" data-filter="Minor">Minor</button>
      <button type="button" data-filter="Polish">Polish</button>
    </div>
  </header>
  <section id="findings">{cards}</section>
  <section id="coverage-receipt">
    <h2>Coverage Receipt</h2>
    {coverage_html}
  </section>
</article>
<script>
const cards = [...document.querySelectorAll('.finding-card')];
document.querySelectorAll('[data-filter]').forEach(btn => btn.addEventListener('click', () => {{
  const value = btn.dataset.filter;
  cards.forEach(card => card.hidden = value !== 'all' && card.dataset.severity !== value);
}}));
</script>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", default="Ariadne Issue Report")
    args = parser.parse_args(argv)
    render_issue_report(
        findings=args.findings.expanduser().resolve(),
        coverage=args.coverage.expanduser().resolve() if args.coverage else None,
        output=args.output.expanduser().resolve(),
        title=args.title,
    )
    print(f"Issue report HTML: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
