# E7 不可行根因诊断（只读）

- 任务编号：`E7-INFEASIBILITY-DIAGNOSIS-20260731`
- 日期：2026-07-31
- 性质：只读诊断。未跑实验、未重跑任何单元、未修改任何代码或封存产物。分析脚本在本目录 `scripts/`。
- 结论标签：`FACT` = 直接读到的数字或代码行；`INFERENCE` = 解释。

---

## 0. 一句话结论

114 个失败单元全部收敛到**同一条判定语句**（`dynamic_multitrip_schedule.py:466-469`），
但这条语句下面藏着**三块互不相同的失败机制**（§8 归因表）：
50c 滚动臂是**事件流本身生成了到达时已过期的新订单**（5 条流精确对应 5 个失败阶段，无一例外）；
静态臂是**零自由度**（三规模全灭，且运行前已被写进自检通过条件）；
100c/150c 滚动臂是**第一个触发点的续排就找不到可执行延续**。

另一条独立于可行性的发现：**整个 120 单元矩阵里，臂间只分化过一次**（50c seed 4 的 NO_COOPERATION）；
30 组滚动臂中 29 组三臂逐字段完全相同。

用户"屎山代码"的怀疑：**部分成立但不是主因**。四层 runner 链、monkeypatch 式臂控制、
一个从未被读取的 `ARM_CONFIGS` 字典确实存在（下详），但它们不是 114 个失败的原因。
真正被证实的接线缺陷只有一处：**碳感知/碳盲开关有一半没接上**。

---

## 1. 数据口径

- 统计单位：120 个正式单元 JSON（3 规模 × 10 算法种子 × 4 臂），路径
  `baselines/china_e3_e7/e7_dynamic_v3_20260731/formal/{50c,100c,150c}/tasks/*.json`，
  排除 macOS AppleDouble `._*` 文件。
- 事件流：15 条冻结流（3 规模 × 5 流），
  `baselines/china_e3_e7/mechanism_foundation_20260730/inputs/e7_events/<instance>/stream_seed{1..5}.json`。
- 种子→流映射：`stream_seed = 1 + ((algorithm_seed − 1) mod 5)`
  （`e7_dynamic_v3_20260731/pre_registration.json` 的 `event_streams.assignment` 字段）。
- 算例：50c = `cn-prd-50c-01-V2-LOCATIONS`，100c = `cn-prd-100c-02-V2-LOCATIONS`，
  150c = `cn-prd-150c-01-V2-LOCATIONS`。
- 阶段分批规则由 `solver/src/setp_solver/search/dynamic.py:998-1023` 定义，
  本诊断在 `scripts/q1_event_vs_fleet.py:22-48` 逐行复刻（不 import solver，避免任何副作用）。

**必须先说的一条口径问题（FACT）**：150c 的 40 个单元**共用同一个名义方案**
（`baselines/china_e3_e7/mechanism_foundation_20260730/inputs/e6/cn-prd-150c-01-V2-LOCATIONS__mismatch00/initial_solution.json`，
`nominal_plan_sha256` 只有 1 个取值），而 50c/100c 每个种子有独立的 E3 JOINT 方案（各 10 个不同 sha256）。
150c 的 `nominal_total_cost` 在 10 个种子上全部等于 7901.137199991607。
所以 150c 的 40 个单元实际只携带 **5 条流 × 1 个方案** 的信息量，种子维度是退化的。

---

## 2. 失败普查（FACT）

| 规模 | 单元 | PASS | LEGAL_INFEASIBLE |
|---|---:|---:|---:|
| 50c | 40 | 6 | 34 |
| 100c | 40 | 0 | 40 |
| 150c | 40 | 0 | 40 |
| 合计 | 120 | 6 | 114 |

按臂 × 失败文本前缀：

| 前缀 | STATIC_FIXED_RECOURSE | 三个滚动臂 |
|---|---:|---:|
| `no feasible vehicle type assignment for separate event trips: …` | 30（10 种子 × 3 规模，全部） | 0 |
| `stage search found no executable continuation (…)` | 0 | 84 |

**两类文本的底层原因是同一条**（FACT）：滚动臂那 84 条的 `top_rejections` 列表里，
**84/84 的第一名都是** `E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route <route>`。
把三条 top_rejections 的计数加总，`no inherited asset` 共 23466 次，
另外两个家族只有 `assignment backtracking exceeded 100000` 297 次、`route … exceeds` 246 次。

