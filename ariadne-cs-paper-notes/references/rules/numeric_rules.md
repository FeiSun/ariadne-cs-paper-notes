# Numeric 规则

这是 numeric specialist 的维护说明。默认 Prose prompt 不读取本文件；数值信号检测和复算来自 `extract_paper_text.py --numeric-json` 与 deterministic reducers。严格表格/数字合同见 `numeric_contract.md`。

## 使命

说明 visible table/prose-number discrepancy 的判断边界。数值问题必须具体、可核查，不能用“可能有问题”“建议复查”这类空泛语言替代 reported/computed/delta。

## 判断边界

当可见表格/正文数字与可见复算值不一致，并且差异超出合理 rounding/aggregation 解释时，通常应为 `Blocker`。如果 weighted/micro aggregation、隐藏 denominator 或表格解析错误可能解释差异，必须作为 aggregation caveat 写清。

如果 numeric specialist 没有有效检查任何信号，应写入 coverage blind spot，而不是假装数值已通过。

## 批注要求

数值 finding 必须包含：

- reported value；
- visible computed value；
- delta；
- aggregation caveat；
- evidence refs；
- 明确说明“复算 X，而表中写 Y”。

不要把 story logic 的推断写成 deterministic numeric error。故事逻辑和证据强度属于 Prose；表格算术属于 Numeric。

## 自查问题

- 这个问题是确定复算错误，还是 denominator/aggregation 未说明？
- reported/computed/delta 是否都出现在诊断里？
- 读者能否从可见表格复现这个核查？
- 如果解析器可能误报，是否降级为 blind spot 或 render-required？
