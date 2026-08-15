CONSTRAINT_VERIFY_DONE

# 三张图表约束事实补证（2026-08-14）

本报告只读代码、数据、已有审计产物和 Figshare 配套原件；没有运行求解器、没有加载算例搜索、没有修改代码或已有文档，也没有修改三个受保护文件。

## 一、缺口一：并发充电限流逐点排查

先给总判断：当前 DEPOTSWAP 使用的是 `DEPOT_CHARGER_CAPACITY_UNBOUNDED`。因此，`fleet_caps.csv` 中的 `configured_depot_gun_count_if_finite=2` 不会成为当前模型的有效并发上限。但代码并不是字面上“完全没有任何数量检查”：当 `Node.station_chargers` 为 `None` 时，检查器、动态验证器和调度协调器都回退到车场客户数。本算例每场最多 4 辆 EV，而回退值是 50，所以这个回退上限在当前车队范围内不会卡住并发充电。

### 1.1 逐点列表

| 代码点 | 这段代码做什么 | 当前配置下是否生效 | 证据与判定 |
|---|---|---|---|
| `solver/src/setp_solver/model_config.py:14-18,26-31`；`solver/src/setp_solver/china81.py:634-669,870-880` | 定义两种车场容量模式；构造车场节点时，只有 `finite_instance` 才把 `configured_depot_gun_count_if_finite` 写入 `Node.station_chargers`。同时把原始桩数保存进 `charger_scenario_by_node`，并把 `active_concurrency_limit` 写成模式值。 | `UNBOUNDED` 生效；2 不生效为有效桩数上限。 | `ModelConfig` 默认模式就是 `unbounded`；DEPOTSWAP 运行入口显式传入同一模式。当前两个车场的场景记录均为 `charger_count=2`、`active_concurrency_limit=UNBOUNDED`、`capacity_mode=UNBOUNDED`。加载后的车场 `station_chargers=None`。 |
| `data/ChinaInstances/china81_instance_depot_swap_jjj_v1_20260813/fleet_caps.csv:1-3` | 提供车队和桩参数。 | `configured_depot_gun_count_if_finite=2` 只保留为来源参数；不作为当前模式的活动容量。 | 两个车场都为 4 CV、4 EV、`configured_depot_gun_count_if_finite=2`、`depot_charger_capacity_default=UNBOUNDED`。 |
| `solver/src/setp_solver/algorithms/problem_hgs/charging.py:857-876`；`1190-1280` | `occupancy_minutes` 先计算已有充电会话的释放时刻；`_static_timing_variants` 再把其他会话的释放时刻加入候选开始时间。注释所说的 shared-charger interaction 是时序候选交互。 | 不产生数量上限，也不实现排队队列。 | 代码只生成“原会话开始时刻 + 外部会话释放时刻”等候选；没有按同一车场同时车辆数计数、也没有读取 `configured_depot_gun_count_if_finite`。车场动作还要在出发前的时间窗内放得下。 |
| `solver/src/setp_solver/algorithms/problem_hgs/charging.py:1593-1617,1662-1668,1867-1877` | 用充电占用时长计算公共站服务时间、车场充电结束时间和下一事件开始时间；检查的是单条路线/单辆车自己的时序可行性。 | 生效为单车时间约束；不是跨车辆并发限制。 | `occupancy_minutes` 被换算成秒并嵌入 route timing / depot window；没有同站跨车计数。 |
| `solver/src/setp_solver/algorithms/problem_hgs/proposals.py:180-221,268-287` | 静态 EV 路径调用 `build_ev_duty_charging_candidates`，并收集其他 duty 的会话释放时刻；动态路径调用动态候选生成器。 | 生效为候选生成分支；不单独限并发。 | 这里把充电会话传给候选和评价器，没有独立的 `station_chargers` 或并发计数检查。 |
| `solver/src/setp_solver/algorithms/problem_hgs/repair.py:56-60,86-104` | DCREX 修复先调用 `evaluator.evaluate`，对插入动作调用 `evaluate_move`。 | 不单独生效。 | 文件没有容量计算；容量判断由下游完整评价/检查链承担。 |
| `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:443-499,537-569,700-801` | `dynamic_state is None` 时走静态 `prepare_multitrip_solution`；否则走动态候选；随后 `_evaluate_prepared` 对候选调用 `check_solution`。增量路径最后也回到同一个 `_evaluate_prepared`。 | 当前保存的 DEPOTSWAP 跑法走静态分支；`check_solution` 会生效。 | 当前技术跑的 `metadata.json` 记录 `dynamic_insertion_operator.enabled=false`。静态分支条件和 `check_solution` 调用均在上述行段。 |
| `solver/src/setp_solver/search/evaluation.py:93-120`（受保护，只读） | 计算 `cost.py` 的成本，再调用 `check_solution`，用硬约束违例计罚。 | 生效为总评价外壳；不另设充电容量。 | 文件只把容量责任交给 `check_solution`，没有第二套充电数量规则。 |
| `solver/src/setp_solver/check.py:242-407`（受保护，只读） | 检查充电动作结构、数值合法性，并按物理车辆检查自己的充电会话是否重叠。 | 生效；但只限制同一辆物理车自己的重叠，不限制不同车同时充电。 | `sessions[physical_vehicle_id]` 按车辆分组；违例文本也是“one physical vehicle has overlapping charging sessions”。 |
| `solver/src/setp_solver/check.py:410-492`（受保护，只读） | 检查车场充电是否和同一物理车辆的行程区间重叠；公共站在当前行程内的充电已经包含在 route timing 中。 | 生效为单车“充电—出车”时序约束；不是跨车并发限制。 | 代码按 `physical_vehicle_id` 比较充电区间与 trip 区间，没有跨车场占用计数。 |
| `solver/src/setp_solver/check.py:583-644,1214-1222`（受保护，只读） | 把充电动作按 48 个半小时槽归入物理站，在同一站、日偏移和槽内按车辆 ID 去重后比较 `C_s`。 | 生效，但当前车场 `station_chargers=None` 时回退为 `max(1, customer_count)`，不是 2。 | `_station_chargers` 对车场的回退值是客户数；本 DEPOTSWAP 是 50 个客户，因此当前检查器的车场回退 `C_s=50`。它是防守性上限，当前每场最多 4 辆 EV，不能被当前车队触发。 |
| `solver/src/setp_solver/algorithms/problem_hgs/schedule_oracle.py:134-203,1062-1064,1193-1211,1244-1318` | 编译站点容量；组合不同 duty 的 occupancy signature；超出容量就 prune；明确写明镜像 `check.py:_check_station_capacity`。 | 若调度协调器被构造，会生效为同一套容量检查；车场同样回退为客户数。 | `_station_capacity` 对 `station_chargers=None` 的车场返回 `max(1, customer_count)`，没有把 2 恢复成活动容量。`ScheduleOracleContext` 还把 `resource_limits` 记录为 `None`，没有另一个隐藏队列资源。 |
| `solver/src/setp_solver/search/dynamic_multitrip_schedule.py:1214,1646-1703` | 动态证书验证结束时调用 `_validate_depot_charger_capacity`；函数按 48 槽统计物理车辆 ID，并比较车场/设施容量。 | 这条只在动态证书验证路径调用；当前静态 DEPOTSWAP 跑法不会触发。若将来启用动态路径，车场仍回退为客户数。 | `evaluation.py:450-465` 说明当前 `dynamic_state=None` 走静态准备；当前 metadata 也记录动态插入关闭。动态函数本身对 `station_chargers=None` 的车场使用 `max(1, customer_count)`。 |
| `solver/src/setp_solver/algorithms/problem_hgs/independent.py:153-166` | 按子问题保留 `bundle.charger_scenario_by_node` 中已有的车场场景，并把 `formal_search_allowed` 设为 false。 | 生效为场景信息传递；不新增或重算并发限制。 | 代码只是筛选并复制已有映射，没有读取 `charger_count` 做排队/容量判断。 |

