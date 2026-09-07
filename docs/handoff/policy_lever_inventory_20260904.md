# 政策杠杆可行性清点（只读调查，2026-09-04）

仓库根：`/Volumes/移动硬盘（512G）/ReSETP`
正式算例：`cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`（北京，两车场）
本报告未修改任何文件、未运行求解器。

---

## 先决事实：正式入口不走 `load_china81_bundle`

这条决定了第 2、4、8 题的答案，先单列。

`run_problem_hgs_private_technical.py` 的 `_build_context`（第 224 行）对本算例走的是
`_build_saved_suite_context`（第 246–257 行 → 定义在第 869 行），再往下是
`_load_v3_suite_bundle`，**不调用 `china81.py` 的 `load_china81_bundle`**。

```
solver/scripts/run_problem_hgs_private_technical.py:246
    if instance_id == DEPOT_SEARCH_INSTANCE_ID:
...
solver/scripts/run_problem_hgs_private_technical.py:252
        return _build_saved_suite_context(
            repo, instance_id,
            package_root=repo / "data/ChinaInstances/china81_final_suite_v2_20260815",
```

日历由这条私有路径**直接**读，路径写死：

```
solver/scripts/run_problem_hgs_private_technical.py:570
    runtime_root = repo / "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
solver/scripts/run_problem_hgs_private_technical.py:571
    time_profile = _load_time_profile(
        resolve_calendar_path(runtime_root),
        cities=cities, date="2025-02-12", require_explicit_mapping=True,
    )
```

它复用 `china81.py` 的 `_load_time_profile` 校验函数（第 1009 行），但不复用
`load_china81_bundle` 的参数化入口。所以：

- 换日历的最小改动落在 **runner 第 570 行**，不是 `china81.py` 的 `runtime_parameter_authority` 形参。
- `china81.py:338` 的 `depot_time_windows` 形参对本算例是**够不着的死参数**（见第 4 题）。

---

## 1. 碳价：`--carbon-price` 的接线

**结论：接通了，代理目标和精确账都吃到，且没有额外的碳权重混淆。**

命令行到 bundle：

```
solver/scripts/run_problem_hgs_private_technical.py:1288-1292
    parser.add_argument("--carbon-price", type=float,
        default=CHINA81_CARBON_PRICE_CNY_PER_KG, ...)
solver/scripts/run_problem_hgs_private_technical.py:1482-1483   # 有限、非负校验
solver/scripts/run_problem_hgs_private_technical.py:1617-1622
    if args.carbon_price != CHINA81_CARBON_PRICE_CNY_PER_KG:
        bundle = replace(bundle,
            prices=replace(bundle.prices, carbon_price=args.carbon_price),
            carbon_price_cny_per_kg=args.carbon_price)
        context = replace(context, bundle=bundle)
```

**精确账**（受保护文件 `cost.py`，只读证据）：

```
solver/src/setp_solver/cost.py:230
    cost_carbon = 0.0 if math.isinf(quota) else (e_total - quota) * _price(prices, "carbon_price")
```

**择时打分器**（`charge_timing.py`，三处独立路径都用同一个价）：

```
solver/src/setp_solver/charge_timing.py:486-499   # ChargeTimingContext.objective_value
    carbon_price = _price(self.prices, "carbon_price")
    if policy == "cost_min" or carbon_price == 0.0: ...
    else: value = cost + carbon_price * emissions
solver/src/setp_solver/charge_timing.py:550,567   # select_start 缓存路径
solver/src/setp_solver/charge_timing.py:714,723,782,810  # 无缓存 fallback 路径
```

**路线搜索的代理目标**（kernel_native 模式下的 proxy，三处）：

```
solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:1012-1019  # EV 单位里程代理
    float(row["depot_energy_cny_per_kwh"]) + (float(row["actual_gco2_per_kwh"])/1000.0
        * float(bundle.prices.carbon_price))
solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:1330-1333  # 班次充电槽代理单价
solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:1386-1389  # CV 推进代理
    propulsion = fuel_liters * (diesel_price_for_route(...) + float(prices.diesel_ef)*float(prices.carbon_price))
```

**无碳权重混淆**：`search/evaluation.py:194-203` 的 `_prices_with_carbon_weight` 会把
`carbon_price` 乘一个 `carbon_weight`，但该权重在私有入口写死为 1.0，没有命令行开关：

```
solver/scripts/run_problem_hgs_private_technical.py:166
        carbon_weight=1.0,
solver/src/setp_solver/search/evaluation.py:52
    carbon_weight: float = 1.0
```

**一个口径提醒（非缺陷，但影响解释）**：kernel 代理选充电槽时是先按碳排序、
再按电价排序，与碳价大小无关：

```
solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:1313-1319
        row = min(available, key=lambda item: (
            float(item["actual_gco2_per_kwh"]),
            float(item["depot_energy_cny_per_kwh"]),
            -float(item["horizon_second_start"]),))
```
即代理层的"选哪个槽"对碳价不敏感，碳价只改代理的单位成本数值；真正按碳价择时发生在
`charge_timing.py` 的精确修复阶段。

