# ③ 拿不到「路线对齐充电窗口」收益的病灶诊断（只读）

诊断人：Claude（只读）。仓库根 `/Volumes/移动硬盘（512G）/ReSETP`，分支 `codex/reporting-pipeline`。
**没有改任何仓库文件，没有跑求解器，没有开搜索。** 只读源码、日志、产物；三份只读分析脚本写在会话临时目录
`.../scratchpad/`（`proxy_vs_exact.py`、`valley_prize.py`、`prize_margin.py`），未进仓库。

---

## 零、一句话结论

**路线搜索这一层根本看不到「什么时候回场」这件事。**
在 `kernel_native` 模式下，客户顺序与趟划分**全部**由内核在一个代理目标上搜完
（本批每跑 5.2 万–11.4 万圈），而这个代理给电动车弧的电价是**每个班次一个常数**，
取自「该班次开始之前那段窗口」里的某一格（`kernel_proposals.py:1292-1319`），
与车辆实际回场时刻无关。所以「把趟排成 12–15 时回场」这件事在内核目标里的梯度**恒为零**。
精确充电重排只在内核**收敛之后**对最终种群的 ≤66 个成员各跑一次
（`runner.py:625,660,671`），教育阶段又把唯一能改「同一辆车趟间客户归属」的动作通道
关掉了（`integrated_private.py:200` `include_structural_channels=False`）。
于是 ③ 与 ② 的路线来自同一个（对择时盲的）分布，③−② ≈ 0 是结构性的，不是抽样。

**钱在哪里、有多少（实测，10 次 MTC 逐解可核）**：MTC 十次里**每一次**都恰好有两次
「第三趟的趟间补电」落在午间谷段之外，起充时刻 904.1–932.3 分，
也就是**只差 4.1–32.3 分钟**没赶上 15:00 的谷段边界。
把这些电量搬进谷段，电费合计可省 **100.70 元 / 10 次 = 10.07 元每跑**；
其中**离边界 15 分钟以内**的部分是 47.31 元 / 10 次 = **4.73 元每跑**。
最刺眼的一例：`P=0.2/MTC-HGS/run_02` 的 `EV_D_OSM_WAY_1071205721_4` 第三趟，
起充 904.1 分（15:04.1），**只要早回场 4.1 分钟**，29.42 kWh 就从平段 0.83644 掉到谷段 0.56329，
一笔省 **8.04 元**——而这 4.1 分钟对路线层完全不可见。

---

## 一、必答题逐条

### 问题 1：趟的发车时刻是决策还是「尽早」？——**发车是「尽早」，回场时刻是路线的函数；搜索里没有任何以「充电窗口对齐」为目标的邻域动作。判定：证实。**

**发车 = 在不让客户干等的前提下尽可能早，且被上界压住。**
`solver/src/setp_solver/search/multitrip_schedule.py:559,577`
```
559:        preferred_departure = max(departure_candidates)      # 各客户 ready_time 反推的最早
577:        depart = min(preferred_departure, latest_departure)  # 再被后向递推上界压住
```
`departure_candidates` 起点是 `departure_floor`（`:462`），逐弧加 `ready_time - elapsed`（`:555-557`）。
`latest_departure` 由终点起的后向递推给出（`:561-569`），只用**本趟自身**节点的 `due_time`。
**没有任何一处允许「为了等便宜电价而主动推迟发车」。**

**唯一能把发车往后推的东西是充电本身**：同日出发前的车场充电结束时刻抬高发车下限。
`multitrip_schedule.py:476-485`
```
476:    predeparture_ends = [ ... action.charge_start_second + occupancy*60 ... ]
485:        departure_floor = max(departure_floor, max(predeparture_ends))
```
所以「充电时刻 → 发车时刻 → 回场时刻」这条链是通的，但它是**充电修复器**在动，
不是路线搜索在动；而充电修复器**只能在给定路线下选时刻**，改不了趟的长度。

