# Method 规则

本规则用于 Method section，以及 Phase B 中涉及机制、novelty、定义、假设和符号解释的综合判断。

## 使命

Method 的任务不是把代码翻译成公式，而是让读者用最低认知负担理解：输入是什么、核心机制是什么、输出是什么、真正新在哪里、依赖哪些假设、哪些不是本文目标。

## 检查点

- section 开头是否先给地图，再进入公式和实现细节。
- 读者能否恢复 input -> key mechanism -> output。
- standard component 和真正 novelty 是否被隔离。
- 定义、假设、non-goals 是否先于使用出现。
- 重要公式后是否有自然语言解释：这个量排什么、越大意味着什么、为什么服务失败模式。
- 是否用 running example、toy example、shape、图示降低真实阅读负担。
- 伪代码和公式是在暴露逻辑，还是在复述实现噪声。
- 是否先写 insight / failure property，再写 mechanism。
- tensor shape、score 意义、training/inference 阶段是否在影响理解处写清。

## 失败信号

- Method 第一段直接进入符号，读者还不知道机制地图。
- 标准组件和作者贡献混在一起。
- 公式没有解释执行哪一步、为什么需要这一步。
- selector、score、trajectory、evidence、document、span、token 等概念未定义。
- 默认 oracle retrieval、固定预算、已知候选或特殊标签，却没有声明。
- 章节像代码说明书，不像设计论证。
- 伪代码包含 Python 噪声，却隐藏输入、输出或决策逻辑。
- 同一对象在正文、公式、图和算法中名称漂移。

## 诊断写法

先命名读者缺失的 mental model：机制地图、novelty 边界、定义、假设、公式解释或复现路径。`writing_principle` 优先从 `结构决定意义`、`显式逻辑，不让读者猜`、`洞察 ≠ 机制`、`知识的诅咒`、`低认知负担 / reader-first` 中选择一个。

## 修改方向

- 增加简短 overview paragraph 或机制图。
- 写清观察到的失败模式 / 属性，再推出设计原则和机制。
- 隔离已有组件和本文真正改变的部分。
- 先定义术语和符号，再使用。
- 只在能降低真实阅读负担时加入 running example、toy example 或 tensor shape。

不要把本文件用于 deterministic symbol audit；符号一致性维护见 `symbol_rules.md`。

## 示例方向

弱：`We introduce a selector module and an aggregator module.`

强的方向：先说观察到的失败模式，再解释为什么拆分 selection 和 aggregation 能解决这个失败模式。

弱：`Let s_i be computed by Eq. (2).`

强的方向：公式后补一句自然语言解释：这个 score 排什么、越大代表什么、为什么这个排序降低前文失败模式。

弱：`Algorithm 1 shows our framework.`

强的方向：先写算法输入、输出、主决策步骤，并标明哪些行对应本文 novelty。

## 自查问题

- 读者能否在读公式前画出 input -> mechanism -> output？
- 哪些组件是标准组件，哪些组件是本文贡献？
- 哪个假设不成立时方法会失效或不适用？
- 每个重要公式是否同时回答“做什么”和“为什么存在”？
- 不看代码，读者能否复原方法逻辑？
