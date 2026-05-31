# Ariadne Rule-Loading Optimization Plan

## 2026-05-29: Implementation Plan

- Goal: split the old all-in-one reviewer lens into role-specific rule documents so Prose review agents load detailed writing rules without dragging unrelated specialist material into context.
- Decisions:
  - Prose rules are executable: Prose Phase A/B packets expose `rule_refs`, and the external prompt wrapper resolves those files into prompt text.
  - Specialist rules are maintenance-only for now: deterministic `check_*.py` logic remains the source of detection behavior, and specialist packets do not receive `rule_refs`.
  - `review_lenses.md` remains as legacy/compat documentation during the transition.
- Non-goals:
  - Do not change UI, HTML renderer behavior, report schemas, output contracts, or deterministic `check_*.py` detection logic.
  - Do not put the original student writing tips into the runtime load path.
- Work items:
  - Add `references/rules/` documents derived from the short/full writing tips.
  - Add Prose `rule_refs` to Phase A, Phase B, and sharded Phase A packets.
  - Update `run_agent_command.py` so `rule_refs` are resolved into generated prompt files.
  - Update skill/workflow documentation and implementation notes.
  - Add focused regression tests for packet refs, prompt resolution, shard refs, and specialist non-refs.
- Verification:
  - Run the focused packet/wrapper/specialist regression tests.
  - Confirm renderer/UI tests are not touched by this change.

## 2026-05-29: Completion Notes

- Completed:
  - Added role-specific rule documents under `ariadne-cs-paper-notes/references/rules/`.
  - Added executable Prose `rule_refs` to Phase A, Phase B, and sharded Phase A packets.
  - Kept specialist rule documents maintenance-only; default specialist packets do not include `rule_refs`.
  - Updated `run_agent_command.py` to resolve rule refs, verify hashes when present, and inject rule contents into generated prompts.
  - Updated `SKILL.md`, `references/workflow.md`, and `implementation-notes.md`.
- Quality pass:
  - Expanded the rules from source tips with a closed principle vocabulary, paper-type evidence contracts, weak/strong examples, and self-check questions.
  - Split `prose_style_rules.md` from maintenance-only `polish_rules.md` so executable Prose prompts do not absorb specialist maintenance notes.
  - Confirmed specialist rule docs remain B-mode maintenance documents and do not reimplement deterministic checker detection.
  - Closed the external-agent integration gap by having `run_prose_agent.py` render `ARIADNE_PROMPT_FILE` with resolved rule text before invoking `--agent-cmd`.
- Verification run:
  - `python3 ariadne-cs-paper-notes/tests/test_build_prose_phase_packet.py`
  - `python3 ariadne-cs-paper-notes/tests/test_build_prose_shards.py`
  - `python3 ariadne-cs-paper-notes/tests/test_run_agent_command.py`
  - `python3 ariadne-cs-paper-notes/tests/test_run_specialist_agent.py`
  - `python3 ariadne-cs-paper-notes/tests/test_run_prose_agent.py`
- Known untouched items:
  - UI/renderer code and artifact schemas were not changed.
  - Deterministic `check_*.py` detection logic was not changed.
  - The untracked `resource/` tips remain source material only, not runtime references.

## 2026-05-30: Residual Logic Audit

- Findings:
  - Confirmed no executable path still loads `review_lenses.md`, no Prose packet loads maintenance-only `polish_rules.md`, and specialist packets remain rule-free.
  - Confirmed one real maintenance risk: Prose rule lists were duplicated between non-sharded and sharded packet builders.
  - Confirmed the no-`--prose-agent-cmd` path intentionally skips the code-level Prose runner; rule delivery there is by SKILL/workflow contract, not `ARIADNE_PROMPT_FILE`.