**回场时刻由什么决定**：`return_second = depart + Σ(行驶 + 服务)`，
即由「本趟客户集合与顺序」＋「上一次充电何时结束」共同决定。
在两班次算例里，客户所属班次是**固定数据**
（`shift_contract.json`：AM 17 / PM 33、`switched_customer_count: 0`），
每趟只能装同一班次的客户（`assert_candidate_routes_single_shift`，`runner.py:647`），
所以「把回场排进 12–15 时」只能靠**同一班次内部**的趟重划（PM 第 2 趟／第 3 趟之间搬客户、
或开新趟）来实现。

**搜索里有没有以充电窗口对齐为目标（或至少能评价到）的邻域动作？——没有。判定：证实。**
- 内核局部搜索的算子来自 PyVRP 默认表（`kernel_proposals.py:225-260`），
  目标函数是 `model.add_edge(distance=_route_proxy_cost_units(...))`（`:1174-1177`），
  该代理的电价与时刻无关（见问题 2）。
- 教育阶段的动作通道，10 次跑的台账里**只有两种**：
  `whole_duty_type_exchange`（同车场整条任务链在油／电车之间互换）与
  `depot_collaboration`（跨车场整趟互换，`proposals.py:266`）。
  能改「同一辆车两趟之间客户归属」的 `multi_trip` 通道（`operators.py:1270` 判定、
  `OpenTripMove` 在 `operators.py:883-903`）被硬关：
  `solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:200`
  ```
  200:        include_structural_channels=False,
  ```
  注释写明这是 2026-09-02 为省评价次数做的取舍（"routing, multi-trip and cross-depot
  moves are the kernel's job"）。实测台账证实它确实一次都没触发：

  | 臂 | proposed_actions（10 次合计） |
  |---|---|
  | MT-HGS | `depot_collaboration` 34,570；`whole_duty_type_exchange` 80,533；**`multi_trip` 0** |
  | MTC-HGS | `depot_collaboration` 27,355；`whole_duty_type_exchange` 55,653；**`multi_trip` 0** |

  （读自 `solver/reports/ideal_construction_20260904/P=0.2/*/run_*/metadata.json`
  的 `accounting.proposed_actions`。）

### 问题 2：代理目标与精确账的错位——**代理把电动车电价当成「每班次一个常数」，回场时刻在代理眼里不存在。判定：证实。**

**代理逐行**（`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py`）：

1. 弧的目标值 = `distance=_route_proxy_cost_units(...)`（`:1174-1177`）；`duration` 只装时间
   （行驶 + 趟间补电预留 `reload_gap_seconds`，`:1173`），**不进目标**。
2. 电动车弧的推进成本（`:1390-1416`）：
   ```
   1391:        energy_kwh = ev_instance_arc_energy_kwh(...)   # 半载常数负荷
   1416:        propulsion = energy_kwh * active_ev_unit_cost
   ```
   `active_ev_unit_cost` 取弧两端客户所属班次的单价均值（`:1407-1415`）。
3. 班次单价怎么来（本批开启，见下）：`_rebuilt_shift_aware_ev_unit_costs`（`:1283-1330`）
   对每个班次取「**上一班次结束到本班次开始**」这段窗口（`:1298-1300`），
   在窗口内按 `(碳强度, 电价, -起始时刻)` 取最小（`:1312-1318`）。
   ```
   1314:            key=lambda item: (
   1315:                float(item["actual_gco2_per_kwh"]),      # ← 先按碳强度排
   1316:                float(item["depot_energy_cny_per_kwh"]),
   1317:                -float(item["horizon_second_start"]),
   1318:            ),
   ```
   **排序键里没有 `carbon_price`**：碳强度被无条件排在电价前面，而不是按钱
   （`电价 + 碳强度 × 碳价`）排。
4. 关掉班次感知时的兜底是**全天 48 格的算术平均**（`:1011-1019`）——不是最小值。
   （`pending_decisions.md` P12 记的「取全时段 min」与本行不符；实际是 mean。）
5. 第二轮及以后：`ev_unit_cost_override` 把**全部**班次单价压成同一个标量
   （`:1027-1031`），连班次分辨率也没了。该标量 = 上一轮精确最优的
   `(cost_elec + E_ev_indirect × 碳价) / kWh`（`runner.py:707-711`）。

