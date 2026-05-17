# Ariadne Report Contract

Use this file for full workbench-style reports and structured JSON artifacts. For HTML-specific rules, also load `html_contract.md`. For strict numeric rendering, also load `numeric_contract.md`.

## Workbench Order

The Reader-Journey passes are internal. Render reports as a revision workbench in this order:

1. **Executive Diagnosis and Salvageable Core / 总评诊断与可救骨架**
2. **Issue Index / Finding Ledger / 问题索引**
3. **Claim-Evidence Audit / 主张与证据审计**
4. **Deep Reading Notes / 逐章精读批注**
5. **Submission Readiness / 数字/公式/图表/版式/提交就绪**
6. **Local Patterns / 共性问题汇总**
7. **Revision Plan / 修改路线**
8. **Coverage Receipt and Artifacts / 覆盖回执与 artifacts**

Focused reviews keep the supported subset in the same relative order. Omit paper-level slots only when input cannot support them, and say so.

## Section Content

### Executive Diagnosis and Salvageable Core

Include:

- 一句话 verdict;
- paper type and review contract;
- highest-risk weakness and why it blocks reader belief;
- salvageable core: minimal viable paper after fixing Blockers/top Majors;
- claims to delete, downgrade, or support with new evidence.

Include **Salvageable Core** when the report has at least two `Blocker` findings or at least three `Major` findings. Use four compact blocks: minimal viable paper, delete/downgrade, fix type, next revision thread.

### Issue Index / Finding Ledger

This is the canonical source for core issue explanations. Include all `Blocker`, `Major`, and revision-relevant grouped `Minor/Polish`.

Use stable finding ids in `F<number>` form, such as `F1`, `F2`, `F12`. Use suffixes such as `F3a`, `F3b`, `F3c` only when splitting one grouped issue. Do not use severity-prefixed ids such as `B1`, `M3`, `N2`, or `P1`.

Every later `关联问题` links to a defined id. Later sections should write local consequence plus linked id, not repeat full diagnosis.

Suggested ledger columns:

- `ID`
- `严重度`
- `问题类型`
- `一句话问题`
- `主要位置`
- `后文引用位置`
- `状态 / 下一步`

### Claim-Evidence Audit

Include when abstract/main claims are available:

- Abstract Promise Tracking;
- Claim-Evidence Map;
- Story Logic and Red-Team Pass;
- title/abstract/introduction/conclusion alignment;
- skim-test observations from Pass 1 when they affect recoverability.

Every abstract sentence containing a number, causal verb, novelty/scope claim, "first", "significant", "state-of-the-art", "robust", "efficient", "general", or "all/across" should appear in the promise table.

### Deep Reading Notes

Organize in manuscript order. Do not split `分章批注`, `逐段手术`, and `句子级批注` into separate top-level sections.

For each visible section:

1. section reflection: `读后一句话`, `章节任务是否对齐`, `建议结构`, `未闭合问题`, `关联问题`, `下一稿任务`;
2. paragraph records: paragraph job, surgery decision, why, linked finding, next-draft structural task;
3. sentence rows under the paragraph for every substantive sentence issue.

Do not render visible `clean` rows. Clean units appear in coverage counts and optional machine-readable artifacts.

### Submission Readiness

Put cross-cutting artifact checks here:

- numerical/table arithmetic and table completeness;
- formula/symbol/algorithm consistency;
- figures/tables/captions and visual system;
- PDF/page layout;
- references/citations, checklist, venue compliance, anonymity, source hygiene;
- Polish Sweep.

Use linked finding ids and concrete values; avoid repeating Issue Index diagnosis.

### Local Patterns

Summarize repeated writing habits only. Give 2-3 representative locations and link to canonical finding ids or deep-reading rows. Do not relist every instance.

### Revision Plan

Render as an execution table, not prose recap. Suggested columns:

- `优先级`: `P0`, `P1`, `P2`, `P3`
- `任务`
- `关联问题`
- `负责人/区域`
- `工作量`
- `验收方式`

Keep rows short and link finding ids instead of repeating diagnoses.

### Coverage Receipt and Artifacts

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
- `writing_principle`
- `next_draft_task`
- `evidence_basis`
- `verification_method`

For `Blocker` and `Major`, also require:

- `confidence`: `high`, `medium`, or `low`
- `severity_rationale`
- `downgrade_condition`

For numeric/table findings, include:

- `reported_value`
- `visible_computed_value`
- `delta`
- `aggregation_caveat`

Use Chinese labels in visible UI. In compact Issue Index cards, prefer only: `位置`, `片段`, `诊断`, `依据`, `置信度`, `验证方式`, `判级理由`, `读者卡点`. Keep `降级条件` and detailed `下一稿任务` in JSON, local rows, or Revision Plan unless a finding genuinely needs a short repair line.

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
    ├── numeric_audit.json
    ├── coverage.json
    ├── render_manifest.json
    └── pass_observations.json
```

`findings.json` is the issue source of truth. `claims.json` is the claim ledger. `numeric_audit.json` is generated by `extract_paper_text.py --numeric-json`. `coverage.json` stores requested scope, units, pass statuses, QA, and blind spots. `render_manifest.json` records rendered sections, output files, omitted/deferred sections, PDF linkage level, and split-part links. `pass_observations.json` stores observations from Pass 0-6 before final classification.

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

If JSON and HTML are both produced, JSON is authoritative and HTML is a rendering. Every finding id in JSON must appear in HTML unless `render_manifest.json` marks it deferred. Every HTML severity badge must correspond to a finding or grouped row in JSON.

If the artifact directory cannot be written, use a temp directory and report the absolute fallback path.

Validate artifacts when feasible:

```bash
scripts/audit_review_artifacts.py \
  --bundle ariadne_notes_<safe-paper-stem>_<YYYYMMDD>/ \
  --html ariadne_notes_<safe-paper-stem>_<YYYYMMDD>.html
```

Fix every `ERROR` before delivery; treat `WARNING` lines as report caveats or calibration notes.

## Polish Sweep

Compact mechanical `Polish` issues such as typos, casing, ordinal formatting, hyphenation, and trivial typography into grouped rows. Suggested columns:

- `Category`
- `Instances / locations`
- `Next-draft task`
- `Count`

Grouped polish still counts in coverage.
