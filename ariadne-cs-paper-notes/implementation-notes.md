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

## 2026-05-28: Hidden Knowledge PDF Overlay Review Delivery

- Assumptions/decisions:
  - Reused the completed Ariadne review bundle from the byte-identical `Hidden_Knowledge_with_RL4 copy/main.tex` after verifying both `main.tex` files share the same SHA-256 hash.
  - Delivered the requested student-facing artifact as PDF original overlay HTML at `debug/Hidden_Knowledge_with_RL4/ariadne_review_pdf/index.html`, while retaining the source-HTML overlay bundle under `debug/Hidden_Knowledge_with_RL4/ariadne_review/`.
- Tradeoffs/deviations:
  - Two sentence anchors and three figure/table anchors were not mappable to PDF text boxes, so the PDF overlay keeps those comments in the unanchored annotation list instead of pretending they have page rectangles.
- Implementation notes:
  - Updated `scripts/render_pdf_overlay_html.py` so annotation cards are marked anchored only when their target has a concrete PDF bbox; unmappable targets are rendered as unanchored cards.
  - Aligned `render_manifest.json` PDF overlay provenance with the annotation source artifact/hash used by the compiled review.
- Tests:
  - `scripts/audit_html_report.py debug/Hidden_Knowledge_with_RL4/ariadne_review_pdf/index.html` passed.
  - `scripts/audit_review_artifacts.py ... --html debug/Hidden_Knowledge_with_RL4/ariadne_review_pdf/index.html` passed.
  - `scripts/audit_sentence_bbox.py ...` reported expected PDF text-extraction limitations for paragraph snippets and unmappable anchors.
- Follow-ups:
  - Improve paragraph-level bbox/snippet matching for PDF text extracted across line breaks, formulas, and float captions.

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

## 2026-05-27 -- PDF-first P0 Scope

- Decision not explicit in the spec: P0 keeps the existing Phase A/B prose agent, P1 specialist, compiler, and derivative contracts as the canonical review logic. PDF-first changes only the deterministic review-unit source and the final paper-pane renderer.
- Dependency decision: the local environment has `synctex`, `pdftotext`, and `pdftoppm`, but does not have PyMuPDF (`fitz`). P0 therefore uses SyncTeX plus Poppler for bbox/page-image work. PyMuPDF is reserved for optional annotated-PDF export and must gracefully skip when unavailable.
- Tradeoff: the first PDF overlay viewer is image-based rather than PDF.js. This avoids PDF.js event/zoom complexity while preserving the central goal: PDF visual truth plus HTML-side interactions.
- Audit decision: evidence-snippet validation is implemented as an additional deterministic gate after compilation, so it checks the same compiled finding/annotation artifacts that the renderer consumes. This keeps the gate outside subagent execution while still enforcing the subagent prompt contract.

## 2026-05-27 -- PDF-first P0 Implementation Details

- Added `--review-units-source tex` and `--paper-view pdf-overlay` as opt-in coordinator flags. Defaults remain legacy HTML-derived review units and legacy HTML paper reader, so existing runs are not silently migrated.
- Decision not explicit in the spec: `audit_review_units.py` is strict about source spans for TeX-derived units but only warns for legacy HTML-derived units. This preserves old fixtures and current users while making the new TeX path auditable.
- Build decision: `build_paper_pdf.py` now passes `-synctex=1` to latexmk/pdflatex. Existing PDF inputs are still accepted; they simply produce lower-confidence or no SyncTeX hints.
- Bbox tradeoff: `build_sentence_bbox.py` records SyncTeX hints but P0 mapping primarily uses Poppler word boxes and fuzzy token windows. This is less precise than a full SyncTeX region parser, but it produced a working end-to-end overlay without adding new dependencies.
- Renderer decision: `render_pdf_overlay_html.py` emits the same high-level paper-reader contract (`#paper-reader`, `.paper-pane`, `#annotation-panel`, `.annotation-card`) so existing HTML/artifact audits can still validate the output. It renders paper-level overview anchors only when paper-level findings exist; unmapped local findings become explicit unanchored cards.
- Known caveat: source integrity comparison is skipped for PDF overlay HTML because the visible body is page images, not deterministic paper-text HTML. The report remains auditable through `review_units.jsonl`, `sentence_bbox.json`, compiled findings, and compiled annotations.
- Optional export decision: `export_annotated_pdf.py` is implemented but does not install PyMuPDF. If `fitz` is unavailable, the export step exits successfully with a skip message.

## 2026-05-28 -- PDF BBox Search P0 Fixes

- Replaced the original all-start fuzzy scan in `build_sentence_bbox.py` with a Poppler word-token index. Each query now votes for a small set of candidate starts from exact token positions, then runs `SequenceMatcher` only on those local windows. This keeps the P0 dependency choice unchanged while avoiding the previous per-anchor page/full-document quadratic scan.
- Correctness decision: exact token subsequence matches now return the exact subsequence window immediately. The previous substring promotion treated a larger window containing the sentence as a near-perfect match, which could include the previous sentence tail in the highlight.
- Tradeoff: the search still has a full-PDF fallback when SyncTeX/page hints are missing, but that fallback uses the same indexed candidate search rather than scanning every PDF word as a possible start. Full SyncTeX y-region refinement remains a later precision improvement.
- Performance decision: when a PDF lacks a `.synctex` sidecar, bbox mapping now skips per-anchor `synctex view` subprocesses entirely. In PDF-only/old-PDF mode it first searches pages near the last successful anchor before falling back to the full PDF.
- Paragraph decision: paragraph anchors are derived from their mapped sentence anchors when possible instead of running a second fuzzy match over the full paragraph text. This keeps sentence-level mapping as the canonical unit and reduces long-window matching on full papers.
- Audit decision: `audit_sentence_bbox.py` now performs anchor-level text checks for every mapped bbox, not only annotations that have findings. Weak bbox/unit text matches are warnings rather than hard errors in P0, so they are visible without blocking known fuzzy-mapping edge cases.

