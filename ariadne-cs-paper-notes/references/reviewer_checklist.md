# Reviewer Checklist

Use this file as the normal review reference. It is condensed from Ofey's CS paper-writing tips into advisor-facing checks: fail signals, severity hints, reader-friction diagnoses, writing principles, and next-draft tasks. This is a critique/annotation reference, not a paper-rewriting reference.

## Severity Labels

- `Blocker`: likely to threaten acceptability or make the main claim unclear, unsupported, misleading, or non-recoverable.
- `Major`: substantially weakens persuasion, reader path, evidence alignment, or submission credibility.
- `Minor`: local clarity, precision, consistency, source hygiene, or presentation issue.
- `Polish`: helpful but not submission-critical.

When uncertain, say what is visible in the manuscript and what is inference. Do not create a second issue-label system.

## High-Risk Finding Fields

Every `Blocker` and `Major` finding must be inspectable. Include these fields in the finding card, table row, or immediately adjacent prose:

- `location`: exact section, paragraph, page, figure, table, equation, or source artifact.
- `evidence_basis`: rendered PDF, LaTeX source, extracted text, table signal, citation/bib signal, visual inspection, or reviewer inference.
- `confidence`: `high`, `medium`, or `low`.
- `verification_method`: how the issue was checked, e.g. PDF visual pass, source grep, table visible-cell arithmetic signal, claim-evidence cross-check, abstract promise tracking, or reviewer reading inference.
- `severity_rationale`: why this is `Blocker`/`Major` rather than a lower severity.
- `downgrade_condition`: what evidence, clarification, experiment, source data, or rewrite would lower the severity.
- `reader_friction`, `writing_principle`, and `next_draft_task`.

If a field is unsupported by the input, write `not available from provided artifact` rather than inventing it. Mechanical script outputs are evidence signals, not verdicts; Ariadne decides severity only after reading the signal in manuscript context.

## Known Blind Spots

Ariadne should be explicit about what cannot be verified from the provided artifacts. Use these limits in findings, coverage receipts, and caveats:

- Without original code, data, logs, or seed-level results, Ariadne cannot verify experimental reproducibility or statistical significance.
- Without seed-level or per-example results, table arithmetic can only check visible-cell consistency; macro/micro/weighted aggregation may remain ambiguous.
- PDF layout comments are limited by the rendered pages and visual resolution available to the agent. If a layout issue is uncertain, mark it `疑似` / `possible`.
- Identity/anonymity checks surface visible signals such as author commands, emails, GitHub links, paths, and metadata-like text; they do not prove a real identity.
- Venue compliance changes over time. If official venue rules are not provided or browsed, say compliance cannot be fully verified.
- For PDF-only input, source-level claims about macros, citations, buildability, and hidden comments are unavailable.

Do not let tool output make the report overconfident. A signal such as "blank table cell detected" or "visible average differs" is a prompt to inspect and explain; it is not automatically a `Blocker`.

## Diagnostic Note Triggers

Use **Sentence-Level Margin Notes** for any substantive paper critique/review/revision request. The following phrases make the need especially explicit: detailed comments, teacher-style feedback, edits, annotations, 批注, 修改意见, 逐句/具体句子 feedback, 认真批注, 像老师一样改, 细致改一下, 帮我改句子, 红笔批注, or 划重点说哪里不对.

## Source Principle Index

This checklist is not only a rule list. It operationalizes the source writing tips' advisor stance. Every substantive margin note should be traceable to at least one source principle below; if a note maps to none, it is probably decorative rather than useful.

| Source principle | Checklist lens that operationalizes it |
|---|---|
| `改变读者理解状态` | central claim, knowledge increment, claim-evidence map, story red-team |
| `低认知负担 / reader-first` | curse-of-knowledge pass, intuition-before-formalism, skimmability, PDF/layout |
| `显式逻辑，不让读者猜` | missing-why probing, precision slots, story logic, paragraph transitions |
| `加入并推动一场已有对话` | related-work coordinates, strategic framing, baseline/evidence contract |
| `argument, not explanation or research log` | paper type/review contract, section jobs, experiments as evidence chain |
| `知识的诅咒` | first-page reader test, new-term intuition checks, cognitive-load notes |
| `洞察 ≠ 机制` | knowledge increment, Method Clarity, Insight vs Mechanism Separation |
| `先定每一层任务 / 一段只做一件事` | paragraph-level surgery, topic-sentence checks, article-ordered Deep Reading Notes |
| `句首接旧信息，句尾放新信息` | flow pattern library, sentence-to-sentence margin notes |
| `caption 首句告诉读者该看见什么` | figures/tables/captions, skimmability, visual system |
| `不要让读者做翻译题/查字典题/算术题` | figure/table readability, numerical sanity, reference/style consistency |
| `红队式自查` | story logic and red-team pass, likely rejection reasons, limitations |

Every substantive margin note that maps to a source principle in this table must mention the principle name in the `违反原则` / writing-principle field, e.g. "这违反知识的诅咒：第一页读者还没有 mental handle for frontier." The Coverage Receipt must report `notes citing source principles: N/M` so principle use is observable.

## Reviewer Stances

Hold these stances while reading before applying any local checklist item:

1. **Change reader belief, not display author knowledge.** A paper succeeds when the reader's understanding changes; a note is valuable when it makes that belief update clearer, better supported, or easier to remember.
2. **First-page / first-day reader test.** Assume a smart reviewer sees the problem for the first time today. If the draft relies on context only the author has, flag the missing bridge.
3. **Explicit logic, no guessing.** Subtlety in academic prose usually reads as ambiguity. If the reader must guess why a claim follows, what a term means, or why this method is the right move, the manuscript has not yet written the logic.
4. **Join an existing conversation.** The paper must say how it changes the field's current map: confirm, contradict, refine, explain, or open a route. Do not let Related Work or Introduction merely describe a topic.
5. **Argument, not explanation, not research log.** Sections should argue what the reader should now believe, not merely report what the authors did.
6. **Direct, simple, precise prose.** Prefer common precise words over fancy ones. Hedging is useful only when evidence uncertainty demands it; otherwise it hides the claim.
7. **Paragraphs are movable objects.** A paragraph may need to be deleted, merged, split, or moved. Do not assume every existing paragraph deserves in-place polishing.

## Curse-of-Knowledge Pass

Apply this lens to every page-1 paragraph, newly introduced term, formal definition, metric, figure/table concept, and claim that feels "obvious" to the author. Ask:

> Would a smart but non-specialist reader understand this the first time, or would they pause and guess?

Always emit a margin-note row when any of these appear:

- **New technical term without intuition**: e.g. `frontier`, `AURC`, `operating point`, `risk-coverage`, `calibration`, `split index`, or a venue-specific concept appears before a one-line intuitive bridge.
- **Claim with implicit causal chain**: the sentence states that X solves/improves/enables Y but omits the why-step that would make the claim feel inevitable.
- **Metric defined only formally**: the reader sees a formula or acronym but not what a larger/smaller value physically means.
- **Figure/table reference without a mental handle**: "as shown later" or a caption points to evidence before the reader knows what to look for.
- **Old concept reused after a long gap without re-anchoring**: a term defined pages earlier appears again as if it were still active in working memory.

Forbidden author moves in this pass: using `obviously`, `clearly`, `naturally`, `it is well known`, or a formula-only definition to skip the reader's bridge. Treat these as `cognitive load`, `intuition gap`, or `missing why` issues, not as polish.

## Intuition-Before-Formalism Rule

Whenever the paper introduces a technical term, metric, formula, threshold, named procedure, or non-obvious design choice for the first time, the writer owes the reader at least one of:

- a one-sentence intuitive bridge: "Intuitively, this measures..."
- a concrete workflow interpretation: "In deployment, this corresponds to..."
- a tiny example or running example
- a figure/table/caption that visibly supplies the intuition

If none is present, create a margin-note row with `Check: cognitive load` or `intuition gap` and draft the missing bridge sentence. Apply this outside Method too: introduction metrics, result measures, captions, and related-work categories all need intuition when they first appear.

## Reader-Journey Workflow

This is the default process for every substantive Ariadne critique. Do not treat checklist items as the organizing principle. Simulate a first-day reader moving through the manuscript, and use the checklist items, reviewer stances, pattern libraries, PDF/layout rules, and source/artifact scripts as tools invoked by that reading process.

Scope may shrink to a section, paragraph, page range, table, or figure; depth does not shrink. If the input cannot support a pass, mark that pass `not applicable` or `pending` in the coverage receipt rather than pretending it was done.

### Pass 0 -- Engagement Contract

Before reading, fix the review contract:

1. requested scope: full paper, section, paragraph, PDF/layout, experiment package, submission walk, or combined scope;
2. input artifacts: PDF, LaTeX/source tree, extracted text, figures/tables, venue/checklist, or excerpt;
3. output language and format: Chinese by default, self-contained HTML when requested;
4. output paths: `ariadne_notes_<stem>_<YYYYMMDD>.html` plus the companion JSON bundle;
5. coverage standard: no sampling inside the requested visible scope; every visible sentence/paragraph/page/table/equation/reference object is inspected. Student-facing notes render only substantive issues; no-issue/clean units are counted in coverage receipts and optional machine-readable coverage artifacts, not shown as `clean` rows.

### Pass 1 -- Cold-Start Skim

Before the linear full read, simulate a new busy reviewer. Read only title, abstract, section openers, figures/tables/captions, and conclusion. Record skim observations: what problem, gap, idea, result, and boundary are recoverable, and where the story breaks.

This pass protects the first-reader perspective. Do not use later full-text knowledge to forgive a missing title/abstract/caption/section-opener signal.

### Pass 2 -- Linear Deep Read

Read the manuscript in article order. For each section, for each paragraph, do sentence checks first and paragraph reflection immediately after that paragraph. Merging sentence checks and paragraph reflection is a reading-rhythm decision, not a depth reduction.

For **every sentence** in the requested visible prose scope, check:

1. grammar, syntax, and mechanical correctness;
2. diction, naturalness, precision, concision, and redundant sentence deletion;
3. ambiguity: referent, modifier, scope, comparator, metric, condition, and evidence strength;
4. sentence-to-sentence flow: old-new order, connector truth, stress position, and emphasis;
5. cognitive load: new terms, metrics, formulas, or concepts without intuition;
6. missing why/how/referent: places where the reader must infer the causal or logical step.

Every substantive sentence issue becomes a sentence row under that paragraph in **Deep Reading Notes**. If a sentence is clean, it still counts in coverage; do not sample or silently skip, but do not render a student-facing `clean` row.

After each paragraph, record a paragraph decision: `保留`, `原位修改`, `合并`, `拆分`, `移动`, or `删除`. Ask whether the paragraph has one job, whether the topic sentence works, whether it should exist here, and what the next-draft structural task is.

### Pass 3 -- Section Reflection

After finishing each section, stop and reflect before moving on:

1. `读后一句话`: what this section made the reader believe;
2. `章节任务是否对齐`: whether the section's actual job matches the paper's contract;
3. `建议结构`: a 3-6 step section skeleton for a first-day reader;
4. `未闭合问题`: loops opened but not closed;
5. `关联问题`: linked finding ids;
6. `下一稿任务`: the concrete section-level revision job.

For experiments, include numerical sanity, figure/table readability, caption takeaway, baseline fairness, and whether each result answers a research question. For Related Work, state whether it builds coordinates leading to the gap or merely lists prior papers.

### Pass 4 -- Whole-Paper Argument

After reading all visible sections, zoom out:

1. central claim and paper type/review contract;
2. abstract promise tracking;
3. claim-evidence map;
4. title/abstract/introduction/conclusion alignment;
5. story logic red-team and likely reviewer attacks;
6. salvageable core: what minimal viable paper remains after fixing Blockers/top Majors.

### Pass 5 -- Submission Walk

Run the hard artifact walk:

- numerical/table arithmetic: every visible average, total, delta, relative improvement, rank, best marker, and prose-cited number;
- formula/symbol/algorithm consistency;
- figures, captions, and visual dictionary;
- PDF/page layout for every rendered page in the requested scope;
- references/citations, bibliography style, placeholders, TODOs, anonymity, checklist, venue compliance, and polish sweep.

For numerical/table arithmetic, Python computation is mandatory when a machine-readable PDF/source signal can be extracted. Run `scripts/extract_paper_text.py <input> --numeric-json <bundle>/numeric_audit.json` and preserve that file in the artifact bundle. Rendered numeric findings must cite the concrete signal values from `numeric_audit.json` (`table_id`, row/column, reported value, visible computed value, delta, aggregation caveat). If the manuscript has visible tables but no `numeric_audit.json`, mark Pass 5 incomplete rather than claiming table arithmetic coverage. Any visible table-value discrepancy is **Blocker-level** in the student-facing report until the manuscript explains the aggregation/denominator; do not render it as `Major`, `Minor`, or `Polish`.

### Pass 6 -- Output Calibration

This pass audits the report, not the paper. Before delivery:

1. deduplicate findings into one canonical **Issue Index / Finding Ledger**;
2. check severity consistency and rebuttal reverse checks;
3. verify every `linked finding` points to a defined id;
4. ensure numeric verdicts include reported value, visible computed value, delta, and caveat;
5. cross-check header/coverage counts against body rows;
6. ensure the revision plan is executable;
7. run `audit_html_report.py` and `audit_review_artifacts.py` when HTML/JSON are produced;
8. fix every `ERROR` before delivery.

### Mandatory Pass Evidence

Each pass must leave visible evidence in the review artifact or a `not applicable` / `pending in <part>` marker. The **Coverage Receipt** must include Pass 0-6 status and explicit counts for sentences, paragraphs, pages, tables, equations, references, findings, and artifacts when available. `Skipped` must be 0 for completed scope.

## Output Structure

The reader journey and the report order are different. Execute Pass 0-6 internally, then render the report as a revision workbench for the student. Use this order for full-paper reviews; focused reviews keep the supported subset in the same relative order.

### 1. Executive Diagnosis and Salvageable Core

- 一句话 verdict.
- Paper type and review contract.
- Highest-risk weakness and why it blocks reader belief.
- Salvageable core: the minimal viable paper after fixing Blockers/top Majors.
- Claims to delete, downgrade, or support with new evidence.

### 2. Issue Index / Finding Ledger

- This is the only place where every core issue receives the full diagnosis.
- Include all `Blocker`, `Major`, and revision-relevant `Minor/Polish` grouped findings.
- Each id must be stable in `F<number>` form (`F1`, `F2`, `F12`), with suffixes such as `F3a/F3b/F3c` only when splitting one grouped finding.
- Every later `关联问题` must link to a defined id here.
- Later sections should write local consequence + linked id, not repeat the full diagnosis.

### 3. Claim-Evidence Audit

- Abstract Promise Tracking.
- Claim-Evidence Map.
- Story Logic and Red-Team Pass.
- Title/abstract/introduction/conclusion alignment.
- Skim-test observations from Pass 1 when they affect claim recoverability.

### 4. Deep Reading Notes / 逐章精读批注

Organize this section in manuscript order. Do not split it into separate global `分章批注`, `逐段手术`, and `句子级批注` sections. For each visible section:

1. section reflection row/block: `读后一句话`, `章节任务是否对齐`, `建议结构`, `未闭合问题`, `关联问题`, `下一稿任务`;
2. for each paragraph: paragraph job, surgery decision, why, next-draft structural task, linked finding;
3. under that paragraph: sentence-level rows for every substantive sentence issue; clean/no-issue coverage is represented by counts, not rendered rows.

This article-order structure prevents repetition and lets the student revise while looking at the paper in order.

### 5. Submission Readiness / 数字、公式、图表、版式、提交就绪

Put cross-cutting artifact checks here:

- numerical/table arithmetic and table completeness;
- formula/symbol/algorithm consistency;
- figures/tables/captions and visual system;
- PDF/page layout;
- reference/citation style;
- checklist, venue compliance, anonymity, source hygiene;
- Polish Sweep for purely mechanical repeated issues.

Use linked finding ids and concrete values; avoid repeating full Issue Index diagnosis.

**Numeric signal-to-render rule**: every numerical signal emitted by `scripts/extract_paper_text.py --numeric-json` with `render_required: true` must appear in **Submission Readiness** with its concrete `table_id`, row/object label, reported value, visible recomputed value, and delta. This applies to `deterministic`, `likely_error`, and `ambiguous` tiers.

- Deterministic tier: render directive comparison and link a `Blocker` finding in the Issue Index.
- Likely-error tier: render concrete comparison, name the plausible rebuttal if any, and link a `Blocker` finding when it affects any visible table value.
- Ambiguous tier: still render concrete comparison and the named rebuttal hypothesis. If it is a visible table-value discrepancy, render it as `Blocker`; ambiguity changes the explanation/caveat, not the severity. It may be grouped with other numeric Blockers, but it must not be silently dropped.

If a signal is a parser false positive, mark it as `render_required: false` in `numeric_audit.json` with a reason before audit, rather than ignoring it in the HTML. The student must be able to see what was checked and why it did or did not become an issue.

### 6. Local Patterns / 共性问题汇总

Summarize repeated writing habits only. Do not relist every instance. Give 2-3 representative locations and link to canonical finding ids or deep-reading rows.

### 7. Revision Plan / 修改路线

Place the execution table near the end, after the author has seen the evidence and local notes. Columns: `优先级`, `任务`, `关联问题`, `负责人/区域`, `工作量`, `验收方式`.

### 8. Coverage Receipt and Artifacts

- Pass 0-6 status.
- Body-backed counts for sentences, paragraphs, sections, pages, tables, equations, references, findings, and grouped polish.
- `Skipped = 0` for completed scope or explicit `pending in <part>`.
- QA gate, severity audit, coverage consistency, linked-finding integrity, numerical concreteness, and artifact audit status.
- HTML/JSON bundle paths and known blind spots.

For focused requests, use the relevant subset. Omit paper-level slots that the input cannot support, but preserve no-sampling coverage inside the requested scope.

## Comment Style

- Follow the **Reader-Journey Workflow** as the default inspection process. The checklist items below are tools for diagnosing what the reader journey exposes, not a replacement for reading sentence by sentence, paragraph by paragraph, section by section.
- Review as an advisor, not a copyeditor. Give dense sentence-level feedback for the requested prose scope, but tie each note to a transferable writing habit rather than a one-off typo.
- Diagnose the paper's argument before rewriting sentences.
- Prefer reader friction, source principle, and self-revision questions over ready-made replacement prose. The goal is to teach the student why the writing fails and how to revise, not to make the student copy an AI sentence.
- Prefer teaching language over reviewer verdict language. Use `Blocker/Major/Minor/Polish` for sorting, but explain the issue as a reader-learning problem: "这里会让读者暂停理解 idea，转而怀疑稿件状态" is better than bare "desk reject". Reserve rejection-risk wording for actual submission-risk analysis, and still explain the reader mechanism behind it.
- Every substantive note should have three layers: **reader friction** (where the reader gets stuck), **writing principle** (what habit/principle is violated), and **next-draft task** (what the student must make true in the revision).
- Use full example sentences sparingly: give one only when it clarifies a principle, fixes a high-risk claim, or the user explicitly asks to leave critique mode. Otherwise give a bounded next-draft task, such as "state the comparator and metric", "move the old concept to the front", or "add one intuitive bridge before the term".
- When you provide example wording, label it as `示例方向`, not as the only correct answer.
- Treat three things as allowed exceptions, not ghost-writing: (1) mechanical corrections with one right answer, such as `polices -> policies`; (2) structural skeletons in bullet form, such as paragraph order or section jobs; (3) placeholder templates that teach claim shape, such as `[dataset] / [metric] / [baseline]`. Do not fill a placeholder template with paper-specific prose unless the user explicitly asks for direct rewriting.
- Prefer repair instructions over broad judgments.
- Never write only "make clearer" or "improve flow"; name the reader question that is unanswered.
- Prefer senior-advisor questions over surface labels: "why should the reader believe this?", "what step is missing?", "why this method rather than the obvious alternatives?", "should this paragraph exist here?", and "what does this term mean physically?"
- When a reader would ask "why?" or "what does that mean?", flag it explicitly as `missing why`, `intuition gap`, or `cognitive load`; do not downgrade it to generic flow.
- Be willing to recommend deletion, merge, split, or move operations. In-place rewriting is not the default when the paragraph's job is wrong.
- Preserve claim strength: do not make a claim broader, more causal, more statistically certain, or more novel than the evidence supports.
- Teach the repeated habit behind recurring issues.
- Separate manuscript facts from reviewer inference.
- If evidence is missing from the provided artifact, ask for the missing source instead of guessing.
- Include **Keep Notes** only when something is already doing important work and should not be damaged during revision. If nothing clearly qualifies, omit the section.
- Compact purely mechanical `Polish` issues. Spelling, casing, ordinal format, hyphenation, and trivial typography should be grouped into one **Polish Sweep** row per category with a location list, not one margin-note row per occurrence. These grouped rows still count in coverage.
- When structure is in doubt, extract paragraph first sentences and present them as bullets. Use this for Introduction, Related Work, Method, Experiments, or any section whose reader path feels unstable.
- Add **Sentence-Level Margin Notes** for every substantive prose critique using the format below.

