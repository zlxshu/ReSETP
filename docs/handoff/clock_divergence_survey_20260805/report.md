# T14 时钟分歧点调查

## 范围与算例

`FACT` 本次只读取并运行了任务指定的六个量。没有修改 `.py` 源码、测试文件或既有结果目录；没有运行 pytest、求解器批次、成本/能耗/电价/碳核算审计。

`FACT` 采用两个算例，未增加第三个：

- `E1`：T13 最小复现，`verify_20251113` 中 `D0→F2→C3→D0`，`B_battery_kwh=80.0`。
- `E2`：已归档 `cn-jjj-50c-01-V2-LOCATIONS`、日期 `2025-02-12`、运行 `O_seed2_budget1000`。使用它是因为 C 路径需要 China81 bundle；该见证路线无在途公共站充电动作。

`FACT` 所有表内数值均来自本目录 `diagnostic_observations.json` 和 `diagnostic_trace.txt` 的实际运行输出；秒数保留运行结果精度。

## 六个量对照表

| # | 量 | A = 排班证书：`search/multitrip_schedule.py` | B = 通用构造路径：`search/construction.py` + `search/charging.py` | C = China81 补全路径：`china81_completion.py` + `algorithms/resetp_alns/support/charging.py` | 三者是否一致；两两差值 |
|---:|---|---|---|---|---|
| 1 | 单趟出发时刻 | `FACT` 位置：`multitrip_schedule.py:365-472`。`route_timing` 从车场 ready/service 起点和客户时间窗反推可行出发，再前向重放；有公共站动作时固定为车场 ready+service（`428-429`）。E1：`0.000000000000 s`。E2 EV：`42560.108380000000 s`。 | `FACT` 位置：`search/charging.py:182-210, 263-282`。从起点 `time_s=origin.ready_time` 开始，车场预充电不推进当前日路线时钟，随后按行驶/服务/公共站充电更新内部 `time_s`。E1：`0.000000000000 s`；E2 通用构造自身前向时钟：`21600.000000000000 s`。若把该路线送入 A 的 `route_timing` 重放，则会得到 `42560.108380000000 s`，那是 A 值，不是 B 自身值。 | `FACT` 位置：补全调用 `china81_completion.py:273-343`；support 自身从 `origin.ready_time` 开始，E2 C 前向时钟为 `21600.000000000000 s`。`exact_china81_score` 的物理化入口 `china81_completion.py:89-142,145-184` 随后委托 A，故其证书出发值为 `42560.108380000000 s`。E1：不计算（无 China81 bundle）。 | `FACT` E1 A=B，差 `0 s`。E2 按三条路径自身时钟：A-B `20960.108380000000 s`，A-C `20960.108380000000 s`，B-C `0 s`；C 进入 exact score 后委托 A，委托值与 A 差 `0 s`。 |
| 2 | 单趟返场时刻；是否计入在途公共站充电占用 | `FACT` 位置：`multitrip_schedule.py:477-613`。前向重放中，公共站动作使 `depart=action_start+occupancy`（`497-536`），所以返场计入在途公共站占用。E1：`14516.411895758229 s`，计入 F2 占用。E2 EV：`58990.435100000000 s`，无公共站动作。 | `FACT` 位置：`search/charging.py:201-282` 的 `time_s` 前向更新；E1 的实际路线时钟重放为 `14516.411895758229 s`，计入 F2 占用；E2 为 `58990.435100000000 s`，无公共站动作。`FACT` 但车场窗口使用的另一个返场锚点由 `search/charging.py:468-522` 调用 `route_return_arrival_without_charging`，E1 为 `9073.829432129312 s`，不计入 F2 占用。 | `FACT` C 生成器本身返回路线和动作，单趟返场值由 `china81_completion.py:89-142` 进入 A 证书时得到。E1：不计算；E2：`58990.435100000000 s`，该算例无公共站动作。 | `FACT` E1 A 与 B 的实际返场一致，差 `0 s`；B 的车场窗口锚点与该实际返场相差 `5442.582463628917 s`（不含在途公共充电 vs 含在途公共充电）。E2 A=B=C，差 `0 s`。 |
| 3 | 车场充电可行窗口 `[earliest, latest]` | `FACT` 位置：首趟/终端充电重排窗口在 `multitrip_schedule.py:2057-2083`，使用静态前置日 `[0,86400-duration]`；趟间窗口在 `2101-2105` 使用 `[previous.return, current.departure-duration]`。E1：该单趟证书未计算首趟车场窗口。E2 首趟 Beijing EV 见证动作持续 `4539.575210877782 s`，窗口实际为 `[0.000000000000, 81860.424789122220] s`。 | `FACT` 位置：`search/charging.py:468-522`，车场窗口为 `[route_return_arrival_without_charging, route_next_day_departure-occupancy]`。E1：`[9073.829432129312, 22442.061476961600] s`；E2：`[58990.435099999995, 208491.018289122200] s`。 | `FACT` 位置：`support/charging.py:557-657`；China81 补全在 `china81_completion.py:330-343` 明确传入 `depot_charge_window_mode="same_day_predeparture"`，故窗口为 `[0, route_departure_second-occupancy]`。E1：不计算；E2 Beijing EV 为 `[0.000000000000, 35691.018289122214] s`，路线出发锚点 `40230.593499999995 s`。 | `FACT` 不一致。E2 端点差：A-B 为 earliest `58990.435099999995 s`、latest `126630.593499999980 s`；A-C 为 earliest `0 s`、latest `46169.406500000006 s`；B-C 为 earliest `58990.435099999995 s`、latest `172800.000000000000 s`。E1 直接可比的 B 窗口与 A/C 均为“不计算”。 |
| 4 | 在途公共站充电可行窗口 `[earliest, latest]` | `FACT` 位置：`multitrip_schedule.py:392-417,497-536`。A 对已有公共站动作检查“到达后开始、截止前结束”，但不输出独立的 `[earliest,latest]` 窗口。E1：不计算独立窗口；实际 F2 动作区间为 `[8789.676303253189,9000.000000000000) s`。E2：不计算（无公共站动作）。 | `FACT` 位置：`search/charging.py:640-763`，公共站窗口为 `earliest=max(arrive,ready)`，`latest=min(station_due,target_due-occupancy-travel)`（`718-723`）。E1 F2：`[425.791628461898,22381.093839624275] s`；E2：不计算（无公共站动作）。 | `FACT` 位置：`support/charging.py:860-967`，同样按站点到达、站点/目标截止和站到目标行驶时间形成窗口。E1：不计算（无 China81 bundle）；E2：不计算（该归档路线无公共站动作）。 | `FACT` E1 只有 B 产生独立公共站窗口；A 只校验动作、C 未适用。E2 三者均没有该算例的 C/A/B 公共站窗口数值，不能作数值一致性比较。 |
| 5 | 同一实体车第 k 趟出发与第 k−1 趟返场的衔接约束 | `FACT` 位置：`multitrip_schedule.py:1090-1219`。候选复用要求 `current.earliest_departure - previous.available >= 0`（`1104-1110`）；趟间充电时再要求充电区间位于返场到下一趟出发之间（`1143-1158`）。E1：不计算（只有一趟）。E2：`CV_D_beijing_1` 的 T1 返场 `50586.927240000000 s`，T2 出发 `50609.736460000000 s`，间隔 `22.809220000003 s`，约束为真。 | `FACT` `search/construction.py:162-218` 与 `search/charging.py:182-282` 按路线逐条构造，没有同一实体车多趟排班/衔接计算。E1：不计算；E2：不计算。 | `FACT` C 的单路线补全位置为 `china81_completion.py:273-343`；实体车多趟衔接不在 support 补全器内，`exact_china81_score` 通过 `china81_completion.py:103-184` 委托 A 物理化。E1：不计算；E2：委托 A 后得到同一条 `22.809220000003 s` 间隔。 | `FACT` E2 A 与 C 的证书结果一致（差 `0 s`）；B 不计算该量，不能把 B 缺少该计算误报为数值相等。 |
| 6 | 跨日偏移 `charge_day_offset` 的取值规则及其对时段表取值的影响 | `FACT` 位置：常量 `multitrip_schedule.py:44`；公共站必须为 `0`（`406-408`）；首趟车场充电证书固定 `-1`（`1024`），趟间 ledger 使用 `0`（`847-853`）。按日历重排时，`2042-2048` 以偏移键选择 profile，首趟用动作自身偏移（`2078-2083`），趟间用 `0`（`2110-2117`）。E1 公共站动作实际为 `0`；E2 首趟车场窗口动作偏移 `-1`，趟间规则为 `0`。 | `FACT` 位置：`ChargingAction` 默认字段 `solution.py:37-46` 为 `0`；`search/charging.py` 不按偏移键切换 profile，而是直接把传入的单一 `gamma_profile` 用于窗口/选时。E1、E2 生成动作均为 `0`；E2 B 车场动作实际起始 `122091.018289122200 s`。因此 B 的 `0` 只保留当前传入时段表，不触发 A 式的 `-1/0` 多 profile 选择。 | `FACT` 位置：`support/charging.py:608-615` 选择 China81 注册日的 `[0, route_departure-occupancy]`，`653-656` 明确把生成动作写成 `charge_day_offset=0`；C 使用传入的 `bundle.time_profile`，不在补全器内按偏移键切换时段表。E2 C 生成动作偏移为 `0`。归档输入见证的旧车场动作虽为 `-1`，但那不是本次 C 补全生成值。 | `FACT` E2 不一致：A 首趟 `-1`、B `0`、C 生成 `0`；偏移两两差：A-B `1` 日=`86400 s`，A-C `1` 日=`86400 s`，B-C `0`。`INFERENCE` 对时段表的直接差异仅在 A 的日历重排路径：`-1` 查前一日 profile，`0` 查运行日 profile；B/C 均直接使用各自传入的单一 profile。 |

## 结论标签

`FACT` 本轮闭合的直接分歧是：B 的车场窗口以“不含在途公共站充电”的返场锚点计算，而 A 的单趟外行程时钟在存在公共站动作时包含该占用；C 的 China81 补全把车场窗口切换为注册日出发前窗口，并将生成动作偏移固定为 `0`，实体车多趟衔接则委托 A 的物理化证书。

`INFERENCE` 在 E1 中，`14516.411895758229 - 9073.829432129312 = 5442.582463628917 s` 是同一路线的“含在途公共充电外行程返场时刻”与“无在途公共充电车场窗口起点”的差，不是两个独立路线的差。

`DECISION` 本目录只记录时钟分歧事实；不记录修复方案、后续任务、成本口径、能耗、电价、碳核算、算法逻辑或测试覆盖结论。`paper_claim_allowed=false`。

`HALT_SCOPE_LIMIT_REACHED` 六个量、两个算例和指定产物已完成；按任务限幅停止。
