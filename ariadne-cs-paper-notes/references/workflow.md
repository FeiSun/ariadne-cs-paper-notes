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

## Context Discipline

Source text is read at most once per representation level:

- `*.review_units.md` / `*.review_units.jsonl`: Prose Review Agent Phase A input. Generate these from the canonical `<stem>.source.html` with `scripts/extract_review_units.py` and read this compact text view instead of rendered HTML.
- `source.html`: rendering and anchor-validation base only. Do not read `<stem>.source.html`, `<stem>.html`, or any rendered HTML report back into model context for prose review or verification. Use audit scripts for verification.
- LaTeX source: source-level diagnostics only, such as macros, citations, labels, build hygiene, hidden comments, and checklist/source package issues. Prefer source-hygiene issue artifacts over reading large source spans in orchestration context.
- Raw audits such as `layout_audit.json`, `references_audit.json`, `numeric_audit.json`, symbol audits, polish audits, and full PDF text dumps are `tool_only`: specialist agents or deterministic reducers may read them; the top-level orchestrator and Prose Phase B read only compact `*_issues.json` derivatives.
- PDF pages: layout track only. Do not mix page images into the main sentence-by-sentence prose-review context. Page images may be checked by page-local tooling or a layout specialist; the orchestrator consumes only `layout_issues.json`, aggregate coverage, and audit stdout.

Do not create duplicate paper-text dumps in the paper directory. Avoid `main_pdftotext.txt`, `paper.txt`, `*.source_preview.html`, `*_preview.html`, and bundle-local generated helper scripts. Use temp extraction outputs and the canonical `<stem>.source.html` / `<stem>.html` pair.

## Agent Architecture

Full-paper Ariadne runs use three roles:

- **Orchestrator**: fixes scope, runs deterministic extraction, launches specialists, collects issue artifacts, runs compilers/renderers/audits, and reports saved paths. It does not read full paper text, raw audits, or generated HTML.
- **Prose Review Agent**: the only agent that reads the full `review_units` view for typical full-paper prose critique. It handles the paper's narrative, sentence/paragraph/section reasoning, and whole-paper claim/evidence synthesis.
- **Specialist Agents**: isolated sidecars for layout, numeric/table checks, references, symbol/term consistency, source hygiene/anonymity, figure/caption checks, and polish. Each reads its own raw audit and writes a curated issue artifact.

Specialists are conditional. Skip a specialist when the input signal is absent, such as no rendered PDF for layout, `numeric_audit.signal_count == 0` for numeric, no `.bib`/`.bbl`/`.aux` for references, no figures/tables/captions for figure/caption, or no notation-heavy content for symbols. If downstream tooling expects a file, write an empty issue artifact with coverage and skip reason rather than making the orchestrator infer absence.

## Prose Review Phases

The Prose Review Agent has two calls for full-paper work:

### Phase A -- Full-Prose Deep Read

Input: complete `review_units.md` / `review_units.jsonl` plus workflow and review lenses.

Work: Pass 1 cold skim, Pass 2 linear sentence/paragraph deep read, and Pass 3 section reflections. Preserve whole-paper continuity; do not section-shard typical 30-50 page CS papers unless token estimates exceed the available context.

Outputs are JSON/JSONL only and should be written incrementally in article order:

- `cold_skim_frame.json`
- `prose_issues.jsonl`
- `paragraph_decisions.jsonl`
- `section_reflections.json`
- `claim_candidates.json`

Incremental writing is required for robustness. After completing each section's Pass 2-3 work, the Prose Review Agent must invoke a file edit/write tool before continuing: append that section's rows to `prose_issues.jsonl` and `paragraph_decisions.jsonl`, then update `section_reflections.json`. Do not buffer multiple sections in working memory and emit them only at the end. On resume, the orchestrator checks completed section ids and asks the Prose Review Agent to continue only missing sections.

Use `scripts/phase_a_resume_status.py` to build the compact resume state:

```bash
scripts/phase_a_resume_status.py \
  --review-units <stem>.review_units.jsonl \
  --prose-issues <bundle>/issue_artifacts/prose_issues.jsonl \
  --paragraph-decisions <bundle>/paragraph_decisions.jsonl \
  --section-reflections <bundle>/section_reflections.json \
  --out <bundle>/phase_a_resume_status.json \
  --next-out <bundle>/phase_a_next_step.json
```