**改动需求：无。** 该轴已跑完（`private_axes_formal_v2_20260904/carbon`，
11 档 0 / 0.05 / 0.075 / 0.10 / 0.15 / 0.20 / 0.30 / 0.60 / 1.5 / 2.0 / 5.0，每档 3 次，33/33 收口）。

该批的 README（`solver/reports/private_axes_formal_v2_20260904/README.md`）已记结论：
碳价 0–0.60 元/kg 车队稳定在 2 油 3 电（排放 187–198 kg）；1.5 元/kg 转 1 油 5 电
（125.6 kg，−35%）；2.0 元/kg 起转纯电 6 辆（87.7→82.5 kg，−56%）。
翻转阈值在 0.60–1.5 与 1.5–2.0 之间。总成本随碳价单调升 2582.98→3175.37。
**现行碳价 0.075 时碳成本只占总成本 0.56%——这就是"碳价这根杠杆在现实档位上几乎不动"
的定量证据，也是为什么需要找别的杠杆。**

---

## 2. 电价时段划分（最关键）

**结论：能换。做法是造一份反事实日历 CSV 放进仓库，再改 runner 第 570 行一个字符串常量；
不碰三个受保护文件。校验器不检查 `tariff_period`，也不检查任何电价数值，所以"保留北京四档价格
数值、把谷段挪到 12:00–15:00"这种排列是过得去的。**

### 会拦你的校验（全部在 `china81.py:_load_time_profile`，第 1009–1210 行）

| 行号 | 校验内容 | 造反事实日历时怎么过 |
|---|---|---|
| 1016-1019 | 按 `date` + `city`（小写）筛行 | 保持 `date=2025-02-12`、`city=beijing` |
| 1030-1035 | 每城当日必须恰好 48 个唯一 `hourly_calendar_row`（1..48） | 原样保留 |
| 1036-1041 | `city` 必须在 `_CITY_RUNTIME_MAPPING`（第 148 行）注册 | 保持 beijing |
| 1043-1051 | `minute_of_day == (slot-1)*30` | 原样保留 |
| 1052-1055 | `region` 必须等于映射值（jjj） | 原样保留 |
| 1056-1063 | `carbon_source_column` 必须等于 `Beijing` | 原样保留 |
| 1065-1072 | `price_area_id` 必须等于 `beijing`（`require_explicit_mapping=True`） | 原样保留 |
| 1073-1081 | `diesel_zone` 必须等于 `beijing` | 原样保留 |
| 1082-1089 | `joint_key_status` 必须是 `PASS_CITY_DATE_SLOT_PARAMETER_IDENTITY` | 原样保留 |
| 1090-1097 | `diesel_parameter_status` 必须是 `APPROVED_CHINA_E3_FORMAL_RELEASE_001` | 原样保留 |
| 1098-1111 | 五个数值字段有限且 ≥0 | 满足 |
| 1112-1120 | `public_energy + public_service == public_total` | 排列/缩放时三列要一起动 |
| 1122-1144 | 同一小时的两个半小时槽碳强度必须完全相等（abs_tol 1e-12） | 碳列按小时成对 |
| 1204-1207 | 行数必须等于 `48 * 城市数` | 原样保留 |

另有一处在 `_diesel_price_map_from_profile`（第 1260–1293 行）：`diesel_price_cny_per_l`
必须与写死的 `_DIESEL_PRICE_CNY_PER_L_BY_CITY`（字典第 136 行，北京 7.48 在第 137 行）逐位相等，
所以柴油列不能动。

`_city_runtime_binding_from_profile`（第 1330–1357 行）再核一遍 region /
price_area_id / carbon_source_column / diesel_zone 全天恒定且与映射一致。

### 不会拦你的（这是关键发现）

- **`tariff_period` 从头到尾没有被校验**。它只在第 1174 行原样搬进 profile 字典，
  之后没有任何消费者按它算钱：
  ```
  solver/src/setp_solver/china81.py:1174
                  "tariff_period": row["tariff_period"],
  ```
  真正决定电费的是 `depot_energy_cny_per_kwh` / `public_total_cny_per_kwh` 两列
  （消费点：`cost.py:1384-1386`、`charge_timing.py:85-90`、
  `schedule_oracle.py:167-169`、`kernel_proposals.py:1012,1320`）。
- **没有任何"电价必须来自某张注册价表"的交叉校验**。`_china_prices`
  （`china81.py:1215-1240`）只是把 profile 的 depot / public 两列取平均塞进
  `PriceParameters`，不比对任何权威值。
- **运行时不校验日历文件哈希**。`china81_runtime_parameter_authority_v4_20260723/`
  下虽有 `artifact_hashes.json`，但 `grep -rn "sha256\|artifact_hashes" solver/src`
  **零命中**（排除 `__pycache__`），runner 里也没有。
