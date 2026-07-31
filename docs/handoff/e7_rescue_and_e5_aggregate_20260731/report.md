# E7 不可行根因诊断 + 文献对照 + 修复选项 + E5 快充 50c 聚合

角色说明：本任务因 Codex CLI 账号级配额耗尽（恢复时间 2026-08-05 13:39）由用户显式授权终端 Claude Code 临时替代执行，本轮只读诊断 + 数据聚合，未改 `solver/` 下任何文件、未改 TeX、未跑新实验、未覆盖任何已封存证据。

---

## 任务一：E7 不可行根因诊断（代码 + 文献）

### 1.1 代码事实核实

正式矩阵 `baselines/china_e3_e7/e7_dynamic_v3_20260731/formal/{50c,100c,150c}/tasks/*.json`（120 个单元）逐个读出：

| 规模 | 可行 | 不可行 | STATIC_FIXED_RECOURSE 失败数 | 三个路线搜索臂(FULL_ROLLING/NO_COOPERATION/CARBON_BLIND)失败数 |
|---|---|---|---|---|
| 50c | 6 | 34 | 10/10 | 24/30（6/30 可行，均在 seed4、seed9）|
| 100c | 0 | 40 | 10/10 | 30/30 |
| 150c | 0 | 40 | 10/10 | 30/30 |

两种不可行原因文字：

- `STATIC_FIXED_RECOURSE`（不做路线搜索，只做精确物理排班）：`legal_infeasibility_reason` 恒为
  `"no feasible vehicle type assignment for separate event trips: E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route <ID>"`。
- 三个开放路线搜索的臂：`legal_infeasibility_reason` 恒为
  `"stage search found no executable continuation (initial_feasible=False, changed=N, executable=0, accepted=0, top_rejections=[...])"`，且 `top_rejections` 里 100% 条目都是同一句
  `"E7_DYNAMIC_MULTITRIP_V1: no inherited asset can serve open route <ID>"`（例：50c seed1 FULL_ROLLING 593 个候选中 443+76+74 个被拒都是这句；100c/150c seed1 同样如此）。

即：无论是否让搜索重排路线，最终卡住的都是**同一个物理排班约束**，只是路线搜索多试了几百个候选、一个都过不去。这不是搜索能力不足，是候选池里不存在任何可行解。

### 1.2 资产继承逻辑定位

- **核心文件**：`solver/src/setp_solver/search/dynamic_multitrip_schedule.py`
- **继承规则的构造处**：`_whole_trip_cut()`（第 578–742 行，`run_e7_dynamic.py` 内的等价函数，实际调用同名 solver 模块）——把每个阶段触发时刻的证书切成"已完成/在途/可编辑"三段，只有可编辑段（尚未发车的整趟路线 + 尚未开始的充电动作）能被下一阶段改写；在途/已完成路线的车辆归属、类型、可用时刻、剩余电量全部原样带入下一阶段的 `asset_states`。
- **精确指派逻辑**：`prepare_dynamic_multitrip_solution()`（第 347–478 行）。文档字符串（第 356–361 行）明确写着："Schedule open routes on the exact inherited assets... Route ids are replaced by the inherited physical id and the next legal trip number. **No new physical id can be created.**"
- **候选筛选的硬性条件**：`_dynamic_assignment_candidates()`（第 702–747 行）：

```python
for asset_id, asset in working.items():
    state = asset.state
    if (
        state.vehicle_type != route.vehicle_type.lower()
        or state.home_depot_id != route.home_depot_id
    ):
        continue
    ...
```

一辆车只有同时满足"车型一致（EV 服务 EV 路线、CV 服务 CV 路线）"和"车场一致"，并且在该路线最晚发车时刻之前处于空闲（EV 还需电量可达），才算候选。

