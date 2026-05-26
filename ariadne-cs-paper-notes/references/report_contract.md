# Ariadne Report Contract

Use this file for structured JSON artifacts and the paper-reader report contract. For HTML-specific rules, also load `html_contract.md`. For strict numeric rendering, also load `numeric_contract.md`.

## Paper-Reader Order

The Reader-Journey passes are internal. Student-facing HTML now uses a paper-first shape:

1. **Paper Reader / 论文正文批注**
2. **Global Findings / 全局重要问题** only when `--full-report` is requested or the manifest declares `paper-reader-with-global-findings`
3. **Coverage Receipt / 覆盖回执**

The old workbench sections (`总评诊断`, `问题索引`, `主张证据`, `精读批注`, `提交就绪`, `共性问题`, `修改路线`) are legacy and must not be emitted by paper-reader HTML. Sentence, paragraph, and section notes belong in overlay anchors and annotation cards, not in a separate deep-reading ledger.

## Finding Ledger JSON

`findings.json` is the canonical source for core issue explanations. Include all `Blocker`, `Major`, and revision-relevant grouped `Minor/Polish`. For paper-reader overlays, keep the full teaching content here and let local annotations point back by `issue_id`; do not duplicate diagnosis, reader friction, principle, evidence basis, or self-check fields in `annotations.json`.

Use stable finding ids in `F<number>` form, such as `F1`, `F2`, `F12`. Use suffixes such as `F3a`, `F3b`, `F3c` only when splitting one grouped issue. Do not use severity-prefixed ids such as `B1`, `M3`, `N2`, or `P1`.

Every later `关联问题` links to a defined id. Later sections should write local consequence plus linked id, not repeat full diagnosis.

## Paper-Reader Annotation Artifacts

For source-derived overlay reports, prefer anchor-only annotations:

```json
{
  "issue_id": "F12",
  "target_level": "sentence",
  "sentence_id": "s-introduction-p003-s002",
  "short": "机制结论过满",
  "title": "机制主张强于证据"
}
```

`findings.json` stores the full review prose once. `annotations.json` stores only anchor, short UI label, and current source artifact/hash. Render with `scripts/render_paper_html.py --annotations annotations.json --findings findings.json`; the renderer joins the teaching content at HTML generation time.

For source-derived paper-reader annotation pages, render from the exact canonical source artifact used for review-unit extraction. Leave `--full-report` off for overlay plus coverage; add `--full-report` only when the user wants the extra `#global-findings` section. `--issues-dir` may contribute display-facing specialist overlays such as layout, numeric, and figure/caption, but hidden source hygiene, hidden reference metadata, and macro-only symbol findings should remain in structured artifacts as `render_visibility: artifact_only` unless they visibly affect the rendered paper:

```bash
scripts/render_paper_html.py <main.tex> \
  --raw-html <stem>.source.html \
  --reuse-raw-html \
  --annotations <bundle>/annotations.json \
  --findings <bundle>/findings.json \
  --coverage <bundle>/coverage.json \
  --issues-dir <bundle>/issue_artifacts \
  --output <stem>.html
```

With `--full-report`, `render_manifest.json` should declare `paper-reader`, `global-findings`, and `coverage-receipt`; without it, declare only `paper-reader` and `coverage-receipt`. The renderer, not an LLM, must emit the sections declared in `render_manifest.json`. If `--reuse-raw-html` is omitted during final rendering, the renderer may regenerate source HTML and change anchors; artifact audit should treat that as unsafe for source-derived overlay reports.

## Global Findings

Global findings are not a re-rendered issue index. Include only independent whole-paper Major/Blocker critiques, for example:

- novelty or positioning weakness;
- story-logic / thesis-to-evidence gap;
- experiment-design or evaluation-independence threat;
- paper-wide claim calibration and limitation visibility.

Bind local issues to their real location instead. A judge-risk finding about `LLM-as-a-Judge Verification` should be a section/paragraph annotation there, not a global finding. LaTeX macro, hidden BibTeX, and source-hygiene findings should stay out of student-facing global findings unless they visibly affect the rendered paper or submission checklist.

## Claim-Evidence JSON

Record when abstract/main claims are available:

- Abstract Promise Tracking;
- Claim-Evidence Map;
- Story Logic and Red-Team Pass;
- title/abstract/introduction/conclusion alignment;
- skim-test observations from Pass 1 when they affect recoverability.

Every abstract sentence containing a number, causal verb, novelty/scope claim, "first", "significant", "state-of-the-art", "robust", "efficient", "general", or "all/across" should appear in `claims.json` or the argument map. Do not emit a separate top-level claim-evidence HTML table for paper-reader reports.

