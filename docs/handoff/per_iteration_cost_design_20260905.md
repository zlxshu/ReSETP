# 每圈成本的构成与可施工提速设计（只读，2026-09-05）

只读诊断＋微基准。**没有改仓库任何文件**，没有开 GA 搜索式实验（只跑了固定圈数的探针）。
脚本全部在 scratchpad（同目录）：`probe_common.py`（复刻交付批建图）、`probe_structure.py`（结构导出）、`probe_bench.py` / `probe_bench_long.py`（固定圈数 A/B）、`probe_attribution.py`（算子评估次数归因）、`probe_validate.py`（48 解模型等价）、`probe_decode.py`（48 解解码等价 ＋ churn 压力）、`probe_cprofile.py`。

**被读工作树版本（另一位代理正在改 `kernel_proposals.py`，行号以此为准）：**

| 文件 | SHA256 | 取样时刻 |
|---|---|---|
| `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py` | `54a9263a…d5f4e80` | 2026-09-05 03:26 |
| `solver/src/setp_solver/algorithms/problem_hgs/runner.py` | `b63c2569…6920579` | 同上 |
| `solver/scripts/run_problem_hgs_private_technical.py` | `7a7d60fe…899ddd8` | 同上 |

**探针口径**：完全复刻 `solver/scripts/run_ideal_construction_one.sh` 的 MTC-HGS 臂
（`--instance-id cn-jjj-50c-01-DEPOTSEARCH-d996f755bd --fleet-parameter-class endogenous
--charge-timing-policy cost_plus_carbon --no-ev-charge-time-proxy --ev-reload-gap-proxy`，
午谷电价日历，碳价 0.2，`max_reloads_per_vehicle` 用已落地的默认值 8）。
机器 Apple M1，探针单进程独占（本机后台只有 UI，load average 2.0）。
所有变体用同一个固定随机种子（20260905），停止准则用 `MaxIterations`（不是 `NoImprovement`），
所以"跑得快"只可能来自每圈更便宜，不可能来自轨迹更短。

---

## 0. 先把三件靠读代码就能定死的事定死

**这三条不需要跑，跑之前先做掉，因为它们决定哪几个变体值得测。**

### 0.1 载重维数：2 维 ＝ 载重 ＋ 体积，**没有锁定维**

`kernel_proposals.py:1113-1136`（客户 delivery）与 `:1461-1471`（车辆 capacity）里，
锁定维只在 `locked_depots` / `locked_vehicle_types` 非空时才追加，而这两个元组
（`:1085-1096`）只有在 `cross_depot_enabled=False` / `type_exchange_enabled=False` 时才非空。
交付批两个开关都是开的，所以**锁定维根本不存在，不是"恒为零"**。

实测（`probe_structure.py`）：`num_load_dimensions = 2`，`locked_load_dimensions = ()`，
capacity 向量 `(17350, 72)` ＝ (载重 kg×10, 体积 m³×1)。
派工信里说的 `excess_load=[0,0]` 就是这两维，**第二维是体积，是真约束**：

```
单客户最大 体积/容量 = 0.4167   载重/容量 = 0.2403
全部客户 合计 体积/容量 = 13.26  载重/容量 = 7.65
体积被载重支配（每个客户都满足 体积占比 ≤ 载重占比）: False
```

体积在总量上比载重**紧一倍**。所以"去掉未激活的维"这件事在本批**无维可去**；
真去掉体积维＝拆掉一条真约束（第 1.3 节实测了它值多少，但那是 B 类，不建议）。

### 0.2 20 个车辆类型的参数向量：**恰好只有 4 个真正不同**

`probe_structure.py` 逐字段导出 20 个 `VehicleType`（含 `capacity / start_depot /
end_depot / fixed_cost / tw_early / tw_late / shift_duration / max_distance / max_duration /
unit_distance_cost / unit_duration_cost / start_late / initial_load / reload_depots /
max_reloads / max_overtime / unit_overtime_cost / profile`）：

| 组 | 成员数 | capacity | fixed_cost | tw | start=end depot | profile | reload_depots | max_reloads |
|---|---:|---|---:|---|---:|---:|---|---:|
| cv @ D_OSM_WAY_1003511503 | 3 | (17350, 72) | 17000000 | 21600–79200 | 0 | 0 | (2,) | 8 |
| cv @ D_OSM_WAY_1071205721 | 7 | (17350, 72) | 17000000 | 21600–79200 | 1 | 1 | (3,) | 8 |
| ev @ D_OSM_WAY_1003511503 | 3 | (17000, 72) | 27000000 | 21600–79200 | 0 | 2 | (2,) | 8 |
| ev @ D_OSM_WAY_1071205721 | 7 | (17000, 72) | 27000000 | 21600–79200 | 1 | 3 | (3,) | 8 |