- Fixes:
  - Added shared `scripts/prose_rule_refs.py` as the single source of executable Prose rule lists, hashes, and shard section matching.
  - Updated packet builders to import that shared source instead of carrying parallel hard-coded lists.
  - Made the top-level pipeline skip message explicit when code-level `rule_refs` resolution did not run.
  - Added tests to lock the shared rule lists and explicit skipped-Prose status.

## 2026-05-30: Process Audit Fix Plan

- Scope:
  - Audited the Hidden_Knowledge_with_RL4 review run against the generated bundle and current scripts.
  - Goal is to fix workflow guarantees, provenance, context isolation, and paper-reader fidelity gaps exposed by that run.
  - No code changes were made during this audit; this section is the follow-up implementation plan.

- Confirmed review-run facts:
  - The run did not execute LLM Prose or LLM Specialist subagents. `prose_agent_summary.json`, `specialist_agent_summary.json`, `vision_figure_agent_summary.json`, and `*.prompt.md` are absent from the bundle, and `pipeline_status.json` marks `run_prose_agent`, `run_specialist_agent`, and `run_vision_figure_agent` as skipped.
  - Prose rule buckets exist in Phase A/B prompt packets, but the actual run collapsed Orchestrator and Prose Agent into one Codex context, so rule isolation was not mechanically enforced.
  - Deterministic specialists did run through `run_p1_specialists.py`, but they are Python checkers/reducers, not LLM subagents. Specialist rule documents under `references/rules/` are currently maintenance-only and are not read by specialist scripts.
  - Layout status is semantically ambiguous: it is recorded as `skipped` even though 30 pages were checked and no main-review observations were emitted. Numeric is a stronger blind spot: `numeric_audit.json` has `signal_count: 0` and `checked: 0` on a table-heavy paper.
  - The generated `coverage.json` leaves `known_blind_spots` empty even though numeric checking skipped all table-number signals.
  - The paper-reader HTML does not preserve booktabs three-line table styling. The source tables use `\toprule`, `\midrule`, and `\bottomrule`; the renderer strips those commands and the generated CSS gives table cells full grid borders.

- Corrections to keep the audit precise:
  - Do not treat `review_units.md` and `review_units.jsonl` as independent context loads when estimating required agent context; they encode overlapping paper text. Track actual packet/input byte and token budgets instead.
  - Do not use transient UI/runtime observations, such as reconnects or terminal truncation, as formal evidence. Use bundle files, script status, and command receipts.
  - Do not describe layout as "not run"; describe it as "checked pages but emitted a skipped/no-action status." Numeric is the case that effectively failed to inspect table signals.

- P0 fixes:
  - Enforce subagent provenance for full-paper mode. A full-paper paper-reader run that requires Prose Phase A/B should fail or stop as pending unless `run_prose_agent.py` has produced a valid `prose_agent_summary.json` or an explicit `--allow-single-agent` mode is set.
  - Add artifact provenance receipts: agent command, generated prompt path, resolved rule IDs and hashes, input artifact hashes, output artifact hashes, phase status, and whether the run was dry-run/single-agent/external-agent.
  - Make final artifact audit check provenance, not only artifact shape. If full-paper mode claims subagent execution, missing summaries or missing prompt receipts should be an error.
  - Fix the Phase B cold-skim schema mismatch. `cold_skim_frame.json` currently uses fields like `problem_recoverable` and `skim_breaks`, while `build_phase_b_input.py` expects `problem`, `gap`, `idea`, `evidence`, `boundary`, and `first_reader_breaks`, leaving `phase_b_context.json` cold-skim fields empty.

