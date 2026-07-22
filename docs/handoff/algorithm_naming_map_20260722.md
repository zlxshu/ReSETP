# 算法命名映射（工程代号 ↔ 论文学名）

- 编号：ALGO-NAMING-MAP-001
- 日期：2026-07-22
- 状态：用户 2026-07-22 拍板确认
- 单一事实源：代码里保留工程代号，论文（`docs/paper_v2/paper_main.tex`）一律用学名/缩写；
  S5 表格图生成脚本按本表把代号映射成学名，不得把工程代号写进论文或图表。

## 主算法

| 工程代号 / 缩写 | 论文学名（中文全称） |
|---|---|
| `MV-HGS-SP` | 多视角混合遗传搜索—精确路线池重组算法 |

英文全称：Multi-View Hybrid Genetic Search with exact route-pool recombination (set-partitioning)。
组成：三个成本视角各由一个 PyVRP 0.12.2 HGS 独立维护种群 → 完整非线性 ReSETP 模型裁判精英
→ SciPy/HiGHS 集合划分精确重组跨视角路线 → 单调保护（重组不严格改善则保留最好父方案）。

## 三个视角子算法（同一 HGS 引擎、三种成本代理，各自可单独作 baseline）

| 工程代号（代码 `route_proxy_mode`） | 论文缩写 | 论文学名（中文全称） | 成本代理 |
|---|---|---|---|
| `cv_only` | **HGS-F** | 燃油成本导向混合遗传搜索 | 传统燃油车里程/油耗成本引导 |
| `naive_ev` | **HGS-E** | 简化电动混合遗传搜索 | 线性电耗+恒功率充电近似引导 |
| `mechanism_ev` | **HGS-M** | 机制感知混合遗传搜索 | 完整非线性充电—分时电价—碳排放机制成本引导 |

F=Fuel、E=Electric、M=Mechanism。三者均以完整非线性 ReSETP 模型评价并经独立检查器复算，
CPU 单独报告（收敛式）。

## 已废弃/纠正的命名（不得再用）

- **`ReSETP-ALNS`**：论文旧稿 tex 行958 编造的名字，用户从未命名过；`\cite{ref:66}`
  （Ropke-Pisinger 2006 ALNS 开山论文）为误引，已删正文引用。ALNS（开源与自产加强版）
  **不进任何对比表**（MV-HGS-SP 内部为 HGS 非 ALNS）。ref:66 的 bibitem 暂留待用户定
  （删除或挪相关工作）。
- **P3 三臂旧标签 mother/ablation/full**：`mother`=HGS-M（mechanism_ev 单视角），
  `full`=MV-HGS-SP，两臂 P3 数据复用；`ablation`（去SP多视角）不进主表，降附录组件消融。

## tex 落实位置（2026-07-22 已改）

算法章步骤1（引入三视角学名）、路线池示意图节点、实验章 §4.2 正文、表6(tab:algorithm-comparison)、
全量汇总表(tab:china81-summary)。全部用 HGS-F/HGS-E/HGS-M/MV-HGS-SP。

**2026-07-22 用户令：本刊几乎不设附录，删除附录 A（原 China81 全 81 题逐题表 A1）。** 全量
81 题结果只由正文分层汇总表 `tab:china81-summary`（城市群×规模 + 配对 Wilcoxon/Holm 显著性）
承载；逐题 81 行明细不进论文，仅留仓库封存 CSV 作证据。S5 生成脚本**不再生成 A1 逐题表**，
只填 `tab:china81-summary`。私有表全部方法措辞统一为"收敛式"（非等墙钟）。原则：能进正文
（含图表）就进正文，无展示必要则不展示以保持简洁。

见 [[e2-final-campaign-p3-p4-complete]]、[[mv_hgs_sp_stage1_closeout_20260720]]。