**本批确实开了班次感知**：`run_problem_hgs_private_technical.py:1852`
`shift_aware_ev_unit_cost_enabled=True`（DEPOTSEARCH 算例走这条），
落盘 `route_engine_source_id` 含 `shift-aware-ev-price`。

**代理认为在哪个槽充 vs 精确账实际在哪个槽充**（`P=0.2/MTC-HGS/run_02`，午谷日历，
日期 2025-02-12——由 `china81.py:42 DEFAULT_CHINA81_DATE` 定，且我按该日历该日期
逐槽手算 `cost_elec = 131.8928` 与官方 `breakdown.cost_elec = 131.8928` **逐位相同**，
`E_ev` 手算 69.2344 对官方 69.1403，差 0.09 来自碳强度按小时归一）：

| | 代理选的槽 | 代理单价（含碳） | 精确账实际充电时刻 | 实付单价（含碳） |
|---|---|---:|---|---:|
| AM 班（窗口 00:00–08:00） | 06:30 平段 0.83644 / 碳 0.5849 | **0.95342** | 05:00 谷段 0.56329 / 碳 0.5937 | 0.68203 |
| PM 班（窗口 11:00–13:00） | 12:30 谷段 0.56329 / 碳 0.1646 | **0.59621** | 12:19–13:00 谷段 + **15:04／15:30 平段** | — |
| 全解 | — | — | — | **0.68239**（电费 0.61756） |

（班次感知关掉时的全天均值代理 = 0.93731。）

**错位有三处，量级可核**：
- **AM 弧被高估 0.271 元/kWh（+40%）**：代理按碳强度排序挑到 06:30 的平段电，
  精确择时器在碳价 0.2 下永远挑 05:00 的谷段电。代理 0.95342 对实付 0.68203。
- **PM 弧被低估**：代理只认「午休窗口那一格」，而 PM 多趟车的第二次趟间补电发生在
  15:04／15:30 的**平段**（0.83644），代理里根本没有这个窗口。
- **回场时刻的梯度恒为零**：由于单价是按**客户所属班次**查表，而客户班次是固定数据，
  「同一批客户在 PM 两趟之间怎么分」不改变代理电费一分钱。
  15:00 这条谷／平边界（0.56329 → 0.83644，差 **0.27315 元/kWh**）
  **在内核目标里完全不存在**。

**具体一笔手算**（run_02，`EV_D_OSM_WAY_1071205721_4` 第 3 趟）：
起充 904.1 分、29.4155 kWh、平段 0.83644 → 电费 24.60 元。
若回场早 4.1 分钟落在谷段：29.4155 × 0.56329 = 16.57 元，**省 8.04 元**。
判据：趟间补电窗口下界 `earliest = previous_return`（`charging.py:2199`），
择时器在 `[earliest, latest]` 内取目标最小（`charging.py:2210` → `_select_depot_charge_start_from_windows`，
`charging.py:582-634`）。上界必然满足 `latest ≥ start = 904.1 > 900`。
若 `earliest ≤ 900`，则 900 分（谷段 0.56329，严格便宜于 0.83644）落在 `[earliest, latest]` 内，
择时器必然选它——但它选了 904.1。**所以 `earliest = previous_return > 900` 是逐行可推的**，
904.1 就是回场时刻，离 15:00 的谷段边界只差 4.1 分钟。

### 问题 3：充电时刻修复发生在何时——**只在个体评价前批量调用；内核局部搜索的接受／拒绝用的是纯代理值。判定：证实。**

`repair_changed_duties(_outcome)` 的全部调用点（仓库内 grep，排除定义处）：

| 调用点 | 时机 |
|---|---|
| `runner.py:660` | 内核**收敛之后**，对最终种群每个成员解码后各调一次 |
| `education.py:384,396` | 教育阶段每个候选动作评价前（只有 `whole_duty_type_exchange` / `depot_collaboration` 两个通道） |
| `initialization.py:800,808` | 初始种群构造 |
| `integrated_private.py:409,417` | `integrated` 模式的子代（本批不走这条） |
| `dynamic_insertion.py:339` | 动态插入（本批 `dynamic_insertion_operator.enabled = False`） |