## Overlay Reading Notes

Organize in manuscript order through paper-reader anchors. Do not split `分章批注`, `逐段手术`, and `句子级批注` into separate top-level HTML sections.

For each visible section:

1. section reflection: `读后一句话`, `章节任务是否对齐`, `建议结构`, `未闭合问题`, `关联问题`, `下一稿任务`;
2. paragraph records: paragraph job, surgery decision, why, linked finding, next-draft structural task;
3. sentence rows under the paragraph for every substantive sentence issue.

Do not render visible `clean` rows. Clean units appear in coverage counts and optional machine-readable artifacts.

## Submission Readiness Signals

Keep cross-cutting artifact checks in issue artifacts and overlay/global annotations:

- numerical/table arithmetic and table completeness;
- formula/symbol/algorithm consistency;
- figures/tables/captions and visual system;
- PDF/page layout;
- references/citations, checklist, venue compliance, anonymity, source hygiene;
- Polish Sweep.

Use linked finding ids and concrete values; avoid repeating finding diagnosis in multiple visible places.

## Local Patterns

Summarize repeated writing habits as findings only when they affect the reader across multiple anchors. Give representative locations through `target_anchors` and do not relist every instance in HTML.

## Revision Plan Data

If a revision plan is requested separately, save it as structured data or a separate artifact, not as a default paper-reader section. Suggested fields:

- `优先级`: `P0`, `P1`, `P2`, `P3`
- `任务`
- `关联问题`
- `负责人/区域`
- `工作量`
- `验收方式`

Keep rows short and link finding ids instead of repeating diagnoses.

## Coverage Receipt and Artifacts

Include:

- Pass 0-6 status;
- body-backed counts for sentences, paragraphs, sections, pages, tables, figures, equations, references, findings, grouped polish;
- `Skipped = 0` for completed scope or explicit `pending in <part>`;
- QA gate, severity audit, coverage consistency, linked-finding integrity, numerical concreteness, artifact audit status;
- artifact paths and known blind spots;
- source-principle tally: `notes citing source principles: N/M`.

Suggested coverage table:

| Unit | Total | Reviewed | With issues | Clean | Skipped | Pending in |
|---|---:|---:|---:|---:|---:|---|

Suggested body-backed count table:

| Claimed unit | Claimed count | Body section / selector | Actual count | Status |
|---|---:|---|---:|---|

## Finding Schema

Every finding object in `findings.json` should contain:

- `id`
- `severity`: `Blocker`, `Major`, `Minor`, `Polish`
- `location`
- `snippet` when useful
- `diagnosis`
- `reader_friction`
- `writing_principle`: one atomic principle, not an issue category or a bundle of principles
- `self_check` or `next_draft_question`: a question the author can use to diagnose the revision
- `evidence_basis`
- `verification_method`

For findings derived from issue artifacts, prefer short provenance references over repeating raw evidence:

- `source_issue_ids`: ids from `prose_issues.jsonl`, `whole_paper_findings.jsonl`, or specialist `*_issues.json`
- `evidence_refs`: raw-audit observation ids, BibTeX keys, table ids, page ids, or source line references
- `source_artifacts`: paths or ids for the curated issue artifact and any tool-only raw audit

Cross-section findings may use:

- `target_anchors`: ordered sentence/paragraph/section anchors involved in the problem
- `spans_sections`: `true` when the finding depends on multiple manuscript locations
- `primary_anchor`: the preferred visible anchor for default overlay focus

Do not collapse a cross-section problem to a single sentence anchor when the diagnosis depends on multiple places.

For `Blocker` and `Major`, also require:

- `confidence`: `high`, `medium`, or `low`
- `severity_rationale`
- `downgrade_condition`

For numeric/table findings, include:

- `reported_value`
- `visible_computed_value`
- `delta`
- `aggregation_caveat`

## Issue Artifact Schema

Specialists and Prose Review phases write curated issue artifacts. Raw audits are tool-only; issue artifacts are the model-readable/report-renderable layer.

Minimum shape:

```json
{
  "artifact_type": "ariadne_issue_artifact",
  "domain": "layout",
  "context_policy": "model_readable_issue_only",
  "producer": "layout_agent",
  "status": "completed",
  "skip_reason": "",
  "source_artifacts": [
    {
      "path": "layout_audit.json",
      "hash": "sha256:...",
      "context_policy": "tool_only"
    }
  ],
  "coverage": {
    "checked": 30,
    "issues": 2,
    "skipped": 0
  },
  "issues": [
    {
      "local_id": "L1",
      "severity": "Major",
      "issue_type": "layout",
      "title": "...",
      "diagnosis": "...",
      "reader_friction": "...",
      "writing_principle": "低认知负担 / reader-first",
      "self_check": "...",
      "evidence_refs": ["layout-p012-003"],
      "recommendation": "...",
      "confidence": "medium",
      "render_hint": {
        "anchor": "page:12",
        "target_level": "paper"
      }
    }
  ]
}
```