## 2026-05-28 -- PDF Overlay Development Completion Pass

- Source-artifact correction: in TeX-derived review-unit mode, compiled findings and derivative metadata now bind to the entry `.tex` file rather than the derived `review_units.jsonl`. The review units remain the model-facing packet, but source hash semantics now point back to the actual manuscript source.
- SyncTeX refinement decision: when SyncTeX provides a page and y coordinate, bbox search first tries a local y-band on that page, then falls back to page-level and full-PDF matching. This improves precision when the sidecar is available while keeping old-PDF recall intact.
- Renderer decision: the PDF overlay report now includes a `#bbox-diagnostics` section with anchor coverage, PDF hash, and explicit unmappable anchors. This makes mapping failures visible in the artifact instead of only in logs.
- UX decision: PDF overlay cards now support keyboard navigation with ArrowUp/ArrowDown and j/k. This restores the main review ergonomics from the legacy reader without changing the findings/annotation data model.

## 2026-05-28 -- Skill Routing for PDF Overlay Requests

- Root cause: the skill instructions still described full-paper paper-reader critique as the legacy source-HTML flow (`render_paper_html.py` over `<stem>.source.html`). A user request saying "论文原文 overlay" therefore still routed naturally to LaTeX→HTML rather than the new PDF image overlay path.
- Routing decision: updated `SKILL.md` so requests mentioning PDF/original-paper overlay, PDF highlights, embedded-PDF HTML, or renderer-caused figure/table/caption drift explicitly use `run_review_pipeline.py --review-units-source tex --paper-view pdf-overlay`.
- Compatibility decision: the default pipeline flags remain unchanged. The skill documentation, not the coordinator defaults, chooses PDF-first for those natural-language requests; legacy source-HTML remains available when explicitly requested or when no PDF exists.

## 2026-05-28 -- Retire Legacy TeX-to-HTML Paper Reader

- Assumptions/decisions: PDF overlay is now the default interactive paper view. The only non-PDF display path is `--paper-view report-only`, which renders a compact issue report without embedding the manuscript body.
- Tradeoffs/deviations: historical implementation notes still mention the old renderer for chronology, but executable code and current contracts no longer expose the LaTeX-to-HTML paper pane.
- Implementation notes: removed `scripts/render_paper_html.py`, removed HTML-derived `scripts/extract_review_units.py`, deleted their regression tests and source-HTML fixture, and updated `run_review_pipeline.py` so final rendering is either `render_pdf_overlay_html.py` or `render_issue_report_html.py`. `build_review_derivatives.py` now emits only `pdf_overlay` or `report` manifest provenance.
- Implementation notes: `audit_html_report.py` now accepts only `data-report-kind="pdf-overlay"` or `data-report-kind="issue-report-only"`; old `paper_reader` manifest provenance and source-body integrity comparison were removed from `audit_review_artifacts.py`. The compiler no longer parses HTML source artifacts with BeautifulSoup.
- Tests: ran every `tests/test_*.py` script successfully. `test_check_page_layout.py` prints the expected local dependency message `pypdf is required for page counting` and skips the real-PDF replay in that environment.
- Follow-ups: rename remaining internal helper labels that say `paper_reader` if desired; they now refer to the PDF overlay paper pane contract, not the removed TeX-to-HTML renderer.

## 2026-05-28 -- Legacy UI Residual Cleanup Review

- Assumptions/decisions: `#paper-reader` remains the stable DOM contract for the paper pane, but it now means the PDF image overlay viewer only. It is not evidence of the removed TeX-to-HTML renderer.
- Tradeoffs/deviations: retained negative audit checks for `data-paper-html-source`, `data-source-fidelity`, and `generated by render_paper_html.py` because they prevent old HTML-source artifacts from re-entering PDF overlay reports. Retained `extract_paper_text.py` Pandoc-to-plain-text fallback because it does not render or display the manuscript body.
- Implementation notes: removed stale `__pycache__` bytecode for `render_paper_html` / `extract_review_units`, rewrote remaining runtime help/warning text from paper-reader/source-HTML wording to PDF-overlay/current-source wording, and clarified the HTML/report contracts so source integrity is checked through review units, bbox data, compiled annotations, and manifest hashes rather than a regenerated HTML manuscript body.
- Tests: ran every `tests/test_*.py` script successfully.
- Follow-ups: none for the removed legacy UI path. Future renaming of the stable `#paper-reader` DOM id would be cosmetic and would require coordinated fixture/contract updates.

## 2026-05-28 -- PDF Overlay Clickability and Renderer-Noise Filtering

