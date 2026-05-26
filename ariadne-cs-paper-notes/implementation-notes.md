# Ariadne Architecture Implementation Notes

This file records implementation decisions, tradeoffs, and spec clarifications made while optimizing the Ariadne paper-review skill architecture.

## 2026-05-23 -- Three-Role Architecture

- Split the old "main reviewer" role into three responsibilities:
  - Orchestrator: schedules tools/subagents and reads only compact outputs/audit stdout.
  - Prose Review Agent: the only agent that reads full `review_units` for typical full-paper prose review.
  - Specialist Agents / deterministic reducers: isolated side channels for layout, numeric/table, references, symbols, source hygiene, figure/caption, and polish.
- Decision not explicit in the original spec: the orchestrator should not read raw `layout_audit.json`, `numeric_audit.json`, or `references_audit.json`. Only curated `*_issues.json`, compiler summaries, and compact audit stdout should enter orchestration context.
- Tradeoff: Prose Phase A still reads the whole `review_units.md` for 30-50 page papers because cross-section prose/claim problems need full-paper context. The spec keeps a fallback path for section-sharded Phase A when review units exceed context.

## 2026-05-23 -- Phase A/B Boundary

- Added a deterministic compactor, `scripts/build_phase_b_input.py`, to build `phase_b_context.json` from Phase A outputs plus specialist issue artifacts.
- Decision not explicit in the original spec: Phase B should not re-read full `section_reflections.json` or raw issue artifacts. It reads the compact derived context only.
- Phase A must write incrementally by section (`prose_issues.jsonl`, `paragraph_decisions.jsonl`, `section_reflections.json`) so a crashed long prose review can resume without losing all section work. The current implementation specifies this behavior; a full runner/resume implementation is still pending.

## 2026-05-23 -- Issue Artifact Contract

- Added the `ariadne_issue_artifact` schema with `context_policy: model_readable_issue_only`.
- Added skipped stubs for gated specialists. This lets downstream scripts depend on predictable files without forcing pointless specialist work.
- Decision not explicit in the original spec: high-risk issue fields are enforced for `Blocker`/`Major` specialist issues unless a later compiler can fill them from linked findings.
- Audit now accepts legacy bundles that lack `issue_artifacts/` with a warning, preserving existing fixtures and historical reports.

## 2026-05-23 -- Deterministic Compilation

- Added `scripts/compile_review_artifacts.py` to normalize `prose_issues.jsonl`, `whole_paper_findings.jsonl`, and specialist `*_issues.json` into final `findings.json`, anchor-only `annotations.json`, and `issue_artifacts/compiled_issue_index.json`.
- Decision not explicit in the original spec: final `F<number>` ids should be assigned only by the compiler. Agents write local ids such as `P1`, `W1`, `reference-hidden-metadata-fields`, etc.
- Dedup is intentionally conservative:
  - Merge only same-domain/same-type issues with matching evidence refs or highly similar same-anchor diagnosis.
  - Keep different-domain issues separate and cross-link by `related_issue_ids`.
  - Preserve every source issue in `source_issue_ids` when merging.
- `compiled_issue_index.json` exists mainly for auditability: it proves JSONL shards were normalized by deterministic code and suppresses the earlier JSONL "not schema-audited yet" warning.
- Tradeoff: The compiler can synthesize default `reader_friction`, `writing_principle`, and self-check text for deterministic specialist outputs. This keeps artifacts schema-compliant but is less nuanced than a human/prose-agent finding. Substantive prose review remains the Prose Review Agent's job.

## 2026-05-23 -- Renderer Boundary

- `scripts/render_paper_html.py` now accepts `--issues-dir` for curated specialist issues and can also render compiled `findings.json` + anchor-only `annotations.json`.
- Decision not explicit in the original spec: display-facing issue artifacts can be rendered as anchored or unanchored paper-reader cards when their natural anchor is page-level (`page:12`, `page:references`) rather than a source HTML sentence/paragraph id. Artifact-only issues stay in JSON and are listed as deferred findings.
- HTML is still fully deterministic. LLMs should not write HTML report bodies or paper-reader overlays.

