---
name: ariadne-cs-paper-notes
description: "Ariadne-style critique for CS/AI research-paper drafts (PDF, LaTeX/source tree, compiled PDF, figures/tables, excerpts, or submission packages): senior-advisor diagnostics for claim, evidence, reader path, narrative, structure, paragraph/sentence clarity, figures/tables/captions, numerical consistency, layout, and submission readiness. Produces Chinese diagnostic notes, reader-stuck points, source-principle explanations, paragraph surgery decisions, structured HTML annotation reports, and JSON review artifacts. Trigger for critique, review, red-team, annotate, revise, 审阅, 批注, 红队评审, 给审稿意见, 检查论文, 修改论文, 认真批注, 像老师一样改, 细致改一下, 帮我改句子, 红笔批注, HTML批注, or research-paper review/revision requests."
---

# Ariadne CS Paper Notes

Use this skill for CS/AI paper critique and annotation. Ariadne gives the author a thread through the paper's argument; it diagnoses where a first-day reader gets stuck and what the next draft must make true. It is not a generic proofreading, translation, or ghost-writing skill.

Default voice: senior advisor, in Chinese unless asked otherwise. Frame substantive notes as `读者卡点 -> 单一违反原则 -> 自改问题`. `issue_type` is only a category/filter, while `writing_principle` / `principle` must be one atomic, directly applicable rule rather than a bundle of slogans. Use examples sparingly as `示例方向`; do not silently strengthen claims, invent results, invent citations, or produce paper-ready prose unless the user explicitly leaves critique mode.

## Load Map

Read only the references needed for the request:

- `references/workflow.md`: always for substantive paper critique. It defines scope discipline, artifact extraction, Pass 0-6, coverage, QA gates, and final response.
- `references/review_lenses.md`: when judging paper substance, prose, structure, figures, layout, related work, experiments, references, or submission readiness.
- `references/report_contract.md`: when producing structured JSON artifacts or paper-reader report metadata.
- `references/html_contract.md`: when the user asks for HTML, 网页, 可视化报告, 批注报告, or a saved structured review file.
- `references/numeric_contract.md`: whenever the manuscript has visible tables, prose-cited numbers, averages, deltas, ranks, percentages, or best markers.

Do not routinely load the original teaching notes. This skill uses reviewer-facing references. If the user asks to revise the skill from source writing tips, use the source files outside this skill folder.

## Execution

1. Identify input type: PDF, LaTeX project, single `.tex`, compiled PDF, excerpt, figures/tables, or submission package.
2. Act as the orchestration layer for full-paper jobs. The top-level agent sets scope, launches tools/subagents, collects structured artifacts, runs renderer/audits, and reports paths. It should not read raw layout/reference/numeric/symbol/polish audits or write HTML by hand.
3. Extract signals when a file/project is provided:
   - Prefer `scripts/extract_paper_text.py <paper-path>`.
   - Use `--max-items` high enough for the requested visible scope; rerun if extraction reports incomplete coverage.
   - For LaTeX/project input, identify the entry `.tex` and compile or use a rendered PDF with `scripts/build_paper_pdf.py <paper-path>` when possible.
   - For papers with visible tables or prose numbers, run `scripts/extract_paper_text.py <paper-path> --numeric-json <bundle>/numeric_audit.json` before drafting numeric findings.
4. For paper-reader/full-prose critique, use the deterministic coordinator rather than hand-running the renderer. The Prose Review Agent reads the compact `*.review_units.md` / `*.review_units.jsonl` view for Pass 1-3 prose critique, not rendered HTML.
   - **Default PDF overlay path:** for LaTeX/PDF full-paper annotation requests, including `论文原文 overlay`, `PDF overlay`, `pdf 中高亮`, `嵌入 PDF 的 HTML`, and `针对 PDF 的批注 HTML`, run `scripts/run_review_pipeline.py <main.tex-or-project> --paper-view pdf-overlay --bundle <bundle>`. This generates TeX-derived review units, `sentence_bbox.json`, a copied `paper.pdf`, bundled PDF.js assets, and `ariadne_review_pdf/index.html`.
   - **Issue-report-only path:** when the user explicitly wants only a批注问题报告/no paper body, or when no compiled PDF can be produced, use `--paper-view report-only`. This generates `issue_report.html` with findings and coverage but no embedded paper pane.
   - The top-level deterministic coordinator is `scripts/run_review_pipeline.py <main.tex-or-project> --bundle <bundle>`. Use it to prepare TeX-derived review units, specialist artifacts, resume packets, prose prompt packets, compilation, derivatives, render, and audits. It stops at explicit Prose Phase A/B checkpoints unless `--allow-partial-compile` is passed; do not treat a partial compile as a full-paper prose review.
