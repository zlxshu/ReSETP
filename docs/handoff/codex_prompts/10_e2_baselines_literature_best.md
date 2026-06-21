# 提示词⑩ — E2：8 个文献基线重做到文献最优形态（阶段③）

> 先读 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md`（含 8 基线“算法设计提取”转录）。M1 系统 Python、`codex/reporting-pipeline` 分支。依赖阶段①的 69 算例。

## 为什么要做（实证根因）
03 HALT 体检发现：现有 8 基线里 **GA/PSO/ACO/GWO/IWD 五个在 10 seed 上返回完全相同的值、std=0**——它们**原地返回暖启动解、根本没在有效搜索**。读码确认根因不是没播种（`_ga_initial_population:897` 已含 `session.current` 暖启动），而是**通用“随机键解码”表示太弱**（`_order_to_solution → random_key_to_solution` 把暖启动好结构打散→候选恒比暖启动差→永不接受）。**赢这种基线=注水，审稿一看 std=0 即识破。**

**目标**：把 8 个基线**按各自源论文重做到文献最优形态**（user 铁律：所有算法做到最优、设计全部来自论文/网上、禁止自创），使每个都**真正在搜索**（跨 seed 有方差、能改善暖启动），这样“ALNS 赢它们”才诚实有力。

## 各基线的文献设计（照抄/适配，逐个标出处）
统一要求：① 用各算法**文献忠实的表示与算子**（不是通用随机键）；② 种群/初始解用**好构造播种**（暖启动 + NN/贪心/扫描 + 各文献的构造法）；③ 内嵌局部搜索精修；④ 解码/可行性**复用 `candidates.py` 现成**（构造/插入/EV 充电修复/时窗/多车场/cross-site），别重造可行性；⑤ 目标计算全过同一 `score_candidate/EvalBudget`。

1. **GA ← Narayanan 2022 [BCBMVPMB] §2.3**：染色体=路线集；**NN 初始 + 插入改进**；二元锦标赛选择；**common-nodes / common-arcs 交叉**；10% 变异（随机/最近 node·route 删除）；精英 top10% + 随机。（替换现有随机键 GA。）
2. **PSO ← 离散 VRPTW-PSO（李宁2004 机制 + post-2020 离散实现）**：排列编码 + 交换序列速度，但**每代加局部搜索**避免塌缩；pbest/gbest 用真成本。
3. **VNS ← Woller 2025 [VSUPJ3V7] Algorithm 1**：construction → perturbation/shaking → **RVND 局部搜索** → 无改进重启，ITERS_MAX=r×n；鲁棒 repair。
4. **ACO ← 何美玲2023 IACO [DJWRJRWX]**：状态转移概率融合节约值 s_ij + 时间窗偏差 dev_ij + 宽度 width_j（式12-13）；自适应挥发 ρ(t)=0.95ρ(t-1)→ρ_min（式16），Δτ=(z_max−z)/z·Q；**VND 邻域=插入+交换**。参数 m=20/iter=100/ρ0=0.8/ρ_min=0.01/α=1/β=2。
5. **GA-VNS ← #1 GA + #3 VNS memetic**：GA 框架 + 对精英做 VNS 精修。
6. **LNS ← 高娇娇2024 GLNS [TAQUPN3F]**：扫描构造 + LNS（random/相似 removal、最远/后悔 repair）+ SA 接受；max_iter=1000/ε=0.3/Φ=0.05/μ=0.95。（现有 LNS 已较强、是体检里唯一真搜索的之一，按文献校准即可。）
7. **GWO ← 马祥丽2025 HGWO [J9SJK8C4]**：GWO + GA 交叉（alpha/beta/delta 引导）+ LNS 破坏修复；自然数编码；罚函数。NIND=50/MAXGEN=350~1000。
8. **IWD ← 张婧文2025 IIWD [NC2MAHE4]**：智能水滴 + LNS + SA；单串编码（仓库/车/客户）。

> Codex 读不了中文期刊原文——以上设计已转录在 `baseline-algorithm-catalog.md`「算法设计提取」段；arXiv 的 Narayanan/Woller 可自取。拿不准的细节**停下报告**，不要猜测自创。

## Phase 0 — audit（逐基线）
对 8 个基线各写：现状实现是什么表示/算子、为什么 std=0 或为什么偏弱、对照源论文缺了什么、怎么改到文献忠实。输出 `baselines/e2_baselines/audit.md`。

## Phase 1 — 重实现（逐基线、逐个 commit）
按上表逐个重做到文献忠实形态，复用 `candidates.py` 可行性机制；每个独立 commit + 单测。**接口不变**：`run_metaheuristic_baseline(algorithm, bundle, seed, eval_budget, max_runtime, initial_solution)`，目标过 `score_candidate/EvalBudget`。

## Phase 2 — “真在搜索”硬门禁（关键，防再出 std=0 稻草人）
对每个基线，在 2-3 个代表算例 × 5 seed 上快验：① **跨 seed std>0**（不是恒定值）；② **best 明显改善暖启动**（不是原地返回）；③ 零违约；④ **用其文献/网络推荐的标准参数配置**（种群规模/迭代/降温/信息素等取源论文或公认调参值，写进报告），且 **收敛曲线显示明显收敛**（best-so-far 随时间平滑下降到平台，非过早停滞或锯齿乱跳）——这是 user 明确要求"其他算法也优化到正常发挥水平、图中明显收敛"。**任何基线仍 std=0 / 不改善暖启动 / 不收敛 → 标 HALT_BASELINE_DEGENERATE、报告、不计入**。输出 `baselines/e2_baselines/search_sanity.md`（含每基线收敛曲线 + 参数出处）。

## 验收
- 8 基线全部文献忠实、每个标出处、每个过“真在搜索”门禁（std>0 + 改善暖启动 + 零违约）；TS 仅当仓库有现成才加，否则注明跳过。
- 接口/裁判不变；复用 candidates 可行性；系统 Python；每基线绑 commit；单测过。
- 诚实：哪个基线没做到文献强度 / 仍退化，如实写，绝不用 std=0 的弱版充数。

## 边界
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义；不动 winner ALNS（那是阶段②）。
- 禁止自创算法：拿不准的设计停下报告，不臆造。
- 系统 Python 金标准；跑不出诚实 HALT。

## 交付
`baselines/e2_baselines/{audit.md, search_sanity.md}` + 8 基线重实现 + 各单测 + 多次 commit（写 hash + 各基线文献出处）。