**内核局部搜索里一次都没有。** 内核自己的接受／拒绝在
`runner.py:615 algorithm.run(NoImprovement(patience))` 内部完成，
用的是 `engine.penalty_manager` + `data` 的代理 `distance`／`duration`。

**路线动作的「充电收益」何时才被看到**：只有当该路线**活到内核最终种群**、
并被 `runner.py:625 natives = [kernel_result.best, *population]` 解码时。
种群上限 `max_pop_size = 65`（metadata `effective_population`），
所以每轮最多 66 个候选进精确账。实测每跑 `full_evaluations` 只有 **109–167**
（含 25 个初始个体、2–3 轮），对照内核圈数 **52,430–113,563**。
也就是说：**万分之一量级的候选才被按真实充电成本评价过一次。**

### 问题 4：班次回场上界缺失的实际影响——**缺陷属实，但对「③ 拿不到路线收益」贡献小。判定：证实（缺陷）／小（贡献）。**

上界 `_latest_trip_departure_second`（`charging.py:1513-1528`）来自
`multitrip_schedule.py:561-569` 的后向递推，只含本趟客户与终点节点 `due_time`，
**不含「本车必须在本班次结束前回场」这条 duty 级约束**；班次侧只接了下界
（`charging.py:2245-2255` 的 `shift_floors`）。已有记录见
`docs/handoff/code_review_charge_timing_20260904.md` §8（`MT-HGS/run_04` 的
`EV_D_OSM_WAY_1071205721_7#T2` 固定晚 118.6639562 s）。

**十次两臂计数**（读自 `metadata.json` 的 `accounting.charging_rejection_reasons`，
午谷批 `P=0.2`）：

| 通道 | MT 提出 | MT 拒绝 | MT 拒绝率 | MTC 提出 | MTC 拒绝 | MTC 拒绝率 |
|---|---:|---:|---:|---:|---:|---:|
| `depot_collaboration` | 34,570 | 34,052 | **98.50%** | 27,355 | 26,984 | **98.64%** |
| `whole_duty_type_exchange` | 80,533 | 17,275 | **21.45%** | 55,653 | 13,833 | **24.85%** |

分项：`NO_FEASIBLE_WINDOW` MT 3,494 / MTC 3,249；`SCHEDULE_CONFLICT` MT 8,211 / MTC 6,291；
`PRESCREEN_REJECT` MT 39,479 / MTC 31,277。
按**比率**看两臂几乎一样（与北京批 §1.4 的 +15% 同方向、同量级）。
不可行个体数：两臂 `verdict` 全为 `RUN_COMPLETE`，无解被策略判不可行
（`comparison_n10/summary.json` 的 `infeasible_under_policy` 为 0）。

**为什么贡献小**：即便把这些候选全部救活，**这两个通道都不改「同一辆车两趟之间的客户归属」**，
所以救回来的候选一个也变不出「第三趟早 4 分钟回场」。它吃掉的是车型互换与跨车场整趟互换的
候选量（估算 ≈ 每跑 4.6 万次提出里的 4.5 万次被挡），对本病灶是旁支。

### 问题 5：种群与接受规则——**不可行个体确实进池，但「③ 搜到过更好解却被丢弃」不能判定；原因是丢弃发生在内核的代理择优里，按构造不留痕。判定：不能判定。**

- 内核最终种群的**可行与不可行两个子种群都会被解码**：
  `runner.py:625 natives = [kernel_result.best, *population]`，
  而 `third_party/setp_hgs_kernel/setp_hgs_kernel/Population.py:35-43` 的 `__iter__`
  先吐 `_feas` 再吐 `_infeas`。`runner.py:673` 只保留精确判定可行的
  （`if full.feasible: exact.append(...)`）。
