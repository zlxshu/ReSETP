# Paper V2 防御性与 AI 味表述清理（2026-07-31）

## 状态

- 终态：`COMPLETE`
- 目标：`docs/paper_v2/paper_main.tex`
- 交付：`docs/handoff/style_cleanup_20260731/`
- 实验运行：0
- solver 修改：0

## 修改范围

以任务开始时工作树中的 TeX 为基线备份，全文扫描防御性免责句、泛化空话、稿件状态元叙述、机械过渡、长句和名词堆叠。共登记 41 处修改：防御性 8 处、AI 味 26 处、可读性 7 处。原第 255 行“然而相关研究仍存在一些不足：”和原第 1629 行“然而，本文也存在一定局限性。”均删除。

数据口径与模型语义保持：合成订单披露，81 算例与机制展示算例角色，非等算力比较，2025 任务同批同机同停机规则，E3 的 27 单元聚合，E4 的 405×28 配对分母，E5 不可行单元分母，E6 的 20/19 单元分母，E7 的 27 单元统计口径，实体车多趟保守近似，以及影子碳价与法定履约成本区分。

## 验收

`latexmk -g -xelatex -interaction=nonstopmode -halt-on-error paper_main.tex` 完成 2 遍 XeLaTeX 和 1 次 `xdvipdfmx`，生成 24 页 PDF。未定义引用 0；overfull 1 条，来自未修改的节点信息表；underfull 1 条，来自未修改的英文参考文献。抽查摘要、引言、算法、机制实验、讨论、结语和参考文献页，文字无裁切、重叠或乱码。

修改前备份 SHA-256：`fdb31f5f4001abce2b03cae53c977f57d95c21c5143259ae31082e59410d8d6a`。

修改后 TeX SHA-256：`63364081342b8ff5cf5564013cdf2cc0919f76890d5a0d1ebc59ce142c67b5cc`。

完整逐项表与边缘保留清单见 `docs/handoff/style_cleanup_20260731/report.md`。