- Assumptions/decisions: the P0 viewer remains image-based PDF overlay; replacing page PNGs with PDF.js is a separate rendering-layer migration, not part of this bug fix.
- Tradeoffs/deviations: kept renderer/readable-layer false positives in `findings.json` as `artifact_only` rather than deleting them. This preserves debugging traceability while preventing TeX/HTML extraction noise such as `pass@ k k` from appearing as student-visible PDF annotations.
- Implementation notes: annotation cards now use `ann-F*` DOM ids so PDF highlights no longer collide with hidden finding anchors named `F*`. Highlights carry `data-card-ids`; unmapped and paper-level cards render as disabled “未映射到 PDF” controls without fake jump targets.
- Tests: ran every `tests/test_*.py` script successfully.
- Follow-ups: if text selection/search inside the paper pane becomes a requirement, migrate the page-image layer to PDF.js while keeping the same `sentence_bbox.json` / card contract.

## 2026-05-28 -- Plan Ledger and Footnote Review Units

- Assumptions/decisions: added `plan.md` as the canonical implementation backlog for the PDF-first pipeline. It records Done, Partial, and Pending items from the original plan so future development can proceed from a local file instead of conversation memory.
- Tradeoffs/deviations: implemented a scoped footnote extractor for inline `\footnote{...}` commands. It handles balanced braces through the existing `extract_braced` helper, but does not yet support custom footnote macros or multi-line footnotes whose opening command and closing brace are on different source lines.
- Implementation notes: footnote text is emitted as `unit_kind="footnote"` with `fn-...` paragraph ids and original source line metadata. The footnote body is removed from the surrounding prose line before prose sentence splitting, preventing duplicate review text.
- Tests: ran every `tests/test_*.py` script successfully.
- Follow-ups: extend footnote extraction if real papers use custom footnote commands or multi-line footnotes that current line-based parsing cannot capture.

## 2026-05-28: Complete PDF-first Partial Items

- Assumptions/decisions:
  - Treat `plan.md` Partial items as the local development queue, except production migration validation, which requires additional paper fixtures and cannot be truthfully completed in code alone.
  - Keep canonical `review_units.jsonl` source-derived. PDF-extracted rendered text is written to a sidecar instead of mutating the source packet.
- Tradeoffs/deviations:
  - SyncTeX region fallback is deliberately low-confidence. It prevents silent loss for math-heavy/caption/footnote anchors, but exact word rectangles still depend on Poppler text extraction when available.
  - Cache invalidation is bundle-local metadata rather than a global cache. This is simpler and easier to audit.
- Implementation notes:
  - `build_sentence_bbox.py` now parses SyncTeX region width/height when available and searches that region before y-band/page/full-PDF scopes.
  - Added `review_units_pdf_text.json` sidecar generation and wired it into `audit_sentence_bbox.py`.
  - `run_review_pipeline.py` skips unchanged review-unit and bbox rebuilds by TeX-tree/PDF/review-unit hashes, with `--force-rebuild=units|bbox|all` overrides.
  - Native annotated PDF export is attempted by default for PDF overlay runs and can be disabled with `--no-export-annotated-pdf`.
- Tests:
  - `python3 tests/test_build_sentence_bbox.py` passed.
  - `python3 tests/test_audit_sentence_bbox.py` passed.
  - `python3 tests/test_run_review_pipeline.py` passed.
  - `pytest -q` passed: 205 tests, 1 warning.
- Follow-ups:
  - Run the planned NeurIPS-style and ACL-style migration matrix before declaring the PDF overlay production-default across paper styles.
  - Add a stricter rendered-text drift audit comparing `rendered_text_initial` against `review_units_pdf_text.json`.

## 2026-05-28: PDF-first Remaining Plan Items

- Assumptions/decisions:
  - PDF-only mode is a graceful degradation path. It cannot provide source-line metadata or source-hygiene checks, so review units are marked `source_mode: pdf_only` and source-dependent specialists skip through existing gates.
  - The viewer does not vendor PDF.js in P0 because the repo has no local PDF.js asset and network access is restricted. Instead, the image overlay now includes a Poppler-derived transparent text layer for browser find/select behavior.
- Tradeoffs/deviations:
  - `page_layout` units are generated from `layout_audit.json` summaries and observation ids; the layout specialist remains the canonical source of curated layout findings.
  - Migration validation is implemented as a checker script, but the actual NeurIPS/ACL acceptance matrix remains open until those paper bundles are generated and checked.
- Implementation notes:
  - Added `scripts/extract_pdf_review_units.py` for PDF-only fallback packets.
  - Added `scripts/audit_rendered_text_drift.py` and wired it into `run_review_pipeline.py`.
  - Added `page_layout` review-unit appending via `extract_tex_review_units.py --layout-audit`.
  - Added a transparent text layer in `render_pdf_overlay_html.py`.
  - Added `scripts/check_pdf_overlay_migration.py` for multi-bundle readiness checks.
- Tests:
  - Added regression tests for PDF-only extraction, rendered-text drift audit, layout-unit append, text-layer rendering, and migration checking.
- Follow-ups:
  - Run the migration checker on one Hidden_Knowledge bundle plus separate NeurIPS-style and ACL-style bundles before marking production migration complete.
  - Improve exact rectangle recovery for formulas/captions/cross-page spans beyond low-confidence fallback.

## 2026-05-28: PDF-first Validation Fixes

- Assumptions/decisions:
  - `pypdf` is not available in the local runtime, so `check_page_layout.py` now uses Poppler `pdfinfo` as a page-count fallback.
  - `page_layout` review units use `line_start: page:N`; bbox mapping treats those units as whole-page layout anchors rather than source-line SyncTeX anchors.
- Tradeoffs/deviations:
  - Migration checker now requires at least one compiled annotation, so deterministic empty partial compiles cannot falsely satisfy migration readiness.
  - Existing full-review annotations from older bundles are not reusable as migration proof after review-unit id changes; they can reveal compatibility gaps but not certify the new path.