- **报错与分类点**：候选为空时在第 466–470 行抛
  `ValueError(f"... no inherited asset can serve open route {profile.route.vehicle_id}")`；
  路线搜索的候选评价循环在 `baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py` 第 1370–1385 行捕获这类 `ValueError`（计入 `dynamic_rejections`），当全部候选（一次通常 300–800 个）都失败时抛
  `NoExecutableContinuation("stage search found no executable continuation ...")`（同文件 class 定义于第 73 行）。
  `run_e7_dynamic.py` 第 1691–1699 行的 `is_legal_infeasibility()` 把这两类异常都判定为"合同允许的 LEGAL_INFEASIBLE"而非技术 HALT。

### 1.3 用大白话总结这套规则

1. **车队总量在整条动态时域内绝不增加**：不能凭空造一辆新的实体车（no new physical id）。
2. **车辆的车场归属和车型在整条动态时域内锁死**：一辆挂在 D_guangzhou 的 CV，永远只能服务 D_guangzhou 的 CV 路线；不能借调成 EV，也不能换到别的车场常驻（"跨场协同"发生在客户-路线归属层面的搜索阶段，但落到物理排班时，接手的路线仍必须由**该路线当前归属车场**的一辆空闲同型车来执行）。
3. **只有"空闲"车辆能接新活**：已经发车（在途/已完成）的整趟路线和已经开始的充电动作绝对冻结，其车辆状态（可用时刻、剩余电量）原样带入下一阶段；只有尚未发车的车辆槽位可用于新增/被修改的开放路线。
4. **没有拒单，没有延后，没有外包，没有加派车辆**：代码中不存在任何"把这个新订单标记为未服务、计罚金、跳过"的分支。一旦某条新增/被修改的开放路线在当前空闲车辆池里找不到匹配（哪怕只有一条路线找不到），整个任务单元直接判 `LEGAL_INFEASIBLE`，`final_total_cost=None`。

### 1.4 文献对照（已读原文，给出页码）

以下 PDF 均取自 `/Users/zhouleixishu/Zotero/storage/`，页码为 `pdftotext -layout` 抽取的页序（与印刷页码一致或接近，不含期刊页眉的文章页码时以此为准）。

**① Pillac, Gendreau, Guéret, Medaglia (2013), "A review of dynamic vehicle routing problems", European Journal of Operational Research 225, 1–11.**（项目此前笔记称"Pillac 2012"，实为该刊 2013 年正式出版；未找到独立的 2012 版本文件，判定为同一篇文献的年份记忆误差。）
- p.2：运输公司"可以拒绝一个顾客请求，或者因为根本无法服务它，或者因为服务成本过高"，这套"接受/拒绝"流程被称为 **service guarantee**，"已被许多方法采用"。→ 拒单是标准做法之一，且有专门术语。

**② Zhang & Woensel (2023), "Dynamic vehicle routing with random requests: A literature review", Int. J. Production Economics 256, 108751.**
- p.5–6，§4.1 "Rejection"：明确区分"允许拒单"和"禁止拒单"两类问题。**关键句（p.6）**："in the VRPDSRs where rejections are forbidden, the authors primarily focus on minimizing the total travel costs and/or service lateness, and **the time and vehicle constraints should be relaxed to guarantee feasibility**. For instance, Ninikas and Minis (2014) and Sarasola et al. (2016) **assume that the fleet size is sufficiently large to serve all requests**。"
- p.8：举例 Bent & Van Hentenryck (2004) 的做法——先把静态 Solomon 算例求到最优路线数，再**额外加两辆车**，才能保证动态到达时留有余地。
- p.28：定量统计——"**Nearly 36% of the reviewed papers explicitly consider request rejections**, but only 55% of them accept/reject immediately。"

**③ Mardešić, Erdelić, Carić, Đurasević (2024), "Review of Stochastic Dynamic Vehicle Routing in the Evolving Urban Logistics Environment", Mathematics 12.**
- p.12，§3.2.4 "The Ability to Reject Customers"：**"not all instances may have a feasible solution that serves every customer. Consequently, the ability to reject customer requests is a vital component of DVRPs."** —— 把"能拒单"直接定义为动态 VRP 区别于静态 VRP 的标志性特征之一。

