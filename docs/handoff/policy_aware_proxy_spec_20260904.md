# 策略感知 EV 路线代理 —— 可直接派工的施工规格

规格作者：Claude（只读设计员）。仓库根 `/Volumes/移动硬盘（512G）/ReSETP`，分支 `codex/reporting-pipeline`。
**本次设计没有改仓库任何文件，没有开求解器搜索。** 只读源码与已落盘产物；四份只读脚本写在会话临时目录
（`policy_proxy_truth.py`、`trip_clock_probe.py`、`cm_violation_probe.py`、`truth.json`），未进仓库。
本文所有数字都是本次实算，不是从 `route_effect_root_cause_20260904.md` / `route_effect_design_review_20260904.md` 抄的。

自检：三份日历各自重建 `DutyEvaluationContext` 后逐槽复算，
`P=0.2/MT-HGS/run_02` 的 `cost_elec` = 121.390418（官方 121.3904180006173）、
`P=0.2/MTC-HGS/run_02` 的 `cost_elec` = 131.89278031（官方 131.89278030877944），
两份都逐位相同。所以下文的槽价、实付均价与求解器同口径。

---

## 零、三条必须先看的实测结论（它们改写了派工单里两条验收线）

**结论 1 —— 用户要的效果，这个改动在午谷日历下确实做得出来。**
改后两臂的班次代理不再相同：

| 午谷日历 | MT-HGS（asap）代理 | MTC-HGS（cost_plus_carbon）代理 | 现行（两臂共用） |
|---|---:|---:|---:|
| AM 窗 [0,480) | **0.96510275** | **0.68202575** | 0.95342275 |
| PM 窗 [660,780) | **1.18460175** | **0.59620575** | 0.59620575 |

即：MTC 的电动车弧代理整体便宜，MT 的 PM 弧代理贵一倍。两臂第一轮的路线搜索从此不再是同一个分布——
这正是 `route_effect_design_review_20260904.md` 角度 7 指出的「③−② 结构性为零」的病根，
而且**不需要剥夺臂① 任何信息**（见 §C）。

**结论 2 —— 派工单里「北京 asap 代理逐位不变」这条验收线是错的，实测不成立。**
北京基准日历下，现行键选 06:30（390 分），asap 规则选 00:00（0 分）：

| 北京 v4 | 现行 | asap | cost_plus_carbon |
|---|---:|---:|---:|
| AM 窗 | 390 分 / **0.68026575** | 0 分 / **0.69194575** | 360 分 / **0.68026575** |
| PM 窗 | 750 分 / **1.18154175** | 660 分 / **1.18460175** | 720 分 / **1.18154175** |

北京下 asap 臂的代理**会变**（AM +1.72%、PM +0.26%）。**逐位不变的是 `cost_plus_carbon` 臂的代理值**
（0.68026575 / 1.18154175，与现行完全相同），但它选中的**槽号会从 390 变到 360**（同价同碳的并列，
只是并列决胜方向不同）。正确的验收线见 §D.1。

**结论 3 —— 派工单里「均一日历下两臂相同」这条也不成立。**
`china81_cf_calendar_uniform_v1_20260904` 只是**电价**均一（全天 0.84945008），**碳强度仍随时段变化**：

| 均一日历 | 现行 | asap | cost_plus_carbon |
|---|---:|---:|---:|
| AM 窗 | 390 分 / 0.96643008 | 0 分 / **0.97811008** | 360 分 / **0.96643008** |
| PM 窗 | 750 分 / 0.88237008 | 660 分 / **0.88543008** | 720 分 / **0.88237008** |

两臂差 0.01168（AM）与 0.00306（PM），**不是 0**。`_money_units` 的标度是 100000（分辨率 1e-5 元），
这个差在内核目标里是**可见的**，不会被取整抹掉。正确的验收线见 §D.1。

---

## A. 改动点清单

红线（写进派工信，逐条核）：
- `third_party/setp_hgs_kernel/` 下**一个字节都不许动**；若设计要求改内核，**停工回报**，不许自行决定。
- `solver/src/setp_solver/cost.py`、`check.py`、`solver/src/setp_solver/search/**`、
  `algorithms/problem_hgs/evaluation.py` **不许动**。
- 不改 `charge_amount_strategy="just_enough"`；不改停止规则（`NoImprovement(patience)`、`num_iters_no_improvement=10**9`）。
- 公开 28 题隔离：`solver/scripts/run_problem_hgs_public_technical.py` 只 import `setp_hgs_kernel`
  （第 13–14 行），本规格所有改动都在 `setp_solver` 里，公开算例与表 7 不受影响。
  验收时用 `git status third_party/` + 文件哈希核对（见 §E）。

---

### A(1)+(4) `_rebuilt_shift_aware_ev_unit_costs` 按策略取值（排序键随之消失）

> **(1) 与 (4) 是同一处改动的两半，不是两处。** 一旦选槽由策略决定，就不存在残留的「排序键」了：
> `cost_plus_carbon` 的键**就是**按钱，`carbon_min` 的键**就是**按碳，`asap` 的键**就是**最早。
> 现行的 `(碳强度, 电价, -起始)` 键是被**删掉**，不是被打补丁。

**文件：** `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py`
**函数：** `_rebuilt_shift_aware_ev_unit_costs`
**行号：** 签名 `1283-1287`；窗口递推 `1289-1305`；选槽 `1306-1319`（`min(available, key=…)` 就在 `1312-1318`）。

**改前（1283-1287、1312-1318）**
```python
def _rebuilt_shift_aware_ev_unit_costs(context, rows) -> dict[str, dict[str, float | int]]:
    """Select the lowest-carbon half-hour in each causal charging window."""
    ...
        row = min(available, key=lambda item: (
            float(item["actual_gco2_per_kwh"]),
            float(item["depot_energy_cny_per_kwh"]),
            -float(item["horizon_second_start"]),          # 并列取最晚
        ))
```

