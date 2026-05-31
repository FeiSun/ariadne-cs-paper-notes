# Prose Phase B 规则

Phase B 做整篇 claim-evidence synthesis 和 cross-domain integration。它只读 `phase_b_context.json` 和 curated specialist issue artifacts，不重新读 full review units 或 raw audits。

## 输出合同

每条 `whole_paper_findings.jsonl` student-visible issue 必须包含：

- `local_id`, `severity`, `issue_type`, `title`, `diagnosis`;
- `reader_friction`: 中文说明整篇层面的读者卡点；
- `writing_principle`: 闭合原则表中的一个原则；
- `self_check`: 中文自改问题；
- `confidence`, `evidence_refs`, `severity_rationale`, `downgrade_condition`;
- `source_issue_ids`，必要时含 `target_anchors`, `related_issue_ids`, `claim_ids`。

## 使命

判断全稿中心论证是否 coherent、adequately evidenced、honestly bounded，并且目标读者能否快速恢复。Phase B 只把 specialist issues 纳入全局 finding，当它们改变 claim strength、reader trust、acceptance risk 或 submission readiness。

## Whole-Paper Questions

- 这篇 paper 希望读者记住的一个中心 claim 是什么？
- 读者读完后应该更新哪个信念？
- 摘要/引言承诺的 paper 是否被 Method、Experiments、figures、conclusion 支撑？
- 哪些 claims unsupported、over-scoped，或只由 hidden/weak evidence 支撑？
- limitations 是诚实边界，还是 future-work gesture？
- 最可能的拒稿理由是什么，主文是否回答/收窄/隐藏了它们？
- 论文是否回答 why now，而不只是 why important？
- 论文类型和证据合同是否匹配正在卖的 claim？

## Claim-Evidence Map

对每个 major claim，把证据分类为：

- absent；
- present but hidden；
- present but indirect；
- present but weak / unfairly compared；
- adequate within a stated boundary。

不要替作者强化 claim 来匹配证据。要么要求补证据，要么要求收窄 claim。

## 红队镜头

- 一文一核：所有 contribution 是否服务同一个中心？
- gap-depth：gap 是否超过 “X 没被用于 Y”？
- insight-vs-mechanism：是否先说作者看见了什么，再说机制？
- boundary：怀疑者是否知道结果不能泛化到哪里？
- evidence-chain：实验是否在公平预算和 baseline 下回答 RQ？
- fast-skim：标题、摘要、heading、段首句和 caption 能否重建 argument？
- rejection-reason：前三个可能拒稿理由是否已在主文回应？

## Specialist Integration

Numeric、layout、reference、source hygiene、symbol、figure/caption、polish issue 只有在影响中心证据、读者信任、投稿风险或 claim scope 时，才升级为 whole-paper finding。否则保留为 lower-level source issue ids。

## 诊断写法

Phase B 不写“实验需要更多 baseline”这种表面话，而要说清 claim 为什么站不稳。例如：

- 中心 claim 强于 visible evidence envelope；
- paper recommendation 缺 operational bridge；
- theory-to-experiment bridge 缺 assumptions 和 finite-sample calibration；
- main evidence 回答了一个窄问题，却被摘要写成 broad robustness；
- appendix-only evidence 承担了主文 claim-critical 工作。

`writing_principle` 优先用 `改变读者理解状态`、`一文一核`、`文字精确性先于 flow`、`显式逻辑，不让读者猜`、`红队式自查`、`特定读者共同体`。

## 自查问题

- 如果不补实验，哪些 claim 必须收窄？
- 哪个 finding 修掉后最能提高可接受性？
- 哪些局部问题其实是同一个整篇 claim/evidence 问题的症状？
- 什么证据能让每个 Major/Blocker 降级？
- 全稿最终应该让读者带走哪一个 bounded contribution？

## 输出规则

- 只读 `phase_b_context.json`。
- 吸收 lower-level issues 时保留 `source_issue_ids`。
- 跨 section 问题用多 anchor，不要伪装成单句问题。
- 不写 HTML，不手动分配最终 `F<number>` ids。
