# Codex 提示词 08 — 路线池 + Set-Partitioning 重组 headroom 探针（Pilot19）

> 本提示词由 Claude 在通读 `cost.py / check.py / evaluation.py / winner_operators.py / action_space.py` + 文献后写定，目标是**一次干成**。Codex 冷启动、读不了论文，本文件自包含。**先证据、后单点改动、再短测**；连续 3 次猜测性修复失败必须升级为架构问题、停下写诊断，不许硬怼。

## 0. 开工前必读（不读完不许动手）
- `HANDOFF.md` 全文 + 变更日志末段（截至 Pilot18 `8e840309` 及其后的"认错更正"条）。
- `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot18/pilot18_headroom_probe.md`（拿到 Pilot18 定义的"最强非 DR 基线 winner_static_meta"的精确口径：prices / carbon_profile / carbon_quota / eval_budget / max_runtime / 代表算例 bundle id / seeds）。
- `solver/src/setp_solver/cost.py`（`evaluate`）、`search/evaluation.py`（`penalized_obj/model_cost/EvaluationContext`）、`check.py`（`check_solution` 各约束）、`solution.py`（`Route/ChargingAction/Solution/physical_vehicle_id`）、`search/winner_operators.py`（`run_winner_kernel`、`WinnerKernelConfig`）。

## 1. 背景与为什么这条路成立（别跑偏）
- 病根已定位：DR-ALNS（我们抄的 Reijnen 原版动作空间 `[3,1,10,100]`=选算子+调破坏量+调温度）和 winner kernel 共用**同一族破坏-修复邻域**，所以困在同一个局部最优盆地、互相持平（Pilot17 DR≈ALNS +0.57%）。Pilot18 给 winner kernel 16× 预算 0 增益——但那只证明"**同一条轨迹**榨干了"，winner kernel 把它一路生成的几千条好路线**全扔了**（`_run_winner_kernel_loop` 只留 best/current，不存路线池）。
- 文献成熟解法（ALNS + set-partitioning 路线池 matheuristic）：把搜索中生成的可行路线攒成池子，用一个小整数规划重新挑一组路线拼成最优组合；这是**跨整段历史的重组**、与破坏-修复是不同机制，能跳出盆地，文献报告比纯 ALNS 平均好约 12%。来源：VRP cross-docking matheuristic (sciencedirect S1568494621000867)、ALNS overview (sciencedirect topics)。
- **Claude 已核实本仓库满足直接套用的条件**：
  - 目标函数**完全可加**：`penalized_obj` 的成本部分 = `evaluate()` total_cost = 固定车费+里程+油+电+占用+转运+碳，逐路线/逐充电动作可加；碳成本对总排放线性，配额是常数偏移；**公平惩罚默认关闭**（`fairness_enabled=False` / `FAIRNESS_ENABLED=False`），无跨路线非线性耦合。
  - 跨路线约束只有三类，SP/重建可控：客户恰好覆盖一次（=SP 分割约束）、车队物理车数上限（`num_cv/num_ev`；多趟 `#Tn` 可把多路线打包到少数物理车，静态 `check_solution` 不查趟间时间重叠 → 重贴标签即满足）、公共充电站每时隙容量（多在 capacity=1 的 `f` 站，唯一要在 SP 里防的真冲突）。
  - 每条路线精确成本**直接用 cost.py**：对单条路线建 `Solution([route], charging_actions=该路线的动作)` 调 `evaluate(..., carbon_quota_kg=0.0)["total_cost"]`，零改动零语义风险。
  - 求解器用 worker 自带 `scipy.optimize.milp`（HiGHS，scipy 1.18），**不依赖 Gurobi**。

**本轮目标**：不训练、不动 DR。新增一个**路线池+SP 重组**模块与探针，回答一个预先写死判级的问题——**SP 重组能不能砍过 winner kernel 的最强单轨迹 best？** 能砍过即证明"盆地可跳出、headroom 真实存在"（Pilot18 的到头是单轨迹假象），并顺带得到一个比 GA-VNS/LNS/纯 ALNS 更强的算法当 DR 地基；砍不过即是比 Pilot18 更硬的"接近最优"证据。