**改后（≤15 行）**
```python
def _rebuilt_shift_aware_ev_unit_costs(
    context, rows, *, charge_timing_policy: str | None = None
) -> dict[str, dict[str, float | int]]:
    """Price each causal window at what THIS arm's timing policy would pay."""
    carbon_price = float(context.bundle.prices.carbon_price)
    def _key(item):                     # 并列一律取最早 = 精确 select_start 的口径
        start = float(item["horizon_second_start"])
        elec = float(item["depot_energy_cny_per_kwh"])
        gco2 = float(item["actual_gco2_per_kwh"])
        if charge_timing_policy is None:          # 未声明策略 = 历史键，逐位不变
            return (gco2, elec, -start)
        if charge_timing_policy == "asap":        return (start,)
        if charge_timing_policy == "cost_min":    return (elec, start)
        if charge_timing_policy == "carbon_min":  return (gco2, start)
        if charge_timing_policy == "cost_plus_carbon":
            return (elec + gco2 / 1_000.0 * carbon_price, start)
        raise ValueError(f"unknown charge timing policy {charge_timing_policy!r}")
    row = min(available, key=_key)
```
**其余不动**：`selected[...]` 字典里的六个字段（`window_start_second` / `window_end_second` /
`selected_slot` / `selected_slot_start_second` / `electricity_cny_per_kwh` / `actual_gco2_per_kwh` /
`proxy_cny_per_kwh`）保持原样，`proxy_cny_per_kwh` 仍然是 `elec + gco2/1000*carbon_price`。
另加两条断言：
- 策略名必须过 `setp_solver.charge_timing.validate_charge_timing_policy`（同一个白名单，不许另造）；
- `carbon_price == 0.0` 时 `cost_plus_carbon` 退化为 `cost_min`——**与精确择时器同口径**
  （`charge_timing.py:select_charge_timing_start` 里那两处 `if policy == "cost_plus_carbon" and carbon_price == 0.0: policy = "cost_min"`）。本批 P=0.2 不触发，但必须写，否则 P=0 的臂会与精确账错位。

**并列决胜方向（必须按这条写，不许自选）**：精确择时器 `charge_timing.py`
`select_start` 末尾是 `min(scored, key=lambda item: (item[0], item[1]))`，`item[1]` 是起始时刻——
**并列取最早**。代理必须同向。代价是北京/均一日历下 `cost_plus_carbon` 的 `selected_slot`
从 390 变 360（**价与碳完全相同，`proxy_cny_per_kwh` 逐位不变**，只是台账里的槽号变了）。
若有人坚持槽号也不能变，唯一的替代是给 `cost_plus_carbon`/`carbon_min` 保留 `-start`
并列键——**不推荐**，因为那就与精确账反向了。

**文档同步（顺手做）**：函数 docstring 现在写的是 "Select the lowest-carbon half-hour"，
改后不再成立，必须改掉。

---

### A(2) 策略参数链：`effective_charge_timing_policy` → `_rebuilt_shift_aware_ev_unit_costs`

四层，每层加一个形参，**默认一律 `None`**（= 历史行为）。

| # | 文件 | 位置 | 加什么 |
|---|---|---|---|
| 2a | `solver/scripts/run_problem_hgs_private_technical.py` | `route_engine_options` 组装段（`1845` 之后、`make_route_engine` 定义 `1915` 之前，任选一处紧邻 `route_engine_options["ev_charge_time_proxy_enabled"] = …` 的位置） | `route_engine_options["charge_timing_policy_for_proxy"] = effective_charge_timing_policy`（该变量在 `1628-1632` 已算好；`mechanism_off` 含 `charge_timing` 时它自动是 `"asap"`，正是 MT-HGS 臂） |
| 2b | `kernel_proposals.py` | `IndependentKernelDutyRouteProposalEngine.__init__` 关键字段，`84-85` 之间（`shift_aware_ev_unit_cost_enabled` 之后） | 形参 `charge_timing_policy_for_proxy: str | None = None`；`116-119` 区域加 `self.charge_timing_policy_for_proxy = (None if charge_timing_policy_for_proxy is None else validate_charge_timing_policy(str(charge_timing_policy_for_proxy)))` |
| 2c | `kernel_proposals.py` | `__init__` 里调用 `_build_unique_asset_problem` 处，`190-193` 之间 | 传 `charge_timing_policy_for_proxy=self.charge_timing_policy_for_proxy` |
| 2d | `kernel_proposals.py` | `_build_unique_asset_problem` 签名 `817-819` 之间；调用点 `1020-1021` | 形参 `charge_timing_policy_for_proxy: str | None = None`；`rates = _rebuilt_shift_aware_ev_unit_costs(context, rows, charge_timing_policy=charge_timing_policy_for_proxy)` |

**为什么默认必须是 `None`：** `shift_aware_ev_unit_cost_enabled=True` 还有三个别的调用方——
`solver/scripts/run_coalition_experiment.py:469`、`run_mixed_fleet_experiment.py:275` 与 `:423`——
以及三个现有测试（`solver/tests/test_problem_hgs_reload_gap.py:217,297`、
`test_problem_hgs_kernel_native.py:62`、`test_problem_hgs_ev_charge_time_and_lock_pins.py:55`）。
默认 `None` 让这六处**结构性逐位不变**，不用靠事后跑一遍来验。

**`source_id` 溯源（必做）：** `kernel_proposals.py:276-312` 的 `self.source_id` 拼接串里，
紧跟 `"shift-aware-ev-price:"` 之后加
`(f"policy-proxy-{self.charge_timing_policy_for_proxy}:" if self.charge_timing_policy_for_proxy else "")`。
只影响私有技术线的 metadata 字符串，不影响任何数字。仓库里已有的
`route_engine_source_id` 只出现在历史产物里，没有任何代码按它做相等判断（已 grep 核过）。

**台账缺口（顺手补，D.1/D.5 要用）：** 引擎上的 `self._shift_aware_ev_proxy`（`kernel_proposals.py:1023`
写入）**目前没有落盘**——`run_problem_hgs_private_technical.py:1930-1950` 的 `route_engine_wiring`
只写了 `route_engine_source_id` 与 `ev_charge_time_proxy`。请在 `route_engine_wiring` 里加一项
`"shift_aware_ev_proxy": route_engine._shift_aware_ev_proxy`（若嫌读私有属性难看，一并加个
`@property shift_aware_ev_proxy`）。这是纯 metadata 增项，任何数字都不动，但没有它 D.1 与 D.5 无法从产物核账。

---

### A(3) `ev_unit_cost_override` 不再抹平分班次值

**文件：** `kernel_proposals.py`　**行号：** `1027-1031`
**上游：** `runner.py:707-711` 把上一轮精确最优的 `(cost_elec + E_ev_indirect × carbon_price) / kWh`
算成一个标量，`runner.py:575-580` 经 `route_engine_factory(ev_unit_cost_cny_per_kwh=…)` 传回。
本批 `restarts` = 2–3，所以第 2、3 轮现在**完全没有班次/策略分辨率**。

**改前（1027-1031）**
```python
        if ev_unit_cost_override is not None:
            ev_unit_cost_by_depot[depot_id] = float(ev_unit_cost_override)
            for key in list(ev_unit_cost_by_depot_and_shift):
                if key[0] == depot_id:
                    ev_unit_cost_by_depot_and_shift[key] = float(ev_unit_cost_override)
```