**④ He, [等] (2025), "Dynamic electric vehicle fleets management problem for multi-service platforms with integrated ride-hailing...", Transportation Research Part B 199, 103281.**（EV 车队、滚动时域，场景与本项目最接近）
- p.16：为保证解存在，直接**假设**"电动车数量是充足的（例如可用电动车数不少于请求数）以确保可行解存在"。
- p.18：滚动时域实验里再次明确"我们预期有相应充足数量的电动网约车（**保证充足的车队规模能满足全部服务请求**）"。→ 这篇论文选择"车队足量假设"而不是让物理排班硬性卡死。

**⑤ Ojeda Rios, Xavier, Miyazawa, Amorim (2021), "Recent dynamic vehicle routing problems: A survey", Computers & Industrial Engineering 160, 107604.**
- p.4/p.15/p.18：把"是否允许拒绝顾客"列为动态 VRP 分类法的独立维度之一（与车辆容量约束并列），并指出"在存在硬时间窗、不允许拒单的场景里，为了保证有解，这两个条件通常不能同时成立"。

**⑥ Goodson, Ohlmann, Thomas (2013), "Rollout Policies for Dynamic Solutions to the Multivehicle Routing Problem with Stochastic Demand and Duration Limits", Operations Research 61(1), 138–154.**
- p.12：车队规模 M 直接取"该算例静态 VRP 最优解的路线数"（固定），但目标函数是"**期望服务需求量**"，允许在预算/时限内**只服务一部分需求**而不判整体不可行——用"软目标"而不是"硬可行性"处理运力不足。

**⑦ Wang, Bell, Steinegger 等 (2024), "Collaboration and resource sharing in the multidepot time-dependent vehicle routing problem with time windows", Transportation Research Part E 192, 103798.**（多车场协同论文，与 E7 的 NO_COOPERATION/FULL_ROLLING 设计动机相近）
- 引用了 Schmidt, Silva, Darvish, Coelho (2023) 的 "Time-dependent fleet size and mix multi-depot vehicle routing problem"（TD-FSM-MDVRP）——该问题族把**车队构成本身当作决策变量**，不是全程冻结的常量。

另有两篇同批检索但未提供额外证据的文献，如实列出：Dong et al. (2023, *Sustainable Energy Technologies and Assessments* 58, 103366)"Dynamic electric vehicle routing problem considering mid-route recharging and new demand arrival"——全文未讨论拒单或车队规模处理，新增需求如何被吸收未见明确说明；Voccia, Campbell & Thomas (2019, *Transportation Science*)"The Same-Day Delivery Problem for Online Purchases"——聚焦承诺时限定价而非拒单机制本身，未找到与本问题直接对应的段落。

### 1.5 逐问回答

| 问题 | 文献标准做法 | 本项目 E7 做法 |
|---|---|---|
| 现有车队无法服务新订单时怎么办 | 拒单+罚金（Pillac "service guarantee"；Zhang&Woensel 36% 论文允许拒单；Mardešić 称之为"vital component"）；或外包/延后（Zhang&Woensel 综述里 SDDP 分支）；或提前假设车队足够大以回避该情形（He et al. 2025；Ninikas & Minis 2014；Sarasola et al. 2016） | 无任何分支处理：候选找不到匹配车辆即抛异常，整单元判 LEGAL_INFEASIBLE，`final_total_cost=None` |
| 车队规模在动态过程中固定还是可增 | 固定时几乎全部"故意留足余量"（+2 辆车、"数量不少于请求数"），不是紧贴静态最优值；也有论文（FSM-MDVRP）直接把车队构成当决策变量 | 固定为触发时刻已空闲的车辆集合，且该集合来自"刚够跑赢静态基线"的 E3 封存最优解（无预留余量，见任务三） |
| 可行性怎么定义 | 三选一：①服务全部顾客且允许拒单（拒单不算失败，是被评分的合法结果）；②假设车队足量使"服务全部"恒可行；③目标函数按"实际服务量"打分，未服务不判整体失败 | 服务全部新增/变更需求 **且** 只能用继承下来的空闲实体车执行，任一条件不满足即整单元失败，没有第三种"部分服务"的合法出口 |
| 冻结规则 | 冻结已发车/已执行的路线前缀（"a vehicle that has left its previous location cannot be diverted" —— Zhang & Woensel p.6）；未见任何一篇要求同时把"车辆-车场-车型"绑死到不可再分配 | 除了路线前缀冻结外，**额外**把"物理车辆的车场归属和车型"锁定为全程不可变常量（pre_registration.json 的 `irreversibility.immutable` 明确列出） |