Allowed `domain` values include `prose`, `whole_paper`, `layout`, `numeric`, `reference`, `symbol`, `source_hygiene`, `figure_caption`, and `polish`. Empty stubs are valid when `status` is `skipped`, `issues` is empty, and `skip_reason` explains the gate.

Every non-empty issue must include `local_id`, `severity`, `issue_type`, `title`, `diagnosis`, `evidence_refs`, `confidence`, and `render_hint.display_group`. `Blocker` and `Major` issues should also include `reader_friction`, `writing_principle`, `self_check`, `severity_rationale`, and `downgrade_condition` unless a deterministic compiler will add them from a linked finding.

Issue artifacts may set `render_visibility: "student_visible"` or `render_visibility: "artifact_only"` per issue. When omitted, prose, whole-paper, layout, numeric, and figure/caption issues are student-visible by default; reference, source-hygiene, symbol, and polish issues are artifact-only by default unless explicitly promoted because they visibly affect the rendered paper. Artifact-only findings remain in `findings.json` and `compiled_issue_index.json`, but the compiler must not create overlay annotations for them and the derivative manifest should list their final ids in `deferred_findings`.

The deterministic compiler maps local ids to stable `F<number>` ids, deduplicates related issues, preserves `source_issue_ids`, and joins issue artifacts into `findings.json`, `annotations.json`, `claims.json`, and coverage. Review agents and specialists should not assign final `F<number>` ids unless the compiler is unavailable.

`scripts/compile_review_artifacts.py` is the canonical compiler for issue artifacts. It reads `issue_artifacts/`, writes final `findings.json` and anchor-only `annotations.json`, and writes `issue_artifacts/compiled_issue_index.json`. The compiled index records source artifact hashes, normalized JSONL shards, `source_issue_id -> finding_id` mapping, and dedup groups so audits can verify that JSONL shards were handled by deterministic code instead of being re-read by the orchestrator.

### Compiler Dedup Rules

The compiler should deduplicate issue artifacts conservatively:

- Same or overlapping `evidence_refs` plus same domain and same diagnosis type: merge into one finding, preserving all `source_issue_ids`.
- Same anchor plus different domains: usually keep separate findings and add `related_issue_ids`; merge only when the reader-facing diagnosis and next action are identical.
- Prose issue and specialist issue at the same anchor: prose finding stays primary when it explains the reader/argument consequence; specialist issue becomes provenance, a sub-finding, or a linked overlay/global finding.
- Same table/figure/page but different failure modes, such as layout overflow versus caption takeaway: keep separate findings and cross-link.
- Whole-paper Phase B findings may absorb multiple lower-level issues only when the lower-level findings would be redundant after synthesis; otherwise link them with `related_issue_ids`.

When merging, choose the highest severity unless a written `severity_rationale` justifies downgrading the combined finding. Never drop a `Blocker`/`Major` source issue without preserving it in `source_issue_ids` or `related_issue_ids`.

### Prose Phase Artifacts

Phase A artifacts:

- `cold_skim_frame.json`: first-day reader recovery of problem/gap/idea/evidence/boundary.
- `prose_issues.jsonl`: sentence/paragraph/section prose issues in article order.
- `paragraph_decisions.jsonl`: paragraph job, surgery decision, linked local issue ids, and next-draft structural task.
- `section_reflections.json`: per-section reflection, suggested skeleton, unresolved problems, and compact summary fields.
- `claim_candidates.json`: claims/promises found during prose reading.
- `phase_a_resume_status.json`: compact deterministic resume state built from review units and completed Phase A shards; orchestrator-readable, not a replacement for completed issue artifacts.
- `phase_a_next_step.json`: optional compact packet naming the next pending section and append targets for the next Prose Phase A call; orchestrator-readable, not a source of review findings.
- `phase_a_prompt_packet.json`: compact deterministic packet for the next Prose Phase A call; names read inputs, next section, write targets, and output contract without embedding raw audits or completed shards.
- `pipeline_status.json`: compact coordinator state written by `run_review_pipeline.py`; records deterministic steps, paths, checkpoint state, and next action. It is orchestration metadata, not review content.

