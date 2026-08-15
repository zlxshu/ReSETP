# DSS v2 第 1 步技术方案稿：排程见证、单车 Oracle 与被改车辆协调

> 状态：Codex 技术方案草稿，供 Claude 裁决与后续施工使用；不是生产实现，也不表示未决技术选择已获用户批准。
>
> 本稿范围：仅覆盖 v2 第 1 步。本文不修改生产代码，不运行求解器，不改评价、可行性或成本口径。

## 一、方案概要

本步把“路线序列”与“这条路线怎样在一天内真实执行”分开表示。现有 `DutyIndividual` / `DutyTrip` 继续承载车辆、车场、行程与客户序列身份；新增的排程见证 `ScheduledDuty` 伴随其存在，显式给出每趟发车和回场时刻、连续 SOC 轨迹及充电会话。单车排程 Oracle 针对一辆被改车辆生成非支配排程前沿；协调器在扣除未改车辆既有充电占用后，从多辆被改车辆的前沿中选择一个联合可行组合。任何层级找不到合格结果，都拒绝本次候选，不在评价阶段暗中修路线、时间或充电。

总体数据流如下：

`交叉或教育移动产生被改 Duty` → `单车 Oracle 生成各车排程前沿` → `协调器扣除未改车辆占用并联合选取` → `形成 ScheduledDuty 排程见证` → `完整评价与不得暗修核验` → `prepare_multitrip_solution 重放`

本文逐项明确对象表示、事件集与标签递推、联合协调、四处接入、确定性缓存、工作量记账、首批重放考题和性能预算。凡现有源码和证据不能唯一确定、或存在多个会改变实现含义的可行选择，统一放入末尾“待 Claude 裁决”，本文不代替 Claude 或用户拍板。

## 二、ScheduledDuty 正式表示

### 2.1 与现有 DutyIndividual / DutyTrip 的关系

**现状。** `DutyTrip` 只保存趟号、客户序列、动态锁定客户前缀和完整访问序列（`solver/src/setp_solver/algorithms/problem_hgs/model.py:33-77`）；`PhysicalVehicleDuty` 保存实体车身份、车型、车场、趟集合和显式充电会话（同文件 `:80-163`）；`DutyIndividual` 再把各实体车 Duty 组成完整候选（`:165-200`）。三者都没有各趟发车/回场时刻。下游 `route_timing()` 也明确说明，当前出发时刻只是给没有时钟字段的 `Route` 生成的一个可复现见证，不是其他时钟不存在的证明（`solver/src/setp_solver/search/multitrip_schedule.py:388-403`）。

**本稿建议的语义关系。** `ScheduledDuty` 是 `PhysicalVehicleDuty` 的**伴生排程见证**，不是 `DutyTrip` 的子类，也不替换 `DutyTrip`：

- `DutyTrip` 继续只回答“这辆车第几趟按什么顺序访问哪些节点”；交叉和教育移动只改这一结构层。
- `ScheduledDuty` 回答“在这个固定结构下，这辆车怎样按时钟和 SOC 执行”；Oracle/协调器每次对结构变化重新生成它。
- `DutyIndividual` 必须携带本次协调器最终选中的 `ScheduledDuty`，使排程进入个体身份、缓存和完整评价；不得把它只放在进程外缓存中。
- 空 Duty（`trips=()`）仍是固定注册表里的未启用车辆，不需要伪造排程。非空 Duty 必须有且仅有一个与其身份、趟集合完全一致的排程见证。

这固定了“结构与排程分层”的语义，但 `ScheduledDuty` 最终是作为 `PhysicalVehicleDuty.schedule` 字段嵌入，还是作为 `DutyIndividual.schedules` 的按车映射保存，现有源码没有唯一答案，列入第十节待 Claude 裁决。无论采用哪一种，不能形成两份可各自修改的真值。

### 2.2 字段、不变量与时间—SOC—充电见证

建议的最小正式对象如下；名称是施工稿接口名，不是已经存在的生产类型：

| 对象 | 必备字段 | 用途 |
|---|---|---|
| `ScheduledTripWitness` | `trip_index`、`route_signature`、`departure_second`、`return_second`、`start_soc_kwh`、`end_soc_kwh` | 把一个 `DutyTrip` 的结构身份绑定到实际时钟和趟首/趟末电量 |
| `ScheduledSOCPoint` | `event_index`、`event_kind`、`trip_index`、`node_id`、`event_second`、`soc_before_kwh`、`soc_after_kwh` | 记录出发、每段行驶、到站、充电各曲线段端点和回场的连续 SOC 链；相邻点必须闭合 |
| `ScheduledChargingSession` | `relation`、`after_trip_index`、`before_trip_index`、`route_trip_index`、`station_id`、`physical_station_id`、`charge_start_second`、`charge_end_second`、`charge_day_offset`、`start_energy_kwh`、`end_energy_kwh`、`energy_kwh`、`occupancy_minutes`、`charging_curve_id`、`locked` | 无歧义描述首趟前、趟间或途中充电，并可机械投影为现有 `DutyChargingSession`/`ChargingAction` |
| `ScheduledDuty` | `physical_vehicle_id`、`vehicle_type`、`home_depot_id`、以上三组见证、`occupancy_signature`、`local_accounting_vector`、`schedule_contract_sha256`；另有派生属性 `schedule_fingerprint` | 单车 Oracle 的一个完整前沿元素 |

这里的“连续 SOC”不是只存一对趟首/趟末数字。现有多趟证书已有 `ScheduledTrip.start_battery_kwh/end_battery_kwh` 和充电前后能量（`multitrip_schedule.py:83-99,119-139`），而证书重放器会从给定 `departure_second` 逐弧重算到达、服务和回场时钟（`solver/src/setp_solver/search/certificate_execution.py:211-319`）。新见证应在此基础上把跨趟和充电曲线段的 SOC 点也正式保存，至少满足：

