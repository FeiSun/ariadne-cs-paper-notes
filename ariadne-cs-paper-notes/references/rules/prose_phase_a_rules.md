# Prose Phase A 规则

Phase A 做全文线性深读：cold skim、逐节逐段逐句批注、paragraph decisions、section reflections。它读完整 `review_units.md/jsonl`，但写出的可见批注必须是中文导师式诊断。

## 输出合同

每条 `prose_issues.jsonl` student-visible issue 必须包含：

- `local_id`, `severity`, `issue_type`, `title`, `diagnosis`;
- `reader_friction`: 中文写出读者卡在哪里；
- `writing_principle`: 闭合原则表中的一个原则；
- `self_check`: 中文自改问题；
- `confidence`, `evidence_refs`, `severity_rationale`, `downgrade_condition`;
- `target_anchors`, `section_id`，必要时含 `paragraph_id` / `primary_anchor`。

不要只写 title+diagnosis。干净句子通过 paragraph receipt 计入覆盖率，不渲染“没问题”评论。

## Pass 1：Cold Skim

先像第一次接触论文的审稿人一样读标题、摘要、引言开头/结尾、主图/主表、结论和 limitation。记录：

- 第一眼中心主张是什么；
- 读者最早在哪里卡住；
- 论文类型和证据合同；
- 哪些 claim 需要 Phase B 综合核查；
- 初步的 likely rejection reasons。

## Pass 2：线性深读

按文章顺序逐节读，不抽样。每个段落都要有 `paragraph_decisions.jsonl` receipt，并记录 sentence review coverage。

重点判断：

- What / Why / Gap / Idea / Evidence / Boundary 是否显式。
- 段落是否一段只做一件事。
- topic sentence 是否承担可扫读骨架。
- 句子是否保留 scope、condition、comparator、metric、evidence strength、boundary。
- claim 是否比 evidence 更强。
- Method、Experiments、Related Work 是否遵守各自规则文件。

## 段落决策

每段必须给一个决策：`keep`, `revise`, `split`, `merge`, `move`, `delete`。记录：

- 当前 paragraph job；
- 是否只有一个 job；
- topic sentence 做了什么；
- 下一稿需要让这一段变成什么；
- clean sentences 的覆盖 receipt。

## Section Reflection

每节结束后更新 `section_reflections.json`，包括：

- 读者读完这一节后处于什么理解状态；
- 这一节在全稿 argument 中的角色；
- 是否支撑中心主张；
- 结构弱时给 3-6 步 section skeleton；
- unresolved questions；
- linked local issue ids。

## 各节最低检查

- Abstract/Introduction：What / Why / Gap / Idea / Evidence / Boundary 是否可见，是否 overclaim。
- Related Work：是否建立坐标系，假设和 baseline 是否前后呼应。
- Method：先地图后细节，novelty 隔离，定义和假设先于使用，公式有自然语言解释。
- Experiments：RQ/evidence jobs 可见，claim-evidence alignment，baseline/fairness/budget/variance/boundary 可核查。
- Figures/Tables/Captions：一个证据任务，caption takeaway-first，不让读者做算术/翻译。
- Conclusion/Limitations：收束中心更新和边界，不要 tense-shifted abstract。

## 失败信号

- 第一页有背景但没有问题压力。
- 摘要、引言贡献、主图/主表、结论卖的不是同一篇 paper。
- 段落同时定义、动机、方法、结果和过渡。
- topic sentence 只有 “we next describe” 或 “Table 2 shows”。
- 读者必须猜一个 result 为什么支撑 claim。
- 为了 flow 删除 scope、baseline、denominator 或 evidence strength。
- Figure 1 先展示所有模块，却不告诉读者核心 idea。
- contribution bullets 是活动列表而不是可验证 claim。
- section 的段首句连读不成 mini-outline。

## 自查问题

- 聪明但陌生的读者只读第一页能否讲出这篇 paper？
- 每段在做什么：证明、定义、比较、动机、过渡、报告证据？
- 哪句话第一次让 section job 可见？
- 当顺序才是真问题时，批注是否先诊断结构而不是改句子？
- clean sentences 是否通过 coverage 记录，而不是塞进可见批注？
