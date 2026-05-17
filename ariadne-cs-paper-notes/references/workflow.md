# Ariadne Workflow

Use this file for every substantive CS/AI paper critique. It defines how to run the review; use `review_lenses.md` for what to look for, `report_contract.md` for what to render/save, `html_contract.md` for HTML, and `numeric_contract.md` for strict table/number handling.

## Scope, Not Depth

Ariadne has one depth standard: highest-coverage senior-advisor critique of the requested visible scope. The user may narrow scope to a full paper, section, paragraph, page range, figure, table, PDF layout, source tree, or submission package; do not lower depth inside that scope.

Do not sample silently. If the paper or output is too large, split the review into explicit parts and mark pending sections/pages/artifacts. Units without substantive issues are counted in the coverage receipt, not rendered as visible `clean` rows.

For partial inputs, state missing context and review the local job fully:

- abstract: story slots, result precision, claim strength
- introduction: problem/gap/idea/evidence/boundary path
- method: map, definitions, novelty, notation, reproducibility
- experiments: evidence chain, baselines, metrics, budgets, variance, ablations, failures
- figures/tables: claim, caption, readability, numeric sanity
- PDF/layout: rendered page rhythm and visual hierarchy

## Artifact Workflow

1. Identify input type: LaTeX project, single `.tex`, compiled/rendered PDF, PDF-only paper, excerpt, figures/tables, or submission package.
2. Extract material when files are provided:
   - Prefer `scripts/extract_paper_text.py <paper-path>`.
   - By default it writes private temp output and prints `Wrote signals to <path>` on stderr; read that path.
   - Use `--max-items` high enough for all visible sections, captions, equations, references, and numeric signals in scope. If extraction reports incomplete coverage, rerun with a larger value before claiming full coverage.
   - For LaTeX/source input, identify the entry `.tex`; compile or locate a rendered PDF with `scripts/build_paper_pdf.py <paper-path>` when local tools allow.
   - If compilation fails, report the warning and continue source-only; ask for the PDF when layout matters.
3. For PDF, use page numbers and short snippets. The rendered PDF is authoritative for layout, skimmability, figure/table readability, page breaks, and actual reader experience.
4. Plain text extraction strips layout. Do not use `extract_paper_text.py` or `pdftotext` alone as evidence for layout judgments; visually inspect/render PDF pages when judging layout.
5. For visible tables or prose-cited numbers, run numeric extraction before drafting numeric findings:
   `scripts/extract_paper_text.py <paper> --numeric-json <bundle>/numeric_audit.json`
6. Treat deterministic scripts as evidence signals, not final judgments. Use them to make notes concrete, then decide severity from manuscript context and the relevant contract files.

## Reader-Journey Passes

Run these passes internally. Render externally in the workbench order from `report_contract.md`.

### Pass 0 -- Engagement Contract

Before reading, fix:

1. requested scope;
2. input artifacts;
3. output language and format;
4. output paths, including HTML and JSON bundle when applicable;
5. coverage standard: no sampling inside requested visible scope.

Record missing artifacts and known blind spots up front.

### Pass 1 -- Cold-Start Skim

Simulate a busy first-day reviewer. Read title, abstract, section openers, figures/tables/captions, and conclusion before the linear read. Record what problem, gap, idea, result, and boundary are recoverable, and where the story breaks.

Do not use later full-text knowledge to forgive a missing title/abstract/caption/section-opener signal.

### Pass 2 -- Linear Deep Read

Read in article order. For each section and paragraph, check sentences first, then reflect on the paragraph immediately.

For every sentence in the requested visible prose scope, check:

1. grammar, syntax, and mechanics;
2. diction, naturalness, precision, concision, and deletion-worthy redundancy;
3. ambiguity: referent, modifier, scope, comparator, metric, condition, evidence strength;
4. sentence flow: old-new order, connector truth, stress position, emphasis;
5. cognitive load: new terms, metrics, formulas, concepts without intuition;
6. missing why/how/referent: unstated causal or logical steps.

Every substantive sentence issue becomes a row under its paragraph in **Deep Reading Notes**. Clean sentences count only in coverage.

After each paragraph, decide: `保留`, `原位修改`, `合并`, `拆分`, `移动`, or `删除`. Ask whether the paragraph has one job, whether the topic sentence works, whether it belongs here, and what structural task the next draft must complete.

### Pass 3 -- Section Reflection

After each visible section, record:

- `读后一句话`
- `章节任务是否对齐`
- `建议结构`: 3-6 step skeleton
- `未闭合问题`
- `关联问题`
- `下一稿任务`