### 1.2 `charging.py` 中全部 `occupancy_minutes` 用法的归类

读到的全部用法是：`:871` 计算其他会话释放时刻；`:971` 把动作占用时长复制到 duty 会话；`:1264` 计算车场动作持续时间；`:1595` 作为公共站服务时间；`:1616` 检查车场动作能否塞进出发前窗口；`:1665` 推进下一事件时钟；`:1867` 计算车场充电窗口；`:1989`、`:2012`、`:2045`、`:2062` 用于会话/动作转换和身份比较。

这些用法都属于“一个动作占多久、单车何时释放、下一段行程何时能开始”或记录一致性；没有一处把 `occupancy_minutes` 转成同一车场的跨车辆排队队列。真正的跨车辆槽容量判断集中在 `check.py`、动态验证器和 schedule oracle，而当前车场的活动值均是客户数回退，不是 2。

### 1.3 总判定

`FACT`：**当前 DEPOTSWAP 配置下，同一车场同一时刻的并发充电车辆数不受“2 台充电桩”的有效限制；在当前每场最多 4 辆 EV 的车队范围内，没有会实际卡住并发充电的有效数量上限。**

同时保留实现细节：代码字面上仍有 `C_s=50` 的防守性槽容量检查（客户数回退）。所以论文或图注不应写成“所有代码路径完全没有任何数量检查”；准确说法是“模型关闭了 2 桩并发约束，当前车队范围内不形成桩位竞争或排队”。