## 2. 绝对边界（违反即作废）
1. **不训练、不跑 PPO。**
2. **不改** `cost.py`/`check.py`/`search/evaluation.py`/`winner_operators.py` 的任何语义；只**新增**模块、只**调用**它们。SP 是后处理，最终裁判永远是真 `check_solution` + 真 `evaluate`。
3. 所有成本/可行性必须经 worker `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`、NumPy 2.3.5。
4. 只报 x86 同机相对%，绝不与 M1 绝对数横比。
5. 每个长跑设墙钟封顶（winner 多种子按 Pilot18 口径；MILP 单次 ≤ 300s），到点记录"未解完/到达预算"，不硬跑过夜。
6. 遇不确定先查仓库文献/Zotero/参考代码（`Reference Algorithm/ALNS@wangqianlongucas`、`ALNS-7.0.0@N-Wouda`）/arXiv，再单点改、再短测。
7. commit 以 `[x86/DR]` 开头；只 force-add 小产物（报告+CSV+重建出的最优解 json）；不加日志/raw trace/大中间文件。

## 3. 精确执行规范

### 3.1 新增文件
- `solver/src/setp_solver/search/route_pool_sp.py`：纯函数模块（建池/去重/单路线成本/SP 求解/重建/校验）。
- `solver/tests/test_route_pool_sp.py`：单测（小构造算例验证：覆盖矩阵正确、SP 选出恰好覆盖一次、重建过 `check_solution`、单路线成本与 `evaluate` 一致、池去重保留最便宜）。
- 探针 runner（脚本或 `solver/rl/dr_alns_ppo/pilot19_route_pool_sp_probe.py`），产出报告到 `solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot19/`。

### 3.2 建路线池（多种子，零改 winner 代码）
- 每个规模选 **1 个代表 bundle**（与 Pilot18 同一个，记录确切 id；50/75/100/150/200c）。先做 50/75/100，再视墙钟做 150/200。
- 跑 `run_winner_kernel`（用 **Pilot18 winner_static_meta 完全相同的口径**：同 flags/eval_budget/max_runtime/prices/carbon_profile/carbon_quota），**seeds 1..S（S=12 起，按墙钟可降到 8）**，每次记录 best_solution、total_cost、feasible、actual_evals、runtime。
- **harvest**：把每个 run 的 `best_solution.routes` 全部入池，连带各路线自己的 `charging_actions`（按 `vehicle_id` 归集）。**只收 `cross_site_services` 为空的解**（winner kernel 默认如此；若发现非空，停下报告 `HALT_CROSS_SITE_PRESENT` 并说明，不擅自处理）。
- **去重**：池按 `(frozenset(路线内客户 id), vehicle_type)` 归并，保留**单路线成本最低**那条（成本 = §3.3）。被同客户集更便宜路线支配的丢弃。
- **兜底列**：为每个客户加一条"最近 depot→该客户→该 depot"的单客户路线（保证 SP 分割一定有可行解）；该兜底路线必须自身过 `check_solution` 单路线可行（容量/时间窗/EV 电量），不可行则不加（记录）。兜底成本由真 `evaluate` 给（通常很贵，SP 仅在必要时才用）。
- **池太薄兜底**：若去重后 distinct 路线数 < 3×客户数，再用公开 API `WinnerOperatorSet` + `apply_winner_action` 跑一个轻量 harvest 循环（同算子、不改 winner 文件），把每个可行候选解的路线也入池，直到够厚或到墙钟。

### 3.3 单路线成本（直接用 cost.py）
`cost_r = evaluate(Solution(routes=[r], charging_actions=该路线动作), instance, carbon_profile, prices, carbon_quota_kg=0.0)["total_cost"]`。按路线对象缓存。SP 目标 = Σ 选中 cost_r（碳配额常数偏移与转运在全解重算时统一处理，不进 SP 目标）。