1. 车、车型、车场、趟号和路线签名与结构 Duty 逐项相同；趟号连续，不能少趟、多趟或换车。
2. 每趟从 `departure_second` 重放得到的回场时刻必须等于 `return_second`；客户和回场时间窗全满足。
3. EV 相邻 SOC 点闭合：行驶只扣除已核算能耗，充电只按 P35 对应曲线增加能量，任何时刻均在电池上下界内；前一趟回场 SOC、趟间会话前后 SOC、下一趟发车 SOC 连成一条链。
4. 充电会话的 `energy_kwh = end_energy_kwh - start_energy_kwh`，占用时长等于相应分段曲线积分。现有 `charging_curve_for_action()` 已检查能量、曲线和时长一致性（`solver/src/setp_solver/cost.py:496-593`）。
5. `occupancy_signature` 不是另一套容量判据，只是把同一会话按 checker 口径映射成 `(physical_station_id, day_offset, slot_index, action_vehicle_id)` 的规范集合，供协调器组合。

现有 `PhysicalVehicleDuty.charging_sessions`（`model.py:113-115`）与新 `ScheduledDuty.charging_sessions` 不能长期并列成两个可编辑源。过渡期若为了 `to_solution()` 兼容而保留旧字段，旧字段只能由新见证机械投影，并在构造时要求逐字段一致；不一致直接拒绝。最终单一承载位置列入待裁决。

### 2.3 指纹与缓存身份

当前 `DutyIndividual.fingerprint` 对 `duties` 做 `asdict()` 后哈希（`model.py:201-214`），因此只要正式排程进入 Duty 的 dataclass，它会自然进入个体指纹；若采用 `DutyIndividual.schedules` 映射方案，则必须把排程映射显式加入同一 payload。不能让同一个个体指纹对应两个发车时钟或两套充电会话。

指纹分成两个用途，避免循环依赖：

- `duty_structure_fingerprint`：只含实体车身份、车型、车场、趟序、节点序列和动态锁，不含求解后的排程；作为单车 Oracle 输入键。
- `schedule_fingerprint`：含 `ScheduledDuty` 的全部输入字段、`schedule_contract_sha256` 和所有浮点字段的规范表示，但不把派生 fingerprint 自身放回 payload；浮点按现有评价上下文身份函数的 `float.hex()` 做法编码，避免十进制格式差异（`solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:207-274`）。
- `DutyIndividual.fingerprint`：结构与最终选中排程两者都含，作为种群、教育缓存和完整评价身份。

排程列表、SOC 点、会话和占用签名全部按稳定键排序后再哈希；禁止依赖集合迭代顺序。见证自身不得含运行墙钟、缓存命中等观测字段，否则相同排程会因性能观测得到不同身份。

### 2.4 完整评价、不得暗修检查与 prepare_multitrip_solution 重放

当前静态完整评价先把 `DutyIndividual` 转成 `Solution`，再调用 `prepare_multitrip_solution()`，随后 `_assert_no_hidden_repair()` 只核路线映射和充电动作（`problem_hgs/evaluation.py:343-353,797-822`）。增量评价在合并所有 Duty 切片后又做同样的准备和检查（`:601-611`）。现有 `DutyIndividual.to_solution()` 也只能输出路线与充电动作（`model.py:216-249`）。因此，新见证必须穿过以下统一边界：

1. `to_solution()` 仍生成 legacy `Solution` 的路线和由见证投影出的显式 `ChargingAction`；时钟不伪装进 `Route`。
2. `prepare_multitrip_solution()` 增加“已给定排程见证/证书”的重放入口。它不得再为该候选另选时钟，而是对每趟调用已有 `route_timing(..., forced_departure_second=...)` 的强制时钟路径（`multitrip_schedule.py:388-466`），重算回场时刻、SOC 和充电账。
3. 由重放结果形成 `MultiTripCertificate`。现有证书已正式保存每趟发车、回场、补能结束和趟首/趟末电量（`multitrip_schedule.py:83-99,141-149`）；`build_certificate_execution_ledger()` 再验证证书状态、路线绑定和执行时钟（`certificate_execution.py:108-135`）。
4. “不得暗修”检查扩为三组相等：路线结构不变、显式充电动作不变、`ScheduledDuty` 与返回证书的时钟/SOC/会话不变。只有现有浮点等价容差允许的数值重算差，不允许换站、改量、挪时、换趟或重建另一份排程。
5. 重放或等价检查失败时返回 `SENTINEL_MISMATCH`/明确接口拒绝，保留原见证和差异；不得回退到旧补全器偷偷生成一套可行时钟。
6. 通过上述重放后，仍由完整 `check_solution()` 和完整成本/利润/公平评价裁决。当前完整评价会先算各车场利润，再构造公平上下文并调用 checker，最后算完整成本（`problem_hgs/evaluation.py:413-495`）；单车 Oracle 的局部分量不能取代这一层。

这条接线允许 `prepare_multitrip_solution()` 继续充当真值重放器，而不再充当对已排程个体的第二个隐式排程器。施工会涉及哪些非保护文件由后续工单决定；本稿没有修改任何评价源码。

## 三、单车排程 Oracle

### 3.1 有限事件集的精确构造

**输入合同。** 单车 Oracle 输入一个固定的结构 Duty、静态评价上下文、初始资产状态（静态为车场/初始 SOC/日界；动态接口第 4 步另接）、求解态（仅求可行或按获批局部分量优化）和 `schedule_contract_sha256`。它不读取或修改其他车辆；共享容量只编码成输出的占用签名，由协调器处理。

事件集不是按任意秒长网格采样，也不是黄金分割/固定次数一维搜索，而是对现有分段线性合同做有限顶点枚举。构造顺序如下：