- P1 fixes:
  - Repair numeric coverage. The numeric checker should detect table-number signals from LaTeX table sources and/or PDF tables; if extraction fails, it must emit an explicit blind spot and visible coverage warning instead of a quiet `signal_count == 0`.
  - Separate specialist status values: use `completed_no_issues`, `completed_no_signals`, `skipped_not_requested`, and `failed` instead of overloading `skipped`.
  - Replace density-only audit incentives. The current 15% sentence/paragraph annotation gate can be satisfied by backfilling issues. Add checks for Phase A receipts: paragraph decision coverage, section reflection coverage, monotonic full-paper traversal, and no synthetic "top issue" backfill without corresponding paragraph decisions.
  - Fix claim-link ID mapping. `claims.json` can link local whole-paper IDs such as `WB001`, while compiled findings use `F...`; either preserve stable source IDs in compiled findings or rewrite claim links during compilation. Audit warnings for broken claim links should become errors in strict/full-paper mode.
  - Make `known_blind_spots` mandatory when any requested deterministic specialist has zero effective coverage.
  - Update coverage pass status so Pass 6 is not left `pending` after the final HTML/artifact audits have completed.

- P2 fixes:
  - Provide a deterministic prose artifact writer/validator for inline or local-agent runs. It should validate IDs, anchors, paragraph IDs, required fields, JSONL shape, and output paths before compile.
  - Add a dependency bootstrap/self-check command that reports missing runtime packages and gives one supported install path, instead of discovering `bs4`, `lxml`, or `pdfplumber` failures mid-run.
  - Add measured context receipts for each phase: packet bytes/tokens, rule bytes/tokens, review-unit bytes/tokens, shard count, and whether the orchestrator read full review units directly.
  - Strengthen sharding guidance for larger papers. The orchestrator should prefer shard packets or external prose-agent runs instead of reading both full review-unit formats into one context.
  - Clarify in docs whether specialist rule files are maintenance-only or executable. If executable specialist agents are supported later, add specialist `rule_refs` and prompt receipts analogous to Prose.

- HTML/table fidelity fixes:
  - Preserve booktabs semantics when rebuilding HTML tables: record `\toprule`, `\midrule`, `\bottomrule`, and `\cmidrule` positions instead of deleting them during inline conversion.
  - Render paper-reader tables as three-line academic tables by default: no vertical cell grid, no per-cell full borders, top rule, header-bottom rule, and bottom rule.
  - Use `\midrule` to determine the header/body split where available, so multi-row table headers are not forced into "row 0 = thead".
  - Add renderer tests for booktabs tables, multi-row headers, and wraptable/table* variants.

## 2026-05-30: Remaining Process Fixes Completion Notes

- Completed:
  - Added LaTeX tabular numeric fallback to `extract_paper_text.py --numeric-json`, so numeric audit can inspect source tables when no PDF is available or PDF extraction misses table rows.
  - Kept numeric conservative: it emits structured recomputation signals for visible summary columns/rows and records source/PDF coverage counts; it still does not claim full OCR certification.
  - Added `validate_prose_artifacts.py` and wired it into strict full-paper pipeline before compile. It validates JSONL shape, paragraph ids, required fields, sentence receipts, section reflections, linked issue ids, and monotonic paragraph traversal.
  - Strengthened artifact audit with Phase A monotonic-order checks, prose issue anchor/paragraph-decision traceability, strict claim links through `compiled_issue_index.source_to_finding_id`, and mandatory blind spots for zero-effective specialists.
  - Added measured context receipts to Prose provenance: packet/prompt/rule/input bytes and estimated tokens, read input count, shard flag, and explicit single-agent full-review-unit context receipt.
  - Added `check_runtime_deps.py` for dependency self-check and one supported install path.
- Residual limits:
  - Numeric coverage is now meaningfully better for LaTeX tables, but full PDF OCR/table-structure certification remains out of scope.
  - There is a deterministic validator, not a deterministic prose artifact writer. Inline/local agents still write artifacts themselves, but the pipeline now blocks malformed artifacts before compile.
  - Sharding guidance remains policy plus receipts/gates; there is no hard ban on an orchestrator manually reading full review units outside the pipeline.
