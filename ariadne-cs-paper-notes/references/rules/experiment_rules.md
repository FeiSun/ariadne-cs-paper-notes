# Experiments 规则

本规则用于 Experiments section 和 Phase B 的证据链综合。它判断实验论证，不做数值复算；数值复算边界见 `numeric_rules.md`。

## 使命

实验部分首先是一条结构化质证链，不是表格巡礼。它要让读者看见每个主张由哪个研究问题、设置、metric、baseline、预算、aggregation 和边界支撑。

## 检查点

- 表格/图之前是否先给 research questions 或 evidence jobs。
- 每个主表/主图是否支撑一个明确 claim。
- baseline 是否强，比较是否在数据、预算、metric、protocol 上公平。
- 小幅提升是否有 variance、seeds、CI 或跨设置一致性。
- ablation 是否对应中心机制，而不是只证明“加了模块更好”。
- failure cases 和 limitations 是否解释边界，而不是被隐藏。
- 不看代码，读者能否大致复现主结果设置。
- 主图/主表是否可扫读为证据，还是要求读者做算术和查隐藏 denominator。
- cost/latency/compute/supervision claim 是否在可比资源下测量。

## 失败信号

- section 按 “Table 1, Table 2, more results” 组织，而不是按问题组织。
- 结果句复读表格数值，却不解释 pattern、exception 或 mechanism。
- 摘要/引言的 broad claim 只有窄证据或间接证据。
- baseline 弱、预算不匹配或缺少合理排除理由。
- tiny gain 被写成广泛 superiority，但没有稳定性证据。
- claim-critical evidence 只在 appendix。
- limitation 写成 future work，而不是当前假设、成本或 failure boundary。
- failure case 只展示 cherry-picked success，没有边界分析。
- efficiency/resource claim 缺硬件、预算、样本数或成本单位。

## 诊断写法

指出断裂的证据链：缺 research question、不公平 comparator、隐藏 denominator、variance 支撑弱、因果解释过强、ablation 缺失、泛化过界。`writing_principle` 优先用 `文字精确性先于 flow`、`显式逻辑，不让读者猜`、`特定读者共同体`、`不要让读者做翻译题/查字典题/算术题` 或 `红队式自查`。

## 修改方向

- 按 3-4 个 research questions 重组实验。
- 每个结果局部写清 setting、metric、baseline、budget、aggregation 和 boundary。
- 解释规律和异常，不复述可见表格数值。
- 当证据只覆盖子集、模型规模、数据集、预算或 metric 时，收窄 claim。

## 示例方向

弱：`Our method reduces cost by 40%.`

强的方向：补齐同一 decoding budget、硬件、每 query 平均成本、比较对象和统计口径。

弱：`The model performs well on rare cases.`

强的方向：说明 rare case 的定义、样本数、metric、baseline 和提升幅度。

弱：`The ablation proves the module is necessary.`

强的方向：改成“提供证据表明该模块在当前评估设置下有贡献”；若 gain 很小，要求 variance 或重复运行。

## 自查问题

- 每个表/图到底支撑哪个 claim？
- Related Work 中命名的强 baseline 是否在实验中比较或有明确排除理由？
- 主结果能否经受 matched-budget 比较？
- gain 很小时，稳定性证据是否足够？
- limitation 是否说明当前假设、成本和失败边界，而不仅是 future work？