## Output QA Gate

Before finalizing any report, run this self-audit. In normal use this is an agent self-check; in JSON workflows it can also be run by external validators.

1. **High-risk field check**: every `Blocker`/`Major` has location, evidence basis, confidence, verification method, severity rationale, downgrade condition, reader friction, writing principle, and next-draft task.
2. **Unsupported-claim check**: every inference is labeled as inference; every manuscript fact has a visible evidence basis.
3. **Coverage check**: coverage receipt matches the requested scope and does not claim pages, sections, figures, tables, references, or passes that were not actually inspected.
4. **HTML contract check**: if HTML is produced, every severity-badged issue has `data-severity`; filter controls are functional or rendered as a static legend; no unimplemented PDF sync or embedded annotation is promised.
5. **Tool-boundary check**: script output is cited as signal/evidence, not as final judgment.
6. **Blind-spot check**: the report states relevant Known Blind Spots when source, PDF, seed data, code, venue rules, or visual resolution are missing.
7. **Revision-workbench structure check**: full-paper reports use the canonical report order: 总评诊断与可救骨架 -> 问题索引 -> 主张与证据审计 -> 逐章精读批注 -> 提交就绪 -> 共性问题汇总 -> 修改路线 -> 覆盖回执. Do not split section, paragraph, and sentence notes into separate repeated top-level sections.
8. **Body-backed count check**: every count in the header, summary band, or Coverage Receipt must be backed by visible body rows/cards or an explicit `pending in <part>` marker.
9. **Verdict calibration check**: every `confidence: high` or deterministic evidence finding whose `verification_method` contains table arithmetic, broken reference, placeholder, anonymity, source grep, or exact source parse must use concrete directive language. Numerical findings must state reported value, visible recomputed value, and delta. They must not stop at "有偏差", "需复查", "需要核对", or "建议复查" unless immediately followed by the concrete value pair and the specific rebuttal that could explain it.

If the report fails a QA item, fix the report before delivering it. Add a compact QA line in **Coverage Receipt** rather than a long meta-discussion.

## Coverage Consistency Gate

Run this after the report is drafted and before delivery. This gate prevents the report from making the same kind of overclaim it criticizes in the paper.

1. List every quantitative coverage claim in the header, summary band, table of contents, and **Coverage Receipt**: sentence-note count, paragraph-row count, section-reflection count, page count, figure/table/equation count, bibliography-entry count, grouped-polish count, and split-part pending count.
2. For each claim, identify the body section or selector that backs it, such as `#deep-reading-notes [data-note-kind="sentence"]`, `#deep-reading-notes [data-note-kind="paragraph"]`, `#deep-reading-notes [data-note-kind="section"]`, `#submission-readiness .pdf-anchor`, or `#coverage-receipt`.
3. Verify that the actual body count matches the claimed count. If a unit is deferred, the body or receipt must say `pending in <part>`; do not count pending units as reviewed.
4. If the count cannot be verified, fix the report by adding the missing body section, correcting the count, or splitting the missing material into the next part.
5. Record the gate in **Coverage Receipt**: `Coverage consistency: N claims checked, M repaired, 0 unresolved`.

For HTML reports, run `scripts/audit_html_report.py <report.html>` when feasible and fix any `ERROR` lines before delivery.

## Severity Consistency Audit

After drafting findings and before final output:

1. Group findings by problem type, such as missing baseline, table inconsistency, abstract overclaim, formula/notation ambiguity, paragraph surgery, claim-evidence mismatch, layout readability, citation hygiene, or submission compliance.
2. Within each group, compare severity labels. The same problem type on equally central evidence should use the same severity.
3. If two findings in the same group have different severities, either state the discriminating factor in the lower-severity finding or adjust the severity.
4. Record the audit in **Coverage Receipt**: `Severity audit: N finding groups checked, M adjusted`.

This audit is not a second issue-label system. It is a consistency check on the existing `Blocker/Major/Minor/Polish` labels.

## Rebuttal Reverse Check

For every `Blocker`, briefly imagine the strongest reasonable author response:

- Could the author point to visible text, table, appendix, source, or venue rule that already answers the finding?
- Would a missing clarification, one extra sentence, or an aggregation explanation reduce the severity?
- Is the finding based on reviewer inference rather than visible evidence?

If the rebuttal stands, downgrade or qualify the finding. If it does not stand, use the rebuttal attempt to write a sharper `downgrade_condition`. Record the count in **Coverage Receipt**: `Rebuttal reverse check: N Blockers checked, M downgraded/qualified`.

**Magnitude-aware constraint**: rebuttals must quantitatively explain numeric gaps. "The author may have used weighted aggregation" is not enough by itself; name the denominator or weighting assumption that could plausibly produce the reported value. Small gaps can remain ambiguous when hidden rounding or micro/macro aggregation could explain them. Gaps above 2 percentage points or 5% relative difference should not be softened by a theoretical aggregation rebuttal unless the manuscript provides a specific formula or denominator. If the rebuttal cannot explain the magnitude, keep the directive verdict.

## High-Confidence Verdict Discipline

Hedging must match evidence certainty. "Scripts emit signals, never verdicts" is a tool-boundary rule; it is **not** a license for vague rendered feedback. Ariadne's student-facing note should be concrete enough that the student knows exactly what to inspect or fix.

| Evidence type | Required rendered language | Forbidden rendered language |
|---|---|---|
| **Deterministic**: visible-cell arithmetic gap too large for plausible aggregation, broken `\ref`/`\cite{?}`, TODO/placeholder, visible anonymity leak, blank table cells in a main evidence table, clearly undefined symbol in visible source | "X, not Y"; "复算 X，而表中写 Y"; "缺失"; "未定义"; give exact location/value | Standalone "可能", "需要核对", "建议复查", "需复查", "有偏差" |
| **Ambiguous**: small arithmetic gap, possible weighted/micro aggregation, claim-evidence gap where another section may contain evidence, uncertain visual/layout issue | "复算 X，表中写 Y（gap N）；若使用 weighted/micro aggregation，需要说明 denominator" | Vague "需复查" without the concrete value pair and plausible rebuttal |
| **Inference-only**: story logic, paragraph surgery, strategic framing, reader path | Reader-friction language: "读到这里，读者会..." | Overconfident mechanical-error verdicts |

Ambiguous numerical evidence still requires concrete rendering. For visible table values, `ambiguous` affects rebuttal framing only; it does **not** lower severity below `Blocker` and does **not** permit "有偏差/需核对" without reported/computed/delta. A useful student note says exactly what the table reports, what the visible recomputation gives, and what missing aggregation definition would resolve it.

Anti-patterns the QA Gate must catch:

- "Score X 与可见均值有偏差" -> write the concrete comparison, e.g. "Table 1, Method A Score X: 按可见三列复算约 95.52，不是表中的 95.77；若用 weighted/micro aggregation，表注必须说明 denominator。"
- "best bold 需复查" -> identify the visible max/min and the cell that was bolded.
- "可能来自隐藏小数" by itself -> state whether hidden precision could plausibly explain the magnitude; if not, keep the finding as an error.

On deterministic evidence, hedging itself is a calibration failure. On ambiguous evidence, do not overclaim certainty; give the concrete discrepancy and the precise missing explanation.

## Sentence-Level Margin Notes

Use this pass for every substantive prose critique. Do not let it replace the paper-level review; put it after paper-level findings when paper-level context exists.

### Ariadne Coverage Standard

This is the only depth standard. The user may narrow the **scope** to a paper, section, paragraph, page range, figure, table, or reference list, but do not narrow the **depth** inside that scope.