**滚动臂的失败文本在同一 (规模, 种子) 下三臂逐字节相同：28/28 组**（FACT）——
包括三条 top_rejections 的路线名和计数（例：100c seed01 三臂全是
`AWARE_14_001:77, DYN_EVENT_N4:41, AWARE_17_001:35`）。

**评价数账（FACT）**：`per_search_pass_cap=600`、`per_stage_total_cap=1200`。
84 个滚动臂失败单元中，**84/84** 满足
`actual_evaluations = completed_stage_count × 1200 + 600`。
6 个 PASS 单元满足 `actual_evaluations = stage_count × 1200 = 4800`。
即：**失败阶段只烧掉了一趟 600 次的搜索，而不是两趟。**

---

## 3. 问题 1：事件流强度对不对得上车队余量

### 3.1 车队与名义方案资产（FACT）

车队上限来自 `data/ChinaInstances/china81_finite_fleet_authority_v1_20260723/fleet_caps.csv`；
名义方案资产按 `(home_depot_id, vehicle_type)` 数路线。**路线数是实体车数的上界**——
多趟串接只会让实体车更少，因而"未动用的合法运力"那一列是**下界**，方向是安全的。
（50c 的 PASS 单元 `physical_vehicle_ids` 恰为 8 个、与 8 条路线相等，但那是**动态续排之后**的清单，
不能反推名义方案本身有无串接；此处只取上界口径。）

| 规模 | 车场 | 上限 cv/ev | 名义方案 cv/ev | 该场未动用的合法运力（下界） |
|---|---|---|---|---|
| 50c | D_guangzhou | 4 / 1 | 2 / 1 | ≥2 CV |
| 50c | D_shenzhen | 5 / 2 | 3 / 2 | ≥2 CV |
| 100c | D_guangzhou | 8 / 2 | 5 / 2 | ≥3 CV |
| 100c | D_shenzhen | 10 / 3 | 7 / 3 | ≥3 CV |
| 150c | D_dongguan | 4 / 1 | 3 / 1 | ≥1 CV |
| 150c | D_foshan | 4 / 1 | 3 / 1 | ≥1 CV |
| 150c | D_guangzhou | 9 / 3 | 6 / 3 | ≥3 CV |
| 150c | D_shenzhen | 10 / 3 | 7 / 3 | ≥3 CV |

规模合计：50c 12 上限 / 8 在用；100c 23 / 17（seed04、seed10 为 18）；150c 35 / 27。

### 3.2 新增订单的归属高度集中（FACT）

新增订单的责任车场继承捐赠客户的归属
（`e7_dynamic_v3_20260731/inputs/owners/<instance>/stream_seed*.json` 的 `derivation` 字段：
"base ZONE responsibility; add inherits exact donor owner"）。逐条流统计：

- **50c：5 条流 × 5 个 add，共 25 个，100% 归 `D_guangzhou`。**
- **100c：5 条流 × 10 个 add，共 50 个，100% 归 `D_guangzhou`。**
- **150c：5 条流 × 15 个 add，共 75 个，100% 归 `D_dongguan`。**

也就是说，**150c 的全部新增订单都落在 4 个车场里最小的那个**（dongguan 上限 4 CV + 1 EV，名义方案只用了 3 CV + 1 EV）。

### 3.3 新增订单数 / 可继承车辆数（分桶后的比值）

**先交代分母口径（这一条决定了本节结论的效力）**：任务要求的分母是"该阶段名义方案里**处于空闲/可继承状态**的实体车辆数"。
计算它需要按触发时刻重放证书执行账（`build_certificate_execution_ledger`），
只读条件下拿不到——失败单元没有落盘 `asset_states`，重放就是跑实验，本任务禁止。
**故本节分母用的是该车场名义方案的全部资产（含该时刻仍在执行名义任务的车）**，是个天花板。
因此下表的比值一律是**低估**，本节的"不超过"型结论是**在天花板口径下成立**，
真实的空闲口径比值只会更高，可能越过 1.0。这条列为未查清项。

比值按 `(该阶段该车场的 add 数) / (名义方案在该车场的路线数上界)`。完整逐阶段表在
`diagnosis_numbers.json → q1_event_intensity_vs_fleet.streams`。整流汇总：

| 规模 | 落点车场 | 全流 add 数 | 该场可继承资产上界 | 全流比值 | 单阶段最大 add 数 | 单阶段最大比值 |
|---|---|---:|---:|---:|---:|---:|
| 50c | D_guangzhou | 5 | 3 | 1.67 | 2 | 0.67 |
| 100c | D_guangzhou | 10 | 7 | 1.43 | 4 | 0.57 |
| 150c | D_dongguan | 15 | 4 | 3.75 | 4 | **1.00** |

