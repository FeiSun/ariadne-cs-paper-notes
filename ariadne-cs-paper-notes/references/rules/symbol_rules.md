# Symbol 规则

这是 notation/symbol consistency specialist 的维护说明。检测来源仍是 `check_symbol.py`。Method 的机制解释问题见 `method_rules.md`。

## 使命

说明符号和数学命令一致性 issue 的判断边界。目标是让读者能建立一个稳定 notation registry，而不是猜两个符号是否同义。

## 判断边界

当 symbol reuse、macro redefinition、undefined command-like math token、variant-symbol pair 迫使读者猜测含义时，应报告。大多数 finding 应写成 verification request，除非 manuscript 已经证明是数学错误。

常见 LaTeX 命令如 `\le`, `\ge`, `\to`, `\mid`, `\bigl`, `\bigr`, `\displaystyle` 不应因 allowlist 缺失被当作实质 notation 问题。

## 批注方向

- 要求稳定 notation contract。
- 第一次出现时定义符号和缩写。
- 跨 section、equation、figure、pseudocode 保持同名同义。
- 如果是 checker allowlist 噪声，应留在 artifact-only 或修 checker，不升级给学生。

## 自查问题

- 读者能否不用猜就建立一张符号表？
- 这是 notation consistency，还是 Method explanation？
- 变体符号是有意区分并已定义，还是无意漂移？
- 公式、图、伪代码和正文是否用同一名称表示同一对象？