**写法甲（按班次比例校正）—— 推荐**
```python
        if ev_unit_cost_override is not None:
            ev_unit_cost_by_depot[depot_id] = float(ev_unit_cost_override)
            keys = [k for k in ev_unit_cost_by_depot_and_shift if k[0] == depot_id]
            if keys:
                base = sum(ev_unit_cost_by_depot_and_shift[k] for k in keys) / len(keys)
                # base > 0 always (a tariff row is a positive price); guard anyway.
                factor = float(ev_unit_cost_override) / base if base > 0.0 else 1.0
                for k in keys:
                    ev_unit_cost_by_depot_and_shift[k] *= factor
```
**写法乙（干脆不覆盖分班次那一份）**
```python
        if ev_unit_cost_override is not None:
            ev_unit_cost_by_depot[depot_id] = float(ev_unit_cost_override)
            # per-shift prices keep the calendar+policy structure; the scalar
            # feedback only feeds the shift-agnostic fallback.
```

**利弊**

| | 甲（比例校正） | 乙（不覆盖） |
|---|---|---|
| 保留分班次/分策略结构 | 保留（比值不变） | 保留（原值不变） |
| 精确账反馈的**水平**信息 | 保留 | **丢掉**（因为开了班次感知时，EV 弧只读 `ev_unit_cost_by_shift`，`ev_unit_cost_by_depot` 一次也用不上，见 `_route_proxy_cost_units:1417-1431`） |
| 实测校正幅度 | 反馈标量 =(`cost_elec`+`E_ev_indirect`×0.2)/`electricity_kwh`，run_02 逐位读得：**MTC 0.68230570**=(131.892780+69.140255×0.2)/213.5712，改后两班次均值 (0.68202575+0.59620575)/2 = 0.63911575 → **factor 1.06758**；**MT 1.02468844**=(121.390418+45.282989×0.2)/127.3041，均值 (0.96510275+1.18460175)/2 = 1.07485225 → **factor 0.95333**。**两侧都在 ±7% 内，温和** | 无 |
| 风险 | 均值是**未按 kWh 加权**的（建图期拿不到分班次电量），是一个约定，要写进注释 | 悄悄拆掉了一条已接线的反馈回路，属于「顺手多改一件」 |

**推荐甲。** 理由：它只做用户要求的那一件事（不抹平结构），不额外拆掉别人建好的反馈；
实测校正幅度 ±7%，不会把臂间差（AM 0.965 vs 0.682）抹掉。
**不稳定判据（写进派工信）：** 若任一轮算出的 `factor` 偏离 1 超过 25%，
落盘一条 `accounting` 告警并**降级为乙**（本轮不覆盖分班次值），不要放任它放大。

---

### A(5) 落盘每趟 `depart_second` / `return_second`

**好消息：不需要新算任何东西，也不需要动 `charging.py`。**
`FullEvaluation` 已经带 `certificate: MultiTripCertificate`
（`algorithms/problem_hgs/evaluation.py:242`），而
`MultiTripCertificate.trips` 是 `tuple[ScheduledTrip, ...]`
（`search/multitrip_schedule.py:170`），`ScheduledTrip` 有
`route_id / physical_vehicle_id / trip_index / vehicle_type / home_depot_id /
departure_second / return_second / recharge_end_second`（`multitrip_schedule.py:107-116`）。
**这块数据一直都在内存里，只是没写进 JSON。**

**序列化点：** `solver/scripts/run_problem_hgs_private_technical.py:2687-2703`，
写 `best_solution.json` 的那个 `_json(...)` 字典里，与 `"individual"` / `"evaluation"` /
`"accounting"` **平级**加一个新键：

```python
        {
            "individual": asdict(result.best),
            "trip_clock": [                      # 新增：每趟的发车/回场/补电结束时刻
                asdict(trip)
                for trip in sorted(
                    result.best_evaluation.certificate.trips,
                    key=lambda t: (t.physical_vehicle_id, t.trip_index),
                )
            ],
            "evaluation": {...},
            ...
        }
```

`ScheduledTrip` 是 `@dataclass(frozen=True)`（`search/multitrip_schedule.py:107`），
八个字段全是 `str` / `int` / `float`，`asdict` 直接可用——同一个 `_json(...)` 字典里
`violations` 已经在用 `asdict`，不需要写任何自定义序列化。

**为什么放在顶层而不是塞进 `DutyTrip`：** `DutyTrip` 是 frozen dataclass，参与
`_duty_fingerprint` / 解的去重键 / `asdict(result.best)`。往里加字段会改解的身份，
风险与收益完全不成比例。放顶层 → `asdict(result.best)` **逐位不变**，
`build_charge_timing_comparison.py`、`compute_green_window_outlay.py`、
`generate_carbon_charging_figure.py`、`backfill_table8.py` 这些现有消费方一个都不用改。

**一致性断言（写进代码，不只是验收步骤）：** 序列化前遍历一次，对每个 duty
按 `trip_index` 升序，对每条 `trip_index > 最小 trip_index` 的车场充电会话断言
```
session.charge_start_second >= trip_clock[前一趟].return_second - 1e-6
```
（这是 `charging.py:2199` `earliest = previous_return` 的直接推论）。**只能写单侧不等号**：
`cost_plus_carbon` 下起充可以晚于回场（run_02 `EV_D_OSM_WAY_1071205721_4` 的 T2 起充
= 46800.0 s，正好是 PM 班次下界，晚于 T1 回场 35343.8 s）。任何一条破了就 `raise`。

**已实测的验收锚点（我已经跑过，不是推断）：** 用午谷日历重建 context、加载
`P=0.2/MTC-HGS/run_02/best_solution.json`、`DutyFullEvaluator.evaluate` 一次，
`certificate` 给出

```
EV_D_OSM_WAY_1071205721_4 T1 depart=29764.50598 return=35343.80598 recharge_end=47909.02455
EV_D_OSM_WAY_1071205721_4 T2 depart=47909.02455 return=54247.51454 recharge_end=56017.63284
EV_D_OSM_WAY_1071205721_4 T3 depart=56017.63284 return=65315.73784 recharge_end=65315.73784
```
**T2 `return_second` = 54247.51454，与 T3 的 `charge_start_second` = 54247.51454 差 7.3e-12 秒。**
（同一次复算里 `cost_elec` = 131.89278030877944，与官方逐位相同。
注意：该复算的 `total_cost` 是 2563.94 而官方是 2588.17，差 24.23，
原因是我的探针没传 `ev_daily_premium_cny`，与本改动无关，不要被它带偏。）

---

### A(6) 班次回场上界接入 `_latest_trip_departure_second`

**病：** `charging.py:1513-1528` 的上界只来自 `TripTiming.latest_departure_second`
（本趟客户时间窗的后向递推），**不含「本车必须在本班次结束前回场」**。班次侧现在只接了下界
（`_shift_minimum_departure_second_by_route`，`charging.py:2085-2092`）。

