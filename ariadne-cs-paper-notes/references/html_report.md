# Ariadne HTML Notes Report

Use this reference when the user asks for HTML, 网页, 可视化报告, 批注报告, or a structured review file. The report is a review artifact, not a replacement for the paper or PDF.

## Scope

- Write review content in Chinese by default.
- Keep precise technical terms in English when clearer: claim, evidence, baseline, ablation, caption, limitation, pAURC, coverage, etc.
- Use a self-contained `.html` file unless the user asks for a different format.
- Do not require external network assets, fonts, JavaScript libraries, or CSS frameworks.
- Inline `<script>` is allowed for self-contained interactions such as severity filtering or table toggles. External script URLs, CDN bundles, remote fonts, and remote CSS are not allowed.
- If the report shows severity filter controls such as `全部 / Blocker / Major / Minor / Polish`, the controls must work. Every element that visually carries a severity badge must have `data-severity` on a stable container so it can be hidden as a unit: finding cards, issue-index rows, deep-reading section/paragraph/sentence rows, local-pattern rows, claim-evidence rows with risk labels, and submission/PDF/Layout page-note rows. Wire the buttons with inline JavaScript and update active/`aria-pressed` states. If filtering is not implemented, render a static severity legend instead of clickable-looking buttons.
- Add `data-issue-type` for issue-type filtering whenever the finding type is clear: `math`, `numeric`, `evaluation`, `claim`, `layout`, `checklist`, `prose`, `citation`, `source`, or `submission`.
- Sections that are paper-wide or meta by design, such as Executive Diagnosis, Salvageable Core, Story Logic overview, Revision Plan, and Coverage Receipt, may remain visible under all filters. Do not leave severity-badged issue items untagged.
- When a filter hides all filterable children in a section or table, show a small empty-state note such as `该严重度暂无项` / `该表无此严重度项` instead of leaving a blank section body or a header-only table.
- Do not claim live PDF synchronization, clickable PDF jumping, or embedded PDF annotations unless a tool actually implements them.
- When the trigger phrase itself contains `批注`, such as `HTML批注` or `批注报告`, include the diagnostic margin-note sections described in `references/reviewer_checklist.md`.

## Recommended Layout

Use a sober advisor-report design:

- Header: paper title/path, review date, input artifacts, and requested review scope.
- Summary band: central claim, submission readiness, top risks count by severity.
- Sticky or top navigation: Executive Diagnosis and Salvageable Core, Issue Index / Finding Ledger, Claim-Evidence Audit, Deep Reading Notes, Submission Readiness, Local Patterns, Revision Plan, Coverage Receipt.
- Main content: readable max-width, section cards only for repeated findings or notes; avoid decorative marketing layout.
- Right rail or compact top panel: functional severity filters by `Blocker`, `Major`, `Minor`, `Polish`, or a static legend if filters are omitted.

Render the report as a revision workbench, not as pass-by-pass logs. The reading process happens internally; the HTML order should help the student understand the paper's risks, then revise in article order, then execute the final plan. Do not split `分章批注`, `逐段手术`, and `句子级批注` into separate repeated sections; they belong inside **Deep Reading Notes / 逐章精读批注** under each manuscript section.

Use these canonical section labels for full-paper HTML reports:

| English canonical section | 中文标签 |
|---|---|
| Executive Diagnosis and Salvageable Core | 总评诊断与可救骨架 |
| Issue Index / Finding Ledger | 问题索引 |
| Claim-Evidence Audit | 主张与证据审计 |
| Deep Reading Notes | 逐章精读批注 |
| Submission Readiness | 数字/公式/图表/版式/提交就绪 |
| Local Patterns | 共性问题汇总 |
| Revision Plan | 修改路线 |
| Coverage Receipt and Artifacts | 覆盖回执与 artifacts |

Prefer semantic HTML:

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

## Finding Card Schema

Represent each finding in JSON with stable fields. In the visible HTML **Issue Index**, render a compact student-facing card; keep full operational details in `findings.json` and in the final Revision Plan instead of making every card feel like a long reviewer report.

- `id`: short stable anchor in `F<number>` form, e.g. `F1`, `F2`, `F12`; use suffixes such as `F3a`, `F3b` only when splitting one grouped finding.
- `severity`: `Blocker`, `Major`, `Minor`, or `Polish`. Any table-value/numerical discrepancy with `reported_value`, `visible_computed_value`, and `delta` is `Blocker` in the student-facing report. Do not downgrade visible arithmetic/value mismatch to `Major`, `Minor`, or `Polish`; uncertainty about aggregation changes the caveat, not the severity.
- `location`: section/page/paragraph/table/figure anchor.
- `snippet`: short quote from the manuscript, if useful.
- `diagnosis`: what is wrong.
- `confidence`: `high`, `medium`, or `low`; required for `Blocker` and `Major`.
- `verification_method`: e.g. PDF visual pass, LaTeX source, extracted text, table signal, claim-evidence cross-check, abstract promise tracking, or reviewer inference.
- `severity_rationale`: why the finding is `Blocker`/`Major` rather than a lower severity.
- `downgrade_condition`: what evidence, clarification, or revision would lower the severity.
- `reader_friction`: where the reader gets stuck, what they know so far, and what they still have to guess.
- `writing_principle`: source principle or writing habit violated, e.g. `知识的诅咒`, `given-new`, `显式逻辑`, `一段只做一件事`.
- `next_draft_task`: concrete next-draft task or self-revision question, not paper-ready prose.
- `evidence_basis`: `PDF page`, `LaTeX source`, `extracted text`, or `reviewer inference`.