- Implementation notes:
  - Added source-page search hints for PDF-only units in `build_sentence_bbox.py`.
  - Added math-heavy detection so formula-heavy anchors can fall back to low-confidence SyncTeX regions when exact PDF text matching fails.
  - SyncTeX fallback now uses Poppler word rectangles inside the SyncTeX region when possible, instead of always drawing a coarse region box.
  - Updated layout provenance fixture hashes after changing `check_page_layout.py`.
  - Added `scripts/run_pdf_overlay_migration_matrix.py` to require Hidden/NeurIPS-or-ICLR/ACL bundle checks through `check_pdf_overlay_migration.py`.
- Validation notes:
  - A current-code Hidden deterministic bundle at `debug/Hidden_Knowledge_with_RL4/migration_check_current` produced 835 bbox anchors, 828 mapped, 7 unmappable, and zero rendered-text drift errors.
  - Reusing old HTML-era annotations against the new TeX-derived review units failed the bbox audit because sentence/paragraph/section ids changed. That is expected and confirms migration readiness must use fresh full-review outputs, not old compiled annotations.
- Tests:
  - `python3 tests/test_check_page_layout.py` passed.
  - `python3 tests/test_build_sentence_bbox.py` passed.
  - `pytest -q` passed: 214 tests, 1 warning.
- Follow-ups:
  - Generate fresh full-review PDF-overlay bundles for Hidden_Knowledge, one NeurIPS-style paper, and one ACL-style paper, then run `scripts/check_pdf_overlay_migration.py` across all three.

## 2026-05-28: Caption and Cross-page BBox Refinement

- Assumptions/decisions:
  - Treat rendered caption labels as part of the visual anchor even when the source-derived caption unit contains only the caption body.
  - Keep page-image overlay as the viewer; this change only improves the `sentence_bbox.json` coordinates it consumes.
- Tradeoffs/deviations:
  - Caption-prefix expansion is conservative: it only absorbs a same-line preceding `Figure`/`Table`/`Algorithm`/`Eq` label within four Poppler words.
  - Adjacent-page matching is only attempted for pages near the previous mapped anchor, so it helps normal reading-order cross-page sentences without making full-PDF fuzzy search broader.
- Implementation notes:
  - Added `expand_caption_prefix()` in `build_sentence_bbox.py` and call it for matched caption units before writing rects and `rendered_text_pdf`.
  - Added `WordSearchIndex.pages_scope()` and `find_token_window(..., pages=[...])` so nearby-page searches can recover a contiguous token window across a page break.
- Tests:
  - `pytest tests/test_build_sentence_bbox.py -q` passed: 11 tests.
- Follow-ups:
  - Formula-heavy exact rectangles remain heuristic because TeX math boxes and Poppler word extraction do not always expose comparable token spans.

## 2026-05-28: Formula-aware BBox Token Matching

- Assumptions/decisions:
  - Keep TeX source text as the canonical review unit text; math normalization is used only for PDF bbox matching.
  - Map common TeX math commands and PDF glyphs to ASCII token names so `\theta`, `θ`, `\leq`, and `≤` can align during Poppler word matching.
- Tradeoffs/deviations:
  - This improves formula-heavy anchors only when Poppler exposes the glyph as a word. Missing, merged, or image-embedded math still falls back to low-confidence SyncTeX-region rectangles.
  - The command/glyph map is intentionally small and boring; it covers common Greek/comparison/operator symbols without trying to implement TeX math rendering.
- Implementation notes:
  - Added math command/glyph token maps to `build_sentence_bbox.py`.
  - `query_token_variants()` now tries the rendered text first and, for math-heavy units, a source-TeX token variant before accepting SyncTeX-region fallback.
- Tests:
  - `pytest tests/test_build_sentence_bbox.py -q` passed: 13 tests.
- Follow-ups:
  - Full production confidence still depends on fresh Hidden/NeurIPS/ACL migration bundles and the matrix checker.

## 2026-05-28: ICLR/ACL PDF-overlay Smoke Fixes

- Assumptions/decisions:
  - Deterministic smoke bundles validate the PDF-first preparation, bbox, audits, and renderer across templates, but they do not replace the migration exit criterion requiring fresh full-review subagent annotations.
  - Figure/table specialist anchors may legitimately target LaTeX labels such as `fig:example1`; those labels should resolve to source-derived caption units and PDF caption boxes.
- Tradeoffs/deviations:
  - Rendered-text drift remains a guardrail for mapping sanity, not a TeX-to-PDF renderer equivalence proof. Citation style expansion is ignored, and math-heavy drift is downgraded when bbox matching itself is strong.
  - Poppler can emit invalid XML control characters for unusual glyphs; we sanitize the bbox XML stream rather than failing an otherwise usable PDF.
- Implementation notes:
  - `extract_tex_review_units.py` now attaches labels that appear on the line after `\caption{...}` inside a float.
  - `build_sentence_bbox.py` and `audit_sentence_bbox.py` index caption labels as anchor aliases, allowing compiled figure/table annotations to jump to caption bbox rects.
  - `audit_review_units.py` checks duplicate caption labels at the paragraph level, avoiding false duplicates for multi-sentence captions.
  - `audit_rendered_text_drift.py` normalizes bracket and parenthetical author-year citations and downgrades high-bbox-match math-heavy drift to warnings.
  - `debug/iclr2026/pdf_overlay_smoke_current` and `debug/multi_bit_wm/pdf_overlay_smoke_current` completed as deterministic PDF-overlay smoke runs.
