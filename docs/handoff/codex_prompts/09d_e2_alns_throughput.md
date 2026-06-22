# 提示词⑨d — E2 ALNS 真根因：吞吐(每步太贵→迭代饿死)，做快它（阶段②续，关键）

> 先读 `HANDOFF.md` + `baselines/e2_alns/{sa_acceptance_gate.md, sa_acceptance_halt_report.md}` + `sa_raw_runs.csv`。M1 系统 Python、`codex/reporting-pipeline`。承接 09/09b/09c 三次 HALT。

## 根因（已用 09c 数据坐实，是吞吐不是质量）
- 09c 实测 evals/s：**LNS ~34；强化后 ALNS（lns_cooling）仅 4–12，autofit 仅 3.8**。
- **决定性证据**：ALNS 在**能跑够迭代的小算例**上追平/赢 LNS（threeshift-50c 平 +0.37%、75c **赢 −1.4%**，二者都跑满 ~14k-16k evals）；一到 100c+ 就因每步太贵、**迭代被饿死**（仅 3283-9382 evals）而输（+1.4~1.5%）。→ **ALNS 不是找不到好解，是每步成本太高、跑不够步数。**
- 病因 = 强化时加的**成本感知后悔修复 + 扫描构造**让每个被计数 eval 比 LNS 贵 3–9 倍（与最早 03 HALT 同类：每 eval 全量重算）。SA(lns_cooling) 已把质量差距压到多数档 ~1.5% 内，**就差吞吐这一脚**。
- 这印证 user 判断：**ALNS 成熟、是没调教对（被加料拖慢），不是不行**。修法 = 让每步变快到 LNS 级，不是再堆算子。

## 目标
把 E2 ALNS（含 TRUE_REPAIR/ADAPTIVE_Q/扫描/SA-lns_cooling 这套）**每步成本降到 ≈ LNS 水平（目标 100c 上 ≥~30 evals/s）**，使它在 69 基准 threeshift 全档**迭代不再被饿死、mean 追平/超过 LNS 且稳定**。纯工程提速，**不改搜索逻辑/参数语义**（免数值漂移）。

## Phase 1 — 让每步变快（照文献的增量/delta 评估，纯工程）
1. **增量/delta 成本评估**：destroy-repair 只对**改动的路线**重算成本/可行性，别每步整解重算（Ropke-Pisinger 本就用 delta 评估；这也是 LNS 快的原因）。复用 03 提速时给基线做的 delta/缓存机制（`candidates.py` 快评分路径）。
2. **精简成本感知修复**：cost-aware regret 若是瓶颈，用增量插入代价（只算插入点的 Δcost，不全量 evaluate）；full `check_solution` 延到接受/落盘。
3. **扫描构造别每步重做**：scan-restart 只在停滞时触发，不每代全量重建。
4. **不改算法语义**：提速=工程优化，改完必须验"提速前后同 seed 同结果或统计等价"（防把 09c 的质量改没）。

## Phase 2 — 修 200c 超时返回（独立 bug）
- 09c 暴露：200c 单期(vanilla/multidepot)**所有算法含 LNS 全 inf**——runner 硬超时 kill 时没返回 incumbent。
- 改：**硬超时/到点一律返回当前 best 可行解（至少暖启动），绝不返回 inf/空**。这样 200c 行至少有可比数字。
- 若提速后 200c 单期仍跑不够迭代，可对 200c 单期适度放宽墙钟（注明），但**对所有算法一致**。

## Phase 3 — 重测门（真实墙钟，决定性）
- 预算阶梯同 09c（threeshift 50-100c=300s/150-200c=900s），seed≥5，threeshift 全 5 档 + vanilla/multidepot 交叉。
- **门（同时满足）**：① ALNS evals/s 升到 ≈LNS 量级（不再被饿死）；② threeshift 全档 mean 追平/超过 LNS（gap≤0 或不显著为正、Wilcoxon 不再支持 LNS 更好）；③ std 稳定（不塌缩）；④ 收敛曲线平滑；⑤ 零违约；⑥ 200c 返回有限解。
- 输出 `baselines/e2_alns/throughput_gate.md` + raw + verdict + 收敛曲线。

## Phase 4 — 守锚 + 定稿
- 重跑 `winner_restoration run-current`，确认 legacy `100-01` 锚仍 £4878.331796/零违约/delta 0.0。
- 过门则把提速写进 `run_e2_alns_final()`，更新报告（含 evals/s 前后对照 + delta 评估出处）。

## ⚠️ 诚实出口（关键，user 须知的决策树）
**若提速到 LNS 级吞吐后，ALNS 在 threeshift 全档仍系统性输 LNS**（即"跑够迭代也赢不了")——那就是**真·"GLNS 是更好的 ALNS"**的诚实结论，不是工程问题。**此时停下、报告、交 user 决策**（可能选项：把 ALNS 重基于 GLNS 架构 + 在其上做 ReSETP 增量/碳感知；或重议定位），**不准再无限加料硬刚，不准退回 DR-ALNS 救场**。但**先把吞吐这一脚补上再判**——因为小算例证据(50/75c 追平/赢)强烈表明这是工程而非能力问题。

## 边界
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义；不动 legacy `run_winner_kernel`（锚必复现）。
- 提速纯工程、不动搜索逻辑/参数；改完必验等价。
- 系统 Python + `PYTHONHASHSEED=0`；内部确定；每改动绑 commit；单测过；跑不出诚实 HALT。

## 交付
`baselines/e2_alns/{throughput_gate.md, raw, verdict, 收敛曲线}` + 提速代码（delta 评估/缓存/超时返回 incumbent）+ 等价性验证 + 单测 + 锚守门 + 多次 commit（写 hash + evals/s 前后对照）。
