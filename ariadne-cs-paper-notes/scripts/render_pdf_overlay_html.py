#!/usr/bin/env python3
"""Render a PDF.js Ariadne paper reader with HTML overlay annotations."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any


SEVERITY_CLASS = {
    "Blocker": "blocker",
    "Major": "major",
    "Minor": "minor",
    "Polish": "polish",
}


def load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compact_text(value: Any, *, max_chars: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def html_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def script_json(value: str) -> str:
    return value.replace("</", "<\\/")


def as_rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [item for item in payload[key] if isinstance(item, dict)]
    return []


def finding_index(findings_path: Path) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in as_rows(load_json(findings_path), "findings") if item.get("id")}


def annotation_target(annotation: dict[str, Any]) -> tuple[str, str]:
    level = str(annotation.get("target_level") or "").lower()
    for candidate_level, field in (
        ("sentence", "sentence_id"),
        ("paragraph", "paragraph_id"),
        ("section", "section_id"),
        ("paper", "paper_id"),
    ):
        value = str(annotation.get(field) or "")
        if value:
            return level or candidate_level, value
    return level or "paper", "paper"


def severity_for(finding: dict[str, Any]) -> str:
    severity = compact_text(finding.get("severity"), max_chars=40)
    return severity if severity in SEVERITY_CLASS else "Minor"


def severity_label(severity: str) -> str:
    return {
        "Blocker": "阻断",
        "Major": "重大",
        "Minor": "次要",
        "Polish": "润色",
    }.get(severity, severity)


def issue_type_for(finding: dict[str, Any]) -> str:
    return compact_text(finding.get("issue_type") or finding.get("domain") or "prose", max_chars=80)


def card_id(issue_id: str) -> str:
    return f"ann-{issue_id}"


def annotation_groups(annotations_path: Path, findings: dict[str, dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    anchored: dict[str, list[dict[str, Any]]] = {}
    unanchored: list[dict[str, Any]] = []
    for annotation in as_rows(load_json(annotations_path), "annotations"):
        issue_id = str(annotation.get("issue_id") or "")
        finding = findings.get(issue_id)
        if not finding:
            continue
        level, target = annotation_target(annotation)
        row = {"annotation": annotation, "finding": finding, "level": level, "target": target}
        if level == "paper" or not target:
            unanchored.append(row)
        else:
            anchored.setdefault(target, []).append(row)
    return anchored, unanchored


def copy_pdfjs_assets(out_dir: Path) -> None:
    package_root = Path(__file__).resolve().parents[1] / "node_modules" / "pdfjs-dist"
    sources = {
        package_root / "build" / "pdf.min.js": out_dir / "pdfjs" / "pdf.min.js",
        package_root / "build" / "pdf.worker.min.js": out_dir / "pdfjs" / "pdf.worker.min.js",
    }
    missing = [str(path) for path in sources if not path.exists()]
    if missing:
        raise RuntimeError("pdfjs-dist assets are missing; run `npm install` before rendering PDF.js reports")
    for source, target in sources.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def copy_pdf(pdf: Path, out_dir: Path) -> str:
    target = out_dir / "paper.pdf"
    if pdf.resolve() != target.resolve():
        shutil.copy2(pdf, target)
    return target.name


def first_rect_page(anchor: dict[str, Any]) -> int | None:
    for rect in anchor.get("rects", []):
        try:
            page = int(rect.get("page") or 0)
        except (TypeError, ValueError):
            continue
        if page > 0:
            return page
    return None


def rect_style(rect: dict[str, Any], page_size: dict[str, Any]) -> str:
    width = float(page_size.get("width") or 0)
    height = float(page_size.get("height") or 0)
    if all(key in rect for key in ("x0_pct", "y0_pct", "x1_pct", "y1_pct")):
        left = float(rect["x0_pct"]) * 100
        top = float(rect["y0_pct"]) * 100
        right = float(rect["x1_pct"]) * 100
        bottom = float(rect["y1_pct"]) * 100
    elif width > 0 and height > 0:
        left = float(rect.get("x0", 0)) / width * 100
        top = float(rect.get("y0", 0)) / height * 100
        right = float(rect.get("x1", 0)) / width * 100
        bottom = float(rect.get("y1", 0)) / height * 100
    else:
        left = top = 0.0
        right = bottom = 0.0
    return f"left:{left:.4f}%;top:{top:.4f}%;width:{max(right-left, 0.1):.4f}%;height:{max(bottom-top, 0.1):.4f}%;"


def render_finding_card(row: dict[str, Any], *, unanchored: bool = False) -> str:
    finding = row["finding"]
    annotation = row["annotation"]
    issue_id = str(finding.get("id") or annotation.get("issue_id") or "")
    severity = severity_for(finding)
    issue_type = issue_type_for(finding)
    level = row.get("level") or "paper"
    target = row.get("target") or "paper"
    target_attrs = {
        "sentence": "data-target-sentence",
        "paragraph": "data-target-paragraph",
        "section": "data-target-section",
        "paper": "data-target-paper",
    }
    attr_name = target_attrs.get(str(level), "data-target-paper")
    if level == "paper" and str(target) == "paper":
        unanchored = False
    unanchored_attr = ' data-unanchored="true"' if unanchored else ""
    target_attr = "" if unanchored else f' {attr_name}="{html_escape(target)}"'
    jump_page = row.get("jump_page")
    page_attr = f' data-jump-page="{html_escape(jump_page)}"' if jump_page and not unanchored else ""
    jump_attr = f' data-jump-target="{html_escape(target)}"{page_attr}' if not unanchored else ""
    disabled_attr = ' disabled aria-disabled="true"' if unanchored else ""
    jump_label = f"PDF 第 {jump_page} 页" if jump_page and not unanchored else ("定位原文" if not unanchored else "未映射到 PDF")
    details = [
        ("读者卡点", finding.get("reader_friction")),
        ("违反原则", finding.get("writing_principle")),
        ("自改问题", finding.get("self_check") or finding.get("next_draft_task")),
    ]
    detail_html = "".join(
        f"<p><strong>{html_escape(label)}</strong> {html_escape(compact_text(value, max_chars=900))}</p>"
        for label, value in details
        if compact_text(value)
    )
    return f"""