## 2026-05-23 -- P1 Specialist Reducers

- Added deterministic P1 reducers for the three first specialist domains:
  - layout: `check_page_layout.py` raw audit -> `build_specialist_issues.py --domain layout`
  - numeric: `extract_paper_text.py --numeric-json` raw audit -> `build_specialist_issues.py --domain numeric`
  - reference: `check_references.py` raw audit -> `build_specialist_issues.py --domain reference`
- Decision not explicit in the original spec: deterministic reducers are acceptable P1 fallbacks for full LLM specialist agents. They generate the same `*_issues.json` contract, so later subagents can replace or augment them without downstream changes.
- Reference checker scope is intentionally hygiene-focused. It catches x-prefixed URL/DOI/eprint fields, hidden cited metadata, arXiv metadata style, author-format anomalies, unprotected acronyms/model names, and strong arXiv-id/BibTeX-year mismatch signals.
- Decision not explicit in the spec: arXiv year mismatch is only reported when the arXiv id's implied year and BibTeX `year` differ by more than one year. This avoids noisy cross-year preprint cases such as January arXiv ids paired with the prior conference/copyright year.

## 2026-05-23 -- P1 Specialist Runner

- Added `scripts/run_p1_specialists.py` as the single orchestrator-facing entry point for deterministic layout/numeric/reference/source-hygiene/polish/symbol/figure-caption specialists.
- Decision not explicit in the spec: if a raw audit already exists in the bundle and `--force` is not passed, the runner reuses it even when the original PDF/TeX input is not supplied. This supports resume/debug workflows and avoids rerunning expensive or environment-dependent extraction.
- The runner prints only compact status lines and writes `p1_specialists_summary.json`; it does not print raw audit contents to stdout.
- If the input needed for a domain is missing and no reusable raw audit exists, the runner writes a skipped issue stub instead of failing the whole specialist stage.
- `--force` regenerates raw audits when possible. This is useful after manuscript changes but can depend on local tools such as `pdftotext`.

## 2026-05-23 -- Source Hygiene / Anonymity Reducer

- Added `scripts/check_source_hygiene.py` to produce structured `source_hygiene_audit.json` from LaTeX source.
- Added `source_hygiene` support to `scripts/build_specialist_issues.py` and `scripts/run_p1_specialists.py`.
- Decision not explicit in the spec: source hygiene is grouped under one domain rather than separate `anonymity`, `placeholder`, and `submission_mode` domains. This keeps the specialist surface compact while preserving issue types inside each observation.
- The checker surfaces placeholder/broken-reference markers, TODO/TBD/FIXME, identity/anonymity signals, final/non-anonymous template switches, local absolute paths, and camera-ready wording.
- Identity/anonymity findings are signals, not proof of a real-world identity. Reports should phrase them as visible submission risks.
- For coverage accounting, the source-hygiene reducer uses the sum of structured signal counts as `coverage.checked`; this is a pragmatic count of inspected signal classes, not a count of source lines.

## 2026-05-23 -- Polish Sweep Reducer

- Added `scripts/check_polish.py` to produce grouped `polish_audit.json` signals from LaTeX source and extracted prose.
- Added `polish` support to `scripts/build_specialist_issues.py` and `scripts/run_p1_specialists.py`.
- Decision not explicit in the spec: polish findings are grouped by mechanical class rather than emitted per occurrence. This keeps issue artifacts compact and prevents routine copy-editing signals from consuming prose-review context.
- The checker currently covers repeated adjacent words, missing periods in `et al.`, `e.g.` / `i.e.` abbreviation style, common hyphenation variants, US/UK spelling drift, Unicode punctuation in source, and breakable spaces before reference commands.
- Tradeoff: polish findings are intentionally low/medium confidence style signals. The renderer should show them as a sweep/checklist section, not as evidence that the prose-review agent has made a substantive writing diagnosis.