**方向要说实话：** 加上界只会让 `[earliest, latest]` **变窄**，因此**只会增加**、
绝不会减少 `NO_FEASIBLE_WINDOW`。它的价值不在救回被拒候选，而在
**让 `carbon_min` 这条臂重新可行**——那正是 4.10「电网代管」臂的前置。

**已实测的病灶与判据（我已经跑过）：**
`solver/reports/ablation_formal_10x_v5_20260904/MT-HGS/run_04/best_solution.json`
按 `carbon_min` 重排后
```
VIOLATION: Violation(type='TIME_WINDOW', vehicle_id='EV_D_OSM_WAY_1071205721_7#T2',
                     location='AM', detail='returns after AM end; late by 118.6639562 s',
                     severity='hard')
```
逐趟时钟（同一次探针）：AM 班次窗 = (28800.0, 39600.0) 秒。

| 策略 | T2 前的车场充电 | 强制发车 | T2 回场 | 判定 |
|---|---|---:|---:|---|
| asap | 起 35062.90，历时 631.16，止 35694.06 | 35694.06 | 38781.56 | 可行 |
| carbon_min | 起 **36000.00**，历时 631.16，止 36631.16 | 36631.16 | **39718.66** | 超 AM 末 118.664 s |

**改动 6a —— 新建一个与下界对称的辅助函数（写在 `charging.py`，不许动 `evaluation.py`）**
```python
def _shift_maximum_return_second_by_route(solution, context) -> dict[str, float] | None:
    """Mirror of _shift_minimum_departure_second_by_route: the shift END."""
    if not context.shift_aware_departure_enabled:
        return None
    contract = context.rebuilt_route_constraints
    if contract is None:
        raise ValueError("shift-aware departure has no shift contract")
    ceiling: dict[str, float] = {}
    for route in solution.routes:
        shifts = {str(contract.customer_shift_by_id[n])
                  for n in route.node_sequence[1:-1]
                  if n in contract.customer_shift_by_id}
        if len(shifts) == 1:
            ceiling[route.vehicle_id] = float(
                contract.shift_window_second_by_id[next(iter(shifts))][1])
    return ceiling
```
（与 `evaluation.py:484-506` 逐行同构，只把 `[0]` 换成 `[1]`。混班次的趟不设上界，
与下界侧「`len(shifts) == 1` 才设」保持一致。）

**改动 6b —— `_latest_trip_departure_second` 加 duty 级入参**
文件 `charging.py`，函数定义 `1513-1528`。
```python
def _latest_trip_departure_second(
    timing, route, instance, prices, *, shift_return_ceiling_second: float | None = None
) -> float:
    latest = getattr(timing, "latest_departure_second", None)
    if latest is None:
        latest = float(route_departure_second(route, instance, prices))
    if shift_return_ceiling_second is not None:
        # return(d) = max(preferred, d) + span, span from this unforced clock
        # (multitrip_schedule.py:577-579 `earliest_departure = depart`), so
        # d <= ceiling - span is exactly "this trip returns inside its shift".
        span = float(timing.return_second) - float(timing.earliest_departure_second)
        latest = min(float(latest), float(shift_return_ceiling_second) - span)
    return float(latest)
```
**为什么 `span` 取自未强制时钟是对的（可证，不是估）：**
`route_timing` 里 `earliest_departure = depart`（`multitrip_schedule.py:577-579`），
且 `return(d) = max(preferred, d) + minimal_span`。未强制时钟的 `d = min(preferred, latest_departure)`。
当 `d ≥ preferred` 时 `span = minimal_span`，上界是**精确**的；
当 `latest_departure < preferred` 时 `span > minimal_span`，上界略偏紧（保守，仍安全）。

**改动 6c —— 三个调用点各传上界**
| 行号 | 所在函数 / 分支 | 传什么 |
|---|---|---|
| `charging.py:1476` | `_static_timing_variants` 里 duty 内的候选时钟生成 | `shift_return_ceiling_second=ceilings.get(route.vehicle_id)`；`ceilings` 在该函数已构造 `solution` 之后调 6a 求一次 |
| `charging.py:2186` | `_anchor_duty_depot_actions`，`position == 0` 且 `same_day_predeparture` | 同上；`ceilings` 在 `2085-2092` 现有 `shift_floors` 旁边一起求 |
| `charging.py:2201` | `_anchor_duty_depot_actions`，`position > 0`（`full_gap`） | 同上 |

**改完后 run_04 那笔会变成什么（可先手算核对）：**
T2 的 `span` = 38781.56 − 35694.06 = 3087.50 s（两策略下相同）；
`ceiling − span` = 39600 − 3087.50 = **36512.50**；
`latest = 36512.50 − 631.16 = 35881.34`，`earliest = previous_return = 35062.90`。
**35062.90 ≤ 35881.34，窗口非空** → `carbon_min` 会在这段里另选一个起充，解重新可行，
不会退化成 `NO_FEASIBLE_WINDOW`。

**文档同步：** `route_effect_root_cause_20260904.md` 里「它能救回 `NO_FEASIBLE_WINDOW`」这句要删；
`code_review_charge_timing_20260904.md` §8 的「不修，只判断」要改成「已修」。

---

## B. 代理值真值表（脚本实算，`policy_proxy_truth.py` 一次跑出，未手抄）