**除 `name`（＝`physical_vehicle_id`）外，20 个向量逐字段落进 4 个等价类。**
每 duty 一类的唯一原因就是 `kernel_proposals.py:1491` 的 `name=duty.physical_vehicle_id`
——是**为了解码时能把内核路线认回物理车**，不是因为固定成本 / 容量 / 班次窗 / 锁定维逐 duty 不同。

**一条必须写进设计的边界**：`:1449-1458`，当 `context.dynamic_state is not None` 时
`vehicle_tw_early` 取 `max(depot.ready_time, cut.trigger_second, asset.available_second)`，
**逐物理车不同**。所以合并必须实现成"按完整参数向量去重"，不能写死 4 类：
动态路径下去重会自然退化回 20 类，这正是想要的行为。本批 `dynamic_state is None`（已实测）。

### 0.3 4 份 profile 矩阵：其中 **两对逐位相同**，合并是精确的

`profiles` 按 (车型, 车场) 建（`:1161-1168`），但 `_route_proxy_cost_units`（`:1618`）里
duration 只依赖车型，distance 只在两处碰 `depot_id`（cv 的 `diesel_price_for_route`、
ev 的 `ev_unit_cost_by_depot[depot_id]`）。实测逐位对比 4 份 54×54 的
distance / duration 矩阵：

```
profile 0 (cv@D1) vs 1 (cv@D2): dist 逐位相同, dur 逐位相同
profile 2 (ev@D1) vs 3 (ev@D2): dist 逐位相同, dur 逐位相同
0 vs 2 / 0 vs 3 / 1 vs 2 / 1 vs 3: 不同（dist 最大差 6195066, dur 最大差 2047 s）
```

即两个车场在本算例上给出**完全相同**的柴油价与 EV 单价（同一份电价日历），
所以 4 份可以合成 2 份且逐位无损。
**但这是数据决定的，不是结构保证的**——所以实现也必须写成"矩阵逐位相同才合并"的去重，
不能写死 2 份；换算例 / 换成两个车场不同电价，去重会自然退回 4 份。

---

## 1. 每圈成本的构成（实测）

### 1.1 cProfile：内核圈里几乎没有 Python

`probe_cprofile.py`，4000 圈，`collect_stats=False`（与正式跑一致）：

```
9.014 s profiled
  8.513 s (94.4%)  LocalSearch.py:109(__call__)      ← 一进去就是 C++ _search.so
  0.215 s ( 2.4%)  _crossover.selective_route_exchange (C++)
  0.078 s ( 0.9%)  Population.select
  0.012 s          broken_pairs_distance (C++)
  0.001 s          kernel_proposals.py:61(_repin)    ← 我们唯一的 Python 回调，可忽略
```

**内核圈里没有可优化的 Python**：每圈成本 ≈ 局部搜索（94%）＋ 交叉（2.4%）。
（cProfile 自身有开销：同一段在无 profiler 时 13.8 s，带 profiler 14.3 s。
它只用来回答"有没有 Python 回调"，不用来量绝对值。）

### 1.2 固定圈数 A/B（同种子、`MaxIterations`）

两个量：`ms/it` ＝ 4000 或 15000 圈的 GA 墙钟 ÷ 圈数；
`ms/LS` ＝ 对**同一个投影解**连调 200 次 `LocalSearch.__call__` 的均值（无轨迹干扰）。

**4000 圈 × 3 次重复（取中位）：**

| 变体 | 类型数 | profile 数 | 载重维 | ms/it | 比现状 | ms/LS | 比现状 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **a 现状** | 20 | 4 | 2 | **3.451** | 1.000 | 0.948 | 1.000 |
| b 合并车型 | **4** | 4 | 2 | **3.140** | **0.910** | 0.814 | 0.859 |
| c 合并 profile | 20 | **2** | 2 | 3.449 | 0.999 | 0.929 | 0.980 |
| bc 两者都合并 | 4 | 2 | 2 | **3.203** | **0.928** | 0.797 | 0.841 |
| d 去掉体积维 | 20 | 4 | **1** | 2.500 | 0.724 | 1.086 | 1.146 |
| bcd 三样都做 | 4 | 2 | 1 | 2.258 | 0.654 | 0.907 | 0.957 |
| e `max_reloads=49`（9-05 前） | 20 | 4 | 2 | 3.456 | 1.001 | 0.948 | 1.000 |
| f `max_reloads=4` | 20 | 4 | 2 | 3.514 | 1.018 | 0.947 | 0.999 |
| g bc ＋ `max_reloads=4` | 4 | 2 | 2 | 3.175 | 0.920 | 0.794 | 0.838 |

**15000 圈 × 1 次（验证 4000 圈不是早期假象）：**

| 变体 | ms/it | 比现状 | 内核最优（同种子） |
|---|---:|---:|---|
| a 现状 | 3.353 | 1.000 | 267767874 |
| b 合并车型 | **3.077** | **0.918** | 265885015 |
| e `max_reloads=49` | 3.441 | 1.026 | **267767874（与 a 逐位相同）** |