1. **No numerical cap on margin notes.** Output as many notes as the requested scope has substantive issues. A user-provided count is a floor or preference, not a cap.
2. **Per-paragraph mandatory coverage.** Every paragraph in the requested visible scope is inspected and counted. Render a row only when there is a substantive issue or a paragraph surgery decision. Paragraphs without issues are represented in coverage counts, not as visible `clean` rows. Silent skipping is forbidden.
3. **Per-section mandatory coverage.** Every visible section in scope is walked end-to-end. Append a coverage line for each section: `Section X: N paragraphs inspected, M notes produced, K paragraphs marked clean.`
4. **No sampling or shortlists.** If many sentences share one precision/flow/diction pattern, put the pattern rule in **Local Patterns / 共性问题汇总** and still create one row per concrete instance in **Deep Reading Notes / Sentence-Level Margin Notes**.
5. **Cover all visible dimensions.** When present, cover `grammar`, `ambiguity`, `concision`, `diction`, `sentence flow`, `emphasis placement`, `topic sentence`, `paragraph flow`, `paragraph transition`, `cognitive load`, `intuition gap`, `missing why`, `paragraph surgery`, `discourse coherence`, `strategic framing`, `evidence`, `scope`, `caption`, `terminology`, `number sanity`, `table consistency`, and `reference style`.
6. **Output too large means chunking, never dropping.** For HTML reports, generate `ariadne_notes_<stem>_part1.html`, `_part2.html`, etc., with sibling links. For markdown/chat output, finish the current part and explicitly mark the next pending section. Do not replace omitted sections with a summary.
7. **Coverage receipt is mandatory.** End with a table listing sections, paragraphs, sentences when recoverable, issues found, clean/no-issue counts, and skipped count. `Skipped` must be 0 for a completed scope; if it is non-zero, mark the run incomplete and continue or offer the next part.

For every prose scope, perform the close pass visibly enough that the report proves the scope was inspected:

1. Read each sentence in the requested scope in order.
2. Check grammar and syntax.
3. Check whether the sentence's meaning is precise and unambiguous for a reader.
4. Check whether it can be shorter without losing necessary qualifiers.
5. Check sentence-to-sentence flow: old information should connect to the previous sentence; new information should land where the reader expects emphasis.
6. Check paragraph flow: each paragraph should have one job, with Topic -> Support -> Takeaway/Bridge.
7. Check paragraph-to-paragraph flow: transitions should reflect the real logical relation, not decorative connectors.
8. For every paragraph in the requested scope, verify whether the first sentence is a usable topic sentence. It should let a skim reader recover the paragraph's claim without reading the body. If it is generic ("In this section..." / "Table 2 presents..." / "Next we discuss..."), flag it as a `topic sentence` issue and set the next-draft task: turn the opener into the paragraph's actual takeaway.
9. For every new concept, metric, method name, or geometric/metaphorical term, check whether the paragraph gives an intuition before relying on it. If not, flag `cognitive load` or `intuition gap`.
10. For every claim that feels like a jump, ask the missing "why?" question. If the author skipped the reason, flag `missing why`.
11. For every paragraph, decide whether it should stay, merge, split, move, or be deleted. If the paragraph's job is wrong, write a `paragraph surgery` row rather than only polishing its sentences.

For a focused section, inspect every sentence and annotate every substantive issue. For a full paper, inspect every visible paragraph and provide margin-note rows for all substantive issues in that paragraph. If a paragraph has no substantive issue, count it in the coverage receipt rather than rendering a `clean` row.

### Per-Paragraph Coverage Rule

Every paragraph in the requested scope must be inspected. Paragraphs with substantive issues produce margin-note rows. Paragraphs without substantive issues must not produce visible `clean` rows in the student-facing report; instead, record them in the Coverage Receipt as clean/no-issue counts, and optionally in a machine-readable coverage artifact if needed for auditability. Silent skipping is not allowed because it is indistinguishable from forgetting to check.

Preferred format:

| Location | Check | Snippet | Reader friction | Writing principle | Next-draft task / self-check |
|---|---|---|---|---|---|
| Intro ¶2 | precision | "X significantly improves robustness" | 读者看到 result claim，但不知道 metric、baseline、setting、evidence strength，所以不知道该去哪张表验证。 | 显式逻辑；不要让读者猜 comparator。 | 下一稿任务：补 comparator、metric、setting、evidence strength。示例方向: `On [dataset], X improves [metric] by [amount] over [baseline] under [condition].` |
| Intro ¶3 | ambiguity | "This shows that it works in realistic settings." | 读者刚读过多个对象，`This` 和 `it` 都可能指向不同 antecedent，`realistic` 也没有定义。 | 指代清晰；低认知负担。 | 自改问题：`this` 是哪个实验？`it` 是哪个组件？什么条件让 setting realistic？ |
| Method ¶1 | grammar / agency | "The incorporation of uncertainty enables better decisions." | 读者看不到哪个 component 计算 uncertainty，也看不到哪个 decision 改变。 | direct, simple, precise prose；机制主体要可见。 | 下一稿任务：把真正执行动作的组件放到主语位置，用具体动词。 |
| Experiments ¶2 | flow / takeaway | "Table 2 presents our main results." | 读者只知道有 Table 2，不知道读表前应该期待看到什么结论。 | claim before evidence；caption/table 不让读者做算术题。 | 下一稿任务：段首先写这张表要证明的 claim，再解释数字。 |
| Intro ¶4 -> ¶5 | paragraph flow | "However, ..." | 读者被告知有 contrast，但下一段其实是另一个问题，而不是反驳前一句。 | given-new；connector 必须反映真实逻辑。 | 自改问题：到底 contrast 什么？如果没有 contrast，换连接词或补中间 premise。 |
| Figure 1 caption | caption / reader path | "Overview of the framework." | 读者看图前不知道应该从图中学到哪条 claim。 | caption 首句告诉读者该看见什么。 | 下一稿任务：caption 第一声先说 takeaway，再给 setting/metric/details。 |
| Related Work ¶4 | evidence strength | "Prior work fails to address this issue." | 读者可能立刻想到 counterexample，于是从理解 gap 转向质疑你是否公平。 | strategic framing；加入并推动已有对话。 | 下一稿任务：按 route/setting/assumption 收窄 prior-work contrast。 |
| Method ¶2 | diction | "We leverage a sophisticated framework to facilitate..." | 读者要先翻译 filler 才能看到真实动作。 | direct, simple, precise prose。 | 自改问题：这里能否用 `use`, `let`, `rank`, `select` 或另一个普通精确动词？ |
| Experiments ¶1 | topic sentence | "Table 2 presents the main results." | 跳读者只看到 table 存在，不知道这一段证明什么。 | 段首句应服务跳读。 | 下一稿任务：把 opener 改成本段 takeaway；table reference 放在 claim 后面。 |
| Abstract | emphasis placement | "...under matched budgets, which is important because our method improves risk." | 最该记住的新结果被埋在 subordinate position，读者记住的是 setup。 | stress position；改变读者理解状态。 | 自改问题：读者必须记住的新信息是什么？把它放到句子的 stress position。 |
| Intro ¶2 | cognitive load / intuition gap | "risk-coverage frontier" | 读者第一次看到 frontier，还没有 mental handle，不知道沿 frontier 移动的物理含义。 | 知识的诅咒；intuition before formalism。 | 下一稿任务：正式术语前补一个直觉桥。示例方向：回答更多问题通常会提高 answered questions 里的错误风险。 |
| Intro ¶4 | missing why | "We therefore use layerwise endpoint merging." | 读者看到 mechanism，但还不知道什么 observation 让这个 mechanism 变自然。 | 显式逻辑；洞察≠机制。 | 自改问题：你观察到了什么 failure mode，才想到 layerwise endpoint merging？ |
| Intro ¶5 | paragraph surgery | Paragraph shifts from RL work to confidence thresholding with no setup | 读者无法判断这是 baseline、related work、main foil 还是 aside。 | 一段只做一件事；discourse coherence。 | 下一稿任务：决定它的 argumentative role；移到 Related Work、删除，或先加桥说明它为什么现在出现。 |

Coverage rules:

- Cover every visible section and every visible paragraph in the requested scope. Do not impose a note quota. After each section's margin-note rows, append a one-line tally or coverage receipt entry: `Section X: N paragraphs reviewed, M paragraphs with issues, K clean/no-issue paragraphs.`
- Do not include visible `clean` rows for paragraphs, sentences, pages, figures, tables, equations, or references without substantive issues. Cover every required check dimension at least once when visible, and report no-issue coverage through counts.
- Focused section or user-requested line edit: inspect every sentence and annotate every substantive issue. Include flow notes for sentence-to-sentence, paragraph-level, and paragraph-to-paragraph relations when they reveal a revision need.
- Paragraph surgery is required: every paragraph must be classified as `keep as is`, `revise in place`, `merge`, `split`, `move`, or `delete`. Emit a margin-note row for every non-keep decision and include a surgery tally in the Coverage Receipt.
- Sentence-level deletion is part of the close pass: if a sentence repeats what the previous paragraph already established, previews what the next sentence says better, or can be deleted without breaking paragraph flow, emit `Check: redundant sentence` and propose deletion. Do not hide deletion-worthy sentences under generic concision.
- Include concrete self-revision guidance for every issue. Use full example sentences only when they are necessary to demonstrate the principle or when the user explicitly asks to leave critique mode; otherwise ask the student the precise question they must answer while revising.
- Prefer comments on transferable habits: grammar/syntax issues, unnatural or inflated diction, over-claiming, missing comparator, weak subject/verb, unclear referent, ambiguous modifier, wordiness, misplaced emphasis, buried takeaway, unsupported causal language, old-new flow failure, false connector, generic topic sentence, caption without takeaway, number/table inconsistency, and reference-list style drift.
- If only a PDF is available and exact line numbers are absent, use page/section/paragraph anchors and short snippets.

Fill the **Coverage Receipt** table. `Clean paragraphs` / no-issue counts are coverage evidence only; they should not correspond to visible `clean` rows, because student-facing reports should not render no-op comments.

**Cross-pillar tagging**: when one location triggers multiple pillars, such as diction plus overclaiming, a paragraph transition plus layout pressure, or a table sentence plus number sanity, emit one row per dimension with the same location anchor. Cross-reference sibling rows in the repair column when one edit fixes multiple issues.

### Paragraph-Level Surgery

For every paragraph in the requested scope, ask: should this paragraph exist here in this form? Surgery suggestions are first-class advisor comments, not optional polish. Use `Check: paragraph surgery` or `Check: discourse coherence`. Surgery output should be a structural skeleton, not a fully written paragraph.

