# T13 剩余 5 项门禁失败根因诊断

## 范围与执行边界

`FACT` 本轮只读。没有修改任何 `.py` 源码、测试文件或既有结果目录；诊断脚本和输出仅写入本目录。定向 pytest 使用 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONHASHSEED=0`、`PYTHONPATH=solver/src:models/src`，并以 `-p no:cacheprovider` 禁止 pytest 缓存。

`FACT` 三项受保护文件本轮开工与收工 SHA-256 均逐位不变：`solver/src/setp_solver/cost.py` = `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`；`solver/src/setp_solver/check.py` = `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`；`solver/src/setp_solver/search/evaluation.py` = `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

`FACT` 五项定向测试实测为 `5 failed`：甲类 2 项均由 `CHARGING_TRIP_OVERLAP` 失败；乙类 3 项均在 `HALT_H2: no feasible EV route with a nonzero charging action` 处退出。逐字 pytest 输出见 `targeted_pytest_output.txt`，结构化复算见 `diagnostic_observations.json`。

## 甲类：两项精细充电测试的真正违反对象

### 证据链

`FACT` 两项测试自己构造同一个微型算例：`test_refined_carbon_charging.py:150-177` 和 `:204-244`；节点逐字为 `D0`（`d`）、`C1`（`c`）、`F1`（`f`），初始路线逐字为 `['D0', 'C1', 'D0']`，电池上限为 `80.0 kWh`。

`FACT` 第一项 `test_integrated_route_repair_inserts_station_and_remains_fully_feasible` 修复后路线逐字为 `['D0', 'F1', 'C1', 'D0']`。被判违反的动作不是公共站动作，而是：

| 字段 | 实际值 |
|---|---|
| `station_id` | `D0` |
| `node_type` | `d` |
| `physical_station_id(node)` | `D0` |
| `route.node_sequence` | `['D0', 'F1', 'C1', 'D0']` |
| `station_id in node_sequence` | `True` |
| 充电区间 | `[8000.000000000000, 21090.909090909090)` |
| 外行程区间 | `[0.000000000000, 10492.783666140434)` |
| 实际相交秒数 | `2492.783666140434` |

`FACT` 第二项 `test_refined_reset_and_reconstruction_consumes_one_candidate_evaluation` 的修复后路线逐字仍为 `['D0', 'F1', 'C1', 'D0']`。被判违反的动作仍是车场动作：

| 字段 | 实际值 |
|---|---|
| `station_id` | `D0` |
| `node_type` | `d` |
| `physical_station_id(node)` | `D0` |
| `route.node_sequence` | `['D0', 'F1', 'C1', 'D0']` |
| `station_id in node_sequence` | `True` |
| 充电区间 | `[9000.000000000000, 22090.909090909090)` |
| 外行程区间 | `[0.000000000000, 10492.783666140434)` |
| 实际相交秒数 | `1492.783666140434` |

`FACT` 两项中的公共站动作逐字为 `station_id='F1'`、`node_type='f'`、`physical_station_id='F1'`，且逐字出现在相应路线 `['D0', 'F1', 'C1', 'D0']` 中。第一项公共站动作区间为 `[5400.000000000000, 5692.783666140434)`；第二项同样为 `[5400.000000000000, 5692.783666140434)`。该动作满足 `node_type == 'f'`、`station_id in node_sequence`、`charge_day_offset == 0`，因而确实命中 `check.py:453-460` 的跳过分支；它不是两项失败的违反对象。

`FACT` 没有副本编号错配。`station_copies.py:12-13` 的物理站点映射是 `physical_station_id or node_id`；副本生成写法在 `station_copies.py:33-41`，会产生形如 `S__visit_2` 并把物理站点写回 `S`。本微型算例没有任何 `__visit_` 节点：车场两边都是 `D0`，公共站两边都是 `F1`。所以不存在“动作使用副本编号、路线使用原编号”的字符串差异；逐字字符串分别就是 `D0`/`D0` 和 `F1`/`F1`。

