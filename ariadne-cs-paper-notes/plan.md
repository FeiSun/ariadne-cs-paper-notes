# PDF-first Ariadne Pipeline Plan

This file is the running implementation plan for the PDF-first review pipeline. Update it when a planned item changes state.

## Status Legend

- Done: implemented, tested, and wired into the normal pipeline.
- Partial: usable implementation exists, but it does not yet satisfy the original production target.
- Pending: not implemented.

## Current Default

- Done: full-paper annotation requests use TeX-derived review units and PDF image overlay HTML by default.
- Done: report-only output is available with `--paper-view report-only`.
- Done: legacy TeX-to-HTML paper rendering has been removed from executable paths.

## Implemented

- Done: source-derived `review_units.jsonl` / `review_units.md` from TeX.
- Done: LaTeX comments are stripped before expanding `\input`, `\include`, `\subfile`, `\import`, and `\subimport`.
- Done: original input-file source paths and line ranges are preserved.
- Done: `unit_kind` support for `prose`, `caption`, `item`, and `section_heading`.
- Done: `footnote` review units are extracted separately from surrounding prose.
- Done: caption units include `float_kind` and `label`.
- Done: existing Phase A/B prose-agent flow remains canonical.
- Done: P1 specialists remain separate artifacts.
- Done: `compile_review_artifacts.py` remains the only merge point for findings and annotations.
- Done: `build_paper_pdf.py` builds with `-synctex=1`.
- Done: `sentence_bbox.json` records `pdf_hash`, `review_units_hash`, mapping confidence, method, rendered PDF text, rects, and explicit unmappable status.
- Done: bbox search uses Poppler `pdftotext -bbox-layout` word boxes with indexed fuzzy matching.
- Done: bbox mapping uses SyncTeX page/y hints when available.
- Done: bbox mapping uses SyncTeX box/region hints as the first search scope when SyncTeX exposes width/height data.
- Done: paragraph anchors are derived from mapped sentence anchors when possible.
- Done: low-confidence SyncTeX-region fallback keeps math-heavy/caption/footnote anchors visible when text matching cannot recover a token window.
- Done: SyncTeX fallback prefers Poppler word rectangles inside the SyncTeX region before falling back to a coarse region box.
- Done: caption bbox highlights include rendered same-line `Figure`/`Table`/`Algorithm` label prefixes when Poppler exposes them as preceding words.
- Done: bbox search can match a sentence window spanning adjacent nearby pages instead of immediately falling back to full-PDF fuzzy search.
- Done: formula-heavy bbox search tries both rendered-text tokens and source-TeX math-command tokens, with common Greek/comparison/operator glyphs normalized to comparable token names.
- Done: formula-heavy mapped word rectangles are augmented with overlapping SyncTeX regions when Poppler exposes surrounding text but drops or merges formula glyphs.
- Done: Poppler bbox XML with illegal control characters is sanitized before parsing, which allows ICLR-style PDFs with odd glyph extraction to continue.
- Done: caption labels written on the line after `\caption{...}` are attached to source-derived caption units, so figure/table specialist anchors can jump to PDF caption boxes.
- Done: section labels written on the line after a section heading are recorded as aliases, so `sec:*` / `apd:*` anchors can resolve to TeX-derived section units.
- Done: rendered-text drift audit ignores citation style expansion and treats math-heavy drift with a strong bbox match as a warning rather than a hard failure.
- Done: root-relative `\input{Figures/...}` / `\input{Tables/...}` from section files resolves against the project root as well as the current file directory.
- Done: rendered caption geometry warnings such as label-only caption lines are artifact-only and do not appear as student-visible PDF overlay findings.
- Done: `audit_review_units.py` checks source spans, ids, text, caption metadata, and coverage summary.
- Done: `audit_sentence_bbox.py` checks compiled annotation anchors, bbox/unmappable status, anchor-level text match warnings, and `evidence_snippet` matches.
- Done: `review_units_pdf_text.json` sidecar records PDF-extracted rendered text without mutating the canonical source-derived `review_units.jsonl`.
- Done: rendered-text drift audit compares source-derived initial text with PDF-extracted text and writes `rendered_text_drift_audit.json`.
- Done: prose and specialist prompt contracts require `evidence_snippet` for sentence/paragraph issues.
- Done: coordinator cache skips unchanged TeX review units and unchanged PDF bbox maps by dependency hash.
- Done: `--force-rebuild=units|bbox|all` is available for cache invalidation.
- Done: PDF.js overlay renderer emits `ariadne_review_pdf/index.html`, `paper.pdf`, and bundled local `pdfjs/` assets; page PNGs are no longer part of the default reader.
- Done: click PDF highlight -> annotation card.
- Done: click mapped annotation card -> PDF highlight.
- Done: unmapped and paper-level annotation cards are explicit and do not expose fake jump targets.
- Done: severity filters and keyboard navigation work in the PDF overlay.
- Done: old renderer/readable-layer false positives such as `pass@ k k` are hidden from student-visible overlay as `artifact_only`.
- Done: native annotated-PDF export is attempted by default for PDF overlay runs and gracefully skips when PyMuPDF is unavailable; `--no-export-annotated-pdf` disables it.
- Done: PDF-only input mode extracts fallback review units from PDF text and continues through the same bbox/overlay pipeline.
- Done: layout-derived `page_layout` review units are appended from `layout_audit.json` when available.
- Done: PDF rendering now uses bundled local PDF.js instead of page-image rendering.
- Done: `check_pdf_overlay_migration.py` records machine-checkable migration readiness across review bundles.
- Done: `check_pdf_overlay_migration.py` distinguishes strict full-review readiness from deterministic renderer smoke checks via `--allow-deterministic-preview`.
- Done: `run_pdf_overlay_migration_matrix.py` enforces the Hidden/NeurIPS-or-ICLR/ACL three-bundle migration matrix once full-review bundles exist.
- Done: `run_pdf_overlay_full_review_matrix.py` runs three fresh PDF-overlay full-review pipelines with a real `--prose-agent-cmd`, then runs the strict migration matrix.
- Done: `run_pdf_overlay_full_review_matrix.py --preflight` validates the three fixture paths, required local PDF tools, prose-agent command executability, nested stdin-CLI bridge executability, and planned pipeline/matrix commands without invoking LLM agents.
- Done: `run_pdf_overlay_full_review_matrix.py` is resumable; completed bundles are skipped by default, with `--rerun-completed` available for forced revalidation.
- Done: `run_agent_command.py` can bridge `run_prose_agent.py` packets to external CLIs by reading `ARIADNE_PROMPT_PACKET`, writing a prompt file, applying nested `--env KEY=VALUE` entries such as `CODEX_HOME=.ariadne_codex_home`, and optionally piping the prompt to stdin.
- Done: `remap_issue_anchors.py` can assist legacy issue-artifact migration by remapping old prose anchors to current TeX-derived review units, without overwriting the original artifacts.
- Done: `implementation-notes.md` records implementation decisions and test results.