### 1.4 `cost_occ` 的含义与当前解为何为 0.0

`cost_occ` 是**公共充电站按充电占用时长计收的占用成本**，不是车场电费，也不是等待时间成本。`solver/src/setp_solver/cost.py:197-205` 把它作为成本分项加入总成本；`cost.py:1227-1238` 的公式是：对每个充电动作，若站点是车场就跳过，否则累加 `occupancy_minutes × occupancy_fee`。代码注释也明确写着车场预充电使用车场电价、不收公共占用费。

对指定的 `solver/reports/depotswap_trip_compression_recheck_20260814/run_seed11_iter400/best_solution.json` 做了只读读取：`evaluation.breakdown.cost_occ=0.0`、`n_veh_ev=0`、`prepared_solution.charging_actions` 长度为 0、`n_veh_cv=7`。因此当前值为 0.0 的直接原因是**没有任何充电动作**；并且即使有车场充电动作，按这段成本代码也不会产生 `cost_occ`，只有公共站充电动作才会按占用分钟计费。

## 二、缺口二：数据集出处、分辨率、抽样验证结果

### 2.1 原始落地、出处和校验

仓库内已找到原始落地目录 `data/Carbon/中国情景/raw_20260717/`，包括 S1 工作簿、Figshare 元数据 JSON 和配套 Annotation PDF。审计入口是 `baselines/e4_e5/audit_china_tvci_source_gate_20260717.py:30-44,157-182`；本地门禁元数据是 `baselines/e4_e5/china_tvci_source_gate_20260717_v2/metadata.json:6-27,40-89`。