**结论**：本项目在"路线前缀冻结"这一条上与文献一致（这本身是动态 VRP 的标准做法，即"在途不可撤回"）。但在"零拒单/零外包/零延后"和"零车队缓冲"这两条上，比所有 7 篇已读文献都更严格——文献要么留一个"拒单"阀门，要么留一个"车队冗余"缓冲，从未见过两个阀门同时关死的设计。

---

## 任务三：事件强度 vs 车队余量的结构性失衡（只读量化）

### 3.1 十五条冻结事件流

来源：`baselines/china_e3_e7/e7_dynamic_v3_20260731/inputs/event_manifest.csv`

| 规模 | 流(stream_seed) | 批次数 | 新增(add) | 取消(cancel) | 需求变动(demand_change) | 事件合计 |
|---|---|---|---|---|---|---|
| 50c | 1–4 | 4 | 5 | 2 | 5 | 12 |
| 50c | 5 | 3 | 5 | 2 | 5 | 12 |
| 100c | 1–2 | 4 | 10 | 5 | 10 | 25 |
| 100c | 3–5 | 5 | 10 | 5 | 10 | 25 |
| 150c | 1–4 | 5 | 15 | 8 | 15 | 38 |
| 150c | 5 | 6 | 15 | 8 | 15 | 38 |

每规模 5 条流事件构成完全一致（只有批次数微差）。平均每批事件数：50c ≈ 3.2、100c ≈ 5.4、150c ≈ 7.3——随规模单调上升。

### 3.2 车队上限与初始空闲余量

来源：`data/ChinaInstances/china81_finite_fleet_authority_v1_20260723/fleet_caps.csv`（选用列与 `main_reserve_factor=1.25` 一致，即当前唯一权威口径）对照 E7 的名义（事件前）方案：50c/100c 用各自 seed 的 E3 封存 JOINT 方案（`e3_zone_joint_20260731/formal/plans/`），150c 用三个规模共用的 `mechanism_foundation_20260730/inputs/e6/.../mismatch00/initial_solution.json`。

| 算例 | 车场 | 车队上限(CV+EV) | 名义已用(CV+EV) | 空闲CV | 空闲EV |
|---|---|---|---|---|---|
| 50c | D_guangzhou | 4+1=5 | 2+1=3 | 2 | 0 |
| 50c | D_shenzhen | 5+2=7 | 3+2=5 | 2 | 0 |
| **50c 合计** | | **12** | **8** | **4** | **0** |
| 100c | D_guangzhou | 8+2=10 | 5+2=7 | 3 | 0 |
| 100c | D_shenzhen | 10+3=13 | 7+3=10 | 3 | 0 |
| **100c 合计** | | **23** | **17** | **6** | **0** |
| 150c | D_dongguan | 4+1=5 | 3+1=4 | 1 | 0 |
| 150c | D_foshan | 4+1=5 | 3+1=4 | 1 | 0 |
| 150c | D_guangzhou | 9+3=12 | 6+3=9 | 3 | 0 |
| 150c | D_shenzhen | 10+3=13 | 7+3=10 | 3 | 0 |
| **150c 合计** | | **35** | **27** | **8** | **0** |

（50c/100c 已核对多个种子——seed01/05/10 车辆构成完全一致，说明这是 E3 封存解的稳定结构，不是单个种子的偶然值。）

**关键事实：三个规模、每个车场，事件触发前（t=0）的 EV 空闲余量恒为 0。** 名义方案已经用满了 E3 封存最优解允许的全部 EV；能腾挪的只有 CV，且 CV 空闲总量只有 4 / 6 / 8 辆（占车队总量 33% / 26% / 23%，随规模扩大占比反而下降）。