## 2026-05-23 -- Symbol Consistency Reducer

- Added `scripts/check_symbol.py` to produce structured `symbol_audit.json` from LaTeX display equations and macro definitions.
- Added `symbol` support to `scripts/build_specialist_issues.py` and `scripts/run_p1_specialists.py`.
- Decision not explicit in the spec: the symbol reducer reuses the existing `extract_paper_text.py` math-signal helpers rather than adding a second LaTeX math parser. This keeps the P2 reducer aligned with existing seeded-defect tests.
- The checker reports macro redefinition, command-like math tokens that are not defined in visible source or the common allowlist, and common variant-symbol pairs such as `\epsilon`/`\varepsilon`.
- Tradeoff: symbol issues are notation signals, not mathematical correctness verdicts. Reports should phrase them as "verify intended distinction/definition" unless a prose review or human specialist confirms a real formula error.

## 2026-05-23 -- Figure/Caption Reducer

- Added `scripts/check_figure_caption.py` to produce structured `figure_caption_audit.json` from LaTeX float, caption, label, reference, and `\includegraphics` source signals.
- Added `figure_caption` support to `scripts/build_specialist_issues.py` and `scripts/run_p1_specialists.py`.
- Decision not explicit in the spec: this reducer starts with source-level checks and optionally adds rendered-PDF caption geometry when `--pdf` is provided. The runner now passes the PDF/page range through automatically when available.
- Source checks cover missing/short/placeholder captions, missing float labels, unresolved figure/table refs, and missing graphic assets.
- Figure asset checks use Pillow when available to flag low-resolution, near-blank, low-contrast, or extreme-aspect local raster image assets. PDF figure assets are previewed through `pdftoppm` when available and checked for near-blank/low-contrast/extreme-aspect signals.
- Rendered-PDF checks use `pdftotext -bbox-layout` to detect caption labels in compiled pages, source-vs-rendered caption count mismatches, caption text close to the page edge, and rendered label-only/very thin caption lines.
- Decision not explicit in the spec: source and rendered observations are merged into one raw audit and then renumbered sequentially before writing. If a rendered observation's temporary id collides with a source observation id, the original id is kept in `details.original_observation_id`.
- Decision not explicit in the spec: PDF figure previews do not trigger low-resolution findings because preview dimensions depend on rendering DPI and are not a stable source-asset resolution measure. They are used for blankness, contrast, and aspect-ratio checks only.
- Tradeoff: this is still deterministic geometry/source/image-quality hygiene, not semantic figure understanding. It cannot judge whether a plot supports a claim, and it can miss captions embedded as images or produced by unusual macros. A future vision-enabled specialist can read rendered page images and emit the same `figure_caption_issues.json` contract.

## 2026-05-23 -- Derived Mechanical Artifacts

- Added `scripts/build_review_derivatives.py` to derive `coverage.json`, `render_manifest.json`, and `pass_observations.json` from compiled findings, anchor-only annotations, issue artifacts, layout coverage, and source artifact provenance.
- Decision not explicit in the spec: this is one script with three output files rather than three tiny scripts. The outputs are coupled by the same compiled inputs and audit contract, so one deterministic builder avoids divergent counts.
- The derivative builder intentionally stores compact summaries only. It does not copy raw layout/reference/source audits into pass observations.
- Tradeoff: `render_manifest.paper_reader.source_integrity_check` defaults to `skipped` because full source-vs-final HTML body comparison needs the final rendered HTML path. The HTML/artifact audit remains responsible for verified source-integrity checks when both files are available.

## 2026-05-23 -- Phase A Resume Status