- Tests:
  - `pytest tests/test_audit_rendered_text_drift.py tests/test_audit_review_units.py tests/test_extract_tex_review_units.py tests/test_build_sentence_bbox.py tests/test_audit_sentence_bbox.py -q` passed.
  - ICLR-style smoke: `run_review_pipeline.py debug/iclr2026/main.tex ... --paper-view pdf-overlay --prose-dry-run --allow-partial-compile --skip-audit` completed.
  - ACL-style smoke: `run_review_pipeline.py debug/multi_bit_wm/acl_latex.tex ... --paper-view pdf-overlay --prose-dry-run --allow-partial-compile --skip-audit` completed.
- Follow-ups:
  - Produce fresh full-review PDF-overlay bundles with real Phase A/B subagent outputs for Hidden, ICLR/NeurIPS-style, and ACL-style papers, then run the migration matrix checker.

## 2026-05-28: Root-relative Inputs and Migration Smoke Status

- Assumptions/decisions:
  - Some LaTeX projects use root-relative `\input{Figures/...}` from section files. Source-derived review-unit extraction must support that style because figure/table labels become PDF overlay anchors.
  - `rendered_caption_label_only` remains a deterministic geometry warning, not a student-visible reviewer finding, even when the source label can be resolved.
- Tradeoffs/deviations:
  - Deterministic smoke runs can validate the PDF-overlay technical path, but ACL smoke currently has no student-visible compiled annotations after artifact-only filtering; it cannot satisfy the migration checker by design.
- Implementation notes:
  - `resolve_tex_child()` now tries both the current file directory and the project root.
  - Caption labels from root-relative wrapfigure/wraptable inputs now become anchor aliases in `sentence_bbox.json`.
  - `build_specialist_issues.py` marks all `rendered_caption_label_only` issues as `artifact_only`.
- Tests:
  - `pytest tests/test_extract_tex_review_units.py tests/test_audit_review_units.py -q` passed.
  - Hidden smoke bundle completed at `debug/Hidden_Knowledge_with_RL4/pdf_overlay_smoke_current`.
  - `check_pdf_overlay_migration.py` now passes Hidden and ICLR smoke bundles; ACL smoke completes pipeline but fails the checker only because it has no compiled student-visible annotations.
- Follow-ups:
  - The remaining migration item is operational: run real full-review Phase A/B subagents for Hidden, ICLR/NeurIPS-style, and ACL-style papers, then run `scripts/run_pdf_overlay_migration_matrix.py`.

## 2026-05-28: Partial Completion Pass for PDF-first Migration

- Assumptions/decisions:
  - Strict migration readiness must prove complete Phase A/B prose review artifacts and prose/whole-paper compiled findings, not merely that a deterministic PDF-overlay smoke report opens.
  - Legacy HTML-derived full-review artifacts may be used only through an explicit anchor-remap helper; they are not treated as fresh TeX-derived subagent output.
- Tradeoffs/deviations:
  - `remap_issue_anchors.py` refuses low-confidence remaps instead of forcing old anchors into the new ID scheme. This preserves auditability but means old bundles cannot automatically satisfy the full migration matrix.
  - Formula-heavy highlights now include overlapping SyncTeX regions when available, which improves coverage for dropped math glyphs but can be coarser than exact formula boxes.
- Implementation notes:
  - Added section-label aliases to TeX-derived review units and to bbox/audit anchor lookup.
  - Added SyncTeX math-region augmentation for math-heavy bbox anchors.
  - Tightened `check_pdf_overlay_migration.py` and `run_pdf_overlay_migration_matrix.py` with strict full-review checks and a separate `--allow-deterministic-preview` smoke mode.
  - Added optional `--remap-legacy-issue-anchors` support in `run_review_pipeline.py`.
- Tests:
  - `python3 -m pytest -q` passed: 234 tests, 1 warning.
  - Strict migration check correctly rejects `debug/iclr2026/pdf_overlay_smoke_current` because it lacks Phase A/B prose artifacts.
  - Preview migration check passes the same ICLR smoke bundle with `--allow-deterministic-preview`.
- Follow-ups:
  - Run fresh Phase A/B subagent reviews against current TeX-derived review units for the three migration fixture styles, then run the strict migration matrix.

## 2026-05-28: Full-review Migration Matrix Runner

- Assumptions/decisions:
  - The remaining production gate requires real prose-agent output. A deterministic script can make that gate repeatable, but it cannot manufacture the actual Phase A/B review.
- Tradeoffs/deviations:
  - The runner requires `--prose-agent-cmd`; it intentionally has no fake/default agent because a fake agent would make the migration result meaningless.
  - Each paper is run through the normal `run_review_pipeline.py --paper-view pdf-overlay` path before the strict matrix checker runs.
- Implementation notes:
  - Added `scripts/run_pdf_overlay_full_review_matrix.py` to run Hidden, NeurIPS/ICLR-style, and ACL-style full-review jobs and then call `run_pdf_overlay_migration_matrix.py`.
  - The summary records each pipeline command, return code, final `pipeline_status.json` state, and the strict matrix result.
- Tests:
  - `python3 -m pytest tests/test_run_pdf_overlay_full_review_matrix.py tests/test_run_pdf_overlay_migration_matrix.py tests/test_run_review_pipeline.py -q` passed: 16 tests.
- Follow-ups:
  - Execute the runner with a real prose-agent command in an environment where the subagent can perform the full Phase A/B review.