**逐条结论：**

- **(b) 20 种车型合并成 4 种：省 8.2–9.0% 每圈**（4000 圈 −9.0%，15000 圈 −8.2%，
  三次重复 3.140 / 3.143 / 3.071，稳定）。纯局部搜索口径省 14%。**这是本题唯一实测有效的一项。**
- **(c) 4 份 profile 合成 2 份：0.0%（3.449 vs 3.451）。** 逐位相同的内核最优
  （282256396 / 275795744 / 282997425 三次全对上）证明它确实是无损变换，但**它不省时间**
  ——PyVRP 的矩阵是按 profile 索引查表，份数不进热循环，只省内存（两份 54×54 int64 ＝ 46 KB）。
  **不要为了它单独开工。** 它只作为 (b) 的顺带项（合并车型时顺手把重复 profile 也去掉）。
- **(d) 去掉体积维：省 27.6%，但那是拆约束。** 内核最优从 2.8 亿掉到 2.13 亿——
  掉的是被体积维挡住的不可行解。0.1 节已证体积不被载重支配，**这一维是真的，不能去**。
  列在这里只是给出"多维载重值多少"的量：**约 0.95 ms/圈 / 维**。
- **(e/f) `max_reloads`：在本算例上不是成本项。**
  两个口径**夹住零**：4000 圈 ×3 次重复，49 与 8 是 3.456 vs 3.451（**+0.1%**）；
  15000 圈 ×1 次，是 3.441 vs 3.353（**+2.6%**）。两者符号相反、量级都在噪声内。
  **真正的证据不是计时，是轨迹**：15000 圈那一次，49 与 8 在同种子下
  **内核最优逐位相同（267767874）**——41 个多出来的槽位从来没被走到过，两条搜索路径完全一致。
  4 与 8 同样没差（3.514 vs 3.451）。

  **⚠️ 这与交接里"`max_reloads` 49→8 约省 17%/圈"对不上。** 我复现不出那 17%。
  代码侧也不支持："每车 50 段行程槽位"不是一次性分配——`Route::insert` 里
  `depots_.reserve(depots_.size() + 1)`（`Route.cpp:148`）是按需增长的，
  `maxTrips` 只出现在两处**判断**（`Route.cpp:156` 的越界检查、
  `RelocateWithDepot.cpp:183` 的 `if (vRoute->numTrips() == vRoute->maxTrips()) return 0`）。
  所以 `max_reloads` 大只会让 `RelocateWithDepot` **多一点自由度**，不会撑大任何数据结构。
  已落盘 48 个 `best_solution.json` 里单车最多 5 趟（3 趟 145 车次、4 趟 19、5 趟 2），
  上限 8 从来没被顶到过。

  **那 17% 是哪来的（已查）**：全仓库只有一处写它——
  `docs/handoff/CURRENT_PROJECT_CONTEXT.md:3`：
  「第 1 轮预留 p75＋下限、`max_reloads` 8 已落地…速度 3 并行 3.6–3.8 ms/圈（快约 17%）」。
  它引的批次是 `solver/reports/reload_fix_shortrun_20260905/`，该目录下
  **没有任何 ms/圈 的对照表或 A/B 记录**（`comparison/summary.md`、`comparison/README.md`
  里都搜不到），只有 6 个跑的 `raw_runs.csv`。我从那 6 个 `raw_runs.csv` 自己算：
  **中位 3.90 ms/圈（3.79–4.11）**，与交接写的 3.6–3.8 基本对得上。
  但那个"快 17%"是拿它**跟并发回归外推的 c=3 预测值 4.48 比出来的残差**，而这个残差同时被三件事污染：
  ① 同一批还改了第 1 轮的 reload 预留（p75＋下限），那是会改整条搜索轨迹的改动；
  ② 并发回归（R²=0.675）主要拟合在 c≈4.2–6.0，外推到 c=3 本身不可靠；
  ③ 不是同批同种子的 A/B。
  **结论：那 17% 是跨批残差，不是 `max_reloads` 的效应。建议撤下或补一次同批 A/B。**

### 1.3 为什么合并车型能省，而 profile 不能

**因为这道题上 20 辆车里只有 5–6 辆真的装货。** 48 个已落盘最优解逐个数：

```
每个解实际载客的车数: 5 辆 → 19 个解 ; 6 辆 → 29 个解  （车队 20 辆）
```

于是内核的 20 条 `Route` 里长期有 **14–15 条是空的**。PyVRP 的局部搜索对空路线有一条
**按车辆类型逐个探**的固定开销（见第 2 节），车辆类型数直接乘在上面。
把 20 类并成 4 类，这条固定开销就从"最多 20 次×8 个算子"降到"最多 4 次×8 个算子"。

（注：交接里 §3(b) 写"车队实测 20 辆…20 个 duty"，那是**车队规模**；
**真正派出去的只有 5–6 辆**。这一条对理解每圈成本很关键，之前的诊断没区分。）

