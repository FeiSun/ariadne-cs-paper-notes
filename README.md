# Ariadne CS Paper Notes

Ariadne CS Paper Notes 是一个面向 CS/AI 论文草稿的 Codex / Claude skill。目标是模拟读者从第一页开始读论文时的卡顿、追问、反思、重构和最终判断，对论文做全面的修改批注。

它默认输出中文批注报告，必要时保留 claim、gap、baseline、ablation、caption、skimmability 等英文术语。

## 目标与定位

- 从真实读者的理解路径出发，而不是只检查语法。
- 每读一句都问：读者会不会卡住，会不会问 why，这个特殊概念有没有清晰的定义、解释，这段是否应该存在。
- 把问题写成 `读者卡点 -> 写作原则 -> 下一稿任务`，让作者知道为什么要改、下一稿该做什么。
- 保留论文当前证据强度，不替作者发明更强 claim、实验结果、citation 或结论。

你可以把它当成一个“论文写作诊断器”：它不替你走完整个迷宫，但会给你一根线，让你看见论文的 argument、结构、证据和页面阅读体验哪里断了。


## 输入与输出

推荐输入同时包含：

- LaTeX 源文件或 LaTeX 项目目录：用于精确定位 section、paragraph、figure/table、citation、TODO、宏和源文件结构。
- 编译后的 PDF：用于检查读者真正看到的页面，包括第一页印象、figure/table 位置、caption 邻近性、孤行孤词、页面节奏和视觉层级。

只提供 PDF 也可以做正文、结构、图表和 layout 批注；只提供 LaTeX 也可以做 source-level review，但页面布局判断会受限。

典型输出包括：

- 中文 advisor-style 批注
- executive diagnosis 和 prioritized issue index
- central claim、story logic、gap、insight、claim-evidence 诊断
- 逐章、逐段、逐句的 Deep Reading Notes
- 段落级保留、合并、拆分、移动、删除、重写判断
- grammar、diction、precision、ambiguity、concision、sentence flow 检查
- figure/table/caption 和正文数字一致性检查
- PDF layout / first-page / page rhythm 检查
- 自包含 HTML 报告和 companion JSON artifacts
- coverage receipt：说明实际读了什么、哪些部分缺上下文或无法验证

## 批注流程

Ariadne 内部按读者旅程工作，而不是直接套 checklist：

1. **确认范围与证据**  
   判断输入是 PDF、LaTeX、局部段落还是完整项目；能编译就结合 source + PDF，不能编译就说明限制。

2. **冷启动 skim**  
   像第一次打开论文的读者一样先看标题、abstract、introduction 开头、figure/table 和 section skeleton，重建论文承诺的 What / Why / Gap / Idea / Evidence / Boundary。

3. **线性深读**  
   从第一页往后读。每个段落都判断它的 job 是否明确，是否应该保留、合并、拆分、移动、删除或重写；每句话都检查 reader friction、missing why、knowledge curse、概念桥、claim 强度、语法和流动性。

4. **章节反思**  
   每读完一节，检查这一节是否完成了它在论文 argument 中的任务：是否铺好了下一节，是否留下 loose ends，是否让读者的理解状态发生了正确变化。

5. **全局论证检查**  
   回到 paper-level，看 central claim、story logic、gap framing、insight vs mechanism、claim-evidence chain 是否成立。

6. **submission readiness 检查**  
   检查数值、表格、caption、PDF layout、匿名性、引用、符号一致性、可复现性、venue 风险等。

7. **输出校准与审计**  
   合并重复 finding，校准 severity，检查 HTML/JSON artifact 是否一致，最后给出可执行的 revision plan 和 coverage receipt。

## HTML 报告结构

完整 HTML 报告默认保存到被 review 的 PDF 或 `.tex` 入口文件同目录，命名类似：

```text
ariadne_notes_<paper-stem>_<YYYYMMDD>.html
ariadne_notes_<paper-stem>_<YYYYMMDD>/
```

目录中的 JSON artifacts 是报告的数据底稿，通常包括 `findings.json`、`claims.json`、`numeric_audit.json`、`coverage.json`、`render_manifest.json` 和 `pass_observations.json`。

完整报告通常包含：

- **Executive Diagnosis and Salvageable Core / 总评诊断与可救骨架**
  一眼说明论文最核心的问题、最可救的主线、下一稿应该优先救什么。

- **Issue Index / Finding Ledger / 问题索引**  
  按 Blocker / Major / Minor 等 severity 汇总主要问题，给出证据、位置、修复方向和降级条件。

- **Claim-Evidence Audit / claim-证据审计**  
  检查论文的主要 claim、证据、实验、图表、限制和 rebuttal 风险是否对齐。

- **Deep Reading Notes / 逐章精读批注**  
  按论文顺序组织 section、paragraph、sentence notes。这里是最像导师边读边批注的部分。

- **Submission Readiness / 数字/公式/图表/版式/提交就绪**
  检查数值一致性、figure/table/caption、layout、匿名性、引用、符号、artifact 等。

- **Local Patterns / 共性问题汇总**  
  汇总反复出现的写作习惯问题，比如 paragraph job 不清、claim 过强、transition 缺失。

