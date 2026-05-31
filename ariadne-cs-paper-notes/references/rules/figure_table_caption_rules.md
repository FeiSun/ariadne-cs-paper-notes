# 图表与 Caption 规则

这是 deterministic figure/caption artifacts 的维护说明。默认 specialist packet 不读取本文件；检测来源仍是 `check_figure_caption.py`。

## 使命

说明图、表和 caption issue artifact 的判断边界。语义层面的“图表是否支撑主张”主要由 Prose 或未来 vision specialist 处理；本文件不复制几何、资产、引用检测逻辑。

## 判断边界

当图表是中心证据，而读者无法恢复 setup、metric、comparison 或 takeaway 时，应升级。placeholder caption、缺 label、引用解析失败、资产不可读、caption 与图表分离等问题，如果影响主证据，可为 `Major`。

轻微 caption 表述、局部 legend 负担或非主证据图表的可读性问题，通常是 `Minor` 或 `Polish`。

## 批注方向

- 一张图/表只服务一个核心论点。
- caption 首句先告诉读者该看见什么。
- 后续 caption 补 setting、metric、comparator、direction、aggregation/statistical detail。
- 表格不要让读者做翻译题、查字典题、算术题。
- 颜色、marker、method name、symbol 要和全稿视觉字典一致。

## 示例方向

弱 caption：只有名词短语和 legend 说明。

强 caption：第一句给 takeaway，第二句说明 setting、metric、comparison 和必要统计口径。

## 自查问题

- 只看图/表和 caption，审稿人能否说出证据 claim？
- caption 是降低工作量，还是强迫读者回正文找 setup？
- 颜色、marker、方法名和符号是否与全稿一致？
- 不可读是资产质量问题，还是信息密度/设计问题？