The orchestrator should read only `phase_a_resume_status.json` and, for the next prompt packet, `phase_a_next_step.json`; it should not read the full completed Phase A JSONL shards when deciding where to continue.

If the full review units exceed the context threshold, use section-sharded Phase A and record the split in coverage. `scripts/build_prose_shards.py` writes `phase_a_shard_manifest.json` plus per-shard packets under `phase_a_shards/`. A later synthesis pass is mandatory; do not deliver independent section reviews as a substitute for whole-paper judgment.

`scripts/run_prose_agent.py` is the optional execution wrapper for Phase A/B. It does not hard-code a model provider. Pass `--agent-cmd "<command>"`; the command receives `ARIADNE_PROMPT_PACKET`, `ARIADNE_BUNDLE`, and `ARIADNE_ISSUE_ARTIFACTS`, then writes the JSON/JSONL targets named in the packet. Use `--allow-incomplete` when it is called from the top-level pipeline so a pending Phase A checkpoint is not treated as a failed deterministic stage. The runner stops on `no_progress` when an agent exits successfully but does not advance resume status or write-target counts.

For sharded Phase A, pass `--shard-manifest <bundle>/phase_a_shard_manifest.json` to `run_prose_agent.py`. The runner executes shard packets in manifest order and skips shards whose sections are already complete.

### Phase B -- Whole-Paper Synthesis and Cross-Domain Integration

Input: `phase_b_context.json`, not full review units. A deterministic compactor such as `build_phase_b_input.py` should build this file from `cold_skim_frame.json`, `section_reflections.json`, `claim_candidates.json`, and all curated `*_issues.json`. The schema is defined in `report_contract.md`; Phase B should not re-read full section reflections or raw specialist audits to make its own compact view.

Work: Pass 4 whole-paper argument red-team plus integration of specialist issues into the central claim/evidence story. Ask whether numeric, reference, layout, symbol, source-hygiene, figure/caption, or polish issues change acceptability, claim strength, or reader trust.

Outputs are JSON/JSONL only:

- `argument_map.json`
- `claims.json`
- `salvageable_core.json`
- `whole_paper_findings.jsonl`

Phase B may add cross-section findings. Such findings must use multiple anchors when needed, not a misleading single sentence anchor.

## Deterministic Specialists

Use these reducers before compilation when the corresponding inputs exist:

```bash
scripts/run_p1_specialists.py --bundle <bundle> --tex <main.tex> --pdf <main.pdf> --aux <main.aux> --bbl <main.bbl>
```

The runner is the preferred orchestrator entry point. It reuses existing raw audits unless `--force` is passed, writes skipped stubs for unavailable domains, and prints only compact status plus a `p1_specialists_summary.json` path.

Equivalent manual commands:

```bash
scripts/check_page_layout.py <paper.pdf> --out <bundle>/layout_audit.json
scripts/extract_paper_text.py <paper.pdf> --numeric-json <bundle>/numeric_audit.json
scripts/check_references.py <main.tex> --aux <main.aux> --bbl <main.bbl> --out <bundle>/references_audit.json
scripts/check_source_hygiene.py <main.tex> --out <bundle>/source_hygiene_audit.json
scripts/check_polish.py <main.tex> --out <bundle>/polish_audit.json
scripts/check_symbol.py <main.tex> --out <bundle>/symbol_audit.json
scripts/check_figure_caption.py <main.tex> --pdf <main.pdf> --out <bundle>/figure_caption_audit.json

scripts/build_specialist_issues.py --domain layout --raw-audit <bundle>/layout_audit.json --out <bundle>/issue_artifacts/layout_issues.json
scripts/build_specialist_issues.py --domain numeric --raw-audit <bundle>/numeric_audit.json --out <bundle>/issue_artifacts/numeric_issues.json
scripts/build_specialist_issues.py --domain reference --raw-audit <bundle>/references_audit.json --out <bundle>/issue_artifacts/reference_issues.json
scripts/build_specialist_issues.py --domain source_hygiene --raw-audit <bundle>/source_hygiene_audit.json --out <bundle>/issue_artifacts/source_hygiene_issues.json
scripts/build_specialist_issues.py --domain polish --raw-audit <bundle>/polish_audit.json --out <bundle>/issue_artifacts/polish_issues.json
scripts/build_specialist_issues.py --domain symbol --raw-audit <bundle>/symbol_audit.json --out <bundle>/issue_artifacts/symbol_issues.json
scripts/build_specialist_issues.py --domain figure_caption --raw-audit <bundle>/figure_caption_audit.json --out <bundle>/issue_artifacts/figure_caption_issues.json
```

