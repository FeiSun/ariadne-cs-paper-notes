# Ariadne HTML Contract

Use this file when the user asks for HTML, 网页, 可视化报告, 批注报告, or a saved structured review file. Also load `report_contract.md`; load `numeric_contract.md` when numbers/tables are visible.

## Scope

- Write review content in Chinese by default.
- Keep precise technical terms in English when clearer: claim, evidence, baseline, ablation, caption, limitation, coverage.
- Produce a self-contained `.html` unless the user asks otherwise.
- The HTML is a teaching annotation interface, not merely a report. Put the paper text first and attach comments directly to the sentences that need attention.
- When the user asks specifically for a paper-HTML annotation page, default to a paper-reader deliverable: set `data-report-kind="paper-reader-only"` for overlay plus coverage, or `data-report-kind="paper-reader-with-global-findings"` when explicitly adding independent whole-paper findings. Keep `#paper-reader`, `#annotation-panel`, provenance metadata, annotation cards, and a compact coverage receipt. Do not recreate the legacy full workbench tables.
- Do not require external network assets, remote fonts, CDN scripts, or CSS frameworks.
- Inline JavaScript is allowed for self-contained filters/toggles.
- Do not claim live PDF synchronization, clickable PDF jumping, embedded PDF annotations, or written PDF comments unless implemented and checked.
- When trigger text includes `批注`, include article-ordered diagnostic section/paragraph/sentence notes.
- When TeX source is available, the paper text shown in `#paper-reader` must come from a deterministic paper-to-HTML pass, not from LLM-authored prose. Prefer a LaTeXML/ar5iv-style paper HTML view that preserves sections, paragraphs, equations, figures, tables, citations, and references as faithfully as feasible.
- If deterministic TeX-to-HTML is unavailable, render only the explicitly requested visible scope from extracted source/PDF text. Mark the scope limitation in the HTML and `render_manifest.json`; do not present the paper-reader as full-paper coverage.

## Required Sections

Paper-reader-only annotation pages use `#paper-reader` and `#coverage-receipt`:

```html
<article class="review-report" data-report-kind="paper-reader-only">
  <header>...</header>
  <nav aria-label="Review sections">...</nav>
  <section id="paper-reader">...</section>
  <main>
    <section id="coverage-receipt">...</section>
  </main>
</article>
```

When the user asks for `--full-report` or an extra global diagnosis after the overlay, use only `#global-findings` between the paper reader and coverage receipt:

```html
<article class="review-report" data-report-kind="paper-reader-with-global-findings">
  <header>...</header>
  <nav aria-label="Review sections">...</nav>
  <section id="paper-reader">...</section>
  <main>
    <section id="global-findings">...</section>
    <section id="coverage-receipt">...</section>
  </main>
</article>
```

Use these Chinese section labels:

| Section id | 中文标签 |
|---|---|
| `paper-reader` | 论文正文批注 |
| `global-findings` | 全局重要问题 |
| `coverage-receipt` | 覆盖回执 |

Do not use legacy top-level note sections such as `executive-diagnosis`, `issue-index`, `claim-evidence-audit`, `deep-reading-notes`, `submission-readiness`, `local-comments`, `revision-plan`, `top-priorities`, `section-review`, `paragraph-surgery`, `margin-notes`, `keep-notes`, `section-comments`, or `section-reflections` in paper-reader reports.

## Layout and Style

Use a sober paper-annotation design:

- header with paper title/path, review date, input artifacts, requested scope;
- summary band with source/provenance metadata and annotation counts;
- top/sticky navigation;
- readable paper column with advisor annotations beside it;
- the first major viewport after the header must be the annotated paper, not a table-heavy report section;
- use a two-pane layout on desktop: paper text on the left, sticky annotation panel on the right;
- collapse to paper-first single column on mobile, with selected annotation details opening below the sentence or as a top-of-section panel;
- keep the paper pane visually close to a CS paper: clear section hierarchy, paragraphs, equations/tables/figures in place, and enough whitespace for sustained reading;
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

## Paper Annotation UI

The saved HTML must contain an inspectable annotation workspace before the workbench sections:

```html
<section id="paper-reader" class="paper-reader" aria-label="Annotated paper">
  <div class="reader-shell">
    <article class="paper-pane" data-paper-html-source="latexml|ar5iv|pandoc|extracted-text" data-source-fidelity="deterministic|limited-scope" data-source-artifact="..." data-source-hash="sha256:..." data-sentence-id-scheme="section-paragraph-sentence-v2" data-annotation-mode="overlay-only">
      <p>
        <span class="paper-sentence" data-sentence-id="s-intro-001">Clean sentence.</span>
        <span class="paper-sentence has-annotation" data-sentence-id="s-intro-002" data-has-issue="true" data-issue-ids="F1" data-severity="major" data-issue-type="prose" tabindex="0" role="button" aria-describedby="ann-s-intro-002">Problem sentence.</span>
      </p>
    </article>
    <aside id="annotation-panel" class="annotation-panel" aria-label="批注详情">...</aside>
  </div>
</section>
```

### Source Fidelity Rules

- The LLM must not rewrite, paraphrase, complete, or summarize the paper body inside `#paper-reader`. It may only add annotation attributes, visual wrappers, annotation cards, and workbench sections around source-derived text.
- `data-paper-html-source` identifies the conversion backend: `latexml`, `ar5iv`, `pandoc`, or `extracted-text`. Use `manual-fixture` only in tests or examples, never in delivered student reports.
- `data-source-fidelity="deterministic"` is required for `latexml`, `ar5iv`, or `pandoc` paper panes. Include `data-source-artifact`, `data-source-hash`, `data-sentence-id-scheme`, and `data-annotation-mode="overlay-only"`.
- `data-source-fidelity="limited-scope"` is allowed only when deterministic conversion is unavailable. Include `data-visible-scope`, `data-source-artifact`, and `data-source-hash`; state the limitation in the coverage receipt and `render_manifest.json`.
- Stable sentence IDs must come from the paper-HTML generation pass, not from the review-writing pass. Until `scripts/render_paper_html.py` exists, use a documented deterministic scheme such as `section-slug + paragraph index + sentence index`, and record it in `data-sentence-id-scheme`.
- `annotations.json` for overlay mode must record the current pre-annotation paper source as top-level `source_artifact` and `source_hash`, matching `render_manifest.paper_reader.source_artifact` / `source_hash`. Do not reuse prior review annotations as source content for a new manuscript revision; historical annotations may only be used for calibration or debugging and must not pass as a fresh full-paper review.
- If a generated report uses a deterministic pre-annotation paper artifact, the final HTML should be auditable by normalizing the final `#paper-reader` after removing annotation-only attributes and comparing it with the source artifact hash. If this comparison was not run, record it as a QA warning, not as a silent success.

Paper-reader annotation requirements:

- Every sentence that has a substantive issue is wrapped in `.paper-sentence.has-annotation`.
- Direct inline annotations are preferred for student-facing HTML: the marked sentence should carry the visible severity/type cue, and the full teaching explanation should appear in the adjacent annotation panel.
- Each issue sentence has stable `data-sentence-id`, `data-has-issue="true"`, `data-issue-ids`, `data-severity`, and `data-issue-type`.
- Each issue sentence has a matching annotation card in `#annotation-panel` with `data-target-sentence="<same id>"`.
- Paragraph, section, and whole-paper structural notes should also be anchored in the paper view instead of being relegated to a separate report: use `data-paragraph-id` + `.has-paragraph-annotation` for paragraph notes, heading `id` + `.has-section-annotation` for section notes, and a compact `#paper-overview-annotations` block for whole-paper notes.
- Paragraph and section anchors should show a short bubble beside the paragraph or heading. The bubble text is a short diagnosis only; clicking or keyboard-activating it opens the full teaching note in `#annotation-panel`.
- Non-sentence annotation cards set `data-target-level="paragraph|section|paper"` and the matching `data-target-paragraph`, `data-target-section`, or `data-target-paper` attribute. Sentence cards may keep `data-target-sentence` for compatibility.
- If existing review content cannot be safely mapped to one paper sentence, preserve it as an unanchored/global annotation card with `data-unanchored="true"` and no `data-target-sentence`. Do not drop old report content merely because sentence anchoring failed.
- The annotation card explains `问题是什么`, `为什么有问题`, one atomic `违反原则`, `严重度理由` when it adds information beyond the severity badge, `关联问题` when relevant, and `自改问题`.
- Keep `location`, `snippet`, `evidence_basis`, and `verification_method` in JSON for anchoring, audit, and artifact checks, but do not show them by default in paper-reader margin cards. The clicked sentence/paragraph/heading already provides the visible location and source text.
- Never use the visible labels `位置`, `原句/片段`, or `证据/验证` inside paper-reader margin cards for sentence, paragraph, section, or paper anchors. Those labels are allowed in compact workbench tables only, not in overlay teaching cards.
- Show `核查依据` in a margin card only when it adds manuscript-level evidence the reader could not infer from the anchor itself, such as a table recomputation, PDF page/layout observation, citation/reference issue, source hygiene issue, checklist/submission risk, or human/judge audit detail. Do not show mechanical provenance such as `data-sentence-id`, `data-paragraph-id`, `source-derived paper-reader`, or `generated by render_paper_html.py`.
- Avoid showing command-style `下一稿任务` in margin cards unless the user explicitly requested a revision plan.
- Clean sentences may be wrapped as `.paper-sentence` for navigation, but they should not render visible clean comments.
- Use visual markers on sentences, paragraphs, headings, and the paper-overview block. Sentence markers should not obscure text; paragraph/section bubbles should be small enough not to disrupt paper reading.
- Default to a quiet reading state: annotation details may be hidden until the student clicks or keyboard-activates an issue sentence/bubble. When active, the matching card or card group for that anchor must be the only prominent anchored detail, and the UI must make the anchor-card relationship obvious with a pointer, backlink, arrow, or equivalent visual connector.
- Clicking or keyboard-activating an issue anchor highlights it and shows its matching annotation card. Provide `上一条` / `下一条` controls at least for issue-sentence navigation.
- Severity and type filters must apply to both paper sentence markers and annotation cards. If filtering is absent, show a static legend instead of clickable controls.
- `data-issue-ids` may contain multiple ids separated by spaces. Each id must exist either in the hidden `#finding-anchor-index`, an overlay annotation card, or a `#global-findings` card.
- If the paper view is generated from LaTeXML/ar5iv-style HTML, preserve equations/tables/figures as much as possible and wrap prose sentences without breaking math, citations, or inline code.
- If a numeric signal in `numeric_audit.json` maps to a sentence or phrase in the paper pane, its annotation card must render the concrete `表中数值`, `可见复算值`, `差值`, and `口径说明`, and link to the canonical numeric finding id. If no exact sentence can be located, render it as an unanchored annotation card or a true global finding; do not invent a paper sentence anchor.