- **Revision Plan / 修改路线**
  把问题转成下一稿可以执行的任务，而不是停在评价。

- **Coverage Receipt and Artifacts / 覆盖回执与 artifacts**  
  明确本轮读了哪些页面、章节、段落、表格和 artifacts，哪些判断基于 source，哪些基于 PDF，哪些不可验证。

## 安装

### Codex skill installer

如果你的 Codex 安装里有 skill installer，可以直接从 GitHub 安装：

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo FeiSun/ariadne-cs-paper-notes \
  --path ariadne-cs-paper-notes
```

如果这个脚本不存在，用下面的手动安装方式。安装后重启 Codex，让新 skill 被加载。

### 手动安装

先 clone 仓库：

```bash
git clone git@github.com:FeiSun/ariadne-cs-paper-notes.git
cd ariadne-cs-paper-notes
```

这个仓库有一层看起来重复的目录名，这是刻意的：外层 `ariadne-cs-paper-notes/` 是 Git repo，内层 `ariadne-cs-paper-notes/` 是真正要复制到 Codex / Claude 的 skill 包。

安装到 Codex：

```bash
mkdir -p ~/.codex/skills
rsync -a \
  --exclude tests \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  --exclude .claude \
  --exclude .gitignore \
  ariadne-cs-paper-notes/ \
  ~/.codex/skills/ariadne-cs-paper-notes/
```

安装到 Claude Code：

```bash
mkdir -p ~/.claude/skills
rsync -a \
  --exclude agents \
  --exclude tests \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  --exclude .claude \
  --exclude .gitignore \
  ariadne-cs-paper-notes/ \
  ~/.claude/skills/ariadne-cs-paper-notes/
```

`agents/openai.yaml` 只是 Codex UI metadata，Claude Code 不需要。

## 依赖

运行需要：

- Codex、Claude Code，或其他支持 local skills 的 agent runtime
- Python 3.9+，推荐 3.10+

可选但推荐：

- `pandoc`：更好地从 LaTeX 提取文本
- Poppler 的 `pdftotext` 和 `pdfinfo`：提取 PDF 文本和页数
- `pdfplumber` 或 `pypdf`：PDF 处理 fallback
- `latexmk` 或 `pdflatex`：从 LaTeX 编译 PDF
- `bibtex` 或 `biber`：处理 bibliography

缺少可选工具时应当 graceful degrade：没有 `pandoc` 会用 regex fallback；没有 Poppler / `pdfplumber` 时 PDF 文本提取能力受限；没有 LaTeX 编译工具时仍可 review source 或已有 PDF，但 layout/build 评论会少。

## 使用示例

### 1. 全文 source + PDF 深度 HTML 批注

```text
使用 Ariadne CS Paper Notes 审阅这个 LaTeX 项目和编译后的 PDF，输出中文 HTML 批注报告，保存到论文 PDF 或 tex 入口文件同目录。

请模拟资深导师从第一页开始读论文时的卡顿、反思、重构和最终判断，对这篇论文做导师级、全方位、不要遗漏的修改批注。请同时看 source 和 PDF：

1. 从读者理解路径出发，检查 central claim、story logic、gap、insight、claim-evidence 是否成立。
2. 逐段逐句批注全文，不要只给代表性问题；每个段落都要检查。
3. 特别检查 cognitive load / 知识的诅咒、missing why、intuition gap、insight vs mechanism、paragraph surgery。
4. 对每个段落判断是否应该保留、合并、拆分、移动、删除或重写。
5. 检查每句话的 grammar、diction、precision、ambiguity、concision、sentence flow、topic sentence、paragraph transition。
6. 检查 figures/tables/captions、表格数字一致性、正文数字与表格是否一致。
7. 检查 PDF layout，包括第一页印象、图表位置、caption、孤行孤词、页面节奏、视觉系统一致性。
8. 输出中文 HTML 批注报告，保存到论文同目录。
9. 不要抽样，不要只列 top issues；请给 coverage receipt，说明实际检查了哪些部分。
```

### 2. 只看 PDF 的完整读者体验检查

```text
使用 Ariadne CS Paper Notes 审阅这个 paper.pdf。请把 PDF 当成读者真正看到的版本，重点检查第一页印象、abstract/introduction 的读者路径、figure/table/caption、页面节奏、claim-evidence 对齐和 layout 问题。输出中文 HTML 报告；如果缺少 LaTeX source，请在 coverage receipt 里说明哪些判断无法做。
```

### 3. 只看 Introduction

```text
使用 Ariadne CS Paper Notes 只审阅 Introduction。不要重写成最终版本；请逐段逐句诊断读者在哪里卡住，gap 是否 recoverable，段落 job 是否明确，topic sentence 和 transition 是否支撑 story。最后给一个下一稿 introduction restructure plan。
```

### 4. 专门检查实验、表格和数字

```text
使用 Ariadne CS Paper Notes 检查 Experiments、Table 1-3 和 Figure 2-4。请重点看 claim-evidence 是否对齐，baseline/metric/setting 是否缺失，caption 是否告诉读者应该看什么，正文数字和表格数字是否一致，是否存在平均值或百分比复算风险。输出中文 finding ledger 和 revision tasks。
```

### 5. 修改后复查

```text
使用 Ariadne CS Paper Notes 复查这版修改稿。请对照上一轮 finding，判断哪些已经解决、哪些只是局部缓解、哪些引入了新问题。重点看 central claim、gap framing、paragraph surgery 和 PDF layout 是否比上一版更清楚。
```

## 脚本用法

这个 skill 主要通过 Codex / Claude 调用；脚本也可以单独跑。

从 PDF 或 LaTeX 提取 review signals：

```bash
python ariadne-cs-paper-notes/scripts/extract_paper_text.py path/to/paper.pdf -o -
python ariadne-cs-paper-notes/scripts/extract_paper_text.py path/to/latex-project --max-items 200
```

编译 LaTeX 项目：

```bash
python ariadne-cs-paper-notes/scripts/build_paper_pdf.py path/to/latex-project
```

审计生成的 HTML 报告：

```bash
python ariadne-cs-paper-notes/scripts/audit_html_report.py path/to/ariadne_notes_paper_20260517.html
```

审计 HTML + JSON artifact bundle：

```bash
python ariadne-cs-paper-notes/scripts/audit_review_artifacts.py \
  --bundle path/to/ariadne_notes_paper_20260517/ \
  --html path/to/ariadne_notes_paper_20260517.html