**FACT（天花板口径）**：在"该车场全部名义资产"这个分母下，不存在"某个阶段一次性新增的订单数超过全部资产"的情况——
最坏是 150c 的 1.00（stream1 stage1：4 个 add 对 4 个 dongguan 资产）。整条流的累计比值在 150c 达到 3.75。

**未查清**：这 4 个 dongguan 资产在触发时刻 30937.6 s 有几个真的空闲，未知。
若空闲数少于 4，该阶段的真实比值就 > 1.0。要算出来必须重放证书执行账，本任务禁止。

### 3.4 决定性发现：新增订单在被处理时时间窗已经过期（FACT）

逐条 add 事件比较它的 `new_due_time` 与它所在批次的 `trigger_time`：

| 规模 | 流 | 首个含"到期时刻早于触发时刻"的阶段 | 滚动臂实际失败阶段 |
|---|---:|---:|---:|
| 50c | 1 | 4 | **4** |
| 50c | 2 | 3 | **3** |
| 50c | 3 | 4 | **4** |
| 50c | 4 | 无 | **无（PASS）** |
| 50c | 5 | 3 | **3** |

**50c 上 5/5 精确对应，零例外。** 唯一没有过期订单的 stream 4，正是唯一跑通的那条流。

具体数字（50c stream1 stage4，触发时刻 64800.0 s）：

| 客户 | t_appear | ready | due | due − trigger |
|---|---:|---:|---:|---:|
| N2 | 59384.6 | 59384.6 | 59384.6 | **−5415.4** |
| N3 | 59614.7 | 59614.7 | 60316.8 | **−4483.2** |

50c stream2 stage3（触发 54000.0）：N1 due=53801.3，**−198.7**。

**为什么这必然导致那条报错**（FACT，代码语义）：
`dynamic_multitrip_schedule.py:1237-1248` 从路线最后一个节点的 `due_time` 向前递推出
`latest_start`，`latest = latest_start + origin.service_time` 就是该路线的**最晚发车时刻**；
`:719` 里 `boundary = max(stage_start, asset.available_second) ≥ 触发时刻`；
`:743` `if departure > profile.latest_departure_second + _TOL: continue`。
订单 due 已早于触发时刻 ⇒ latest < boundary ⇒ 所有资产都被 `continue` 掉 ⇒
`:466-469` 抛 `no inherited asset can serve open route`。**与车队余量无关，加多少车都无解。**

100c / 150c 也都含过期 add（首个出现在阶段 3–5），但那两个规模在**阶段 1 就死了**，
过期订单还没轮到，所以在那里不是主因。

### 3.5 100c / 150c 的阶段 1 失败（部分未查清）

**FACT**：100c、150c 的全部 80 个单元 `attempted_stage_count=1, completed_stage_count=0, failure_stage=1`。
阶段 1 的触发时刻是 29726–32400 s，该批次的 add 订单 ready 在 41028–58611、due 在 43144–61115，
**没有一个过期**。所以 50c 那套机制在这里不适用。

**FACT**：滚动臂阶段 1 的失败文本是 `initial_feasible=False, changed=600 (150c 为 594), executable=0, accepted=0`，
top_rejections 首位是 `AWARE_14_001`（100c）/ `AWARE_12_001`（150c）。
`AWARE_nn_mmm` 这种编号由 `baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py:812` 生成，
含义是"给排名第 nn 的资产新开的第 mmm 趟"——**不是名义方案里原有的路线，而是搜索自己造出来的候选趟次**。

**未查清**：这些候选具体卡在 `_dynamic_assignment_candidates`（`:702-747`）四个条件的哪一个
（车型不符 `:715` / 车场不符 `:716` / 发车时刻越过最晚发车 `:743` / EV 电量不够 `:720-730`）。
落盘字段只保留了 top-3 的路线名与计数，没有保留被拒条件的分解；要定位到条件级别需要重跑，本任务禁止。

**一个必须记录的边界条件（FACT）**：预算 600 是在 **50c seed1 stream1 FULL_ROLLING 单阶段探针**上标定的
（`pre_registration.json → budget.probe_instance/probe_algorithm_seed/probe_stream_seed/probe_arm/probe_stages`，
`budget_lock.json → selected_per_search_pass_cap=600`）。该探针本身用 cap=800 跑出 `status=PASS`
（`probe/cap_800.json`）。**100c 与 150c 从未做过预算探针**，直接套用了 50c 标定的 600。
`changed=600 / executable=0` 说明这 600 次全部用完仍未找到可执行候选，**"600 不够"与"结构性无解"两种解释在现有落盘证据下无法区分**。