`FACT` 新检查由 `check.py:118-124` 调用，函数定义及区间比较在 `check.py:410-490`。该函数先用 `route_timing` 形成实体车的外行程区间（`check.py:433-446`），再对未命中公共站跳过分支的动作执行半开区间相交判断（`check.py:474-477`）。由于真正违反动作的 `node_type` 是 `d`，它不会进入公共站跳过分支；具体命中的是车场动作的 `CHARGING_TRIP_OVERLAP` 分支，而不是副本识别失败。

`INFERENCE` 甲类的成因已闭合：这两项测试的“插入站”路线同时带有一个 `D0` 车场动作和一个 `F1` 在途公共站动作；新增检查正确跳过了 `F1`，但仍把 `D0` 充电动作与同一条路线的外行程比较。被拒绝的两个相交量分别约 `2492.784 s` 和 `1492.784 s`，远大于 `1e-9` 容差，因此不是浮点尾数，也不是公共站副本编号问题。

## 乙类：三项 `HALT_H2` 的生成侧根因

### HALT 的位置和判定条件

`FACT` `HALT_H2` 只在 `solver/src/setp_solver/search/construction.py:211-214` 抛出。其前置逻辑是 `:184-210`：遍历客户和车场，先用 `energy <= battery_cap + 1e-9` 跳过不需要充电的路线（`:188-194`），调用 `repair_route_charging`（`:195-198`），将路线和动作归一化后调用 `check_solution(candidate, instance, prices)`（`:201-208`）；有任何违反就丢弃候选，只有通过检查的候选才进入 `candidates`。`candidates` 为空且 `require_charging_signal=True` 时，才抛出该 HALT。

`FACT` 三项测试都在这条共同路径上失败：H2 在 `test_search.py:278-286`，M0 在 `:289-299`，H3 在 `:428-441`；三项均首先调用 `build_initial_solution`，都没有进入 H3 的 ALNS 调用或 M0 的后续 EV-heavy 循环。

### 最小确定性复现：`D0 → C3 → D0`

`FACT` 该 fixture 的车场开门时刻为 `D0.ready_time = 0.0`、`D1.ready_time = 0.0`，车场日内 `due_time = 32400.0`；公共站 `F1/F2/F3` 均为 `node_type='f'`、`ready_time=0.0`、`due_time=32400.0`、`charge_power_kw=60.0`。该 fixture 的电池容量为 `80.0 kWh`。

`FACT` 确定性见证候选的基础路线逐字为 `['D0', 'C3', 'D0']`，直接行驶能耗为 `83.48426334435885 kWh`，比 `80.0 kWh` 上限多 `3.48426334435885 kWh`，因此确实会进入“需要非零充电”的分支。修复器生成的路线逐字为 `['D0', 'F2', 'C3', 'D0']`，动作逐字字段为：

| `station_id` | `node_type` | `physical_station_id` | 充电区间 | 能量 |
|---|---|---|---|---:|
| `D0` | `d` | `D0` | `[9073.829432129312, 22164.738523038402)` | `80.000000000000 kWh` |
| `F2` | `f` | `F2` | `[8789.676303253189, 9000.000000000000)` | `3.505394945780196 kWh` |

`FACT` 生成器计算出的充电窗口在 T10 前后相同，且都不是空窗：

| 窗口 | T10 前 `[earliest, latest]`（秒） | T10 后 `[earliest, latest]`（秒） | 窗口宽度 |
|---|---:|---:|---:|
| 车场 `D0` | `[9073.829432129312, 22442.061476961600]` | `[9073.829432129312, 22442.061476961600]` | `13368.232044832288` |
| 公共站 `F2` | `[425.791628461898, 22381.093839624275]` | `[425.791628461898, 22381.093839624275]` | `21955.302211162376` |