### 3.4 SP 求解（scipy.optimize.milp / HiGHS）
- 变量 x_r∈{0,1}（每条池内路线）。目标 min Σ cost_r·x_r。
- 约束①覆盖：对每个客户 j，Σ_{r∋j} x_r == 1（稀疏 incidence；`LinearConstraint(A_cover, lb=1, ub=1)`）。
- 约束②公共站时隙容量（仅 `f` 站、capacity=1 的）：对每个被池内 EV 路线充电动作占用的 `(f 站, 48 制 slot)`，Σ_{占用该(站,slot)的 r} x_r ≤ capacity。depot（容量≈客户数）跳过。slot 用 `charging_slot_breakdown(..., n_slots=48, cyclic=True)` 求（与 `_check_station_capacity` 同口径）。
- `integrality=1`、`bounds=[0,1]`、HiGHS `time_limit≈120–300s`。记录 milp_status/gap/time。
- 若分割不可行：因有兜底列，分割应恒可行；若仍报不可行，回退 set-covering（≥1）+ 贪心去重，并在报告标注"用了覆盖回退"。

### 3.5 重建 + 校验（真裁判）
- 取 x_r=1 的路线集；**重贴车辆标签**满足唯一性+车队上限：按 type 分组，若该 type 选中路线数 ≤ `num_cv`/`num_ev`，逐一给 `CV1..`/`EV1..`；否则 round-robin 打包成 `CVk#Tn`/`EVk#Tn` 趟。同步把每条路线及其 `charging_actions` 的 `vehicle_id` 改成新标签；`home_depot_id=node_sequence[0]`。
- 组 `Solution(routes, charging_actions, cross_site_services=[])`，跑真 `check_solution(sol, instance, DEFAULT_PRICES)`。
- **必须零违约才算数**。若有违约：记录类型/计数；对 STATION_CAPACITY/FLEET 冲突做**一次**池内替换修复（用覆盖同客户集的次优路线替换冲突路线）；仍不行则标 `SP_RESULT_INFEASIBLE` + 阻塞约束，不注水。

### 3.6 比较口径
- `best_single` = S 次 winner_static_meta 里**可行**解的最低 total_cost（最强单轨迹基线）。
- `sp_cost` = 零违约重建解的真 `evaluate` total_cost。
- `headroom_sp% = (best_single − sp_cost)/best_single × 100`（正=SP 更好）。
- 另报 vs S 次均值、vs Pilot18 winner_static_meta 记录值（连续性）。

## 4. 预先写死判级（写进报告，禁止事后改）
- 任一规模 `headroom_sp% ≥ 10%` → **`ROOM_CONFIRMED`**：盆地可跳出、headroom 真实，Pilot18 的到头是单轨迹假象 → 绿灯进杠杆 2（DR 学"破坏/委派"+ 学"何时触发 SP 重组"），并把"ALNS+SP matheuristic"作为新强基线。
- `2% ≤ headroom_sp% < 10%` → **`MODEST_ROOM`**：重组有效但不到 10%；ALNS+SP 本身已是超过 GA-VNS/LNS 的贡献，DR 可在其上再推；user 拍板要不要继续冲 10%。
- 各规模 `headroom_sp% < 2%` → **`NO_ROOM_SP`**：连跨轨迹重组都榨不动 → 比 Pilot18 更硬的"启发式族接近强吸引子"证据；下一步＝等 Gurobi 上精确下界量到全局最优的真实 gap，再定 DR 去留。

## 5. 突发预案
- worker 漂到 py312 / NumPy≠2.3.5 / 解出现非有限成本 → `HALT_INTEGRITY`，从日志+环境查根因，不改参硬跑。
- MILP 超时未达最优：用当前最优整数解，标注 `milp_time_limited` + gap；不把超时当失败。
- 池/重建反复出 STATION_CAPACITY 冲突：回到 `_check_station_capacity` 与文献，确认是否该把更多 `f` 站时隙容量进 SP；单点改、短测。
- 200c 墙钟扛不住：先交 50/75/100/150 结论，200c 标 `SCALE_DEFERRED_RUNTIME`，不阻塞判级。

## 6. 交付物
- `pilot19_route_pool_sp_report.md/json`（每规模：best_single / sp_cost / headroom_sp% / 池大小 / milp_status/gap/time / 重建违约 / worker / numpy / runtime / 判级；引用上述文献来源）。
- `pilot19_scale_rows.csv`、`pilot19_pool_stats.csv`、重建出的最优解 json（小）。
- 新单测全过；`git diff --cached --check` 干净。
- 最终回复用人话说：每个规模 SP 重组砍了多少、落在哪个判级、Pilot18 的"到头"是不是被推翻、下一步该不该进杠杆 2。