- **Merge candidates**: adjacent paragraphs repeat background, define the same concept, or split one logical move into two tiny paragraphs. Output: `Merge ¶X+¶Y into one paragraph` plus a short skeleton.
- **Delete candidates**: a paragraph adds boilerplate, repeats a prior point, breaks the discourse flow, or belongs only in a generic contribution list. Contribution lists are optional; if they merely restate the body and weaken rhythm, say so.
- **Sentence-level deletion**: a single sentence repeats what the previous paragraph already established, says the same thing as the next sentence in a weaker form, or can be removed without breaking old-new flow. Output: `Delete this sentence; the next sentence carries the transition more directly.`
- **Split candidates**: a paragraph performs three or more jobs, such as defining a concept, critiquing prior work, introducing the method, and previewing experiments.
- **Move candidates**: a paragraph belongs in Related Work, Method, Experiments, or Limitations rather than where it currently appears. Especially flag comparator/baseline/alternative-method paragraphs that appear in Introduction without prior setup; these often belong in Related Work or a dedicated method-comparison subsection unless the Introduction explicitly frames their role.
- **Contribution-list check**: if the Introduction ends with a contribution list, evaluate whether each bullet is a falsifiable claim with evidence hook or merely an activity/boilerplate restatement. Source principle: contribution lists are optional, not mandatory. If the list does not add reader value, emit `paragraph surgery` with delete/compress advice.
- **Revise-in-place candidates**: the paragraph's job is right but the topic sentence, bridge, or order is wrong.

Required surgery output when a non-keep decision is visible:

| Location | Check | Current paragraph job | Surgery | Structural skeleton |
|---|---|---|---|---|
| Intro ¶1-¶2 | paragraph surgery | Both introduce abstention and risk motivation | Merge | `Deployment needs adjustable abstention; define risk/coverage only after the need is clear.` |
| Intro ¶5 | discourse coherence | Confidence thresholding appears without prior setup | Move or delete | `Move to Related Work unless the Introduction first frames it as the controllable-but-not-policy-level foil.` |
| Intro ¶6 | redundant sentence | Sentence restates the prior paragraph before a stronger transition | Delete | `Delete the weaker setup sentence and let the next sentence open the paragraph.` |
| Intro ending | paragraph surgery | Contribution list repeats the body without evidence hooks | Delete or compress | `Keep only bullets that are falsifiable claims with metric/dataset/evidence hooks.` |

## PDF/Layout Notes

Use this pass whenever the user asks to actually revise a paper, judge visual polish, or review a rendered PDF. The PDF is the source of truth for reader-facing layout; LaTeX source alone cannot reveal page rhythm, line breaks, figure placement, or visual balance. To inspect layout, visually render/open the PDF with the host platform's PDF Read/view/render capability. `scripts/extract_paper_text.py` and `pdftotext` strip layout; do not use extracted plain text as evidence for layout judgments.

For long PDFs, do not try to visually read the whole document in one call. Layout coverage must be complete for the requested PDF scope:

- Read every PDF page in chunks, such as pages 1-10, 11-20, and so on when the PDF reader has a page limit.
- For each page, inspect page rhythm, headings, figure/table placement, caption proximity, widows/orphans, and whitespace balance. Emit PDF/Layout Notes rows only for substantive issues; pages without issues are represented by clean/no-issue counts in the Coverage Receipt.
- The Coverage Receipt must include page coverage: pages reviewed, pages with issues, clean pages, and pages skipped. `Skipped` must be 0 for a completed layout scope.
- If output is too large, split by page range into parts; never sample pages to fit one report.
- If the user explicitly restricts the scope to pages 3-5, only pages 3-5 need page-complete coverage, and the Coverage Receipt must state that limited scope.

Check:

- Page-level reading flow: headings stranded near page/column bottoms, awkward page breaks, paragraphs whose final line leaves only one word, and dense pages with no breathing room.
- Figures/tables: placement near first mention, caption proximity, caption as takeaway, readable labels, consistent visual dictionary, units/directions, and whether the figure/table can be understood without hunting through text.
- Typography and spacing: cramped equations, overfull-looking lines, excessive vertical gaps, inconsistent table spacing, crowded legends, and equations/tables that interrupt the paragraph logic.
- Skimmability: first page, section openings, figure captions, and table titles should let a reviewer recover the story quickly.

When both source and PDF are available, cite PDF page/location for the reader-facing problem and use LaTeX source only to propose the likely fix. If no PDF is available, ask for one when layout matters.

Severity hint: unreadable main figures/tables, captions that hide the main evidence, or layout that prevents a reviewer from following the central claim can be `Major`; local spacing, widows/orphans, lonely last words, and minor whitespace balance are usually `Polish` unless they create real readability failure.

## Paper-Type Calibration

All papers need a central claim, evidence, and boundary, but evidence shape differs.

- **Method paper**: main results, strong baselines, fair budgets, ablations, trade-offs, failure boundaries.
- **Analysis/understanding paper**: stable patterns, controls, counterfactuals, mechanism explanations, boundary conditions.
- **Benchmark/dataset/resource paper**: construction protocol, coverage, annotation quality, bias analysis, representative baselines, use cases, limitations.
- **Systems paper**: end-to-end utility, throughput/latency/cost/stability, deployment constraints, reliability, operational trade-offs.
- **Theory paper**: definitions, assumptions, theorem/proof correctness, tightness, counterexamples, relation to prior results.

For mixed papers, name the dominant review contract and the secondary contract. Example: a method + benchmark paper needs both fair method comparison and resource construction/coverage evidence.

Do not penalize a draft for lacking every empirical-ML convention when the paper type calls for a different evidence shape.

## Checklist Items

Use these items inside the Reader-Journey passes. They are not a separate review order.

### 1. One Central Claim

- **Fail signals**: title, abstract, intro ending, Figure 1, main table, and conclusion sell different stories; contribution list contains unrelated mini-papers; reader cannot say "if you remember one sentence, remember this".
- **Severity hint**: `Blocker` when there are multiple central updates or no recoverable central claim; `Major` when the claim exists but is inconsistently foregrounded.
- **Repair**: force a one-sentence paper claim: "In [setting/problem], we use [core idea] to address [core difficulty], supported by [evidence], within [boundary]." Align title, abstract result sentence, intro ending, Figure 1, main results, and conclusion to it.

### 2. Knowledge Increment and Gap Depth

- **Fail signals**: gap is only "X has not been applied to Y", "A and B have not been combined", or "benchmark score is slightly lower"; the paper says what it built but not what reader belief changes; mechanism is described without the insight that makes the mechanism necessary.
- **Severity hint**: `Blocker` when novelty/value cannot be stated beyond surface combination; `Major` when the gap is real but buried or shallowly framed.
- **Repair**: state the before/after update: "Before this paper, readers would believe __; after this paper, they should believe __." Separate insight from mechanism: what did the authors notice about why prior routes fail, and what mechanism uses that insight? Pressure-test the gap by hiding dataset/task/method names.

### 2b. Strategic Framing and Positioning

- **Fail signals**: the paper describes prior work in a way that is technically plausible but strategically bad for this paper; the framing accidentally makes the paper look incremental, unfair, or like it solves a different problem; the introduction treats a baseline/related-work family as a random detour rather than as the necessary foil.
- **Severity hint**: `Major` when the framing weakens the paper's novelty or invites an obvious rejection; `Minor` when the positioning is correct but not yet persuasive.
- **Next-draft task**: ask "what story is most favorable while still fair?" Reframe prior work by the role it plays in the paper's argument: strong-but-not-controllable, controllable-but-not-policy-level, accurate-but-expensive, broad-but-shallow, etc. If the current framing is not true to the cited papers or not friendly to the paper's own contribution, change the contrast so it describes the cited work fairly while making this paper's need visible.
- **Advisor probe**: if a sentence about prior work makes the reader ask "then why is your paper needed?", flag `strategic framing`, not just diction.

### 3. What / Why / Gap / Idea / Evidence / Boundary

- **Fail signals**: first page lacks problem pressure; "why important" is generic; "why now" is absent; boundary/non-goals appear only in rebuttal-like language or not at all.
- **Severity hint**: `Blocker` when What/GAP/Idea/Evidence cannot be recovered; `Major` when one or two slots are implicit.
- **Repair**: add or move sentences so the first page explicitly answers all six slots. Use an ABT (And-But-Therefore) check when the introduction lacks tension: And = current consensus/routes, But = hard failure or changed condition, Therefore = paper idea. For mature drafts, make these slots visible in paragraph openings and captions, not just buried prose.

### 4. Reader-First Structure

- **Fail signals**: paper follows research chronology; sections start with details before a map; paragraphs do multiple jobs; key takeaways appear mid-paragraph; abstract/intro/conclusion repeat rather than divide labor.
- **Severity hint**: `Blocker` when the reader path is unrecoverable; `Major` when the story exists but has high cognitive load.
- **Next-draft task**: section openings should state each section's job; extract paragraph first sentences and check whether they form a coherent elevator pitch; move takeaways to visible positions.
- **Detection heuristic**: actually extract paragraph first sentences for the target section when structure is in doubt. Present them as bullets and ask whether they form a coherent mini-talk. If they are generic, repeated, or jump topics, the section likely lacks reader-first structure.

### 5. First Page and Abstract

- **Fail signals**: abstract omits problem/gap/evidence/meaning; first page spends too long on broad background; results lack dataset/metric/baseline/setting; contribution bullets are activities instead of verifiable claims; title is vague, marketing-heavy, dishonest about scope, or hard to search.
- **Severity hint**: `Blocker` when the first page does not establish the paper; `Major` when the paper is understandable only after later sections.
- **Repair**: title should be clear, honest, searchable, and aligned with the central claim. Abstract should usually cover Problem -> Gap/Idea -> Method -> Results -> Meaning. Results must be scoped and factual. Contribution bullets should be falsifiable claims with evidence hooks, not activity reports.

### 6. Claim-Evidence Alignment