**口径。** 算例 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`，`fleet_parameter_class=endogenous`，
`depot_charging_scenario=60kw`，`carbon_price = 0.2`。窗口取自
`context.rebuilt_route_constraints.shift_window_second_by_id`（**不是**硬读 `shift_contract.json`），
班次窗 AM (28800, 39600)、PM (46800, 68400)，因果充电窗因此是 AM [0, 480) 分、PM [660, 780) 分。
两个车场 `D_OSM_WAY_1003511503` 与 `D_OSM_WAY_1071205721` **每一格都相同**（日历不分车场），下表只列一次。
代理值 = `depot_energy_cny_per_kwh + actual_gco2_per_kwh/1000 × 0.2`。
**并列决胜：现行取最晚（`-start`），改后取最早（与精确择时器同向）。**

### B.1 窗口代理：现行 vs 改后

| 日历 | 窗 | 现行（槽/代理） | asap（＝MT 臂） | cost_plus_carbon（＝MTC 臂） | cost_min | carbon_min | 关班次感知时的全天均值 |
|---|---|---|---|---|---|---|---:|
| **beijing v4** | AM [0,480) | 390分 / 0.68026575 | **0分 / 0.69194575** | **360分 / 0.68026575** | 0分 / 0.69194575 | 360分 / 0.68026575 | 0.93731008 |
| **beijing v4** | PM [660,780) | 750分 / 1.18154175 | **660分 / 1.18460175** | **720分 / 1.18154175** | 660分 / 1.18460175 | 720分 / 1.18154175 | 0.93731008 |
| **midday_valley** | AM [0,480) | 390分 / 0.95342275 | **0分 / 0.96510275** | **300分 / 0.68202575** | 60分 / 0.69206575 | 360分 / 0.95342275 | 0.93731008 |
| **midday_valley** | PM [660,780) | 750分 / 0.59620575 | **660分 / 1.18460175** | **720分 / 0.59620575** | 720分 / 0.59620575 | 720分 / 0.59620575 | 0.93731008 |
| **uniform** | AM [0,480) | 390分 / 0.96643008 | **0分 / 0.97811008** | **360分 / 0.96643008** | 0分 / 0.97811008 | 360分 / 0.96643008 | 0.93731008 |
| **uniform** | PM [660,780) | 750分 / 0.88237008 | **660分 / 0.88543008** | **720分 / 0.88237008** | 660分 / 0.88543008 | 720分 / 0.88237008 | 0.93731008 |

### B.2 一眼看出的三件事

1. **北京下两臂改后不相同。** AM 0.69194575（asap）vs 0.68026575（c+c），差 **0.01168**；
   PM 1.18460175 vs 1.18154175，差 **0.00306**。
   现行两臂共用 0.68026575 / 1.18154175，差为 0。
   （北京 AM 的 0 分与 390 分**电价相同**（都是 0.56328575 谷价），差别只在碳强度 643.3 vs 584.9 gCO₂/kWh；
   PM 的 660 分与 750 分电价也相同（1.14862175），差别在碳 179.9 vs 164.6。）
2. **午谷差多少：AM 差 0.28308（41.5%），PM 差 0.58840（98.7%）。** 这是三份日历里最大的臂间缺口，
   也是本改动唯一能在本批看出效应的场景。
3. **均一日历下两臂也不相同**（AM 差 0.01168、PM 差 0.00306），因为该日历只均一了**电价**，
   碳强度仍按小时变。它现在的角色是「臂间差最小的对照」，不是「臂间差为零的对照」。

### B.3 趟间 PM 那一列（用户点名的「若区分」）—— 现在的规格里**不区分**，但缺口要摆出来

**裁定：本批保持两个因果窗，不新增第三个「趟间」窗。**
理由：新增窗口等于改窗口结构，越过用户「保留分班次/分策略结构」的口径；
而且趟间充电的下界是 `earliest = previous_return`（`charging.py:2199`），
那是**路线的函数**，建图期没有这个数（这正是内核看不见回场时刻的原病灶，不是这次要治的）。

缺口有多大，用 `run_02` 的实付账把它摆出来（午谷日历，按「该趟是不是本车第一趟」分桶）：

| 臂 | 桶 | 会话数 | kWh | 实付起充时刻（分） | 实付含碳均价 |
|---|---|---:|---:|---|---:|
| MT-HGS（asap） | AM · 首趟 | 2 | 42.0732 | 0.0, 0.0 | **0.96510275** |
| MT-HGS（asap） | PM · 趟间 | 4 | 85.2309 | 618.90, 632.04, 898.50, 930.17 | **1.05410220** |
| MTC-HGS（c+c） | AM · 首趟 | 3 | 78.1041 | 300.0, 300.0, 300.0 | **0.68202575** |
| MTC-HGS（c+c） | PM · 趟间 | 5 | 135.4671 | 739.16, 755.00, 780.00, 904.13, 930.17 | **0.68246710** |

读法：
- **首趟这一格，改后代理与实付逐位相同。** MT 的 asap 代理 0.96510275 = 实付 0.96510275
  （asap 的 `earliest = 0.0`，所以确实在 00:00 起充，窗口最早槽就是真相）；
  MTC 的 c+c 代理 0.68202575 = 实付 0.68202575（05:00 起充，正是窗口内的最小值）。**误差 0。**
- **趟间这一格，代理结构上够不着。** MT 的 4 笔起充里没有一笔落在 [660,780)；
  MTC 的 5 笔里只有 3 笔落在窗内。代理仍然只能用「本班次开始前那段窗口」的价当近似。
  即便如此，改后 MT 的 PM 代理 1.18460 比现行的 0.59621 离实付 1.05410 近得多（见 §C）。

---

## C. 公平性论证：改后**两臂**的代理都更贴自己的精确账，没有谁被剥夺信息

口径：`|代理 − 该臂 run_02 该桶实付含碳均价|`，再按该桶 kWh 加权。午谷日历，P=0.2。

| 臂（策略） | 桶 | kWh | 现行代理 | 改后代理 | 实付 | 现行偏差 | **改后偏差** |
|---|---|---:|---:|---:|---:|---:|---:|
| MT-HGS（asap） | AM·首趟 | 42.0732 | 0.95342 | 0.96510 | 0.96510 | 0.01168 | **0.00000** |
| MT-HGS（asap） | PM·趟间 | 85.2309 | 0.59621 | 1.18460 | 1.05410 | 0.45790 | **0.13050** |
| MTC-HGS（c+c） | AM·首趟 | 78.1041 | 0.95342 | 0.68203 | 0.68203 | 0.27140 | **0.00000** |
| MTC-HGS（c+c） | PM·趟间 | 135.4671 | 0.59621 | 0.59621 | 0.68247 | 0.08626 | **0.08626** |

**按 kWh 加权的平均绝对偏差（元/kWh）**

| 臂 | 现行 | 改后 | 降幅 |
|---|---:|---:|---:|
| MT-HGS（asap，127.304 kWh） | **0.31042** | **0.08737** | −71.9% |
| MTC-HGS（cost_plus_carbon，213.571 kWh） | **0.15397** | **0.05472** | −64.5% |

**折成钱的口径误差总额（偏差 × kWh）**

| 臂 | 现行 | 改后 |
|---|---:|---:|
| MT-HGS | 39.52 元 | **11.12 元** |
| MTC-HGS | 32.88 元 | **11.69 元** |

**三句话结论：**
1. **两臂都变准，没有一臂变差。** 四个格子里，两个降到 0，一个从 0.45790 降到 0.13050，
   一个不变（MTC 的 PM 窗现行与 c+c 选中同一格）。
   **但要单独点出一条：MT 的 PM 那格偏差不只是变小，是换了符号。**
   现行 0.59621 把 asap 臂的 PM 电动车弧**低估** 0.45790，改后 1.18460 **高估** 0.13050。
   对路线决策来说方向比幅度更要紧：现行下 MT 的 PM 电动车弧看着便宜，改后看着贵，
   **PM 班次里油/电分工的激励方向被整个翻过来了**。这正是 §E 风险 1 的机制，
   也正是 D.5 线 3（MT 三次均值与 2662.76 差 < 13）真正在测的东西。
   「更准」和「会把车队推向另一边」两句同时成立，后一句必须一起报，不许只报前一句。
2. **改后两臂的剩余口径误差几乎相等**（11.12 元 vs 11.69 元），而现行是 39.52 元 vs 32.88 元
   ——现行不但更不准，两臂还不等准。**改后比改前更公平，不是更不公平。**
3. **剩下的 11 元误差全部来自「趟间充电不在因果窗内」这一条**（§B.3），
   两臂同源、同量级，不构成臂间偏袒。它是下一件事，不是这一件事。

**因此不需要 handicap 臂①。** `route_effect_design_review_20260904.md` 角度 7 的结论
（「唯一能打开 ③−② 缺口的做法是故意让臂① 的代理更差」）在**这个设计下不成立**：
它当时假定代理只能是「按到达时刻查价」，而 asap 与 cost_plus_carbon 在 900 分处是同一个阶跃；
本设计改的是**窗口内怎么选槽**，两臂在窗口里的最优点本来就不同（asap 取端点，c+c 取最小），
所以缺口自然存在，不用人为制造。

---

## D. 验证方案（无长跑；1–4 全是秒级到分钟级，5 是每臂 3 次短跑）

> **总原则：1→2→3→4 全过之前不开任何一次搜索；5 全过之前不谈长跑。任一破线立刻停工回报。**

### D.1 秒级真值表断言（改 §B 表的两条错线）

新增测试 `solver/tests/test_policy_aware_shift_proxy.py`（或 Codex 觉得更合适的同类文件），
用 §B 的三份日历各建一次 context，直接调 `_rebuilt_shift_aware_ev_unit_costs`，
逐格与下表比对，**容差 1e-6**：

| 断言 | 内容 |
|---|---|
| **D.1a 历史不变** | `charge_timing_policy=None` 时，三份日历 × 两个窗 × 两个车场共 12 格的 `proxy_cny_per_kwh` **与改前逐位相同**（0.68026575 / 1.18154175 / 0.95342275 / 0.59620575 / 0.96643008 / 0.88237008），且 `selected_slot_start_second` 也逐位相同（23400 / 45000 秒，即 390 / 750 分） |
| **D.1b 午谷生效** | midday_valley：`asap` → AM 0.96510275、PM 1.18460175；`cost_plus_carbon` → AM 0.68202575、PM 0.59620575 |
| **D.1c 北京：值不变、槽号变** | beijing v4：`cost_plus_carbon` 的 `proxy_cny_per_kwh` = 0.68026575 / 1.18154175（**与 D.1a 逐位相同**），但 `selected_slot_start_second` = 21600 / 43200 秒（360 / 720 分，不是 23400 / 45000）。**`asap` 的值会变**：0.69194575 / 1.18460175 |
| **D.1d 均一：两臂不同** | uniform：`asap` 0.97811008 / 0.88543008，`cost_plus_carbon` 0.96643008 / 0.88237008；断言 `asap != cost_plus_carbon`，AM 差 0.01168、PM 差 0.00306 |
| **D.1e 碳价为 0 时退化** | `carbon_price=0.0` 下 `cost_plus_carbon` 与 `cost_min` 选中同一格（与 `charge_timing.py` 的两处退化分支同口径） |
| **D.1f 未知策略拒绝** | 传一个不在 `CHARGE_TIMING_POLICIES` 里的名字必须 `raise ValueError` |

**派工单里那两条要作废：**「北京 asap 代理逐位不变」→ 改成 D.1c；
「均一两臂相同」→ 改成 D.1d（两臂**不同**，差 0.01168 / 0.00306）。作废理由见 §零结论 2、3。

### D.2 现有回归：默认参数 `build_charge_timing_comparison.py` 逐位不变

```
export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src'
.public-hgs-venv/bin/python3 solver/scripts/build_charge_timing_comparison.py \
  --out-dir <改动后的新目录>
