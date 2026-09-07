# 公共充电站「顺路小补」：现状诊断、上界探针与算法设计

日期：2026-09-07　作者：Claude（设计与诊断，未改任何求解器代码、未跑求解器、未改论文）

本文回答三件事：(1) 现在的充电修复层到底给每趟造了哪几种充电安排；(2) 允许「车场补大部分
＋沿途公共站小补」最多能给已落盘的最优解带来多大改善；(3) 要不要改、怎么改、改完要不要重跑。

---

## 0. 一句话结论

算法确实比模型窄——模型允许一趟里在任意多个公共站部分充电，算法每趟只造两种极端安排
（全在车场／车场只补到够开到某一个站＋该站补足全程）。**但把这个口子打开不会改变任何一个
论文数字**：离线上界探针显示，两份日历、两个碳价、43 个已落盘解、411 个电动车趟里，
**没有一趟**能在满足「同一台车下一趟还能按原时刻出发」这个约束下从顺路小补里赚到钱，
**上界在每一格都是 0 元/日**。唯一在放松该约束时出现的正收益（午间设谷 × 碳价 1.0，
14 趟、1.04 元/解、约占总成本 2600 元的 0.04%）全部要靠车在站里空等 2.75 小时，
把同一台车的下一趟推迟约 3 小时——探针已逐行核出这 14 行**全部顶到下一趟**。
零会话的真正原因不是算法窄，是公共站服务费 0.4 元/kWh 恒定加价，加上车场那笔充电本来
就已经占住了当天最干净的时段。

因此推荐**方案 A（修复层扩展）**，理由是模型—算法一致性，不是为了改数字；并且
**任何一格论文批次都不需要重跑**。

---

## 1. 现状：修复层到底造了什么（带文件:行号）

主文件：`solver/src/setp_solver/algorithms/resetp_alns/support/charging.py`（2439 行）。

### 1.1 一趟的充电安排候选是怎么枚举的

`repair_route_charging_candidates`（:799）按 `public_station_candidate_mode` 分两支：

* `fallback`（模块默认，:66 `DEFAULT_PUBLIC_STATION_CANDIDATE_MODE = "fallback"`）：
  只造一个候选 `depot_fallback`，:892 处直接返回。这一支里**公共站只在电量不够时才出现**——
  `_repair_route_charging_candidate`（:1045）沿路线前推，只有
  `should_insert = failure_offset is not None`（:1129，`_first_direct_infeasible_offset` 报出
  「按当前电量直开会在第几个点断电」）成立时才调 `_best_station_insert`。也就是说，
  在 fallback 支里公共站是**可行性救火队**，永远不是经济选项。
* `parallel`（正式实验实际使用值，见 §1.5）：在上面的车场候选之外，再对每个公共站造一个
  「强制经过该站」的候选。关键在 :922 和 :987：

  ```
  launch_target = max(initial_battery, _ev_energy(instance, start_node, station.node_id, load_kg, prices))
  ```

  车场那笔补电被**钉死**在「刚好够开到那个站」。到站之后，:1131 的
  `coverage_targets = future_targets if depot_precharge_target_kwh is not None else ...`
  把该站的补电目标设成**整条剩余路线的全部能量**。所以 parallel 支的候选不是
  「车场补大部分＋站里小补一点」，而是**「车场补到刚够摸到站＋该站包办剩下全程」**。

* 一趟只可能有一个公共站。:909–:920 的注释把这件事写死了：强制路径出发即只带够到第一个站的
  电，到站后补足全部剩余需求，因此第二次插站在数学上不可能发生；:1212
  `if station_insertions < len(forced_station_path): raise` 是配套的失败关闭。

* 车场补电量的候选：`charge_amount_strategy`（:57–:63 的 `just_enough / max_coverage /
  soc_85 / soc_95 / full` 加充电曲线拐点档）。上层
  `solver/src/setp_solver/algorithms/problem_hgs/charging.py:1172` 会在多个 `amount_strategy`
  上循环。但注意：一旦走 parallel 支，:922 的 `launch_target` 直接覆盖了这个档位选择
  （`_depot_precharge_action`:1433 里 `target_charge_level_kwh is not None` 分支不再看
  `charge_amount_strategy`）。**「车场补多少」和「站里补多少」这两个连续量，从来没有被
  当成两个可以独立取值的决策变量枚举过。**

* 一趟最多一笔车场充电：`_reanchor_depot_actions`:1534，:1560 处
  `expected one depot charging action ... found {n}` 直接抛错。这一点**与论文一致**——
  `docs/paper_v2/paper_main.tex:424` 明写首趟前和趟间的车场充电过程集合「均为空集或只含一个
  充电过程」。窄的只有公共站那一侧。

### 1.2 候选之间怎么比

`repair_route_charging`（:734）拿到候选列表，用
`route_model_cost_delta(candidate_route, candidate_actions, context)`（来自
`operators/repair_scoring.py`）逐个打分，:795 `min(scored_candidates)` 取优。打分口径是论文
目标函数的路线级增量，含电费、碳成本、里程成本。

### 1.3 站会话怎么计价