- **受保护文件 `check.py` 对日历零校验**。
  `grep -n "tariff_period\|depot_energy\|public_total\|valley\|peak\|flat\|time_profile"
  solver/src/setp_solver/check.py` **零命中**——它不检查时段标签、不检查
  "谷≤平≤峰"这类价序、也不碰 time_profile。
  `china81_completion.py` 只在第 85 行复用同一个 `_load_time_profile`
  （多日历场景），没有额外约束。
  **⇒ 排列过的日历不会在求解时被任何校验器打回。**

### 最小改动方案

1. 新建目录（必须在仓库根下，因为 `china81.py:374/381` 有
   `parameter_root.relative_to(root)`，仓库外路径会抛 `ValueError`），例如
   `data/ChinaInstances/china81_counterfactual_calendar_v1_20260904/`，
   里面放一份 `tariff_carbon_hourly_calendar.csv`（文件名固定，见
   `field_rename_compat.py:13,21-30`）。
   反事实内容只改 `depot_energy_cny_per_kwh` / `public_energy` / `public_service` /
   `public_total` 四列在 48 个槽之间的排列（`tariff_period` 标签跟着改，纯记录用），
   其余列逐字节照抄北京当日。
2. 改 `solver/scripts/run_problem_hgs_private_technical.py:570` 的路径常量；
   更稳妥是加一个 `--tariff-calendar-authority` 参数，默认值即现路径，
   把第 570 行改成读该参数。

**涉及文件**：新增 1 个数据目录 + `run_problem_hgs_private_technical.py` 1 处。
**估计行数**：写死路径改法 1 行；加命令行参数改法约 8–12 行
（`add_argument` 一段 + `_build_context` / `_build_saved_suite_context` /
`_load_v3_suite_bundle` 三层透传一个关键字参数）。
**受保护文件**：`cost.py` / `check.py` / `search/evaluation.py` **完全不碰**——
它们只从 `bundle.time_profile` 的行里读列值，不关心行从哪来。

### 附：北京当日实际时段（证据，来自日历本身）

`data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv`，
city=beijing，date=2025-02-12：

- 谷 `valley` 00:00–07:00 与 23:00–24:00，`depot_energy` = 0.56328575
- 平 `flat` 07:00–10:00、13:00–17:00、22:00–23:00，`depot_energy` = 0.83644275
- 峰 `peak` 10:00–13:00、17:00–22:00，`depot_energy` = 1.14862175
- 碳强度最高在谷段（04:00 前 0.60–0.6439，00:30 处 0.6433），
  最低在 12:00–15:00（0.1541–0.1826）——正是峰/平电价区。

论文 4.4 节"三者对不上"的说法在数据上成立。

---

## 3. 电价整体缩放 / 折扣

**结论：没有现成参数。命令行 31 个开关里没有任何一个碰电价
（完整清单见 `run_problem_hgs_private_technical.py` 第 1270–1474 行：
`--data-repo-root --instance-id --enterprise-id --initial-solution
--enterprise-init-constructor --carbon-price --ev-cap-override --fleet-mix-override
--recharge-mode --depot-curve --convergence-csv --education-depth-limit
--population-mode --objective-mode --arm --fleet-parameter-class
--depot-charging-scenario --first-trip-prev-night --charge-timing-policy --lazy-exact
--ev-departure-gap-proxy --ev-reload-gap-proxy --confirming-round --search-mode
--no-ev-charge-time-proxy --frvcpy-charging --depot-assignment-operator
--dynamic-insertion-operator --mechanism-off --init-witness
--include-charging-candidates --charging-prescreen`）。**

`PriceParameters` 里确实有 `depot_electricity_price` / `station_electricity_price`
（`prices.py`，`depot_electricity_price` 字段定义在 `PriceParameters` 内，
由 `_china_prices` 在 `china81.py:1274-1276` 赋值），但那是**全天平均值**，
只作兼容字段；逐槽计费走的是 profile 行里的 `depot_energy_cny_per_kwh`
（`cost.py:1384-1386`、`charge_timing.py:85-90`）。改这两个标量**不会**改充电费。

**最小改动（两条路，推荐第一条）：**

- **A（零代码，推荐）**：与第 2 题同一条通道——造一份把
  `depot_energy_cny_per_kwh` 整体乘 k（或对某几个槽打折）的日历 CSV，
  `public_energy` / `public_service` / `public_total` 三列同步改并保持
  `energy + service == total`（`china81.py:1112-1120`）。
  改动 = 新增 1 个数据目录 + runner 第 570 行 1 行。**不碰受保护文件。**
- **B（加代码）**：在 runner 加 `--electricity-scale`，在
  `_load_time_profile` 返回后、`_china_prices` 之前，对 profile 的四个价格列
  乘系数。落点是 `run_problem_hgs_private_technical.py:571-590` 之间，
  约 12–15 行。**同样不碰受保护文件**（受保护文件只读列值）。
  B 的好处是一次跑批可扫多个系数而不用生成多份 CSV。

---

## 4. 企业作业时间窗