`FACT` 这两个窗口的公式位于 `solver/src/setp_solver/search/charging.py:468-522`：车场窗口由无充电返场时刻与下一周期出发时刻减充电时长给出（`:508-511`）；公共站窗口由到站时刻、站点/客户截止时刻和站到客户行驶时间给出。当前工作树相对 T10 前基线在该文件的差异仅为 `_curve_aware_action` 的导入位置，未改变这些窗口公式；诊断脚本按同一公式把前后数值逐项复算。

`FACT` 相关路线时钟有两个必须区分的数值。生成车场窗口使用的无公共充电路线时钟是：`route_departure_second = 3132.970567870687`、`route_return_arrival_without_charging = 9073.829432129312`。而新增重叠检查通过 `route_timing(..., charging_actions=...)` 看到的、包含在途 `F2` 充电占用的外行程区间是 `[0.000000000000, 14516.411895758229)`；因此 `D0` 动作从无公共充电返场边界 `9073.829432129312` 开始，却落在“包含 F2 在途充电”的路线区间内。

`FACT` 关闭新增 `_check_charging_trip_overlap` 后的最小反事实中，`C3` 候选的其他检查违反为空，候选通过；打开当前检查后，唯一新增违反是：`CHARGING_TRIP_OVERLAP`，充电区间 `[9073.829432129312, 22164.738523038402)` 与外行程 `[0.000000000000, 14516.411895758229)` 相交 `5442.582463628917 s`。公共站 `F2` 动作逐字满足 `node_type='f'`、`station_id='F2'` 出现在 `['D0', 'F2', 'C3', 'D0']`、`charge_day_offset=0`，命中跳过分支；真正新增违反仍是 `D0` 车场动作。

`FACT` 对 50 个客户—车场候选的完整枚举为：24 个能耗超过 80 kWh；12 个成功构造了带动作的候选；12 个在充电修复阶段抛出异常；当前检查器下 0 个候选通过。仅关闭新增重叠检查时恰有 1 个候选通过，即确定性 `C3@D0`；该候选正是测试注释在 `test_search.py:284` 指定的 `['D0', 'F2', 'C3', 'D0']`。其余候选的既有 `CHARGING_START` 或 `STATION_CAPACITY` 违反不属于本轮新增根因。

`INFERENCE` 乙类不是“测试算例窗口变空/变负”，也不是 T10 生成器把这类窗口普遍改窄：确定性候选的车场窗口宽 `13368.232044832288 s`、公共站窗口宽 `21955.302211162376 s`，且 T10 前后逐位相同。三项之所以报告“没有生成出带充电的可行 EV 路线”，是因为生成路径把 `check_solution` 放在候选入池之前（`construction.py:201-210`）；新增检查把本来能通过旧检查的 `C3@D0` 候选丢掉，随后共同的空候选分支抛出 `HALT_H2`。因此支持证据指向“新检查器与在途公共充电/车场预充电时间语义的交互”，不支持“算例太小太紧”或“普遍适用窗口被生成器改窄”这两个判断。

## 结论与状态

`FACT` 甲类两项：违反动作是 `D0` 车场充电，字符串和物理站点均一致，没有副本编号问题；`F1` 在途公共站动作命中跳过分支。实际相交为 `2492.783666140434 s` 与 `1492.783666140434 s`。

`FACT` 乙类三项：`HALT_H2` 在 `construction.py:213` 抛出；确定性 `C3@D0` 候选的生成窗口前后相同且非空，旧检查反事实通过，当前新增检查只新增 `CHARGING_TRIP_OVERLAP` 并把该候选排除。

`DECISION` 本轮只完成根因证据，不改变源码、测试、结果和模型口径；`paper_claim_allowed = false`。

`HALT_REGRESSION_FAILED` 定向门禁仍保持 `36 passed / 5 failed` 的 T12 起点状态；本轮没有将诊断结果误报为回归恢复，也没有触发 `HALT_ROOT_CAUSE_NOT_FOUND`。