---

## 4. 问题 2：资产继承规则到底要求什么

抛错位置：`solver/src/setp_solver/search/dynamic_multitrip_schedule.py:466-469`
（在 `prepare_dynamic_multitrip_solution` 的回溯赋值函数 `assign` 内）。
候选集由 `_dynamic_assignment_candidates`（`:702-747`）生成。**一辆继承车要能接管一条开放路线，必须同时满足**：

| # | 条件 | file:line | 实际代码语义 |
|---|---|---|---|
| 1 | 车型完全一致 | `:714-718` | `state.vehicle_type != route.vehicle_type.lower()` → `continue`。CV 不能顶 EV 的趟，反之亦然。 |
| 2 | **归属车场完全一致** | `:714-718` | `state.home_depot_id != route.home_depot_id` → `continue`。**硬相等，无跨场调拨**。 |
| 3 | 资产已释放 | `:719` | `boundary = max(stage_start, asset.available_second)`。前一趟未返场则用返场时刻。 |
| 4 | 能赶上最晚发车 | `:743-744` | `departure > profile.latest_departure_second + _TOL` → `continue`。`latest_departure` 由路线上所有节点 `due_time` 向前递推（`:1237-1248`）。 |
| 5 | EV：剩余时间内充得进足够的电 | `:720-730` | `reachable_energy_kwh(battery, latest_departure − boundary) + _TOL < drive_energy` → `continue`。22 kW 桩功率写死在 prices。 |
| 6 | EV：发车电量口径 | `:731-740` | 缺多少补多少（`needed = max(0, drive_energy − battery)`），发车时刻取 `max(preferred, energy_ready)`。 |

**候选池本身的边界（这条最关键）**：候选只在 `working` 里找
（`:712` `for asset_id, asset in working.items()`），而 `working` 只由 `normalized_states` 构造
（`:392-400`），`normalized_states` 来自入参 `asset_states`。**函数体内没有任何一处向 `working` 添加新键。**

被排除的情况，逐条对照用户列的清单：

- **绑定在别的车场** → 排除（条件 2，硬相等）。
- **本阶段已被使用** → **不排除**。资产被占用后 `available_second` 前移（`:521`），仍留在候选池里，
  只要时间赶得上就能再接一趟；`:490-502` 还做了等价资产去重以剪枝。
- **电量不足** → 对 EV 排除（条件 5）。CV 不受此限。
- **时间窗来不及** → 排除（条件 4）。这是 50c 失败的实际触发条件。
- **车型不匹配** → 排除（条件 1）。
- **回溯预算** → `:420-422` 上限 `_MAX_ASSIGNMENT_STATES = 100_000`（`:64`），超出即判失败。落盘里出现 297 次。

另有一条上游校验：`:371-372` 若有开放路线而 `asset_states` 为空，直接抛
`open routes have no inherited assets`（本批 120 单元未触发）。

---

## 5. 问题 3：动态阶段能不能新开一辆实体车

**不能。FACT。**

- 结构上的封闭点：`dynamic_multitrip_schedule.py:392-400` 构造 `working`，`:712` 只遍历 `working`，
  全函数无写入新键的路径。函数 docstring（`:356-362`）也写着 "No new physical id can be created"，
  但**判定依据是上述代码结构，不是这句注释**。
- 资产宇宙的来源：第一次静态切分在 `:178` `for asset_id, asset in ledger.assets.items()` 建 `asset_states`，
  `ledger` 由 `build_certificate_execution_ledger(solution, certificate, …)` 从**名义方案**算出。
  后续阶段的切分（`:229-344`）拿上一阶段的完整资产表继承，`:245` 的注释明确
  "Assets unused in the preceding continuation remain present instead of silently disappearing"——
  只保证不丢，不新增。

**这是 E7 特有的，不是从静态模型继承的。FACT。**
静态多趟排程 `solver/src/setp_solver/search/multitrip_schedule.py` 的行为正相反：
`_schedule_cv_group`（`:630-648`）在没有空闲车赶得上时执行 `next_local_id += 1`，
**当场新开一辆实体车**，编号 `CV_{depot}_{local_id}`（`:641`）；EV 同理（`:752`）。
新开的总量事后由 `:977-980` 对着 `instance.num_cv` / `instance.num_ev` 校验，
超了才报 `needs N CV but cap is M`。