**结论：`china81.py:338` 的 `depot_time_windows` 形参对本算例够不着——正式入口不调
`load_china81_bundle`（见"先决事实"）。本算例的作业时间窗来自算例包里的
`shift_contract.json`，值是 08:00–19:00，没有命令行开关。改它不会连带改客户时间窗，
两者在不同文件里，但改早了/晚了会让客户窗落到班次外，需要同步。**

### 时间窗从哪来

```
solver/scripts/run_problem_hgs_private_technical.py:703-712
    shift_contract = json.loads((saved_root / "shift_contract.json").read_text(...))
    shift_windows = {shift_id: (float(row["start_minute"]) * 60.0,
                                float(row["end_minute"]) * 60.0)
                     for shift_id, row in shift_contract["shifts"].items()}
```
`saved_root` = `data/ChinaInstances/china81_final_suite_v2_20260815/instances/cn-jjj-50c-01-DEPOTSEARCH-d996f755bd/`

该文件实测内容：
- `attendance`: `start_minute=480.0`, `end_minute=1140.0` → 08:00–19:00（**仅记录，不进模型，见下**）
- `shifts.AM`: 480–660（08:00–11:00）
- `shifts.PM`: 780–1140（13:00–19:00）
- `lunch`: 660–780（11:00–13:00），`return_to_depot_required=true`,
  `loading_and_charging_sequential=true`
- `vehicle_volume_capacity_m3=7.2`, `vehicle_payload_capacity_kg=1735.0`

**只有 `shifts` 两项和 `vehicle_volume_capacity_m3` 进求解器**。全仓库 grep
`attendance` / `lunch` / `loading_hours_per_m3` / `order_allocation` /
`vehicle_payload_capacity_kg` 在 `solver/src` 与 `solver/scripts` 下**零命中**
（只有 `run_problem_hgs_private_technical.py:712` 读 `shifts`、`:862` 读
`vehicle_volume_capacity_m3`）。

**所以"08:00–19:00"这个说法要修正**：`attendance` 480–1140 只是文档记录，不进模型。
真正约束求解器的是两段班次 **08:00–11:00 与 13:00–19:00**，中间 11:00–13:00
对求解器而言是"没有班次"的空档（`lunch` 里那些 `return_to_depot_required` /
`loading_and_charging_sequential` 规则也没接线）。
（第 9 题里午间那几次充电落在什么位置、由什么决定，见该节的说明；这里不做因果断言。）
`shift_windows` 进 `RebuiltRouteConstraintContract.shift_window_second_by_id`：
```
solver/scripts/run_problem_hgs_private_technical.py:860
                shift_window_second_by_id=shift_windows,
```

### 客户时间窗从哪来（独立文件）

同目录的 `orders.csv`，逐客户两列 `time_window_early_minute` /
`time_window_late_minute`（表头第 18–19 列），另有 `shift_id` / `shift_start_minute` /
`shift_end_minute` 三列冗余记录班次归属。例：C001 = 517.588466–557.591330 分
（08:37:35–09:17:35），`shift_id=AM`。runner 读客户班次归属：
```
solver/scripts/run_problem_hgs_private_technical.py:853-856
            customer_shift_by_id={customer_id: str(row["shift_id"])
                for customer_id, row in built.orders_by_customer.items()},
```

**耦合关系**：`shift_contract.json` 和 `orders.csv` 是两份文件，改一份不会自动改另一份。
但 50 个客户窗是按 AM 480–660 / PM 780–1140 布进去的
（`orders.csv` 的 `window_classification` 列写着
`OBSERVED_WIDTH_AND_WITHIN_SHIFT_SHAPE__SHIFT_PLACEMENT_EXTRAPOLATED`），
所以把班次窗挪走而不动客户窗，客户窗会落在班次外，多半直接不可行。
**要当作两件事一起改**。

### 最小改动

- **A（数据侧，推荐用于"整体平移作业日"的杠杆）**：复制算例目录成一个新 instance_id，
  同时改 `shift_contract.json` 的 `shifts` 与 `orders.csv` 的两列客户窗
  （平移同样的分钟数），再在 runner 第 124 行加一个新的 instance_id 常量并在
  `_build_context` 第 246 行放行。约 5–8 行代码 + 一次数据生成。

  该算例目录下另有 6 个文件，已核实 runner 只读其中两个：
  `source_mapping.csv`（第 499–504 行，节点 id 映射，且第 504 行校验其键集
  必须等于目标节点集）与 `matrix_reference.json`（第 507 行）。
  `witness_status.json` / `contestability.csv` / `enterprise_assignment.csv` /
  `provenance.json` / `artifact_hashes.json` 在 runner 里 grep **零命中**。
  平移时间窗不改节点身份，所以这两个文件原样复制即可，
  **5–8 行的估计成立**。
- **B（代码侧，只平移班次不动客户）**：在 runner 加
  `--shift-window-shift-minute`，在第 709–712 行构造 `shift_windows` 时加偏移。
  约 8 行。但如上所述，单独平移班次大概率不可行，只有"加宽"（早开始/晚结束）方向安全。

