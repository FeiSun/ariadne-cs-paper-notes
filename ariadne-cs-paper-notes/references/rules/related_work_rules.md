# Related Work 规则

本规则用于 Related Work section 和全文定位。不要把它和 `reference_rules.md` 混淆；后者只管 bibliography metadata hygiene。

## 使命

Related Work 不是报菜名，而是建立研究空间坐标系：已有路线按什么假设、设置、证据类型和边界分组；本文在哪个坐标上推进了一步。

## 检查点

- prior work 是否按 route、assumption、setting 或 boundary 分组，而不是按时间线。
- 每组是否以本文定位收束。
- 对比是否公平、具体，而不是 strawman。
- prior-work categories 是否和后文 baseline / experimental comparison 对齐。
- 这一节是否让 paper 显得必要，而不是只是 incremental。
- 是否避免 citation dump：先解释一组 work 代表什么，再列代表性 citation。
- 语气是否描述路线/设定差异，而不是攻击 prior work。

## 失败信号

- 长 author-year list 取代综合。
- 每段只写 A 做了 X、B 做了 Y，没有组织 field。
- gap 只是 “prior work has not used X for Y”。
- fails / ignores / cannot / lacks 等强词没有条件和边界。
- Related Work 和 Experiments 暗示不同 competitor categories。
- 相邻关键路线只作为 citation dump 出现。
- 缺失 strong baseline 被隐藏，而不是解释。

## 诊断写法

命名缺失的坐标：assumption、route、setting、evidence type、boundary 或 baseline link。`writing_principle` 优先用 `加入并推动已有对话`、`特定读者共同体`、`problem-solution text`、`文字精确性先于 flow`。

## 修改方向

- 按假设/路线/设置分组 prior work。
- 用 comparison sentence 替代 citation list。
- 每组末尾落一个转折句，解释本文占据的 gap。
- 用 “在 X assumption 下” 或 “在 Y setting 中” 这类公平语言，避免绝对失败叙述。

引用格式、DOI/URL、venue abbreviation 和 BibTeX hygiene 属于 `reference_rules.md` 与 deterministic reference checks。

## 示例方向

弱：`Many methods study this problem [1,2,3,4,5,6,7].`

强的方向：先识别两到三条路线，解释每条路线的假设，再为每组列代表作。

弱：`Existing methods fail to handle noisy retrieval.`

强的方向：写清已有方法在哪些前提下有效，以及你的 setting 如何改变这些前提。

弱：`Prior work ignores our setting.`

强的方向：说明 prior work 主要研究 X under Y assumption；本文移除/改变 Y，因此暴露 Z failure mode。

## 自查问题

- 这一节建立了什么坐标系？
- 每组 work 的 route、assumption、setting 或 boundary 是什么？
- 每组结尾是否说明本文坐在哪里？
- Experiments 中的 baselines 是否在这里被预告？
- 被引用作者会不会认为你的对比是公平的？