## Filters and Tags

If severity filters such as `全部 / Blocker / Major / Minor / Polish` are shown, they must work. Every severity-badged issue item must have `data-severity` on a stable container so it hides as a unit:

- paper sentence markers;
- paragraph/section/paper overview bubbles;
- annotation cards;
- global finding cards.

Wire buttons with inline JavaScript and update active/`aria-pressed` states. If filtering is not implemented, show a static legend instead of clickable-looking buttons.

Add `data-issue-type` when clear: `math`, `numeric`, `evaluation`, `claim`, `layout`, `checklist`, `prose`, `citation`, `source`, or `submission`.

When a filter hides all filterable children in a section/table, show a small empty state such as `该严重度暂无项` / `该表无此严重度项`.

## Global Findings HTML

`#global-findings` is only for independent whole-paper Major/Blocker findings that are not better anchored to a sentence, paragraph, or section. Appropriate examples include novelty weakness, story-logic gaps, experiment-design threats, judge independence, evidence sufficiency, or a paper-wide claim calibration problem.

Do not put local issues in `#global-findings`. If an issue belongs to a concrete subsection such as `LLM-as-a-Judge Verification`, bind it to that heading or paragraph. Do not include source/macro/BibTeX/hidden-LaTeX hygiene issues unless the problem is visible in the paper rendering or directly affects submission-facing layout.

Every `render_required` numeric signal must appear with concrete values. Prefer the closest paper anchor; if none exists, render the numeric finding as an unanchored card or a global finding with the same concrete values. See `numeric_contract.md`.

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

Only emit the canonical paper-reader HTML pair: `<stem>.source.html` and `<stem>.html`. Do not create `*.source_preview.html`, `*_preview.html`, plaintext paper dumps, or bundle-local generated helper scripts.

## HTML Audit

Before delivery, run when feasible:

```bash
scripts/audit_html_report.py <report.html> --source <paper-reader.source.html>
```

If JSON artifacts exist, also run:

```bash
scripts/audit_review_artifacts.py --bundle <bundle>/ --html <report.html> --source <paper-reader.source.html>
```

`--source` should point to the pre-annotation paper-reader source artifact named in `data-source-artifact`; the audit recomputes `data-source-hash` and compares the final paper pane against that source after removing annotation-only markup. Fix every `ERROR` before delivery. Treat `WARNING` lines as caveats or calibration notes; a skipped source comparison must remain visible as a warning, never as silent success.