- 精确侧的外部种群在本模式下**没被用过**：metadata
  `accounting.population_admissions = 0`、`population_admission_attempts = 0`。
  `docs/handoff/code_review_charge_timing_20260904.md` §8 描述的
  `_infeasible` 子种群（`external_population.py:68-72`）属于 `integrated` 模式。
- **没有搜索过程最优轨迹**：`convergence.csv` 只有 2 行（每轮一行），
  run_02 两行 `best_feasible_raw_cost` 都是 2588.167012636026——即第二轮没改进；
  `convergence_diagnostics.csv` 同样只有 2 行。
- **决定性的一点**：真正的丢弃发生在内核 5 万–11 万圈的代理择优里。
  一条「回场早 4 分钟、精确账便宜 8 元」的路线，在代理眼里与原路线**电费完全相同**
  （问题 2），只要它的里程／油耗代理稍差一点点就会被淘汰，
  **而这次淘汰不写任何日志**。所以「③ 有没有见过更好的解」按当前落盘无法判定；
  「无法判定」本身就是一条要登记的缺口。

### 问题 6：warm-start 通道——**本批没有用 warm start；且 warm start 的充电计划在投影进内核时被整体丢弃，回来后按策略重算。判定：证实（机制）／不适用（本批）。**

- 本批未使用：24 个 metadata 的 `requested_initial_solution` 全为 `None`
  （`run_ideal_construction_one.sh` 未传 `--initial-solution`）。
- 读入路径：`run_problem_hgs_private_technical.py:1795-1796` → `_load_registered_initial_solution`
  （`:181-193`），保留完整 Duty（含充电会话）。
- **投影进内核时充电被丢掉**：`kernel_proposals.py:671-704 _project` 只用
  `trip.customer_ids` 造 `IndependentKernelTrip`，`charging_sessions` 一个字段都不带。
- 回来时充电按策略重算：`runner.py:660 repair_changed_duties_outcome` 用
  `policy.charge_timing_policy`（MTC 为 `cost_plus_carbon`，MT 为 `asap`）重排。
- **初始个体在内核里就是普通成员**：`runner.py:589-598` 把 seeds 投影进 `init`（`:596 init.append(engine.project(individual))`），
  之后由 `GeneticAlgorithm` 按代理适应度正常淘汰，没有保护位。
  所以「造一个对齐谷段的初始解喂进去」这条路是被堵死的：它的对齐优势在代理里不可见，
  会被当成一个普通（甚至偏差）的解淘汰掉。

---

## 二、病灶排序表

| # | 候选病灶 | 证据 | 判定 | 对「③ 拿不到路径收益」的贡献 |
|---|---|---|---|---|
| 1 | **路线代理的电动车电价与回场时刻无关**（每班次一个常数，取自班次开始前的窗口） | `kernel_proposals.py:1292-1319`（窗口＋排序键）、`:1401-1416`（按客户班次查表）、`:1174-1177`（该值就是内核目标）；客户班次固定：`shift_contract.json` AM17/PM33、`switched_customer_count:0` | **证实** | **大**。15:00 的 0.27315 元/kWh 边界在内核目标里恒为零梯度；这是 ③≈② 的主因 |
| 2 | **能改「同车两趟之间客户归属」的动作通道被硬关**，精确账下没有任何趟重划动作 | `integrated_private.py:200 include_structural_channels=False`；20 个 metadata 的 `proposed_actions` 里 `multi_trip` 计数为 0 | **证实** | **大**。内核收敛后唯一能按真实充电成本纠偏的入口不存在 |
| 3 | **精确评价只覆盖内核最终种群的 ≤66 个成员** | `runner.py:615,625,660,671`；`full_evaluations` 109–167 对 `iterations` 52,430–113,563；`max_pop_size=65` | **证实** | **中**。即便代理有梯度，采样密度也只有万分之一量级 |
| 4 | **班次感知代理按碳强度而非按钱排序**，AM 弧单价被高估 40% | `kernel_proposals.py:1314-1318`（键里无 `carbon_price`）；实测 AM 代理 0.95342 对实付 0.68203 | **证实** | **中**。扭曲的是油／电分工与车队构成（MTC 六次 2油3电 vs MT 四次 3油3电），不直接扭曲择时 |
| 5 | **第二轮起标量单价覆盖，连班次分辨率也丢掉** | `kernel_proposals.py:1027-1031`；`runner.py:707-711`；`restarts` 2–3 | **证实** | **小**。第一轮的路线骨架已定型 |
| 6 | **趟间补电时刻上界不含班次回场约束** | `charging.py:1513-1528`、`:2199-2205`；`code_review_charge_timing_20260904.md` §8；两臂拒绝率 98.50% vs 98.64% / 21.45% vs 24.85% | **证实（缺陷）** | **小**。吃候选量，但被吃的两个通道本来就改不了趟重划 |
| 7 | 「AM/PM 趟间迁移客户」这条设计 | 客户班次是固定数据（`shift_contract.json`）；`assert_candidate_routes_single_shift`（`runner.py:647`） | **证伪（不可构造）** | **无**。可构造的版本是**同班次内**的趟重划，即 #2 |
| 8 | `charging_prescreen.enabled` 落盘为 `False` 但预筛实际在跑 | `runner.py:741 charging_prescreen_accounting=None`；`charging_rejection_reasons` 里有 `PRESCREEN_REJECT` | **证实（只是落盘缺口）** | **无**（不影响数字，但台账要修） |