5. Use the two-phase Prose Review Agent for full-paper critique:
   - Phase A reads the full review units and runs cold skim, linear deep read, paragraph decisions, and section reflections. It writes `prose_issues.jsonl`, `paragraph_decisions.jsonl`, `section_reflections.json`, `cold_skim_frame.json`, and `claim_candidates.json` incrementally in article order.
   - Phase B reads only compact derived inputs (`phase_b_context.json`, curated specialist `*_issues.json`, and claim candidates) to produce `argument_map.json`, `claims.json`, `salvageable_core.json`, and `whole_paper_findings.jsonl`.
   - `scripts/run_prose_agent.py --bundle <bundle> --agent-cmd "<external agent command>"` can run the Phase A/B loop through a pluggable agent. The command receives `ARIADNE_PROMPT_PACKET`, `ARIADNE_BUNDLE`, and `ARIADNE_ISSUE_ARTIFACTS`; it must write the JSON/JSONL targets named in the packet. Use `--dry-run` to validate packets without calling the agent. The runner detects `no_progress` if an agent returns successfully without advancing resume/write-target counts.
   - If the external CLI expects a prompt on stdin, use the provider-neutral bridge: `--agent-cmd "python3 scripts/run_agent_command.py --env CODEX_HOME=.ariadne_codex_home --stdin-prompt --command '<cli command that reads stdin>'"`. The bridge reads `ARIADNE_PROMPT_PACKET`, writes `<packet>.prompt.md`, sets `ARIADNE_PACKET` and `ARIADNE_PROMPT_FILE`, applies any `--env KEY=VALUE` entries, and pipes the rendered packet prompt to the command.
   - If review-unit token estimates exceed the available context, fall back to section-sharded Phase A plus a mandatory synthesis pass; `scripts/build_prose_shards.py` writes `phase_a_shard_manifest.json` and shard packets. Mark this split in coverage.
   - For resumes, run `scripts/phase_a_resume_status.py --next-out <bundle>/phase_a_next_step.json` and read only the compact resume/next-step packets to identify pending sections and append targets; do not reread completed Phase A JSONL shards into orchestration context.
   - For release migration validation across paper styles, first run `scripts/run_pdf_overlay_full_review_matrix.py --preflight --prose-agent-cmd "<external agent command>" --hidden-input <tex> --neurips-input <tex> --acl-input <tex> --out-root <dir>` to validate fixtures/tools/commands without invoking LLM agents. Then rerun without `--preflight`; this runs three fresh PDF-overlay full reviews and invokes the strict migration matrix. Do not use deterministic preview or preflight bundles as migration proof.
6. Keep prose judgment and sidecar artifact checks separate. Launch specialist subagents conditionally for layout, numeric/table, references, symbol/term consistency, source hygiene/anonymity, figure/caption, and polish only when the corresponding raw audit or manuscript signal exists. Each specialist reads its own raw audit and writes a compact `*_issues.json`; the orchestrator reads issue artifacts, not raw audits. Skipped specialists should emit an empty issue stub when downstream tooling expects the artifact.
   - Deterministic specialist reducers are available for layout, numeric, references, source hygiene/anonymity, polish, symbol/notation consistency, and source plus optional rendered-geometry / raster-or-PDF-asset-quality figure/caption checks. Prefer the single runner `scripts/run_p1_specialists.py --bundle <bundle> --tex <main.tex> --pdf <main.pdf>`; it calls `scripts/check_page_layout.py`, `scripts/extract_paper_text.py --numeric-json`, `scripts/check_references.py`, `scripts/check_source_hygiene.py`, `scripts/check_polish.py`, `scripts/check_symbol.py`, `scripts/check_figure_caption.py`, then `scripts/build_specialist_issues.py`.
   - Optional LLM specialist refinement can run after deterministic reducers with `scripts/run_specialist_agent.py --issues-dir <bundle>/issue_artifacts --agent-cmd "<external specialist command>"`. The specialist command receives only curated issue artifacts by default; do not pass raw audits into the orchestrator.
   - Optional semantic figure/caption vision review can run with `scripts/run_vision_figure_agent.py` or pipeline `--vision-figure-agent-cmd`. Page images are tool-only inputs for that specialist; the orchestrator should read only the compact runner summary and curated `figure_caption` issue artifact.