### 3.3 新增趟次需求 vs 空闲资产：结构性不匹配的量化

以"新增(add)+需求变动(demand_change)"之和作为"可能需要一辆空闲车执行或重新安排的趟次"的上限（cancel 只会释放运力，不计入压力侧）：

| 规模 | 每流 add+demand_change | 空闲CV | 空闲EV | 压力/CV空闲 比值 |
|---|---|---|---|---|
| 50c | 10 | 4 | 0 | 2.5× |
| 100c | 20 | 6 | 0 | 3.3× |
| 150c | 30 | 8 | 0 | 3.75× |

比值随规模单调恶化（2.5× → 3.3× → 3.75×），车队上限虽然从 12 涨到 35（增长 2.9 倍），但事件压力从 10 涨到 30（增长 3 倍）还要快，且 E3 封存最优解本身已经把车队用到 66.7%–77.1%（8/12=66.7%、17/23=73.9%、27/35=77.1%），没有随规模扩大预留出更多缓冲。这解释了可行率不是"随机波动"而是"单调塌陷"（50c 6/40 → 100c/150c 0/40）：不是搜索运气变差，是空闲池与事件强度的比值本来就在恶化，且 EV 侧从一开始就是零余量，任何需要 EV 的新趟次都是即时死局，与搜索强不强、候选选得巧不巧无关（1.2 节里 100% 的拒绝原因锁定为同一条"找不到可继承资产"就是这个原因的直接证据）。

需要如实说明的边界：以上是"事件触发前(t=0)"的空闲快照，不是逐阶段的动态余量；实际运营中白天大部分时段车辆都在跑路线，同一时刻的真实空闲数只会更低（更紧张），本报告未运行新的求解来逐阶段重建每个触发时刻的真实空闲快照，因为这需要执行 solver 排班逻辑，超出"只读诊断"范围。t=0 快照已经足以证明结构性失衡方向成立，逐阶段精确值留待用户批准后再补测。

---

## 任务二：E7 修复选项（不替用户选择）

以下四个选项互不排斥，也可以组合；均未替用户拍板，仅给出改动范围、影响面、文献依据和可行率的粗估。

### 选项 A：显式拒单/延后 + 罚金（对齐 Pillac "service guarantee"、Zhang&Woensel 拒单分支、Mardešić "vital component"）
- **改什么**：给 `assign()`（`dynamic_multitrip_schedule.py` 第 413–478 行）和候选评价循环（`e7_formal_dynamic_value_20260714.py` 第 1370–1385 行）增加"标记为 unserved/deferred，计入预注册罚金"的第三条出路，替代直接抛异常。
- **改动文件**：`solver/src/setp_solver/search/dynamic_multitrip_schedule.py`、`baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py`、`baselines/china_e3_e7/e7_dynamic_v3_20260731/run_e7_dynamic.py`（分类与结算逻辑）。
- **触及三个保护文件**：可能触及 `solver/src/setp_solver/search/evaluation.py`——如果罚金要计入"完整候选评价"的目标函数，需要在受保护的评价路径里加一项，这需要用户额外批准修改保护哈希。
- **触及 paper_main.tex 已定稿模型公式**：是，目标函数需要新增拒单罚金项和对应符号，模型章节要改。
- **是否作废 E2–E6**：否，罚金机制只作用于 E7 自己的动态目标函数，不改变 E2（跨场协同）、E3（客户重指派）、E5（充电）、E6（公平）的已封存结果。
- **文献先例**：Pillac et al. (2013) p.2；Zhang & Woensel (2023) 全篇（p.5–6, p.28 的 36% 统计）；Mardešić et al. (2024) p.12。
- **可行率估计**：所有 120 个单元都能产出非 null 的目标值（因为"有限个客户被拒"本身就是合法结果，不再触发 LEGAL_INFEASIBLE），但"完整服务率"会 <100%；给不出精确的"可行率"数字，因为这改变了可行性的定义本身，不是同一把尺子。

