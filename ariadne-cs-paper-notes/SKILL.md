---
name: ariadne-cs-paper-notes
description: "Ariadne-style critique for CS/AI research-paper drafts (LaTeX source, compiled/rendered PDF, or excerpts): a senior-advisor thread through the paper's labyrinth of claim, evidence, structure, narrative, contribution framing, sentence/paragraph/section clarity, PDF/layout, figures/tables/captions, and submission readiness. This skill gives diagnostic notes, reader-stuck points, source-principle explanations, paragraph surgery decisions, and Chinese HTML annotation reports; it gives the author a thread to revise with, not paper-ready prose rewrites. Trigger when the user asks to critique, review, red-team, annotate, revise, 审阅, 批注, 红队评审, 给审稿意见, 检查论文, 修改论文, 认真批注, 像老师一样改, 细致改一下, 帮我改句子, 红笔批注, HTML批注, or review a research paper or paper section."
---

# Ariadne CS Paper Notes

## Overview

Use this skill to critique CS/AI paper drafts against Ofey's paper-writing principles. Ariadne's image is the thread through a labyrinth: this skill should give students a thread of diagnostic notes, questions, and reader-stuck points so they can find their own way through the paper's argument, structure, narrative, contribution expression, and evidence. It is not a generic proofreading or ghost-writing skill. Review like a senior advisor who helps the author see where the paper fails a first-day reader; do not walk the maze for them by producing paper-ready prose.

The default voice is teaching, not verdict. Use severity labels to prioritize work, but frame notes as `读者卡点 -> 违反原则 -> 下一稿任务`: where the reader gets stuck, which writing principle is violated, and what job the student must complete in the next draft. Avoid bare "desk reject" language unless discussing actual submission risk, and even then explain the reader-trust mechanism behind it.

## Trigger Discipline

Use this skill only for research-paper review tasks: critique, red-team review, advisor-style comments, claim-evidence diagnosis, structure review, precision/flow review, figure/table/caption critique, or submission-readiness feedback.

Do not use it for ordinary English polishing, translation, emails, blogs, grant text, or generic academic editing unless the user explicitly asks to apply these CS paper-writing principles.

When the user asks for "editing" or "revision", treat it as critique and annotation by default: diagnose before any wording suggestion, and do not produce paper-ready prose rewrites inside this skill. Preserve the author's evidence strength; do not silently upgrade claims, invent results, invent citations, or make the story stronger than the manuscript supports.

## Required Reference

Load `references/reviewer_checklist.md` for the default Reader-Journey Workflow, Ariadne Coverage Standard, source-principle index, reviewer stances, checklist tools, output structure, severity labels, comment style, and canonical Diagnostic Note Triggers list.

Load `references/html_report.md` when the user asks for HTML, 网页, 可视化报告, 批注报告, or a structured review file.

Do not routinely load the original teaching notes. This skill intentionally uses a reviewer-facing checklist instead of long student-facing explanations. If the user explicitly asks to revise the skill itself from the original writing tips, use the source files outside this skill folder.

## Review Scope, Not Depth

Ariadne has one review standard: highest-coverage senior-advisor critique of the requested visible scope. Do not choose a lighter depth because the user says only "批注一下", "修改意见", "认真看看", or "review this". The scope may vary; the standard does not.

Scopes are not mutually exclusive. When a request spans multiple scopes, such as "full-paper HTML annotation report on this PDF" or "LaTeX + compiled PDF + submission readiness", apply the union of all relevant scope requirements and report each coverage dimension separately.

- **Full-paper scope**: run the full Reader-Journey Workflow: engagement contract, cold-start skim, linear deep read with sentence checks and paragraph reflection, section reflection, whole-paper argument, submission walk, and output calibration. Render story diagnosis, finding ledger, claim-evidence audit, article-ordered deep reading notes, submission-readiness notes, local patterns, revision plan, and coverage receipt.
- **Focused section/paragraph scope**: run the same standard on the visible scope. Inspect every sentence and paragraph in that scope; include paragraph decisions, source-principle explanations, issue rows for substantive issues, and a local coverage receipt. Do not render `clean` / no-issue rows in student-facing notes; no-issue units are represented only by coverage counts. Omit only paper-level outputs that the input cannot support.
- **First-page scope**: fully inspect title, abstract, introduction opening/ending, Figure 1 when visible, and recoverability of What / Why / Gap / Idea / Evidence / Boundary.
- **Experiment scope**: fully inspect research questions, evidence alignment, baselines, fairness, metrics, budgets, variance, ablations, trade-offs, failure cases, limitations, numerical sanity, and figure/table/caption quality.
- **Integrated source+PDF scope**: when LaTeX source is available, compile or use the rendered PDF, then combine PDF reader-facing evidence with source-level diagnostic locations.
- **PDF/layout scope**: inspect rendered pages as the source of truth for page-level reading experience: figure/table placement, caption proximity, line/page breaks, widows/orphans, cramped equations, whitespace balance, overfull-looking lines, and visual hierarchy.
- **HTML report output**: create a self-contained Chinese HTML notes report with structured sections, severity badges, sentence/paragraph margin notes, PDF page anchors when available, and coverage receipts.
- **Submission package scope**: identify likely rejection reasons, obvious errors and consistency issues, venue-compliance risks, anonymity/reproducibility risks, and the manuscript changes needed to preempt them.