7. After Prose Phase A/B and specialists finish, run `scripts/compile_review_artifacts.py --issues-dir <bundle>/issue_artifacts ...` to normalize JSONL shards and curated issue artifacts into final `findings.json`, `annotations.json`, and `compiled_issue_index.json`. Render from those compiled artifacts; do not ask an LLM to merge issue shards or hand-assign final `F<number>` ids.
8. Derive mechanical companion artifacts with `scripts/build_review_derivatives.py` after compilation. It writes `coverage.json`, `render_manifest.json`, and `pass_observations.json` from compiled JSON and issue artifacts; do not ask an LLM to count or hand-write those files unless the run has an unusual split-part shape the script cannot express. The derivative render mode must match the intended HTML shape: `pdf-overlay` for the default embedded-PDF reader, or `issue-report-only` for a findings report without the paper body.
9. Render from compiled artifacts with the renderer selected by the coordinator. For the default PDF overlay, use `scripts/render_pdf_overlay_html.py` via `run_review_pipeline.py --paper-view pdf-overlay`. For report-only output, use `scripts/render_issue_report_html.py` via `--paper-view report-only`. `--issues-dir` is only for display-facing specialist overlays such as layout, numeric, and figure/caption; source hygiene, hidden reference metadata, and macro-only symbol findings remain in JSON/audit artifacts as artifact-only findings unless they visibly affect the paper. The renderer must preserve the selected PDF/page body or omit the body entirely for report-only mode, and deterministically emit the requested report shape; never ask an LLM to write HTML.
10. Treat script outputs as evidence signals. Never read rendered HTML reports, full layout audits, reference parses, full PDF text dumps, or page images back into orchestration context for verification. Use issue-only artifacts, deterministic compiler/derivative summaries, and compact audit stdout instead. Page images are allowed only for escalated layout/vision signals inside the relevant specialist.
11. Run the Reader-Journey workflow from `references/workflow.md`: Pass 0 engagement contract, Prose Phase A for Pass 1-3, Prose Phase B for Pass 4 and cross-domain integration, specialist issue artifacts for Pass 5, and audit-driven Pass 6.
12. Paper-reader HTML批注 requests use the PDF-first overlay as the primary output. The default companion is only a compact coverage receipt and bbox diagnostics. Do not append the old workbench sections (`总评诊断`, `问题索引`, `主张证据`, `精读批注`, `提交就绪`, `共性问题`, `修改路线`) to paper-reader reports. If the user asks for a report without the paper body, use `--paper-view report-only`.
13. Keep section, paragraph, and sentence diagnostics anchored in the paper view. Do not split them into separate top-level report sections.
14. For HTML reports, follow `references/html_contract.md` and `references/report_contract.md`; create a PDF-first annotation interface plus the companion artifact bundle beside the reviewed paper when writable. Review agents and specialists write JSON only. HTML must be generated by `scripts/render_pdf_overlay_html.py`, `scripts/render_issue_report_html.py`, or another deterministic local renderer chosen by `run_review_pipeline.py`; do not hand-write or paraphrase the paper body inside `#paper-reader`.
15. For paper-reader annotation requests that say full paper, 全文, 逐句, 不抽样, or 不只列 top issues, the overlay annotations must be generated from the current manuscript in this run. Do not use prior review outputs, historical annotations, or cached finding ledgers as the source of review content; they may only be used for calibration/debugging. A canonical/top-issues finding list is not a substitute for the sentence/paragraph/section overlay layer. Prefer anchor-only `annotations.json`: each annotation stores `issue_id`, target id(s), and short UI label, while full teaching content lives once in `findings.json` and is joined by `render_pdf_overlay_html.py` through `sentence_bbox.json`. `annotations.json` must record the current source-derived paper artifact and hash so artifact audit can reject stale annotations after the student revises the paper.
16. Before delivery, run `scripts/audit_html_report.py <report.html>` for HTML and `scripts/audit_review_artifacts.py --bundle <bundle>/ --html <report.html>` when JSON artifacts exist. Fix `ERROR` lines; use only compact stdout in orchestration context.