* 电价：`cost.py:1326 charging_action_electricity_cost`。有时变价日历时（本项目一直有），
  车场节点读 `depot_energy_cny_per_kwh`，公共站节点读 `public_total_cny_per_kwh`
  （:1382–:1409），并且是**按充电动作实际跨过的每个半小时槽分段结算**
  （`charging_action_slot_breakdown`，cyclic=True）。所以「到站时段」的说法要更精确：
  是充电起止时刻覆盖的所有槽，不是单一到站时刻。
* 服务费：不是单独一项，已经并进 `public_total = public_energy + public_service_fee`
  （日历列，见 §2.1）。
* 碳强度：`cost.py:787 charging_action_emissions_kg`，车场和公共站**共用同一列**
  `actual_gco2_per_kwh`，只随时段变，不随地点变。
* 绕行的电耗：计入。`_best_station_insert`:2107 里 `energy_to_station` / `energy_to_target`
  用 `ev_instance_arc_energy_kwh`（含半载推进），站里要补的量因此自动包含绕行电耗。
* 绕行的里程成本：计入总目标（`cost.py:192 cost_km`，电动车 0.9145 元/km），但**不在
  `_best_station_insert` 的内部排序键里**——:2301 的排序键是 `(gamma, detour, station_id)`，
  即先比碳强度再比绕行米数；里程钱只在外层 `route_model_cost_delta` 比候选时才进账。
* 绕行时间：论文目标里没有时间价格项（五项＝固定＋里程＋燃油＋电费＋碳），只作为时间窗
  可行性约束出现。

### 1.4 内核会不会主动插站

**不会。** `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:1258` 建 HGS 内核模型时，
节点集合是 `(*depots, *reload_copies, *customers)`——`node_type == "f"` 的公共站**根本没有进内核**。
所以内核（third_party/setp_hgs_kernel，PyVRP 派生）的所有邻域算子只在客户序列上动，
站节点只能由修复层产生。内核看到的电价是一个按班次折算的代理单价
（run_01 metadata 的 `shift_aware_ev_proxy`：AM 0.68027、PM 1.18154 元/kWh），
这个代理里**只有车场价**，没有公共站价。

### 1.5 现有 parallel 模式下站方案为什么总是输（定量）

先看运行侧证据（`solver/reports/grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS/run_01/metadata.json`）：

| 计数器 | run_01 值 |
|---|---|
| `charging_station_pruning.totals.enumerated` | 145 403（≈96 站 × 1 515 次未命中缓存的修复） |
| `...reachable` | 21 064 |
| `...after_equivalence` | 21 064（站副本去重没删掉任何一个） |
| `...after_dominance` | 21 064（**支配剪枝一个都没剪掉**） |
| `...candidate_rebuilds` | 22 579 ＝ 1 515 车场候选 ＋ 21 064 公共站候选 |
| `...candidate_evaluations` | 56 265 |
| `evaluation.breakdown.station_charging_kwh` | **0** |

也就是说：站候选**被完整地造出来并打过分了两万多次**，是每次都输，不是没被枚举。

再看价格结构（`data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv`，
`city=beijing, date=2025-02-12`）：

| 时段 | 小时 | 车场 `depot_energy` | 公共站 `public_energy` | 服务费 | 公共站 `public_total` | 碳 kg/kWh |
|---|---|---|---|---|---|---|
| 谷 | 23–07 | 0.56329 | 0.56329 | 0.40 | 0.96329 | 0.585–0.644 |
| 平 | 07–10、13–17、22–23 | 0.83644 | 0.83644 | 0.40 | 1.23644 | 0.154–0.319 |
| 峰 | 10–13、17–22 | 1.14862 | 1.14862 | 0.40 | 1.54862 | 0.165–0.486 |

**结构性事实：`public_energy` 与 `depot_energy` 每个小时逐位相等，`public_total` 恒等于
`depot_energy + 0.40`。** 午谷反事实日历
（`china81_cf_calendar_midday_valley_v1_20260904`）只重排了时段边界，这条恒等式照旧
（README 明写服务费列不动、`public_energy + public_service == public_total` 逐位成立）。
所以**同一小时里，站永远比车场贵 0.40 元/kWh，一分不多一分不少**；站唯一可能的优势是
「挑一个更干净、或更便宜的小时」。

充电功率不是优势来源，而且这一条要连充电曲线一起核，光看铭牌功率不够：

* 铭牌功率相等：公共站 `station_power_kw = 60.0`
  （`data/ChinaInstances/china81_final_suite_v2_20260815/facilities.csv` 第 19 列，424 行全是 60.0），
  车场 `depot_charge_power_kw = 60.0`
  （`fleet_caps.csv`，本算例两个车场都是 60.0，参数类 `P43_I_CHINA_LOGISTICS_DEPOT_DC_60KW_DEFAULT`）。