1. **路线时钟事件。** 对每条固定节点序列预编译逐弧行驶、服务和能耗。客户、车场和已在路线中的公共站的 `ready_time`/`due_time` 是原始边界（`solver/src/setp_solver/instance_loader.py:14-34`）；将这些边界按该节点之前的累计行驶/服务偏移反推成“趟可发车时刻”的分段断点。`route_timing()` 的前向等待与强制发车检查是重放真值（`multitrip_schedule.py:388-466`）。
2. **价格/碳事件。** 加入实际 time-profile 覆盖期内所有 30 分钟边界。现有计价常量为 1800 秒（`cost.py:42`），精确充电起点搜索也正是把每个时档边界减去充电曲线各阶段的相对边界（`cost.py:666-732`）。因此候选不仅含整点边界，还含 `slot_boundary - curve_phase_relative_boundary`。
3. **P35 SOC 事件。** 车场 22 kW 与公共站 60 kW 曲线都用 `0/85%/95%/100%` SOC 节点和三段功率（`solver/src/setp_solver/charging_curve.py:86-106`）。事件集加入这些绝对电量、初始 SOC、每一剩余趟的必需出发电量、这些量加/减固定路径能耗的前像，以及“曲线阶段端点或充电结束正好落在一个时间边界”时由分段线性曲线反解出的 SOC。
4. **站点占用事件。** 容量语义按 checker 的 48 个循环半小时档：充电动作只要触及某档，就在该档计一次（`check.py:609-628`）。所以容量状态真正改变的边界是 `day_offset × 86400 + slot_index × 1800`；其他车辆会话的任意秒级起止点不额外创造容量语义。物理站点别名由 `physical_station_id(node)` 归一化（`solver/src/setp_solver/station_copies.py:12-13`）。
5. **闭包。** 对“等待到下一事件、按固定路线执行一趟、在允许站点按某曲线充到下一 SOC 事件”三类转移反复取像/前像，直到不再产生新的合法 `(time, SOC)` 顶点。所有时域、SOC 域、趟数、站点数和曲线段数都是有限的，所以闭包有限；若实现因标签/事件上限提前停止，状态只能是 `SEARCH_EXHAUSTED`，不能报 `INFEASIBLE`。

精确性的核心是：在两个相邻事件之间，路线传播、曲线充电时长、逐档电价/碳和容量签名均保持同一分段表达；可行域与局部分量的最优点只能出现在这些分段多面体的顶点。实现不得以“每 1 分钟/每 1 kWh”这类采样网格代替顶点枚举。具体浮点规范化与闭包数据结构仍须 Claude 校审，列入第十节。

### 3.2 标签状态、递推顺序与转移

每个标签至少保存：

`(progress, location, time_second, soc_kwh, local_accounting_vector, occupancy_signature, predecessor)`。

- `progress` 精确到“第几趟之前/路线内允许充电节点/第几趟之后”，保证两个标签只有在未来结构相同处才能比较。
- `time_second` 是当前可继续执行的绝对时刻；`soc_kwh` 是同一时刻的连续电量。CV 的 SOC 维度固定为空，但仍走时钟递推，不能沿用当前见证时钟后直接宣告重叠。
- `local_accounting_vector` 不用一个“完整成本”标量冒充全局模型。它保存排程会改变的可加分量：分时电费、充电占用费、充电间接排放/碳成本、路线时间成本，以及按车场归属的相同分量。固定路线下不变的距离、燃油、固定车成本可以标记为常量而不进入标签。现有完整成本分项见 `cost.evaluate()`（`cost.py:147-225`），全局利润/公平仍在完整评价中处理。
- `occupancy_signature` 保存该单车所有显式动作按正式容量口径触及的规范档集合，而不是连续区间并发数。
- `predecessor` 只用于最后重建 `ScheduledDuty`，不参与支配或哈希。

递推采用固定顺序的标签扩展：

1. `WAIT`：从当前时刻等到下一有限事件，不改 SOC 和占用；若等待会进入完整时间成本，先把相应增量计入向量。
2. `CHARGE`：仅在结构允许的车场或路线中已有的公共站位置，从当前 SOC 充到有限 SOC 事件；按 P35 曲线得精确时长，按 `charging_action_slot_breakdown()` 逐档分能量（`cost.py:596-663`），追加会话、成本/排放与占用签名。
3. `TRIP`：在一个候选发车事件启动下一固定趟，调用同口径路线传播，检查每个客户时间窗、回场时窗和路上公共站会话，扣除精确能耗，生成回场标签。
4. 所有趟完成后，只保留满足终端 SOC/动态继承合同的终止标签，反向重建正式见证。

公共站是只允许在已有 `DutyTrip.effective_route_visits` 中选择充电，还是 Oracle 可插入新的站点节点，会改变结构层边界；现有 `to_solution()` 明确保留 `route_visits`（`model.py:216-233`），本稿不擅自扩成站点插入器，列入待 Claude 裁决。

### 3.3 支配剪枝与全局组合所需备选的保留

单车前沿不能只按局部成本留一个最便宜排程。若两个排程占用不同站点/时档，较贵者可能是全车队唯一可组合项。安全剪枝只允许在**相同车辆、相同 progress/location、相同结构与锁定历史**下进行。

标签 A 支配标签 B，当且仅当以下条件同时成立：

1. A 的可用时刻不晚于 B，SOC 不低于 B；并且 A 合法等待到 B 的时刻后仍在所有局部分量上不差。若等待会增加某分量，就先把等待增量计入再比较。
2. A 的 `local_accounting_vector` 对所有会进入完整目标、利润或排放的分量逐项不大于 B；至少一项严格更好，或资源状态严格更宽松。不得在双目标/公平口径尚未完全接线时用一个加权和提前删解。
3. A 的占用签名是 B 的子集。签名不同且互不包含时，即使 A 更便宜也不能删 B；协调器可能只容得下 B。
4. 两者的未来允许动作集合相同。站点位置、day offset、动态锁或曲线段身份不同而会改变未来动作时，不可比较。

论证：在上述条件下，B 的任一后续动作序列都可从“不更晚、SOC 不更低、成本/排放不更高、占用档不更多”的 A 继续执行；用 A 替换 B 不会让任何协调组合失去容量或让全局可加分量变差。因此删 B 不会漏掉全局最优组合所需的备选。这个论证不成立的标签一律保留。

完整终止标签再按同一保守关系形成单车非支配前沿。**精确态不设静默前沿大小上限**；若为性能设置上限、beam、超时或近似压缩，必须返回 `SEARCH_EXHAUSTED` 并保存截断原因，不能把截断后的非空/空集合冒充完整前沿。

### 3.4 INFEASIBLE 与 SEARCH_EXHAUSTED 的边界

Oracle 返回三种互斥状态：

- `FEASIBLE`：有限事件图完整构造，标签搜索完整结束，至少有一个终止标签，所有前沿元素均已重放为合法 `ScheduledDuty`。
- `INFEASIBLE`：有限事件图完整构造，未触发时间、事件、标签、内存或前沿截断，队列穷尽后没有任何合法终止标签；失败证书至少给出最后可达 progress、各硬约束淘汰计数和事件/标签总数。
- `SEARCH_EXHAUSTED`：事件闭包、标签队列、数值反解、内存、墙钟、取消信号或实现支持范围任一未完成。它表示“本次没有完成证明”，候选可在搜索流程中被拒绝，但报告和消融中不得计为物理不可行。