For experiments, include numerical sanity, figure/table readability, caption takeaway, baseline fairness, and whether each result answers a research question. For Related Work, judge whether it builds coordinates leading to the gap or merely lists prior papers.

### Pass 4 -- Whole-Paper Argument

Zoom out:

- central claim and paper type/review contract;
- abstract promise tracking;
- claim-evidence map;
- title/abstract/introduction/conclusion alignment;
- story logic red-team and likely reviewer attacks;
- salvageable core after fixing Blockers/top Majors.

### Pass 5 -- Submission Walk

Run the hard artifact walk:

- numerical/table arithmetic and table completeness;
- formula, symbol, algorithm, notation consistency;
- figures, captions, visual dictionary;
- PDF/page layout for every rendered page in requested scope;
- references, citations, bibliography style;
- placeholders, TODOs, anonymity, checklist, venue compliance, reproducibility, source hygiene;
- mechanical polish sweep.

For numeric details, use `numeric_contract.md`. If a manuscript has visible tables but no `numeric_audit.json`, mark table arithmetic coverage incomplete rather than claiming it.

### Pass 6 -- Output Calibration

Audit the report:

1. deduplicate findings into one canonical Issue Index;
2. check severity consistency and rebuttal reverse checks;
3. verify linked finding ids;
4. ensure numeric findings include reported value, visible computed value, delta, and caveat;
5. cross-check header/coverage counts against body rows;
6. ensure the revision plan is executable;
7. run HTML/artifact audits when files are produced;
8. fix every audit `ERROR` before delivery.

## QA Gates

Run these before delivery and record compact status in the Coverage Receipt.

### Output QA Gate

- High-risk field check: every `Blocker`/`Major` has required inspectability fields.
- Unsupported-claim check: separate visible manuscript facts from reviewer inference.
- Coverage check: do not claim pages/sections/objects not inspected.
- HTML contract check: if HTML exists, every severity-badged issue has `data-severity`; filters work or are static legend; no unimplemented PDF sync is promised.
- Tool-boundary check: scripts are cited as signals/evidence, not verdicts.
- Blind-spot check: missing source, code, data, seed results, venue rules, or visual resolution are stated.
- Workbench structure check: full reports use the canonical 8-section order.
- Body-backed count check: every header/summary/coverage count is backed by visible body rows or explicit pending marker.
- Verdict calibration check: deterministic errors use concrete directive language.

### Coverage Consistency Gate

List each quantitative coverage claim in the header, summary band, body, and Coverage Receipt. Match it to a body selector or artifact-backed count, such as:

- `#deep-reading-notes [data-note-kind="sentence"]`
- `#deep-reading-notes [data-note-kind="paragraph"]`
- `#deep-reading-notes [data-note-kind="section"]`
- `#submission-readiness [data-issue-type="numeric"]`
- `#coverage-receipt`

Fix mismatches by adding missing rows, correcting counts, or splitting the report. Record: `Coverage consistency: N claims checked, M repaired, 0 unresolved`.

### Severity Consistency Audit

Group findings by problem type, compare severities within each group, and either state the discriminating factor or adjust severity. Record: `Severity audit: N finding groups checked, M adjusted`.

### Rebuttal Reverse Check

For every `Blocker`, imagine the strongest reasonable author response. Could visible text, table, appendix, source, or venue rule already answer it? Would one clarification or aggregation explanation lower severity? Is it inference-only?

If the rebuttal stands, downgrade or qualify. If not, use it to sharpen `downgrade_condition`. Numeric rebuttals must quantitatively explain gaps; generic "weighted aggregation may explain it" is not enough unless the manuscript gives denominator/weights or the magnitude is plausibly rounding-level.

## Known Blind Spots

Use these in findings, caveats, and coverage:

- Without code, data, logs, or seed-level results, Ariadne cannot verify reproducibility or statistical significance.
- Without seed-level/per-example results, table arithmetic checks visible-cell consistency only; macro/micro/weighted aggregation may remain ambiguous.
- PDF layout comments are limited by rendered pages and available visual resolution. Mark uncertain visual issues as `疑似` / `possible`.
- Identity/anonymity checks surface visible signals; they do not prove a real identity.
- Venue compliance changes. If official rules are not provided or checked, say compliance cannot be fully verified.
- For PDF-only input, source-level macros, hidden comments, buildability, and `.bib` fields are unavailable.

## Final Response

For saved HTML reports, do not paste the full HTML. Give absolute paths and PDF linkage level using the block in `SKILL.md`. If tests/audits could not be run, say so.