Phase B artifacts:

- `phase_b_context.json`: deterministic compact input built from Phase A outputs and specialist `*_issues.json`.
- `phase_b_prompt_packet.json`: compact deterministic packet for the Prose Phase B call; points to `phase_b_context.json` and required Phase B outputs.
- `argument_map.json`
- `claims.json`
- `salvageable_core.json`
- `whole_paper_findings.jsonl`

`build_phase_b_input.py` is the intended deterministic compactor. Until implemented, any manual compaction must be saved as `phase_b_context.json` and clearly marked in `render_manifest.json`.

### Phase B Context Schema

`phase_b_context.json` is the only full synthesis input for Prose Phase B. It must be compact, deterministic, and derived from Phase A artifacts plus curated issue artifacts.

```json
{
  "schema_version": 1,
  "context_policy": "model_readable_compact_synthesis_input",
  "source_artifacts": [
    {"path": "cold_skim_frame.json", "hash": "sha256:..."},
    {"path": "section_reflections.json", "hash": "sha256:..."},
    {"path": "claim_candidates.json", "hash": "sha256:..."}
  ],
  "cold_skim": {
    "problem": "...",
    "gap": "...",
    "idea": "...",
    "evidence": "...",
    "boundary": "...",
    "first_reader_breaks": ["..."]
  },
  "section_summaries": [
    {
      "section_id": "introduction",
      "title": "Introduction",
      "one_line": "...",
      "role_in_argument": "...",
      "top_issue_ids": ["P3", "P7"]
    }
  ],
  "claim_candidates": [
    {"id": "C1", "text": "...", "location": "...", "strength": "...", "source_issue_ids": ["P4"]}
  ],
  "cross_section_terms": [
    {
      "term": "delta",
      "definitions": [
        {"section_id": "method", "anchor": "s-method-p003-s002", "meaning": "..."},
        {"section_id": "experiments", "anchor": "s-exp-p007-s004", "meaning": "..."}
      ],
      "issue_ids": ["P42"]
    }
  ],
  "specialist_issues_compact": [
    {
      "domain": "layout",
      "local_id": "L1",
      "severity": "Major",
      "title": "...",
      "anchor": "page:14",
      "source_artifact": "issue_artifacts/layout_issues.json"
    }
  ],
  "coverage": {
    "sections_summarized": 8,
    "specialist_domains": 7,
    "issue_count": 42
  }
}
```

The compactor should include only section-level summaries, top issue ids, compact claim candidates, cross-section term/claim signals, and specialist issue summaries. It must not copy full review units, full paragraph decisions, full raw audits, or complete bibliography/layout/PDF dumps into `phase_b_context.json`.

Use Chinese labels in visible UI. In paper-reader margin cards, keep the card focused on the teaching note: `问题是什么`, `为什么有问题`, `违反原则`, optional informative `严重度理由`, optional manuscript-level `核查依据`, and `自改问题`. Do not show `位置`, `原句/片段`, or `证据/验证` in sentence/paragraph/section/paper overlay cards because the active paper anchor already supplies location and original text. Show `核查依据` only for concrete manuscript-level checks, not for generic grammar/prose judgments. Do not show mechanical provenance such as generated ids or source-derived renderer details. Prefer `自改问题` over `下一稿任务`; keep detailed command-style repair steps in JSON or a requested revision-plan artifact.

## Claim Schema

Each `claims.json` item should contain:

- `claim_id`
- `claim_text`
- `location`
- `claim_type`
- `strength`
- `required_evidence`
- `visible_evidence`
- `status`: `supported`, `overclaim`, `unsupported`, or `ambiguous`
- `next_draft_task`
- linked finding ids when applicable

## Structured Artifacts

Substantial HTML reports must save structured artifacts beside the reviewed paper when writable:

```text
<paper-directory>/
├── ariadne_notes_<safe-paper-stem>_<YYYYMMDD>.html
└── ariadne_notes_<safe-paper-stem>_<YYYYMMDD>/
    ├── findings.json
    ├── claims.json
    ├── issue_artifacts/
    │   ├── prose_issues.jsonl
    │   ├── whole_paper_findings.jsonl
    │   ├── layout_issues.json
    │   ├── numeric_issues.json
    │   ├── reference_issues.json
    │   ├── symbol_issues.json
    │   ├── source_hygiene_issues.json
    │   ├── figure_caption_issues.json
    │   └── polish_issues.json
    ├── numeric_audit.json
    ├── layout_audit.json
    ├── coverage.json
    ├── render_manifest.json
    └── pass_observations.json
```