**受保护文件**：都不碰。

**附注（与本题无关但需备案）**：这条私有路径把 `formal_search_allowed` 置为 False
（`run_problem_hgs_private_technical.py:677,808`）。已核实该标志只在
`private_instance_rebuild_20260811.py:271` 的 `_validate_loaded_contract` 里被读
（`if not base.formal_search_allowed: raise`），那是**另一条重建路径**的入口守卫，
本 runner 不调用它。**不 gate 任何杠杆要碰的东西。**

---

## 5. 电动车补贴（EV 日固定溢价）

**结论：常量 100.0 元/日，定义在 `private_instance_rebuild_20260811.py:47`，
没有命令行覆盖。**

```
solver/src/setp_solver/private_instance_rebuild_20260811.py:47
EV_DAILY_FIXED_PREMIUM_CNY = 100.0
```

引用点（共 3 处，均为 import 后直接用常量，无覆盖通道）：
```
solver/scripts/run_problem_hgs_private_technical.py:698-700
    from setp_solver.private_instance_rebuild_20260811 import (
        EV_DAILY_FIXED_PREMIUM_CNY,
    )
solver/scripts/run_problem_hgs_private_technical.py:848
        ev_daily_fixed_premium_cny=EV_DAILY_FIXED_PREMIUM_CNY,
solver/scripts/run_coalition_experiment.py:268
        ev_daily_fixed_premium_cny=EV_DAILY_FIXED_PREMIUM_CNY,
```

它进的是 `DutyEvaluationContext.ev_daily_fixed_premium_cny`
（构造在 `run_problem_hgs_private_technical.py:840-865`），
在本次示例解里体现为 `cost_fix_ev_premium = 300.0`（3 辆 EV × 100，见第 9 题）。

**最小改动**：在 runner 加 `--ev-daily-premium`（`type=float`,
`default=EV_DAILY_FIXED_PREMIUM_CNY`），第 848 行改成用 `args` 的值。
问题是第 848 行在 `_suite_context_from_built` 内部，`args` 不在作用域，
需要把参数从 `_build_context`（224 行）→`_build_saved_suite_context`（869 行）
→`_suite_context_from_built`（685 行）三层透传。
**估计 12–16 行。受保护文件不碰。**
（补贴 = 把这个数从 100 往下调，调到 0 即"电油同价"，调成负数即真补贴。）

---

## 6. 四种充电策略在正式入口是否可用

**结论：四种全部可用且实现完整；但有一个静默覆盖闸门要注意——
只要不传 `--mechanism-off charge_timing`，`--charge-timing-policy` 就被逐字尊重。
正式跑批脚本没传 `--mechanism-off`，所以 `carbon_min` / `cost_min` 在正式入口可直接用。**

```
solver/src/setp_solver/charge_timing.py:25-33
CHARGE_TIMING_POLICIES = frozenset({"asap","cost_min","cost_plus_carbon","carbon_min"})
DEFAULT_CHARGE_TIMING_POLICY = "carbon_min"

solver/scripts/run_problem_hgs_private_technical.py:1361-1366
    parser.add_argument("--charge-timing-policy",
        choices=tuple(sorted(CHARGE_TIMING_POLICIES)), default="cost_plus_carbon", ...)
```

**静默覆盖闸门**：
```
solver/scripts/run_problem_hgs_private_technical.py:1518-1522
    effective_charge_timing_policy = (
        args.charge_timing_policy
        if mechanism_enabled["charge_timing"]
        else "asap"
    )
solver/scripts/run_problem_hgs_private_technical.py:1506-1508
    mechanism_enabled = {name: name not in mechanism_off for name in sorted(MECHANISM_NAMES)}
```
`mechanism_off` 只来自 `--mechanism-off`（第 1450 行，默认空串），与 `--arm` 无关。
`run_private_axes_one.sh` 的 COMMON 里没有 `--mechanism-off`，
所以 `mechanism_enabled["charge_timing"] is True`，policy 原样生效。
（消融批里 `MT-HGS` 臂才是关掉 charge_timing 的那条，见
`build_charge_timing_comparison.py:58-61` 的 `ARM_EXPECTATION`。）

实现完整性（四条分支都有代码，不是占位）：
```
solver/src/setp_solver/charge_timing.py:477-500   # objective_value：asap / carbon_min / cost_min / cost_plus_carbon
solver/src/setp_solver/charge_timing.py:745-812   # 无缓存 fallback：同样四分支
solver/src/setp_solver/charge_timing.py:762-764,782-784  # carbon_price==0 时 cost_plus_carbon 自动降级成 cost_min
solver/src/setp_solver/charge_timing.py:747-748   # carbon_min 且无碳档案时退回 earliest
```
运行结果里也有记录字段：`requested_charge_timing_policy` /
`effective_charge_timing_policy`（第 1568–1569、2469–2470 行）——跑完可以核。

**改动需求：无。**

---

## 7. 单次求解耗时（6 并行）