**一条必须写清的前提（不是病灶，别改）**：充电量策略是 `just_enough`
（`run_problem_hgs_private_technical.py:216`（`_policy` 里写死 `charge_amount_strategy="just_enough"`）；
`charging.py:266` 依赖该值）。**正因为「只充够下一趟」，午间谷段的钱才只能靠改路线拿到**：
若改成 `max_coverage`／`full`，run_02 的 `EV_..._4` 可以在 13:00 谷段一次性充够 T2+T3
（18.43 + 29.42 = 47.85 kWh，同解里已存在 46.94 kWh 的单次会话，容量够），
直接省掉 15:07 那笔平段电——**但这笔钱会落进 ②（固定路线重排），③−② 仍然是 0**。
这与用户红线（降本减碳必须经由路线改变实现）正好相反，**不要动它**。

---

## 三、可施工设计（不写代码）

三个设计按「解决第几号病灶」排序。**验证指标统一用「谷外趟间电量」**
（每个解里 `trip_index ≥ 2` 且起充落在谷价之上的会话，折成
`Σ kWh × (实付电价 − 0.56328575)`），理由：北京批已证明择时机制的货币量级只有 8–10 元，
而单臂十次极差 33–47 元，**任何 10 元级的改进在 n=10 的 ③−② 上必然被噪声淹没**
（今天的 p=0.970 就是这么来的）。当前基线：MTC 十次 **10.07 元/跑**，
其中离 15:00 边界 15 分钟以内的 **4.73 元/跑**。

### 设计 A（首选）：把路线代理的电动车电价改成「按回场时刻查槽价」

- **机制**：给内核目标一个真实的时刻梯度。内核已经在算每条弧的到达时刻
  （`duration` 里已含行驶 + `reload_gap_seconds`），把「客户 → 车场副本」这条**回场弧**
  的电动车代理成本，从「按班次查常数」改成「按该弧的预计到达时刻查日历槽」的分段常数：
  回场时刻落在谷段 → 用谷价，落在平／峰 → 用对应价。
- **改动点**：
  - `kernel_proposals.py::_route_proxy_cost_units`（`:1340-1419`）——EV 分支
    增加一个「回场弧」入参，按到达时刻区间取价；
  - `kernel_proposals.py::_build_unique_asset_problem`（`:1129-1198` 建边循环）——
    对 `right.node_id in reload_ids` 的弧，用「上一趟出发时刻 + 该趟时长」的
    **构造期估计到达时刻**（首轮用参考解的趟时长，后续轮用上一轮精确最优的实际回场时刻，
    走已有的 `route_engine_factory(**factory_kwargs)` 反馈通道，`runner.py:702-714`）；
  - 顺手把 `_rebuilt_shift_aware_ev_unit_costs`（`:1312-1318`）的排序键从
    `(碳强度, 电价, -起始)` 改成 `(电价 + 碳强度/1000 × 碳价, -起始)`——修病灶 #4。
