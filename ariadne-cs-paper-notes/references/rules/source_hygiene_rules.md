# Source Hygiene 规则

这是 LaTeX/source package 与 submission-readiness specialist 的维护说明。检测来源仍是 `check_source_hygiene.py`。

## 使命

说明 source artifact hygiene 的判断边界。此类问题影响 anonymous review、venue compliance、reproducibility trust 或 reviewer-visible draft state。

## 判断边界

以下问题可升级：

- anonymous submission 中可见身份信号、仓库 slug、致谢、ORCID、邮箱等；
- TODO/TBD/FIXME/placeholders；
- broken reference markers；
- camera-ready wording 出现在 review 版；
- local absolute paths；
- template mode drift；
- LLM/API-based work 的 prompt/model/version/sampling/disclosure 缺失，且影响复现或伦理合规。

身份/匿名问题应表述为 submission risk，不是对作者身份的指控。venue-specific compliance 需要按当前官方政策核对。

## 批注方向

- 区分 source-only 和 compiled-PDF-visible。
- source-only 且不影响 reviewer-visible paper 的问题默认 artifact-only。
- compiled visible 或 submission-critical 问题才升级到 student-visible。
- 给出清理方向：移除身份文本、检查 front matter、repository link、acknowledgment、metadata、supplement。

## 自查问题

- 这个 source package 能否直接通过 anonymous review hygiene？
- TODO/placeholders 是否可见给 reviewer？
- 问题只在 source 中，还是影响 rendered paper？
- 如果提交 code/supplement/artifact，reviewer 能否找到 README、environment、dummy run 和 main-result path？