**INFERENCE**：所以静态模型是"在车队上限内按需开车"，动态续排是"锁死在名义方案实际动用的那几辆车上"。
两者的差额就是 §3.1 表格里那列"未动用的合法运力"：
**150c 的 dongguan 有 ≥1 辆合法但名义方案没用的 CV，而该规模 100% 的新增订单都落在 dongguan，动态阶段却碰不到这辆车。**

---

## 6. 问题 4：为什么 STATIC_FIXED_RECOURSE 在 stream 4 上也失败

**代码路径差异（FACT）**：分派在 `baselines/china_e3_e7/e7_dynamic_20260731/run_e7_dynamic.py:833-844`。
静态臂走 `static_fixed_stage`（`:700-812`），三个滚动臂走 `_ORIGINAL_CONTROLLED_STAGE`（`:845-894`）。

`static_fixed_stage` 整个阶段只做**一件事**（`:713-721`）：调用
`prepare_stage_with_singleton_type_choices`（`baselines/e7_dynamic/e7_dynamic_continuous_trigger_gate_20260714.py:89-130`）。
该函数只枚举**新增趟次的车型**：把所有 `_ADD_` 单例路线（`:102`）在 `(cv, ev)` 上做笛卡尔积（`:104`），
按 EV 数量从少到多排序逐个试 `prepare_dynamic_multitrip_solution`；全试完仍失败就抛
`no feasible vehicle type assignment for separate event trips: {last_error}`（`:130`）。

静态臂**少了的补救手段**（对照滚动臂）：

| 补救手段 | 滚动臂 | 静态臂 |
|---|---|---|
| 同态无协同重排（`asset_aware_future_repack_candidate`） | 有（`probe:696-704`） | 无 |
| ALNS 候选搜索（600 次/趟，两趟） | 有（`probe:740-752, 889-931`） | 无，`"evaluations": 0`（`legacy:787`） |
| 跨场重指派 | 有（`allow_cross_depot=True`，`probe:926`） | 无 |
| 重新组织既有路线以腾出资产 | 有 | 无，路线结构固定 |
| 可调自由度 | 全部 | **仅新增趟次的 cv/ev 选择** |

**结论（FACT + INFERENCE）**：静态臂的唯一自由度是给新增趟次选车型。
只要新增趟次在**原封不动的名义路线结构**下找不到可继承资产，它就必然在阶段 1 死掉，
`actual_evaluations = 0`。30/30 个静态单元都是这个形态。stream 4 不例外——
滚动臂能跑通 stream 4，是因为它们可以**重排既有路线**来腾出资产；静态臂没有这个动作。

**必须指出的一点（FACT）**：静态臂阶段 1 的这个失败**在正式跑之前就被写进了接线自检的通过条件**。
`e7_dynamic_v3_20260731/run_e7_dynamic.py:1364-1377` 显式跑一次 50c seed1 静态臂，
若它**没有**以 `LEGAL_INFEASIBLE` + `final_total_cost is None` + `actual_evaluations == 0` + `failure_stage == 1` 收场，
就抛 `HALT_LEGAL_INFEASIBLE_CLASSIFICATION_SELFCHECK`。
`report.md` 第 22 行把它记为通过项：
"50c STATIC_FIXED_RECOURSE stage 1 retained as LEGAL_INFEASIBLE with null objective and 0 evaluations"。
**也就是说"静态臂会在阶段 1 全军覆没"是运行前已知并被接受的设计状态，不是跑出来才发现的意外。**

---

## 7. 问题 5：三个滚动臂为什么给出完全相同的成本

**这一条分成两个开关，答案不一样。**

### 7.1 协同开关（NO_COOPERATION）：接线正常，且在可观测的样本上真的 binding

**接线路径（FACT）**：
`legacy:860-874` 把 `"no_cooperation"` 作为 `arm` 传进 `probe._controlled_stage`；
`probe:902-915` 据此调用 `base.search_stage(..., allow_cross_depot=False, candidate_best_gate=no_cross_gate)`，
其中 `no_cross_gate`（`probe:863-868`）拒绝任何含跨场客户的候选；
对照 `probe:916-931` 的 `full` 分支是 `allow_cross_depot=True` + `participation_gate`。

**数值证据（FACT，n=2）**：50c seed 4（stream 4）四臂全字段对比：