## Partial

- None. Code-side partial implementation items have been resolved or moved to explicit known limits / validation gates.

## Known Limits

- Exact formula rectangles remain bounded by PDF extraction reality. The mapper normalizes common math tokens, tries source-TeX math token variants, prefers Poppler word boxes inside SyncTeX regions, and augments math-heavy anchors with overlapping SyncTeX regions. When Poppler and SyncTeX both expose only coarse boxes, the highlight is intentionally coarse rather than fabricated.

## Pending

- Pending: execute `run_pdf_overlay_full_review_matrix.py` with a real prose-agent command for Hidden_Knowledge, one NeurIPS/ICLR-style paper, and one ACL-style paper, then pass the strict migration matrix before declaring PDF overlay production-default across all paper styles.

## Pending Validation

- Production migration validation requires complete fresh Phase A/B prose artifacts and prose/whole-paper compiled findings. Deterministic smoke bundles validate the PDF-overlay technical path, but they are not release evidence. Old HTML-derived anchors cannot be treated as fresh TeX-derived review output.
- Preflight evidence exists at `debug/pdf_overlay_full_review_matrix_preflight/full_review_matrix_summary.json`: Hidden_Knowledge, ICLR-style, and ACL-style fixture paths exist; `pdftotext` / `pdftoppm` are available; and the Codex CLI bridge command is executable. This does not certify migration readiness because it intentionally does not invoke LLM agents.
- Real-run evidence exists at `debug/pdf_overlay_full_review_matrix_real/full_review_matrix_summary.json`: all three jobs reached `needs_prose_phase_a`. The previous `~/.codex` readonly-state issue was resolved by passing `CODEX_HOME=.ariadne_codex_home`; the remaining failure is that the nested Codex CLI cannot reach `https://api.openai.com/v1/responses` from this sandbox/network environment. `debug/pdf_overlay_full_review_matrix_real/external_agent_blocker_diagnostic.json` records the per-paper stderr.

## Next Development Order

1. Run `scripts/run_pdf_overlay_full_review_matrix.py --prose-agent-cmd "<real agent command>" ...` for Hidden_Knowledge, one NeurIPS/ICLR-style paper, and one ACL-style paper without `--preflight` in a user-approved trusted external-agent environment, or with an approved prose-agent command that can run inside the sandbox.
2. Inspect its strict matrix summary. Use `--allow-deterministic-preview` only for renderer smoke checks.
3. Continue hardening PDF.js viewer behavior on long papers and browser `file://` edge cases.