## Output Rules

Review the requested visible scope at full depth; narrow scope is allowed, lower depth is not. Do not sample silently. Units without issues are counted in coverage receipts, not rendered as visible `clean` rows. For full-paper paper-reader critique, the visible overlay must be dense enough to demonstrate the requested deep read: sentence-level issues for substantive sentence problems, paragraph-surgery notes for non-trivial paragraph decisions, section notes for structural issues, and coverage metadata for clean units. If the result is only a small canonical issue list, mark the scope as focused/top-issues rather than full-paper/逐句.

Do not create duplicate paper-text artifacts. The default paper-reader HTML is `<bundle>/ariadne_review_pdf/index.html` with `paper.pdf` and local `pdfjs/` assets under `<bundle>/ariadne_review_pdf/`; the report-only alternative is `<bundle>/issue_report.html`. Do not emit `*.source_preview.html`, `*_preview.html`, `.source.html` paper-text variants, or plaintext paper dumps next to the paper. Let extraction scripts use their default temp output. Do not place generated helper scripts such as `build_overlay_artifacts.py` inside an artifact bundle.

For every `Blocker` and `Major`, make the finding inspectable in structured artifacts: location, evidence basis, confidence, verification method, severity rationale, downgrade condition, reader friction, one atomic writing principle, and a self-check question. In paper-reader overlay margin cards, do not render `位置`, `原句/片段`, or `证据/验证` as visible labels; the active source sentence/paragraph/heading already provides location and original text. Show `核查依据` only for concrete manuscript-level evidence such as numeric recomputation, PDF layout observation, visible citation/reference checks, or visible submission-readiness risk; keep hidden source hygiene, hidden reference metadata, and macro-only findings as `render_visibility: artifact_only` unless they visibly affect the rendered paper. Never show renderer provenance like `data-sentence-id`, `data-paragraph-id`, or `source-derived paper-reader`. Avoid command-style next-draft tasks unless the user explicitly asks for a revision plan or direct edits.

For numeric/table signals, be strict and concrete. Visible table-value discrepancies remain `Blocker` in the student-facing report until the manuscript explains the aggregation/denominator. Always cite reported value, visible recomputed value, delta, and aggregation caveat when available.

For partial inputs, state missing context and review the local scope at full depth. Mark unsupported passes/layers as `not applicable`, `unavailable`, or `pending`, rather than inventing full-paper certainty.

## Saved HTML Final Block

For saved HTML reports, end with:

```text
Saved artifacts:
  PDF overlay HTML: /absolute/path/<bundle>/ariadne_review_pdf/index.html
  Issue report:     /absolute/path/<bundle>/issue_report.html  (only when --paper-view report-only)
  Artifact bundle:  /absolute/path/<bundle>/
    findings.json          (N findings; B Blocker, M Major)
    annotations.json       (N overlay anchors)
    sentence_bbox.json     (PDF coordinate mapping; unmappable anchors explicit)
    claims.json            (N claims; K overclaims/unsupported)
    issue_artifacts/        (D specialist domains; I curated issues)
    coverage.json          (Pass 0-6: done/pending/skipped)
    render_manifest.json
    pass_observations.json (compact derived pass observations)
```

## Platform Notes

Runtime files are `SKILL.md`, `references/*.md`, `scripts/extract_paper_text.py`, and `scripts/build_paper_pdf.py`. `tests/` is for development/regression checks. `agents/openai.yaml` is Codex UI metadata; keep it aligned with this skill, but do not rely on it for review logic.