<article id="{html_escape(card_id(issue_id))}" class="annotation-card severity-{SEVERITY_CLASS[severity]}" data-severity="{html_escape(severity)}" data-issue-type="{html_escape(issue_type)}" data-issue-ids="{html_escape(issue_id)}" data-target-level="{html_escape(level)}"{target_attr}{unanchored_attr}>
  <button class="card-jump" type="button"{jump_attr}{disabled_attr}>
    <span class="card-severity">{html_escape(severity_label(severity))}</span>
    <span class="card-title">{html_escape(finding.get("title") or issue_id)}</span>
    <span class="card-jump-label">{html_escape(jump_label)}</span>
  </button>
  <p>{html_escape(compact_text(finding.get("diagnosis"), max_chars=1200))}</p>
  {detail_html}
</article>
"""


def anchor_label(anchor_id: str, anchor: dict[str, Any]) -> str:
    source = compact_text(anchor.get("source_file"), max_chars=80)
    line = anchor.get("line_start") or ""
    suffix = f" ({Path(source).name}:{line})" if source or line else ""
    return f"{anchor_id}{suffix}"


def render_overlay_html(
    *,
    pdf: Path,
    findings_path: Path,
    annotations_path: Path,
    sentence_bbox_path: Path,
    coverage_path: Path | None,
    manifest_path: Path | None,
    output: Path,
    dpi: int,
    title: str,
) -> None:
    out_dir = output.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    copy_pdfjs_assets(out_dir)
    pdf_name = copy_pdf(pdf, out_dir)
    findings = finding_index(findings_path)
    anchored, unanchored = annotation_groups(annotations_path, findings)
    bbox = load_json(sentence_bbox_path) or {}
    bbox_anchors = bbox.get("anchors") if isinstance(bbox.get("anchors"), dict) else {}
    page_sizes = bbox.get("page_sizes") if isinstance(bbox.get("page_sizes"), dict) else {}
    bbox_coverage = bbox.get("coverage") if isinstance(bbox.get("coverage"), dict) else {}
    source_artifact = str(sentence_bbox_path)
    source_hash = str(bbox.get("review_units_hash") or "")
    overlays_by_page: dict[int, list[str]] = {}
    unanchored_rows: list[dict[str, Any]] = list(unanchored)
    anchored_rows: list[dict[str, Any]] = []
    unmappable_items: list[str] = []
    if isinstance(bbox_anchors, dict):
        for anchor_id, anchor in sorted(bbox_anchors.items()):
            if isinstance(anchor, dict) and anchor.get("unmappable"):
                reason = compact_text(anchor.get("reason") or "unmappable", max_chars=160)
                unmappable_items.append(f"<li><code>{html_escape(anchor_label(anchor_id, anchor))}</code>: {html_escape(reason)}</li>")

    for target, rows in anchored.items():
        anchor = bbox_anchors.get(target) if isinstance(bbox_anchors, dict) else None
        if not isinstance(anchor, dict) or anchor.get("unmappable") or not anchor.get("rects"):
            unanchored_rows.extend(rows)
            continue
        jump_page = first_rect_page(anchor)
        for row in rows:
            item = dict(row)
            if jump_page:
                item["jump_page"] = jump_page
            anchored_rows.append(item)
        issue_ids = " ".join(str(row["finding"].get("id")) for row in rows if row["finding"].get("id"))
        card_ids = " ".join(card_id(issue_id) for issue_id in issue_ids.split())
        severity = severity_for(rows[0]["finding"])
        issue_type = issue_type_for(rows[0]["finding"])
        level = rows[0]["level"]
        marker_class = {
            "sentence": "paper-sentence has-annotation",
            "paragraph": "annotation-bubble has-paragraph-annotation",
            "section": "annotation-bubble has-section-annotation",
        }.get(level, "annotation-bubble has-section-annotation")
        section_id_written = False
        for rect in anchor.get("rects", []):
            page = int(rect.get("page") or 0)
            if page <= 0:
                continue
            page_size = page_sizes.get(str(page), {}) if isinstance(page_sizes, dict) else {}
            if level == "sentence":
                target_attr = f'data-sentence-id="{html_escape(target)}"'
            elif level == "paragraph":
                target_attr = f'data-paragraph-id="{html_escape(target)}"'
            elif level == "section":
                target_attr = f'data-section-id="{html_escape(target)}"'
            else:
                target_attr = f'data-anchor-id="{html_escape(target)}"'
            id_attr = ""
            if level == "section" and not section_id_written:
                id_attr = f' id="anchor-{html_escape(target)}"'
                section_id_written = True
            overlays_by_page.setdefault(page, []).append(
                f'<button{id_attr} class="pdf-highlight {marker_class} severity-{SEVERITY_CLASS[severity]}" '
                f'style="{rect_style(rect, page_size)}" {target_attr} '
                f'data-has-issue="true" data-issue-ids="{html_escape(issue_ids)}" '
                f'data-card-ids="{html_escape(card_ids)}" '
                f'data-severity="{html_escape(severity)}" data-issue-type="{html_escape(issue_type)}" '
                f'aria-describedby="{html_escape(card_id(issue_ids.split()[0]) if issue_ids else "")}" '
                f'type="button" title="{html_escape(rows[0]["finding"].get("title") or issue_ids)}"></button>'
            )

    overlay_payload = json.dumps(overlays_by_page, ensure_ascii=False, separators=(",", ":"))
    page_count = max([0, *overlays_by_page.keys(), *[int(page) for page in page_sizes.keys() if str(page).isdigit()]])

    anchored_cards = [render_finding_card(row) for row in anchored_rows]
    paper_rows = [row for row in unanchored_rows if row.get("level") == "paper" and row.get("target") == "paper"]
    unmapped_rows = [row for row in unanchored_rows if row not in paper_rows]
    paper_cards = [render_finding_card(row, unanchored=True) for row in paper_rows]
    unanchored_cards = [render_finding_card(row, unanchored=True) for row in unmapped_rows]
    paper_issue_ids = " ".join(str(row["finding"].get("id")) for row in paper_rows if row["finding"].get("id"))
    paper_overview = (
        f'<div id="paper-overview-annotations"><button class="annotation-bubble paper has-paper-annotation" '
        f'data-paper-id="paper" data-has-issue="true" data-issue-ids="{html_escape(paper_issue_ids)}" '
        f'data-card-ids="{html_escape(" ".join(card_id(issue_id) for issue_id in paper_issue_ids.split()))}" '
        f'data-severity="{html_escape(severity_for(paper_rows[0]["finding"]))}" '
        f'data-issue-type="{html_escape(issue_type_for(paper_rows[0]["finding"]))}" type="button">Paper notes</button></div>'
        if paper_rows and paper_issue_ids
        else ""
    )
    coverage = load_json(coverage_path) if coverage_path else None
    coverage_rows = ""
    if isinstance(coverage, dict):
        for row in coverage.get("units", []) if isinstance(coverage.get("units"), list) else []:
            if isinstance(row, dict):
                coverage_rows += (
                    f"<tr><td>{html_escape(row.get('unit'))}</td><td>{html_escape(row.get('total'))}</td>"
                    f"<td>{html_escape(row.get('reviewed'))}</td><td>{html_escape(row.get('with_issues'))}</td>"
                    f"<td>{html_escape(row.get('pending_in'))}</td></tr>"
                )
    manifest = load_json(manifest_path) if manifest_path else None
    report_kind = "pdf-overlay"
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#f4f5f7; color:#172033; }}
    .review-report {{ min-height:100vh; }}
    #paper-reader {{ display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:0; }}
    .paper-pane {{ padding:24px; overflow:auto; max-height:100vh; }}
    .pdfjs-status {{ max-width:980px; margin:0 auto 12px; color:#667086; }}
    .pdf-page {{ position:relative; max-width:980px; margin:0 auto 18px; background:white; box-shadow:0 1px 8px rgba(20,30,50,.14); }}
    .pdf-page.is-loading {{ min-height:760px; display:flex; align-items:center; justify-content:center; color:#667086; }}
    .pdf-page-content {{ position:relative; margin:0 auto; }}
    .pdf-page canvas {{ display:block; width:100%; height:auto; }}
    .pdf-text-layer {{ position:absolute; inset:0; overflow:hidden; line-height:1; text-align:initial; z-index:1; }}
    .pdf-text-layer span,.pdf-text-layer br {{ color:transparent; position:absolute; white-space:pre; cursor:text; transform-origin:0% 0%; }}
    .pdf-overlay {{ position:absolute; inset:0; z-index:2; pointer-events:none; }}
    .pdf-highlight {{ position:absolute; border:0; background:rgba(235, 89, 75, .24); outline:2px solid rgba(194, 50, 50, .65); cursor:pointer; padding:0; }}
    .pdf-highlight {{ pointer-events:auto; }}
    .pdf-highlight.severity-major {{ background:rgba(240, 158, 54, .26); outline-color:rgba(192, 110, 16, .72); }}
    .pdf-highlight.severity-minor {{ background:rgba(64, 132, 214, .22); outline-color:rgba(35, 93, 170, .68); }}
    .pdf-highlight.severity-polish {{ background:rgba(91, 153, 104, .22); outline-color:rgba(49, 122, 68, .68); }}
    .pdf-highlight.is-active {{ outline-width:4px; }}
    #annotation-panel {{ position:sticky; top:0; height:100vh; overflow:auto; background:#fff; border-left:1px solid #d9dee8; padding:16px; }}
    .filters {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px; }}
    .filters button,.card-jump {{ border:1px solid #ccd3df; background:#fff; border-radius:6px; padding:7px 9px; cursor:pointer; }}
    .annotation-card {{ border:1px solid #d7dce6; border-left-width:4px; border-radius:8px; padding:12px; margin:0 0 12px; }}
    .annotation-card.severity-blocker {{ border-left-color:#c83232; }}
    .annotation-card.severity-major {{ border-left-color:#c06e10; }}
    .annotation-card.severity-minor {{ border-left-color:#235daa; }}
    .annotation-card.severity-polish {{ border-left-color:#317a44; }}
    .card-jump {{ display:block; width:100%; text-align:left; font-weight:700; }}
    .card-jump[disabled] {{ cursor:not-allowed; opacity:.72; }}
    .card-severity {{ font-size:12px; margin-right:6px; color:#5c6678; }}
    .card-jump-label {{ float:right; font-size:12px; font-weight:600; color:#5c6678; }}
    #bbox-diagnostics {{ padding:16px 24px; background:#fff; border-top:1px solid #d9dee8; }}
    #bbox-diagnostics dl {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:0 0 12px; }}
    #bbox-diagnostics dt {{ font-size:12px; color:#647084; }}
    #bbox-diagnostics dd {{ margin:2px 0 0; font-weight:700; }}
    #bbox-diagnostics ul {{ max-height:180px; overflow:auto; margin:8px 0 0; padding-left:20px; }}
    #coverage-receipt {{ padding:24px; background:#fff; border-top:1px solid #d9dee8; }}
    #coverage-receipt table {{ border-collapse:collapse; width:100%; }}
    #coverage-receipt th,#coverage-receipt td {{ border:1px solid #d9dee8; padding:6px 8px; text-align:left; }}
    @media (max-width: 900px) {{ #paper-reader {{ grid-template-columns:1fr; }} #annotation-panel {{ position:relative; height:auto; border-left:0; }} }}
  </style>
</head>
<body>
<article class="review-report" data-report-kind="{report_kind}">
  <section id="paper-reader">
    <div class="paper-pane pdf-paper-pane" data-paper-view="pdfjs-overlay" data-source-artifact="{html_escape(source_artifact)}" data-source-hash="{html_escape(source_hash)}" data-sentence-id-scheme="section-paragraph-sentence-v2" data-annotation-mode="pdfjs-overlay">
      <div id="finding-anchor-index" hidden aria-hidden="true">{''.join(f'<span id="{html_escape(issue_id)}"></span>' for issue_id in findings)}</div>
      <div id="pdfjs-viewer" class="pdfjs-viewer" data-pdf-src="{html_escape(pdf_name)}" data-page-count="{html_escape(page_count)}" aria-label="PDF.js 论文阅读器">
        <p class="pdfjs-status">正在加载 PDF...</p>
      </div>
      <script type="application/json" id="pdf-overlay-data">{script_json(overlay_payload)}</script>
      {paper_overview}
    </div>
    <aside id="annotation-panel">
      <div class="filters">
        <button type="button" data-filter="all">全部</button>
        <button type="button" data-filter="Blocker">阻断</button>
        <button type="button" data-filter="Major">重大</button>
        <button type="button" data-filter="Minor">次要</button>
        <button type="button" data-filter="Polish">润色</button>
      </div>
      {''.join(anchored_cards)}
      {''.join(paper_cards)}
      {''.join(unanchored_cards)}
    </aside>
  </section>
  <section id="bbox-diagnostics">
    <h2>PDF 锚点诊断</h2>
    <dl>
      <div><dt>锚点总数</dt><dd>{html_escape(bbox_coverage.get("anchors_total", len(bbox_anchors) if isinstance(bbox_anchors, dict) else 0))}</dd></div>
      <div><dt>已映射</dt><dd>{html_escape(bbox_coverage.get("mapped", ""))}</dd></div>
      <div><dt>不可映射</dt><dd>{html_escape(bbox_coverage.get("unmappable", ""))}</dd></div>
      <div><dt>PDF 哈希</dt><dd>{html_escape(compact_text(bbox.get("pdf_hash"), max_chars=24))}</dd></div>
    </dl>
    <details {"open" if unmappable_items else ""}>
      <summary>不可映射锚点 ({len(unmappable_items)})</summary>
      <ul>{''.join(unmappable_items) if unmappable_items else '<li>无</li>'}</ul>
    </details>
  </section>
  <section id="coverage-receipt">
    <h2>覆盖回执</h2>
    <p>覆盖一致性 (Coverage consistency)：确定性 PDF overlay 渲染已连接编译后的发现、批注和 bbox 锚点。</p>
    <table><caption>覆盖汇总</caption><thead><tr><th scope="col">单位</th><th scope="col">总数</th><th scope="col">已审阅</th><th scope="col">有问题</th><th scope="col">待处理位置</th></tr></thead><tbody>{coverage_rows}</tbody></table>
  </section>
</article>
<script src="pdfjs/pdf.min.js"></script>
<script>
const cards = [...document.querySelectorAll('.annotation-card')];
let highlights = [];
const viewer = document.getElementById('pdfjs-viewer');
const overlayData = JSON.parse(document.getElementById('pdf-overlay-data').textContent || '{{}}');
const pdfSource = viewer ? viewer.dataset.pdfSrc : '';
if (window.pdfjsLib) {{
  pdfjsLib.GlobalWorkerOptions.workerSrc = 'pdfjs/pdf.worker.min.js';
}}
async function renderPdf() {{
  if (!viewer || !window.pdfjsLib) return;
  viewer.innerHTML = '<p class="pdfjs-status">正在加载 PDF...</p>';
  try {{
    const pdf = await pdfjsLib.getDocument({{url: pdfSource}}).promise;
    viewer.innerHTML = '';
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {{
      const page = await pdf.getPage(pageNumber);
      const viewport = page.getViewport({{scale: 1.45}});
      const section = document.createElement('section');
      section.className = 'pdf-page pdf-anchor is-loading';
      section.id = `pdf-page-${{pageNumber}}`;
      section.dataset.page = String(pageNumber);
      section.textContent = `正在渲染 PDF 第 ${{pageNumber}} 页...`;
      viewer.appendChild(section);
      const content = document.createElement('div');
      content.className = 'pdf-page-content';
      content.style.width = `${{viewport.width}}px`;
      content.style.height = `${{viewport.height}}px`;
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      content.appendChild(canvas);
      const textLayer = document.createElement('div');
      textLayer.className = 'pdf-text-layer';
      content.appendChild(textLayer);
      const overlay = document.createElement('div');
      overlay.className = 'pdf-overlay';
      overlay.innerHTML = (overlayData[String(pageNumber)] || []).join('\\n');
      content.appendChild(overlay);
      section.textContent = '';
      section.classList.remove('is-loading');
      section.appendChild(content);
      await page.render({{canvasContext: canvas.getContext('2d'), viewport}}).promise;
      if (pdfjsLib.renderTextLayer) {{
        const textContent = await page.getTextContent();
        await pdfjsLib.renderTextLayer({{
          textContentSource: textContent,
          container: textLayer,
          viewport,
          textDivs: []
        }}).promise;
      }}
    }}
    highlights = [...document.querySelectorAll('.pdf-highlight')];
    bindHighlights();
    setFilter(activeFilter);
  }} catch (error) {{
    viewer.innerHTML = `<p class="pdfjs-status">PDF.js 加载失败：${{String(error && error.message || error)}}</p>`;
  }}
}}
let activeFilter = 'all';
function setFilter(value) {{
  activeFilter = value;
  cards.forEach(card => card.hidden = value !== 'all' && card.dataset.severity !== value);
  highlights.forEach(h => h.hidden = value !== 'all' && h.dataset.severity !== value);
}}
document.querySelectorAll('[data-filter]').forEach(btn => btn.addEventListener('click', () => setFilter(btn.dataset.filter)));
function activate(target) {{
  highlights.forEach(h => h.classList.remove('is-active'));
  const sectionHit = document.getElementById('anchor-' + target);
  const hit = highlights.find(h => h.dataset.sentenceId === target || h.dataset.paragraphId === target) || sectionHit;
  if (hit) {{
    hit.classList.add('is-active');
    hit.scrollIntoView({{behavior:'smooth', block:'center'}});
  }}
}}
function activeCardIndex() {{
  const visible = cards.filter(card => !card.hidden);
  const current = document.activeElement && document.activeElement.closest ? document.activeElement.closest('.annotation-card') : null;
  return {{visible, index: current ? visible.indexOf(current) : -1}};
}}
function focusCardAt(index) {{
  const {{visible}} = activeCardIndex();
  if (!visible.length) return;
  const bounded = Math.max(0, Math.min(index, visible.length - 1));
  const card = visible[bounded];
  card.scrollIntoView({{behavior:'smooth', block:'center'}});
  const button = card.querySelector('.card-jump');
  if (button) button.focus();
  const target = button ? button.dataset.jumpTarget : '';
  if (target) activate(target);
}}
function bindHighlights() {{
  highlights.forEach(hit => hit.addEventListener('click', () => {{
    const firstCard = (hit.dataset.cardIds || '').split(/\\s+/).find(Boolean);
    const firstIssue = (hit.dataset.issueIds || '').split(/\\s+/).find(Boolean);
    const card = (firstCard && document.getElementById(firstCard)) || (firstIssue && document.querySelector(`.annotation-card[data-issue-ids~="${{CSS.escape(firstIssue)}}"]`));
    if (card) {{
      card.scrollIntoView({{behavior:'smooth', block:'center'}});
      const button = card.querySelector('.card-jump');
      if (button) button.focus();
    }}
  }}));
}}
document.querySelectorAll('.card-jump[data-jump-target]').forEach(btn => btn.addEventListener('click', () => activate(btn.dataset.jumpTarget)));
document.addEventListener('keydown', event => {{
  if (!['ArrowDown','ArrowUp','j','k'].includes(event.key)) return;
  const {{visible, index}} = activeCardIndex();
  if (!visible.length) return;
  event.preventDefault();
  const next = index < 0 ? 0 : index + (event.key === 'ArrowUp' || event.key === 'k' ? -1 : 1);
  focusCardAt(next);
}});
renderPdf();
</script>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--sentence-bbox", required=True, type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--title", default="Ariadne PDF Review")
    args = parser.parse_args(argv)
    render_overlay_html(
        pdf=args.pdf.expanduser().resolve(),
        findings_path=args.findings.expanduser().resolve(),
        annotations_path=args.annotations.expanduser().resolve(),
        sentence_bbox_path=args.sentence_bbox.expanduser().resolve(),
        coverage_path=args.coverage.expanduser().resolve() if args.coverage else None,
        manifest_path=args.manifest.expanduser().resolve() if args.manifest else None,
        output=args.output.expanduser().resolve(),
        dpi=args.dpi,
        title=args.title,
    )
    print(f"PDF overlay HTML: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