Use Chinese labels in the UI. For compact Issue Index cards, prefer only these visible fields:

- `位置`
- `片段` when useful
- `诊断`
- `依据`
- `置信度`
- `验证方式`
- `判级理由`
- `读者卡点`

Do **not** render `降级条件` or `下一稿任务` inside every Issue Index card by default. Those fields remain required in `findings.json` for auditability and should be used in **Revision Plan**, local deep-reading rows, or when a finding genuinely needs a short "如何修" line. This keeps the index complete but not bloated.

For table/numerical findings, preserve the concrete arithmetic signal when available:

- `reported_value`
- `visible_computed_value`
- `delta`
- `aggregation_caveat`, e.g. `visible arithmetic mean only; weighted/micro average or hidden denominator may differ`

The visible report should quote these fields with Chinese labels:

- `表中数值` for `reported_value`
- `可见复算值` for `visible_computed_value`
- `差值` for `delta`
- `口径说明` for `aggregation_caveat`

Do not render raw schema keys such as `reported_value`, `visible_computed_value`, `delta`, or `aggregation_caveat` in the Chinese-facing HTML body. Do not render a numerical finding as only `平均值有偏差` or `需复查` when the artifact contains reported/computed/delta values.

For numerical clusters, split mixed-risk issues instead of burying them in one card. All of these are `Blocker` when they involve a visible table value mismatch; use the title/caveat to distinguish the nature of the problem rather than lowering severity:

- `Hard arithmetic error`: the visible arithmetic cannot reproduce the reported value and affects a claim, table ranking, or prose statement.
- `Aggregation ambiguity`: visible macro cells do not reproduce the summary value, but hidden decimals, weighted/micro aggregation, or a different denominator could explain it. The report still must show `表中数值 / 可见复算值 / 差值`, and the row/card is still `Blocker` until the paper states the denominator clearly.
- `Table generation risk`: repeated average/delta/bold/prose-number issues imply the tables should be regenerated from one spreadsheet/script.

Use sub-ids such as `F3a`, `F3b`, `F3c` when one original priority contains multiple numerical risk types.

## Issue Index / Finding Ledger

Use this section immediately after **Executive Diagnosis and Salvageable Core**. It is the canonical source of full issue explanations. Later sections should usually reference the canonical issue id instead of restating the full finding.

Suggested columns:

- `ID`
- `严重度`
- `问题类型`
- `一句话问题`
- `主要位置`
- `后文引用位置`
- `状态 / 下一步`

Every repeated reference in Deep Reading Notes, Claim-Evidence Audit, Submission Readiness, Local Patterns, or Revision Plan should use a linked id such as `<a class="finding-link" href="#F3a">F3a</a>`. Do not invent linked ids that do not have a corresponding finding card, issue-index row, or grouped finding row.

Repetition rule:

- Issue Index / finding cards: compact canonical diagnosis. Do not repeat every operational field from JSON.
- Issue Index: one-line ledger.
- Later sections: concise local consequence + linked finding id. Do not repeat the full finding diagnosis unless the local context changes the interpretation.

## Structured Review Artifacts

Use this for substantial HTML reports. Structured artifacts are the source of truth; HTML is a rendering of them. Do not keep these only as conceptual objects in the model's context.

Required output behavior: write the HTML report and all JSON artifacts to disk. Default layout:

```text
<paper-directory>/
├── <paper>.pdf / <entry>.tex
├── ariadne_notes_<safe-paper-stem>_<YYYYMMDD>.html
└── ariadne_notes_<safe-paper-stem>_<YYYYMMDD>/
    ├── findings.json
    ├── claims.json
    ├── numeric_audit.json
    ├── coverage.json
    ├── render_manifest.json
    └── pass_observations.json
```

Required artifacts:

- `findings.json`: one object per finding or grouped polish sweep. Required fields mirror **Finding Card Schema**. Numerical findings include `reported_value`, `visible_computed_value`, `delta`, and `aggregation_caveat` when available.
- `claims.json`: the claim ledger. Each object should contain `claim_id`, `claim_text`, `location`, `claim_type`, `strength`, `required_evidence`, `visible_evidence`, `status`, `next_draft_task`, and linked finding ids.
- `numeric_audit.json`: Python-generated table/number recomputation signals from `scripts/extract_paper_text.py --numeric-json`. This file is mandatory when the manuscript has visible tables or prose-cited numbers. Every rendered numeric finding should either cite one or more signal ids/locations from this file, or state why the relevant table could not be parsed. Render-required table-number discrepancy signals have `required_severity: "Blocker"`; the LLM may explain aggregation caveats but must not lower the severity. Reported/computed/delta values must come from this artifact when available.
- `coverage.json`: requested scope, units reviewed, total/reviewed/with issues/clean/skipped counts, Reader-Journey pass status, QA gate status, and known blind spots.
- `render_manifest.json`: section order, omitted/optional sections with reasons, output filename(s), PDF linkage level, and any split-part links. This is not a duplicate of findings; it tells the renderer how the structured data was rendered.
- `pass_observations.json`: observations collected during Pass 0-6 before final classification. Use this schema shape:

```json
{
  "pass_0_engagement_contract": [{"location": "review scope", "observation": "..."}],
  "pass_1_cold_start_skim": [{"location": "...", "what_tripped_me": "...", "linked_findings": ["F1"]}],
  "pass_2_linear_deep_read": [{"location": "...", "paragraph_job": "...", "sentence_checks": 4, "reflection": "..."}],
  "pass_3_section_reflections": [{"location": "...", "suggested_skeleton": ["..."]}],
  "pass_4_whole_paper_argument": [{"location": "...", "observation": "..."}],
  "pass_5_submission_walk": [{"location": "...", "observation": "..."}],
  "pass_6_output_calibration": [{"location": "report", "observation": "..."}]
}
```

Source-of-truth rule: if JSON artifacts and HTML are both produced, JSON is authoritative for data and HTML must be cross-checked against it. Every finding id in JSON must appear in HTML unless the render manifest marks it as deferred to another part. Every HTML severity badge must correspond to a finding or grouped row in JSON. If no JSON artifacts are produced, the HTML itself must satisfy the same contract.

If the artifact directory cannot be written, use a temp directory and report the absolute fallback path in the final response. Do not imply that JSON artifacts were saved beside the paper when they were not.

Validation command when artifacts exist:

```bash
scripts/audit_review_artifacts.py \
  --bundle ariadne_notes_<safe-paper-stem>_<YYYYMMDD>/ \
  --html ariadne_notes_<safe-paper-stem>_<YYYYMMDD>.html
```

Fix every `ERROR` before delivery. Treat `WARNING` lines as report caveats or calibration notes.

## Abstract Promise Tracking

Include this section when an abstract is available. Every abstract sentence containing a number, causal verb, scope claim, novelty claim, "first", "significant", "state-of-the-art", "robust", "efficient", "general", or "all/across" should appear in the table.

Suggested columns:

- `Abstract claim`
- `Claim type`
- `Body evidence location`
- `Evidence strength`
- `Verdict`: `supported`, `overclaim`, `unsupported`, or `ambiguous`
- `Next-draft task`

## Sentence-Level Margin Notes

For diagnostic margin notes, use a table or repeated note cards. Table is denser; cards are easier to scan on narrow screens.

Required columns/fields:

- `位置`
- `检查维度`: choose from `grammar`, `ambiguity`, `concision`, `diction`, `emphasis placement`, `sentence flow`, `topic sentence`, `paragraph flow`, `paragraph transition`, `cognitive load`, `intuition gap`, `missing why`, `redundant sentence`, `paragraph surgery`, `discourse coherence`, `strategic framing`, `insight vs mechanism`, `evidence`, `scope`, `caption`, `terminology`, `number sanity`, `table consistency`, `reference style`, `page rhythm`, `page break`, `widow orphan`, `figure placement`, `figure readability`, `caption proximity`, `equation crowding`, `legend consistency`, `visual system`, `clean`
- `原句/片段`
- `读者卡点`
- `违反原则`
- `下一稿任务 / 自改问题`
- `严重度`

For Ariadne advisor reports, include the source principle inside `违反原则` whenever the note maps to one, e.g. `源原则：知识的诅咒`, `显式逻辑`, `洞察≠机制`, `一段只做一件事`, or `改变读者理解状态`.

Sentence-level notes should teach the student how to revise rather than provide copy-ready prose. In `下一稿任务 / 自改问题`, prefer a diagnosis-backed action or question, such as `补 comparator + metric`, `把旧信息放句首`, `解释这个术语的物理含义`, or `这一句删掉后段落是否仍然顺？`. Give full example wording only as `示例方向` when it clarifies the principle, fixes a high-risk claim, or the user explicitly asks to leave critique mode.

The preferred teaching structure is:

1. **读者卡点**: "读到这里，读者已经知道 X，但还不知道 Y，所以会卡在 Z."
2. **违反原则**: name the writing principle, not only the surface defect.
3. **下一稿任务**: tell the student what cognitive/writing job the next draft must complete.

## Polish Sweep

Use this section to compact low-value mechanical `Polish` issues. Do not create one sentence-level row per spelling typo, ordinal-format issue, casing issue, or trivial hyphenation issue.

Suggested columns:

- `Category`
- `Instances / locations`
- `Next-draft task`
- `Count`

Grouped polish rows still count in the coverage receipt.

## Salvageable Core

Include this section when the report has at least two `Blocker` findings or at least three `Major` findings in the Issue Index / Finding Ledger. It should be forward-looking, not a damage assessment.

Use four blocks:

- `Minimal viable paper`: what the paper could become after fixing Blockers and top Majors.
- `Delete vs. downgrade`: which claims must be removed, and which can survive with narrower scope.
- `Fix type`: sentence rewrite / section restructure / new analysis / rerun experiment / artifact cleanup.
- `Next revision thread`: the single most important thread for the author to follow next.

## Deep Reading Notes

Use this section for Pass 2 and Pass 3 output. It is the ordered manuscript walkthrough and replaces separate global `分章批注`, `逐段手术`, and `句子级批注` sections. Do not duplicate the same local critique in multiple top-level sections.

For each visible section, render a compact subsection such as:

```html
<section class="paper-section" id="sec-introduction">
  <h3>1. Introduction</h3>
  <div class="table-wrap">
    <table>
      <caption>Section reflection</caption>
      <thead><tr><th scope="col">读后一句话</th><th scope="col">章节任务是否对齐</th><th scope="col">建议结构</th><th scope="col">未闭合问题</th><th scope="col">关联问题</th><th scope="col">下一稿任务</th></tr></thead>
      <tbody><tr data-note-kind="section" data-severity="major">...</tr></tbody>
    </table>
  </div>
  <div class="paragraph-note" id="intro-p1">
    <h4>Paragraph 1</h4>
    <table>... paragraph row ... sentence rows ...</table>
  </div>
</section>
```

Required row types inside `#deep-reading-notes`:

- `data-note-kind="section"`: one section-reflection row/block per visible section. Use Chinese fields: `读后一句话`, `章节任务是否对齐`, `建议结构`, `未闭合问题`, `关联问题`, `下一稿任务`. Values should be Chinese and explanatory, e.g. `部分对齐：问题钩子有了，但方法动机还没接稳。`
  - `data-note-kind="paragraph"`: one paragraph row per visible paragraph with a substantive issue or non-trivial surgery decision. Required fields: `段落`, `当前任务`, `处理决定` (`保留`, `原位修改`, `合并`, `拆分`, `移动`, `删除`), `为什么`, `关联问题`, `下一稿结构任务`.
- `data-note-kind="sentence"`: one sentence row for every substantive sentence issue under the corresponding paragraph. Required fields: `位置`, `检查维度`, `原句/片段`, `读者卡点`, `违反原则`, `关联问题`, `下一稿任务 / 自改问题`, `严重度`.

Do not render `clean` / no-issue rows in the student-facing HTML. Clean coverage is represented by coverage counts and, when needed, machine-readable artifacts such as `coverage.json`; issue tables should contain only substantive comments.

Do not render a separate visible "sentence coverage ledger" / `#sentence-coverage` section in the final HTML. A sentence-like coverage ledger is useful as an internal or JSON artifact for auditability, but it duplicates **Deep Reading Notes** and makes the student-facing report noisy. If produced, save it beside the report as a companion artifact or mention it in `render_manifest.json`; do not add a visible HTML section or visible Coverage Receipt row for the ledger unless the user explicitly asks for audit internals.

This article-order structure is the main anti-repetition mechanism: section diagnosis, paragraph surgery, and sentence notes sit together at the place the author will revise. Later cross-cutting sections should link back to the relevant finding ids rather than repeating the full local explanation.

## Submission Readiness

Use this section for Pass 5 output and cross-cutting artifact checks. It may contain multiple compact tables. Suggested subsections:

- `数值与表格`: table arithmetic, blank cells, best-marker/ranking, prose/table mismatch, aggregation ambiguity. Always include concrete reported/computed/delta values when available.
- `公式与符号`: formula, notation, symbol/macro, algorithm consistency.
- `图表与 caption`: figure/table readability, caption takeaway, visual dictionary.
- `PDF 版式`: page-level layout rows. Use a table for short per-page notes; cards only for multi-part visual diagnosis.
- `引用与 checklist`: reference/citation style, venue checklist, anonymity, source hygiene.
- `Polish Sweep`: grouped mechanical polish only.

**Numeric signal rendering completeness**: this section is signal-driven, not only finding-driven. Every `render_required` signal in `numeric_audit.json` must appear in `Submission Readiness` with the concrete `table_id`, row/object label, reported value, visible recomputed value, and delta. Promotion into the Issue Index depends on severity; rendering the signal does not. Ambiguous signals still get a row with the named rebuttal hypothesis (for example weighted/micro aggregation or denominator ambiguity). Never drop a numeric signal merely because it is not promoted to a Blocker/Major finding.

Allowed optional detail anchors include `id="pdf-page-N"` page anchors and paper-specific compliance sections such as `id="checklist"`. If an optional section carries severity-tagged issues, it must follow the same `data-severity`, linked-finding, caption, scoped-header, and empty-state rules.

For page-level layout rows, suggested columns are `PDF 页`, `严重度`, `版式卡点`, `关联问题`, `下一稿任务`.

When PDF pages are known, include a page anchor:

```html
<a href="#pdf-page-3" class="page-link">PDF p.3</a>
```

These are report-internal anchors, not live jumps into an external PDF viewer unless implemented separately.

## Coverage Receipt

For every substantive Ariadne report, include a coverage receipt table near the end of the report. It must list every visible unit reviewed in the requested scope:

| Unit | Total | Reviewed | With issues | Clean | Skipped | Pending in |
|---|---:|---:|---:|---:|---:|---|

`Skipped` must be `0` for completed scope. If any section is pending because the report is split into parts, mark the report as incomplete and link to the next part rather than implying full coverage.

Coverage claims must be evidence-backed:

- PDF page totals must come from `PDF Coverage Metadata` in the extraction signals, a renderer, or another explicit page-count source. Do not invent `6/6` or similar counts from memory.
- If page count is unavailable, write `page count unknown` and do not claim full-page coverage.
- Layout claims such as "截断", "缺页", "overflow", or "caption separated" require visual/rendered evidence. If the evidence is only suggestive, write `疑似` / `可能` and state the limitation.
- Table/numerical coverage must mention blank cells, placeholder cells, and missing baseline settings separately from arithmetic errors.
- Header/summary counts must be body-backed. If the header says `82 visible sentence notes`, then `#deep-reading-notes [data-note-kind="sentence"]` must contain 82 visible issue rows, or the receipt must say which rows are `pending in <part>`. If the header says `56 visible paragraph rows`, then `#deep-reading-notes [data-note-kind="paragraph"]` must contain 56 visible issue rows or an explicit deferral. Coverage-only artifact counts may appear in the Coverage Receipt, but they should not require a visible duplicate ledger section.

Add a surgery row or companion table summarizing paragraph-level decisions: merged, deleted, split, moved, revised in place, and kept/no-issue counts. This makes paragraph surgery observable without rendering no-op `clean` comments.

Also include a source-principle citation tally such as `notes citing source principles: N/M`.

Include review QA lines:

- `High-risk fields complete: yes/no`
- `Severity audit: N groups checked, M adjusted`
- `Abstract promises tracked: N/N`
- `Rebuttal reverse check: N Blockers checked, M downgraded/qualified`
- `Known blind spots stated: yes/no`
- `Structured artifacts / HTML contract: passed / not produced / needs repair`
- `Numerical signals cited with concrete values: N/N`
- `Coverage consistency: N claims checked, M repaired, 0 unresolved`
- `Polish items: N grouped into K categories`

Include a body-backed count table:

| Claimed unit | Claimed count | Body section / selector | Actual count | Status |
|---|---:|---|---:|---|
| Visible sentence issue notes | N | `#deep-reading-notes [data-note-kind="sentence"]` | N | pass |
| Visible paragraph issue rows | N | `#deep-reading-notes [data-note-kind="paragraph"]` | N | pass |
| Section reflection rows | N | `#deep-reading-notes [data-note-kind="section"]` | N | pass |

Include a Reader-Journey pass receipt, either as a companion table or coverage row:

| Pass | Status | Evidence in report |
|---|---|---|
| Pass 0 engagement contract | done / not applicable / pending | Header + artifact paths + coverage scope |
| Pass 1 cold-start skim | done / not applicable / pending | Claim/evidence audit and skim observations |
| Pass 2 linear deep read | done / not applicable / pending | Deep Reading Notes sentence + paragraph rows |
| Pass 3 section reflection | done / not applicable / pending | Deep Reading Notes section rows |
| Pass 4 whole-paper argument | done / not applicable / pending | Executive Diagnosis / Claim-Evidence / Story Logic |
| Pass 5 submission walk | done / not applicable / pending | Submission Readiness rows |
| Pass 6 output calibration | done / not applicable / pending | Coverage Receipt + audit status |

## Revision Plan

Render the revision plan as an execution table, not a prose recap. The Issue Index already contains diagnosis; the plan should help the author assign work.

Suggested columns:

- `优先级`: `P0`, `P1`, `P2`
- `任务`
- `关联问题`
- `负责人/区域`: Method, Experiments, Evaluation, Writing, Submission, Figures, References, etc.
- `工作量`: `S`, `M`, `L`, or `M/L`
- `验收方式`

Example:

| 优先级 | 任务 | 关联问题 | 负责人/区域 | 工作量 | 验收方式 |
|---|---|---|---|---|---|
| P0 | 修 Eq.(3) / Algorithm / Figure 3 的方法一致性 | F1 / F3 | Method | M | notation/shape table passes; Algorithm and equation agree |
| P0 | 重算 Table 1/2/3/10/11 的 averages、deltas、bold markers | F3a / F3b / F3c | Experiments | M | spreadsheet/script values match rendered PDF |
| P0 | 重填 submission checklist | F5 | Submission | S | every `Yes` has a paper anchor |

Keep plan rows short. If a task repeats an Issue Index diagnosis, replace the repeated text with a linked finding id.

When the report is split across parts, every part includes a partial coverage receipt in its own footer:

- Units covered in this part: full row with total/reviewed/with issues/clean/Skipped=0 for sections, pages, figures, tables, equations, or references as applicable.
- Units handled in other parts: row with the unit name plus `pending in <sibling-filename>.html`; do not fill counts.
- The final part also includes an aggregate total row summing all completed sections.

Never produce a single-part receipt that claims to cover sections deferred to another part.

## PDF Linkage Levels

