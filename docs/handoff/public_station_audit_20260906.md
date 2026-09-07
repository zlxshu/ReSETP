# 公共充电站到底是不是摆设 —— 只读核查

核查对象：私有算例 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`，已跑结果
`solver/reports/grid2x2_v2_20260905/`（80 次）与 `solver/reports/carbon_price_sweep_v2_20260906/`（46 次），共 126 次运行。
全部为只读读取与秒级脚本，未改仓库、未跑路径搜索。

---

## 一句话结论

公共桩**不是摆设**：97 个站真实存在、被求解器成组枚举、被成本比较过，并且在 126 次运行里真的被用过 8 次。
但它在经济上几乎必输——**同一时刻，公共桩电价恒等于车场电价 + 0.4 元/kWh 服务费，碳因子完全相同**，
而且代码里公共桩**只在"电不够、开不到下一个点"时才被插入**，不存在"因为更便宜/更干净所以去公共桩补一口"的动作。
所以论文图上"充电全在车场"是真实结果，不是画图漏画。

---

## 1. 算例确实设了公共桩，而且设得很"齐"

节点构成（`data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/nodes.csv`，共 149 行数据行）：

| 类型 | 个数 |
|---|---|
| depot（车场） | 2 |
| customer（客户） | 50 |
| station（公共充电站） | 97 |

与论文正文一致：`docs/paper_v2/paper_main.tex:723` 与 `:868` 都写"50 个客户、2 个车场和 97 个公共充电站"。**数字没问题。**

参数（`solver/src/setp_solver/china81.py:891-905` 建 station 节点，取自
`data/ChinaInstances/china81_final_suite_v2_20260815/facilities.csv` 的 beijing 行）：

- 功率 `station_power_kw = 60.0` kW，枪数 `station_gun_count = 1`
- 时间窗 `ready_time = CHINA81_HORIZON_START_SECOND`、`due_time = CHINA81_HORIZON_END_SECOND`
  → **全天开放，没有营业时段限制**
- 车场同样 60 kW（`china81.py:883` 取 `depot_charge_power_kw`，`china81.py:1274` 默认 60.0），
  充电曲线三者同一条 `M17_FAST_SHAPE_SCALED_60KW_PWL`（`china81.py:1285-1300`）
  → **公共桩没有任何功率优势**
- 本批运行里车场充电桩容量被设成 `"active_concurrency_limit": "UNBOUNDED"`
  （`solver/scripts/run_problem_hgs_private_technical.py:960-968`）；
  公共桩则是 `capacity_mode = "finite_instance"`、并发上限 = 枪数 = 1
  （`solver/src/setp_solver/china81.py:643-663`，并发确实被强制，见
  `solver/src/setp_solver/check.py:632`、`solver/src/setp_solver/search/dynamic_multitrip_schedule.py:2418`）
  → **车场不排队、公共桩单枪排队；这是公共桩的额外劣势，不可能是它被选中的理由**

位置分布（用 `.../directed_matrices/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/ev/road_distance_m.csv` 实算）：

- 客户 → 最近公共桩路网距离：最小 0.31 km，四分位 1.66 km，**中位 2.89 km**，上四分位 5.38 km，最大 34.71 km
- 车场 `D_OSM_WAY_1071205721` → 最近公共桩 4.52 km；车场 `D_OSM_WAY_1003511503` → 28.06 km
- 客户之间中位路网距离 20.47 km
- 随机抽 3000 对客户，在两客户之间插一个最优公共桩的**额外行驶时间中位数只有 2.0 分钟**（p10 0.6 分钟，p90 4.3 分钟）

→ **绕行成本很小，几何上不是障碍。**

电价与碳（`data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv`，
北京 2025-02 全月 1344 行逐条核过）：

- `public_energy_cny_per_kwh − depot_energy_cny_per_kwh` 的取值集合 = **{0.0}**（每一格都相等）
- `public_service_fee_cny_per_kwh` 取值集合 = **{0.4}**（恒定）
- 于是 `public_total = depot_energy + 0.4`，**任何时刻公共桩每度都贵 0.4 元**
- 碳因子 `carbon_factor_kgco2e_per_kwh` 是**按城市按时段**给的，车场和公共桩**共用同一列**
  → 同一时刻在公共桩充电，碳排放**一点也不比车场低**

2025-02-01 北京分时（depot / public 元每度）：

| 时段 | 类别 | 车场 | 公共桩 |
|---|---|---|---|
| 00:00–07:00 | 谷 | 0.56329 | 0.96329 |
| 07:00–10:00 | 平 | 0.83644 | 1.23644 |
| 10:00–13:00 | 峰 | 1.14862 | 1.54862 |
| 13:00–17:00 | 平 | 0.83644 | 1.23644 |
| 17:00–22:00 | 峰 | 1.14862 | 1.54862 |
| 22:00–23:00 | 平 | 0.83644 | 1.23644 |
| 23:00–24:00 | 谷 | 0.56329 | 0.96329 |

碳强度（kg/kWh，逐小时）：07:00 最脏 0.56890，**13:00 最干净 0.11210**，12:00 0.11670，15:00 0.12100，14:00 0.13220。

价格代码出处：`solver/src/setp_solver/cost.py:1382-1408` —— 车场节点按 `depot_energy_cny_per_kwh` 结算，
其他（公共桩）按 `public_total_cny_per_kwh` 结算，逐半小时格切分。同规则也在
`solver/src/setp_solver/charge_timing.py:74-91`。

---

## 2. 求解器确实会用公共桩，但只在两个很窄的口子上

### (a) 路径搜索内核完全不认公共桩

`solver/src/setp_solver/algorithms/problem_hgs/charging.py:371` 的注释写明
"charging and public-station detours only add time"。内核用的是每班次的电价代理
（metadata 里的 `route_engine_wiring/shift_aware_ev_proxy`，只有 `electricity_cny_per_kwh` = 车场电价 0.56329/1.14862），
**内核不会主动往路线里插公共桩**。公共桩只在充电修复层出现。

### (b) 候选模式：`fallback` = 只走车场；`parallel` = 额外造"公共桩路径"

`solver/src/setp_solver/algorithms/resetp_alns/support/charging.py:65-66`

```
PUBLIC_STATION_CANDIDATE_MODES = frozenset({"fallback", "parallel"})
DEFAULT_PUBLIC_STATION_CANDIDATE_MODE = "fallback"
```

- `fallback`（默认）：`support/charging.py:892-895` 直接 return，**只有车场路径**，一个公共桩候选都不造。
- `parallel`：继续往下，对 97 个站逐个筛，造出"公共桩路径"候选，和车场路径一起比成本。

**本批实验用的是 `parallel`**——出处是源码硬编码，
`solver/scripts/run_problem_hgs_private_technical.py:333: public_station_candidate_mode="parallel"`，
在 `_policy()` 里，两条臂共用，没有开关。

> 说明：`solver/reports/grid2x2_v2_20260905/beijing/P=0.2/*/run_01/metadata.json` **里并没有记录
> `public_station_candidate_mode` 这个字段**（我 grep 过，0 命中）。可佐证的间接证据是
> metadata 里 `charging_station_pruning/totals/enumerated` 非零（只有走过 `fallback` 早退之后才会累加）。
> 两条臂的 `charge_timing_policy` 差别在 metadata 的 `mechanism_closure/effective_charge_timing_policy`：
> MT-HGS = `asap`（joblist 里带 `--mechanism-off charge_timing`），MTC-HGS = `cost_plus_carbon`。

### (c) 关键限制一：插桩只由"开不到"触发，不由"更便宜"触发

`support/charging.py:1109-1187`：循环里 `should_insert = failure_offset is not None`，
`failure_offset` 来自 `_first_direct_infeasible_offset(...)`——**电量够就绝不插桩**。
没有任何"因为电价/碳更低，去公共桩补一口"的算子。

而车场预充在默认（`fallback`）路径下是 `_depot_precharge_action(..., target_charge_level_kwh=None)`
→ `support/charging.py:1466-1476` 取 `route_need`（整趟所需电量）。EV 初始电量
`initial_ev_battery_kwh = 0.0`、电池 `B_battery_kwh = 77.28`（`china81.py:1262-1263`）。
所以只要整趟能耗 ≤ 77.28 kWh，车场一口就充满整趟，**永远不会触发"开不到"**，公共桩自然一次都用不上。

### (d) 关键限制二：`parallel` 的公共桩路径是"整趟二选一"，不是"顺路补一口"

`support/charging.py:895-1040` 的构造是：
`launch_target = max(initial_battery, 从车场开到该站所需电量)`，车场只充这么多；
到站后 `coverage_targets = future_targets`（**剩下全程**），
末尾还有 fail-closed 检查 `if station_insertions < len(forced_station_path): raise ValueError("forced public-station path was not fully used")`（`support/charging.py:1211-1212`）。
源码注释自己写明："A second public insertion therefore cannot occur"。

也就是说，模型里**唯一能表达的公共桩动作 = 一趟里最多一个公共桩，且这个站要承担该趟剩余的全部电量**，
车场只留"够开到这个站"的最小电量。**没有"车场充大部分 + 客户附近公共桩小补一口"这种形态。**

### (e) 与"depot-only"开关不要混淆

另有一个 `DYNAMIC_DEPOT_ONLY_CANDIDATE_MODE`（`problem_hgs/charging.py:70`，
在 `:1730` 和 `:1826` 抛错禁止公共桩），那是**动态插入算子**用的。
本批运行 `dynamic_insertion_operator/enabled = False`，**没启用**。

---

## 3. 已跑的解：8 次公共桩会话，占 0.23% 的充电电量

扫 126 个 `best_solution.json`（grid2x2_v2 80 个 + carbon_price_sweep_v2 46 个），
按 `nodes.csv` 的 node_type 归类每一次 `charging_sessions`：

| 充电地点 | 会话数 | 电量 kWh |
|---|---|---|
| 车场 depot | 1230 | 27 602.83 |
| 公共桩 station | **8** | **62.63** |

→ 公共桩占会话数 **0.65%**，占电量 **0.226%**。

同一批 metadata 的候选枚举计数（`charging_station_pruning/totals`）：
枚举 23 425 500 次、可达 3 214 558 次、成本评价 9 677 028 次。
**所以不是"没生成候选"，是生成了、比过价、然后基本全被淘汰。**

八次公共桩会话分布：

| 报告 | 政策 | 碳价 | 站点 | 开始时刻 | kWh |
|---|---|---|---|---|---|
| `grid2x2_v2_20260905/midday/P=1.0/MT-HGS/run_01` | asap | 1.0 | S_OSM_NODE_4464442989 | 13:15 | 8.812 |
| `carbon_price_sweep_v2_20260906/P=1.7/run_02` | cost_plus_carbon | 1.7 | S_OSM_WAY_1348314458 | 14:23 | 7.688 |
| 同上 `P=1.8/run_02`、`P=1.9/run_01`、`P=1.9/run_03`、`P=2.0/run_01`、`P=2.0/run_02`、`P=2.0/run_03` | cost_plus_carbon | 1.8–2.0 | 同一个站 | 14:23 | 7.688 |

两点必须说清：

1. **那 1 次 `midday` 的运行绑的不是默认日历**：它的 `bundle_source_paths/tariff_carbon_calendar` =
   `data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904/...`（把 13:00–17:00 改成谷段 0.56329）。
   其余 7 次绑的是默认 `china81_runtime_parameter_authority_v4_20260723`。
2. 这 7 次其实是**同一个解在不同碳价/种子下重复出现**（同站、同时刻、同电量），不是 7 个独立证据。

**为什么"没用上"——三选项里的答案是"候选造出来了、被成本淘汰"，不是没造、也不是几何不可行。**
证据是上面的枚举/可达计数（每次修复平均枚举 97 个站、可达约 13 个）。

### 拿观测到的那一次做离线核算（碳价 2.0 那条）

该车（`EV_D_OSM_WAY_1071205721_5`）的 trip_clock 与充电会话：

- T1 08:23 出发、10:32 回场；T2 **13:02 出发**、15:50 回场
- 车场会话：T1 前 06:00 充 15.136 kWh；T2 前 **13:00 充 2.175 kWh**（只 2.18 分钟）
- 公共桩会话：T2 途中 **14:23 在 S_OSM_WAY_1348314458 充 7.688 kWh**

这正是 (d) 描述的"整趟二选一"形态：车场只充到够开到站，剩下全在站里补。

单位成本对比（默认日历）：
- 车场 13:00（平段）：0.83644 元/kWh，碳 0.11210 kg/kWh
- 公共桩 14:23（平段）：1.23644 元/kWh，碳 0.13220 kg/kWh
- 差额 = **0.4 + P × 0.0201 元/kWh，对任何碳价 P ≥ 0 都为正**

即：把这 7.688 kWh 挪回 13:00 的车场那一口，碳价 2.0 下能省 7.688 × (0.4 + 0.0402) ≈ **3.38 元**。
所以**这 8 次公共桩会话不构成"公共桩划算"的证据**。

（未做的一步：我没有离线重跑 `repair_route_charging_candidates` 去确认这条 trip 的纯车场候选当时确实可行，
因此不对"为什么它还是被留下来"下因果结论。廉价验证办法 = 对该 route 单独调一次该函数，
看 `depot_fallback` 分支是否 raise。）

---

## 4. "有可用时段即充电"能不能也在公共桩充？

**能，而且已经在做。** `asap` 只决定**什么时候开始充**（`charge_timing.py:746`：
`if policy == "asap" ... return earliest`），不决定**在哪充**；在哪充由
`public_station_candidate_mode` 决定，两条臂都是 `parallel`。
证据就是上表那次 `midday/P=1.0/MT-HGS/run_01` —— 它是 `asap` 臂，照样用了公共桩。

真正禁止公共桩的是另一个开关（`DYNAMIC_DEPOT_ONLY_CANDIDATE_MODE`，动态插入算子专用），本批没启用。

---

## 5. 判断：不是摆设，是"经济上不划算 + 建模上只能整趟替换"

**不是摆设**：97 个站有真实 OSM 身份、有功率、有全天可用时段、进入了候选枚举、被成本比较、并且真的被选中过 8 次。

**没用起来的三层原因，按重要性排：**

1. **价格结构决定它同一时刻永远贵 0.4 元/kWh，碳还完全一样。**
   公共桩要赢，只能靠"在比车场那口更干净/更便宜的时段充"。条件是
   `p_pub(t') − p_depot(t) < P · (γ(t) − γ(t'))`。

   拿本批 126 个解的**全部 1230 次车场充电**（27 602.8 kWh）实算这个上限：
   - 实际充电间接碳排 **8486.6 kg**；
   - 若每一度都挪到当日碳强度最低的时段，碳排 **3094.3 kg** → **机制作用空间上限 = 5392.3 kg，占 63.5%**；
   - 但同样这批电量若全挪到"中午最干净时段的公共桩"，电费从 21 690.1 元涨到 31 850.1 元（**+10 160 元**）；
   - → **整体切换的盈亏平衡碳价 = 10160 / 5392.3 ≈ 1.88 元/kg**。

   论文主基准碳价 **0.2 元/kg**，离这个门槛差约 **9 倍**——在主基准下公共桩不可能赢。
   碳价扫到 **1.7–2.0** 才零星出现公共桩，与这个 1.88 的门槛高度吻合，是很强的内部一致性证据。
2. **插桩只由"开不到"触发。** 车场默认一口把整趟充满（初始电量 0、电池 77.28 kWh），
   本算例每趟能耗都远低于电池容量，所以"开不到"几乎不发生，公共桩连出场机会都没有
   （这一条与 `paper_main.tex:696` 正文写的"电量不足以完成一趟时经允许访问的公共充电站补电"是**一致的**，
   论文没有说错，只是读者会以为公共桩是常规选项）。
3. **`parallel` 造出的公共桩路径是"整趟二选一"**：车场只充"够开到站"，站里补完剩余全程。
   现实中最合理的用法——"车场充大头 + 中午在客户附近顺手补一口进最干净时段"——**模型里表达不出来**。

**几何不是原因**：客户到最近站中位 2.89 km，绕行中位仅 2 分钟。
**功率不是原因**：两边都是 60 kW、同一条充电曲线。
**营业时段/排队不是原因**：站全天开放；本批车场充电桩并发无上限，公共桩每站 1 枪且并发被强制——
这只会让公共桩更不利，不会解释"为什么没用它"。

### 想让"即充"和"择时"都能真用公共桩，要改哪里、改多大

按改动量从小到大：

| 改法 | 动哪里 | 改动量 | 预期效果 |
|---|---|---|---|
| A. 降服务费 / 让服务费分时 | 只改日历 `public_service_fee_cny_per_kwh`（`tariff_carbon_hourly_calendar.csv`），代码零改 | 最小，一列数据 | 服务费降到 0.4 → 0.1 以下，或中午时段减免，公共桩立刻能在中午低碳段赢。但**参数得有出处**，不能拍脑袋 |
| B. 允许"部分补电"而不是整趟替换 | `support/charging.py:895-1040` 的 `launch_target` / `coverage_targets` 构造，加一种"车场按 `route_need` 充满 + 站里补 Δ"的候选 | 中等，一个函数 + 候选去重/支配剪枝要跟着改 | 让"中午顺路补一口"可表达。但只要服务费还是 0.4，碳价 < 0.88 元/kg 时仍不会被选 |
| C. 让插桩由成本/碳触发，而不只由"开不到"触发 | `support/charging.py:1119-1125` 的 `should_insert` 判据，要新增经济性触发；候选数会爆炸，必须配剪枝 | 大，等于重做修复层的邻域 | 这是"择时充电"机制真正能用到公共桩的前提 |
| D. 给公共桩差异化功率（快充 120–150 kW）或给车场加桩位约束 | `facilities.csv` + `china81.py:891-905`，以及车场 `active_concurrency_limit` | 小到中 | 制造"公共桩换时间"的真实取舍。目前两边都是 60 kW、车场不排队，公共桩没有任何非价格优势 |

**关于"中午在客户附近公共桩充电能否进入碳强度最低时段"——这里有增量价值，但要说准。**

车场充电窗口口径已核实：本批用的是 `same_day_predeparture`
（`solver/scripts/run_problem_hgs_private_technical.py:1059` → `DEFAULT_DEPOT_CHARGE_WINDOW_MODE`，
定义在 `solver/src/setp_solver/search/multitrip_schedule.py:80`；
只有加 `--first-trip-prev-night` / `--first-trip-window` 才会翻成 `full_gap`，两份 joblist 都**没有**这两个参数，116 行 0 命中）。
其语义见 `multitrip_schedule.py:798-799`：窗口 = **[当日 00:00, 出发时刻 − 充电占用时长]**。

所以：

- 车场**能**够到 13:00 的最干净时段，**但只对那些出发时刻在 13:00 之后的趟**；
- 对**上午出发的趟**（本批实测：06:00 那一口 6044 kWh、00:00 那一口 2063 kWh、05:00 1596 kWh、09:00 2887 kWh，
  合计约 46% 的充电电量落在 00:00–10:00），车场**只能**在当日 00:00 到出发前之间充，
  而默认日历里这段恰恰是全天**最脏**的（γ 0.545–0.569 kg/kWh，07:00 达峰值 0.56890），
  **车场无论如何够不到 13:00 那 0.11210**；
- 这时候，中途在客户附近的公共桩补电，是这一趟唯一能进最干净时段的通道。
  单位换算：车场 06:00 谷段（0.56329 元、γ 0.56570）换成公共桩 13:00 平段（1.23644 元、γ 0.11210），
  贵 0.67315 元/kWh、少排 0.45360 kg/kWh → **盈亏平衡碳价 ≈ 1.48 元/kg**，
  正好落在观测到公共桩开始出现的 1.7 附近下方。

**这才是值得写进论文的机制故事**（"晨发趟被锁死在最脏时段，公共桩是它唯一的低碳通道"），
但要让它真的跑出来，必须先做上面的 B + C——现在模型只能"整趟二选一"，
且插桩只由"开不到"触发，这条通道在算法里根本没有开口。
另外主基准碳价 0.2 元/kg 离 1.48/1.88 的门槛差 7–9 倍，
**在主基准下无论怎么改算法都不会有可见效果**，要出效应必须同时动服务费口径（改法 A）或碳价设定。

---

## 附：核查过程中的两条口径说明

- 126 个 `metadata.json` 与 126 个 `best_solution.json` 一一对应，无缺失；
  `solver/reports/grid2x2_v2_20260905/_partial_killed_2202/` 下的目录名不是 `run_*`，未被计入。
  （中途一次扫描曾报 125 个和 1 个异常记录，重复三次均无法复现，判为外置硬盘一次瞬时读取异常；
  以本文档中可复现的 126/126、8 次公共桩会话为准。）
- metadata 里的 `route_engine_wiring/shift_aware_ev_proxy/*/actual_gco2_per_kwh`（643.3 / 179.9 g）
  是**内核每班次的代理取值**，不等于日历原始行；本文档所有电价与碳数字均直接取自
  运行各自绑定的 `tariff_carbon_hourly_calendar.csv` 原始行。