```

## Quick Check

安装后，可以先让 Codex / Claude 对一个短 excerpt 触发 `Ariadne CS Paper Notes`。如果是从 clone 的仓库做脚本级检查：

```bash
python ariadne-cs-paper-notes/scripts/extract_paper_text.py \
  ariadne-cs-paper-notes/tests/fixtures/seeded_defects/wrong_average.tex -o -
python -m pytest ariadne-cs-paper-notes/tests
```

## 安全与隐私

目前这个项目主要在作者自己的 macOS 15 环境和论文 PDF / LaTeX 草稿上测试。它按“可信输入”设计：用于编译和审阅你自己的 LaTeX/PDF，不要直接拿陌生人给你的 LaTeX 项目当可信代码运行。

这个工具会提取和生成可能包含隐私信息的 review artifacts，包括 manuscript text、作者名、affiliation、email、ORCID、GitHub link、acknowledgment、绝对路径、匿名性信号和审稿判断。不要把生成的 `ariadne_notes_*.html`、`ariadne_notes_*/` artifact bundle、`paper_review_extract_*.md`、编译 PDF 或论文源文件提交到公开仓库，除非这些内容本来就准备公开。

默认 extraction 文件会写成仅文件拥有者可读写的权限，即 Unix `0600` mode；不用后仍建议删除。

## 代码结构

```text
ariadne-cs-paper-notes/
├── README.md
├── LICENSE
├── LICENSE-DOCS
├── .gitignore
└── ariadne-cs-paper-notes/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    ├── references/
    │   ├── workflow.md
    │   ├── review_lenses.md
    │   ├── report_contract.md
    │   ├── html_contract.md
    │   └── numeric_contract.md
    ├── scripts/
    │   ├── audit_html_report.py
    │   ├── audit_review_artifacts.py
    │   ├── build_paper_pdf.py
    │   ├── calibrate_review_runs.py
    │   └── extract_paper_text.py
    └── tests/
        ├── fixtures/
        └── test_*.py
```

主要文件：

- `SKILL.md`：短入口，定义什么时候触发、如何调度 workflow、按需加载哪些 reference。
- `references/workflow.md`：导师式 reader-journey workflow、artifact extraction、coverage 标准和 QA gates。
- `references/review_lenses.md`：source principles、paper-type calibration、结构/论证/句段/图表/版式/提交审阅镜头。
- `references/report_contract.md`：Revision Workbench 顺序、finding/claim/coverage schema 和 JSON artifact contract。
- `references/html_contract.md`：HTML 报告结构、filters、PDF linkage、输出路径和审计要求。
- `references/numeric_contract.md`：严格数值/表格信号渲染、reported/computed/delta 规则和 numeric audit contract。
- `scripts/extract_paper_text.py`：从 PDF / LaTeX 提取 review signals、表格和数值信号。
- `scripts/build_paper_pdf.py`：尝试编译 LaTeX 项目，供 source + PDF 联合审阅。
- `scripts/audit_html_report.py`：检查 HTML 报告结构、链接、coverage 和严重程度呈现。
- `scripts/audit_review_artifacts.py`：检查 HTML 与 JSON artifacts 是否一致。
- `scripts/calibrate_review_runs.py`：比较两次 review 的 finding drift，用于校准。

## 开发

从仓库根目录运行测试：

```bash
python -m pytest ariadne-cs-paper-notes/tests
```

当前测试覆盖主要保护 extraction、LaTeX/PDF helper、HTML report contract、artifact audit 和 seeded defect fixtures。

## License

辅助脚本和测试使用 Apache License 2.0，见 `LICENSE`。

skill 指令、prompt、reference checklist、HTML report guidance、README 和其他非代码说明材料使用 CC BY-SA 4.0，见 `LICENSE-DOCS`。