* 充电曲线也相等：实际充电时长走
  `charging_curve.py:248 curve_for_charging_node(node_type=...)` →
  `:198 _spec_for_charging_node_uncached`，该函数**按节点类型分叉**（`"d"`→`depot_*`，
  `"f"`→`public_*`）。实测本算例两支返回**同一条曲线**：
  `depot_charging_curve_id == public_charging_curve_id == "M17_FAST_SHAPE_SCALED_60KW_PWL"`，
  `soc_breakpoints = (0.0, 0.85, 0.95, 1.0)`、
  `relative_powers = (0.99707, 0.45455, 0.15152)` 逐位相同。

**同样的电量、同样的起始电量，站和车场耗时逐位一致；所以「站补电省时间→少一辆车」
这条通道在本算例里不存在。**（这也是 §4 里判 B/C 不值得的前提之一；若将来换成
公共站快充、车场慢充的参数，这条结论必须重核。）

闭式的每 kWh 账（探针输出 `per_kwh_gap.csv`，把 1 kWh 从「车场当天最便宜的槽」挪到「站的第 h 小时」）：

| 日历 | 车场最便宜槽 | 最有利的站时刻 | 电费差 元/kWh | 碳折减 kg/kWh | 盈亏平衡碳价 元/kg | P=0.2 净额 | P=1.0 净额 |
|---|---|---|---|---|---|---|---|
| 北京真实 | 00:00，0.56329，0.6433 kg | 13:00，1.23644，0.1541 kg | +0.67316 | 0.4892 | **1.376** | −0.388 | −0.184 |
| 午间设谷 | 01:00，0.56329，0.6439 kg | 13:00，0.96329，0.1541 kg | +0.40000 | 0.4898 | **0.817** | −0.302 | **+0.090** |

即使完全不算绕行，论文正式碳价 0.2 元/kg 离盈亏平衡还差 4～7 倍；只有在午谷日历 ×
碳价 1.0 这一格，理论上每 kWh 才有 +0.09 元的空间。

但这张闭式表用的是「车场被迫在夜里最脏的谷段充电」这个最不利假设。**实际解里不是这样**：
run_01 的 `shift_aware_ev_proxy` 显示，趟间那笔车场补电落在 12:00（碳 0.1646 kg/kWh），
**车场已经占住了午间最干净的时段**。这才是站方案输的最终原因——站唯一的理论优势
（更干净的小时）车场自己已经拿到了，还便宜 0.40 元/kWh。

### 1.6 固定路线入口是否还活着（只报告，不删）

用户 2026-09-06 令「固定路线方案一律不得存在」。核查结果：

| 入口 | 位置 | 是否活的 |
|---|---|---|
| `solve_charging_fixed_route` | `resetp_alns/support/charging.py:569`；`search/charging.py:69` | 正式主线**不可达**（见下） |
| `replay_fixed_route_charging` | 同上 :706 / :215 | 只有 `solver/tests/test_e5_ablation.py:81-82` 调用 |
| `solve_charging_naive` | 同上 :544 / :44 | 只被上面两个内部调用 |

* `algorithms/problem_hgs/mechanical_baseline.py:21,617` 从**旧文件** `setp_solver.search.charging`
  导入 `solve_charging_fixed_route`。`mechanical_baseline` 只被 `setp_solver/main3b_backend.py:59`
  导入，而 `main3b_backend` 只被 `solver/tests/test_main3b_protocol.py` 引用。
  正式运行入口 `solver/scripts/run_problem_hgs_private_technical.py` **不导入这两者**（已 grep 确认）。
* `setp_solver/china81_completion.py:330 complete_china81_route_skeleton`（内部会调
  `repair_route_charging_candidates`）**全仓无调用点**，是死代码；`evaluation.py:36` 只从该模块
  取 `_depot_fleet_violations` 和 `annotate_cross_site_services`。

**另有一条值得单列的发现：`charging.py` 有两份，已经分叉。**
`solver/src/setp_solver/search/charging.py`（975 行）是旧版，**没有** `repair_route_charging_candidates`、
没有 `public_station_candidate_mode`、没有充电曲线和 `ChargingRepairRuntime` 缓存；
`solver/src/setp_solver/algorithms/resetp_alns/support/charging.py`（2439 行）是现行版。
正式主线走的是后者（`problem_hgs/charging.py:36-37` 从后者导入）。前者只剩
`mechanical_baseline` 和三个测试文件在用。

### 1.7 正式实验的开关取值

`solver/scripts/run_problem_hgs_private_technical.py:335`（`_policy`）里
`public_station_candidate_mode="parallel"` 是**写死的**，没有 CLI 开关；
`problem_hgs/charging.py:1185` 另有一处写死的 `"parallel"`。
`solver/scripts/run_grid2x2_one.sh` 的命令行里没有相关参数。所以本轮所有正式解都是 parallel。

---

## 2. 模型—算法差距的准确表述

**模型允许什么**（`docs/paper_v2/paper_main.tex`）：

* :412「充电站在重复访问时使用相应节点副本」——一趟里可以**多次**访问公共站，次数无上界。
* :420–:421 每个被访问的公共站节点对应一个充电过程 $h$，$B_h^{d}=\varepsilon_{ir}+Y_{ir}$，
  充电量 $Y_{ir}$ 是**连续决策变量**，即**部分充电**，量不受「补足剩余全程」约束。