| 项目 | 已核实内容 |
|---|---|
| 数据集标题 | `High temporal and spatial resolution projected electricity carbon emission factors of China from 2025-2060` |
| 作者 | Yaowang Li；Shixu Zhang；Ning Zhang；Yuliang Liu；Ershun Du；Chongqing Kang；Yuting Qin；Weiran Li；Yi Xie；Hongyi Wei。作者列表来自仓库内 Figshare JSON。 |
| 年份 | Figshare citation 字段标为 **2025**；当前 v3 的仓库元数据记录 published/modified 为 **2026-04-02**。配套 `Scientific Data` 论文页面标为 Published 21 April 2026。这里的 2025 是数据集 citation 年，不把它误写成当前 v3 发布年。 |
| DOI / URL | DOI `10.6084/m9.figshare.28953545.v3`；[Figshare API record](https://api.figshare.com/v2/articles/28953545)；[DOI landing link](https://doi.org/10.6084/m9.figshare.28953545.v3)。 |
| 许可证 | **CC BY 4.0**，见 [Creative Commons 许可文本](https://creativecommons.org/licenses/by/4.0/)。 |
| S1 原始文件 | `CEF data for Scenario S1.xlsx`，Figshare file id `63393795`，下载 URL `https://ndownloader.figshare.com/files/63393795`，16,131,311 bytes。 |
| S1 文件 SHA-256 | `8e23df4a39707077a2c772e9ab0a275b388fe4ded04d0db4fe0937616499486d`。 |
| 其他 provenance 文件 SHA-256 | `figshare_article_28953545.json`：`c4729e9cd5d2de21652b12185729c560d04d454cb6d43ac7888ffde181c936d5`；`figshare_dataset_annotation.pdf`：`75d3d0a265cc3e1df044f00c8a10f4328f85c9de776582df4f22b2a75916691d`。 |

审计脚本还用 Figshare 元数据核对了文章 id `28953545`、version 3、DOI、CC BY 4.0、S1 文件名和文件大小；本地记录的 S1 MD5 是 `3cdf56af1e9c90167fc4c85ccc5afd5b`。本报告使用 SHA-256 作为文件身份报告值。

### 2.2 原始时间分辨率不是被丢掉的更细粒度

`FACT`：原始 Annotation PDF 第 1 页 §1 写明 temporal resolution 是 one hour；第 3 页 §2.3 写明 common year 是 8,760 小时、leap year 是 8,784 小时；第 3 页 §3 的表结构是 `Time` 加 `Mainland China`、北京等 31 个省级列，共 32 条序列。

对仓库内原始 `CEF_data_Scenario_S1.xlsx` 做了只读工作簿读取，得到：

| 原始 sheet | 数据行数（不含表头） | 列数 | 结论 |
|---|---:|---:|---|
| 2025 | 8760 | 33 | `Time` + 32 条序列 |
| 2030 | 8760 | 33 | 同上 |
| 2035 | 8760 | 33 | 同上 |
| 2040 | 8784 | 33 | 闰年 |
| 2045 | 8760 | 33 | 同上 |
| 2050 | 8760 | 33 | 同上 |
| 2055 | 8760 | 33 | 含缺失值，但行数仍是 common year |
| 2060 | 8784 | 33 | 含缺失值，且为闰年 |

这与 `audit_china_tvci_source_gate_20260717.py:189-316` 的读表逻辑和 `:319-349` 的转换逻辑一致。转换代码对每个 hourly row 生成两个 `minute=0/30` 的槽，并检查 2025 年输出为 17,520 行；它是复制，不是插值。因而当前 48 槽文件的“碳值成对相同”来自明确的 hourly-to-half-hour conversion，不是原始文件里存在 30 分钟碳数据后又丢了一半。

### 2.3 两个城市、两个日期的抽样

从 `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv` 只读抽取成都、广州各两个日期（均不含北京 2025-02-12），每组 48 槽；对碳列检查 24 个相邻 `(1,2),(3,4),...,(47,48)` 槽对，对电价列同时检查相邻对和整日变化。

| 城市 | 日期 | 碳相邻对恒等 | 电价相邻对恒等 | 电价全天不同值 | 电价整日相邻变化 |
|---|---|---:|---:|---:|---:|
| Chengdu | 2025-02-01 | 24/24 | 24/24 | 3 | 6/47 |
| Chengdu | 2025-02-12 | 24/24 | 24/24 | 3 | 6/47 |
| Guangzhou | 2025-02-01 | 24/24 | 24/24 | 3 | 5/47 |
| Guangzhou | 2025-02-12 | 24/24 | 24/24 | 3 | 5/47 |

电价的“相邻对恒等 24/24”本身不矛盾：一个电价段可以覆盖多个半小时槽；关键是整日有 3 个不同电价值，并且分别出现 6/47 或 5/47 次相邻槽变化。抽样事实支持：**电价列保留了 30 分钟槽位上的日内变化，而碳列在每个小时内复制到两个半小时槽。** 这是四组抽样，不把它扩大成对所有城市日期逐行重算的全量统计；全量转换规则由上面的审计脚本直接支持。

## 三、缺口三：原件对“模拟/投影”、平均/边际、发电侧/消费侧的原文措辞

### 3.1 原始数据集与配套论文的原文

以下是直接从仓库随 Figshare 下载保存的 Annotation PDF 和配套 `Scientific Data` 论文核到的短引文；引文保留英文原文，页码或章节给在括号内。

1. 数据集 Annotation PDF，第 1 页 §1：`This dataset provides electricity carbon emission factors for the mainland China power system under planning scenarios for the period 2025–2060, with a temporal resolution of one hour and a spatial resolution at the national or provincial level.`

2. 同一 Annotation PDF，第 4 页 §3（Temporal correspondence）：`The hourly data represent the average emission intensity for each hour, calculated through power system operation simulation, and are not instantaneous values.`

3. 配套论文 [Scientific Data, Abstract](https://www.nature.com/articles/s41597-026-07272-6)：`This study presents a comprehensive dataset of projected hourly electricity carbon emission factors for China from 2025 to 2060`；同一摘要继续说明数据由结合电力系统规划和运行模型的 simulation method 生成。

4. 配套论文 §Background & Summary：论文把这些因子定义为 electricity consumption 的 carbon intensity；§Methods / Carbon emission flow model 又说明省级因子按总碳排放与总发电量计算，碳排放包括输入电力的间接排放和本地发电的直接排放。论文 §Data Records 说明各 sheet 是每个年份的 hourly projections，数据文件和 Annotation PDF 均通过 Figshare 发布。

### 3.2 判定：平均还是边际，发电侧还是消费侧

`FACT`：原件明确写的是**每小时平均排放强度**，不是瞬时值；并把 `Cef_data-a-b` 定义为**电力消费的间接碳排放因子**，单位 `tCO₂/MWh`，数值上等于 `kgCO₂/kWh`。

`INFERENCE`：因此这套数据应归类为**消费侧使用的平均电力碳排放因子**，其计算基础是发电计划、潮流和碳排放流模型；它不是边际排放因子，也不是只针对发电机组烟囱端的直接排放因子。这里“不是边际”是由原件明确的 average 定义和消费侧间接因子定义推出的分类；原件没有找到一句单独写着 `not marginal` 的英文原句。仓库审计元数据 `metadata.json:38` 另外明确把 source nature 记录为 not marginal。

### 3.3 论文正文可用的候选表述

下面三句都按原件的“规划情景—逐小时模拟—消费侧平均因子”口径写，不把 2025 说成历史实测：

1. **“本文采用 Figshare 发布的中国大陆电力碳排放因子情景数据；该数据基于电力系统规划与运行模拟，提供 2025—2060 年、31 个省级区域的逐小时消费侧平均排放因子。”**

2. **“在 S1 基准规划情景下，我们使用北京 2025 年的逐小时投影电力消费碳排放因子，将其作为车队充电用电的时变排放参数。”**

3. **“该因子由逐小时发电计划、跨省潮流及碳排放流计算得到，表示相应时段电力消费的间接平均排放强度，而非边际排放因子或发电机组的直接排放因子。”**

### 3.4 2055/2060 空值与“2025 年北京电网”措辞

`FACT`：原始 S1 工作簿确实包含 2025、2030、…、2060 八个年份 sheet；仓库审计 `raw_runs.csv` / `metadata.json:91-104` 记录 2055 有 6 个空值、2060 有 51 个空值。审计脚本 `audit_china_tvci_source_gate_20260717.py:285-299` 将它们记录为未授权的未来投影年份，而不是把它们当作 2025 的数据错误。

`FACT`：原件把这套数据定义为 2025—2060 的 planning scenarios / projected data；配套论文 §Methods 说明 2020 年电力系统发电与电网结构是 2025—2060 规划的基础，§Technical Validation 说明用于和官方数据比较的是 2021—2023 的真实世界数据。原件没有把 2025 sheet 定义成“2025 年北京实测校准层”。

`INFERENCE`：2055 和 2060 的空值与未来年份规划情景的设计是一致的，但空值本身只证明这些源文件单元格缺失，不证明缺失原因。2025 这一层应写成**情景起点/投影年份**，不是“基准年实测校准”。

`UNKNOWN`：当前取证没有找到足以支持“2025 年北京电网实际碳强度”或“2025 北京实测序列”的原件措辞。因此正文建议写“**S1 情景下的 2025 年北京逐小时投影消费侧平均电力碳排放因子**”，不要写“2025 年北京电网实测碳强度”。

## 四、对终端 Claude 三条结论的判定

| 终端 Claude 的结论 | 判定 | 依据 |
|---|---|---|
| “同场同时充电不存在 2 个充电桩的竞争/数量约束。” | **需修正措辞，主旨成立。** | `china81.py` 和当前运行入口都确认 `UNBOUNDED`，所以 2 不形成有效模型约束；但 `check.py`、动态验证器和 schedule oracle 对 `station_chargers=None` 有 `C_s=customer_count=50` 的防守性回退。因此不能写成代码字面上完全没有任何数量检查；准确说是当前车队范围内不形成 2 桩竞争或有效排队。 |
| “Figshare S1 是 8760 小时数据，仓库把碳值无插值复制成 17520 个半小时槽；碳的 48 槽是假精度，电价是真 30 分钟变化。” | **成立。** | 原始 S1 工作簿 2025 sheet 直接读到 8760 行、33 列；Annotation §2.3/§3 写明 hourly/8760；审计转换代码逐小时复制成两个半小时槽。成都、广州各两天的抽样均得到碳相邻对 24/24 恒等，而电价全天 3 个不同值并有 5/47 或 6/47 次相邻变化。 |
| “该碳强度数据是模拟/投影，不是官方、历史实测、实时或边际排放。” | **主旨成立；‘2025 北京电网’需改成情景投影措辞。** | Annotation 原件明确写 planning scenarios、operation simulation、hourly average；配套论文摘要明确 projected、simulation，§Background/Methods 明确消费侧碳强度和碳排放流计算。原件没有找到单独的 `not marginal` 句子，但 average/consumption-side 定义不支持把它称为 marginal；仓库门禁也明确登记 not marginal。 |

## 五、未能取证的清单

1. `UNKNOWN`：没有找到原件直接写出 `not marginal` 的一句英文；“非边际”是由原件的 average 定义、消费侧间接因子定义和计算方法归类得到，仓库门禁另有明确标签。
2. `UNKNOWN`：没有找到原件把 2025 北京序列称为“2025 年实测北京电网”或“2025 基准年实测校准”。现有证据只支持 S1 情景下的 2025 年投影。
3. `UNKNOWN`：指定的当前可行解没有 EV 和充电动作，因此不能从该解观察并发充电或排队行为；本报告只核对了代码合同和容量回退。
4. 本任务没有发现“原始 Figshare 数据集在仓库中缺失”的情况；因此没有把仓库检索转成外部猜测。原始工作簿、Figshare JSON、Annotation PDF、下载 URL 和哈希记录均已找到。

## 六、受保护文件哈希前后对照

以下哈希在本任务开始前和报告写入后各读取一次；三份文件均只读，前后相同。

| 受保护文件 | 任务开始前 SHA-256 | 报告写入后 SHA-256 | 结果 |
|---|---|---|---|
| `solver/src/setp_solver/cost.py` | `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989` | `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989` | 一致 |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | 一致 |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | 一致 |