协调器同样使用这一区分：单车前沿非空但联合搜索被截断是协调器 `SEARCH_EXHAUSTED`；只有所有单车前沿都完整、笛卡尔组合也完整穷尽且没有容量可行组合，才是共享容量 `INFEASIBLE`。当前 `CandidateStatus` 只区分若干接口/充电拒绝（`solver/src/setp_solver/algorithms/problem_hgs/contracts.py:29-40`），后续实现需把这三态保存在专项字段和失败原因中，不能全部压成 `REJECTED_CHARGING`。

### 3.5 预编译上下文与计价开销控制

为一个评价上下文只构造一次 `ScheduleOracleContext`：

- `node_by_id`、节点类型、物理站点 ID、车场/站点容量；
- 每个站点的 city-specific 价格/碳 30 分钟数组和绝对边界；
- P35 两套已缩放曲线、SOC 节点、各段功率、累计时长与逆函数；
- 每个结构趟的路线签名、逐弧时长/能耗、客户时窗传播断点；
- checker 口径的 48 档容量键模板；
- `evaluation_context_sha256` 与 `schedule_contract_sha256`。

原因是现有热路径会对每个动作反复构造节点字典：`charging_curve_for_action()` 在每次曲线检查中执行 `{node_id: node}`（`cost.py:508-515`），`charging_action_electricity_cost()` 又重建节点字典和站点时序表（`:1157-1171`）。Oracle 的每个标签转移不能重复做这些与候选无关的工作。

预编译只消除查表和对象构造，不改变成本语义。每个完成见证仍必须用现有 `charging_action_slot_breakdown()`、完整 `cost.evaluate()` 和 checker 重放核对。如何让标签热路径使用预编译结构而又不复制一份可能漂移的 `cost.py` 逻辑，有两个可行实现边界，列入待 Claude 裁决：向保护文件申请一个只读预编译参数入口，或在新 Oracle 模块实现同式热路径并用逐候选差分核验守住真值。本稿不修改 `cost.py`。

## 四、被改车辆协调器

### 4.1 未改车辆剩余容量日历

协调器先从当前完整候选中取出**未改车辆**的显式充电动作（用 `physical_vehicle_id(action.vehicle_id)` 判断动作属于哪辆实体车，不能拿带 `#Tn` 的动作 ID 直接和 `changed_duty_ids` 比），构造已占用集合与剩余容量；这一步必须逐字复用 `check.py:_check_station_capacity()` 的语义（`solver/src/setp_solver/check.py:583-644`）：

1. 静态为 `solution.charging_actions`；动态第 4 步还要加 `reserved_charging_actions`，与 checker `:601-604` 相同。
2. 只接受节点类型 `d/f`；每个动作调用同一个 `charging_action_slot_breakdown(action, ..., n_slots=48, cyclic=True)`（`:605-625`）。
3. 用 `physical_station_id(node)` 合并站点访问副本（`:626`；实现定义在 `station_copies.py:12-13`）。
4. 容量键严格为 `(physical_station_id, charge_day_offset, slot_index)`；值严格是 checker 所用的 `action.vehicle_id` 集合（`check.py:627-630`），不能擅自改成连续秒重叠或另一种车辆归一化。
5. 站点容量严格复用 `_station_chargers()`：显式 `station_chargers` 优先；无值的车场容量为至少 1 且按客户数放大，公共站为 1（`check.py:1214-1222`）。

剩余日历保存 `capacity`、`occupied_action_vehicle_ids` 和 `remaining = capacity - len(set)`。加入一个前沿元素时，按其规范占用签名更新同一集合；任何键超容量立即剪枝。为了避免语义漂移，最终应由 checker 和协调器共享同一纯函数，而不是复制五条规则。是否允许为此改受保护 `check.py`，不是本稿能决定的事项。

### 4.2 多车前沿联合选取

输入为 `changed_duty_ids`、每车一个完整 Oracle 前沿、未改车辆剩余日历和完整评价器。输出不是未经真值检查的单一“局部最便宜排程”，而是一组按规范顺序排列的联合候选及最终选择：

1. 先验证每个被改非空 Duty 都有 `FEASIBLE` 前沿；任一 `INFEASIBLE` 或 `SEARCH_EXHAUSTED` 先按其原状态返回。
2. 车辆搜索顺序固定为“前沿较小优先，再按 `physical_vehicle_id`”，只用于加快剪枝，不改变结果。
3. 对每辆车的前沿按 `local_accounting_vector`、占用签名、`schedule_fingerprint` 排序，做确定性深度优先枚举。
4. 每加入一个排程就把占用签名并入剩余日历；超容量立刻剪枝。只在有严格、分量级下界时做成本/排放支配剪枝，不用未批准的加权和。
5. 对容量可行的完整组合，组成带正式排程见证的 `DutyIndividual`。联合候选按完整评价逐一重放，沿用现有“完整罚分成本、再按 fingerprint”决胜逻辑；当前交叉候选正按这两个键选最小项（`integrated_private.py:376-393`）。完整评价因客户、锁、车队、利润、公平等拒绝时继续考察其他联合候选，不把第一项的全局失败误写成共享容量无解。
6. 返回本次完整评价下最优的合法联合候选；若未来双目标接口返回非支配集，则这里保留所有完整非支配联合候选，不能提前加权压成一个。

单车前沿与协调器的职责由此分开：Oracle 证明单车结构是否可排并保留不同占用备选；协调器证明被改车辆能否与未改车辆共同占用站点；完整评价证明整个模型是否合法和值多少。

### 4.3 最坏开销与拒绝语义

设本次改变 `k` 辆车，第 `i` 辆前沿大小为 `F_i`。不利用剪枝时，完整组合数的最坏上界是 `∏ F_i`；深度优先访问的部分节点上界为 `1 + Σ_{j=1..k} ∏_{i=1..j} F_i`。这是指数最坏情形，不能用“通常只改两车”冒充封闭上界。容量冲突剪枝、较小前沿优先和安全下界只改善实测，不改变最坏量级。

