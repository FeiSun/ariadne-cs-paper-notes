# Ariadne Review Lenses

Use these lenses inside the Reader-Journey workflow. They describe what to notice and how to diagnose it. They are not a separate pass order.

## Severity Labels

- `Blocker`: likely to threaten acceptability or make the main claim unclear, unsupported, misleading, or non-recoverable.
- `Major`: substantially weakens persuasion, reader path, evidence alignment, or submission credibility.
- `Minor`: local clarity, precision, consistency, source hygiene, or presentation issue.
- `Polish`: helpful but not submission-critical.

When uncertain, distinguish manuscript facts from reviewer inference. Do not create a second severity system.

## Advisor Stance

- Change reader belief, not display author knowledge.
- Apply the first-page / first-day reader test.
- Make logic explicit; do not let the reader guess why a claim follows.
- Position the paper inside an existing conversation.
- Treat sections as arguments, not research logs.
- Prefer direct, simple, precise prose.
- Treat paragraphs as movable objects: delete, merge, split, move, or revise in place when needed.

## Source Principle Index

Every substantive margin note should map to exactly one source principle. Put that principle in `违反原则` / `writing_principle`. Do not use `issue_type` as the principle, and do not join several principles with `；`; a useful note should say which single rule the current sentence/paragraph/section violates. Report `notes citing source principles: N/M` in coverage.

| Source principle | Operational lens |
|---|---|
| `改变读者理解状态` | central claim, knowledge increment, claim-evidence map, story red-team |
| `低认知负担 / reader-first` | first-day reader, intuition before formalism, skimmability, PDF/layout |
| `显式逻辑，不让读者猜` | missing why, precision slots, story logic, transitions |
| `加入并推动一场已有对话` | related-work coordinates, strategic framing, baseline/evidence contract |
| `argument, not explanation or research log` | section jobs, experiments as evidence chain |
| `知识的诅咒` | page-one bridges, first-use term intuition, cognitive-load notes |
| `洞察 ≠ 机制` | knowledge increment, method motivation, insight vs mechanism |
| `先定每一层任务 / 一段只做一件事` | paragraph surgery, topic sentences, article-ordered notes |
| `句首接旧信息，句尾放新信息` | old-new flow and stress position |
| `caption 首句告诉读者该看见什么` | figure/table captions and skimmability |
| `不要让读者做翻译题/查字典题/算术题` | table readability, numerical sanity, style consistency |
| `红队式自查` | story red-team, likely rejection reasons, limitations |

## Core Paper Lenses

### Central Claim

Fail signals: title, abstract, intro ending, Figure 1, main table, and conclusion sell different stories; contribution list contains unrelated mini-papers; reader cannot state the one thing to remember.

Repair: force a one-sentence paper claim: `In [setting/problem], we use [core idea] to address [core difficulty], supported by [evidence], within [boundary].`

### Knowledge Increment and Gap

Fail signals: gap is only "X has not been applied to Y"; paper says what it built but not what reader belief changes; mechanism appears without the insight that made it necessary.

Repair: state before/after belief update. Separate insight from mechanism: what did the authors notice, and what mechanism uses that insight?

### What / Why / Gap / Idea / Evidence / Boundary

Fail signals: first page lacks problem pressure; why-important is generic; boundary appears only as rebuttal or not at all.

Repair: make all six slots visible in abstract/introduction, paragraph openings, and captions.

### Reader-First Structure

Fail signals: research chronology, details before map, paragraphs doing multiple jobs, buried takeaways, abstract/intro/conclusion repeating instead of dividing labor.

Repair: extract paragraph first sentences and ask whether they form a coherent mini-talk; move takeaways to visible positions.

### Claim-Evidence Alignment

Fail signals: abstract/introduction claims lack matching evidence; claim stronger than experiments; evidence hidden in appendix; small gains sold as broad superiority.

Repair: build a claim-evidence map. Mark evidence absent, present but hidden, present but weak, or adequately supported. Narrow claims or add evidence.

### Related Work and Strategic Framing

Fail signals: chronological list, citation walls, unfair strawman language, prior-work categories not matching baselines, framing that makes the paper look incremental or unnecessary.

Repair: group by assumptions, routes, settings, and boundaries. End each group with a positioning sentence that leads to the gap.

### Method Clarity and Insight vs Mechanism

Fail signals: method reads like code translation; formulas before system map; novelty mixed with standard components; symbols before definitions; no running example; method appears from nowhere.

Repair: open with input -> key mechanism -> output. Define terms before use. Add natural-language interpretation after important formulas. State the insight before the mechanism: `We observed <failure/property>; this suggests <design principle>; therefore we <mechanism>.`

### Experiments as Evidence Chain

Fail signals: organized by table number; no research questions; weak/missing baselines; unfair budgets; no variance for small gains; ablations do not test central mechanism; failure cases/limitations absent.

Repair: organize around 3-4 questions tied to the central claim. For each result, state setting, metric, baseline, budget, aggregation, and boundary.

### Figures, Tables, Captions

Fail signals: object serves multiple unclear claims; caption is noun phrase; units/directions/deltas require reader calculation; visual dictionary changes; fonts/markers/legends are inconsistent; main figure/table is unreadable.

Repair: each object serves one claim. Caption first sentence states what to learn, then setting/metric/comparison/statistical detail. Inspect every visible figure, table, and display equation in scope; clean objects are counted in coverage only.

### Limitations and Boundaries

Fail signals: limitations are future work only; known baseline/cost/leakage/failure boundary is hidden; non-goals are unclear.