---

## 2. PyVRP 局部搜索里，规模项到底是哪一个

只读 `third_party/setp_hgs_kernel/setp_hgs_kernel/cpp/search/`。

### 2.1 主导项：`orderVehTypes` 的空路线探测（**随车辆类型数线性**）

`LocalSearch.cpp:865-868` 构造时：

```cpp
for (size_t vehType = 0; vehType != data.numVehicleTypes(); vehType++)
    orderVehTypes.emplace_back(vehType, offset);      // 每个车辆类型一项 → 本批 20 项
```

`LocalSearch.cpp:340-342`（`search()` 每个 step、每个客户 U 都调）：

```cpp
if (step > 0 || hasInitialEmptyRouteOperator)
    applyEmptyRouteMoves(U, costEvaluator, step == 0);
```

`LocalSearch.cpp:483-505`：

```cpp
for (auto const &[vehType, offset] : orderVehTypes) {           // 20 次 vs 4 次
    auto empty = std::find_if(begin, end, isEmpty);
    if (empty != end && applyNodeOps(U, (*empty)[0], ...)) break;   // 每次跑 8 个节点算子
}
```

**关键点**：`LocalSearch.cpp:303-304 / :327-329` 那条邻居循环有
`lastUpdated > lastTested` 的增量缓存挡着，**而 `applyEmptyRouteMoves` 没有任何缓存**
——每个 step、每个客户、每个车辆类型都无条件重跑。
50 个客户 × 20 个类型 × 8 个节点算子（`Exchange10/20/11/21/22, SwapTails,
RelocateWithDepot, DepotSplit`，实测算子表见 `probe_structure.py` 输出）
＝ 每个 step 最多 8000 次算子评估；合并成 4 类后是 1600 次。
14–15 条空路线保证这个循环几乎每次都真的找得到空路线（`find_if` 不会白跑）。

### 2.2 次要项：`SwapRoutes` 的同类型早退（**随类型数二次，但基数小**）

`SwapRoutes.cpp:12-13`：

```cpp
if (U == V || U->vehicleType() == V->vehicleType()) return 0;
```

20 类时 190 个路线对全都要真评估；4 类时组内的 C(3,2)+C(7,2)+C(3,2)+C(7,2)=48 对直接早退。
**但 `intensify()`（`LocalSearch.cpp:358-374`）先跳过空路线**，实际参与的只有 5–6 条非空路线
＝ 10–15 对，所以这一项**在本批上基本不值钱**。
`SwapStar` 与车辆类型数无关（它按路线对 × 客户走，`SwapStar.cpp:11-60`）。

### 2.3 `max_reloads`：只是判断，不是分配

- `Route.h:975` `maxTrips() = vehicleType_.maxTrips()`，只在两处用：
  `Route.cpp:156` `if (numTrips() > maxTrips())` 越界检查；
  `RelocateWithDepot.cpp:183` `if (vRoute->numTrips() == vRoute->maxTrips()) return 0`。
- `Route.cpp:148` `depots_.reserve(depots_.size() + 1)` —— **按需增长**，与 `max_reloads` 无关。
- `RelocateWithDepot.cpp:68/86/126/144` 的循环走的是 `vehType.reloadDepots`（本批每车 1 个），
  不是 `maxReloads`。

**所以 `max_reloads` 不是规模项**，与 1.2 节 (e/f) 的实测一致。

### 2.4 载重维数：进最内层

`SwapStar.cpp:86-97` 的 `deltaLoadCost` 有 `for (size_t dim = 0; dim != data.numLoadDimensions(); ++dim)`，
每维两次 `loadPenalty`；`Route.cpp:315/325/344` 每维一个 `nodes.size()` 长的前后缀数组。
实测每维约 0.95 ms/圈（1.2 节 d）。**但本批两维都是真的，无维可删。**

### 2.5 把"主导项"实测出来，而不是只靠读代码

`probe_attribution.py`：同一个投影解，连调 200 次 `LocalSearch.__call__`，
每次调用后读每个算子的 `statistics.num_evaluations` 并累加（`init()` 每次会清零，所以必须逐次读）。
**唯一的差别是车辆类型数（20 vs 4），profile / 载重维 / `max_reloads` 全都不动：**

| 算子 | 20 类 评估次数 | 4 类 评估次数 | 变化 |
|---|---:|---:|---:|
| DepotSplit | 1,267,797 | 916,823 | −27.7% |
| Exchange10 | 1,141,394 | 877,203 | −23.1% |
| SwapTails | 1,140,969 | 876,781 | −23.2% |
| Exchange11 | 1,140,948 | 876,701 | −23.2% |
| Exchange21 | 1,140,880 | 876,883 | −23.1% |
| Exchange22 | 1,140,879 | 876,658 | −23.2% |
| Exchange20 | 1,140,855 | 876,707 | −23.2% |
| RelocateWithDepot | 1,140,757 | 876,759 | −23.1% |
| **节点算子小计** | **9,254,479** | **7,054,515** | **−23.8%** |
| SwapRoutes（路线算子） | 3,954 | 3,969 | +0.4% |
| SwapStar（路线算子） | 3,954 | 3,969 | +0.4% |