For common phrasing that implies diagnostic margin notes, see **Diagnostic Note Triggers** in `references/reviewer_checklist.md`. Any paper critique/review/revision request should include diagnostic margin notes for the requested visible scope; Ariadne may narrow scope, but it does not lower depth.

For partial inputs, do not pretend to have full-paper certainty. State the missing context and review the local job at full depth: abstract = story slots and result precision; introduction = problem/gap/idea path; method = map/definitions/novelty/reproducibility; experiments = evidence chain; figures/tables = claim/caption/readability.

For long papers or large source trees, chunk the review into explicit parts rather than narrowing coverage. State which sections are covered in the current part, which remain pending, and continue with sibling HTML/markdown parts when needed. Do not silently drop sections or switch to sampling.

## Artifact Workflow

1. Identify the input type: LaTeX project, single `.tex`, PDF, paper excerpt, figures/tables, or submission package.
2. Extract review material when a file or project is provided:
   - Prefer `scripts/extract_paper_text.py <paper-path>`. By default it writes to a platform-appropriate temp file and prints `Wrote signals to <path>` on stderr; read that path. Pass `-o <file>` only when a specific destination is needed, or `-o -` only when stdout is intentionally needed.
   - Set `--max-items` high enough to cover all visible sections, captions, equations, and bibliography entries in the requested scope. If the signals report incomplete coverage due to `--max-items`, rerun with a larger value before claiming full coverage.
   - For LaTeX source or project input, prefer integrated review: identify the entry `.tex`, compile a rendered PDF with `scripts/build_paper_pdf.py <paper-path>` when local LaTeX tools are available, then review both source and PDF. If compilation fails, report the build warning, continue with source-only comments, and ask for the PDF for layout-sensitive judgment.
   - For PDF, use page numbers and short snippets. Treat the rendered PDF as authoritative for layout, visual rhythm, figure/table readability, page breaks, and whether the prose actually reads well on the page.
   - To inspect layout, open/render the PDF visually with the host platform's PDF Read/view/render capability. `scripts/extract_paper_text.py` and `pdftotext` strip layout; do not use extracted plain text as the source for layout judgments.
   - For long PDFs, do not try to visually read the whole document in one call. Read every page in the requested PDF scope in chunks and render issue rows only for pages with substantive layout issues; pages without issues are represented only by clean/no-issue counts in the coverage receipt. Never sample pages to fit one report. If the user explicitly asks about a single page/range, record that limited scope in the coverage receipt.
   - When both LaTeX and PDF are available, use the PDF for reader-facing evidence, first impression, page-level layout, figures/tables, and skimmability; use the LaTeX source for exact locations, macros, citations, TODOs, and source-level diagnostics.
3. Read the generated `Review Signals` before drafting comments. Treat extraction warnings as review caveats, not as manuscript facts.
   - If PDF signals include `PDF Coverage Metadata`, use its page count in the coverage receipt. Do not invent page totals.
   - If signals include `Table Completeness and Blank-Cell Signals`, treat blank/placeholder cells in main evidence tables as evidence-chain risks before writing any claim that a baseline or method is covered across all settings.
   - If signals include `Table Numeric Recalculation Signals`, cite the concrete `reported`, `visible arithmetic mean`, and `delta` values in the finding. Do not write only "平均值有偏差" or "需复查" when the signal gives the actual numbers; say what visible arithmetic produced and then state any limitation such as possible weighted/micro aggregation.
   - `ambiguous` numeric signals still require concrete rendering. Ambiguity only changes severity/rebuttal framing; it does not allow vague summaries. Write "表中写 X；按可见单元复算 Y；delta Z；若使用 weighted/micro aggregation，需要说明 denominator."
   - If signals include `Symbol and Macro Consistency Signals`, cite the concrete macro/token/symbol pair and keep the tool boundary clear. These are notation signals, not proof that an equation is wrong; use them to prompt method-reading, notation-registry, and reproducibility checks.
   - Deterministic scripts produce evidence **signals**, not final judgments. Use them to make your advisor note more concrete, then decide severity from the paper context, metric definition, and claim-evidence role.