* :423–:424 车场侧才有基数约束：首趟前集合 $\mathcal C^{0r_1}_{kp}$ 与趟间集合
  $\mathcal C^{rr'}_{kp}$「均为空集或只含一个充电过程」。
* 车场与公共站之间**没有二选一约束**；一趟里既在车场充、又在路上的多个站充，是合法方案。

**算法只做了什么**：

| 维度 | 模型 | 算法（parallel 支） |
|---|---|---|
| 一趟内公共站次数 | 0…任意多 | 0 或 1（:909 注释＋:1212 失败关闭） |
| 站的充电量 | 连续变量 $Y_{ir}$ | 强制＝「覆盖整条剩余路线」（:1131） |
| 车场补电量 | 连续变量，与站量独立 | 强制＝「刚够开到那个站」（:922/:987） |
| 车场＋站的分配比例 | 连续 | 只有两个端点：100%车场 / 最小车场＋站包全程 |
| 站的触发条件 | 经济或可行性 | fallback 支只在断电时（:1129）；parallel 支靠人为制造断电 |

一句话：**「车场充多少」和「站充多少」这条连续的分配轴，算法只取了两个端点，中间从未枚举；
而且一趟最多一个站。**

---

## 3. 上界探针（任务二）

脚本：`solver/scripts/probe_station_topup_20260907.py`（只读）
输出：`solver/reports/probe_station_topup_20260907/{per_kwh_gap,trip_upper_bound,summary}.csv`

### 3.1 做法

对每个已落盘 `best_solution.json`，取 `evaluation.prepared_solution.routes` 的每条电动车趟、
`trip_clock` 的出发时刻，复刻修复层的行程时钟；对路线上每个「车场出发弧或任一客户之后的弧
$(i,j)$」和每个公共站 $s$：

* 绕行距离 $d(i,s)+d(s,j)-d(i,j)$、绕行时间、绕行电耗，全部走 `instance.arc_metrics` 与
  `ev_instance_arc_energy_kwh`（**与求解器同一套只读函数，含半载推进和冻结的 EV 路网矩阵**）；
* 用 `_curve_aware_action` 造站充电动作（60 kW 曲线），用 `charging_action_electricity_cost` /
  `charging_action_emissions_kg` **按槽精确结算**站电费与站碳；
* 车场那侧按**该趟车场充电动作实际选中时段**的均价与均碳折减（对站方案最有利的口径）；
* 替换档位 25% / 50% / 100% 的车场补电量；
* 收益 ＝ 车场省下的（电费＋碳价×碳） − 站的（电费＋碳价×碳） − 绕行里程费（0.9145 元/km）。

**有意放宽的两处**（宁可高估，避免把「没找到」当成「不存在」）：

1. 允许车在站里**等到当天任一更便宜/更干净的半小时槽**再起充；
2. 绕出去的位置放宽到车场出发弧（派工只要求客户之后）。

时间可行性分四档逐层收紧，每档一列，便于看清「上界靠哪个假设撑着」：

| 列 | 检查什么 |
|---|---|
| `time_window_ok` | 绕行＋充电占用 ≤ 到下一客户的松弛，且不越站的服务窗口 |
| `time_window_ok_downstream` | 从插站处**重走整趟剩余路线**，逐点核 `due_time`（含回场） |
| `pushes_next_trip` | 本趟被推迟 `added_trip_seconds` 后，**同一台车的下一趟还能不能按原时刻出发** |
| `gain_no_wait_cny` | 完全不许在站等候（到站即充）的同一笔账 |

仍未检查的：不重排行程、不检查班次合约细则、不检查车场充电窗口是否会因电量减少而换时段
（后者对站方案不利，故不影响上界性质）。

### 3.2 结果

| 目录 | 碳价 | 解数 | 趟数 | 有正收益 | 下游窗口也可行 | **不顶到下一趟** | 上界 元/解 | 最好单趟 元 | 不许等候时有正的趟 |
|---|---|---|---|---|---|---|---|---|---|
| `grid2x2_v3_20260906/beijing/P=0.2/MTC-HGS` | 0.2 | 10 | 79 | 0 | 0 | **0** | **0.000** | −0.760 | 0 |
| `grid2x2_v3_20260906/beijing/P=1.0/MTC-HGS` | 1.0 | 10 | 96 | 0 | 0 | **0** | **0.000** | −0.760 | 0 |
| `grid2x2_v3_20260906/midday/P=0.2/MTC-HGS` | 0.2 | 10 | 82 | 0 | 0 | **0** | **0.000** | −0.342 | 0 |
| `grid2x2_v3_20260906/midday/P=1.0/MTC-HGS` | 1.0 | 10 | 116 | 14（12.1%） | 14 | **0** | **0.000** | +1.002 | 0 |
| `policy_combos_20260907/midday_subsidy`（run_01–03） | 0.2 | 3 | 38 | 0 | 0 | **0** | **0.000** | −1.217 | 0 |

（放松「不顶下一趟」这一条时，午谷 × 1.0 那格的上界是 1.036 元/解、13.47 kg/解；
其余四格即使放松也仍是 0。）

（`midday_subsidy` 目录实际有 10 次运行；按派工口径只取前三次。）

**两碳价的差别**：北京真实日历下，碳价从 0.2 抬到 1.0 完全不改变结论（上界都是 0，最好单趟
都是 −0.76 元）；只有午谷日历下抬到 1.0 才让 12% 的趟出现正上界。这与 §1.5 的盈亏平衡碳价
（真实日历 1.376、午谷 0.817）方向一致。

**唯一出现正收益那一格长什么样**（`trip_upper_bound.csv`，14 行）：
首趟 10:14 到达站 `S_OSM_NODE_12070106294`（绕行仅 70 米、106 秒），**在站空等到 13:00**
才起充，把整笔 26.94 kWh 的夜间车场补电搬过来。电费亏 10.84 元，碳减 11.84 kg，
碳价 1.0 下净赚 1.00 元。

这 14 行**确实能过整趟下游时间窗**（`time_window_ok_downstream` 全为真——本算例客户
due_time 很宽），所以「上界为零」不是靠一个偷懒的检查撑住的。真正把它们判死的是**多趟**：
`added_trip_seconds` 为 10 501～11 825 秒（2.9～3.3 小时），`pushes_next_trip`
**14 行全为真**，同一台车的下一趟按原时刻出不去了。在多趟排班下，
「为省 1 元把整台车压后 3 小时」不是可行改进。

**为什么是零**：不是绕行造成的，是价差造成的。看 `trip_upper_bound.csv` 里那个绕行几乎为零
的样本（站 `S_OSM_WAY_167459641`，绕行 3×10⁻⁷ 米、绕行时间 0 秒）：移 10.86 kWh，
车场实际单价 1.1291 元/kWh，站单价约 1.2364 元/kWh，**纯价差就亏 1.17 元**，
碳只省 0.094 kg，碳价 1.0 下仍净亏 1.07 元；该样本的盈亏平衡碳价是 12.4 元/kg。
绕行里程费在最好的几行里只占 0.06～0.42 元，是次要项。

### 3.3 结论

**在本算例的现行价格与多趟排班下，顺路小补的收益上界在每一格都是 0 元/日**——
两份日历、两个碳价（0.2 与 1.0）、43 个解、411 个趟，无一例外。
原因是公共站服务费 0.4 元/kWh 的恒定加价，叠加「车场那笔充电已经占住当天最干净的时段」，
而不是绕行代价。只有在「午间设谷 × 碳价 1.0」这一格，**并且允许把同一台车的下一趟推迟约
3 小时**时，才出现 1.04 元/解（≈0.04% 总成本）的理论上界。

---

## 4. 三个候选设计

共同前提：不动三个受保护文件（`cost.py`、`check.py`、`search/evaluation.py`）；
新行为一律挂在显式开关后面，默认关闭，以保住既有结果的逐位可复现性。

### 方案 A：修复层扩展——两段式「车场部分补 ＋ 沿途单站小补」

**思路**：把 `public_station_candidate_mode` 增加一个取值 `split`。对每条趟、每个候选插入位置
$(i,j)$、每个候选站 $s$，把「车场补 $x$ kWh、站补 $y$ kWh」当成一条一维决策轴来解，而不是
只取两个端点。

**为什么可以精确解，而不是拍一个百分比网格**（邻域论证）：

固定站 $s$、插入位置 $(i,j)$、以及两笔充电各自的**起充时刻**后，设整趟总需电量为 $E$
（含绕行电耗），车场补 $x$、站补 $E-x$。电价与碳强度都是**时段上的阶梯函数**，
按槽分段结算（`cost.py:1382` 起）。若两笔充电都不跨槽，则总成本
$f(x) = c_d x + c_s (E-x) + K$ 在 $x$ 上是**线性**的，最优必在端点；一旦某笔充电跨槽，
斜率在「该笔充电正好填满当前槽」的那个 $x$ 处发生变化。所以

> $f$ 是 $x$ 的分段线性函数，断点只可能落在「车场充电或站充电的时长正好触到一个半小时槽边界」
> 的那些 $x$ 上。日历一天 48 槽，两笔充电各至多跨过 48 个槽边界，**断点至多 96 个**，
> 全部枚举即得精确最优，无需网格近似。

（充电曲线是分段线性的，会再引入至多 $|breakpoints|$ 个断点，量级不变。）

**伪代码**：

```
function SPLIT_CANDIDATES(trip r, instance, prices, calendar):
    C ← [ depot_only_candidate(r) ]                      # 现有 fallback 候选，保持不变
    for each position (i, j) in arcs(r) with i ∈ {depot} ∪ customers(r):
        S ← K_NEAREST_STATIONS(i, j, k)                  # 预计算，k≈5，按 d(i,s)+d(s,j)−d(i,j)
        for s in S:
            if not TIME_FEASIBLE_DETOUR(i, s, j) : continue
            E   ← total_energy_need(r) + detour_energy(i, s, j)
            X   ← BREAKPOINTS(E, depot_slot_grid, station_slot_grid, charge_curve)
                  ∪ {0, E}                               # 至多 ~100 个候选分配
            for x in X:                                  # x = 车场补电量
                if x > battery_cap or E − x > battery_cap : continue
                a_d ← depot_action(x,  start = ARGMIN_SLOT(depot_window,  x))
                a_s ← station_action(E − x, start = ARGMIN_SLOT(arrival_s .. latest_s, E − x))
                if not BATTERY_FEASIBLE(r, s, a_d, a_s) : continue
                if not TIME_WINDOWS_OK(r, s, a_s)        : continue
                C ← C ∪ { candidate(route = r with s inserted at (i,j), actions = [a_d, a_s]) }
    return PRUNE(C)                                       # 沿用现有 equivalence + dominance
```

**剪枝**：沿用现有两级。
`physical_station_id` 等价类合并（:974）继续用；`_remove_dominated_station_screens`（:2093）
的支配关系需要**加一维**——现有 `_strictly_dominates_station`（:2049）比的是
（到站时刻、离站电量、占用时长、电费、碳……）这一组资源，两段式方案要把「留在车场的能量 $x$」
也算进资源向量，否则不同 $x$ 的候选会互相误支配。注意 §1.5 的实测：**当前支配剪枝一个都没剪掉**
（after_dominance == reachable == 21 064），所以它现在不是瓶颈，加一维也不会更糟。

**复杂度**：设一趟客户数 $n$、候选站数 $k$（近邻裁剪后）、断点数 $T\le 100$。
每趟 $O(n\,k\,T)$ 次候选构造，每次构造要走一遍路线做电量/时间校验，即 $O(n)$，
合计 $O(n^2 k T)$。本算例 $n\approx 5$、$k=5$、$T\approx 100$ → 每趟约 12 500 次基本操作，
比现在的「97 站全枚举 → 约 14 个可达候选 × 全路重建」高一个量级但同数量级可控。
若嫌重，可先只在**每趟一个位置**（当前最省绕行的那个 $(i,j)$）上开，$O(nkT)$。

**与现有开关的关系**：新增第三个取值 `split`；`fallback` 与 `parallel` 行为逐字节不变。
`repair_route_charging`（:734）的比法（`min` over `route_model_cost_delta`）不用改。

**时间窗与容量**：容量不受影响（站需求为 0）。时间窗必须比探针严——要走完整的
`route_timing` / `certified_depot_charge_window` 复核，含后续客户的连锁迟到与班次合约，
不能只看下一客户的松弛。

**与首趟前 / 趟间车场补电的联动**：这是本方案最需要小心的一处。车场补电量 $x$ 变小后，
`certified_depot_charge_window`（`search/multitrip_schedule.py`）给出的窗口不变，但
`select_certified_depot_charge_start` 选中的**槽可能变**（充电时长变短，能塞进更便宜的槽）。
所以每个 $x$ 都要重新选一次车场起充时刻，不能沿用原候选的时刻——探针里为了做上界故意
用了原时刻，正式实现不能这么省。`_reanchor_depot_actions`（:1534）在末尾会再算一次，
必须确认它不会把 $x$ 覆盖掉。

**改动文件与函数清单**：

| 文件 | 函数 | 改什么 |
|---|---|---|
| `resetp_alns/support/charging.py` | `PUBLIC_STATION_CANDIDATE_MODES`(:65) | 加 `"split"` |
| 同上 | `repair_route_charging_candidates`(:799) | 新增 split 分支（约 120 行） |
| 同上 | `_repair_route_charging_candidate`(:1045) | 允许 `depot_precharge_target_kwh` 与站覆盖量解耦；:1131 的 `coverage_targets` 改为按传入的站补电量走 |
| 同上 | `_best_station_insert`(:2107) | 增加「按指定能量充」的入口，绕开 `charge_amount_target_kwh` |
| 同上 | `_strictly_dominates_station`(:2049)、`_station_screen_profile`(:1956) | 资源向量加「车场留存能量」维 |
| 同上 | `ChargingRepairRuntime.candidate_key`(:156) | 缓存键加新维度 |
| `problem_hgs/charging.py` | `ChargingRepairPolicy`(:585)、:1185、:1338、:1742 | 把写死的 `"parallel"` 换成策略字段 |
| `scripts/run_problem_hgs_private_technical.py` | `_policy`(:321) | 加 CLI 开关，**默认 `parallel`** |
| `solver/tests/` | 新增 | §6 的三客户单测 |

**工作量**：约 350–450 行改动 ＋ 单测。以 Codex 一次派工计，中高难度（要动支配关系和缓存键）。

**对可复现性的影响**：默认关闭 → 现有结果逐位不变（须实测解哈希，不能只看代码声称）。

**风险**：(a) 支配关系改错会**默默削弱**现有 parallel 支的剪枝或误剪；(b) 候选数上升拖慢
每次修复，71 283 次迭代的规模下常数因子敏感；(c) 车场起充时刻要随 $x$ 重选，容易与
`_reanchor_depot_actions` 打架。

### 方案 B：内核算子——把站节点做成路线的一部分

**思路**：仿 Schneider, Stenger & Goeke (2014) 的 `stationInRe` 与 Keskin & Çatay (2016) 的
SR/SI 算子族，在局部搜索里加「插站 / 删站 / 换站」邻域。

**文献出处（已核原文）**：

* Schneider M, Stenger A, Goeke D. The Electric Vehicle-Routing Problem with Time Windows and
  Recharging Stations. *Transportation Science*, 2014, DOI 10.1287/trsc.2013.0490. §4.4：
  「the `stationInRe` operator performs insertions and removals of recharging stations.
  The operator is defined for all generator arcs $(v,w)$, where $v$ is a recharging station.」
  另外 2-opt\* 与 relocate 也对充电站开放，exchange 不开放。图 3 给出插入与删除两种形态。
* Keskin M, Çatay B. Partial recharge strategies for the electric vehicle routing problem with
  time windows. *Transportation Research Part C*, 2016, 65:111–127. §4.2.2 站删除（Random /
  Worst-Distance / Worst-Charge-Usage / Full-Charge Station Removal）、§4.3.2 站插入
  （Greedy Station Insertion、GSI with Comparison、Best Station Insertion）。

**关于「该算子在原文确实触发过」的核查结论（重要）**：

* **触发到什么程度已核**：Keskin & Çatay 的算法 2（ALNS 主循环）第 5–6 行「每 $N_{SR}$ 次
  迭代选一个 SR 算法删站、再选一个 SI 算法修复」、第 15 行「破坏后不可行就执行 Greedy
  Station Insertion」——算子在主循环里被**无条件周期性调用**，不是可选装饰。
  Schneider 等的 `stationInRe` 在每次禁忌搜索迭代的复合邻域里被枚举。
* **未核到的**：两文正文里**没查到**按算子分列的触发次数表或单独关掉站算子的消融实验。
  所以「该算子对结果有多大贡献」这一层，本次**未核**。
* **必须写进设计的迁移边界**：两文的目标函数都是**只有距离（和车辆数）**——
  Schneider 「minimize the number of vehicles ... total traveled distance」；
  Keskin 目标式 (1)「minimizes total distance traveled」。两文**都没有车场充电这个替代选项、
  没有分时电价、没有服务费、没有碳强度**。它们的站访问是**纯续航救火**：Keskin 的 SI
  明写触发条件是「the first customer at which the vehicle arrives with a negative battery level」。
  所以照搬它们的算子**不会带来经济动机**——在我们的算例里，路线靠车场充电本来就电量可行，
  站算子插进来的每一次都要被 §1.5 的 0.40 元/kWh 服务费判死。这条边界必须明写，
  否则就是「文献参数没核在原文是否真触发过」的老毛病换个马甲。

**伪代码**（局部搜索层）：

```
for each route r, for each arc (u, v) in r:
    STATION_IN:   for s in K_NEAREST(u, v): try r' = r with s inserted between u and v
    STATION_OUT:  if u is a station: try r' = r without u
    STATION_SWAP: if u is a station: for s' in K_NEAREST(pred(u), succ(u)): try r' = r with u→s'
    for each r': actions ← EXACT_CHARGE_AMOUNTS(r')      # 交给修复层定量
                 accept if route_model_cost_delta(r', actions) < 0
```

**复杂度**：每条路线 $O(n k)$ 个邻域点，每个点要重算充电安排 $O(n)$ → 每条路线 $O(n^2 k)$。
但**真正的代价不在这里**。

**致命的工程障碍**：内核（`third_party/setp_hgs_kernel`，PyVRP 派生，版本 0.12.2）
**没有站的概念**，而且它的路线与可行性核心是**编译好的 C++ 扩展**
（`third_party/setp_hgs_kernel/setp_hgs_kernel/_setp_hgs_kernel.cpython-313-darwin.so`，
源码在同目录 `cpp/`），不是改几行 Python 就能加维度的地方——加站节点和电量资源要动 C++ 并重编。
`kernel_proposals.py:1258` 只把 depot、reload copy、customer 三类喂进 `Model`。要让内核算子
碰站，得给 PyVRP 加「可选零需求节点」和「电量资源」，这是把电量约束搬进内核——
本项目此前从未做过，也不在任何已批准路线里。而且内核的代价代理只有每公里成本和一个按班次
折算的车场电价（`shift_aware_ev_proxy`），**代理里根本没有公共站价这一项**，
即使插了站，内核也看不见它贵在哪。

**改动文件**：`third_party/setp_hgs_kernel/**`（外部依赖，属于重写）、
`problem_hgs/kernel_proposals.py`、`problem_hgs/charging.py`、代理定价一整套。
**工作量**：数周级，且要重建内核的可行性与增量评价。**风险**：极高，且收益按 §3 为零。

### 方案 C：混合——内核只做插/删站，补电量由修复层精确解决定

即 B 的邻域 ＋ A 的定量。**继承 B 的全部内核改造代价**（站节点仍必须进内核模型），
只把「充多少」的责任还给修复层。相对 B 唯一的减负是不用在内核里实现充电曲线定价，
但「零需求可选节点 ＋ 电量资源」这块硬骨头一点没少。

---

## 5. 推荐

**推荐方案 A，并且不需要重跑论文批次。**

理由：

1. **上界为零**（§3）。两份日历、两个碳价、43 个解、411 个趟，没有一趟能在不推迟
   下一趟的前提下从顺路小补里赚到钱；因此改造的正当性只能是**模型—算法一致性**，
   不能包装成「能改善结果」。选最小改动的那个方案是对的。
2. **B 和 C 的代价与收益完全不匹配**：要把站节点塞进 PyVRP 派生内核并给它电量资源，
   而收益上界是零。
3. **A 是唯一能真正覆盖模型那条连续分配轴的方案**，而且它的精确解论证（§4 方案 A 的
   分段线性断点枚举）本身就是可以写进算法章的内容——「我们不是拍了个百分比网格，
   是证明了最优必在至多 96 个断点上」。

**要不要重跑：五格全部不用重跑。** 上界在每一格都严格为 0（§3.2 右侧几列），
开关默认关闭时结果逐位不变，打开后站会话数应仍为 0。
`midday × P=1.0` 那 14 行正收益已被「顶到下一趟」判死，不构成例外。

**必须同时纠正的一条叙事**：不要把「零会话」归因成「算法把可行域缩小了」。
算法确实窄（§2 属实），但零会话的成因是价格结构（服务费 0.4 元/kWh 恒定加价 ＋
车场已占住最干净时段）。论文里如果要解释站为什么不被用，应该讲价格，不是讲算法。

---

## 6. 验证计划（不自行开长跑）

**第一步：秒级单测（必须先过）。** 造一个 3 客户小算例，让两段式方案**必优**：

* 一个车场、一个公共站、三个客户，站正好落在客户 1 与客户 2 之间的直线上（绕行 ≈ 0）；
* 把日历改成：车场可用窗口只覆盖高价高碳时段（例如只有峰段可充），站的到达时刻落在
  低价低碳时段，且构造成 `public_total(站时刻) < depot_energy(车场窗口)`；
  ——注意这需要**构造日历**，因为真实日历里 `public_total ≡ depot + 0.40` 使这不可能，
  单测必须自带一份合成日历并在注释里写明「这是为了让机制必然触发的构造情景，不是现实价格」。
* 断言：`repair_route_charging(..., public_station_candidate_mode="split")` 返回的方案里
  车场补电量 $0 < x < E$、站补电量 $E-x > 0$，且总成本严格低于 `fallback` 和 `parallel` 两个候选。
* 附加断言（回归护栏）：同一算例下 `fallback` 与 `parallel` 的返回值与改动前**逐位相同**。

**第二步：每臂 ≤3 次短跑，只看机制探针，不看名次。**
在 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd` 上，`beijing × P=0.2` 与 `midday × P=1.0` 两格，
每格 split 开 / 关各 3 次。看四个数：
`evaluation.breakdown.station_charging_kwh`、
`accounting.charging_station_pruning.totals.{candidate_rebuilds, after_dominance}`、
`evaluation.total_cost`、`accounting.wall_seconds`。
判据：(a) 开关关闭时四个数与既有 run 逐位一致；(b) 开启时 `candidate_rebuilds` 应显著上升
（证明新候选真的造出来了，不是没触发）；(c) `station_charging_kwh` 预期仍为 0，若不为 0，
必须能在 `trip_upper_bound.csv` 里找到对应的、且 `pushes_next_trip` 为假的正收益格，
否则说明实现有错（很可能是漏了多趟约束）。
(d) `wall_seconds` 上升幅度需报告；超过 2 倍就要先做近邻裁剪 $k$ 的标定。

**第三步：用户批准后才开 10 次验收。** 不自行启动。

**停止条件**：第二步若 `candidate_rebuilds` 没上升，说明 split 分支没被走到，
停下来查接线，不要靠加跑次数掩盖。

---

## 7. 附：本文用到的证据入口

* 代码：`solver/src/setp_solver/algorithms/resetp_alns/support/charging.py`（现行修复层）、
  `solver/src/setp_solver/search/charging.py`（旧版，已分叉）、
  `solver/src/setp_solver/algorithms/problem_hgs/charging.py`、
  `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:1258`（内核节点集合）、
  `solver/scripts/run_problem_hgs_private_technical.py:335`。
* 价格与算例：`data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv`、
  `data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904/`、
  `data/ChinaInstances/china81_final_suite_v2_20260815/{facilities.csv,fleet_caps.csv}`、
  `data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/`。
* 探针：`solver/scripts/probe_station_topup_20260907.py`、
  `solver/reports/probe_station_topup_20260907/{per_kwh_gap,trip_upper_bound,summary}.csv`。
  注意 `.gitignore:31` 把整个 `solver/reports/` 排除在版本控制之外（既有约定，本次未改），
  所以这三份 CSV 只在本机磁盘上；本文 §1.5 与 §3.2 的关键数字已抄进正文，可离开 CSV 复核。
* 论文：`docs/paper_v2/paper_main.tex:412,420-424`。
* 文献：Schneider/Stenger/Goeke 2014 *Transportation Science* §4.4（Zotero JR544Q2D）；
  Keskin/Çatay 2016 *TR-C* 65:111–127 §4.2.2/§4.3.2/算法 2（Zotero WNDTM5L3）。