- Added `scripts/phase_a_resume_status.py` to derive `phase_a_resume_status.json` from `review_units.jsonl`, `prose_issues.jsonl`, `paragraph_decisions.jsonl`, and `section_reflections.json`.
- Decision not explicit in the spec: the helper judges a section complete when it has a section reflection and paragraph-decision coverage. Prose issue rows are not required because a section can be clean or have only paragraph-level notes.
- The output is intentionally compact and marked `context_policy: model_readable_resume_status_only`; it lists completed, partial, and pending section ids without replaying full completed JSONL shards.
- Added optional `--next-out` support for `phase_a_next_step.json`, a compact orchestrator packet that names the next pending section and append targets for the next Prose Phase A call.
- Tradeoff: this is a resumability coordinator, not a Prose Phase A runner. It tells the orchestrator where to continue and where to append, but it does not automate the LLM deep read.

## 2026-05-23 -- Top-Level Pipeline Coordinator

- Added `scripts/run_review_pipeline.py` as a checkpoint-aware deterministic coordinator for build/render/extract/specialists/resume/compile/derive/render/audit.
- Decision not explicit in the spec: the coordinator stops when Prose Phase A or Phase B artifacts are missing instead of compiling a specialist-only report by default. `--allow-partial-compile` is available for debug previews and must be labeled partial.
- The coordinator writes `pipeline_status.json` with `context_policy: model_readable_pipeline_status_only`, compact step stdout/stderr tails, artifact paths, and next action. The orchestrator can read this status without loading paper text or raw audits.
- Tradeoff: this is a local deterministic backbone, not an autonomous LLM runner. It prepares and resumes prose work but does not perform the Prose Agent's sentence-by-sentence judgment.

## 2026-05-23 -- Prose Phase Prompt Packets

- Added `scripts/build_prose_phase_packet.py` to generate compact `phase_a_prompt_packet.json` and `phase_b_prompt_packet.json`.
- Decision not explicit in the spec: prompt packets point to model-readable inputs and output targets instead of embedding full paper text or compact context inline. This keeps the orchestrator packet small and lets the Prose Agent explicitly decide what to open/read.
- Phase A packets include the next resume section, write targets, and JSON/JSONL output contracts. Phase B packets include only `phase_b_context.json` as read input plus Phase B write targets.
- `run_review_pipeline.py` now writes these packets automatically at the relevant checkpoints and points `next_action` at them.

## 2026-05-23 -- Pluggable Prose Agent Runner

- Added `scripts/run_prose_agent.py` to run Prose Phase A/B through an external `--agent-cmd` without hard-coding a model provider.
- The runner passes compact environment variables (`ARIADNE_PROMPT_PACKET`, `ARIADNE_BUNDLE`, `ARIADNE_ISSUE_ARTIFACTS`) and expects the external agent to write the JSON/JSONL targets named in the packet.
- Phase A loops by refreshing `phase_a_resume_status.json` after each call, so a section-by-section agent can resume and stop cleanly once no pending sections remain.
- The runner now detects no-progress calls: if an external agent exits successfully but does not advance resume status or write-target counts, the call is marked `no_progress` and the loop stops instead of burning iterations.
- Decision not explicit in the spec: standalone `run_prose_agent.py` returns nonzero when phases remain pending, but `run_review_pipeline.py` invokes it with `--allow-incomplete` because pending prose work is a valid checkpoint, not a deterministic pipeline failure.
- Tradeoff: this is an execution wrapper, not a built-in LLM client. It keeps API/vendor concerns outside the skill while making the architecture runnable by any local/remote agent command that honors the packet contract.

## 2026-05-23 -- Section-Sharded Phase A Manifest