- **Fail signals**: abstract/introduction claims have no matching figure/table/experiment/analysis/proof; evidence exists but is hidden in appendix; claim is stronger than evidence; small gains are presented as broad superiority.
- **Severity hint**: `Blocker` for unsupported main claims; `Major` for hidden, weak, or mismatched evidence.
- **Repair**: make a claim-evidence map. For each claim, mark evidence absent, evidence present but not foregrounded, or evidence present but too weak. Narrow claims or add evidence.

### 7. Related Work as Coordinates

- **Fail signals**: chronological "A did X, B did Y"; citation walls; prior work categories do not match experiment baselines; missing recent representative work; unfair strawman language.
- **Severity hint**: `Major` when positioning or baseline logic is unclear; `Blocker` if the paper's claimed gap depends on an inaccurate prior-work map.
- **Repair**: group work by assumptions, routes, settings, and boundaries. End each group with a positioning sentence that leads to the paper's gap. Explain baseline omissions.

### 8. Method Clarity

- **Fail signals**: method reads like code translation; formulas appear before the system map; novelty is mixed with standard components; symbols/terms used before definition; complex method lacks running example; important formulas lack natural-language interpretation; tensor shapes or input/output contracts are unclear where relevant; pseudocode exposes Python noise instead of logic.
- **Severity hint**: `Major` for hard-to-follow method; `Blocker` if reproducibility or claimed novelty is not understandable.
- **Repair**: open with input -> key mechanism -> output. Separate existing components from new contributions. Define terms before use. Add natural-language explanation after important formulas and a running/toy example when complexity is high. Use one stable notation contract; mark important tensor shapes at first use when helpful.

### 8b. Insight vs Mechanism Separation

- **Fail signals**: the method section explains every mechanical step but never states the insight that made this mechanism natural; the method appears to fall from the sky; the introduction says what the method does but not what the authors noticed about the problem that motivated it.
- **Severity hint**: `Major` when the method has no recoverable insight layer; `Minor` when the insight exists but is buried under implementation details.
- **Repair**: write an explicit insight sentence before the mechanism: `We observed that <prior route failure / structural property>; this suggests <design principle>; therefore we <mechanism>.` If this sentence cannot be written from the manuscript, say the paper currently has a mechanism but not yet an articulated insight.
- **Reviewer probe**: the `deus ex machina` smell. If the method feels mechanically inserted rather than motivated by an observation/hypothesis chain, flag `missing why` or `insight vs mechanism` even when the method is technically sound.

### 9. Experiments as Evidence Chain

- **Fail signals**: experiments are organized by table number; no explicit research questions; weak/missing baselines; unfair budgets; no variance/stability for small gains; ablations do not test the central mechanism; failure cases/limitations absent; text restates tables instead of interpreting patterns; numerical claims in prose do not survive recomputation against the tables.
- **Severity hint**: `Blocker` when main empirical claim is not supported fairly; `Major` for missing secondary evidence or unclear experiment narrative.
- **Repair**: organize experiments around 3-4 questions tied to the central claim. For each result, state setting, metric, baseline, budget, aggregation, and boundary. Add or foreground ablation, robustness, cost/trade-off, failure, and reproducibility evidence as needed.

### 10. Figures, Tables, and Captions

- **Fail signals**: figure/table serves multiple unclear claims; caption is only a noun phrase; units/directions/deltas require reader calculation; visual dictionary changes across figures; first figure is an opaque architecture hairball rather than a usable visual abstract; plot fonts/markers/line widths/legends look inconsistent with the paper; text is rasterized or unreadable in the final PDF.
- **Severity hint**: `Major` when main evidence is hard to read; `Minor` for local table/caption cleanup.
- **Repair**: each figure/table/equation should serve one core claim. Caption first sentence should state what to learn, then setting/metric/object/comparison/statistical details. Add direct labels, units, arrows, deltas, consistent colors/markers, and booktabs-style tables where appropriate. Check final PDF readability, visual dictionary consistency, grayscale/colorblind robustness, squint-test hierarchy, and whether graph/table typography feels like part of the paper.
- **Per-object coverage rule**: inspect every visible figure, table, and display equation in the requested scope. Render rows only for substantive issues in the Issue Index, Deep Reading Notes, or Submission Readiness / PDF layout notes. Objects without issues are counted as clean/no-issue objects in the Coverage Receipt, not shown as visible `clean` rows. The Coverage Receipt must count figures, tables, equations, objects with issues, clean objects, and skipped objects.

### 10b. Numerical Sanity in Tables and Cross-References

- **Fail signals**: row/column averages, totals, deltas, relative improvements, percentages, ranks, bold/underline best markers, or "wins on N tasks" counts do not match visible table cells; numbers cited in prose disagree with the source table/figure; the same baseline/dataset/model has unexplained cross-table drift; impossible or suspicious values appear, such as precision/recall/AUC > 1, percentages summing beyond the stated denominator, all-zero std over seeds, or ablations that dominate the full model everywhere; units, decimal-vs-percent notation, decimal places, or macro/micro aggregation drift within one table.
- **Severity hint**: `Blocker` when a wrong number changes the sign of the main claim; `Major` when the inconsistency is real but the qualitative claim may survive; `Minor` for unit, precision, or bolding cleanup.
- **Repair**: double-check all visible numerical information before trusting the takeaway. Recompute every visible row/column average, total, delta, relative gain, percentage, rank, best/second-best marker, and win count in every visible table. Cross-check every number cited in abstract, introduction, experiment text, captions, conclusion, and appendix against its source table/figure cell. If raw data, seed-level results, or calculation scripts are needed but unavailable, state that limitation explicitly and ask for them; do not present a partial spot-check as complete verification.
- **Reviewer method**: for each visible table, traverse every numerical cell and any derived summary attached to it. Then trace each reused number into prose/caption/appendix and verify it appears consistently in any other table or figure that reuses it. If the visible output cannot fit the full double-check record, split the report into parts; do not replace the full record with discrepancy-only sampling.
- **Using extraction signals**: when `scripts/extract_paper_text.py` emits `Table Numeric Recalculation Signals`, quote the concrete values. A good finding says "Table 1, Method A Score X: reported 95.77; visible arithmetic mean of the preceding cells is 95.52; delta +0.25; if this is weighted/micro aggregation, the denominator must be stated." Do **not** collapse this to "Score X 有偏差" when the signal gives reported/computed/delta values. The script output is a signal, not a verdict: decide severity only after checking whether the manuscript defines a non-arithmetic aggregation.

### 10c. Symbol and Macro Consistency Signals

Use this as the lightweight method/notation audit. Do not expect scripts to prove equation correctness; scripts may surface first-use, reuse, and macro drift signals, while the advisor judges the method.

- **Fail signals**: symbol first used before definition; same symbol reused for different objects; macro and rendered name drift; nearby equations mix scalar/vector/matrix quantities without prose explaining shape; algorithm variable names do not match the method section; trainable parameters, stop-gradient, or update target are ambiguous.
- **Severity hint**: `Blocker` when a core method equation or algorithm cannot be implemented as written; `Major` when notation ambiguity affects reproducibility or reader trust; `Minor` for local notation cleanup.
- **Reviewer method**: build a notation registry for method-critical symbols: symbol, meaning, type/shape when inferable, first definition, later reuse locations, and drift/conflict. For every display equation central to the method, ask whether a reader could transcribe it into pseudocode without filling in unstated decisions. Emit one finding per missing decision.
- **Tool boundary**: deterministic tools may emit symbol/macro consistency **signals** such as undefined first use, inconsistent macro expansion, or repeated symbols in incompatible contexts. They must not label an equation correct/incorrect by themselves.

When `scripts/extract_paper_text.py` emits `Symbol and Macro Consistency Signals`, quote the concrete signal in the finding, e.g. "Macro `\risk` has two visible expansions" or "`\epsilon` and `\varepsilon` both appear in display equations." Then explain what the author must verify in prose, notation, or algorithm. Do not write "the equation is wrong" unless the manuscript reading independently establishes that.

## Calibration Loop

Use this when improving Ariadne itself or comparing two generated reports for the same paper.

1. Run the same paper/review prompt twice, ideally with the same requested scope and artifact set.
2. Save each run's `findings.json`.
3. Run `scripts/calibrate_review_runs.py run1/findings.json run2/findings.json`.
4. Any same-finding severity drift is a calibration issue. Inspect whether the cause is vague severity rationale, unstable problem typing, missing evidence basis, or genuine ambiguity.
5. Record the lesson as a fixture, checklist rule, or known blind spot. The goal is not deterministic wording; the goal is stable severity and stable high-risk findings.

### 11. Precision, Flow, and Style

- **Fail signals**: key claims omit object/scope/condition/comparator/metric/denominator/evidence strength/boundary; causal verbs exceed evidence; "robust", "efficient", "generalizes", "significant", or "scales" are unscoped; pronouns and modifiers are ambiguous; abstract nouns replace actions.
- **Severity hint**: `Major` when imprecision changes the claim or misleads; `Minor` for local flow/style issues.
- **Repair**: first write the precise version, then compress. Keep necessary qualifiers. Use concrete subjects, early verbs, stable terminology, and connectors that match the actual logic.

#### Precision Pass Scan Order

1. Scan title, abstract result sentence, contribution bullets, intro ending, experiment takeaways, caption first sentences, and conclusion first paragraph.
2. For each key claim, fill these slots: object, scope, condition, comparator, metric/denominator, evidence strength, boundary.
3. Mark missing slots before rewriting.
4. Group repeated issues into patterns and put the pattern + repair rule into **Local Patterns / 共性问题汇总**. Then create one **Deep Reading Notes / Sentence-Level Margin Notes** row per concrete instance; every occurrence of the pattern gets its own location-anchored row. Pattern grouping explains the habit, but it is not a substitute for per-instance markup.

#### Precision Pattern Library

- **Unscoped comparison**
  - Pattern: "improves", "outperforms", "is better", "reduces cost", "more robust" without baseline, metric, setting, or denominator.
  - Diagnosis: reader cannot tell what comparison the evidence must support.
  - Tighten: "On [dataset/setting], X improves [metric] by [amount] over [baseline] under [budget/condition]."