返回与拒绝语义如下：

- 某车单车前沿完整为空：`INFEASIBLE_SINGLE_DUTY`。
- 所有单车前沿完整，但所有笛卡尔组合都触犯 checker 同款容量日历：`INFEASIBLE_SHARED_CAPACITY`。
- 组合搜索因次数、内存、墙钟或取消信号提前停止：`SEARCH_EXHAUSTED_COORDINATOR`，不得写成不可行。
- 至少有容量可行组合，但全部被完整评价的其他约束拒绝：保留各自完整模型违反，汇总为 `REJECTED_FULL_MODEL`，不得归罪于 Oracle/容量。
- 找到合法组合：返回 `FEASIBLE` 及最终选中见证；不调用旧补全器再改一次。

任何协调组合尝试上限都属于会改变完备性的实现选择，必须显式进入 `schedule_contract_sha256`，触发时记 `SEARCH_EXHAUSTED`。本稿不自设一个看似安全的固定上限。

## 五、接入点与调用合同

### 5.1 交叉修复

当前交叉对每个 `crossed.child` 在 `integrated_private.py:361-375` 调 `repair_changed_duties()`；异常即丢弃，然后完整评价。第 2 步施工时将这一段的静态排程职责替换成统一协调入口：

`coordinate_changed_duties(reference, raw_child, changed_duty_ids, oracle_context)`。

客户服务不完整的前置拒绝仍保留（`:352-360`）；Oracle 只处理排程原因，不能包办客户覆盖、注册表或锁。`repair_changed_duties` 原样保留为 A0 和遗留对照，不在新路径成功后再次执行。协调器返回 `SEARCH_EXHAUSTED` 时本次候选拒绝但单独计数；只有完整穷尽才记排程不可行。

### 5.2 教育移动

当前 `evaluate_move()` 先 `move.apply()`、再核锁（`education.py:79-91`），随后在 `:92-110` 调 `repair_changed_duties()`，失败统一记 `REJECTED_CHARGING`。第 3 步施工时这里与交叉共用同一个协调器，输入 `move.changed_duty_ids`，输出一个或多个正式排程候选，再交 `DutyIncrementalEvaluator.evaluate_after_change()`。

未改 Duty 继续复用增量切片；当前增量评价会用 `_changed_duty_ids()` 复核申报范围（`problem_hgs/evaluation.py:556-599,897-917`）。因为正式排程进入 Duty 指纹，若协调器改变了一辆车的时钟/会话，该车必须被视为实际改变；不能只按客户序列判断未改。

### 5.3 完整评价

静态完整评价的两个真值入口固定为：

- 全量：`DutyFullEvaluator._evaluate_full()` 中 `prepare_multitrip_solution()` 与不得暗修检查（`problem_hgs/evaluation.py:343-353`）；
- 增量：所有切片合并后的同一准备和检查（`:601-611`）。

两处都必须接收并重放同一 `ScheduledDuty`，不得只在交叉/教育层缓存时钟。增量 `prepare_duty_slice()` 目前也会对单 Duty 独立准备（`:381-411`）；它需要把正式证书/排程随切片缓存，否则合并后又会丢钟。完整 checker 仍是最终真值，不改变 `solver/src/setp_solver/search/evaluation.py`、`cost.py` 或 `check.py`。

### 5.4 动态 future-only 适配器预留

第 1 步只冻结接口，不实现动态调度。预留的 `DynamicScheduleAdapterInput` 至少含：

- `trigger_second`；
- 每辆资产的继承位置、SOC、可用时刻、车型与车场；
- 已完成/进行中路线、锁定充电动作、完整资产注册表；
- 只允许修改的未来 `DutyTrip` 与未来客户集合；
- 静态相同的 `schedule_contract_sha256`，另加动态适配器版本。

原因是当前动态路径与静态不同：`repair_changed_duties()` 在 `dynamic_state` 存在时只核公共站动作和锁，然后直接返回候选（`charging.py:137-159`）；真正的动态准备从资产状态、触发时刻和锁定会话逐车排未来（`problem_hgs/dynamic.py:256-355`），最后 `_merge_execution_history()` 明确拒绝改写已执行路线与历史动作（`:460-511`）。第 4 步适配器只能从触发点后的继承状态开始，返回 future-only 见证；静态“车场、日初 SOC、从 0 时刻开始”签名不得复用。历史排程也必须加入锁核验，因为现有 `assert_locks_preserved()` 只看客户前缀和锁定会话（`model.py:398-454`）。

## 六、确定性与缓存

### 6.1 排程合同 SHA 与缓存键

`schedule_contract_sha256` 至少绑定：对象 schema 版本、事件构造版本、P35 曲线 ID/节点/功率、30 分钟档与 day-offset 口径、容量语义版本、数值规范化/容差、Oracle 运行态、支配规则、任何资源上限，以及预编译上下文身份。评价输入本身继续由现有 `evaluation_context_sha256()` 绑定（`problem_hgs/evaluation.py:265-274`）。

建议分两级缓存：

1. **单车前沿缓存**键：`(duty_structure_fingerprint, initial_asset_state_fingerprint, lock_fingerprint, evaluation_context_sha256, schedule_contract_sha256, oracle_mode)`。它不含未改车辆日历，因为 Oracle 不看全局占用；缓存值是完整前沿及其状态/记账。
2. **协调结果缓存**键：`(sorted changed duty ids and frontier fingerprints, unchanged_capacity_calendar_fingerprint, evaluation_context_sha256, schedule_contract_sha256)`。日历必须进入这一层，避免相同单车前沿在不同全局占用下误复用。

现有教育缓存只含 repair 开关、提议引擎身份、候选 fingerprint 和罚分状态（`integrated_private.py:424-445`）；接入后至少要让个体 fingerprint 已包含排程，并把排程合同 SHA 加入相关缓存身份。缓存命中必须返回字节身份一致的前沿/联合结果。

### 6.2 平局决胜

所有枚举顺序固定：车辆 ID、趟号、事件时刻、SOC、物理站点 ID、day offset、slot、会话字段、排程指纹。局部分量完全相等时，以较小占用签名、再以 `schedule_fingerprint` 决胜；完整评价相等时沿用成本/罚分后按 `DutyIndividual.fingerprint` 的现有顺序（`integrated_private.py:381-393`）。