These reducers are deterministic P1 fallbacks for specialist agents. They emit completed issue artifacts when real issues exist and skipped stubs when the raw audit has no actionable signals. The figure/caption reducer can run from source only; passing the rendered PDF adds caption geometry checks, and local raster or previewable PDF figure assets add basic readability/quality checks, without exposing page images or raw layout dumps to the orchestrator.

Optional LLM specialist refinement runs after these deterministic reducers:

```bash
scripts/run_specialist_agent.py --issues-dir <bundle>/issue_artifacts --agent-cmd "<specialist command>" --audit
```

The command receives `ARIADNE_SPECIALIST_PACKET`, `ARIADNE_SPECIALIST_DOMAIN`, `ARIADNE_SPECIALIST_INPUT`, and `ARIADNE_SPECIALIST_OUTPUT`. By default it reads only curated `*_issues.json` files, not raw audits. If a future specialist truly needs raw audit evidence, extend the packet explicitly and keep the raw audit isolated from the orchestrator.

## Top-Level Coordinator

For ordinary runs, prefer the deterministic coordinator:

```bash
scripts/run_review_pipeline.py <main.tex-or-project> --bundle <bundle>
```

It prepares/builds the PDF when possible, renders source HTML, extracts review units, runs deterministic specialists, writes `phase_a_resume_status.json`, `phase_a_next_step.json`, and `phase_a_prompt_packet.json`, and then stops if Prose Phase A/B artifacts are missing. When Phase A artifacts exist, it also writes `phase_b_context.json` and `phase_b_prompt_packet.json`. After the Prose agents have written their JSON/JSONL artifacts, rerun the same command to compile, derive, render, and audit. Use `--allow-partial-compile` only for debugging or specialist-only previews; partial compile output must not be presented as a full-paper prose review.

For final compiled reports, the coordinator calls `render_paper_html.py` with `--reuse-raw-html --full-report` so the final overlay uses the exact canonical source HTML that generated `review_units`. This prevents sentence anchors from changing between Prose Phase A and final rendering. The renderer emits the workbench sections deterministically from JSON artifacts; agents must not write HTML.

If a vision-capable figure/caption specialist is available, pass `--vision-figure-agent-cmd "<command>"`. The runner creates tool-only page images and a compact vision packet; only the curated `figure_caption` issue artifact and compact runner summary should enter orchestration context.

## Deterministic Compilation

After Phase A, Phase B, and conditional specialists have written their issue artifacts, run:

```bash
scripts/compile_review_artifacts.py \
  --issues-dir <bundle>/issue_artifacts \
  --findings-out <bundle>/findings.json \
  --annotations-out <bundle>/annotations.json \
  --index-out <bundle>/issue_artifacts/compiled_issue_index.json
```

The compiler normalizes `prose_issues.jsonl`, `whole_paper_findings.jsonl`, and specialist `*_issues.json` files into final `F<number>` findings and anchor-only annotations. It preserves `source_issue_ids`, records normalized JSONL shards in `compiled_issue_index.json`, and applies the conservative dedup rules in `report_contract.md`. Review agents should not perform this merge in model context.

## Deterministic Derivatives

After compilation, derive mechanical companion artifacts instead of asking an LLM to count or write them:

```bash
scripts/build_review_derivatives.py \
  --findings <bundle>/findings.json \
  --annotations <bundle>/annotations.json \
  --issues-dir <bundle>/issue_artifacts \
  --layout-audit <bundle>/layout_audit.json \
  --source-artifact <stem>.source.html \
  --requested-scope "<scope>" \
  --output-file <stem>.html \
  --coverage-out <bundle>/coverage.json \
  --manifest-out <bundle>/render_manifest.json \
  --pass-observations-out <bundle>/pass_observations.json
```

The derivative builder writes `coverage.json`, `render_manifest.json`, and `pass_observations.json` from compiled artifacts and issue artifacts. It should be the default path for these files; manual versions are only acceptable when the derived script cannot express an unusual split-part run, and they must still pass artifact audit.

## Artifact Workflow