`findings.json` is the final issue source of truth after deterministic compilation. `claims.json` is the claim ledger. `issue_artifacts/` contains curated model-readable issue inputs from Prose Phase A/B and specialists. `numeric_audit.json` is generated by `extract_paper_text.py --numeric-json`. `layout_audit.json` is generated by `scripts/check_page_layout.py` for PDF layout coverage. Other raw audits are tool-only and may live beside these files. `coverage.json` stores requested scope, units, pass statuses, QA, layout coverage, issue-artifact coverage, and blind spots. `render_manifest.json` records rendered sections, output files, omitted/deferred sections, PDF linkage level, compiler inputs, and split-part links. `pass_observations.json` is derived from phase and issue artifacts by default.

Use `scripts/build_review_derivatives.py` to derive `coverage.json`, `render_manifest.json`, and `pass_observations.json` from `findings.json`, `annotations.json`, `issue_artifacts/`, layout audit coverage, and source artifact provenance. LLM agents should not hand-count these artifacts. Manual versions are reserved for unusual split-part runs and must still pass `audit_review_artifacts.py`.

### Legacy Bundle Compatibility

During migration, artifact audits must accept both formats:

- **Current format**: `issue_artifacts/` exists and contains Prose Phase A/B and specialist issue artifacts or explicit skipped stubs.
- **Legacy format**: no `issue_artifacts/` directory; `findings.json`, `claims.json`, `numeric_audit.json`, `layout_audit.json`, `coverage.json`, `render_manifest.json`, and `pass_observations.json` may be present directly in the bundle.

Legacy bundles should pass existing schema checks with a `WARNING` such as `legacy bundle: issue_artifacts/ absent; recommend migration`. New full-paper reviews created after this contract should use the current format. Keep legacy compatibility until the next major schema version; after that, missing `issue_artifacts/` may become an `ERROR` for newly generated full-paper reports while historical fixtures remain explicitly marked legacy.

For PDF layout review, keep visual coverage separate from prose coverage:

```json
{
  "layout": {
    "pages_total": 30,
    "pages_checked": 30,
    "pages_sampled": [],
    "pages_escalated": [5, 14],
    "full_layout_coverage": true
  }
}
```

If only selected pages were visually checked, set `full_layout_coverage` to `false` and list `pages_sampled`. Full sentence/prose coverage never implies full PDF layout coverage by itself.

Every layout finding or Pass 5 layout observation must trace to a real `layout_audit.json` observation with `layout_audit_observation_id`, `produced_by: "scripts/check_page_layout.py"`, and a matching `script_hash`. A page/issue-type pair may be used only as a fallback when the observation id is unavailable. If `coverage.layout.pages_checked > 0`, artifact audit requires `layout_audit.json` and the referenced PDF must be available so audit can replay `scripts/check_page_layout.py`.

The artifact bundle must contain data artifacts only. Do not include generated Python helper scripts, duplicate paper-preview HTML, or plaintext paper dumps.

HTML is a deterministic rendering of JSON artifacts. LLM agents must not hand-write HTML, recreate the paper body, or manually assemble legacy report sections when a renderer/compiler is available. If JSON and HTML are both produced, JSON is authoritative and HTML is a rendering. Every student-visible finding id in JSON must appear in HTML unless `render_manifest.json` marks it deferred; artifact-only findings should be deferred by design. Every HTML severity badge must correspond to a finding or grouped row in JSON.

Pass observation shape:

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

If the artifact directory cannot be written, use a temp directory and report the absolute fallback path.

Validate artifacts when feasible:

```bash
scripts/audit_review_artifacts.py \
  --bundle ariadne_notes_<safe-paper-stem>_<YYYYMMDD>/ \
  --html ariadne_notes_<safe-paper-stem>_<YYYYMMDD>.html \
  --source ariadne_paper_reader_<paper-stem>.source.html
```

For paper-reader outputs, `render_manifest.json` must set `paper_reader.source_integrity_check` to `verified`, `mismatch`, or `skipped`. `verified` requires recomputing `source_hash` from the source artifact and comparing the final paper pane against it after annotation-only markup is stripped. `skipped` is allowed only as an explicit warning state; `mismatch` is an error.

Fix every `ERROR` before delivery; treat `WARNING` lines as report caveats or calibration notes.

## Polish Sweep

Compact mechanical `Polish` issues such as typos, casing, ordinal formatting, hyphenation, and trivial typography into grouped rows. Suggested columns:

- `Category`
- `Instances / locations`
- `Next-draft task`
- `Count`

Grouped polish still counts in coverage.