数据源：两份 launcher.log 的 `启动 <axis>/<tag>/run_N` 与
`完成 <axis>/<tag>/run_N exit=0` 配对（格式见 `run_private_axes_one.sh:26,32`）。
两份日志都未跨午夜。

**⚠️ 机器出处：未记录。** 两份 launcher.log 和 run 目录下的
`metadata.json` / `decision.json` 里都 grep 不到 host / machine / platform /
uname / cpu 字段（实测零命中），README 也没写。按仓库的跨机不可比规矩，
**下面这些绝对秒数只在产出它们的那台机器上有效，换机必须重测**。

### `solver/reports/private_axes_formal_v2_20260904/launcher.log`（33 任务，6 并行）

| 指标 | 值 |
|---|---|
| 中位 | **480 s = 8.0 min** |
| 最大 | **897 s = 14.9 min** |
| 最小 | 232 s = 3.9 min |
| 均值 | 519 s = 8.65 min |
| 总 CPU 墙钟和 | 17 141 s = 4.76 h |
| 实测批墙钟 | 01:45:01 → 02:34:41 = **0.83 h** |

按碳价档分（每档 3 次，秒）：
```
carbon=0     [417, 818, 897]    中位 818
carbon=0.05  [337, 344, 405]    中位 344
carbon=0.075 [469, 480, 495]    中位 480
carbon=0.10  [481, 593, 615]    中位 593
carbon=0.15  [725, 808, 837]    中位 808
carbon=0.20  [341, 587, 717]    中位 587
carbon=0.30  [313, 540, 590]    中位 540
carbon=0.60  [303, 417, 636]    中位 417
carbon=1.5   [380, 427, 701]    中位 427
carbon=2.0   [414, 423, 541]    中位 423
carbon=5.0   [232, 424, 434]    中位 424
```
耗时与碳价无单调关系；离散度主要来自种子。

### `solver/reports/ablation_formal_10x_v5_20260904/launcher.log`（30 任务，6 并行）

| 指标 | 值 |
|---|---|
| 中位 | **400 s = 6.7 min** |
| 最大 | **971 s = 16.2 min** |
| 最小 | 180 s = 3.0 min |
| 均值 | 447 s = 7.5 min |
| 总 CPU 墙钟和 | 13 415 s = 3.73 h |
| 实测批墙钟 | **0.67 h** |

### 换算公式（6 工人）

用 `总墙钟 ≈ N × 均值 / 6`，不要用 `ceil(N/6) × 中位`（后者在耗时异质时高估）。
实测校验：33 × 519 / 6 = 2 854 s = 0.79 h，实测 0.83 h（差 5%，来自尾部收束）。

以 private_axes 的均值 519 s/次计：

| N 次求解 | 预计墙钟 |
|---|---|
| 6 | ~0.15 h（9 min） |
| 30 | ~0.72 h（43 min） |
| 33 | ~0.79 h（实测 0.83 h） |
| 60 | ~1.44 h |
| 90 | ~2.2 h |
| 120 | ~2.9 h |
| 180 | ~4.3 h |
| 300 | ~7.2 h |

经验加成：实测比公式高 5–8%，规划时按 **N × 520 s / 6 × 1.08** 报。

---

## 8. 重排工具能不能吃反事实日历

**结论：能，而且改动比正式入口还小——它复用同一个 `_build_context`，
所以第 2 题那一处路径改动会同时惠及重排工具，零额外改动。
换碳价则需要给它加一个命令行参数（约 6 行），因为它现在从批次元数据里读碳价。**

### 它怎么拿日历

```
solver/scripts/build_charge_timing_comparison.py:319
    runtime = _load_runtime(repo)
solver/scripts/build_charge_timing_comparison.py:331-333
    bundle, _initial, _np, context = runtime._build_context(
        repo, shared["instance_id"], fleet_parameters=fleet_class
    )
```
`runtime` 就是 `run_problem_hgs_private_technical` 模块本身。所以它走的是
**完全同一条**私有构建路径 → 同一个写死的 `runtime_root`（runner 第 570 行）。

**⇒ 换时段划分：改 runner 第 570 行（或加那个参数）后，重排工具自动吃到新日历，
它自己一行都不用改。**

### 它怎么拿碳价

```
solver/scripts/build_charge_timing_comparison.py:329
    carbon_price = float(shared["carbon_price_cny_per_kg"])
solver/scripts/build_charge_timing_comparison.py:335-339
    bundle = replace(bundle,
        prices=replace(bundle.prices, carbon_price=carbon_price),
        carbon_price_cny_per_kg=carbon_price)
    context = replace(context, bundle=bundle)
```
`shared` 来自 `_collect_runs(batch_dir)`，是批内所有 run 必须一致的元数据
（`SHARED_METADATA_FIELDS`，第 64–70 行，含 `carbon_price_cny_per_kg`）。
覆盖机制已经在了，只是值被锁到批次自己的碳价。

