# 提示词③ — 轨② 基线提速 + 正式公平对比

> 先完整读仓库根 `HANDOFF.md` + `docs/handoff/memory/baseline-algorithm-catalog.md`（项目背景、8 基线设计、公平 harness 接口、纪律铁律）。本任务在 **M1 基准机、系统 Python `/opt/anaconda3/bin/python3.13` + numpy 2.3.5** 跑（数字要与 £4878/£5347 锚同环境可比）。

## 背景：上一轮卡在哪
8 个文献基线（GA / PSO / VNS / ACO / GA-VNS / LNS / GWO / IWD）已实现接入统一接口、零违约跑通（`solver/src/setp_solver/search/metaheuristic_baselines.py` + `metaheuristic_baseline_runner.py`，测试 `solver/tests/test_metaheuristic_baselines.py`）。但 **HALT 在吞吐**：eval/s 仅 3.96–11.04，达不到 16000 eval / 900s 需要的 17.78，所以没产出正式对比。
诊断：每个被 `EvalBudget` 计数的 eval 太重，疑似**每步全量重新解码 + 每步全量 `check_solution`**，超出"一次 `evaluate()`"。winner kernel 靠 delta / 精简计分能到 17.78+。

## 目标
把基线每-eval 成本降到 ≈ winner kernel 水平，让 16000 eval 在合理时间跑完；产出 ALNS / DR-ALNS vs 8 基线的**正式公平对比表**（mean/best/std + Wilcoxon + 收敛曲线 + 运行时），证明我们打得过它们。诚实：跑不出就 HALT，不注水、不混旧数据。

## Phase 0 — profile（先报告再动手）
- 对最慢的几个基线用 cProfile / 计时埋点，定位每个 eval 的时间花在哪：decode（表示→Solution）/ `evaluate()` / `check_solution` / 其它，给占比。
- 对照 winner kernel 一个 eval 做什么（为什么能 17.78+），找出基线多做的冗余。
- 输出 `baselines/profile_report.md`。

## Phase 1 — 提速（只动基线/接口层，不碰 cost/check/evaluation 语义）
让"每个被计数的 eval ≈ 一次 `evaluate()`"：
- 局部搜索类（VNS/LNS 的破坏修复、ACO 的 VND、GWO/IWD 内嵌 LNS）用**增量/delta 成本**评估移动，别每步整解重算。
- **full `check_solution` 只在"接受新解 / 每代末 / 最终落盘"做**，搜索内部用 `penalized_obj` 快路径判优劣。
- **缓存解码**：表示没变的部分别重复 decode，只对改动的路线重算。
- 复用 `candidates.py` 现成的快评分 / 可行性机制（winner kernel 用的那套），别另起炉灶。
- **不改算法语义**：提速 = 纯工程优化，不动搜索逻辑 / 参数（免数值漂移）。改完必须验"提速前后同 seed 同结果或统计等价"。

## Phase 2 — 重测吞吐 + 定对比口径
- 重测每个基线 eval/s。
- 口径（user 已拍板"先保 16000，不行放宽墙钟"）：
  - 全部基线在 100-01 上能 ≤900s 跑完 16000 eval → 用 **16000 eval / 900s**（与锚完全一致）。
  - 个别（多为种群法 GA/PSO/GWO/IWD）仍 >900s → **保持 16000 eval 不变、墙钟上限放宽到 3600s** 让它跑完，对比表如实附运行时（仍是"等评估次数"公平，且"我们又快又好"对我们有利）。
- **收敛安全阀（防低估基线、防审稿打脸）**：每个基线记录收敛曲线（best-so-far vs eval 数）。若某基线在 16000 eval 处明显还在大幅下降（没收敛）→ 额外给它一次大预算（80000 eval，复用现有 headroom 口径）再测，对比表同时报 16000 与 80000 两档，避免"赢了一个没跑够的对手"。

## Phase 3 — 正式对比 + 出表（M1 系统 Python，10 seed，零违约）
- 算例 `100-01-24h`、`L-main`（150/200 未生成则不跑、注明）。
- 每算例每算法记：mean/best/std 总成本、路线数、CV/EV 混合、违约数、运行时、评估数、收敛曲线。
- 对每个基线算 vs winner-kernel ALNS（及公平 SA、DR-ALNS 若就绪）的 gap% + scipy Wilcoxon p + 配对胜场；判级沿用 `alns_crush_v2` 的"碾压/小幅领先/持平/失败"。
- 复用 `alns_crush_v2` 的并行 / Wilcoxon / 汇总写法 + 现有 `fair_sa_reference_costs.json`。
- 输出 `baselines/comparison_table.csv` + `baselines/report.md`（结论一句话放开头：100-01/L-main 上我们对这 8 个各是什么结果）+ 收敛曲线数据。

## 验收
- 提速后 eval/s 报告 + 达标情况；语义不变验证（提速前后等价）。
- 8 基线正式对比表 + Wilcoxon + 收敛曲线齐全；零违约；评估数严格达标（16000，或注明放宽墙钟）；系统 Python 金标准环境。
- 每个数字绑 commit hash；改动分多次 commit；测试过。
- 诚实：哪个基线没跑出 / 没收敛 / 我们没赢，如实写。

## 边界
- 禁改 `cost.py`/`check.py`/`evaluation.py` 语义；提速只动基线与接口层，不动搜索逻辑/参数。
- 不动 winner kernel / DR 代码。
- 在 M1 基准机系统 Python 跑（别在 RL venv 跑，数值会漂）。
- 跑不出诚实 HALT，不注水、不顶替、不混旧数据。

## 捷径与坑
- 提速核心 = "每 eval 只算改动部分 + full check 延后 + 复用 winner 的快评分路径"——这就是 winner kernel 快的原因。
- 别为提速改算法逻辑/参数（会动数值、毁公平），改完务必验等价。
- 种群法天生每个后代要整解评估、慢，放宽墙钟比硬压更诚实。
- 收敛曲线是"赢得是否公平"的护身符，必须出。

## 交付
`profile_report.md` + 提速后的 `metaheuristic_baselines`（含 delta/缓存/延后 check）+ 正式 `comparison_table.csv` + `report.md` + 收敛曲线 + 多次 commit（报告写 hash）。
