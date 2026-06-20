# 提示词② — 8 文献基线复刻 + 公平对比（已实现，HALT_BASELINE_THROUGHPUT；被 03 接续）

> 先完整读仓库根 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md`（含 8 基线完整设计转录 + 公平 harness 接口）。本任务在 M1 基准机、系统 Python 跑。8 基线已实现接入但卡在吞吐（eval/s 3.96–11.04 < 17.78），提速与正式对比见 `03_baseline_speedup.md`。

```
任务：复刻 8 个文献主流元启发算法做基线，在现有公平对比框架内（同 evaluate/check、同 16000 预算、10 种子、Wilcoxon、零违约）与 winner-kernel ALNS（及将来 DR-ALNS）在 100-01 与 L-main 上对打，证明我们打得过它们。

铁律：
- 不改 cost.py / check.py / evaluation.py 语义。所有算法用同一 evaluate() + check_solution 评分判可行。
- 公平：同 16000 eval + 同 900s + 同 10 seed + 同算例 + 暖启动 make_shared_initial_solution；每个基线目标计算走同一 evaluate()/penalized_obj、过 EvalBudget 计数、封顶 16000。
- 零违约才计入；系统 Python 金标准环境；数字绑 commit hash；每基线独立 commit；跑不出诚实 HALT。
- 照下面文献设计复刻/适配，禁止自创。

要读的论文 / 设计来源（详细转录见 baseline-algorithm-catalog.md「算法设计提取」段）：
1. GA  ← Narayanan 2022 arXiv:2204.05545 §2.3
2. PSO ← 带 TW 的离散 PSO（标准设计）
3. VNS ← Woller 2025 arXiv:2511.09570（CEC-12 冠军）
4. ACO ← 何美玲 2023 CIMS DOI 10.13196/j.cims.2023.03.029（改进蚁群+VND）
5. GA-VNS ← #1 GA + #3 VNS 组合（memetic）
6. LNS ← 高娇娇 2024 IEM DOI 10.19495/j.cnki.1007-5429.2024.03.004（扫描+LNS+SA）
7. GWO ← 马祥丽 2025（混合灰狼+GA交叉+LNS）
8. IWD ← 张婧文 2025 DOI 10.13714/j.cnki.1002-3100.2025.17.001（智能水滴+LNS+SA）
TS：仅当仓库/Reference Algorithm 有现成可适配才做，否则跳过注明。

Phase 0 audit：核对 HANDOFF§4 路径/接口；查现成可适配实现；逐基线归类（仓库已有/Reference有/照论文新写）；确认 150/200 算例是否存在。报告 baselines/audit.md。
Phase 1：定义统一 BaselineSolver 接口（建议 metaheuristic_baselines.py，对照 alns_crush_v2）：输入 (bundle,seed,eval_budget=16000,max_runtime=900,initial_solution)→返回最优 Solution；目标走 evaluate()/penalized_obj 过 EvalBudget 计数。
Phase 2：复刻 8 基线（照转录设计）。所有基线解码成 ReSETP 可行解必须复用 candidates.py 现成构造/修复/插入/充电机制（别重造 EV充电/时窗/多车场/cross-site 可行性）。
Phase 3：跑对比（100-01-24h、L-main，10 seed）→ mean/best/std/路线数/车型/违约/时间/评估数；vs winner-kernel ALNS & 公平 SA 的 gap% + Wilcoxon + 判级；输出 baselines/comparison_table.csv + report.md。

交付：audit + metaheuristic_baselines + 对比 runner + 8 基线实现 + 各单测 + comparison_table.csv + report.md + 多次 commit。
```

## 实际产物（已实现，未出正式对比）
- 代码 `solver/src/setp_solver/search/metaheuristic_baselines.py` + `metaheuristic_baseline_runner.py`；测试 `solver/tests/test_metaheuristic_baselines.py`（3 OK）；产物 `baselines/{audit.md,report.md,comparison_table.csv}`；commit d088664。
- HALT_BASELINE_THROUGHPUT：eval/s 3.96–11.04 < 16000/900s 需的 17.78。保护文件无 diff。→ 由 `03_baseline_speedup.md` 接续提速 + 正式对比。