- **解决**：病灶 #1（主）、#4（顺带）。
- **复杂度/耗时**：建边是 O(节点² × profile)，一次性；不改内核内循环，**单圈成本不变**。
  预期总耗时变化 < 2%。风险是内核弧成本不再满足三角不等式的直觉，但代理本来就不是度量。
- **10 分钟内的短跑验证**：
  1. **单元核对（秒级，不求解）**：**客户集合必须固定**——取同一辆电动车的同一批 PM 客户
     （例如 8 个），只改两趟之间的切分（5+3 与 3+5），使第 2 趟回场分别落在 15:00 前后。
     调 `_build_unique_asset_problem` 取两种切分的代理总成本。
     **判定线：改后两者必须不同，差额 ≈ 第 3 趟能量 × 0.27315 元/kWh；改前两者的电费项必须逐位相同**
     （里程项会因顺序不同而变，比对时只看电动车推进成本那一项）。
     只要客户集合不固定，这条核对就无效——今天的代理按客户所属班次查表，
     换一批客户本来就会变价，与时刻无关。
  2. **一次 5 分钟单跑**（`P=0.2/MTC-HGS`，同参数），读该解的「谷外趟间电量」。
     **判定线：从 10.07 元降到 ≤ 4 元算有效；仍 ≥ 8 元算无效。**
- **预期效应**：内核开始把 PM 第 2 趟压短以赶在 15:00 前回场。
  谷外电量的可拿上限是 10.07 元/跑，其中 4.73 元/跑（离边界 ≤15 min）几乎必然拿到。
  折算 ③−② 预计从 **−0.31 元** 走到 **−5 ～ −8 元**（把 10.07 当上限、4.73 当保底）。

### 设计 B：把「同班次内趟重划」这一个通道放回教育阶段，并按谷外电量定向触发

- **机制**：内核收敛后，对**确实有谷外趟间补电的电动车 duty**，在精确账下试
  `RelocateMove` / `SwapMove` / `OpenTripMove`（`multi_trip` 通道），
  把 PM 第 2 趟的尾部客户挪到第 3 趟（或另开一趟），让第 2 趟回场提前到 15:00 前。
  这是**唯一在精确目标上直接把钱落袋**的设计。
- **改动点**：
  - `integrated_private.py:200` 的 `include_structural_channels=False` 改为
    「只开 `multi_trip`，不开 `depot_collaboration`/`fairness_cross_depot`」
    （`proposals.py:132-140` 的 `structural_channels` 集合按此收窄）；
  - 在 `proposals.py::MechanismProposalEngine.propose` 里加一道**定向门**：
    只对「存在 `trip_index ≥ 2` 且起充时刻落在谷价之上的会话」的 duty 生成 `multi_trip` 动作，
    并且只生成「把源趟末尾 1–2 个客户挪到下一趟」这一族，避免恢复 2026-09-02
    记录的 59.6 万次评价换 16% 改进的旧账。
- **解决**：病灶 #2（主）、#3（缓解——把有限的精确评价花在有钱的地方）。
- **复杂度/耗时**：候选数受定向门约束在每个精确候选 O(EV duty 数 × 2) ≈ 6 个动作，
  每个动作一次充电重排 + 一次增量评价。按当前 `full_evaluations` 109–167 估，
  增量 < 1,000 次评价／跑，**预计单跑增加 30–60 秒**（当前 5–13 分钟）。
- **10 分钟内的短跑验证**：
  1. 一次 5 分钟单跑，`--initial-solution` 直接喂 `P=0.2/MTC-HGS/run_02/best_solution.json`
     （它的两笔谷外电正是 904.1 / 930.2）。
  2. **判定线（三条，全部要）**：
     (a) metadata `accounting.proposed_actions.multi_trip > 0`（通道真开了）；
     (b) `accounting.accepted_actions.multi_trip > 0`（有动作被接受）；
     (c) 新解的谷外趟间电量 < 11.59 元（run_02 基线）。
     其中 (c) 只要降到 ≤ 3.6 元就说明那笔 8.04 元的 4.1 分钟缺口被补上了。