- Added `scripts/build_prose_shards.py` for oversized `review_units` cases.
- It writes `phase_a_shard_manifest.json` and per-shard packets under `phase_a_shards/`, grouping sections by approximate token budget.
- Decision not explicit in the spec: shard packets still point at the canonical review units rather than copying excerpt text into each packet. This avoids duplicated paper text and keeps source hashes stable, at the cost of requiring the external Prose Agent to select only the listed sections.
- `run_review_pipeline.py` now creates the shard manifest when the review-unit token estimate exceeds `--prose-shard-threshold` and passes it into `run_prose_agent.py`.
- `run_prose_agent.py --shard-manifest ...` executes shard packets in manifest order, skipping shards whose sections are already complete according to `phase_a_resume_status.json`.
- Follow-up implemented on 2026-05-24: `phase_a_resume_status.py` now separates front matter into a `front_matter` bucket with `front_matter_sections`, `front_matter_paragraphs`, and `front_matter_sentences` coverage fields. Front matter no longer creates a misleading partial review section.

## 2026-05-23 -- Optional LLM Specialist Hook

- Added `scripts/run_specialist_agent.py` to let external specialist agents refine deterministic `*_issues.json` artifacts.
- Decision not explicit in the spec: the default specialist packet includes only curated issue artifacts, not raw audits. The external command receives `ARIADNE_SPECIALIST_PACKET`, `ARIADNE_SPECIALIST_DOMAIN`, `ARIADNE_SPECIALIST_INPUT`, and `ARIADNE_SPECIALIST_OUTPUT`.
- The runner writes refined artifacts to `issue_artifacts_llm/` by default and can audit that directory. `run_review_pipeline.py` can use the refined directory for compile/render when `--use-specialist-agent-output` is passed.
- Tradeoff: deterministic reducers remain the default reliable path. LLM specialist refinement is opt-in because it can improve judgment/grouping but introduces model variability.

## 2026-05-24 -- Sharded Phase B Guard

- Added an artifact audit guard for sharded Phase A: if `phase_a_shard_manifest.json` exists, a full audit now requires both `phase_b_context.json` and `issue_artifacts/whole_paper_findings.jsonl`.
- Decision not explicit in the spec: the guard lives in `audit_review_artifacts.py`, not only in the coordinator. This catches hand-assembled bundles where a sharded Phase A was run but the mandatory synthesis pass was skipped.
- Tradeoff: the guard checks for the presence of Phase B synthesis artifacts, not their intellectual quality. Quality remains the Prose Phase B agent's job and is reflected through findings/claims audits.

## 2026-05-24 -- Provider-Neutral Command Adapter

- Added `scripts/run_agent_command.py` as a generic adapter for local/remote agent commands. It renders a prompt markdown file from a packet, sets `ARIADNE_PACKET` and `ARIADNE_PROMPT_FILE`, and can capture JSON stdout to a declared output file.
- Decision not explicit in the spec: this adapter is intentionally not Ariadne-Prose-specific. `run_prose_agent.py` remains the resume-aware Phase A/B loop, while `run_agent_command.py` is a thin bridge for any provider CLI that wants a file prompt.
- Tradeoff: no vendor-specific defaults are bundled. This avoids hard-coding Codex/Claude/OpenAI invocation details in the skill, but users still need to supply a command that honors the packet contract.

## 2026-05-24 -- Optional Vision Figure Hook

- Added `scripts/run_vision_figure_agent.py` and pipeline flags `--vision-figure-agent-cmd`, `--vision-figure-pages`, `--vision-figure-agent-timeout`, and `--vision-figure-dry-run`.
- The hook renders selected PDF pages to page PNGs, writes a compact `vision_image_manifest.json`, writes a `*.vision_packet.json`, and lets an external vision-capable agent write a `figure_caption` issue artifact.
- Decision not explicit in the spec: page images are tool-only artifacts; the main orchestrator should read only the runner summary and final curated issue artifact. This preserves the context-isolation principle for visual evidence.
- Tradeoff: the deterministic figure/caption checker remains the default. The vision hook is opt-in because semantic visual judgment needs a model with image access and may vary by provider.