**⇒ 换碳价：加 `--carbon-price`（`type=float`, `default=None`），
第 329 行改成 `carbon_price = float(args.carbon_price) if args.carbon_price is not None
else float(shared["carbon_price_cny_per_kg"])`。约 6 行。**

### 它现在只比两种策略

```
solver/scripts/build_charge_timing_comparison.py:53-61
ASAP_ARM = "MT-HGS"; CARBON_ARM = "MTC-HGS"
ASAP_POLICY = "asap"; CARBON_POLICY = "cost_plus_carbon"
solver/scripts/build_charge_timing_comparison.py:345-348
    policies = {name: runtime._policy(evaluator, charge_timing_policy=name)
                for name in (ASAP_POLICY, CARBON_POLICY)}
```
要把 `cost_min` / `carbon_min` 也放进对照，把第 347 行的元组加两项即可
（`runtime._policy` 第 155–173 行对任何 policy 都通用），
但下游 `paired_rows` 的自检（第 400–420 行 replay/invariance 两条）和
Markdown 渲染（第 640–940 行）按两策略写死，需一并调整，**约 40–60 行**。

### 重排的正确性护栏（利好：结果可信）

```
solver/scripts/build_charge_timing_comparison.py:391-397
    repaired = repair_changed_duties(individual, individual,
        changed_duty_ids=changed, context=context, policy=policy)
    evaluation = evaluator.evaluate(repaired)
    if not evaluation.feasible: raise SystemExit(...)
```
外加两条自检：用解自己的策略重放必须复现官方 breakdown（第 400–420 行），
以及 `ROUTE_INVARIANT_KEYS`（第 76–83 行：`cost_fix` / `cost_km` / `cost_fuel` /
`distance_total` / `n_veh_cv` / `n_veh_ev`）在只改充电时刻时不许动。

**⇒ 结论：反事实"时段划分"和"电价缩放"都可以先用重排工具花几分钟看方向，
再决定要不要花 1–3 小时重搜路线。这是本次调查最有价值的一条。**

**警告一条**：重排只改充电时刻，**不改路线、不改车队构成**。
所以它能测的是"给定这套路线，换时段/换碳价能省多少充电成本和碳"，
测不出"时段变了以后企业会改派几辆电车"。补贴（第 5 题）和车队构成杠杆
必须重搜路线。

---

## 9. 算例里的充电设施与充电行为

样本：`solver/reports/ablation_formal_10x_v5_20260904/MTC-HGS/run_04/best_solution.json`

### 充电是否全在车场：是

`evaluation.breakdown`：
```
depot_charging_kwh   = 222.23217173900284
station_charging_kwh = 0
electricity_kwh      = 222.23217173900284
ev_drive_kwh         = 222.23217173900284
cost_elec            = 182.84975860746533
cost_carbon          = 38.51766649605588
E_total              = 192.58833248027938   (E_cv_direct 119.32560568, E_ev_indirect 73.26272680)
n_veh_cv = 2, n_veh_ev = 3
cost_fix = 1150.0, cost_fix_ev_premium = 300.0   ← 3 EV × 100 元/日，对应第 5 题
total_cost = 2629.7530955931165
```
**`station_charging_kwh = 0`，公共充电站一次都没用，全部在车场充。**
算例里确实有公共站（`nodes.csv` 里 `S_OSM_NODE_*` 若干），但没被选中。

### 每辆电动车的充电次数与起止时刻

`individual.duties` 共 20 条（含空槽），非空 5 条：2 辆油车（0 次充电）+ 3 辆电车。
充电桩 id 全等于本车 `home_depot_id`，`charge_day_offset` 全为 0（当日，无隔夜）。

| 车辆 | 趟数 | 次数 | 第 n 次 | 起 → 止 | 电量 kWh |
|---|---|---|---|---|---|
| EV_D_OSM_WAY_1003511503_2 | 2 | 2 | 1 | 06:00:00 → 06:47:04 | 46.936 |
| | | | 2 | 12:19:10 → 13:02:44 | 43.441 |
| EV_D_OSM_WAY_1071205721_1 | 3 | 3 | 1 | 06:00:00 → 06:19:36 | 19.534 |
| | | | 2 | 12:35:00 → 13:06:16 | 31.163 |
| | | | 3 | 15:30:10 → 15:44:04 | 13.866 |
| EV_D_OSM_WAY_1071205721_2 | 3 | 3 | 1 | 06:00:00 → 06:19:43 | 19.659 |
| | | | 2 | 13:00:00 → 13:18:29 | 18.430 |
| | | | 3 | 15:04:08 → 15:33:25 | 29.204 |

合计 8 次、222.232 kWh，与 `depot_charging_kwh` 逐位一致。
每次 `start_energy_kwh = 0.0`、`end_energy_kwh == energy_kwh`；
充电曲线全为 `M17_FAST_SHAPE_SCALED_60KW_PWL`，`locked=false`。