Use these labels so the report does not overpromise:

- **Level 0: Page anchors in report**. The HTML links to its own PDF page-note sections, e.g. `#pdf-page-3`. This is the default and is easy to implement.
- **Level 1: External PDF open link**. Use Level 1 only when the HTML file and source PDF will be co-located in the same directory, or when the agent can compute a stable relative path between the HTML output file and the PDF. Browser support for opening at a page such as `paper.pdf#page=3` varies; label it as `查看 PDF p.3（浏览器支持因实现而异）` or another clearly best-effort convenience link, not guaranteed sync.
- **Level 2: Embedded PDF viewer**. Requires an actual viewer implementation, such as PDF.js or browser-native embed. Do not claim this unless built.
- **Level 3: Written PDF annotations**. Requires a PDF annotation tool/API such as PyMuPDF, pypdf annotation support, or a platform PDF API. Do not claim comments were written into the PDF unless the tool generated an annotated PDF file and it was checked.

For the current skill, default to Level 0. Mention Level 2/3 only as possible future implementation work unless the user explicitly asks to build it.

## Styling Guidance

Keep the report practical and print-friendly:

- Use a neutral background, high-contrast text, and restrained accent colors by severity.
- Use severity badges with fixed colors: `Blocker` = `#b42318` on `#fff1f0`; `Major` = `#9a6700` on `#fff7df`; `Minor` = `#3451b2` on `#edf2ff`; `Polish` = `#147d64` on `#e9f8f3`.
- Add a shape or text prefix to severity badges when helpful for accessibility, for example `■ Blocker`, `▲ Major`, `● Minor`, `◆ Polish`; do not rely on color alone.
- Make tables horizontally scrollable on small screens by wrapping them in `.table-wrap { overflow-x: auto; }`.
- Give substantive tables a `<caption>` and use `<th scope="col">` for header cells.
- Use sticky table headers for long tables when practical.
- Add optional filters and local navigation for long reports, but show full details by default. Do not default-hide Minor/Polish or teaching-layer rows; students need the local habits too.
- If the user explicitly asks for a compact view, a `Top findings only / 全部细节` toggle may hide non-ledger details, but the default state must be `全部细节` and coverage must remain verifiable.
- Add finding chips such as `<a class="finding-link" href="#F3a">F3a</a>` beside repeated local rows.
- Use an optional issue-type filter when `data-issue-type` is available.
- Add `@media print` rules so the report can be saved as PDF: hide navigation/filter controls, set sticky elements to `position: static`, reduce box shadows, set readable font sizes, and avoid page breaks inside finding cards/tables when practical.
- Avoid animations, remote fonts, or decorative gradients.

Minimum CSS should cover:

- typography and max-width
- severity badges
- finding cards
- responsive tables
- page anchors
- print behavior

## Minimal HTML/CSS Template