## 2026-05-24 -- Paper-Reader Global Findings Renderer

- `render_paper_html.py` now supports `--reuse-raw-html` so final rendering can overlay annotations onto the exact source-derived HTML that was used to extract review units. This prevents final render from rerunning Pandoc and changing sentence anchors after Prose Phase A/B.
- The renderer supports `--full-report`, `--coverage`, and global finding rendering. In current paper-reader mode, `--full-report` appends only `#global-findings` plus `#coverage-receipt`; it no longer emits the legacy workbench sections (`executive-diagnosis`, `issue-index`, `claim-evidence-audit`, `deep-reading-notes`, `submission-readiness`, `local-comments`, `revision-plan`).
- Decision not explicit in the spec: paper-reader HTML is now the canonical student-facing shape. Full teaching content lives in `findings.json` and is joined into overlay cards; only independent whole-paper Major/Blocker findings are duplicated below the paper as `#global-findings`.
- Fixed a contract gap where compiled findings with only `target_anchors` did not become paper-reader overlay annotations. The renderer now infers sentence/paragraph/section targets from `target_anchors`, `primary_anchor`, or `anchor`.

## 2026-05-24 -- Fake-Agent End-to-End Canary

- Added a fake Prose Agent end-to-end regression test in `tests/test_run_review_pipeline.py`.
- The test runs the pipeline through source extraction, fake Phase A/B JSON writes, compilation, derivative generation, full-report rendering, HTML audit, and artifact audit without calling a real LLM.
- Decision not explicit in the spec: the canary uses a tiny source-derived HTML fixture rather than a LaTeX/PDF build. This isolates orchestration, artifact, renderer, and audit contracts from external Pandoc/LaTeX variability while still proving the new architecture can close the loop.

## 2026-05-23 -- Audit Hash Hardening

- `audit_review_artifacts.py` now recomputes `sha256` for existing `source_artifacts` named inside issue artifacts and errors on mismatches.
- Decision not explicit in the spec: missing source artifact paths remain tolerated for legacy/portable bundles, but if the referenced file exists locally, its hash must match. This gives local replay safety without making archived bundles impossible to inspect.

## 2026-05-23 -- RL2 Dry-Run Findings

- The `debug/Hidden_Knowledge_with_RL2` dry run validates the new backbone:
  - `phase_b_context.json` stayed compact (about 14KB in the first run).
  - Compiler output from manually curated issue artifacts produced 188 findings/annotations.
  - Automatic P1 specialist reducers produced 187 findings/annotations because the deterministic reference checker currently has one fewer reference category.
  - Source hygiene runner pass found 3 curated issues on RL2: TODO markers, identity/anonymity signals, and camera-ready wording.
  - Polish runner pass found 2 curated issues on RL2: smart/Unicode punctuation in source and breakable spaces before reference commands.
  - Symbol runner pass found 1 curated issue on RL2: a macro redefinition signal for `\thefootnote`.
  - Figure/caption runner pass found 2 curated issues on RL2 after PDF geometry was enabled: an unresolved figure/table reference in visible source and a rendered label-only/thin-caption signal.
- Derived `coverage.json`, `render_manifest.json`, and `pass_observations.json` were generated for RL2 and passed artifact audit with only the expected source-integrity skipped warning.
  - HTML audit and review artifact audit pass for the compiled and auto-compiled reports.
- Dry-run artifacts under `debug/Hidden_Knowledge_with_RL2/ariadne_notes_main_20260523/` are validation outputs, not canonical source code.

## Open Implementation Items

- Add optional vision-enabled figure semantics checks for whether the visual content supports the caption/claim. The current implementation covers source hygiene, rendered-caption geometry, and raster/PDF-preview asset quality signals.
- Add provider-specific convenience adapters if needed (for example a local Codex/Claude/OpenAI CLI wrapper). The architecture now has provider-neutral runners, but no vendor-specific command is bundled.