浮点身份用规范十六进制表示；“数值相等”的容差只用于现有物理等价检查，不可用于把跨容量档或跨 P35 节点的两个事件合并。任何容差变化都必须改变排程合同 SHA。

### 6.3 主 GA 随机流隔离

Oracle、支配、前沿排序和协调器均不得接受主 GA 的 RNG 参数，也不得调用全局随机源。当前交叉会在 `crossover.py:358-360` 消耗主 RNG 旋转候选顺序；新排程层若再按调用次数消耗同一流，会使 A0/A1 多出纯实现混杂。

本稿首选全确定性，无需独立随机流。若 Claude 最终认为某个等价平局必须随机，唯一允许的接口是从 `(实验种子, duty_structure_fingerprint, action_id, schedule_contract_sha256)` 派生无状态独立子流；不得随调用先后改变，也不得推进主 GA RNG。该例外须写入合同和消融元数据。

## 七、SearchAccounting 记账

### 7.1 字段清单

现有 `SearchAccounting` 只有总体动作、评价、缓存切片、交叉/教育和墙钟字段（`contracts.py:65-99`）。第 1 步建议新增以下专项字段；名称可按代码风格微调，但信息不得丢失：

| 组 | 字段 |
|---|---|
| Oracle 调用/缓存 | `schedule_oracle_calls`、`schedule_oracle_cache_hits`、`schedule_oracle_cache_misses`；命中率由 hits/(hits+misses) 导出 |
| Oracle 终态 | `schedule_oracle_statuses: Counter[FEASIBLE/INFEASIBLE/SEARCH_EXHAUSTED]`、`schedule_oracle_failure_reasons: Counter[str]` |
| Oracle 墙钟 | `schedule_oracle_wall_seconds_total`、`schedule_oracle_wall_seconds_samples`，导出 `p50/p95/p99/max`；缓存命中与未命中分别统计 |
| 事件与标签 | `schedule_oracle_event_counts`、`schedule_oracle_labels_generated`、`schedule_oracle_labels_pruned`、`schedule_oracle_slot_pricing_calls`、`schedule_oracle_curve_transitions` |
| 前沿 | `schedule_oracle_frontier_sizes`、`schedule_oracle_frontier_cache_bytes`（若可得）；导出前沿大小 `p50/p95/p99/max` |
| 改动范围 | `scheduled_changed_duty_counts: Counter[int]`，记录每次 1/k 辆车 |
| 协调器 | `schedule_coordinator_calls`、`schedule_coordinator_cache_hits/misses`、`schedule_coordinator_combinations_attempted`、`schedule_coordinator_capacity_prunes`、`schedule_coordinator_full_candidates`、`schedule_coordinator_statuses`、`schedule_coordinator_wall_seconds_samples` |
| 接线结果 | `schedule_rescued_candidates_by_channel`、`schedule_rejected_candidates_by_channel_and_status`，区分交叉、教育、完整模型拒绝 |

精确 p50/p95/p99 由每次调用原始样本在导出时按固定方法计算；如果担心内存，原始逐调用行可以流式写入技术产物，但最终 `SearchAccounting` 序列化必须带分位数与样本数。不得只留平均值，因为 99 分位长尾会决定 20 分钟内的真实代数损失。

### 7.2 聚合口径与失败原因

失败原因至少按以下稳定码分组，同时保存原始异常文本：`NO_TIME_WINDOW`、`SOC_DEFICIT`、`CURVE_MISMATCH`、`LOCK_CONFLICT`、`UNSUPPORTED_PUBLIC_STATION_STRUCTURE`、`EVENT_LIMIT`、`LABEL_LIMIT`、`FRONTIER_LIMIT`、`ORACLE_TIMEOUT`、`SHARED_CAPACITY`、`COORDINATOR_LIMIT`、`REPLAY_MISMATCH`、`FULL_MODEL_VIOLATION`。

`INFEASIBLE` 与 `SEARCH_EXHAUSTED` 分开统计；缓存命中的原始求解墙钟不能重复计入纯 Oracle 计算，但命中查找墙钟仍计入算法总墙钟。总体算法墙钟继续独立记录，不能用 Oracle 自报时间替代端到端净开销。现有 `CandidateOutcome.work_accounting` 和 `SearchAccounting._record_work()` 已提供把下层工作量汇入总账的入口（`contracts.py:43-54,100-107`）。

## 八、第一批考题：08-10 PRD50 三种子死亡接收组合重放

### 8.1 可从现有产物重建的输入

三份来源包为：

- `solver/reports/problem_hgs_serial_finalonly_prd50_seed1_20260810/`
- `solver/reports/problem_hgs_serial_finalonly_prd50_seed2_20260810/`
- `solver/reports/problem_hgs_serial_finalonly_prd50_seed11_20260810/`

从现有文件能封存：

1. `metadata.json` 中的实例 ID、种子、3 代、每臂 10 秒上限和三个受保护文件哈希。
2. `best_solutions.json` 中两个臂的**最终** `DutyIndividual`、最终 prepared solution、完整评价、运行总账和按原始错误文本聚合的 `rejection_reasons`。三个文件中 FULL 臂相关区分别从 seed 1 `:500`、seed 2 `:500`、seed 11 `:525` 开始，聚合拒绝账分别位于 `:927`、`:927`、`:977` 附近。
3. `raw_runs.csv:2-3` 中每臂服务客户/需求、成本、排放、动作和拒绝总数。
4. `artifact_hashes.json` 中上述包内文件哈希。
5. 汇总证据 `solver/reports/carpet_sweep_20260810/private_space/death_reasons.csv:2-19`：逐 seed、车辆和报错原文的 18 个计数桶；合计 seed 1/2/11 为 103/95/115。源码复核后其中 CV 趟重叠 241、EV 车场充电窗为空 72（评审 `review.md:21-35`）。

这些材料足以建立 `legacy_aggregate_manifest`：固定三个来源包及哈希、实例/种子/预算、18 个原文计数桶、总数 313，以及“这是 A0 历史聚合基线”的身份。

### 8.2 现有产物无法重建的内容

现有包**不能**把 313 个成员逐一还原成可直接喂给 Oracle 的候选。`private_space/report.md:66-67,80-85` 已明确记录：产物只保存聚合原文计数，没有每次拒绝的候选状态快照。具体缺少：