Use this as the stable starting point and fill the content. Micro-adjust spacing when needed, but keep the 8-section structure, Chinese labels, severity colors, table wrapper, print rules, self-contained design, and article-order deep-reading organization.

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ariadne 论文线索批注</title>
  <style>
    :root {
      --bg: #f7f8fb; --paper: #ffffff; --ink: #1f2937; --muted: #5f6b7a;
      --line: #d8dee8; --soft: #eef2f7;
      --blocker: #b42318; --blocker-bg: #fff1f0;
      --major: #9a6700; --major-bg: #fff7df;
      --minor: #3451b2; --minor-bg: #edf2ff;
      --polish: #147d64; --polish-bg: #e9f8f3;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; line-height: 1.65; }
    .review-report { max-width: 1180px; margin: 0 auto; padding: 28px; }
    header, nav, section { background: var(--paper); border: 1px solid var(--line); border-radius: 8px; }
    header { padding: 28px; margin-bottom: 16px; }
    nav { position: sticky; top: 12px; padding: 12px 16px; margin-bottom: 16px; }
    nav a { margin-right: 14px; color: #2449a7; text-decoration: none; }
    section { padding: 22px; margin-bottom: 16px; box-shadow: 0 8px 22px rgba(31, 41, 55, .05); }
    h1, h2, h3 { line-height: 1.25; margin: 0 0 10px; }
    p { margin: 8px 0; }
    code { background: #f3f5f8; border-radius: 4px; padding: 1px 5px; }
    .badge { display: inline-flex; align-items: center; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 700; border: 1px solid transparent; }
    .blocker { color: var(--blocker); background: var(--blocker-bg); border-color: #ffd3cf; }
    .major { color: var(--major); background: var(--major-bg); border-color: #f2d98f; }
    .minor { color: var(--minor); background: var(--minor-bg); border-color: #c8d4ff; }
    .polish { color: var(--polish); background: var(--polish-bg); border-color: #bce7d8; }
    .finding { border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin: 12px 0; background: #fbfcfe; break-inside: avoid; }
    .finding-title { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; font-weight: 700; }
    .field { margin: 6px 0; }
    .filters { display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 16px; }
    .filter-btn { appearance: none; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--ink); cursor: pointer; font: inherit; font-weight: 700; padding: 8px 14px; }
    .filter-btn[aria-pressed="true"] { border-color: #2449a7; color: #2449a7; box-shadow: 0 0 0 2px rgba(36, 73, 167, .15); }
    [data-hidden-by-filter="true"] { display: none !important; }
    .empty-state { display: none; color: var(--muted); font-style: italic; }
    section[data-filter-empty="true"] > .empty-state { display: block; }
    .table-wrap[data-filter-empty="true"] .empty-state { display: block; }
    .table-wrap { overflow-x: auto; margin-top: 10px; }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { border: 1px solid var(--line); padding: 9px; vertical-align: top; text-align: left; }
    th { background: var(--soft); }
    thead th { position: sticky; top: 0; z-index: 1; }
    caption { text-align: left; font-weight: 700; margin: 0 0 8px; }
    .finding-link { display: inline-flex; align-items: center; border: 1px solid var(--line); border-radius: 999px; padding: 0 7px; text-decoration: none; color: #2449a7; font-weight: 700; }
    .page-link { color: #2449a7; }
    @media print {
      body { background: #fff; font-size: 11pt; }
      .review-report { max-width: none; padding: 0; }
      nav, .filters { display: none !important; }
      section, header { box-shadow: none; border-color: #bbb; break-inside: avoid; }
      .finding, tr { break-inside: avoid; }
    }
  </style>
</head>
<body>
<article class="review-report">
  <header>
    <h1>Ariadne 论文线索批注</h1>
    <p>论文：<code><!-- paper path/title --></code></p>
    <p>HTML report：<code>ariadne_notes_&lt;stem&gt;_&lt;YYYYMMDD&gt;.html</code></p>
    <p>Artifact bundle：<code>ariadne_notes_&lt;stem&gt;_&lt;YYYYMMDD&gt;/</code></p>
    <p>Reader-Journey passes performed: Pass 0 done; Pass 1 done; Pass 2 done; Pass 3 done; Pass 4 done; Pass 5 done; Pass 6 done.</p>
  </header>
  <nav aria-label="Review sections">
    <a href="#executive-diagnosis">总评诊断与可救骨架</a>
    <a href="#issue-index">问题索引</a>
    <a href="#claim-evidence-audit">主张与证据审计</a>
    <a href="#deep-reading-notes">逐章精读批注</a>
    <a href="#submission-readiness">提交就绪</a>
    <a href="#local-comments">共性问题汇总</a>
    <a href="#revision-plan">修改路线</a>
    <a href="#coverage-receipt">覆盖回执</a>
  </nav>
  <div class="filters" aria-label="Severity filters">
    <button class="filter-btn" type="button" data-filter="all" aria-pressed="true">全部</button>
    <button class="filter-btn" type="button" data-filter="blocker" aria-pressed="false">Blocker</button>
    <button class="filter-btn" type="button" data-filter="major" aria-pressed="false">Major</button>
    <button class="filter-btn" type="button" data-filter="minor" aria-pressed="false">Minor</button>
    <button class="filter-btn" type="button" data-filter="polish" aria-pressed="false">Polish</button>
  </div>
  <main>
    <section id="executive-diagnosis"><h2>总评诊断与可救骨架</h2><!-- 一句话 verdict / 论文类型契约 / 最大风险 / 可救骨架 --></section>
    <section id="issue-index"><h2>问题索引</h2><!-- canonical finding cards + ledger table --></section>
    <section id="claim-evidence-audit"><h2>主张与证据审计</h2><!-- abstract promise / claim-evidence / red-team --></section>
    <section id="deep-reading-notes"><h2>逐章精读批注</h2>
      <section class="paper-section" id="sec-introduction">
        <h3>1. Introduction</h3>
        <div class="table-wrap"><table><caption>Section reflection</caption><thead><tr><th scope="col">读后一句话</th><th scope="col">章节任务是否对齐</th><th scope="col">建议结构</th><th scope="col">未闭合问题</th><th scope="col">关联问题</th><th scope="col">下一稿任务</th></tr></thead><tbody><tr data-note-kind="section" data-severity="major"><td><!-- summary --></td><td><!-- alignment --></td><td><!-- skeleton --></td><td><!-- loops --></td><td><!-- e.g. <a class="finding-link" href="#F1">F1</a>, only if F1 exists in Issue Index --></td><td><!-- task --></td></tr></tbody></table><p class="empty-state">该表无此严重度项</p></div>
        <div class="table-wrap"><table><caption>Paragraph and sentence notes</caption><thead><tr><th scope="col">层级</th><th scope="col">位置</th><th scope="col">检查维度 / 当前任务</th><th scope="col">原句/片段</th><th scope="col">读者卡点 / 为什么</th><th scope="col">违反原则</th><th scope="col">关联问题</th><th scope="col">下一稿任务 / 自改问题</th><th scope="col">严重度 / 处理决定</th></tr></thead><tbody><tr data-note-kind="paragraph" data-severity="major" data-decision="merge"><td>段落</td><td>Intro ¶1</td><td><!-- current job --></td><td></td><td><!-- paragraph friction --></td><td><!-- principle --></td><td><!-- linked finding id, if defined --></td><td><!-- task --></td><td>合并</td></tr><tr data-note-kind="sentence" data-severity="major"><td>句子</td><td>Intro ¶1 S1</td><td>sentence flow</td><td><!-- snippet --></td><td><!-- reader friction --></td><td><!-- principle --></td><td><!-- linked finding id, if defined --></td><td><!-- self-revision task --></td><td><span class="badge major">▲ Major</span></td></tr></tbody></table><p class="empty-state">该表无此严重度项</p></div>
      </section>
    </section>
    <section id="submission-readiness"><h2>数字 / 公式 / 图表 / 版式 / 提交就绪</h2><!-- numbers / equations / figures / PDF pages / references / checklist / polish sweep --></section>
    <section id="local-comments"><h2>共性问题汇总</h2><!-- recurring writing habits, no repeated full diagnoses --></section>
    <section id="revision-plan"><h2>修改路线</h2><!-- execution table near the end --></section>
    <section id="coverage-receipt"><h2>覆盖回执与 artifacts</h2><!-- Pass 0-6 receipt + body-backed counts + artifact paths --></section>
  </main>
</article>
<script>
  function applyFilters() {
    const severity = document.querySelector("[data-filter][aria-pressed='true']").dataset.filter;
    document.querySelectorAll("[data-severity]").forEach((node) => {
      const show = severity === "all" || node.dataset.severity === severity;
      node.dataset.hiddenByFilter = show ? "false" : "true";
    });
    document.querySelectorAll("main > section").forEach((section) => {
      const items = Array.from(section.querySelectorAll("[data-severity]"));
      const hasFilterableItems = items.length > 0;
      const hasVisibleItems = items.some((item) => item.dataset.hiddenByFilter !== "true");
      section.dataset.filterEmpty = String(severity !== "all" && hasFilterableItems && !hasVisibleItems);
    });
    document.querySelectorAll(".table-wrap").forEach((wrap) => {
      const rows = Array.from(wrap.querySelectorAll("tbody tr[data-severity]"));
      const hasRows = rows.length > 0;
      const hasVisibleRows = rows.some((row) => row.dataset.hiddenByFilter !== "true");
      wrap.dataset.filterEmpty = String(severity !== "all" && hasRows && !hasVisibleRows);
    });
  }
  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      applyFilters();
    });
  });
</script>
</body>
</html>
```

## Output Instructions

When creating a file, use the platform's normal file-writing tool, for example Codex `apply_patch` or Claude Code `Write`. Do not paste the full HTML body into the chat response; reference the saved file by absolute path.

If the user provides an explicit output path, honor it. If the path is relative, resolve it against the current working directory and report the resolved absolute path.

If no output path is provided, save the HTML report next to the primary reviewed artifact:

```text
<paper-directory>/ariadne_notes_<safe-paper-stem>_<YYYYMMDD>.html
```

Choose the directory and stem as follows:

- PDF-only input: use the PDF's directory and PDF stem.
- LaTeX input with a compiled/rendered PDF: use the compiled PDF's directory and stem.
- LaTeX input without a PDF: use the selected entry `.tex` file's directory and stem.
- Both PDF and LaTeX provided: use the PDF that is treated as the rendered review artifact.

`safe-paper-stem` is the PDF/TeX stem with characters outside `[A-Za-z0-9_.-]` replaced by `_`, stripped of leading/trailing `_`, falling back to `paper`. Append the local review date as `_YYYYMMDD`; this is canonical so repeated reviews of the same paper do not overwrite each other and calibration runs can compare dated artifacts. Add a short suffix such as `_1` or `_hash6` only when needed to avoid overwriting a same-day report or to disambiguate colliding artifact names.

Example:

```text
/path/to/paper/ariadne_notes_emnlp2026.html
/path/to/paper/ariadne_notes_emnlp2026_20260516.html
```

This co-location is intentional: when a PDF is available, prefer Level 1 best-effort links such as `emnlp2026.pdf#page=3` because the HTML and PDF live in the same directory. If the artifact directory is not writable, explain that limitation and ask for an explicit output path or use the nearest writable user-approved fallback.

In the final response, provide the absolute path to the HTML file and state whether PDF linkage is Level 0, 1, 2, or 3.

## Multi-Part Outputs

When the requested Ariadne scope produces more material than fits in one HTML file, split the report into parts. Chunking preserves coverage; it must not be used as a reason to drop sections or summarize away per-paragraph notes.

Suggested split:

- `ariadne_notes_<stem>_<YYYYMMDD>_part1.html`: paper-level findings plus Abstract/Introduction deep-reading notes.
- `ariadne_notes_<stem>_<YYYYMMDD>_part2.html`: Related Work/Method/Experiments deep-reading notes.
- `ariadne_notes_<stem>_<YYYYMMDD>_part3.html`: Figures/Captions, Conclusion, references, source hygiene, and coverage receipt.

Each part should include the same main navigation and relative sibling links, such as `ariadne_notes_<stem>_<YYYYMMDD>_part2.html#deep-reading-notes`. Each part must include the partial coverage receipt described above. Never produce a single part that silently omits paragraphs to fit the file.