- **Over-broad generalization**
  - Pattern: "generalizes", "works across tasks", "is robust", "scales well" based on a narrow set of experiments.
  - Diagnosis: claim scope exceeds evidence scope.
  - Tighten: "Across the [N] evaluated [task family] benchmarks, ..." or "within [condition], ..."
- **Causal verb stronger than evidence**
  - Pattern: "proves", "demonstrates that X causes Y", "because" when the paper only has correlation/ablation/descriptive analysis.
  - Diagnosis: evidence strength is overstated.
  - Tighten: use "suggests", "is consistent with", "supports the hypothesis that", or add the missing causal evidence.
- **Method agency unclear**
  - Pattern: passive or nominalized sentences hide what component does what: "A selection is performed", "the incorporation of features enables..."
  - Diagnosis: mechanism and responsibility are hard to recover.
  - Tighten: "The selector ranks candidate passages using [signal], then the aggregator ..."
- **Related-work gap too absolute**
  - Pattern: "Previous work ignores/fails/cannot..." without setting and boundary.
  - Diagnosis: likely strawman; reviewer can name exceptions.
  - Tighten: "Most retrieval-augmented QA systems optimize [X], but under [setting] they do not explicitly model [Y]."
- **Dangling pronoun or label**
  - Pattern: "this", "it", "they", "the above method", "our framework" after multiple possible referents.
  - Diagnosis: reader must resolve referents manually.
  - Tighten: replace with "this reranking result", "the noise-aware selector", or the precise object.
- **Nominalization / hidden verb**
  - Pattern: "the determination of X", "the application of Y enables...", "an improvement is observed", "the utilization of..."
  - Diagnosis: the main actor and action are buried inside nouns, so mechanism and responsibility become harder to recover.
  - Tighten: "X determines...", "applying Y enables...", "the selector improves...", or another concrete subject + active verb form.
- **Filler intensifier without statistical or practical scale**
  - Pattern: "significant gain", "substantial improvement", "considerable reduction", "dramatically better" without p-value/CI/effect size or concrete magnitude.
  - Diagnosis: "significant" may imply statistical significance, and other intensifiers substitute attitude for evidence.
  - Tighten: give the actual magnitude and statistical basis when available, e.g. "2.1 EM points, p < 0.05 over 5 seeds"; otherwise use scoped factual language such as "a 2.1-point gain" or "a sizable but untested gain".

#### Flow Pattern Library

- **Old-new order failure**
  - Pattern: a sentence opens with a new object before reconnecting to the previous sentence.
  - Diagnosis: the reader cannot see why this sentence follows from the last one.
  - Repair: move the shared/old concept to the beginning and place the new claim or contrast at the end.
- **Claim without intuition**
  - Pattern: a new technical term, metric, geometric metaphor, or design claim is introduced formally but without a one-sentence intuitive explanation.
  - Diagnosis: the reader has no mental handle and must carry the term by memory, raising cognitive load on every later occurrence.
  - Repair: add a physical/workflow interpretation, tiny example, or "Intuitively..." bridge before relying on the term.
- **Missing why step**
  - Pattern: the paragraph jumps from observation to solution, from prior-work failure to method, or from result to conclusion without the middle reason.
  - Diagnosis: the reader can follow the grammar but not the reasoning chain.
  - Repair: insert the missing premise: why this problem matters, why this method is the right response, or why this evidence supports the claim.
- **Misplaced emphasis**
  - Pattern: the most important new information sits in the middle of a sentence, buried before subordinate clauses, or the paragraph takeaway hides after several support sentences.
  - Diagnosis: readers attend most to first/last positions; burying the news dilutes the intended point.
  - Repair: move the new claim to the sentence's stress position, usually the end, or to the paragraph's first sentence; demote setup, caveats, and qualifiers to the middle.
- **Delayed verb / overloaded subject**
  - Pattern: a long subject phrase with clauses, conditions, and citations delays the main verb.
  - Diagnosis: the reader loses the sentence action before reaching the predicate.
  - Repair: split the sentence or move conditions after the main verb.
- **Multiple paragraph jobs**
  - Pattern: one paragraph defines a concept, critiques prior work, introduces the method, and previews experiments.
  - Diagnosis: the paragraph has no stable task.
  - Repair: split into definition, gap, method transition, or evidence paragraphs; make each paragraph's first sentence name its job.
- **Generic topic sentence**
  - Pattern: "We next describe our method", "Table 2 presents results", or "This section discusses..." as the opening move.
  - Diagnosis: the sentence names an object but does not tell the reader what to learn.
  - Repair: replace with a takeaway sentence that states the paragraph/table/section claim.
- **False connector**
  - Pattern: "therefore", "however", "moreover", or "in contrast" marks a relation not actually supported by the surrounding sentences.
  - Diagnosis: the prose sounds smooth while the reasoning jumps.
  - Repair: use the accurate relation, add the missing premise, or reorder the sentences.
- **Discourse detour**
  - Pattern: a paragraph suddenly introduces a new family of methods, benchmark, metric, or motivation that has not been set up by the prior paragraphs.
  - Diagnosis: the reader cannot tell whether this is a baseline, related work, threat, contribution, or aside.
  - Repair: move it to the proper section, delete it if redundant, or add a bridge that names its role in the argument.

#### Diction Pattern Library

- **Pretentious word choice**
  - Pattern: "utilize" where "use" is enough; "leverage" for trivial use; "facilitate" for "let"; "endeavor to" for "try to".
  - Diagnosis: inflated diction pads the sentence and makes the author sound less direct.
  - Tighten: choose the simplest precise verb.
- **Vague abstract noun**
  - Pattern: "approach", "framework", "methodology", "paradigm", or "scheme" where the concrete component name fits.
  - Diagnosis: the reader must keep guessing what object is doing the work.
  - Tighten: name the actual component, such as "the selector", "the pAURC metric", "the noise-injection step", or "the reranker".
- **Filler academic phrase**
  - Pattern: "It is worth noting that...", "It should be emphasized that...", "In this paper, we present...", "It can be seen that...".
  - Diagnosis: the phrase adds ceremony but no information.
  - Tighten: delete it or replace it with the substantive claim.
- **Dragging adverb chain**
  - Pattern: "very significantly more robustly improved", "highly substantially better", "extremely dramatically reduces".
  - Diagnosis: stacked intensifiers sound informal and substitute attitude for evidence.
  - Tighten: give one concrete magnitude or remove the intensifier.
- **Awkward Latinate construction**
  - Pattern: "an improvement is observed", "a reduction was achieved", "the determination is made by".
  - Diagnosis: passive + nominalization hides the actor and action.
  - Tighten: use an active subject and verb: "the selector improves...", "the filter reduces...", "the judge determines...".

### 12. Story Logic and Red-Team Pass

- **Fail signals**: central claim does not follow from the stated problem/gap; method solves a nearby easier problem; experiments test performance but not the mechanism claimed in the introduction; hidden assumptions must be true for the claim to hold; title/abstract/intro/main table/Figure 1/conclusion contradict each other.
- **Severity hint**: `Blocker` when the paper's reasoning chain is broken or a likely reviewer rejection reason is unaddressed; `Major` when the chain mostly works but has hidden assumptions or unresolved contradictions.
- **Next-draft task**: explicitly test problem -> gap -> idea -> evidence -> boundary. List the top reader/reviewer objections, then mark each as answered, partly answered, or exposed. Add missing evidence, narrow the claim, move boundary text into the main story, or change the gap so it matches what the method actually solves.

For full-paper reviews, output at least one red-team finding when the paper makes a broad main claim, lacks strong baselines, has missing failure analysis, or shows a claim-evidence mismatch.

### 13. Limitations and Boundaries

- **Fail signals**: limitations are future work only; missing baseline/cost/latency/leakage/failure boundary is hidden; known trade-off is not acknowledged; non-goals are unclear.
- **Severity hint**: `Blocker` when a likely reviewer rejection reason is unaddressed; `Major` when boundary is present but too vague.
- **Repair**: list the top three likely rejection reasons. Add proactive clarification, narrowed claims, failure analysis, or limitation text in the main paper rather than relying on rebuttal.

### 14. LaTeX, Citations, and Artifact Hygiene

- **Fail signals**: TODO/TBD/XXX/lorem placeholders; `??` refs; `\cite{?}`; citation dumps; inconsistent macros, names, symbols, dataset labels, or baselines; anonymous submission leaks emails, GitHub usernames, acknowledgments, absolute paths, author metadata, or `\thanks{}`; figure/table numbers are hand-edited or untraceable.
- **Severity hint**: `Blocker` for anonymity leaks, broken references in camera-ready-like submissions, fabricated/unsupported citations, or artifact failures central to the claim; `Minor/Major` depending on visibility and risk.
- **Repair**: run extraction/build checks, resolve placeholders, use semantic filenames/macros, keep one sentence per line when practical for review, make core numbers traceable to scripts/seeds/run IDs, and ensure submitted code/supplement is documented, complete, exercisable, and anonymous.

### 14b. Reference List Style Consistency

- **Fail signals**: venue abbreviation drift (`CVPR` vs. `Conference on Computer Vision and Pattern Recognition` vs. `Proc. CVPR`); URL/DOI/eprint fields appear in some entries and not others without a clear rule; the same work is cited once as arXiv and once as the published venue version; author names, page ranges, years, publishers, or entry types use visibly different styles; workshop papers are typed as `journal` in some entries and `booktitle` in others.
- **Severity hint**: `Major` when the rendered reference list visibly looks inconsistent enough to hurt submission polish or credibility; `Minor` for local field/style drift; `Polish` for whitespace-level differences.
- **Repair**: choose one canonical rule for venue names, URL/DOI/eprint inclusion, arXiv-vs-published preference, author names, pages, and entry types. Then run one bibliography-wide sweep rather than fixing entries one by one.
- **Reviewer method**: inspect the `.bib` fields when source is available and the rendered references when PDF is available. Tabulate `booktitle`/`journal`/`url`/`doi`/`eprint`/`pages` coverage; flag fields whose presence or formatting drifts without a semantic reason.
- **Per-entry coverage rule**: output a bibliography-style table with one row per parsed or rendered reference entry in the requested scope. Include columns for entry key/number, type, venue/booktitle/journal form, URL, DOI, eprint/arXiv, pages format, author format when visible, and status. Mark each cell with the canonical value or drift token. A reader should see all entries at a glance, not only the entries that drift.

