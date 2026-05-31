# Polish 规则

这是 deterministic source polish checks 的维护说明。它不替代 Prose Style；句子精确性和段落 flow 属于 `prose_style_rules.md`。

## 使命

说明拼写、重复词、LaTeX reference spacing、表面一致性等机械问题的判断边界。polish finding 应帮助作者清理投稿表面摩擦，但不要把机械信号升级成论证问题。

## 判断边界

重复词、breakable reference spacing、术语拼写漂移、unicode punctuation、abbreviation 格式等，通常是 `Polish` 或 `Minor`。只有当它们影响主证据可读性、引用可验证性或投稿可信度时才升级。

表格抽取中的 `No No`、`Yes Yes` 等可能是表格结构，不应轻易作为 repeated-word 正文错误。

## 批注方向

- 说明这是 surface friction，不要暗示核心 claim 错误。
- 优先给可执行清理方向：检查列出的候选、统一术语、使用 nonbreaking reference spacing。
- 如果信号可能来自解析器，应标明需要人工确认。

## 自查问题

- 这是源文本真实错误，还是表格/公式抽取噪声？
- 修复后是否能减少 reviewer 的表面摩擦？
- 问题是否足够严重到影响主证据，还是只应作为 artifact-only hygiene？