- Verification run:
  - `python3 ariadne-cs-paper-notes/tests/test_extract_paper_text.py`
  - `python3 ariadne-cs-paper-notes/tests/test_build_specialist_issues.py`
  - `python3 ariadne-cs-paper-notes/tests/test_build_review_derivatives.py`
  - `python3 ariadne-cs-paper-notes/tests/test_audit_review_artifacts.py`
  - `python3 ariadne-cs-paper-notes/tests/test_run_p1_specialists.py`
  - `python3 ariadne-cs-paper-notes/tests/test_validate_prose_artifacts.py`
  - `python3 ariadne-cs-paper-notes/tests/test_check_runtime_deps.py`
  - `python3 ariadne-cs-paper-notes/tests/test_run_prose_agent.py`
  - `python3 ariadne-cs-paper-notes/tests/test_run_review_pipeline.py`
  - `python3 ariadne-cs-paper-notes/tests/test_compile_review_artifacts.py`
  - `python3 ariadne-cs-paper-notes/tests/test_run_agent_command.py`
  - `python3 ariadne-cs-paper-notes/tests/test_render_paper_html.py`
  - `python3 ariadne-cs-paper-notes/tests/test_build_phase_b_input.py`
  - `python3 ariadne-cs-paper-notes/tests/test_build_prose_phase_packet.py`
  - `python3 ariadne-cs-paper-notes/tests/test_build_prose_shards.py`
  - `python3 ariadne-cs-paper-notes/tests/test_html_report_contract.py`

## 2026-05-31: 修复 Ariadne 中文导师式批注退化问题

- Summary:
  - 让 full-paper / paper-reader workflow 的可见批注意见稳定输出中文，并恢复 `读者卡点 -> 单一违反原则 -> 自改问题` 的教学结构。
  - 修复范围包括 `references/rules/` 中文化、Prose Agent prompt 注入、Phase A/B 输出合同、compiler 默认兜底、validator/audit 硬门禁、测试，以及用 `multi_bit_wm/acl_latex.tex` 重跑端到端报告验收。
- Key changes:
  - 将 `references/rules/*.md` 改为中文主体：以 `resource/writing_tips_full_precision_layout_figstyle.md` 为主源、短版为压缩核对表；保留 JSON key、脚本名、必要英文论文片段和 CS 术语。
  - 在 `run_agent_command.py` prompt 链路硬注入中文输出要求：可见批注必须使用中文导师式诊断，并按 `读者卡点 -> 单一违反原则 -> 自改问题` 写。
  - 收紧 `build_prose_phase_packet.py` 和 sharded Phase A packet 的输出合同：Prose/whole-paper issue 必须包含 `reader_friction`, `writing_principle`, `self_check`, `confidence`, `evidence_refs`, `severity_rationale`, `downgrade_condition`。
  - 修复 `compile_review_artifacts.py` 的英文兜底：默认教学字段改为中文，`writing_principle` 必须落在闭合原则表中；可见 prose/whole_paper finding 缺关键教学字段时不能靠 generic fallback 假装合格。
  - 加强 `validate_prose_artifacts.py` 和 `audit_review_artifacts.py`：strict/full-paper 模式下，student-visible Prose/whole-paper 批注若缺中文正文、缺教学字段、或 `writing_principle` 不在闭合原则表，直接失败。
  - 修复 renderer 层剩余英文 fallback，避免 `claim-evidence alignment` 等英文默认值出现在可见 UI。
- Tests and acceptance:
  - 更新 `test_run_agent_command.py`, `test_build_prose_phase_packet.py`, `test_build_prose_shards.py`, `test_validate_prose_artifacts.py`, `test_audit_review_artifacts.py`, `test_render_paper_html.py` 等回归测试。
  - 运行相关 pipeline/prose/render/audit 测试。
  - 重跑 `/Users/ofey/Research/ariadne-cs-paper-notes/ariadne-cs-paper-notes/debug/multi_bit_wm/acl_latex.tex` 完整 full-paper paper-reader workflow，确认 HTML/artifact audit 通过，且可见批注主体为中文。