| 字段 | FULL_ROLLING | NO_COOPERATION | CARBON_BLIND |
|---|---:|---:|---:|
| final_total_cost | 5975.267331229614 | **7217.318971600578** | 5975.267331229614 |
| final_total_profit | 13576.106628048354 | **12334.054987677388** | 13576.106628048354 |
| final_actual_emissions_kg | 380.72346553211526 | **438.7950636519095** | 380.72346553211526 |
| final_charging_energy_kwh | 214.66418669764383 | **215.28179911170668** | 214.66418669764383 |
| final_depot_profit D_guangzhou | 5709.351400127116 | **5410.786039962027** | 5709.351400127116 |
| final_depot_profit D_shenzhen | 7866.755227921238 | **6923.268947715362** | 7866.755227921238 |

NO_COOPERATION 比 FULL_ROLLING **贵 20.786545%**。
50c seed 9（同为 stream 4）则三臂全字段完全相同。

**判定：不是 (a)。是 (b)——接线正常，binding 与否取决于算例实现。**
seed 4 上协同开关同时改变了成本、利润、排放、充电量、两个车场的分账，
这不可能出自未接线的开关；seed 9 上不 binding（该实现里跨场重指派本来就没发生，
`cross_depot_reassignment_after_event=False`、`new_cross_site_customer_ids=[]`）。

### 7.2 碳开关（CARBON_BLIND）：一半接上了，一半没接上 —— 属 (c)

**接上的那一半（FACT）**：`legacy:875-894` 在跑 CARBON_BLIND 时把
`probe._timing_variant_for_strategy` monkeypatch 成恒返 `"immediate"`，
`probe:947-948` 读它算出 `timing_variant`，`probe:967-970` 据此在
`immediate_solution` 与 `aware_solution` 之间选。**这条通路是通的。**
它管的是**事件触发之后**的充电重排时刻。

**没接上的那一半（FACT）**：日初名义方案的充电时刻由
`e7_dynamic_v3_20260731/run_e7_dynamic.py:504-571` 的 `corrected_initial_plan(arm, …)` 决定
（`:575` 把它装成 `PROBE._initial_plan`，正式任务走这条）。该函数：

- `:509-510` 读 `arm` **只为校验合法性**；
- `:513-532` 同时算出 `immediate` 和 `aware` 两个版本；
- `:539-540` **无条件把 `aware` 送进 `prepare_multitrip_solution`**；
- `:564` **硬写 `"strategy": "aware"`**。

`arm` 参数此后再未被使用。**所以 CARBON_BLIND 臂的日初名义方案是碳感知的。**

落盘印证（FACT）：6 个 PASS 单元里，四臂的 `nominal_timing.strategy` 全部是 `"aware"`，
`moved_action_count` 全部是 3，`route_sha256`、`energy_sha256` 逐位相同。
也就是说，**唯一确实发生了碳感知移峰的地方（日初移了 3 个充电动作），在碳盲臂里也照样移了。**

这个缺陷早于 v3：原始 `baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py:544-605` 的 `_initial_plan`
同样接收 `arm` 而不用它，`:549` 硬写 `strategy = "aware"`，
导致 `:576` 的 `timed = immediate if strategy == "naive" else aware` 成为恒真死分支。
v3 的 `corrected_initial_plan` 原样复制了这个行为。

**还有一处会误导读者的地方（FACT）**：接线自检报告里 CARBON_BLIND 的目标值是 2305.468523，
与另外三臂的 2418.475408 不同，看上去像是碳开关起了作用。
但那一行的解由 `run_e7_dynamic.py:1346` 的 `selected = immediate if arm == "CARBON_BLIND" else aware` 单独挑出来，
**只用于填自检表格**，与正式任务实际使用的名义方案（`corrected_initial_plan`，恒 aware）不是同一个东西。

**事件之后那一半也没产生任何差异（FACT）**：6 个 PASS 单元全部
`moved_charge_actions_after_event = 0`、`carbon_aware_charging_shift_after_event = False`；
两个 stream-4 种子上 CARBON_BLIND 与 FULL_ROLLING 的 `final_actual_charging_emissions_kg`
（4.623295546596895）与 `final_charging_energy_kwh`（214.66418669764383）逐位相同。

**判定：(c)。**碳开关的对照面在两端同时塌了——
日初那一半**没接**（是真接线缺陷），事件后那一半**接了但可移动的充电动作是 0**（不 binding）。
**INFERENCE**：即使 E7 全部可行，按当前代码，CARBON_BLIND 与 FULL_ROLLING 的对照也只能反映
"事件后充电重排"这一个窄口径，不反映全天碳感知择时；而在已观测的 2 个单元上这个窄口径的差异恰好是 0。