- 每次拒绝前的父代 `DutyIndividual` 和 `raw candidate`；
- `action_id`、动作参数、所属交叉/教育通道、迭代和调用顺序；
- `changed_duty_ids`、接收/来源车及当时其他车辆的充电占用日历；
- 被拒车辆当时的趟序、节点序列、SOC、充电会话和时钟；
- 当时主 RNG 状态、父代选择和初始种群哈希；
- 完整代码/实例/配置身份（metadata 只保存三个保护文件哈希，不足以证明其余工作树字节身份）。

最终最好个体不能反推中途被拒候选；按同种子重跑也只能产生“同款新样本”，在当前脏工作树和未来接线变化下不能冒充原 313 个。因此不得把重新生成的 313 条标成“08-10 原始逐条重放”。

第一批考题采用两层封存：

1. **L0 历史聚合层**：只读冻结上述三个包和 `death_reasons.csv` 的哈希、18 桶和 313 总数；用于核对历史归因，不宣称逐条重放。
2. **L1 可重放候选层**：施工时在现有两个拒绝点——交叉 `integrated_private.py:361-375` 与教育 `education.py:81-110`——于调用 A0 前保存同一个 raw candidate。每条 JSONL 至少含 `case_id`、实例/评价/搜索/排程合同 SHA、seed/iteration/action/channel、父代与 raw candidate 的完整规范序列化、两者 fingerprint、`changed_duty_ids`、未改车辆容量日历指纹、A0 状态/原始错误、保护文件哈希。随后对完全相同字节输入分别调用 A0 与新 Oracle/协调器。

L1 若由同配置重新捕获得到 313 条，可以称“08-10 同款重建批”；只有候选 fingerprint 与另有原始快照逐条相等时，才能称“原 313 条”。目前不存在这种快照。

### 8.3 封存格式与通过标准

建议测试包含：`manifest.json`、`cases.jsonl`、`expected_a0.jsonl`、`artifact_hashes.json` 和简短 `report.md`。每个 case 单独保存 A0 与 Oracle/协调器的状态、前沿大小、完整重放结果、服务客户/需求、墙钟和失败原因；不只存最后汇总。

否证条件 1 的计算单位必须是**同一批 raw candidates 的配对结果**：

- 分母 `N_A0_schedule_rejected`：A0 因这两类排程错误拒绝的候选数；
- 分子 `N_new_full_replay_feasible`：新 Oracle/协调器给出排程，并通过 `prepare_multitrip_solution` 重放、不得暗修核验和完整可行性检查的同一候选数；
- 另报 `INFEASIBLE`、`SEARCH_EXHAUSTED`、共享容量拒绝和其他完整模型拒绝，不能都算“没救活”。

通过口径严格沿用已批准设计的否证条件 1：**若接入后存活率没有数量级改善、仍绝大多数死亡，则归因被否证并停止。** 但原设计没有把“数量级改善/绝大多数”登记成具体算式，而项目规矩禁止代理自设科学阈值，所以本稿不擅自写成 `≥90%` 或其他数字。可操作化的两个解释列入第十节交 Claude 裁决；未裁决前只报完整计数和比例，不宣布 PASS。

## 九、性能预算

### 9.1 风险量级与目标上界

评审按三个 PRD50、3 代 Full 臂的真实动作量折算出每代约 87.0、98.3、103.3 次单车调用（`review.md:71-83`）。若沿用当前 Python 候选起点枚举，一个近全天窗口约有 200 个临界起点，6 个窗口约 1,200 次固定量计价；再乘充电量候选 `Q`，风险量级是 `1,200 × Q`（`review.md:63-69`）。

本稿给出的**工程目标上界**是：在 PRD50 同款固定候选重放上，Oracle＋协调器的端到端新增墙钟按每代折算不超过 **0.10 秒**；按最坏观测 103.3 次/代折合所有调用（含命中）的有效平均不超过约 **1 毫秒/单车**。依据是评审算术：1 ms/单车只增加约 0.09–0.10 秒/代，而 10 ms 会增加 0.87–1.03 秒，接近当前 1.73–1.92 秒/代的一半以上（`review.md:83-87`）。

这是施工性能目标和否证条件 3 的预警线，不是论文科学门槛，也不保证每个 cache miss 都能在 1 ms 内完成。不得为了满足它截断事件/前沿后仍报 `INFEASIBLE`；完备性与速度冲突时应如实记 `SEARCH_EXHAUSTED` 或 `PERF_TARGET_EXCEEDED`。

### 9.2 达标手段

按优先级采用四项，不改科学合同：

1. **事件预编译**：节点/站点/曲线/time-profile/路线传播断点只按评价上下文构造一次；标签转移只做数组索引和分段线性算术，消除 `cost.py:508-515,1165-1171` 的重复字典与 profile 构造。
2. **前沿缓存**：以结构 Duty＋初态/锁＋上下文 SHA＋排程合同 SHA 缓存完整单车前沿。协调器处理全局容量，避免把日历污染进单车键。
3. **增量重算**：只对 `changed_duty_ids` 调 Oracle；未改 Duty 的正式排程、成本切片和容量占用直接复用。当前增量评价已经按实体车缓存并复核改变范围（`problem_hgs/evaluation.py:535-611`），新排程必须沿用这条边界。
4. **保守支配与确定性搜索序**：只删有证明的标签；协调器小前沿优先并在每层做同款容量剪枝。不得用 beam/前 N 个“提速”后继续声称精确。

必须分别报冷缓存、热缓存和端到端实际代内开销；只报 cache hit 的微秒数或只报 Oracle 内部计时都不达标。

### 9.3 超预算时按设计否证条件 3 记账

超出 0.10 秒/代目标时不隐瞒，也不立刻用减少搜索空间“修数字”。按评审已经修正的两本时间账执行（`review.md:89-96`）：

1. **固定候选重放账**：同一 L1 候选分别过 A0 与 Oracle/协调器，保存纯调用墙钟、事件/标签/前沿/组合数、排程状态、完整可行性和完整成本/排放差；这回答一次调用贵多少、救活什么。
2. **固定墙钟净值账**：进入第 3 步后，A0 与新路径按相同墙钟停，保存固定时点 best-so-far、最终成本与排放、服务客户/需求、完成代数、提议/评价/接受动作数和 time-to-best；这回答算法净值。