```
（默认 `--batch-dir solver/reports/ablation_formal_10x_v5_20260904`。）
把新 `summary.json` 与已落盘的 `solver/reports/charge_timing_comparison_20260904/summary.json`
**逐位 diff**，必须零差异。

**这条覆盖什么、不覆盖什么（必须写清，否则会被误当成全量回归）：**
- **覆盖 A(6)**：该工具走 `repair_changed_duties`（`build_charge_timing_comparison.py:563,612`），
  会命中 `_latest_trip_departure_second` 的两个调用点。上界若卡到了 `asap` / `cost_plus_carbon`
  这两条正式策略，这里立刻炸。
- **不覆盖 A(1)(2)(3)(4)**：该工具**不跑路线搜索**，一行都不碰 `kernel_proposals.py`。
  路线代理的回归靠 D.1a（结构性）+ §A(2) 的默认 `None`（结构性），不靠这条。
- **另加一条**：`.public-hgs-venv/bin/python3 -m pytest solver/tests -q` 全绿。
  仓库里有 45 个测试文件，其中三个（`test_problem_hgs_reload_gap.py`、
  `test_problem_hgs_kernel_native.py`、`test_problem_hgs_ev_charge_time_and_lock_pins.py`）
  会以 `shift_aware_ev_unit_cost_enabled=True` 建引擎且不传策略——它们绿灯就是默认 `None` 生效的证据。

### D.3 run_02 重评价：`return_second` 与下一趟 `charge_start_second`

改完 A(5) 后，用午谷日历重建 context，加载
`solver/reports/ideal_construction_20260904/P=0.2/MTC-HGS/run_02/best_solution.json`
评价一次，落盘的 `trip_clock` 必须满足：
- **点名断言**：`EV_D_OSM_WAY_1071205721_4` 的 T2 `return_second` = **54247.51454**，
  与该 duty T3 的 `charge_start_second` **差 < 1 s**（我实测差 7.3e-12 s）；
- **全局断言**：每个 duty 每条 `trip_index > 首趟` 的车场会话满足
  `charge_start_second ≥ 前一趟 return_second − 1e-6`（**单侧**，理由见 §A(5)）；
- **同一次复算的 `cost_elec` 必须 = 131.89278030877944**（逐位），否则说明 context 建错了。

**破线处置：** 点名断言差 ≥ 1 s → **立刻停工回报**。整份诊断的时刻链条都建在
「趟间起充下界 = 上一趟回场」上；这条不成立，A(6) 与后面所有判读全部要重来。

### D.4 `carbon_min` 由不可行变可行，且正式策略逐位不变

**改前状态我已实测**（30 秒探针，见 `cm_violation_probe.py`；也可用工具复现：
`build_charge_timing_comparison.py --batch-dir solver/reports/ablation_formal_10x_v5_20260904
--policies asap,carbon_min --runs run_04`，会打印
`MT-HGS/run_04  no comparable pair; infeasible under ['carbon_min']`）：

```
MT-HGS/run_04 @ carbon_min → 不可行
VIOLATION TIME_WINDOW  EV_D_OSM_WAY_1071205721_7#T2  'returns after AM end; late by 118.6639562 s'
```

**改后要求（两条，全要）：**
- **(a) 生效**：同一次重排 `MT-HGS/run_04 @ carbon_min` **可行**（`violations` 为空）。
  手算预期：`ceiling − span` = 39600 − 3087.50 = 36512.50，`latest` = 35881.34，
  `earliest` = 35062.90，窗口非空，所以应当是「另选一个更早的起充」而**不是**
  `NO_FEASIBLE_WINDOW`。若结果是后者，说明 `span` 取错了侧，回滚重做。
- **(b) 不误伤**：午谷批 `solver/reports/ideal_construction_20260904/P=0.2/{MT-HGS,MTC-HGS}/run_*`
  共 **20 个解**，按各自的正式策略（MT→`asap`，MTC→`cost_plus_carbon`）重排后
  `cost_elec` **逐位不变**、`infeasible_under_policy` 仍为 0。
  参照值（我已复算，可直接当断言）：`MT-HGS/run_02` = 121.3904180006173，
  `MTC-HGS/run_02` = 131.89278030877944。
  **任一解的 `cost_elec` 变了 → 上界卡到了正式策略，回滚。**

### D.5 短跑：午谷日历 × P=0.2，**每臂 3 次**（这是唯一要开搜索的一步）

配置与 `solver/reports/ideal_construction_20260904/P=0.2` 那一批**完全一致**，只多带本次改动。
每臂 3 个新种子（或复用 run_01/02/03 的种子，二选一，写死在派工信里）。

**判定线（用户已定，照做）：**

| # | 指标 | 线 | 十次基线（我已复算） |
|---|---|---|---|
| 1 | MTC-HGS 3 次总成本均值 | **≤ 2595** | 均值 2605.61、sd 17.09、区间 2579.91–2625.63 |
| 2 | MTC-HGS 车队构成 | **(2CV,3EV) ≥ 2/3 次** | 十次里 (2,3) 占 6、(3,3) 占 3、(2,4) 占 1 |
| 3 | MT-HGS 3 次总成本均值 | **与 2662.76 差 < 13** | 均值 2662.76、sd 6.48、区间 2650.93–2672.56 |
| 4 | 速度 | 两臂 `run_wall_seconds` 3 次均值 **≤ 基线均值 × 1.1** | MTC 均值 396.5 s（线 436.2）、MT 均值 440.1 s（线 484.1） |

**这四条线的真实功效（实测数字，不是意见，派工信里要一起写上，免得误读结果）：**
- 线 1：3 次均值的抽样标准误 = 17.09/√3 = **9.87**。在「什么都没变」的零假设下
  `P(3次均值 ≤ 2595) = 14.1%`。**即约七分之一的概率会白捡一个「通过」。** 它是弱线，不是强证据。
- 线 3：MT 的 3 次均值标准误 = 6.48/√3 = **3.74**；在零假设下
  `P(|3次均值 − 2662.76| < 13) = 99.95%`。**这是一条真正的守门线**，
  专门守 §E 风险 1（asap 臂 PM 代理翻倍会不会把车队推坏）。
- 线 4：`run_wall_seconds` 十次 sd = **121.2 s**，3 次均值标准误 = **70 s**；
  而 1.1× 只比均值高 39.7 s = 0.57 个标准误。**零假设下这条线的误判失败率约 28.5%。**
  同时本改动**在内核内循环里不增加任何一次调用**（`_rebuilt_shift_aware_ev_unit_costs`
  每个车场每轮只跑一次，遍历 ≤16 行；`ev_unit_cost_override` 分支同理），
  所以速度回归在代码形状上是可证明为零的。
  **建议（请用户拍板，不擅自改）**：线 4 改成两条并报——
  (i) 代码形状核对：`algorithm.run(...)` 调用链里没有新增函数调用（人工 diff 核）；
  (ii) 兜底线放宽到「基线均值 + 1 sd」（MTC 517.8 s、MT 561.3 s，零假设下误判率 4.2%）。
  在用户表态前，**按用户原线 1.1× 执行，但破线时先报「疑似噪声」再决定，不自动判死**。

**另加两条硬约束（来自 `route_effect_design_review_20260904.md` 角度 6，实测重算过基线）：**
- 总趟数：3 次均值不得高于基线（run_02：3 辆电车 8 趟）；
- `cost_km`：MTC 3 次均值 ≤ 十次基线均值 + 1 sd = 879.80 + 55.04 = **934.84**；
  MT 3 次均值 ≤ 833.58 + 56.16 = **889.74**。
  （注意：MT 的 `cost_km` 基线是 **833.58 ± 56.16**，不是评审里写的 879.80——那是 MTC 的。）

**线 3 破了怎么读（必须先判别，不许直接判「改坏了」）：**
本改动把 MT 的 PM 电动车弧代理从 0.59621 抬到 1.18460（§C 的符号翻转），
所以 **MT 的车队发生变化本身就是这个改动的预期结果，不是异常**。判别用 §C 的两个钱数：

| 量 | 值（run_02，元/跑） | 含义 |
|---|---:|---|
| 现行低估被纠正的部分 | 0.45790 × 85.2309 = **39.03** | 改动**该**产生的驱动力 |
| 改后高估的残差 | 0.13050 × 85.2309 = **11.12** | 改动**不该**产生的那部分 |

- **属于「如实定价」**（报给用户，但不判失败）：MT 三次总成本相对 2662.76 的移动**大于 11 元**，
  且方向是 `n_veh_ev` 下降 / `cost_elec` 下降、`cost_fuel`+`cost_fix` 上升。
  量级上 11 元的高估残差**解释不了**一次 70–170 元/辆的车队换挡，主导项只能是那 39 元的纠偏。
- **属于「推坏了」**（判失败，回滚 A(1)(2)）：总成本上升但油电分工方向与上面相反，
  或 `cost_km` 同时突破下面那条硬约束线（MT 889.74 元），说明抬价把车推去绕路了。
两条都拿不准 → 按「数据不足以判定」上报，等用户拍板，**不要自行加跑第 4 次**。

**任一破线 → 停工，把破的那条与三次逐值一起回报，不自行调参重试。**

### D.6 长跑（每臂 10 次）

**只在 D.1–D.5 全过、并且用户明确批准之后才开。** 不在本规格的授权范围内。

---

## E. 风险与回滚；公开算例隔离声明

### E.1 风险清单

| # | 风险 | 量级（实测） | 触发信号 | 处置 |
|---|---|---|---|---|
| 1 | **asap 臂的 PM 代理翻倍（0.59621 → 1.18460）把 MT 的车队推坏** | 固定成本档差 70–170 元/辆，比择时那 10 元大一个数量级；MT 十次 `cost_fix` 均值 1229.00、sd 93.03 | D.5 线 3（MT 3 次均值与 2662.76 差 ≥ 13） | 回滚 A(1)(2)，保留 A(5)(6)；把「asap 臂是否也用策略感知代理」做成选择题交用户 |
| 2 | **MTC 的 AM 代理降 28.5%（0.95342 → 0.68203）把油电分工推歪** | 同上；MTC 十次 `cost_fix` 均值 1228.00、sd 104.75 | D.5 线 2（(2CV,3EV) 不足 2/3） | 同上 |
| 3 | **A(6) 的上界卡到正式策略** | 上界只会让窗口变窄，本质上**只会增加** `NO_FEASIBLE_WINDOW` | D.2 有差异，或 D.4(b) 里任一解 `cost_elec` 变了 | 只回滚 A(6)（三个调用点改回不传 `shift_return_ceiling_second`），其余保留 |
| 4 | **A(3) 的比例校正放大** | run_02 实测 factor 0.93–1.07 | 任一轮 `factor` 偏离 1 超过 25% | 该轮降级为写法乙（不覆盖分班次值），落盘一条 `accounting` 告警 |
| 5 | **A(5) 的一致性断言写成双侧** | `cost_plus_carbon` 下起充可以晚于回场（run_02 T2 起充 46800.0 s ≫ T1 回场 35343.8 s） | 断言在正常解上就炸 | 断言必须是单侧 `≥`；点名等号只对 run_02 T3 那一笔 |
| 6 | **并列决胜改向导致台账槽号变化被误读成回归失败** | 北京/均一下 `cost_plus_carbon` 的 `selected_slot` 390→360、750→720，`proxy_cny_per_kwh` 逐位不变 | D.1c | 不是回归失败；在 D.1c 里显式断言「值不变、槽号变」 |
| 7 | **趟间充电的口径误差仍在**（每臂约 11 元/跑） | §C 实测 11.12 / 11.69 元 | 无（已知残留） | 不在本次范围；在交接里登记为下一件事，不许顺手加第三个窗口 |

### E.2 公开算例隔离声明

- `solver/scripts/run_problem_hgs_public_technical.py` 第 13–14 行的全部 import 是
  `from setp_hgs_kernel import GeneticAlgorithmParams, SolveParams, read, solve` 与
  `from setp_hgs_kernel.stop import NoImprovement`。**它一行都不 import `setp_solver`。**
- 本规格改动的六个位置全部落在 `solver/src/setp_solver/**` 与
  `solver/scripts/run_problem_hgs_private_technical.py`，**没有一处在公开路径上**。
  **表 7 的回填数字不会变，也不需要重跑。**
- **交付前必核（写进派工信的收尾清单）：**
  1. `git status --porcelain third_party/` **必须为空**；
  2. `git diff --stat` 的文件清单只能出现：
     `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py`、
     `solver/src/setp_solver/algorithms/problem_hgs/charging.py`、
     `solver/scripts/run_problem_hgs_private_technical.py`、
     一个新测试文件、以及本次要同步的两份文档；
  3. `cost.py` / `check.py` / `search/**` / `evaluation.py` 的 SHA256 与改动前相同。

### E.3 回滚粒度

四段改动**分四条 commit**，任一条可单独 revert：
`C1 = A(5) 落盘` → `C2 = A(6) 班次上界` → `C3 = A(1)(2)(4) 策略感知代理` → `C4 = A(3) override 不抹平`。
**顺序不许换**：C1 是 C2/C3 的观测手段；C2 与 C3 互不依赖但 C2 更便宜、验收更硬，先做；
C4 依赖 C3（没有分班次结构就没有「不抹平」这回事）。

---

## F. 工时估计

| 段 | 内容 | 编码 | 验证 | 小计 |
|---|---|---:|---:|---:|
| C1 | A(5) 落盘 `trip_clock` + 单侧断言 | 0.5 h | D.3　0.5 h | **1.0 h** |
| C2 | A(6) 班次上界（新函数 + 3 个调用点） | 1.5 h | D.4　1.0 h（探针 30 s，含写断言） | **2.5 h** |
| C3 | A(1)(2)(4) 策略感知代理 + 参数链 + `source_id` + 台账落盘 | 2.0 h | D.1 写测试 1.5 h + D.2 回归 0.5 h | **4.0 h** |
| C4 | A(3) override 比例校正 + 不稳定降级 | 1.0 h | 并入 D.5 | **1.0 h** |
| — | D.5 短跑 6 次 | — | 挂机约 45 min（基线单跑 284–713 s，两臂各 3 次，可并行）+ 分析 0.5 h | **1.3 h** |
| — | 两份文档同步（删「救回 NO_FEASIBLE_WINDOW」、改 docstring、`CURRENT_PROJECT_CONTEXT` + `HANDOFF` 变更日志 + `MEMORY` 证据入口） | 0.5 h | — | **0.5 h** |
| | | | **合计** | **≈ 10.3 h**（其中挂机 0.75 h） |

按仓库的施工纪律，C1–C4 是四封独立派工信；**C3 属于「需判断」的改动**
（并列决胜方向、默认值语义、参数链层次），按强度分档不得低于 xhigh；
C1、C2、C4 是照规格落地，medium 即可。

---

## 附：本规格所有数字的复算入口

| 数字 | 出处 / 复算方式 |
|---|---|
| §B 全表 12 格 | `scratchpad/policy_proxy_truth.py`（三份日历各建一次 context，读 `context.rebuilt_route_constraints.shift_window_second_by_id` 与 `time_profile_rows_for_node`） |
| `cost_elec` 逐位相同（两臂 run_02） | 同上脚本 `settle()` 恒功率分槽重算：121.390418 / 131.89278031 |
| §B.3 / §C 的实付分桶均价 | 同上脚本，按「该趟是否本车最小 `trip_index`」分桶 |
| §C 加权 MAD 0.31042→0.08737 / 0.15397→0.05472 | 同上脚本输出 + 按 kWh 加权 |
| T2 `return_second` = 54247.51454 | `scratchpad/trip_clock_probe.py`，`FullEvaluation.certificate.trips` |
| run_04 `carbon_min` 迟到 118.6639562 s + 逐趟时钟 | `scratchpad/cm_violation_probe.py`；工具复现 `build_charge_timing_comparison.py --policies asap,carbon_min --runs run_04` |
| 十次基线（总成本 / `cost_km` / `cost_fix` / `run_wall` / 车队构成） | 直接扫 `solver/reports/ideal_construction_20260904/P=0.2/*/run_*/{best_solution,metadata}.json` |
| D.5 各线的零假设通过率（14.1% / 99.95% / 28.5% / 4.2%） | `statistics.NormalDist(基线均值, sd/√3)` |
| 公开算例隔离 | `solver/scripts/run_problem_hgs_public_technical.py:13-14` |
| 内核弧成本标度 1e-5 元 | `kernel_proposals.py:44` `_ROUTE_COST_SCALE = 100_000` |
