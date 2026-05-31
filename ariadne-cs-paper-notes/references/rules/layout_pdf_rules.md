# PDF Layout 规则

这是 layout specialist 的维护说明。默认 specialist packet 不读取本文件；检测来源仍是 `check_page_layout.py`。

## 使命

说明 deterministic PDF/page-layout audits 输出 issue 时的判断边界。版面问题的核心不是“好不好看”，而是是否打断审稿人的正常阅读路径和证据检查速度。

## 判断边界

当渲染 PDF 阻碍理解时升级：主证据图表不可读、caption 与对象距离异常、页面节奏严重断裂、标题/段落/浮动体导致读者找不到下一阅读目标，或 layout 隐藏了主论证。

孤行、轻微留白、普通分页瑕疵通常是 `Polish`，除非它们显著影响主线阅读。

## 诊断顺序

先问内容结构是否造成 layout 问题，再问 float/table/figure 尺寸和位置，最后才考虑模板安全的微调。

批注应说明：

- 审稿人无法快速看见或比较什么；
- 哪一页/哪个局部对象受影响；
- 可能修法是内容重组、float placement、caption proximity，还是最终 PDF 清理。

## 自查问题

- 正常 PDF zoom 下，审稿人会不会丢失 argument？
- 这是内容/结构问题伪装成 LaTeX spacing 吗？
- 页面节奏是否让下一阅读目标清楚？
- 图表是否过大、过小、过密，或视觉风格像外来拼贴？
