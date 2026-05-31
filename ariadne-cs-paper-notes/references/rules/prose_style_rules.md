# Prose Style 规则

本规则用于句子精确性、flow、段落任务和局部 style。它不是 deterministic source polish；机械拼写/LaTeX hygiene 见 `polish_rules.md`。

## 使命

判断每个句子和段落是否在保留精确含义的同时降低读者工作量。文字精确性先于顺滑：删除 denominator、comparator、scope 或 evidence strength 换来的短句，是更差的句子。

## 精确性槽位

每个关键 claim 都应让读者恢复：

- object：哪个 method、变量、数据集、样本组或现象；
- scope：全部数据、子集、任务族、模型规模或部署场景；
- condition：budget、split、prompt、hardware、assumption、训练/推理阶段；
- comparator：baseline、upper bound、random level、full-data setting、prior SOTA、oracle；
- metric/denominator：metric、比例基数、aggregation、cost unit、speedup 公式；
- evidence：table、figure、theorem、ablation、case study、user study、counterfactual；
- force：demonstrates/shows 还是 suggests/is consistent with/provides evidence for；
- boundary：不能泛化到哪里。

如果删掉一个限定词会改变这些槽位，它就不是 polish，而是 claim 的一部分。

## 常见失败模式

- unscoped comparison：improves / robust / efficient / generalizes 没有 comparator、metric、setting。
- over-broad generalization：窄实验写成方法广泛属性。
- causal overreach：because / proves / fixes / shows 的证据只是 correlation、ablation 或 trend。
- undefined hard case：hard、noisy、rare、faithful、robust、efficient、safe 没有 operational definition。
- floating referent：this / it / they / our framework / the method 有多个可能先行词。
- modifier drift：using / with / under / trained on / averaged over / despite / although 挂错对象。
- false connector：however / therefore / moreover / in contrast 关系不成立。
- buried stress：真正 takeaway 藏在句中或从句里。
- delayed verb：长主语拖延动词，句子 spine 丢失。
- abstract noun stack：名词化隐藏动作和责任。
- multiple paragraph jobs：一段同时定义、动机、方法、结果和过渡。
- generic topic sentence：`Table 2 shows...` 或 `We next describe...` 没有判断。

## Flow 规则

- 句首接旧信息，句尾放新信息。
- 把最重要的新贡献、对比或 takeaway 放在 stress position。
- 主语和动词尽量靠近。
- 一句话尽量只推进一个主要动作。
- 概念已经抽象时，优先用具体 actor 和 verb。
- 段首句应构成 section 的可见骨架。

## 诊断写法

批注要指出具体读者工作量：缺口径、缺比较对象、因果力过强、指代漂移、连接词不真、段落任务过多。`writing_principle` 优先用 `文字精确性先于 flow`、`句首接旧信息，句尾放新信息`、`一段只做一件事`、`显式逻辑，不让读者猜`。

## 示例方向

弱：`Our method reduces cost by 40%.`

强的方向：补齐同一预算、硬件、单位、比较对象和 scope。

弱：`Our approach generalizes to unseen tasks.`

强的方向：说明 unseen 的定义、是否 additional fine-tuning、held-out task 数量、metric 和 strongest baseline。

弱：`The ablation proves that the selector fixes retrieval noise.`

强的方向：把 proves 降为 provides evidence，并写明 evaluated settings。

弱：`This improves robustness.`

强的方向：把 this 替换为具体步骤，并写清 robustness under 什么扰动。

弱：`Table 1 shows that our method achieves 84.3, which is higher than baseline A and B.`

强的方向：正文解释表格支持的 pattern、exception 或 mechanism，而不是复读数值。

## 自查问题

- 读者问“和谁比、在什么设置下、按什么 metric”，句子能回答吗？
- 修改是否为了短而删掉 denominator、baseline、boundary 或 evidence strength？
- 每个 this/it/they 能否替换成具体名词而不改变意思？
- 段首句连读是否形成 mini-outline？
- 每个 however/therefore/moreover 是否经得起字面逻辑检查？
- 因果动词是否有因果证据支撑，还是应该降级？