`start_energy_kwh = 0.0` **不是序列化占位，是被校验过的真实电量**：
```
solver/src/setp_solver/check.py:1155-1158
    actual_start = float(action.start_energy_kwh)
    actual_end   = float(action.end_energy_kwh)
    expected_start = float(battery_before_kwh)      ← 与路线电量台账比对
    expected_end   = expected_start + float(action.energy_kwh)
```
写入点是 `algorithms/problem_hgs/charging.py:2146`
（`start_energy_kwh=previous_end`）。
读数为 0 与两件事自洽：`_china_prices` 给 `initial_ev_battery_kwh=0.0`
（`china81.py:1263`），以及本次运行用的
`charge_amount_strategy="just_enough"`（`run_problem_hgs_private_technical.py:169`）
——每次只充下一趟刚好需要的量，所以车回场时电正好用尽。

### 这些时刻说明什么（对 4.4 节直接有用）

- **三辆车的第一次充电都精确落在 06:00:00**。窗口下界其实是 0.0
  （`multitrip_schedule.py:798-799`：`same_day_predeparture` 返回
  `(0.0, departure_second - occupancy, 0)`），所以 06:00 不是硬约束，是**选出来的**：
  谷段 00:00–07:00 电价全等（0.56328575），`cost_plus_carbon` 在电价打平后由碳强度
  分胜负，而谷段内碳强度最低的正是 06:00–06:30（0.5849，对比 00:00 的 0.6433）。
  **这就是"碳信号在谷段内部起作用"的现成证据。**
- **午间三次落在 12:19 / 12:35 / 13:00，下午两次落在 15:04 / 15:30**，
  正好覆盖碳强度全天最低的 12:00–15:00（0.1541–0.1826），但那段是峰价（1.1486）
  和平价（0.8364）。这就是论文说的"碳最干净的时候电最贵"。
- 但要注意：午间/下午这几次的时刻同时受"上一趟几点回场"约束
  （窗口下界 = `timing.return_second`），**不能全部归因于择时选择**。
  想干净地分离，用第 8 题的重排工具比 `asap` / `cost_min` / `carbon_min` 三条基线。

---

## 汇总表

| 杠杆 | 现成可用？ | 最小改动 | 需不需要重搜路线 |
|---|---|---|---|
| **碳价** | ✅ 完全可用（`--carbon-price`，runner:1288） | 无 | 已跑：11 档 × 3 次（`private_axes_formal_v2_20260904/carbon`）。**固定路线重排也能测**（第 8 题加 6 行） |
| **电价时段划分** | ❌ 无参数 | 新增反事实日历 CSV（放仓库内）+ runner:570 改 1 行（或加参数 8–12 行）。`tariff_period` 无校验、电价无交叉校验、无哈希校验 | **重排即可先看方向**（零额外改动，工具复用同一 `_build_context`）；要看车队/路线响应才重搜 |
| **电价整体缩放 / 分时段折扣** | ❌ 无参数（`depot_electricity_price` 是全天平均，改它不影响计费） | 同上通道：造 CSV（0 行代码）；或 runner 加 `--electricity-scale` 约 12–15 行 | **重排即可**（同上） |
| **企业作业时间窗** | ❌ `china81.py:338` 的 `depot_time_windows` 在本入口够不着；真正生效的是 `shift_contract.json` 的两段班次 08:00–11:00 / 13:00–19:00（`attendance` 08:00–19:00 不进模型） | 数据侧：复制算例目录同改 `shift_contract.json` + `orders.csv` 客户窗，加 instance_id 放行 5–8 行；代码侧只平移班次 8 行（但单独平移多半不可行） | **必须重搜路线**（改的是可行域） |
| **电动车补贴** | ❌ 常量 `EV_DAILY_FIXED_PREMIUM_CNY = 100.0`（`private_instance_rebuild_20260811.py:47`），无覆盖 | runner 加 `--ev-daily-premium` + 三层透传，12–16 行 | **必须重搜路线**（它改的是买几辆电车的决策，重排改不动车队构成） |
| **充电策略 asap / cost_min / cost_plus_carbon / carbon_min** | ✅ 四种全可用（runner:1362，闸门在 1518–1522，正式脚本未触发） | 无 | 两者皆可：正式重搜 or 重排（重排现只比 2 种，扩到 4 种约 40–60 行） |

**受保护文件汇总**：以上 6 个杠杆的最小改动方案**没有任何一条需要动**
`solver/src/setp_solver/cost.py`、`solver/src/setp_solver/check.py`、
`solver/src/setp_solver/search/evaluation.py`。这三个文件只从
`bundle.time_profile` 的行里读列值、从 `prices` 里读标量，不关心数据从哪个目录来。

**建议的先后顺序**（成本从低到高）：
1. 用重排工具（`build_charge_timing_comparison.py`）+ 一份反事实日历，
   几分钟内看"时段划分"和"电价折扣"两个杠杆在固定路线下的方向和量级。
2. 方向确认后，再决定哪几个杠杆值得花 ~45 min（30 次）到 ~1.5 h（60 次）重搜路线。
3. 补贴和作业时间窗两个杠杆没有捷径，只能重搜。
