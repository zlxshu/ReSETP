# 09w — 修复"电池 override 进不了搜索"框架 bug（含前置可行性闸）+ 重跑 09v

日期：2026-06-27（Claude 已亲自核验代码，下方行号经实读）　执行：Codex　决策权：用户
前置：修复 09v（`09v_high_tension_alns_vs_lns_regime_probe_20260627.md`）暴露、Claude 已坐实的测量 bug。

---

## 0. 先读 + 行为铁律
- 完整读 `HANDOFF.md` + `docs/handoff/memory/`；读 `CLAUDE-FABLE-5.md`/`AGENTS.md` 诚实/克制原则。
- **禁改 `cost.py`/`check.py`/`evaluation.py` 语义。** 本任务**不需要**碰 `evaluation.py`（理由见 §2）。允许改 `winner_operators.py`/`metaheuristic_baselines.py`（非保护集），但只做**纯透传**。
- 碳价钉死 `0.05034`；电池只用来源值内存 override；系统 py313/numpy2.3.5/`PYTHONHASHSEED=0`；数字绑 commit。
- 任一闸不过 → **HALT**，不硬出结论，不悄悄改默认行为。

---

## 1. 已坐实的 bug（Claude 实读代码 + 原始 CSV，勿重复诊断）

**数据证据**：`high_tension_separation_probe_stage_a_data/raw_runs.csv` 中 `e2-vanilla-150c-01`/ALNS/seed1，在 80/100/150/280kWh 下 `best_cost` 逐位相同 `= 6015.377586977482`，EV/充电/share 全同 → 四档算的是同一个 80kWh 解。

**代码根因（行号已实读确认）**：
- runner `wallclock_battery_preflight.py:run_worker_task` 只把 override `prices` 传给 warm-start（437）和最终 evaluate/check（490/492），**没传给搜索**（450 `run_e2_alns_throughput`、470 `run_metaheuristic_baseline` 均无 prices 形参）。
- **Winner kernel**：`winner_operators.py` → `run_e2_alns_throughput`(502) → `_run_winner_variant`(581) → `_run_winner_kernel_loop`(648)。搜索成本由 `EvaluationContext` 决定；`EvaluationContext`（`evaluation.py:47`）**本就有 `prices` 字段、默认 `DEFAULT_PRICES`**。但 `_run_winner_kernel_loop` 在 **657 行**构造 context **没传 `prices=`** → 回落 80kWh。`_run_winner_variant` 的 591（build_initial_solution）/625（最终 context）/626（check_solution）也写死 DEFAULT_PRICES。
- **LNS**：`metaheuristic_baselines.py` → `_SearchSession`(97) 在 **115 行**写死 `prices=DEFAULT_PRICES`；且 LNS 算子内另有 **8 处**硬编码 `DEFAULT_PRICES`（243/384/385/680/754/756/767/805/808）。

**影响范围（如实写进报告）**：09t/09u/09v 中所有"电池档之间"的算法结论作废（搜索一律 80kWh）。但 **Goeke80（80kWh 默认）下 ALNS≈LNS 仍成立**。

---

## 2. 修复点（精确，最小侵入；不碰 evaluation.py）

`EvaluationContext.prices` 字段已存在，故**只需把 override 一路透传到构造点，不改 evaluation.py**：

- **Winner kernel**：`run_e2_alns_throughput` / `_run_winner_variant` / `_run_winner_kernel_loop` 各加可选 `prices: PriceParameters | None = None`（`None`→`DEFAULT_PRICES`）。把它传到：657 行 `EvaluationContext(..., prices=prices)`、591 行 build_initial_solution、625 行最终 context、626 行 check_solution。
- **LNS**：`_SearchSession` 加可选 `prices`（`None`→`DEFAULT_PRICES`），115 行用它；把 243/384/385/680/754/756/767/805/808 的 `DEFAULT_PRICES` 改成读 `session.context.prices` / `context.prices`（同一对象，别再引模块默认）。`run_metaheuristic_baseline` 加 `prices` 形参透传。
- runner `run_worker_task`：第 450/470 行两个搜索调用补 `prices=prices`。
- 不改 `run_alns_wouda`（已对）；不改任何算子逻辑/接受准则/预算语义——**只让价格对象透传**。

---

## 3. 前置可行性闸（闸 0）——先用零成本证据判断"值不值得做侵入式 LNS 改造"