- **预期效应**：把 A 拿不到的「离边界 15–32 分钟」那半边（5.34 元/跑）也拿掉一部分。
  **注意 A 与 B 抢的是同一笔钱**：谷外趟间电量 10.07 元/跑是两者合起来的天花板，不能相加。
  A + B 合起来预计吃掉这笔钱的大部分，③−② 预计到 **−8 ～ −10 元**（上限 −10.07 元）。
  单独用 B（不做 A）也有效，但内核仍会不断产出未对齐的路线，B 只能事后补救，
  效果预计 **−3 ～ −5 元**。

### 设计 C（配套，量小但必须做）：把班次回场上界接进趟间补电窗口

- **机制**：`_latest_trip_departure_second` 在返回前，与「本趟所属班次的结束时刻
  − 本趟从出发到回场的时长」取 min，让择时器在 `[earliest, latest]` 里就排除
  会导致晚回场的时刻，而不是产出一个注定被评价器判死的个体。
- **改动点**：`charging.py:1513-1528 _latest_trip_departure_second` 增加一个
  duty 级上界入参；调用点 `charging.py:2185-2190`（首趟前）与 `:2200-2205`（趟间）
  各传入本趟班次上界（班次窗口已在 `contract.shift_window_second_by_id` 里，
  `kernel_proposals.py:1293` 用的就是它）。
- **解决**：病灶 #6。
- **复杂度/耗时**：常数时间，**无耗时影响**。
- **10 分钟内的短跑验证**：不需要跑搜索。用已知的确定性个案：
  `solver/reports/ablation_formal_10x_v5_20260904/MT-HGS/run_04/best_solution.json`，
  按 `carbon_min` 策略重排（`build_charge_timing_comparison.py` 的既有通路）。
  **判定线：改前 `EV_D_OSM_WAY_1071205721_7#T2` 固定晚 118.6639562 s 被判不可行；
  改后该解在 `carbon_min` 下可行**（择时器退回到一个更早的合法时刻）。单个案、秒级。
- **预期效应**：对 ③−② 本身 **≈ 0**；价值在于把 `NO_FEASIBLE_WINDOW`
  （两臂十次合计 3,494 / 3,249）里可救的那部分救回来，
  并解除「均一电价 + cost_plus_carbon」情景下的既有欠账。

### 明确不推荐：把精确充电增量搬进内核的接受判据

理论上正确（这才是真正的联合优化），但代价不可接受：内核每跑 **52,430–113,563 圈**，
每圈内部还有成百上千次局部搜索评价，而当前全跑的精确评价只有 **109–167** 次。
按当前 `charging_repair_cache` 的命中率（run_02：3,236 命中 / 2,617 未命中）估，
即便全缓存也是三到四个数量级的膨胀。**这条恰恰是设计 A 存在的理由**：
A 是它的廉价替身——用一个带回场时刻梯度的代理，把正确的方向便宜地喂给内核。

---

## 四、附：口径与可复算

- 算例 `cn-jjj-50c-01-DEPOTSEARCH-d996f755bd`，日期 **2025-02-12**（`china81.py:42`），
  日历 `data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904/tariff_carbon_hourly_calendar.csv`
  （谷 01:00–06:00 与 **12:00–15:00**；峰 10:00–12:00 与 17:00–23:00）。
- 班次 `shift_contract.json`：AM 08:00–11:00、午休 11:00–13:00（**必须回场**）、PM 13:00–19:00。
- 全部数字读自
  `solver/reports/ideal_construction_20260904/P=0.2/{MT-HGS,MTC-HGS}/run_*/{metadata.json,best_solution.json}`
  与 `comparison_n10/{CONFIRM.md,summary.json}`。
- 手算复现：`cost_elec` 逐位对上官方 `breakdown.cost_elec`（run_02：131.8928），
  确认日历、日期、槽映射三者口径一致。