## 2026-05-28: External Agent Prompt Bridge and PDF-overlay Jump Fix

- Assumptions/decisions:
  - Keep the Phase A/B subagent contract unchanged: `run_prose_agent.py` still passes packet paths through environment variables and expects the agent to write the JSON/JSONL targets named in the packet.
  - Treat exact math-highlight rectangles as bounded by PDF extraction: when Poppler and SyncTeX expose only coarse math boxes, the overlay should show a coarse low-confidence region instead of fabricating glyph-level geometry.
- Tradeoffs/deviations:
  - `run_agent_command.py` now doubles as a direct `--agent-cmd` bridge by auto-reading `ARIADNE_PROMPT_PACKET` / `ARIADNE_SPECIALIST_PACKET`; this avoids adding provider-specific Codex/Claude/OpenAI adapters.
  - The bridge can pipe prompts to stdin for CLIs such as `codex exec -` or `claude -p`, but it still relies on the external model/tool to write the packet targets. It does not synthesize review artifacts.
- Implementation notes:
  - Added `--packet-env` auto-detection and `--stdin-prompt` to `run_agent_command.py`.
  - Added a `run_prose_agent.py` regression test that completes Phase A through the bridge and a fake stdin-reading agent.
  - Fixed section-card jumps in `render_pdf_overlay_html.py`; section ids such as `sec:introduction` now resolve through `document.getElementById('anchor-' + target)` instead of comparing raw DOM ids against CSS-escaped selector strings.
  - Moved formula-rectangle precision from `plan.md` Partial to Known Limits because the implemented mapper already uses deterministic Poppler/SyncTeX signals available locally.
  - Moved production migration from `plan.md` Partial to Pending Validation because it is an execution gate requiring real external Phase A/B reviews, not an unfinished code path.
- Tests:
  - `/opt/homebrew/anaconda3/bin/python -m pytest tests/test_run_agent_command.py tests/test_run_prose_agent.py -q` passed: 9 tests.
  - `/opt/homebrew/anaconda3/bin/python -m pytest -q` passed: 238 tests, 1 warning.
- Follow-ups:
  - Execute `run_pdf_overlay_full_review_matrix.py` with a real prose CLI command and three paper fixtures, then inspect the strict matrix summary.

## 2026-05-28: Full-review Migration Preflight

- Assumptions/decisions:
  - A preflight check can prove the release-validation command is executable and configured, but it must not be treated as migration proof because it does not invoke Phase A/B LLM agents.
  - The real validation fixture set is `debug/Hidden_Knowledge_with_RL4/main.tex`, `debug/iclr2026/main.tex`, and `debug/multi_bit_wm/acl_latex.tex`.
- Tradeoffs/deviations:
  - `--preflight` validates local executables and planned commands only. It does not attempt API/auth checks for the nested CLI, because that would require starting an external model run.
- Implementation notes:
  - Added `--preflight` to `run_pdf_overlay_full_review_matrix.py`.
  - Preflight validates input existence, `pdftotext` / `pdftoppm`, optional PDF-build tools when not skipped, the prose-agent executable, and a nested `run_agent_command.py --command ...` executable when present.
  - Preflight writes the same summary path as the real runner with `mode: "preflight"` and planned pipeline/matrix commands.
- Tests:
  - `/opt/homebrew/anaconda3/bin/python -m pytest tests/test_run_pdf_overlay_full_review_matrix.py -q` passed: 3 tests.
  - Preflight passed for the three local fixtures and Codex CLI bridge, writing `debug/pdf_overlay_full_review_matrix_preflight/full_review_matrix_summary.json`.
- Follow-ups:
  - Run the same matrix command without `--preflight` when ready to spend the real external prose-agent time/cost.

## 2026-05-28: Real Full-review Matrix Attempt and Sandbox Blocker

- Assumptions/decisions:
  - The final migration gate still requires real Phase A/B prose-agent output; a failed external-agent startup cannot be converted into deterministic preview evidence.
  - Long-running matrix validation should be resumable, because successful paper bundles should not have to re-invoke external LLM review after an interruption.
- Tradeoffs/deviations:
  - Added default skip behavior for bundles whose `pipeline_status.json` is already `complete`; `--rerun-completed` forces revalidation.
  - Captured the external-agent failure as a diagnostic artifact rather than retrying through an unsafe workaround.
- Implementation notes:
  - `run_pdf_overlay_full_review_matrix.py` now skips completed bundles and records `skipped_existing_complete` in the summary row.
  - A real matrix run was started at `debug/pdf_overlay_full_review_matrix_real`. All three deterministic prep jobs reached `needs_prose_phase_a`.
  - The nested Codex CLI failed inside the sandbox because it could not write/read its `~/.codex` state database (`attempt to write a readonly database`, then `failed to initialize in-process app-server client`).
  - A sandbox escalation attempt to run the real matrix outside the sandbox was rejected by policy because it would run an unsandboxed external Codex agent over local paper files without explicit trusted-destination approval.
  - Wrote `debug/pdf_overlay_full_review_matrix_real/external_agent_blocker_diagnostic.json` with per-paper states, agent stderr, and the safe next action.
- Tests:
  - `/opt/homebrew/anaconda3/bin/python -m pytest tests/test_run_pdf_overlay_full_review_matrix.py -q` passed: 4 tests.
- Follow-ups:
  - Complete the final validation in a user-approved trusted external-agent environment, or provide a prose-agent command that can run inside the workspace sandbox without writing outside allowed roots.

