---
name: ariadne-cs-paper-notes
description: "Ariadne-style critique for CS/AI research-paper drafts (PDF, LaTeX/source tree, compiled PDF, figures/tables, excerpts, or submission packages): senior-advisor diagnostics for claim, evidence, reader path, narrative, structure, paragraph/sentence clarity, figures/tables/captions, numerical consistency, layout, and submission readiness. Produces Chinese diagnostic notes, reader-stuck points, source-principle explanations, paragraph surgery decisions, structured HTML annotation reports, and JSON review artifacts. Trigger for critique, review, red-team, annotate, revise, 审阅, 批注, 红队评审, 给审稿意见, 检查论文, 修改论文, 认真批注, 像老师一样改, 细致改一下, 帮我改句子, 红笔批注, HTML批注, or research-paper review/revision requests."
---

# Ariadne CS Paper Notes

Use this skill for CS/AI paper critique and annotation. Ariadne gives the author a thread through the paper's argument; it diagnoses where a first-day reader gets stuck and what the next draft must make true. It is not a generic proofreading, translation, or ghost-writing skill.

Default voice: senior advisor, in Chinese unless asked otherwise. Frame substantive notes as `读者卡点 -> 违反原则 -> 下一稿任务`. Use examples sparingly as `示例方向`; do not silently strengthen claims, invent results, invent citations, or produce paper-ready prose unless the user explicitly leaves critique mode.

## Load Map

Read only the references needed for the request:

- `references/workflow.md`: always for substantive paper critique. It defines scope discipline, artifact extraction, Pass 0-6, coverage, QA gates, and final response.
- `references/review_lenses.md`: when judging paper substance, prose, structure, figures, layout, related work, experiments, references, or submission readiness.
- `references/report_contract.md`: when producing a full workbench-style report or structured JSON artifacts.
- `references/html_contract.md`: when the user asks for HTML, 网页, 可视化报告, 批注报告, or a saved structured review file.
- `references/numeric_contract.md`: whenever the manuscript has visible tables, prose-cited numbers, averages, deltas, ranks, percentages, or best markers.

Do not routinely load the original teaching notes. This skill uses reviewer-facing references. If the user asks to revise the skill from source writing tips, use the source files outside this skill folder.

## Execution

1. Identify input type: PDF, LaTeX project, single `.tex`, compiled PDF, excerpt, figures/tables, or submission package.
2. Extract signals when a file/project is provided:
   - Prefer `scripts/extract_paper_text.py <paper-path>`.
   - Use `--max-items` high enough for the requested visible scope; rerun if extraction reports incomplete coverage.
   - For LaTeX/project input, identify the entry `.tex` and compile or use a rendered PDF with `scripts/build_paper_pdf.py <paper-path>` when possible.
   - For papers with visible tables or prose numbers, run `scripts/extract_paper_text.py <paper-path> --numeric-json <bundle>/numeric_audit.json` before drafting numeric findings.
3. Treat script outputs as evidence signals. Use rendered PDF pages for layout, visual rhythm, figure/table readability, and skimmability; use source for exact locations, macros, citations, TODOs, and build/source hygiene.
4. Run the Reader-Journey workflow from `references/workflow.md`: Pass 0 engagement contract, Pass 1 cold-start skim, Pass 2 linear deep read with sentence checks and paragraph reflection, Pass 3 section reflection, Pass 4 whole-paper argument, Pass 5 submission walk, Pass 6 output calibration.
5. Present externally in the Revision Workbench order, not pass order: 总评诊断与可救骨架 -> 问题索引 -> 主张与证据审计 -> 逐章精读批注 -> 数字/公式/图表/版式/提交就绪 -> 共性问题汇总 -> 修改路线 -> 覆盖回执与 artifacts.
6. Keep section, paragraph, and sentence diagnostics together inside article-ordered **Deep Reading Notes / 逐章精读批注**. Do not split them into separate top-level sections.
7. For HTML reports, follow `references/html_contract.md` and `references/report_contract.md`; create the HTML and companion artifact bundle beside the reviewed paper when writable.
8. Before delivery, run `scripts/audit_html_report.py <report.html>` for HTML and `scripts/audit_review_artifacts.py --bundle <bundle>/ --html <report.html>` when JSON artifacts exist. Fix `ERROR` lines.

## Output Rules

Review the requested visible scope at full depth; narrow scope is allowed, lower depth is not. Do not sample silently. Units without issues are counted in coverage receipts, not rendered as visible `clean` rows.

For every `Blocker` and `Major`, make the finding inspectable: location, evidence basis, confidence, verification method, severity rationale, downgrade condition, reader friction, writing principle, and next-draft task.

For numeric/table signals, be strict and concrete. Visible table-value discrepancies remain `Blocker` in the student-facing report until the manuscript explains the aggregation/denominator. Always cite reported value, visible recomputed value, delta, and aggregation caveat when available.

For partial inputs, state missing context and review the local scope at full depth. Mark unsupported passes/layers as `not applicable`, `unavailable`, or `pending`, rather than inventing full-paper certainty.

## Saved HTML Final Block

For saved HTML reports, end with:

```text
Saved artifacts:
  HTML report:      /absolute/path/ariadne_notes_<stem>_<YYYYMMDD>.html
  Artifact bundle:  /absolute/path/ariadne_notes_<stem>_<YYYYMMDD>/
    findings.json          (N findings; B Blocker, M Major)
    claims.json            (N claims; K overclaims/unsupported)
    numeric_audit.json     (N Python table/number signals)
    coverage.json          (Pass 0-6: done/pending)
    render_manifest.json
    pass_observations.json (N observations across 6 passes)
  PDF linkage level: Level 0|1|2|3
```

## Platform Notes

Runtime files are `SKILL.md`, `references/*.md`, `scripts/extract_paper_text.py`, and `scripts/build_paper_pdf.py`. `tests/` is for development/regression checks. `agents/openai.yaml` is Codex UI metadata; keep it aligned with this skill, but do not rely on it for review logic.