### 选项 B：动态阶段车队缓冲/机动车辆（对齐 Zhang&Woensel 引用的 Bent & Van Hentenryck "+2 辆车"、He et al. 2025 "车队足量假设"）
- **改什么**：在事件流触发前给每个场景登记一批预先冻结的"机动车辆"（车场、车型、初始可用时刻需要另行冻结），只在动态阶段允许被 `inherited_asset_states` 引用；E3 封存的静态最优解本身不变。
- **改动文件**：新增一张"动态机动运力表"作为 E7 专属输入；`run_e7_dynamic.py` 里构造 `inherited_asset_states` 处读取该表。`dynamic_multitrip_schedule.py` 的 `assign()` 本身不需要改逻辑（它已经支持任意大小的 `asset_states` 输入）。
- **触及三个保护文件**：否，`dynamic_multitrip_schedule.py` 和 `run_e7_dynamic.py` 都不在保护清单内。
- **触及 paper_main.tex 已定稿模型公式**：需要在车队/成本参数一节新增"动态储备车辆"的描述，但不必改动目标函数结构本身。
- **是否作废 E2–E6**：否，`fleet_caps.csv` 的 `num_cv`/`num_ev`（E2/E3/E5/E6 用的静态车队上限）不变，只是 E7 额外多喂几辆"备用车"进入动态资产池。
- **文献先例**：Bent & Van Hentenryck (2004，见 Zhang & Woensel 2023 p.8 转引)；He et al. (2025) p.16、p.18。
- **可行率估计**：按任务三的量化，50c 缺口约 4–10 辆量级、100c 约 14–20 辆量级、150c 约 22–30 辆量级（这是粗略推算：把"压力/空闲比值"降到 1× 左右所需的额外车辆数），具体加多少辆能让可行率回升到什么水平，需要真正跑一次敏感性搜索才能给出实测数字，本报告不编造。

### 选项 C：放宽车型/车场硬匹配（部分对齐 FSM/mixed fleet 概念，文献支持较弱）
- **改什么**：把 `_dynamic_assignment_candidates()` 第 714–718 行的
  `state.vehicle_type != route.vehicle_type.lower() or state.home_depot_id != route.home_depot_id` 硬性剔除，改为允许 CV 顶替 EV 路线（放弃充电感知计费）或允许跨场空闲车辆临时借调。
- **触及三个保护文件**：不确定——`vehicle_type` 一致性假设是否被 `search/evaluation.py` 的其它路径（例如碳排放、充电计费）依赖，本轮只读未逐一核实，需要用户批准后专门核查再动手。
- **触及 paper_main.tex 已定稿模型公式**：是，EV/CV 路线绑定的建模假设需要放宽表述。
- **是否作废 E2–E6**：可能是——如果放开车场绑定，等于让 E7 的 NO_COOPERATION/FULL_ROLLING 对照失去原本"车场归属"的定义边界，需要用户先确认这是否会污染 E3/E6 已经在用的"车场责任"口径。
- **文献先例**：没有找到"临时换型服务单一新增订单"的直接文献先例；仅有 Wang et al. (2024) 引用的 Schmidt et al. (2023) Fleet Size and Mix MDVRP 把车队构成整体当决策变量，方向近似但粒度不同（是重新设计车队构成，不是运行时临时借调）。
- **可行率估计**：无法估计，缺乏可比文献数字支撑，且实施前需要先核查对保护文件的依赖面。