**这就把归因做实了：**

1. **路线算子的评估次数一位没变（+0.4%）** —— `intensify()` 按路线对走、且先跳过空路线，
   与车辆类型数无关，2.2 节判断的"`SwapRoutes` 在本批不值钱"被实测证实。
2. **节点算子评估次数掉 23.8%**，而 `search()` 与 `intensify()` 的全部代码里
   **只有 `applyEmptyRouteMoves` 一处依赖 `numVehicleTypes`**（`LocalSearch.cpp:483-505`，
   `orderVehTypes` 建于 `:865-868`）。所以这 220 万次的减少**只能**来自空路线探测。
3. 反推出这条支路的占比：若空路线探测占节点算子评估的比例为 x，
   把 20 类降到 4 类会把它降到 4/20，则 `x·(1−0.2) = 0.238` → **x ≈ 29.8%**。
   即：**每圈的节点算子评估里约三成是空路线探测**，邻居循环占另外七成。
4. 评估次数掉 23.8%、纯局部搜索墙钟掉 14%（0.948→0.814 ms/call）——
   两者方向一致、量级合理（空路线上的拼接比一般邻居对便宜，所以省时间的比例小于省次数的比例）。

**主导项判定（已实测，不是推测）：车辆类型数（经由 `applyEmptyRouteMoves`）
> 载重维数（0.95 ms/圈/维，但本批两维都必要）
> `SwapRoutes` 同类型对（实测 +0.4%，可忽略）
> `max_reloads`（实测轨迹逐位相同，＝0）。**

---

## 3. 合并后投影 / 解码怎么保持物理车映射

### 3.1 现在是怎么接的

- 建图（`:1499-1500`）：`vehicle_type_by_duty_id[physical_vehicle_id] = index`，
  `duty_id_by_vehicle_type[index] = physical_vehicle_id`，**1:1**。
- 投影 `_project`（`:708-741`）：每个 duty 取 `self._vehicle_type_by_duty_id[duty.physical_vehicle_id]`
  当 `vehicle_type`，起终点用 `home_depot_id` 的位置，中间趟用 reload 副本。
- 解码 `_decode_changes`（`:743-782`）：
  ```python
  duty_id = self._duty_id_by_vehicle_type[int(route.vehicle_type())]      # :752
  if output[duty_id]:
      raise ValueError("IndependentKernel returned two routes for one physical asset")  # :754
  ```
  最后**只返回链条变了的 duty**（`:777-781`），没变的不进 `replacements`。
- duty 身份三件套 `(physical_vehicle_id, vehicle_type, home_depot_id)` ＝ `_fleet_registry`
  （`:1702-1711`），`project` / `decode_replacements` / `propose` 三个入口都先校验它没变。

### 3.2 合并后会在哪一行炸

`:752` 是 1:1 的字典。合并后一个类型索引对应 3 或 7 个物理车，
**每组的第二条路线必然触发 `:754` 的 ValueError**。这是唯一的硬阻塞点。

### 3.3 保持映射的办法（同车场同车型可任意互换，已实证）

**为什么可以互换**：0.2 节已证同组 20→4 的参数向量逐字段相同；
而且 `probe_validate.py` 把 **48 个已落盘 `best_solution.json`** 分别投影进
现状模型（20 类 4 profile）与合并模型（4 类 2 profile），逐位比
`distance / distance_cost / duration / duration_cost / fixed_vehicle_cost / time_warp /
excess_distance / excess_load / is_feasible / num_routes / num_trips / num_clients`：

```
identical on every compared field: 48/48   mismatches: 0
```

**换句话说：合并不改变任何一个已落盘解的内核读数，也不改变可达空间**——
组内换车位是纯改名，成本函数一位不动。

**改法（`_decode_changes` 一处，配一个新映射）：**

```python
# 建图侧：duty_ids_by_vehicle_type[type_index] = [duty_id, ...]（按 duty 原顺序）
def _decode_changes(self, individual, solution):
    current = {d.physical_vehicle_id: tuple(tuple(t.customer_ids) for t in d.trips)
               for d in individual.duties}
    by_type = {}                                        # 类型 → 该类型的路线链条列表
    for route in solution.routes():
        by_type.setdefault(int(route.vehicle_type()), []).append(self._chain(route))
    output = {duty_id: () for duty_id, _t, _d in self._fleet_registry}
    for vtype, chains in by_type.items():
        slots = list(self._duty_ids_by_vehicle_type[vtype])
        if len(chains) > len(slots):
            raise ValueError("kernel returned more routes than this group owns")
        # ① 锁定 duty 先钉死：它的链条必须留在自己车位上
        # ② 与某车位 current 链条完全相同的，原地不动（零 churn）
        # ③ 其余按"与该车位 current 链条共享客户最多"贪心配对，减少虚假 replacements
        for duty_id, chain in _least_churn_match(slots, chains, current, self._locked):
            output[duty_id] = chain
    return tuple((k, v) for k, v in output.items() if v != current[k])
```

