# Ariadne Numeric Contract

Use this file whenever a paper has visible tables, averages, totals, deltas, relative improvements, percentages, ranks, best/second-best markers, prose-cited numbers, or metric summaries. This contract intentionally keeps paper data strict.

## Extraction

Run structured numeric extraction before drafting numeric findings when machine-readable PDF/source signals can be extracted:

```bash
scripts/extract_paper_text.py <paper.pdf-or-tex> --numeric-json <bundle>/numeric_audit.json
```

Preserve `numeric_audit.json` in the artifact bundle. If visible tables exist but no numeric audit was produced, mark Pass 5/table arithmetic incomplete rather than claiming full numeric coverage.

Use `--max-items` high enough to cover all visible numeric signals. If extraction reports incomplete numeric coverage, rerun with a larger value.

## Strict Rendering Rule

Every numerical signal in `numeric_audit.json` with `render_required: true` must appear in **Submission Readiness** with:

- concrete table id / row / object label;
- `reported_value`;
- `visible_computed_value`;
- `delta`;
- aggregation caveat or rebuttal hypothesis.

Visible table-value discrepancies are `Blocker` in the student-facing report until the manuscript explains the aggregation/denominator. Ambiguity changes caveat and rebuttal framing, not severity.

Do not write vague feedback such as only `平均值有偏差`, `需复查`, `需要核对`, or `建议复查`. A useful note says exactly what the table reports, what visible recomputation gives, and what missing denominator/weights/rounding explanation would resolve it.

Preferred Chinese labels in visible HTML:

- `表中数值` for `reported_value`
- `可见复算值` for `visible_computed_value`
- `差值` for `delta`
- `口径说明` for `aggregation_caveat`

Do not render raw schema keys such as `reported_value`, `visible_computed_value`, `delta`, or `aggregation_caveat` in Chinese-facing body text.

## Signal Tiers

- **Deterministic**: visible-cell arithmetic gap too large for plausible rounding/aggregation, broken refs/cites, TODO/placeholders, anonymity leaks, blank main-evidence cells, undefined source symbols. Render directive language: "X, not Y", "复算 X，而表中写 Y", "缺失", "未定义".
- **Likely error**: concrete visible mismatch with plausible but unstated rebuttal. Render the concrete comparison and name the rebuttal required from the author.
- **Ambiguous**: small gap or possible weighted/micro aggregation/hidden decimals. Still render concrete comparison. For visible table-value discrepancies, keep `Blocker`; explain what denominator/weights/rounding proof would resolve it.
- **Inference-only**: story logic, paragraph surgery, strategic framing. Use reader-friction language rather than mechanical-error verdicts.

## Magnitude-Aware Rebuttal

Author rebuttals must quantitatively explain gaps. "Maybe weighted aggregation" is insufficient unless the manuscript states denominator/weights or the magnitude is plausibly rounding-level.

Small gaps can remain ambiguous when hidden precision or micro/macro aggregation could explain them. Gaps above 2 percentage points or 5% relative difference should not be softened by theoretical aggregation unless a specific formula or denominator is visible.

## Numeric Finding Requirements

Every numeric/table finding promoted into `findings.json` includes:

- `reported_value`
- `visible_computed_value`
- `delta`
- `aggregation_caveat`
- diagnosis containing both reported and computed values
- `severity: "Blocker"`

Rendered row example:

```text
Table 1, Method A Score X：表中数值 95.77；可见复算值 95.52；差值 +0.25；若使用 weighted/micro aggregation，表注必须说明 denominator。
```

## Table and Cross-Reference Sweep

For every visible table in scope:

1. traverse numerical cells;
2. recompute visible row/column averages, totals, deltas, relative gains, percentages, ranks, best/second-best markers, and win counts when feasible;
3. trace prose/caption/abstract/conclusion numbers back to source tables/figures;
4. check same dataset/model/baseline/metric names across tables;
5. flag impossible/suspicious values such as AUC > 1, percentages beyond stated denominators, all-zero std over seeds, or ablations dominating full model everywhere;
6. state when raw data, seed-level results, hidden decimals, or calculation scripts are required but unavailable.

If output cannot fit full record, split into parts; do not replace the full walk with discrepancy-only sampling.

## Parser False Positives

If a numeric signal is a parser false positive, mark it as `render_required: false` in `numeric_audit.json` with a reason before audit, rather than silently dropping it. The student should be able to see what was checked and why it did or did not become an issue.

## Tool Boundary

Scripts emit evidence signals, not final judgments. Use the signal values concretely, then decide explanation and caveat from the paper context, metric definition, claim role, and visible aggregation policy.