### 选项 D：保持代码逻辑不变，重新标定事件强度（不改模型、不改保护文件）
- **改什么**：不动 `dynamic_multitrip_schedule.py`/`run_e7_dynamic.py` 任何逻辑，只降低 15 条事件流的 add/demand_change 强度，使其与任务三算出的空闲余量相匹配（例如把每批新增趟次数压到不超过同期空闲资产数量级）。
- **改动文件**：需要重新生成事件流（当前 15 条已 `frozen: true`，不能就地改内容），即产生一批新的事件流文件和新的事件哈希。
- **触及三个保护文件**：否。
- **触及 paper_main.tex 已定稿模型公式**：否，只是场景参数，不改模型。
- **是否作废 E2–E6**：否。
- **是否作废已有 120 个 E7 单元结果**：是，因为事件流身份哈希变了，当前全部 120 个单元需要重新生成。
- **文献先例**：没有一个通用公式规定"事件强度必须小于车队余量"，但 Zhang & Woensel (2023) 综述的实验设计表里，各文献在把静态算例转成动态算例时都要"为车队规模、到达率等做假设"（p.8），隐含前提是让二者匹配，而不是独立设定后硬撞。
- **可行率估计**：如果新强度按"每阶段新增趟次数 ≤ 同期空闲资产数"标定，理论上可行率会显著回升，但没有重新跑事件流生成和正式矩阵之前，无法给出实测数字。

### 关于"是否只是强度过高"的明确回答

**两件事同时成立，不矛盾**：
1. 事件强度相对于车队空闲余量确实偏高，且随规模扩大而恶化（2.5× → 3.3× → 3.75×，见任务三）——从这个角度看，只调低强度（选项D）理论上能让可行率回升。
2. 但即便强度不变，本项目在"零拒单/零外包/零延后"和"零车队缓冲"这两条设计选择上，比全部 7 篇已读文献都更严格——文献里的车队余量从来不是"卡着静态最优用到 66.7%–77.1%、EV 余量恒为 0"这种紧法，而是刻意留出缓冲或者留一个拒单阀门。所以即使把事件强度降到很低，只要 EV 空闲余量长期为 0 这一结构性事实不变，任何需要 EV 执行的新增趟次仍然是即时死局——选项D 单独使用能缓解但不能根治，选项A/B 是从"零阀门"这个更根本的设计差异上补的。

---

## 任务四：E5 快充 50c 结果聚合

证据目录 `baselines/china_e3_e7/e5_fastcharge_20260731/formal/`，共 20 个单元（`L100_control` 线性对照 × 10 seed + `M17_FAST_SHAPE_SCALED_120KW_PWL` 快充非线性 × 10 seed），`task_status` 20/20 `PASS`。

### 4.1 Schema 核实

`formal/task_status/*.json` 的 `search_total_cost_cny` 字段与 `formal/search_traces/*.json` 的 `complete_candidate_evaluation_trace` 最后一条记录（`source="final_independent_certificate"`, `status="PASS"`）数值完全一致，确认 `search_total_cost_cny` 就是独立复算认证过的完整模型成本，不是搜索内部的近似目标值。`formal/plans/*.json` 的 `solution.charging_actions` 含 `start_energy_kwh`/`end_energy_kwh`，用于本报告自行计算 SOC 曝光比例（电池容量 77.28 kWh，取自 `run_e5_fastcharge_20260731.py` 注释确认的当前批准值）。

### 4.2 两臂逐种子对照

| seed | L100_control 完整成本(CNY) | M17快充 完整成本(CNY) | 成本变化 | 可行 | 实际评价数(两臂相同) |
|---|---|---|---|---|---|
| 1 | 2287.323422 | 2287.347515 | +0.001053% | 是/是 | 367/400 |
| 2 | 2287.323422 | 2287.347515 | +0.001053% | 是/是 | 326/400 |
| 3 | 2287.701999 | 2287.726092 | +0.001053% | 是/是 | 315/400 |
| 4 | 2287.327172 | 2287.347515 | +0.000889% | 是/是 | 373/400 |
| 5 | 2287.701999 | 2287.726092 | +0.001053% | 是/是 | 327/400 |
| 6 | 2290.273792 | 2290.298129 | +0.001063% | 是/是 | 359/400 |
| 7 | 2287.323422 | 2287.347515 | +0.001053% | 是/是 | 321/400 |
| 8 | 2287.323422 | 2287.347515 | +0.001053% | 是/是 | 356/400 |
| 9 | 2287.323422 | 2287.347515 | +0.001053% | 是/是 | 323/400 |
| 10 | 2287.323422 | 2287.347515 | +0.001053% | 是/是 | 335/400 |