**在动 §2 任何代码前**，先做只读 metadata 检查（不改代码、不跑搜索）：
- 对 `gradient01` 每个实例，读 `num_ev`（及 `max_trips_per_physical_vehicle` 多趟语义），算**硬上限下 EV route 的理论可达上限占比** = `num_ev × max_trips / 满足需求所需总 route 数`。
- 判定：若多数 75-200c 实例的 EV 可达上限 **< 20%**，说明 Goeke hard-cap 本身就把混合带封死，**电池再大也到不了非退化高张力档** → 直接 `HALT_CAP_BOUNDED_NO_HEADROOM`，**不做 §2 改造**，报告建议转 DR-ALNS / 改叙事，交 user 决策。
- 若多数实例 EV 可达上限 **≥ 20%**（cap 有头寸，低 EV 是 80kWh 经济性所致而非 cap），才继续 §2。

> 这道闸是回应"必须根据资料、不拍脑袋"：先用 metadata 证据判断假设在本语义下是否物理可能，再决定是否付出 LNS 9 处改造的成本与回归风险。

---

## 4. 两道正确性闸（§2 改完后，都过才准重跑；闸 B 已修正逻辑）

**闸 A — 锚逐位复现（护住正式数字）**：不传 override 时，`run_e2_alns_throughput` 在 `100-01` 上必须逐位复现 winner 锚 `4878.331796187524`（`HANDOFF.md`§1），09s warm-start 69/69 数值不变。任一位不符 = 透传重构污染了默认行为 → **HALT 回滚**。

**闸 B — override 真进搜索（用正确判据，不靠搜索输出 diff）**：
- B1 管道断言：构造 winner/LNS 的搜索 context 时传入 `B=280` override，断言 `context.prices.B_battery_kwh == 280.0`（不是 80）。直接证明 override 到达搜索上下文，**与解的构成无关**。
- B2 成本路径断言：取一个**含 EV 路线、其能量需求介于 80–280kWh 之间**的固定参考解，分别用 80kWh 和 280kWh `check_solution`/`evaluate`：80kWh 下该 EV 路线**应不可行/成本不同**，280kWh 下可行。证明价格真在 cost/check 起作用。
- **注意**：**不要**用"搜索输出 best_cost 在 80 vs 280 不同"当判据——近全 CV 解的成本本就与电池无关，cap 绑定时即使管道正确也会相同，会冤枉管道。B1+B2 才是干净判据。

---

## 5. 重跑 09v Stage A（闸 0/A/B 全过后）
按 09v 原设计（4 档 80/100/150/280kWh × gradient01 × seed1 × {alns_e2_throughput, LNS}，等墙钟，0 采集失败否则 HALT_COLLECTION_COST）+ 09v §6 预注册判决 + caveat。判决：
- **PASS_MECHANISM_SEPARATION** → 机制咬合处 ALNS 真分离 LNS → 下一步正式化 regime + 正式 T3。
- **INCONCLUSIVE/FAIL** → 电池真进搜索、EV 真活跃后 ALNS 仍打平/落后 → 算法创新落 **DR-ALNS**，停止用电池调 vanilla ALNS。
- 这次 EV share/best_cost 在档间**必须有差异**（否则 B1/B2 本该已拦）。

---

## 6. 验收 + 报告
- 闸 0 结论（每实例 EV 可达上限表）；闸 A 贴逐位锚；闸 B1/B2 贴断言结果。
- Stage A 闭合或诚实 HALT。回归测试 `test_cost/test_check/test_search/test_e2_alns_throughput`（+ 覆盖 winner_operators/metaheuristic_baselines 的测试）全过。
- 报告人话先行、标清 PROBE、开头复述目标；§1 影响范围照实写。
- **订正 HANDOFF**：用户先前追加的 09v run log 记的是无效结论，需改注："09v 因 override 未进搜索而无效（best_cost 四档逐位相同坐实），由 09w 取代；Goeke80 tie 仍成立。" 再追加 09w 本轮（闸 0/A/B 结果 + 判决）。
- 产物 commit、记 HEAD 与 artifact hash。

## 7. 不要做的事
- 不碰 cost/check/evaluation；override 默认必回落 DEFAULT_PRICES；锚不复现/管道断言不过就 HALT，别往下跑。
- 闸 0 若 `HALT_CAP_BOUNDED_NO_HEADROOM`，**不要**硬做 LNS 改造去凑结果。
- 不把任一 Stage A 行写成"ALNS 正式赢 LNS"；不试来源外电池；不动碳价。
- 不用术语堆报告；先人话后标签。