Repair: list top likely rejection reasons and either answer them, narrow the claim, or move boundary text into the main story.

## Sentence and Paragraph Lenses

Use sentence-level margin notes for any substantive critique/review/revision request, especially detailed comments, teacher-style feedback, edits, annotations, 批注, 修改意见, 逐句 feedback, 认真批注, 像老师一样改, 细致改一下, 帮我改句子, 红笔批注.

For every visible sentence in prose scope, check:

- grammar/syntax/mechanics;
- precision slots: object, scope, condition, comparator, metric/denominator, evidence strength, boundary;
- ambiguity: referent, modifier, scope, comparator, metric, condition;
- old-new flow, connector truth, stress position;
- cognitive load and first-use term intuition;
- missing why/how/referent;
- deletion-worthy redundancy.

For every paragraph, record whether it should stay, be revised in place, merged, split, moved, or deleted. A paragraph should have one job, a useful topic sentence, and a clear bridge/takeaway.

### Precision Patterns

- **Unscoped comparison**: "improves", "outperforms", "more robust" without baseline/metric/setting/denominator. Repair: name comparator, metric, setting, boundary.
- **Over-broad generalization**: "generalizes", "works across tasks", "robust" from narrow evidence. Repair: scope to evaluated tasks/conditions.
- **Causal verb stronger than evidence**: "proves", "causes", "because" from correlation/ablation/descriptive analysis. Repair: soften or add causal evidence.
- **Method agency unclear**: passive/nominalized action hides component responsibility. Repair: concrete subject + active verb.
- **Related-work gap too absolute**: "prior work fails/ignores/cannot" without boundary. Repair: fair route/setting/assumption contrast.
- **Dangling pronoun/label**: "this/it/they/our framework" after multiple antecedents. Repair: name the object.
- **Filler intensifier**: "significant/substantial/dramatic" without magnitude/statistical basis. Repair: give concrete magnitude or remove.

### Flow Patterns

- **Old-new order failure**: sentence opens with new object before reconnecting to old information.
- **Claim without intuition**: new term, metric, metaphor, or design claim appears without mental handle.
- **Missing why step**: paragraph jumps from observation to solution, prior-work failure to method, or result to conclusion.
- **Misplaced emphasis**: takeaway buried in middle/subordinate position.
- **Delayed verb / overloaded subject**: long subject delays action.
- **Multiple paragraph jobs**: one paragraph defines, critiques, introduces method, and previews experiments.
- **Generic topic sentence**: "Table 2 presents..." or "We next describe..." without takeaway.
- **False connector**: however/therefore/moreover/in contrast misstates relation.
- **Discourse detour**: new method family, benchmark, metric, or motivation appears without role.

### Diction Patterns

- Prefer use/let/rank/select over inflated verbs when precise.
- Replace vague nouns such as approach/framework/methodology with the actual component when possible.
- Delete filler phrases such as "It is worth noting that" unless they add information.
- Replace passive nominalizations with concrete actors and actions.

## PDF/Layout Lens

Use rendered PDF as source of truth for layout, but keep the visual check page-local. For layout claims, run `scripts/check_page_layout.py` over the requested PDF page scope and inspect only escalated/ambiguous pages in the main context. Count pages with issues and clean pages through `layout_audit.json`; `Skipped` must be 0 for completed layout scope.

Check page rhythm, headings, figure/table placement, caption proximity, widows/orphans, whitespace balance, cramped equations, overfull-looking lines, crowded legends, and skimmability. Cite PDF page/location for reader-facing problems; use LaTeX source only for likely fixes.

Unreadable main evidence or layout that blocks comprehension can be `Major`; isolated spacing/widow/orphan issues are usually `Polish` unless they create real readability failure.

## Paper-Type Calibration

- **Method paper**: main results, strong baselines, fair budgets, ablations, trade-offs, failure boundaries.
- **Analysis/understanding paper**: stable patterns, controls, counterfactuals, mechanism explanations, boundaries.
- **Benchmark/dataset/resource paper**: construction protocol, coverage, annotation quality, bias analysis, representative baselines, use cases, limitations.
- **Systems paper**: end-to-end utility, throughput/latency/cost/stability, deployment constraints, operational trade-offs.
- **Theory paper**: definitions, assumptions, theorem/proof correctness, tightness, counterexamples, relation to prior results.

For mixed papers, name dominant and secondary contracts. Do not penalize a paper for lacking conventions irrelevant to its type.

## Source, References, and Submission Hygiene

Fail signals: TODO/TBD/XXX/lorem; `??` refs; `\cite{?}`; citation dumps; inconsistent macros/names/symbols/datasets/baselines; anonymity leaks; hand-edited figure/table numbers; missing artifact traceability.

For references, inspect rendered entries and `.bib` fields when source is available. Flag venue abbreviation drift, URL/DOI/eprint inconsistency, arXiv-vs-published duplication, author/page/year/publisher style drift, and entry-type inconsistency. For requested reference-list review, output one row per parsed/rendered reference entry.

For venue compliance, use official rules if provided or browsed. If not, state that compliance cannot be fully verified from the manuscript alone. Check page limit, template/version, anonymity, required sections/forms, supplement/artifact rules, link/citation restrictions, and LLM/API reporting/disclosure requirements.

## Calibration Loop

When improving Ariadne itself, generate two `findings.json` files from the same paper/scope and run `scripts/calibrate_review_runs.py run1/findings.json run2/findings.json`. Same-finding severity drift is a skill-calibration issue; inspect vague severity rationale, unstable problem type, missing evidence basis, or genuine ambiguity.