4. Reconstruct the paper story before local comments:
   - apparent central claim
   - target reader/community, if inferable
   - What / Why / Gap / Idea / Evidence / Boundary
   - explicit manuscript facts vs. reviewer inference
5. Use the **Reader-Journey Workflow** in `references/reviewer_checklist.md` as the primary process, not as an optional mode: Pass 0 engagement contract -> Pass 1 cold-start skim -> Pass 2 linear deep read with sentence-by-sentence checks plus paragraph surgery -> Pass 3 section reflection with skeleton -> Pass 4 whole-paper argument -> Pass 5 submission walk -> Pass 6 output calibration. The checklist items and pattern libraries are tools invoked during these passes, not the organizing principle.
6. Render the report in the **Revision Workbench** order described in `references/reviewer_checklist.md`, not in pass order. Do not split section, paragraph, and sentence notes into separate repeated sections; put them in the article-ordered **Deep Reading Notes / 逐章精读批注** tree.
7. Before final output, run the **Output QA Gate**, **Severity Consistency Audit**, **Coverage Consistency Gate**, and **Rebuttal Reverse Check** in `references/reviewer_checklist.md`. Make high-risk findings inspectable with confidence, evidence basis, verification method, severity rationale, and downgrade condition. State relevant Known Blind Spots instead of implying unavailable verification.
   - If HTML is produced, run `scripts/audit_html_report.py <report.html>` before delivery when feasible. Fix any `ERROR` lines. Treat `WARNING` lines as review caveats.
   - Apply **High-Confidence Verdict Discipline** in `references/reviewer_checklist.md`: directive language for deterministic errors, magnitude-aware rebuttals, and no standalone hedging on conclusive arithmetic, broken refs, anonymity leaks, placeholders, or blank main-evidence cells.
8. When creating substantial HTML reports, use the **Structured Review Artifacts** contract in `references/html_report.md`: findings, claims, coverage, render manifest, and pass observations are saved artifacts, not conceptual notes only. Create the companion artifact bundle beside the reviewed paper when writable.
   - Produce `findings.json`, `claims.json`, `numeric_audit.json`, `coverage.json`, `render_manifest.json`, and `pass_observations.json` in `<paper-dir>/ariadne_notes_<stem>_<YYYYMMDD>/`, alongside `<paper-dir>/ariadne_notes_<stem>_<YYYYMMDD>.html`.
   - For any paper with visible tables or prose-cited numbers, run `scripts/extract_paper_text.py <paper.pdf-or-tex> --numeric-json <bundle>/numeric_audit.json` before drafting numeric findings. Use Python-computed `reported_value`, `visible_computed_value`, and `delta` from this JSON in the final report; do not rely on memory, prose summaries, or manual mental arithmetic for table errors.
   - Treat every visible table-value discrepancy in `numeric_audit.json` as `Blocker` in the rendered student report. Aggregation ambiguity changes the caveat and rebuttal, not the severity; the student must see the exact reported/computed/delta values.
   - After saving, run `scripts/audit_review_artifacts.py --bundle <paper-dir>/ariadne_notes_<stem>_<YYYYMMDD>/ --html <paper-dir>/ariadne_notes_<stem>_<YYYYMMDD>.html` when feasible. Fix `ERROR` lines before delivery. This checks source-of-truth fields, JSON/HTML drift, high-risk metadata, coverage, pass observations, and render-deferred findings.
   - For calibration/evaluation runs, generate two `findings.json` files from the same paper and run `scripts/calibrate_review_runs.py run1/findings.json run2/findings.json`. Severity drift on the same finding is a skill-calibration issue; do not treat it as a property of the paper.

## Thinking-to-Output Mapping