**为什么必须"最小改动匹配"而不是随便配**：`_decode_changes` 只返回**变了的** duty，
下游 `runner.py:820-870` 的精确阶段按 `replacements` 逐 duty 做解码＋充电修复＋完整评价。
任意配对会让本来没动的车也被判定成"变了"，把每轮的精确阶段工作量从几条 duty 抬到 20 条
——**每圈省下来的 8% 会在精确阶段吐回去**。

**锁定 duty**：`_duty_locked`（`:1713`）＝ `has_dynamic_commitment` 或有
`locked_customer_prefix` 或有 `locked` 充电会话。静态批实测三者全空
（48 个 dump 逐个核过：`has_dynamic_commitment` / `locked_customer_prefix` / 充电会话 `locked` 三者全空，带锁 duty 数 ＝ 0）。
但代码必须处理：先把锁定 duty 钉在含它锁定前缀的那条路线上，再配其余。
另外动态路径下 0.2 节的去重会自然退化成 20 类，那时这套逻辑与今天等价。

**`fleet_exact_composition`（`run_problem_hgs_private_technical.py:2040-2043`）**：
它要求"每辆配置的车都要派出去"。合并只改车位标签，**每组的 (车型, 车场, 台数) 多重集一位不变**
（3/7/3/7），所以固定配比按构造保持；而且合并前后 `num_available` 之和都是 20，
内核照样可以停车，与今天完全一样，不引入新的偏差。

**其余读这两个映射的地方**：`_compatible_vehicle_groups`（`:427-441`）按
`groups[type_index] = 车型标签` 写，合并后同组重复写同一个值，结果正确，**不用改**；
`greedy_repair_skeleton_move`（`:612-615`）用 `_vehicle_type_by_duty_id.values()`
造 20 条空路线，合并后仍是 20 条（类型索引重复），与 `num_available` 之和相符，**不用改**。

---

## 4. 可施工设计（按投入产出排序）

设计 1 与设计 3 都碰 `kernel_proposals.py`——**这个文件正被另一位代理改，两条都要先排队协调，不只是交接 §5 里点名的那条 `max_reloads`。** 设计 2 不碰源码，且已经落地。

### 设计 1（推荐）：车辆类型按参数向量去重（顺带 profile 去重）

- **改哪里**
  - `kernel_proposals.py:1441-1502` `_build_unique_asset_problem` 的 `add_vehicle_type` 循环
  - `kernel_proposals.py:1161-1168` profile 建立处
  - `kernel_proposals.py:743-782` `_decode_changes`
  - 新增 `duty_ids_by_vehicle_type: dict[int, list[str]]` 取代 `duty_id_by_vehicle_type`
- **伪代码**

```python
# 1) profile：矩阵逐位相同才合并（不写死 2 份）
profile_id = {}                       # (车型, 车场) → 去重后的 profile
for key in sorted(profile_keys):
    sig = (dist_matrix(key).tobytes(), dur_matrix(key).tobytes())
    profile_id[key] = canonical.setdefault(sig, model.add_profile(...))

# 2) 车辆类型：按完整参数向量去重（不写死 4 类；动态路径 tw_early 不同 → 自然退回 20 类）
buckets = {}
for duty in fleet_template.duties:
    v = (capacity, fixed_cost, tw_early, tw_late, depot, profile_id[...],
         reload_depots, max_reloads)          # 一切除 name 外的入参
    buckets.setdefault(v, []).append(duty.physical_vehicle_id)
for v, duty_ids in buckets.items():
    model.add_vehicle_type(num_available=len(duty_ids), name="+".join(duty_ids), **v)
    duty_ids_by_vehicle_type[index] = duty_ids

# 3) 解码：组内最小改动匹配（见 3.3）
```

- **预期降幅**：**每圈 −8.2%（15000 圈）到 −9.0%（4000 圈）**，实测中位 3.451→3.140 ms/圈。
  内核占整跑 91–95%，折成整跑墙钟约 **−7.6% 到 −8.4%**。
- **解质量风险：A 类（不改可达空间）**，但**不是逐位可复现**。
  可达空间与成本函数逐位不变（48/48 已落盘解验证）；
  改变的是 `orderVehTypes` 的长度，因而改变空路线探测顺序与随机流
  ——同种子下轨迹会不同（实测内核最优 267767874 → 265885015）。
  **这一点必须向用户明说：不是 bug，是"同一道题、同一片解空间、不同的搜索顺序"。**
