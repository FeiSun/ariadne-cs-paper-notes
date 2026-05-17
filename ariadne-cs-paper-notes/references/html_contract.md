# Ariadne HTML Contract

Use this file when the user asks for HTML, 网页, 可视化报告, 批注报告, or a saved structured review file. Also load `report_contract.md`; load `numeric_contract.md` when numbers/tables are visible.

## Scope

- Write review content in Chinese by default.
- Keep precise technical terms in English when clearer: claim, evidence, baseline, ablation, caption, limitation, coverage.
- Produce a self-contained `.html` unless the user asks otherwise.
- Do not require external network assets, remote fonts, CDN scripts, or CSS frameworks.
- Inline JavaScript is allowed for self-contained filters/toggles.
- Do not claim live PDF synchronization, clickable PDF jumping, embedded PDF annotations, or written PDF comments unless implemented and checked.
- When trigger text includes `批注`, include article-ordered diagnostic section/paragraph/sentence notes.

## Required Sections

Full-paper HTML reports use these ids:

```html
<article class="review-report">
  <header>...</header>
  <nav aria-label="Review sections">...</nav>
  <main>
    <section id="executive-diagnosis">...</section>
    <section id="issue-index">...</section>
    <section id="claim-evidence-audit">...</section>
    <section id="deep-reading-notes">...</section>
    <section id="submission-readiness">...</section>
    <section id="local-comments">...</section>
    <section id="revision-plan">...</section>
    <section id="coverage-receipt">...</section>
  </main>
</article>
```

Use these Chinese section labels:

| Section id | 中文标签 |
|---|---|
| `executive-diagnosis` | 总评诊断与可救骨架 |
| `issue-index` | 问题索引 |
| `claim-evidence-audit` | 主张与证据审计 |
| `deep-reading-notes` | 逐章精读批注 |
| `submission-readiness` | 数字/公式/图表/版式/提交就绪 |
| `local-comments` | 共性问题汇总 |
| `revision-plan` | 修改路线 |
| `coverage-receipt` | 覆盖回执与 artifacts |

Do not use legacy top-level note sections such as `top-priorities`, `section-review`, `paragraph-surgery`, `margin-notes`, `keep-notes`, `section-comments`, or `section-reflections`.

## Layout and Style

Use a sober advisor-report design:

- header with paper title/path, review date, input artifacts, requested scope;
- summary band with central claim, readiness, severity counts;
- top/sticky navigation;
- readable max-width;
- repeated findings/notes may use cards; avoid decorative marketing layout;
- tables are horizontally scrollable on small screens;
- substantive tables have `<caption>` and `<th scope="col">`;
- include print rules so the report can be saved as PDF;
- avoid remote assets, animations, and decorative gradients.

Severity badge colors:

- `Blocker`: `#b42318` on `#fff1f0`
- `Major`: `#9a6700` on `#fff7df`
- `Minor`: `#3451b2` on `#edf2ff`
- `Polish`: `#147d64` on `#e9f8f3`

Use shape/text prefixes when helpful: `■ Blocker`, `▲ Major`, `● Minor`, `◆ Polish`.

## Filters and Tags

If severity filters such as `全部 / Blocker / Major / Minor / Polish` are shown, they must work. Every severity-badged issue item must have `data-severity` on a stable container so it hides as a unit:

- finding cards;
- Issue Index rows;
- Deep Reading section/paragraph/sentence rows;
- local-pattern rows;
- claim-evidence rows with risk labels;
- submission/PDF/layout rows.

Wire buttons with inline JavaScript and update active/`aria-pressed` states. If filtering is not implemented, show a static legend instead of clickable-looking buttons.

Add `data-issue-type` when clear: `math`, `numeric`, `evaluation`, `claim`, `layout`, `checklist`, `prose`, `citation`, `source`, or `submission`.

When a filter hides all filterable children in a section/table, show a small empty state such as `该严重度暂无项` / `该表无此严重度项`.

## Deep Reading HTML

Inside `#deep-reading-notes`, keep notes in manuscript order. Required row/block kinds:

- `data-note-kind="section"`: one section-reflection row/block per visible section with `读后一句话`, `章节任务是否对齐`, `建议结构`, `未闭合问题`, `关联问题`, `下一稿任务`.
- `data-note-kind="paragraph"`: one row per visible paragraph with a substantive issue or non-trivial surgery decision. Include paragraph job, decision (`保留`, `原位修改`, `合并`, `拆分`, `移动`, `删除`), why, linked finding, next structural task.
- `data-note-kind="sentence"`: one row per substantive sentence issue. Include `位置`, `检查维度`, `原句/片段`, `读者卡点`, `违反原则`, `关联问题`, `下一稿任务 / 自改问题`, `严重度`.

Do not render visible `clean` rows or a visible sentence coverage ledger. If a sentence-like coverage ledger is produced, save it as a companion artifact or note it in `render_manifest.json`.

## Submission Readiness HTML

Suggested subsections:

- `数值与表格`
- `公式与符号`
- `图表与 caption`
- `PDF 版式`
- `引用与 checklist`
- `Polish Sweep`

Every `render_required` numeric signal must appear with concrete values. See `numeric_contract.md`.

For page-level layout rows, suggested columns are `PDF 页`, `严重度`, `版式卡点`, `关联问题`, `下一稿任务`.

## Coverage Receipt HTML

Include:

- coverage units table;
- Reader-Journey pass receipt;
- body-backed count table;
- QA/audit lines;
- known blind spots;
- artifact paths.

Coverage counts must be evidence-backed. PDF page totals must come from extraction metadata, renderer output, or another explicit page-count source. Header/summary counts must match visible body rows or be marked pending.

## PDF Linkage Levels

- **Level 0: Page anchors in report**. Default. Links point to report-internal page-note anchors.
- **Level 1: External PDF open link**. Use only when HTML and PDF are co-located or a stable relative path exists; browser page opening is best effort.
- **Level 2: Embedded PDF viewer**. Requires an actual viewer implementation.
- **Level 3: Written PDF annotations**. Requires an annotated PDF file created by a PDF annotation tool and checked.

Do not overpromise. Mention Level 2/3 only if actually implemented or requested as future work.

## Output Paths

If no output path is provided, save beside the primary reviewed artifact:

```text
<paper-directory>/ariadne_notes_<safe-paper-stem>_<YYYYMMDD>.html
```

Choose the stem from the reviewed PDF when available; otherwise from the entry `.tex`. `safe-paper-stem` replaces characters outside `[A-Za-z0-9_.-]` with `_`, trims leading/trailing `_`, and falls back to `paper`. Add suffixes only to avoid overwriting same-day reports or collisions.

Save the artifact bundle beside the HTML as described in `report_contract.md`. If not writable, use a temp directory and report the fallback path.

## HTML Audit

Before delivery, run when feasible:

```bash
scripts/audit_html_report.py <report.html>
```

If JSON artifacts exist, also run:

```bash
scripts/audit_review_artifacts.py --bundle <bundle>/ --html <report.html>
```

Fix every `ERROR` before delivery. Treat `WARNING` lines as caveats or calibration notes.