- **Internal execution** follows Pass 0-6. Pass 2 must inspect every sentence; merging sentence checks and paragraph reflection is for reading rhythm, not for reducing depth.
- **External presentation** follows the report order: **Executive Diagnosis and Salvageable Core**, **Issue Index / Finding Ledger**, **Claim-Evidence Audit**, **Deep Reading Notes**, **Submission Readiness**, **Local Patterns**, **Revision Plan**, and **Coverage Receipt**.
- Pass 0 feeds scope/output/artifact paths and coverage expectations.
- Pass 1 feeds skim observations inside **Claim-Evidence Audit** and, when local, linked notes in **Deep Reading Notes**.
- Pass 2 feeds the article-ordered **Deep Reading Notes**: each section contains section context, paragraph records, and sentence notes under the relevant paragraph.
- Pass 3 feeds the section reflection rows inside **Deep Reading Notes** with Chinese summaries, task-alignment judgments, restructure skeletons, loose ends, and linked finding ids.
- Pass 4 feeds **Executive Diagnosis and Salvageable Core**, **Issue Index / Finding Ledger**, **Claim-Evidence Audit**, title/abstract/conclusion critique, and likely reviewer attacks.
- Pass 5 feeds **Submission Readiness**: numerical/table signals, formula/symbol consistency, figures/captions, PDF layout, references, checklist, anonymity, venue, and Polish Sweep.
- Pass 6 feeds **Coverage Receipt** and must run HTML/JSON audits, finding deduplication, severity consistency, linked-finding integrity, numeric verdict concreteness, row/count cross-check, and revision-plan executability.
- Source-principle diagnosis should appear throughout. If the issue is "frontier lacks intuition", "method appears from nowhere", or "this paragraph should be deleted/moved", label it directly rather than translating it into generic flow.

## Output Rule

Use the output structure and severity labels in `references/reviewer_checklist.md`. Write in Chinese by default unless the user asks otherwise. Keep technical terms such as claim, gap, baseline, ablation, caption, limitation, and skimmability in English when that is clearer; explain them in Chinese prose.

For every Ariadne review, be comprehensive across the requested scope while still leading with the highest-risk findings. Do not bury Blocker/Major issues under sentence nits.

For paper feedback, do not stop at high-level diagnosis. After the paper-level findings, include article-ordered sentence/paragraph/section diagnostic notes for the visible scope inside **Deep Reading Notes**. The pedagogical posture is "explain why this fails and how the student should think while revising", not "supply copy-ready AI rewrites". For coverage, format, and chunking rules, see **Sentence-Level Margin Notes** in `references/reviewer_checklist.md`.

Compact low-value mechanical polish issues into a **Polish Sweep** instead of flooding sentence-level notes. When the report is Blocker-heavy, include **Salvageable Core / 可救骨架** so the student sees the minimal viable revision path, not only the failure list.

For HTML review reports, write the critique and next-draft tasks in Chinese by default, keep necessary technical terms in English, and follow `references/html_report.md`. Use PDF page anchors when available, but do not claim live PDF synchronization or embedded PDF annotations unless a tool actually created them.

When the user asks for an HTML report, create the self-contained `.html` file in the same directory as the reviewed PDF, compiled PDF, or entry `.tex` by default, following `references/html_report.md`; do not paste the full HTML body into chat. In the final response, give the absolute path and the PDF linkage level used.

Create the companion artifact bundle in the same directory by default: `ariadne_notes_<stem>_<YYYYMMDD>/findings.json`, `claims.json`, `numeric_audit.json`, `coverage.json`, `render_manifest.json`, and `pass_observations.json`. If the paper directory is not writable, save the bundle in a temp directory and clearly state the absolute fallback path.

For layout-sensitive revision, prefer reviewing the rendered PDF in addition to the source. For the full layout checklist, page-complete scope rules, and severity anchors, see **Submission Walk** and layout rules in `references/reviewer_checklist.md`. State when a layout comment is based on the PDF; if no PDF is available, mark layout review as unavailable rather than guessing from LaTeX.

Do not edit paper text or produce paper-ready prose inside this critique skill unless the user explicitly asks to leave critique mode. When giving rare example wording, explain the diagnosis first, keep the claim no stronger than the visible evidence, and mark it as `示例方向`.

## Final Response Template

For saved HTML reports, end with a compact artifact block:

```text
Saved artifacts:
  HTML report:      /absolute/path/ariadne_notes_<stem>_<YYYYMMDD>.html
  Artifact bundle:  /absolute/path/ariadne_notes_<stem>_<YYYYMMDD>/
    findings.json          (N findings; B Blocker, M Major)
    claims.json            (N claims; K overclaims/unsupported)
    numeric_audit.json     (N Python table/number signals)
    coverage.json          (Pass 0-6: done/pending)
    render_manifest.json
    pass_observations.json (N observations across 6 passes)
  PDF linkage level: Level 0|1|2|3
```

## Platform Notes

This skill is platform-neutral for Codex and Claude Code: the operative instructions are `SKILL.md`, `references/reviewer_checklist.md`, `references/html_report.md`, `scripts/extract_paper_text.py`, and `scripts/build_paper_pdf.py`.

`agents/openai.yaml` is Codex UI metadata only. Keep it synchronized with the frontmatter description, but do not rely on it for review logic. Claude Code can ignore it.

`tests/` is for development/regression checks and is not required at runtime. Do not copy `__pycache__/` or `*.pyc` files when installing the skill.