- **秒级验证（两条都已在 scratchpad 里跑通，可直接抄成单测）**
  1. `probe_validate.py`：48 个 `best_solution.json` 投影进新旧两个模型，
     `distance / distance_cost / duration / duration_cost / fixed_vehicle_cost / time_warp /
     excess_distance / excess_load / is_feasible / num_routes / num_trips / num_clients`
     **48/48 逐位相同**。这证明**模型**等价。
  2. `probe_decode.py`：把 3.3 的最小改动匹配写出来，在**合并模型**上跑
     `project → decode`，48 个 dump **48/48 返回空元组**（不产生任何 replacement）。
     再加一道压力：把每组内部的路线顺序倒过来再解码，**仍然 48/48 返回空元组**。
     这证明**解码**等价，而且 churn 风险不是空话——匹配规则确实把它压到零。
     （这一条必须写进 `solver/tests/`，因为它盯的正是设计 1 唯一要新写的那段代码。）
  3. `pytest solver/tests/test_problem_hgs_route_proxy.py solver/tests/test_problem_hgs_depot_split.py solver/tests/test_problem_hgs_kernel_native.py solver/tests/test_problem_hgs_reload_gap.py solver/tests/test_problem_hgs_reload_gap_quantile.py`（这五份直接盖住建图 / DepotSplit 分组 / kernel_native 解码 / reload-gap 三条链路）。
- **与已落地改动的冲突**：与 `max_reloads=8`、确认轮自适应耐心**都不冲突**（不同文件 / 不同参数）。
  与另一位代理正在改的 `kernel_proposals.py` **有冲突，必须排队**。

### 设计 2：交付批并行度 ≤3 —— **已经落地了，这里只补一个实测数字**

- **状态**：`solver/scripts/run_ideal_construction_batch.sh:2,10` 已写成
  「M1 4 性能核，交付批 ≤3 并行、不降优先级」，`WORKERS` 默认 3；
  `run_ideal_construction_one.sh` 里 **`nice` 已经一个都不剩**（grep 计数 0）。
  `reload_fix_shortrun_20260905/run_shortrun_batch.sh:22` 也是 `PARALLEL=3`。
  **所以这条不是待办，是已完成项。** 交接 §5 第 1 条那个"7.75 → 约 4.2 分钟"的预期可以关掉了。
- **实测降幅（本轮从已落盘产物算出，非外推）**：
  6 路中位 **6.14 ms/圈**（`ideal_construction_20260904/` 38 跑）→
  3 路中位 **3.90 ms/圈**（`reload_fix_shortrun_20260905/` 6 跑，3.79–4.11）＝ **−36%**。
  交接 §3(e) 的回归 `ms/it = 0.560×并发 + 2.800` 在 c=3 预测 4.48，**比实测悲观 15%**
  ——那条回归主要拟合在 c≈4.2–6.0，往下外推偏保守。
  **以后引 3 路的数就引 3.90 这个实测值，别再用 4.48。**
  （回归在 c=1 的预测 3.36 和我的独占探针 3.35–3.45 吻合得很好，c=1 那端可以继续用。）
- **解质量风险**：无（同种子同圈数同解）。代价是批次总吞吐变慢。

### 设计 3（不推荐，仅备案）：去掉体积载重维

- **改哪里**：`kernel_proposals.py:1113-1136` / `:1461-1471`。
- **预期降幅**：每圈 −27.6%（3.451→2.500）。
- **风险：B 类，而且是拆真约束。** 0.1 节实测体积在总量上比载重紧一倍
  （13.26 vs 7.65 个满载单位），不被载重支配；实测去掉后内核最优从 2.8 亿掉到 2.13 亿，
  掉出来的解在精确账里会被判不可行，等于把工作量推给精确阶段。
  **写在这里只是给"多维载重值多少（≈0.95 ms/圈/维）"一个数，不建议施工。**

### 明确不建议做的两件

- **调 `max_reloads`**（再往下压到 4，或回到 49）：实测 ±2.6% 且同种子轨迹逐位相同，
  **它不在成本里**。同时建议把"49→8 省 17%"这条从交接里撤下或补原始测量。
- **单独合并 profile**：实测 0.0%。只在设计 1 里顺手做掉，不单独立项。

---

## 5. 诚实预期：全做完单跑几分钟，离 2 分钟还差什么

**先换掉一个过时的基线。** 交接引的"中位 7.75 min"是 `ideal_construction_20260904/` 那 38 个
**6 路并行、`max_reloads=49`、无自适应耐心**的跑。今天的代码已经不是那个状态了。
**更近的实测锚点是 `reload_fix_shortrun_20260905/` 的 6 个跑**
（3 路并行、`max_reloads=8`、第 1 轮预留 p75＋下限）：

| 臂/跑 | 墙钟 | 圈数 | ms/圈 |
|---|---:|---:|---:|
| MT-HGS run_01 | 288.3 s | 74,907 | 3.848 |
| MT-HGS run_02 | 226.2 s | 57,982 | 3.900 |
| MT-HGS run_03 | 322.6 s | 82,906 | 3.891 |
| MTC-HGS run_01 | 257.7 s | 63,519 | 4.057 |
| MTC-HGS run_02 | 490.5 s | 129,287 | 3.794 |
| MTC-HGS run_03 | 304.9 s | 74,250 | 4.106 |
| **中位** | **296.6 s ＝ 4.94 min** | **74,579** | **3.90** |