否证条件 3 的结论只能由固定墙钟净值账给出：若新增排程使可完成的搜索工作下降，且最终净改善不足以覆盖代价，就如实判该方案在当前实现/算例下净值不成立。第 1 步只能报告“达到目标/超目标以及量级”，不能用固定候选毛收益提前替代第 3 步净值判决。

## 十、待 Claude 裁决

以下事项现有源码和获批 v2 没有唯一答案；Claude 应在施工前逐项选择或继续交用户。本文没有把推荐项写成用户决定。

1. **排程见证放在哪里。**
   - A：`PhysicalVehicleDuty.schedule: ScheduledDuty | None`；单车身份、增量切片和 `asdict(duty)` 指纹最自然，推荐。
   - B：`DutyIndividual.schedules` 按车映射；结构 Duty 更纯，但所有 replace/切片/改变范围判断都要额外同步。
2. **现有 `charging_sessions` 的单一真值。**
   - A：`ScheduledDuty` 为正式源，`PhysicalVehicleDuty.charging_sessions` 只作机械兼容投影并逐步退役，推荐。
   - B：旧会话仍为源，`ScheduledDuty` 只引用它；改动小，但不足以无歧义表达趟间关系和连续 SOC。
3. **Oracle 是否能插入公共站节点。**
   - A：第 1 步只在现有 `route_visits` 的站点上选充电量/时刻，保持“节点序列已定”的批准边界，推荐。
   - B：同时允许插站；搜索能力更强，但把排程器扩成结构移动，需要重新界定 changed duties、事件集和归因。
4. **容量规则怎样真正共享。**
   - A：申请对受保护 `check.py` 做一次最小重构，把容量日历纯函数供 checker/协调器共同调用；语义最稳，但需要用户当次明确批准。
   - B：协调器直接调用现有公开函数并逐字复刻 `_station_chargers`；不碰保护文件，但存在长期漂移风险。
5. **预编译计价热路径。**
   - A：申请给 `cost.py` 增加只读的预编译上下文参数；单一真值最好，但触及保护文件。
   - B：新 Oracle 模块按同式预编译，所有终止标签再与 `cost.py` 差分重放；不碰保护文件，需承担双实现核验。
6. **有限事件数值规范。**
   - A：沿用 float 运算、以 `float.hex()` 规范身份并用现有物理容差重放，改动小，推荐先做原型。
   - B：时间/SOC 顶点使用有理数或 Decimal；证明更清楚，性能和与现有 float 真值接线成本更高。
7. **任何前沿/标签/组合资源上限。** 不设上限可保完备但可能超预算；设上限必须进入合同并返回 `SEARCH_EXHAUSTED`。具体数值没有现有测量依据，不应在施工前拍脑袋冻结。
8. **P39 双目标尚未进入当前 HGS 接口时，局部分量怎样排序。**
   - A：Oracle/协调器保留成本、排放和车场分量的非支配集，完整评价层决定，语义安全但前沿较大，推荐。
   - B：暂按当前标量成本排；更快，但可能在双目标接线后重新施工并漏掉备选。
9. **原 313 条缺少逐候选快照后的首批考题身份。**
   - A：明确分成 L0 历史聚合＋L1 同款新捕获配对集，不声称逐条复原，推荐。
   - B：尝试按旧版本重跑再称“重建”；只有补齐全部代码/输入/初始种群身份并逐条 fingerprint 对上时才成立，当前证据不足。
10. **否证条件 1 的“数量级改善”怎样数值化。**
    - A：按失败数至少下降一个十进数量级解释，即新路径排程死亡数不高于 A0 的十分之一。
    - B：按存活率/存活赔率提升一个数量级解释；在低/高基线下会给出不同判决。
    原获批文件没有选 A/B；Claude 不应自行把其中一个写成既定科学门槛。若只是技术短试，可先完整报数，正式 PASS 前交用户确认。
11. **0.10 秒/代目标的身份。** 本稿按评审量级提出它作为工程预警线；Claude 需确认它是第 1 步继续优化的目标，还是超过即停止的硬线。未确认前，超线只记 `PERF_TARGET_EXCEEDED`，不替用户终止已批准路线。

## 十一、源码与证据索引

行号均以 2026-08-10 当前工作区为准。

| 主题 | 当前入口 |
|---|---|
| v2 批准、四步顺序、三条否证条件 | `docs/handoff/duty_schedule_core_design_20260810.md:81-108` |
| 对抗评审总替代设计 | `solver/reports/carpet_sweep_20260810/dss_design_review/review.md:210-234` |
| 现有 Duty/指纹/Solution 适配 | `solver/src/setp_solver/algorithms/problem_hgs/model.py:33-249` |
| 交叉修复与教育拒绝点 | `solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:352-393`；`education.py:66-131` |
| 全量/增量完整评价和不得暗修 | `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:323-379,535-630,797-822` |
| 多趟证书、强制时钟和重放 | `solver/src/setp_solver/search/multitrip_schedule.py:71-149,388-466,1899-1990`；`certificate_execution.py:108-135,211-319` |
| P35 曲线与逐档成本 | `solver/src/setp_solver/charging_curve.py:86-106`；`solver/src/setp_solver/cost.py:496-732,1157-1207` |
| 正式共享容量语义 | `solver/src/setp_solver/check.py:583-644,1214-1222`；`solver/src/setp_solver/station_copies.py:12-13` |
| 动态 future-only 现有边界 | `solver/src/setp_solver/algorithms/problem_hgs/charging.py:120-224`；`dynamic.py:256-355,460-511` |
| 现有 SearchAccounting | `solver/src/setp_solver/algorithms/problem_hgs/contracts.py:29-113` |
| 313 条聚合证据与缺失边界 | `solver/reports/carpet_sweep_20260810/private_space/death_reasons.csv:2-19`；`private_space/report.md:58-67,80-85` |
| 三个 PRD50 来源包 | `solver/reports/problem_hgs_serial_finalonly_prd50_seed{1,2,11}_20260810/` |

本稿只新增这一份 Markdown，没有修改上述任何源码、既有文档或既有产物，也没有运行求解器、测试或实验。