### 15. Obvious Error and Consistency Sweep

- **Fail signals**: numbers in abstract/intro/conclusion disagree with tables/figures; table means/averages, deltas, percentages, ranks, bold/underline best markers, or "wins on N tasks" counts do not match the visible cells; macro vs. micro averages or denominators are unstated; method/dataset/model/baseline/metric names drift; figure/table references point to the wrong object; caption takeaway conflicts with visual evidence; contribution count differs across abstract/intro/conclusion; core numbers lack script/seed/run provenance.
- **Severity hint**: `Blocker` when a mismatch changes the main claim, looks like fabrication, or breaks anonymity/submission credibility; `Major` when incorrect arithmetic or inconsistencies weaken trust in evidence; `Minor` for local naming drift.
- **Repair**: run a final consistency sweep across prose, tables, figures, captions, appendix, source macros, and artifact text. Recompute all visible summary numbers when feasible: means/averages, deltas, relative improvements, percentages, ranks, and win counts. State when source data is missing and only visible-cell arithmetic can be checked. Make one canonical name for each method/dataset/metric/baseline. Trace core numbers to tables, scripts, seeds, or run IDs before polishing sentences.

### 16. Skimmability and Nonlinear Reading Path

- **Fail signals**: title/abstract/headings/paragraph first sentences/captions cannot reconstruct the story; section openings are generic; figure-only or 3-minute skim tests fail; important caveats are hidden where a nonlinear reviewer will miss them.
- **Severity hint**: `Major` when a reviewer must linearly read the whole paper to recover the claim; `Minor` when local headings/captions need tightening.
- **Repair**: create a fast-reading channel: informative headings, strong paragraph first sentences, visible takeaways, self-explanatory captions, and proactive clarification of likely objections. Extract first sentences from Introduction/Method/Experiments and check whether they form a coherent mini-talk.

### 17. Integrated Source + Rendered PDF Review

- **Fail signals**: review is based only on `.tex` source when layout matters; final PDF has not been compiled from the entry file; source comments do not map to rendered page problems; PDF-only review invents source-level fixes.
- **Severity hint**: `Major` when layout/figure/table/page rhythm affects first impression or main evidence; `Polish` for local page hygiene that does not affect comprehension.
- **Repair**: when LaTeX is provided, compile or request the rendered PDF. Use PDF pages for reader-facing judgment: first impression, layout, figure/table readability, page breaks, skimmability. Use source for exact edits, macros, citations, TODOs, and reproducibility hygiene. If only PDF is provided, do not require source; use page anchors and state source-level limitations.

### 18. Visual System Consistency Pass

- **Fail signals**: main plots use incompatible fonts, marker sizes, line widths, legends, axis styles, or notation; `Ours`, baselines, ablations, oracle/upper-bound, or human performance change visual identity across figures; figures rely only on color; the most visually salient element is not the intended takeaway.
- **Severity hint**: `Major` when inconsistent visual encoding obscures main evidence or makes figure-only reading misleading; `Minor/Polish` for local style mismatches.
- **Repair**: define a visual dictionary for methods, baselines, ablations, upper bounds, and key variables. Check final PDF figure pages, grayscale/colorblind robustness, font/notation consistency with prose, and the squint test: the most salient visual pattern should match the intended claim.

### 19. Final PDF Layout and Page Rhythm

- **Fail signals**: page starts/ends with orphaned lines or lonely words; headings are stranded; formulas are separated from explanations; figure/table/caption units are split or crowded; page density swings from sparse to cramped; negative spacing or tiny fonts appear to fight the template.
- **Severity hint**: `Major` when layout blocks comprehension of main evidence or makes the draft look unfinished; usually `Polish` for isolated runts/widows/orphans.
- **Repair**: first revise text, paragraph boundaries, caption length, figure/table size, or float placement. Use micro-spacing only after content fixes and never in ways that break venue templates or readability.

### 20. Submission, Reproducibility, and Policy Readiness

- **Fail signals**: page limit/template/font/link/system-form mismatches; missing limitations or ethical disclosure; LLM/API work omits prompt/model version/decoding/settings/leakage risk; code/supplement lacks README, dummy run, main-result reproduction path, or anonymity cleanup.
- **Severity hint**: `Blocker` for anonymity, policy, fabricated citation, or submission-compliance failures; `Major` when reproducibility gaps weaken trust in the main evidence.
- **Repair**: check venue-specific rules at submission time. For LLM/API work, report prompts or prompt templates, model/API version, decoding parameters, sampling seeds where relevant, contamination/leakage controls, and AI assistance disclosure required by the venue. Make artifacts readable, runnable, traceable, and anonymous.

### 21. Venue Compliance Pass

- **Use when**: the user names a venue, deadline, track, workshop, or asks about submission compliance.
- **Fail signals**: review asserts venue compliance without official rules; page limit accounting is unclear; template/version/font/margins/bibliography style may be stale; required limitations/ethics/responsible research/checklist/AI-assistance disclosure sections are absent; supplementary/artifact/link/anonymity rules are not checked.
- **Severity hint**: `Blocker` for anonymity, page-limit, required-form, policy, or dual-submission violations; `Major` for missing reproducibility or disclosure items likely to affect review.
- **Repair**: if official rules are not provided, say compliance cannot be fully verified from the manuscript alone. Ask for the official CFP/author guideline link, or when browsing is available, check the official venue page and state the date checked. Verify page limit and what counts, template/version, formatting/PDF requirements, anonymity, required sections/forms, supplementary/artifact rules, link/citation restrictions, and LLM/API-specific reporting requirements.

## Coverage Discipline

For complete paper reviews, cover all layers unless the input makes a layer unavailable:

- paper-level: central claim, knowledge increment, gap depth, What/Why/Gap/Idea/Evidence/Boundary, paper type and evidence contract
- section-level: title/abstract/intro/Figure 1, Related Work, Method, Experiments, Limitations/Conclusion
- logic-level: story red-team, hidden assumptions, contradictions across title/abstract/intro/Figure 1/main table/conclusion, top likely rejection reasons
- evidence-level: claim-evidence map, baselines, fairness, variance/stability, ablations, failure cases, trade-offs, non-goals, numerical sanity in tables and text-table cross-references
- prose-level: precision, diction, emphasis placement, flow/cohesion patterns, topic-sentence quality, paragraph tasks, sentence-level margin notes when triggered
- visual/PDF-level: first impression, page-complete layout review for the requested PDF scope, skimmability, every visible figure/table/equation, captions, visual system consistency, final page layout
- source/artifact-level: LaTeX hygiene, citation correctness, per-entry reference-list style consistency, buildability, number/name/reference consistency, traceability, anonymity, reproducibility, policy/submission readiness, venue compliance when applicable

## Mini Example

**Finding:** `Major`, Abstract, result sentence.

**Diagnosis:** The sentence "Our method significantly improves robustness across tasks" is too strong and under-scoped. It does not name the task family, metric, baseline, aggregation, or evidence strength, so the reader cannot tell what claim the experiments must support.

**Repair:** Replace with a scoped result sentence, e.g. "On three noisy-retrieval QA benchmarks, the method improves exact match by 2.1 points over the strongest retrieval-augmented baseline under matched inference budgets; gains are largest when relevant evidence is sparse." Only use this wording if those facts are in the paper; otherwise narrow it further.

## Additional Output Examples

### Blocker Finding Example

**Finding:** `Blocker`, Introduction + Experiments.

**Diagnosis:** The introduction claims the paper solves "general long-context reasoning under noisy evidence", but the visible experiments only test two retrieval-QA datasets with synthetic distractors. The main claim is broader than the evidence shape.

**Reader friction / principle:** The reader can trust the experiments and still reject the conclusion, because the claimed setting and tested setting are not the same. This violates explicit logic and claim-evidence alignment.

**Repair:** Narrow the main claim to "retrieval-QA under synthetic/noisy distractors" or add evidence that covers genuinely broader long-context reasoning. Align title, abstract, intro ending, and main table caption to the narrowed setting.

### Claim-Evidence Map Example

| Claim | Visible evidence | Status | Repair |
|---|---|---|---|
| The method improves robustness under noisy retrieval. | Main table on 3 noisy-retrieval QA benchmarks; ablation of selector. | Mostly supported, needs variance if gains are small. | Add seeds/error bars or narrow "robustness" to evaluated noise conditions. |
| The selector explains why the method works. | One qualitative case study. | Too weak. | Add ablation, controlled noise slices, or soften to "suggests". |
| The approach is compute-efficient. | No latency/cost table visible. | Unsupported. | Add matched-budget comparison or remove efficiency claim. |

### Grouped Precision Pattern Example

**Pattern:** Results claims repeatedly omit comparator and setting.

**Representative snippets:** "improves robustness", "achieves better performance", "reduces hallucination".

**Diagnosis:** These claims ask the reader to infer baseline, metric, dataset, and evidence strength.

**Repair rule:** Rewrite result claims as `[object] + [metric] + [comparator] + [setting] + [boundary]`. Apply the same rule to every concrete occurrence in abstract, experiment takeaways, and captions; do not stop after a few examples when the same issue recurs.

### Keep Note Example

**Keep:** The current Figure 1 caption already states the intended takeaway before implementation details. Preserve that first-sentence structure while adding metric/baseline details; do not replace it with a generic component description.