### 7.3 更关键的一层：84 个失败单元里，臂开关根本没被执行到

**FACT**：`probe._controlled_stage`（`:823-849`）的**第一件事**是跑一趟与臂无关的影子基准
`_same_state_no_cooperation`（`:678-767`），配额同样是 600；臂特定的搜索在 `:884-931` 才发生。
`legacy:897` 记的 `actual = result["evaluations"] + result["shadow_evaluations"]`，故每个完整阶段是 1200。

**FACT**：84/84 个滚动臂失败单元的 `actual_evaluations` 恰好等于 `completed × 1200 + 600`，
即失败阶段只烧掉了**一趟** 600。

**INFERENCE（两条独立证据互相印证）**：失败阶段死在**第一趟**，也就是那趟臂无关的影子基准里。
佐证是 28/28 组三臂失败文本逐字节相同——包括 top_rejections 的路线名和计数，
这只有在三臂执行了完全相同的确定性代码路径时才可能出现。

### 7.4 分化只发生过一次：整个矩阵的臂间同一性

**FACT**：把 30 个 (规模, 种子) 滚动臂组逐组比对全部落盘字段
（`status`、`final_total_cost`、`actual_evaluations`、`completed_stage_count`、
`attempted_stage_count`、`failure_stage`、`legal_infeasibility_reason`）：
**29/30 组三臂逐字段完全相同。唯一分化的是 50c seed 4。**

**这比 §7.3 强得多，因为 8 个失败组是在跑完 2–3 个完整阶段之后才死的**（FACT：
50c 有 4 组 `completed=3`、4 组 `completed=2`）。那些已完成的阶段里，臂特定搜索
（不同的 `allow_cross_depot`、不同的 `candidate_best_gate`）**确实运行过**，各烧了 600 次评价。

**INFERENCE**：失败阶段的影子基准是确定性的、且与臂无关；它在三臂上输出逐字节相同的
`changed` / `executable` / `top_rejections` 计数，要求它的输入——**上一阶段释放出来的解**——也逐字节相同。
即：**在那 8 个多阶段失败组里，臂特定搜索跑过，但每一阶段都选回了同一个解**。

合并结论：**90 个滚动臂单元中，84 个的三臂在任何一个阶段都没有分化过。**
不是"四臂对照跑出来打平"，而是四臂对照在 84/90 上**没有产生任何可比的差异**，
在 60/90 上（100c + 150c）**连臂特定搜索都没执行到**。

整个 E7 正式矩阵里，臂开关改变过结果的观测**只有一个**：50c seed 4 的 NO_COOPERATION。

---

## 8. 问题 6：归因拆分

先把 114 个失败单元按已证实的机制分块（一个单元只计一次，按它实际死在哪里）：

| 块 | 单元数 | 占 114 | 证据强度 |
|---|---:|---:|---|
| **A. 新增订单在被处理时时间窗已过期**（50c，24 个滚动臂单元） | 24 | 21.1% | 5/5 条流的首个过期阶段与实际失败阶段精确相等，唯一无过期订单的 stream 4 是唯一 PASS 的流 |
| **B. 静态臂零自由度**（3 规模 × 10 种子） | 30 | 26.3% | 代码路径唯一自由度=新增趟次车型；`evaluations=0`；且运行前已被写进自检通过条件 |
| **C. 100c/150c 阶段 1 找不到可执行延续**（60 个滚动臂单元） | 60 | 52.6% | 机制未定位到条件级；"预算 600 不够"与"结构性无解"无法区分 |

再按用户给的四个归因维度：

### (a) 事件流强度相对车队余量结构性过高 —— **不成立（按"数量"口径）；成立（按"时间窗"口径）**

- **数量维度在天花板口径下不成立（FACT，附口径条件）**：以"该车场全部名义资产"为分母时，
  单阶段最大比值是 150c 的 1.00（4 个 add 对 4 个 dongguan 资产），其余全部 ≤ 0.67。
  **但这不是任务要的"空闲/可继承"分母**——那个需要重放证书执行账，只读条件下算不出（§3.3）。
  真实比值只会更高。**这一条是条件性否定，不是无条件否定。**
- **时间窗维度成立且是 50c 的唯一原因（FACT）**：事件流里存在 `new_due_time` 早于其自身批次
  `trigger_time` 的 add 订单（最极端 −5415 s），这类订单在数学上无法被任何资产服务。
  这不是"强度过高"，是**事件生成与滚动分批的时钟口径没对齐**——
  订单的 `t_appear` 与 `new_due_time` 之间的间隔可以短于 `delta_t_seconds = 10800` 的分批粒度。