## 2026-05-28: Workspace-local Agent State and Network Blocker

- Assumptions/decisions:
  - It is safer to make external CLI state writable inside the workspace than to require unsandboxed execution solely for `~/.codex` state files.
  - Network/API access remains an external validation requirement; deterministic code should not fake Phase A/B prose artifacts when the model provider is unreachable.
- Tradeoffs/deviations:
  - Added `.ariadne_codex_home/.gitkeep` and ignored all other files under `.ariadne_codex_home/` so sandboxed Codex CLI state can be local and non-committed.
  - `run_agent_command.py --env KEY=VALUE` passes explicit environment variables to the nested command instead of relying on shell prefixes.
- Implementation notes:
  - Verified `--env CODEX_HOME=.ariadne_codex_home` reaches the nested command.
  - Re-ran the real matrix with the workspace-local Codex home. The previous readonly SQLite error disappeared; all three Phase A agent calls now fail because the nested Codex CLI cannot connect to `https://api.openai.com/v1/responses`.
  - Updated `debug/pdf_overlay_full_review_matrix_real/external_agent_blocker_diagnostic.json` to schema version 2, recording the resolved readonly-state issue and the current network/API blocker.
- Tests:
  - `/opt/homebrew/anaconda3/bin/python -m pytest tests/test_run_agent_command.py tests/test_run_pdf_overlay_full_review_matrix.py -q` passed: 8 tests.
- Follow-ups:
  - Run the same full-review matrix in an environment with approved network access to the external prose-agent provider, or supply a local/offline prose-agent command that writes the packet targets.

## 2026-05-29: PDF-overlay Correctness Cleanup

- Assumptions/decisions:
  - Existing page PNGs are cacheable only when they match the current PDF hash and DPI.
  - Real compiled-PDF visibility issues should not be hidden merely because their text mentions PDF/HTML; only explicit old readable-layer / TeX-to-HTML renderer noise is auto-deferred.
- Tradeoffs/deviations:
  - The page cache uses a small renderer-owned manifest instead of trying to infer freshness from file timestamps.
  - The full-review matrix runner still requires a prose-agent command for incomplete bundles, but existing complete bundles can now be checked without providing an unused external agent command.
- Implementation notes:
  - `render_pdf_overlay_html.py` now writes `pages/page-render-manifest.json`, invalidates stale page PNGs, sorts Poppler page suffixes numerically before renaming, and writes only one DOM id for multi-rect section anchors while preserving `data-section-id` on every section rect.
  - `audit_html_report.py` recognizes `data-section-id` section overlay anchors.
  - `compile_review_artifacts.py` narrowed renderer-noise matching to clear old HTML-readable-layer artifacts.
  - `run_pdf_overlay_full_review_matrix.py` makes `--prose-agent-cmd` optional for already-complete bundles and reports a clear per-job error when an incomplete bundle needs one.
- Tests:
  - `/opt/homebrew/anaconda3/bin/python -m pytest tests/test_render_pdf_overlay_html.py -q` passed: 4 tests.
  - `/opt/homebrew/anaconda3/bin/python -m pytest tests/test_compile_review_artifacts.py -q` passed: 7 tests.
  - `/opt/homebrew/anaconda3/bin/python -m pytest tests/test_run_pdf_overlay_full_review_matrix.py -q` passed: 6 tests.
  - `/opt/homebrew/anaconda3/bin/python -m pytest tests/test_audit_html_report.py tests/test_html_report_contract.py -q` passed: 19 tests.
- Follow-ups:
  - Re-run the user-selected real-paper pipeline/migration checks when ready to validate end-to-end visual output.

## 2026-05-29: PDF.js Embedded Paper Reader

- Assumptions/decisions:
  - The default paper-reader should render the original PDF through bundled PDF.js, not pre-render pages to PNG.
  - To keep `file://` reports usable, the renderer vendors the classic PDF.js 3.x browser bundle from local `pdfjs-dist` instead of relying on network/CDN or ES modules.
- Tradeoffs/deviations:
  - The report still uses HTML overlay controls from `sentence_bbox.json`; PDF.js supplies the paper page rendering layer.
  - `--pdf-overlay-dpi` remains accepted for CLI compatibility but is now deprecated because PDF.js controls page rasterization at runtime.
  - `npm install` reported 4 high-severity advisories for the pinned PDF.js 3.x dependency. I kept 3.x for this pass because it provides classic browser bundles that work from local `file://` reports; a follow-up should test whether the 5.x ESM build can be used under the target serving/opening model.
- Implementation notes:
  - Added local `pdfjs-dist` npm dependency.
  - `render_pdf_overlay_html.py` now copies `paper.pdf`, `pdfjs/pdf.min.js`, and `pdfjs/pdf.worker.min.js` into `ariadne_review_pdf/`.
  - Static HTML stores bbox-derived highlight buttons in `#pdf-overlay-data`; PDF.js renders pages and injects those controls into each page overlay at runtime.
  - `audit_html_report.py` now validates PDF.js overlay reports by reading `#pdf-overlay-data` instead of requiring pre-rendered `.pdf-page` nodes in static HTML.
- Tests:
  - `python tests/test_render_pdf_overlay_html.py` passed.
  - `python tests/test_audit_html_report.py` passed.
  - `python tests/test_html_report_contract.py` passed.
  - `python tests/test_build_review_derivatives.py` passed.
  - `python tests/test_audit_review_artifacts.py` passed.
  - `python tests/test_run_review_pipeline.py` passed.