- 10/10 seed 两臂均 `feasible=PASS`（`error_candidates=0`，`termination_reason=CANDIDATES_EXHAUSTED`，均在 400 评价预算内自然耗尽候选池，未触发预算上限）。
- 成本变化幅度：10 个 seed 全部落在 **+0.00089% 至 +0.00106%** 区间，均值 **+0.00104%**。

### 4.3 关键问题：120kW 快充下非线性充电机制是否产生可观测效应

**成本层面：基本没有可观测效应。** 10 个 seed 的成本变化幅度（约 0.001%）比 22 kW 慢充基线的 0.000% 略高一个数量级，但绝对幅度仍然是千分之一个百分点级别，在完整模型总成本（约 2287–2290 CNY）里对应约 0.02–0.024 CNY 的差额，属于数值噪声量级，不构成可报告的经济效应。

**充电动作层面：存在一个明确、可复现的物理效应，但只影响单一会话。** 每个 seed 的 4 个充电会话中，恒有 1 个会话把 SOC 充到 100%（其余 3 个会话终止 SOC 均 ≤ 0.37，不进入折减区）。对这唯一一个"充满"的会话：
- L100 线性对照：0%→100% 耗时 38.640 分钟。
- M17 快充非线性：0%→100% 耗时 54.193 分钟。
- **时长比值 54.193/38.640 = 1.403，即快充非线性机制让这一会话的占用时长增加 40.3%**，10 个种子完全一致（同一充电桩占位模式，非随机波动）。

这个 40% 的时长差没有传导成可观测的成本差，原因是该占位延长没有引发排队冲突或额外电价档位切换（具体传导路径未在本报告核实，只陈述观测到的结果）。

**如实定性**：120 kW 快充下，非线性充电机制在**占用时长**上有一个稳定、可复现、方向明确的效应（+40.3%，仅发生在充至 100% SOC 的会话上）；但在**完整模型总成本**上没有可观测效应（约 0.001%，与噪声同量级）。不能笼统说"完全没有效应"，也不能说"有显著的经济效应"——这是两个不同层面的问题，答案不一样。

### 4.4 功率折减区曝光比例

预注册折点 SOC=0.85 与 0.95（`e5_fastcharge_config_20260731.py` 的 `FAST_CURVE` 分段点）。两臂 10 个 seed 共 40 个充电会话：
- 终止 SOC > 0.85 的会话：10/40 = **25.00%**（且这 10 个会话同时终止 SOC > 0.95，即全部是"充到 100%"的会话——0.85–0.95 和 0.95–1.0 两段折减区在本数据里总是一起被覆盖，没有"只进 0.85 折减区、不进 0.95 折减区"的中间情况）。
- 其余 30/40 = 75.00% 的会话终止 SOC ≤ 0.37，完全不触及折减区，充电全程等效恒功率。

### 4.5 与 22 kW 慢充基线对照

| 口径 | 22kW（`e5_nonlinear_final_20260730`，已封存） | 120kW（本次聚合） |
|---|---|---|
| 可行率 | 100%（20/20） | 100%（20/20） |
| 假可行 | 0/20 | 本报告未复核（详见下方口径说明） |
| 完整模型成本变化 | 0.000% | +0.001%（10 seed 均值） |
| 折减区曝光 | 未在本任务复核 | 25.00%（10/40 会话进入 0.85–1.0 区间） |

口径说明：22 kW 的"假可行 0/20"是 `e5_nonlinear_final_20260730` 独立封存的结论，本任务未重新核实；120 kW 是否存在"线性方案在真实非线性物理下假可行"，需要运行 `check_e5_fastcharge_20260731.py` 的独立复算逻辑（对比 `planning_check`/`nonlinear_check` 两条路径），该脚本会调用 solver 的检查/成本代码路径，本轮判定为超出"只读诊断+聚合已有 JSON 字段"的范围，未执行，如实标注为未核实而非编造为"0/20"。
