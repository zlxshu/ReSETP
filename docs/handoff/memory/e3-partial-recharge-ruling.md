---
name: e3-partial-recharge-ruling
description: 2026-07-13 用户终局拍板：22kW 不动、每趟补满降为对照、批准趟间按需补电最小公式组（模仿 Zhen 2020 + Keskin–Çatay 2016）
metadata: 
  node_type: memory
  type: project
  originSessionId: cb905431-5b27-43bc-8a59-b2c8620f2d96
---

2026-07-13 用户对 E3 充电规则终局拍板（对 Codex 原话"我同意你的想法"）：

1. **22 kW 车场交流保持主参数**，不调参救结果。07-12"拍板一=升级功率"意向正式作废关闭（其 40/50/60 阶梯早已因无出处自查作废）。若 22kW 正式门排不开，快充车场只能作有来源、单独声明的敏感性场景。
2. **"每趟回场补满"降为审计对照尺子**（本源=07-12 审计的保守临时规定，非论文原话），只留 14+21 见证与披露句，不进正式矩阵重复臂。
3. **批准最小公式组**：同一实体车两趟之间在真实空档内按需补电、时间/地点/电量连续。用户铁律：新公式新符号高精度模仿已发表论文（不自造）、符号适配进现有体系、接入后用 Python 数学工具八项独立验证、不否定行业精简表达惯例、够用即可。
4. 文献来源已由 Claude 从 Zotero 原文核实：Zhen 2020（TRE 101866，Zotero key BLADDV8J）趟启用序约束(5)+趟间时间衔接约束(11)；Keskin–Çatay 2016（TRC，Zotero key DLWIGJBK）部分充电 y≤Y≤Q、充电时长 g(Y−y) 进时间传播、"满电出发不失一般性"命题 1。D1 批文原话是"返场补电"（非"补满"），按需补电=落实 D1 为文献口径，不推翻已批决定。
5. 适配要点：现有 z_k^τ 推广为车辆–趟启用变量（Zhen 的 α 与本文 α_k^e 冲突，不得搬字母）；充电量沿用 y_{ikt} 分时段变量→碳/成本自动同区间；工作时长上限按实体车全天算，不能因加趟索引变成每趟单独放宽。
6. 边界：不改 prices.py/cost.py/evaluation.py，check.py 只版本化新增，不重判 E1/E2 封存件；小门链重走后才谈 70 次；7/19 结构门红线有效。
7. 用户授权自主推进、平实汇报（无术语无代称）、保留重大决策权；Codex 读不了论文，逐字公式由 Claude 在对话中交付。

关联：[[finding-e3-m0-anchoring]]、[[finding-cross-site-fee-gap]]、[[feedback-check-closed-paths-first]]、[[feedback-prompt-format-plain]]