- **归属集中确有结构性问题（FACT）**：150c 的 75 个新增订单 100% 落在 4 个车场中最小的 dongguan
  （名义方案 3 CV + 1 EV），50c/100c 的新增订单 100% 落在 guangzhou。这是 donor 继承归属的直接后果。

### (b) 资产继承规则过严（有余量但规则不让用）—— **成立，且量化了**

**FACT**：动态续排的资产池封闭在名义方案实际动用的实体车上（§5），
而合法车队上限高于名义方案用量：50c 12 vs 8、100c 23 vs 17、150c 35 vs 27。
按车场分桶后，**新增订单落点车场都存在未动用的合法 CV**（50c guangzhou ≥2、100c guangzhou ≥3、150c dongguan ≥1）。
同时 `:716` 的车场硬相等排除了跨场调拨顶替。

**INFERENCE**：对 A 块（时间窗已过期）放开继承规则没用——过期订单加多少车也做不了。
对 C 块（100c/150c 阶段 1）是否有用，现有落盘证据不足以判断。

### (c) 臂开关未真正接线 / 集成层问题 —— **部分成立，但不是 114 个失败的原因**

**已证实的接线缺陷只有一处（FACT）**：碳开关的日初那一半没接（§7.2），
`corrected_initial_plan` / `_initial_plan` 收下 `arm` 参数后弃之不用，硬写 `aware`。

**已证实的"屎山"特征（FACT，但无害）**：

- 四层 runner 链：v3 → v2（183 行薄壳）→ legacy(1857 行) → 2026-07-14 probe(1766 行)，
  运行时靠 `install_adapter()`（`legacy:921-928`）逐个替换 probe 的模块级函数。
- 臂控制靠 monkeypatch（`legacy:876` 替换 `probe._timing_variant_for_strategy`）而非参数传递。
- **`ARM_CONFIGS` 字典（`v3:252-281`）里的 `route_policy` / `cooperation` / `participation` / `charging`
  四个键在整个仓库中从未被读取**；唯一使用点是 `v3:1351` 把它整体摊进自检报告行，
  以及 `v3:1510` 写进自检 JSON。真正的臂行为在 legacy 的 `if/elif` 分支里另行实现。
  这是文档性缺陷——报告里写着的臂配置和代码实际做的事是两套东西。

**这三条都不是 114 个失败的原因**：失败全部由 `dynamic_multitrip_schedule.py:466-469` 这一条判定触发，
与臂配置的表达方式无关。

**但对"四臂对照能否成立"是致命的（§7.3–7.4）**：90 个滚动臂单元里 84 个三臂逐字段完全相同，
其中 60 个（100c + 150c）连臂特定搜索都没执行到，另 24 个（50c）跑过 2–3 个完整阶段却每阶段都选回同一个解；
6 个 PASS 单元里碳臂对照的日初那一半没接线。
**整个正式矩阵里，臂开关改变过结果的观测只有一个：50c seed 4 的 NO_COOPERATION。**

### (d) 其他 —— **两条独立问题**

1. **150c 的种子维度是退化的（FACT）**：40 个单元共用 1 个名义方案，`nominal_total_cost` 全等于 7901.137199991607。
   即使 150c 全部可行，它也只提供 5 条流的信息，不是 40 个独立单元。
2. **预算 600 只在 50c 上标定过（FACT）**：`pre_registration.json → budget` 记录探针是
   50c/seed1/stream1/FULL_ROLLING/单阶段，`budget_lock.json` 据此锁定 600；
   100c 与 150c 从未做预算探针。100c/150c 阶段 1 的 `changed=600, executable=0`
   与"预算不足"完全兼容，也与"结构性无解"完全兼容，落盘数据无法区分。

---

## 9. 交付物

| 文件 | 内容 |
|---|---|
| `report.md` | 本文件 |
| `diagnosis_numbers.json` | 全部数字（单元普查、名义方案退化度、Q1 逐流逐阶段表、Q5 四臂对照） |
| `scripts/collect_units.py` | 读 120 个单元 JSON → `units_table.json` |
| `scripts/q1_event_vs_fleet.py` | 复刻分批规则，产 `q1_event_vs_fleet.json` |
| `scripts/build_numbers.py` | 汇总 → `diagnosis_numbers.json` |
| `scripts/units_table.json`、`scripts/q1_event_vs_fleet.json`、`scripts/q1_expired_vs_failstage.json` | 中间产物 |
| `done.json` | 完成信号 |