**从这里往下叠：**

| 步骤 | ms/圈 | 中位单跑 | 依据 |
|---|---:|---:|---|
| 今天（3 路并行，已落地的 reload/`max_reloads`） | 3.90 | **4.94 min** | 上表实测 |
| ＋ 确认轮自适应耐心（已落地，按交接省 ~16% 墙钟；本轮未独立复核） | 3.90 | **≈ 4.15 min** | 少的是圈数不是每圈 |
| ＋ 车型去重（设计 1，−8.2% 打在内核那 93% 上） | 3.60 | **≈ 3.83 min** | 本轮实测 |

**按这批的圈数区间外推**（3 路 ＋ 自适应耐心 ＋ 车型去重）：
58,000 圈 → **约 2.9 min**；74,579 圈（中位）→ **约 3.8 min**；129,287 圈 → **约 6.5 min**。

**离同刊母版（陈婉茹 2023，71 客户 6 车场，1.33–2.07 min）还差 1.8–3 倍，差在圈数，不在每圈。**

- 每圈这条路已经快走到头了：**独占单跑**（c=1，实测 3.35–3.45 ms/圈）再叠车型去重
  ≈ 3.10 ms/圈，74,579 圈 × 3.10 ms ＝ 231 s ＝ **3.85 min**。
  也就是说**把机器全让给它、把每圈能省的都省掉，仍然进不了 2 分钟**。
- 要落到 1.3–2.1 min（78–126 s），在 3.60 ms/圈下需要总圈数降到 **2.2 万–3.5 万**，
  比现在的中位 74,579 少 **2.1–3.4 倍**。

**而圈数这一侧，最容易砍的那一刀已经被数据否掉了。**
`CURRENT_PROJECT_CONTEXT.md:3` 记着：**第 1 轮改善的最大间隔是 16,333 圈**，
所以第 1 轮的 20,000 上限**压不下去**——压到 16,333 以下就会真的丢改善。
自适应耐心处理的是第 2 轮起（该行同时记着"第 2 轮起 8/10 轮零改善占墙钟 43%"），那一刀已经落地。
**剩下的 2 倍以上只能来自"换一种停止规则或换一种收敛路径"，那是用户拍板的范围，本报告不提方案。**

**一句话**：本题问的"每圈成本"这条线，实测能拿的是 **8–9%**（车型去重）；
不改代码的并行度那条已经在用（3 路，实测比 6 路快 36%）。
两条都吃满，单跑从今天的 **4.94 min** 到 **约 3.8 min**；
**剩下的 1.8–3 倍必须从圈数里出，而第 1 轮那 20,000 已被本项目自己的轨迹数据证明压不动。**

---

## 附：本轮对已有交接的五处口径更正

1. **"52 个点 × 20 种单车类型 × 4 份矩阵 × 每车 50 段行程槽位 × 多维载重"**里，
   真正进每圈热循环的只有**车辆类型数**（−8.2~9.0%）和**载重维数**（0.95 ms/圈/维，但两维都必要）；
   **profile 份数 0.0%**，**reload 槽位数 ≈0%**。
2. **"`max_reloads` 49→8 约省 17%/圈"复现不出**：实测两个口径夹住零（+0.1% / +2.6%），
   且 15000 圈同种子下内核最优逐位相同（41 个多余槽位从未被走到）。
   已查全仓库，那 17% 只出现在 `CURRENT_PROJECT_CONTEXT.md:3` 一句话里，
   引的批次 `reload_fix_shortrun_20260905/` 下**没有对应的 A/B 或 ms/圈 记录**；
   它是"3 路实测 3.6–3.8"对"并发回归外推 4.48"的跨批残差，同时被 reload 预留改动污染。
3. **"车队实测 20 辆"**是车队规模；48 个已落盘最优解里**真正载客的只有 5–6 辆**，
   14–15 条内核路线长期为空——这正是车辆类型数会变成成本项的原因。
4. **交接 §3(e) 的并发回归在 c=3 处不要用**：它预测 4.48 ms/圈，
   而 3 路的实测中位是 3.90（`reload_fix_shortrun_20260905/` 6 跑），偏保守 15%。
   c=1 那端（3.36）与本轮独占探针（3.35–3.45）吻合，可以继续用。
5. **交接 §5 第 1 条"降并行度可从 7.75 → 约 4.2 分钟"应关闭**：并行度 ≤3、去 `nice`
   已经在 `run_ideal_construction_batch.sh:2,10` 落地，实测 3 路中位单跑已经是 **4.94 min**。
   后续的基线请用 4.94 min，不要再用 7.75 min。
