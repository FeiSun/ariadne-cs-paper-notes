# Reference 规则

这是 bibliography/reference specialist 的维护说明。不要把它和 `related_work_rules.md` 混淆；Related Work 管学术定位，本文件管渲染参考文献和 BibTeX metadata hygiene。

## 使命

说明引用元数据问题的判断边界：参考文献是否可验证、一致、投稿就绪。检测来源仍是 `check_references.py`。

## 判断边界

当 cited evidence 难以验证，或 metadata drift 暗示 source hygiene 低时升级：隐藏 DOI/URL/eprint、arXiv 与 published version 重复、author/year/title 不一致、venue abbreviation 漂移、acronym 未保护、rendered bibliography 数量不一致。

普通 BibTeX `Last, First` 作者格式不应自动报错；只有确实影响渲染或格式一致性时才写 issue。

## 批注方向

- 要求 normalize metadata 并检查 rendered bibliography。
- 不要在这里重写 Related Work 定位。
- 对可能误报的 author-field signal，优先 artifact-only 或 warning。

## 自查问题

- 审稿人能否只凭 rendered bibliography 验证 source？
- 这是 metadata hygiene，还是 Related Work positioning 问题？
- preprint 和 published version 是否重复或表示不一致？
- 规范 BibTeX 字段并重新渲染能否解决？