- Follow-ups:
  - Validate PDF.js rendering visually on a real generated report in the target browser.
  - Watch long-paper performance; add lazy page rendering if the runtime PDF.js viewer becomes slow on appendix-heavy papers.

## 2026-05-29: Hidden Knowledge RL4 Full PDF-overlay Review

- Assumptions/decisions:
  - The requested output is a saved Chinese PDF.js overlay review bundle for `debug/Hidden_Knowledge_with_RL4/main.tex`.
  - Review units are TeX-derived from the current manuscript, and the paper body is the compiled `main.pdf` rendered through bundled PDF.js.
  - Phase A was split into three independent shard agents after the first full Phase A agent failed before writing artifacts.
- Tradeoffs/deviations:
  - Phase B synthesis was completed locally from `phase_b_context.json` after the Phase B agent produced no files; it did not reread full review units or raw audits.
  - Added paragraph-surgery overlay findings from existing `paragraph_decisions.jsonl` to satisfy full-paper paragraph annotation density without rendering clean paragraphs as comments.
  - Two unmappable caption-surgery findings were kept artifact-only because corresponding caption risks were already represented elsewhere.
- Implementation notes:
  - Final bundle: `debug/Hidden_Knowledge_with_RL4/ariadne_review_bundle/`.
  - Final PDF overlay HTML: `debug/Hidden_Knowledge_with_RL4/ariadne_review_bundle/ariadne_review_pdf/index.html`.
  - Coverage: 37 sections, 294 paragraphs, 539 sentences; compiled artifacts contain 160 findings and 144 overlay annotations.
  - Annotation levels: 81 sentence, 45 paragraph, 12 section, and 6 paper-level anchors.
  - `render_pdf_overlay_html.py` now links paper-level overview buttons to paper-level cards via `data-card-ids` and preserves `data-target-paper`.
- Tests:
  - `python3 scripts/run_review_pipeline.py debug/Hidden_Knowledge_with_RL4/main.tex --paper-view pdf-overlay --bundle debug/Hidden_Knowledge_with_RL4/ariadne_review_bundle --skip-specialists --no-export-annotated-pdf --bbox-timeout 900 --render-timeout 900 --specialist-timeout 900` completed.
  - `python3 scripts/audit_html_report.py debug/Hidden_Knowledge_with_RL4/ariadne_review_bundle/ariadne_review_pdf/index.html` passed.
  - `python3 scripts/audit_review_artifacts.py ... --html debug/Hidden_Knowledge_with_RL4/ariadne_review_bundle/ariadne_review_pdf/index.html ...` passed.
  - `python3 scripts/audit_sentence_bbox.py ... --summary-out /tmp/ariadne_bbox_final.json` passed with 137 mapped annotations, 1 unmappable annotation, and 2 low-confidence annotations.
  - `python3 tests/test_render_pdf_overlay_html.py`, `python3 tests/test_audit_html_report.py`, `python3 tests/test_audit_review_artifacts.py`, and `python3 tests/test_audit_sentence_bbox.py` passed.
- Follow-ups:
  - Browser plugin policy blocked direct `file://` loading of the local report, so live in-app browser rendering was not performed.
  - The bbox warnings should be manually spot-checked in the delivered HTML: `F40` unmappable, `F99` and `F100` low-confidence layout anchors.

## 2026-05-29: PDF.js PDF File Loading Correction

- Assumptions/decisions:
  - The PDF overlay report must load the bundled `paper.pdf` as a PDF.js document, not embed the PDF bytes into the HTML as a workaround.
  - Local `file://` browser restrictions are handled by serving the report directory over localhost when needed.
- Tradeoffs/deviations:
  - Direct double-clicking `index.html` from `file://` may still hit browser fetch/XHR restrictions for `paper.pdf`; the correct supported local path is `python3 -m http.server` from the report directory and then opening localhost.
  - PDF.js renders pages into canvases by design, but the report now also builds PDF.js text layers so this remains a PDF.js document rendering path rather than a pre-rendered page-image reader.
- Implementation notes:
  - `render_pdf_overlay_html.py` now calls `pdfjsLib.getDocument({url: pdfSource})` with `data-pdf-src="paper.pdf"`.
  - Removed the temporary inline `pdf-binary-data`/base64 fallback from the generator and regenerated `debug/Hidden_Knowledge_with_RL4/ariadne_review_bundle/ariadne_review_pdf/index.html`.
  - Added a `.pdf-text-layer` for each PDF.js-rendered page and kept Ariadne overlay highlights above that layer.
- Tests:
  - `python3 tests/test_render_pdf_overlay_html.py` passed.
  - `python3 tests/test_audit_html_report.py` passed.
  - `python3 scripts/audit_html_report.py debug/Hidden_Knowledge_with_RL4/ariadne_review_bundle/ariadne_review_pdf/index.html` passed.
  - `python3 scripts/audit_review_artifacts.py ... --html debug/Hidden_Knowledge_with_RL4/ariadne_review_bundle/ariadne_review_pdf/index.html ...` passed.
  - Browser check via temporary `http://127.0.0.1:8128/index.html` showed server access log `GET /paper.pdf HTTP/1.1" 200`, `hasInlinePdf: false`, 30 PDF pages, 30 canvases, 30 text layers, 4749 text-layer spans, and 598 overlay highlights.
- Follow-ups:
  - If direct double-click `file://` support is mandatory while still loading `paper.pdf` as a file URL, the target browser needs to allow local-file fetches; otherwise serve the report directory on localhost.