1. Identify input type: LaTeX project, single `.tex`, compiled/rendered PDF, PDF-only paper, excerpt, figures/tables, or submission package.
2. Extract material when files are provided:
   - Prefer `scripts/extract_paper_text.py <paper-path>`.
   - By default it writes private temp output and prints `Wrote signals to <path>` on stderr; read that path.
   - Use `--max-items` high enough for all visible sections, captions, equations, references, and numeric signals in scope. If extraction reports incomplete coverage, rerun with a larger value before claiming full coverage.
   - For LaTeX/source input, identify the entry `.tex`; compile or locate a rendered PDF with `scripts/build_paper_pdf.py <paper-path>` when local tools allow.
   - If compilation fails, report the warning and continue source-only; ask for the PDF when layout matters.
   - For paper-reader prose review, render the canonical source HTML, then run `scripts/extract_review_units.py <stem>.source.html`; use review units as the Prose Phase A model-facing paper text.
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

In the new artifact flow, Pass 1 is part of Prose Phase A and writes `cold_skim_frame.json`.

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

In the new artifact flow, Pass 2 is part of Prose Phase A and writes `prose_issues.jsonl` plus `paragraph_decisions.jsonl`. Cross-section prose problems may use `target_anchors` and `spans_sections: true`.

### Pass 3 -- Section Reflection

After each visible section, record:

- `读后一句话`
- `章节任务是否对齐`
- `建议结构`: 3-6 step skeleton
- `未闭合问题`
- `关联问题`
- `下一稿任务`

For experiments, include numerical sanity, figure/table readability, caption takeaway, baseline fairness, and whether each result answers a research question. For Related Work, judge whether it builds coordinates leading to the gap or merely lists prior papers.

In the new artifact flow, Pass 3 is part of Prose Phase A and writes `section_reflections.json`.

### Pass 4 -- Whole-Paper Argument

Zoom out:

- central claim and paper type/review contract;
- abstract promise tracking;
- claim-evidence map;
- title/abstract/introduction/conclusion alignment;
- story logic red-team and likely reviewer attacks;
- salvageable core after fixing Blockers/top Majors.

In the new artifact flow, Pass 4 is Prose Phase B. It reads `phase_b_context.json` and curated specialist issues, not full raw audits.

### Pass 5 -- Submission Walk

Run the hard artifact walk:

- numerical/table arithmetic and table completeness;
- formula, symbol, algorithm, notation consistency;
- figures, captions, visual dictionary;
- PDF/page layout as a separate page-level audit track;
- references, citations, bibliography style;
- placeholders, TODOs, anonymity, checklist, venue compliance, reproducibility, source hygiene;
- mechanical polish sweep.

In the new artifact flow, Pass 5 is performed by conditional specialists. They output only reportable `*_issues.json` artifacts. The orchestrator and Prose Phase B consume those curated issue files, not the raw audit files.

For layout, distinguish prose coverage from visual coverage:

- Full sentence-by-sentence prose coverage does not imply full visual page coverage.
- Each rendered page is an independent layout unit. Check for orphan/widow lines, isolated words, large blank areas, float order, figure/table/caption placement, overfull content, broken equations, and appendix/checklist rhythm.
- For any PDF layout claim, first run `scripts/check_page_layout.py <pdf> --pages <range> --out <bundle>/layout_audit.json`. The layout specialist reduces it to `layout_issues.json`; each issue must reference a real `layout_audit.json` observation id rather than replacing the script provenance.
- Keep the referenced PDF available next to the artifacts or by a stable repo/absolute path; artifact audit replays `check_page_layout.py` and rejects layout audits it cannot reproduce.
- The orchestrator does not read `layout_audit.json` wholesale. Only the layout specialist may inspect raw observations and page images, and only for escalated, ambiguous, or high-risk pages.
- Record layout coverage separately in `coverage.json`: `pages_total`, `pages_checked`, `pages_escalated`, `pages_sampled`, and `full_layout_coverage`. If only sampled pages were checked, do not claim full layout coverage; if every page was checked by a page-local process, full layout coverage may be true without feeding every image into the main context.

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

In the new artifact flow, Pass 6 is audit-driven. The orchestrator reads compact stdout from `audit_html_report.py`, `audit_review_artifacts.py`, and specialist artifact audits, then reruns only the failing compiler/renderer/specialist steps. Do not read full HTML or raw audits to debug unless the compact error identifies a specific small file span.

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
