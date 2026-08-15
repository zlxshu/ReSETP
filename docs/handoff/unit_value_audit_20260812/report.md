UNITAUDIT_DONE

# 单位、取值与统计口径只读审计报告

审计日期：2026-08-12  
审计目录：`/Volumes/移动硬盘（512G）/ReSETP`  
任务性质：只读源码、数据、已保存产物与正文核账；本任务没有运行求解器、实验、测试或项目计算脚本，仅做只读检索和对保存数字的四则复算，也没有修改代码、数据或参数。工作树在任务开始前已经不是干净状态，本报告只新增自身这一份交付文件。

本报告把结论分成三种：

- `FACT`：当前文件、已保存产物或可直接手算支持；
- `INFERENCE`：由已确认事实推得，保留适用边界；
- `UNKNOWN`：现有证据不足，不能当成错误或正确结论。

问题按一个“主类”计数，兼类只作交叉索引，避免同一问题重复计数。这里的“进入评价器”还细分为：进入精确总成本、进入利润/公平约束账、仅作为评价器输入。搜索代理、报告和元数据不冒充精确评价器。

## 一、结论摘要

### 1.1 总结论

`FACT`：本轮确认 **18 条现存问题或明确的代理口径偏差**。按主类计数：A 2 条、B 3 条、C 3 条、D 3 条、E 3 条、F 2 条、G 2 条。

`FACT`：未发现当前 `cost.py` 精确总成本账已经把 kW 当 kWh、把分钟当小时、把 kg 当 t，或把 170 元固定成本重复按趟计取。**当前精确总成本数值错误为 0 条。**

`FACT`：有 4 条进入了完整评价链：3 条进入利润/公平约束账（问题 1、2、4），1 条属于送进评价器的车队上限选择器（问题 3）。其中问题 1、2 已经改变过保存的评价派生值；问题 3 当前两套列值相同，数值差异被掩盖；问题 4 当前费率为 0，数值影响为 0。

`FACT`：12 条已经进入某类保存产物或保存 incumbent 的生成路径：其中 2 条改变了保存的评价派生数值（问题 1、2），2 条进入了保存 incumbent 的搜索路径但无法静态量化最终解差异（问题 5、7），其余 8 条进入数据契约、服务量字段、技术判定、报告、元数据或交接文字（问题 8、9、10、11、13、16、17、18）。这 12 条不等于“12 条精确成本都算错”。

`FACT`：当前还没有正式 China81 主实验结果，因此本轮确认的 China 私有侧错误进入**当前可写论文的正式结果为 0 组**。公开 28 题候选包的问题 9 已进入 59 份单次保存包及顶层汇总，但只错在服务需求字段没有披露 `×1000`，求解、容量约束、成本和原始精度审计没有因此算错。

### 1.2 A—G 数量与落点

| 主类 | 确认条数 | 进入完整评价链 | 已进入保存产物或保存解生成路径 | 结论 |
|---|---:|---:|---:|---|
| A 量纲 | 2 | 0 | 1 | 1 条是需求 kg 标签缺失；1 条是旧动态入口“经纬度角度÷m/s”，当前 China 链未调用 |
| B 计价/计量基准 | 3 | 3 | 2 | 两条已经污染利润/公平派生值；一条当前费率为 0，尚未产生数值污染 |
| C 比例与小数 | 3 | 0 | 3 | `×1000` 服务量未标尺度、SISR 正负文字、代理偏差方向文字 |
| D 默认值与实际取数 | 3 | 1 | 2 | 车队选择器名值不一致；1735/1700 kg 契约冲突；80/77.28 kWh 报告冲突 |
| E 代理值与精确值 | 3 | 0 | 2 | 漏 EV 日溢价、入口间电价代理不一致、半载推进代理；完整终评仍走精确规则 |
| F 聚合口径 | 2 | 0 | 1 | SISR 跨题绝对成本求和已进技术判定；MAIN-2 是正式开跑前的报告风险 |
| G 时间基准 | 2 | 0 | 1 | 300 秒被写成 20 分钟；同名收敛列存在两种起钟点 |
| **合计** | **18** | **4** | **12** | 精确总成本数值错误 0；保存的评价派生值受影响 2 |

### 1.3 受保护文件

任务开始与交付前 SHA-256 如下；三者逐位一致：

| 文件 | 任务开始 | 交付前 |
|---|---|---|
| `solver/src/setp_solver/cost.py` | `ad5b360dd255c7c4c975074a6eb3ad5e31354c2eaf7399af288670396140ccd1` | `ad5b360dd255c7c4c975074a6eb3ad5e31354c2eaf7399af288670396140ccd1` |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` |

## 二、按危险度排序的问题清单

### 1. EV 的 50 元/实体车·日溢价进了总成本，却漏出车场利润与公平约束账

- **路径与现写法（FACT）**：`data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv:1-3` 明确 CV 为 170 元/日、EV 为 170+50=220 元/日。`solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:833-858` 按启用 EV 实体车数把 50 元溢价加进 `cost_fix` 和 `total_cost`；但 `solver/src/setp_solver/profit.py:26-46,91-106,181-225` 的利润结构只给每辆物理车扣共同的 `vehicle_fixed_cost`，没有 EV 溢价字段或汇总项。`solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:480-500,558-575` 又直接把这套利润送进公平检查并保存 margin。
- **错在哪**：主类 B，兼 E。同一笔“实体 EV 车·日”成本在系统总账和车场利润账使用了不同口径。
- **正确写法应是什么**：EV 溢价应与基础固定成本一样，对实际启用的每辆 EV 物理车只扣一次，并归到其 `home_depot`；多趟不得重复扣。
- **是否进入评价器/保存结果（FACT）**：已进入完整评价的 depot profit、participation margin 和未来 fairness 判定；精确 `total_cost` 本身是正确的。当前 `solver/reports/combat_v2_20260812/combat_v2_5cycles_final/best_solution.json:554-587,629-758,1076-1080` 保存 5 辆 EV、250 元溢价、佛山 2 辆、广州 3 辆，但保存 margin 没扣这 250 元。保存值佛山 3739.8133685、广州 11946.6545831；正确候选 margin 应分别约为 **3639.8133685**、**11796.6545831**。该包 `fairness_enabled=false`，所以这次没有改变可行判定和总成本。静态检索有 56 份 `best_solution.json` 保存 `cost_fix_ev_premium`，未发现其中同时 `fairness=true` 的包。
- **若改动，影响哪些产物**：所有使用 rebuild EV 溢价并保存 depot profit/margin 的 Problem-HGS 技术包；未来启用 fairness 时会影响 Pi0、参与约束、候选可行性和排序；已经保存的精确总成本分解不需要因本项重算。

### 2. 利润/公平账用“算例城市柴油均价”，总成本按“路线起点城市价”

- **路径与现写法（FACT）**：`solver/src/setp_solver/profit.py:93-122` 对每条 CV 路线用 `prices.diesel_price`；`solver/src/setp_solver/china81.py:1083-1089` 把该兼容字段设为算例所含城市的算术均价。精确总成本却在 `solver/src/setp_solver/cost.py:180-185,244-289` 按 route 的 `home_depot` 城市读取 `diesel_price_by_city`，缺城市或缺价即报错。该利润函数进入 Problem-HGS、通用搜索和 Duty-HGS 的公平链，分别见 `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:480-500`、`solver/src/setp_solver/search/evaluation.py:161-190`、`solver/src/setp_solver/algorithms/duty_hgs/evaluation.py:402-422`。
- **错在哪**：主类 B，兼 E。计价对象从路线起点城市滑成了算例城市均价。
- **正确写法应是什么**：利润账与总账都应按该 route 的 home-depot city 结算柴油价。
- **是否进入评价器/保存结果（FACT）**：已进入利润和公平评价。当前 PRD 的佛山、广州都是 7.44 元/L（`data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/city_runtime_parameter_register.csv:6-7`）；当前 METRO 代表实例的两个车场也都在成都（`data/ChinaInstances/china81_metro_suite_v1_20260812/instances/cn-cy-50c-01-V3-TWO-SHIFT-METRO/nodes.csv:1-3`），所以这些同价包本项数值影响为 0。历史多城市技术包已经受影响：`solver/reports/problem_hgs_private_cy50_system100_180s_fairness_20260809/best_solution.json:240-272,504-515` 保存总油耗 58.2200061 L、精确燃油成本 436.3400809 元、fairness=true；成都 7.48、重庆 7.50 元/L（`data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/city_runtime_parameter_register.csv:3-4`），利润账却用 7.49。由保存的总油耗和精确燃油成本可解得成都约 15.4982520 L、重庆约 42.7217541 L，因此候选利润保存值相对正确值：成都低 0.1549825 元，重庆高 0.4272175 元，合计净高 0.2722350 元。
- **不确定边界（UNKNOWN）**：该包的 Pi0 也由同一错误函数生成（`solver/reports/problem_hgs_private_cy50_system100_180s_fairness_20260809/metadata.json:151-158`），没有 Pi0 分场油耗，不能据此断言最终 margin 偏差或公平判定一定翻转。
- **若改动，影响哪些产物**：多城市包的 depot profit、Pi0、participation margin 和 fairness 判定；不影响已经保存的精确 `cost_fuel` 与 `total_cost`。

### 3. PRDFIX/METRO 运行适配器会把“车队参数类别标签”与“实际读取列”分开

- **路径与现写法（FACT）**：权威选择器在 `solver/src/setp_solver/china81.py:47-95` 明确：`fixed25` 读 `num_cv/num_ev/total_fleet_cap`，`endogenous` 读 `base_all_cv_routes_Rd/base_all_ev_routes_Re`。技术 runner 暴露并传入选择项（`solver/scripts/run_problem_hgs_private_technical.py:126-129,1882-1886,2117-2125`），但 PRDFIX 适配器在 `solver/scripts/run_problem_hgs_private_technical.py:786-820` 始终用 `base_all_*` 构造上限，随后在 `solver/scripts/run_problem_hgs_private_technical.py:835-859` 只按传入对象写类别标签；METRO 适配器同样在 `solver/scripts/build_china81_metro_suite_20260812.py:1735-1764,1790-1814` 固定读 `base_all_*` 后写入传入标签。
- **错在哪**：主类 D。选择器改变了名字和 `has_additional_total_fleet_cap`，未必改变实际车队值。
- **正确写法应是什么**：标签、实际列和值必须来自同一个 `fleet_parameters.depot_caps(row)`；如果 V3 套件只允许 endogenous，就应拒绝 `fixed25`，不能接受后再贴错标签。本报告不替用户选择正式车队类别。
- **是否进入评价器/保存结果（FACT）**：属于评价器输入，因为这些上限进入 instance、车队注册和完整评价的 depot fleet 检查。当前 PRDFIX 与 METRO 的 `base_all_*` 和 `num_*` 全表逐行相等，代表行见 `data/ChinaInstances/china81_suite_prd_fix_v1_20260812/fleet_caps.csv:1-4`、`data/ChinaInstances/china81_metro_suite_v1_20260812/fleet_caps.csv:1-4`，所以现有数值差异被掩盖；已查当前保存包均明确使用 endogenous，没有找到已经贴错 `fixed25` 的保存包。
- **若改动，影响哪些产物**：未来 fixed25/endogenous 正式对照的 vehicle registry、可行域、成本/排放、metadata 和 raw results；当前同值数据的已保存精确得分不因本项变化。

### 4. 精确总账计路线时间成本，利润账完全不记该成本

- **路径与现写法（FACT）**：`solver/src/setp_solver/cost.py:194-199,214,1230-1252` 把行驶时间加公共站途中充电占用时间，按 `route_time_cost_per_hour` 计入 `total_cost`；`solver/src/setp_solver/profit.py:181-225` 没有 `cost_time` 字段，也不汇总这笔成本。
- **错在哪**：主类 B，兼 E。系统总账与车场利润账缺少同一成本项。
- **正确写法应是什么**：费率非零时，应按各 home depot 所属路线，用与总账相同的时间定义扣除 `T_d × r`。
- **是否进入评价器/保存结果（FACT）**：代码缺口进入利润/公平评价，但当前 `solver/src/setp_solver/prices.py:173-176` 默认费率是 0；生产入口未检出非零覆盖，唯一 75 元/h 用例是测试。因此当前保存结果的数值影响为 **0**，不能写成已污染。例：combat 包在 `solver/reports/combat_v2_20260812/combat_v2_5cycles_final/best_solution.json:563,576` 保存 route time 15.1600556 h、`cost_time=0`。
- **若改动，影响哪些产物**：未来非零路线时间成本情景的 depot profit、Pi0、margin 和 fairness；当前零费率包无需因本项重算。

### 5. 路线搜索代理漏算 EV 的 50 元/实体车·日溢价

- **路径与现写法（FACT）**：`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:821-839` 给每个物理 Duty 的 fixed cost 统一写 `vehicle_fixed_cost`，CV/EV 都是 170；整条内核没有读取 `ev_daily_fixed_premium_cny`。完整评价在 `solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:833-858` 才补每辆 EV 50 元。
- **错在哪**：主类 E，兼 B。搜索代理和最终总账的车辆启用成本不一致。
- **正确写法应是什么**：既然代理已经包含车辆 fixed cost，EV Duty 的启用代理应是 220 元/物理车·日，CV 为 170 元；多趟仍只计一次。
- **是否进入评价器/保存结果（FACT）**：不改最终评价公式，但进入路线候选生成、局部搜索与 incumbent 形成。每启用一辆 EV，搜索 fixed component 少 50 元，即相对正确 EV 固定成本少 **22.7273%**；方向上偏向启用/保留 EV。当前 combat 保存解由这条搜索路径产生并用了 5 辆 EV，但不能静态断言最终解因此改变多少；保存 `total_cost` 已正确补回 250 元。
- **若改动，影响哪些产物**：搜索轨迹、候选排序、算子统计、raw runs 与所达 incumbent；不直接改已经保存的精确成本分解。

### 6. EV 电价/碳强度代理在入口之间不统一，默认和动态插入仍走全日均值

- **路径与现写法（FACT）**：`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:44-59,718-748` 默认 `shift_aware_ev_unit_cost_enabled=False`，用车场全天时段的电价加碳成本算术均值；班次代理才在 `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:857-909` 按可达充电窗选槽。combat 主入口在 `solver/scripts/run_problem_hgs_private_technical.py:2174-2180` 打开班次代理；动态插入在 `solver/src/setp_solver/algorithms/problem_hgs/dynamic_insertion.py:257-268` 新建内核时没有传该开关，回落到全天均值。完整评价按实际 charging action 与实际时槽结算，见 `solver/src/setp_solver/cost.py:1123-1137,1140-1206`。
- **错在哪**：主类 E。同一实验链不同 proposal 入口使用不同代理口径。
- **正确写法应是什么**：同一链的所有 EV proposal 入口应使用与各自可达充电窗一致的代理；最终评价继续按实际充电时刻结算。若保留全天均值，必须明确它只是静态代理，不能称为精确成本。
- **是否进入评价器/保存结果（FACT）**：不污染完整评价。现有两班见证在 `solver/reports/root_design_redteam_20260812/report.md:257-291` 与 `solver/reports/combat_v2_20260812/combat_v2_5cycles_final/metadata.json:291-376` 显示：旧均值 0.7901729167 元/kWh，联合可达窗电量加权值 0.6198584733 元/kWh；**实际/窗口值比旧代理低 21.5541%，等价地旧代理比窗口值高 27.4763%**。这里量化的是电价分量，保存表没有单独给出“电价+碳成本”完整代理的总偏差。这不是“代理低估 21.6%”。另一旧货币择时情景是代理 0.7902、实付 1.1300，代理低估约 43%（`docs/handoff/instance_defect_ledger_and_serial_algorithm_20260811.md:467-477`），说明方向随候选充电时序而变。当前动态插入技术包确实启用该入口（`solver/reports/dynamic_insertion_operator_20260812/on_shortest_private/metadata.json:89-106,180-205`），但 `solver/reports/dynamic_insertion_operator_20260812/on_shortest_private/best_solution.json:381` 保存 `n_veh_ev=0`，未证明已有 EV 数值受影响。
- **若改动，影响哪些产物**：默认路线搜索与动态插入的候选排序、轨迹和 incumbent；不改完整评价的已保存精确结算。

### 7. CV/EV 推进成本代理固定按半载，完整评价按逐弧实际载重

- **路径与现写法（FACT）**：`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:919-1000` 固定 `proxy_load_kg = 0.5 × payload_capacity`；完整评价在 `solver/src/setp_solver/cost.py:304-344` 根据客户序列计算每一弧剩余实际载重。
- **错在哪**：主类 E。这是明确的代理—精确口径差，不是精确评价器错误。
- **正确写法应是什么**：若要求两者一致，应使用候选逐弧载重；若保留半载代理，报告必须写清“只提供搜索梯度，完整评价为准”，不能把代理成本当结果成本。
- **是否进入评价器/保存结果（FACT/UNKNOWN）**：完整评价未受污染。实际载重高于半载的弧，代理低估推进能耗；低于半载则高估。全路线净方向和幅度必须逐候选重放，本任务禁止运行，故为 `UNKNOWN`。combat 默认开启推进代理，已进入保存 incumbent 的搜索路径。
- **若改动，影响哪些产物**：路线边成本、候选次序、搜索轨迹和 incumbent；已保存精确成本不因代理字段直接重算。

### 8. V3 构造/shift contract 把 1735 kg 写成通用载重，但当前 EV 权威值是 1700 kg

- **路径与现写法（FACT）**：`solver/scripts/build_china81_suite_rebuild_20260812.py:101-103,1156-1174,2102-2104` 用单一 `VEHICLE_PAYLOAD_CAPACITY_KG=1735` 打包并写契约；代表性保存文件 `data/ChinaInstances/china81_suite_prd_fix_v1_20260812/instances/cn-prd-50c-01-V3-TWO-SHIFT-PRDFIX/shift_contract.json:26-34` 和 `data/ChinaInstances/china81_metro_suite_v1_20260812/instances/cn-cy-50c-01-V3-TWO-SHIFT-METRO/shift_contract.json:26-34` 都写 `vehicle_payload_capacity_kg=1735.0`。当前车型权威在 `solver/src/setp_solver/china81.py:805-835`：CV 1735 kg、EV 1700 kg。
- **错在哪**：主类 D，兼 A。保存契约把 CV 的数值写成了无车型限定的通用值，对 EV 高估 35 kg，即 **2.0588%**。
- **正确写法应是什么**：要么保存/构造时明确该 1735 kg 只用于 all-CV 健康见证，要么按车型分别记录 1735/1700 kg；不能把 1735 标成全车型共同上限。本报告不替用户选择是否采用共同构造容量。
- **是否进入评价器/保存结果（FACT）**：已进入 V3 构造、健康见证和 shift contract。最终精确容量检查没有照抄该通用值，而是在 `solver/src/setp_solver/instance_loader.py:226-237`、`solver/src/setp_solver/check.py:703-716` 按 route vehicle type 取 1735/1700，因此精确评价会拒绝超过 1700 kg 的 EV 路线。问题是构造契约、健康解释及车型交换搜索空间不一致，不是已保存精确成本算错。
- **若改动，影响哪些产物**：V3 的 shift contract、health witness、初始路线/车型交换可行域与健康报告；不影响道路坐标和矩阵。

### 9. 公开 exact 需求与容量都乘 1000，但落盘字段仍叫普通“完成需求”

- **路径与现写法（FACT）**：`third_party/setp_hgs_kernel/setp_hgs_kernel/read.py:30-35,198-204,256-267` 的 `exact` 对 demand 和 capacity 都做 `round(1000×value)`。`solver/scripts/run_public_v2_28_clean_ruler.py:313-335` 从内核读缩放整数，却命名 `completed_delivery/total_delivery`；该字段写入 `best_solution.json`、`decision.json`、`report.md`（`solver/scripts/run_public_v2_28_clean_ruler.py:939-1010`）、progress（`solver/scripts/run_public_v2_28_clean_ruler.py:1110-1129`）和顶层 raw runs（`solver/scripts/run_public_v2_28_clean_ruler.py:1180-1189`），均没有 `_scaled` 或 scale 说明。
- **错在哪**：主类 C，兼 A。小数缩放值被当成原始需求量展示。
- **正确写法应是什么**：输出原始精度审计中的 `completed_demand_raw/total_demand_raw`；若保留整数，字段名应为 `*_delivery_scaled` 并明确 `scale=1000`。
- **是否进入评价器/保存结果（FACT）**：求解和容量约束两边同乘 1000，内部可行性没有错；问题已进入公开 28 题候选包的 59 份 per-run `decision.json/report.md` 及顶层 CSV/日志。例：`solver/reports/public_v2_28_clean_ruler_20260810/PR11A_independent_seed11/decision.json:30-60` 同时保存 `completed_delivery=4806000` 和 raw `4806.0`，同目录 `report.md:1-5` 把 4806000 写成完成需求。当前论文 A3 明确读取 raw 字段（`docs/paper_gci_dmm_vrp_20260804/table_shells_20260812/table_shells.md:90-95`），未被该标签污染。
- **若改动，影响哪些产物**：59 份单次 best/decision/report、顶层 raw runs 与 progress；不影响 routes、成本、scaled feasibility 或 raw-precision audit。

### 10. China81 需求实际是 kg，但多个活动输出字段与报告省略单位

- **路径与现写法（FACT）**：`solver/src/setp_solver/china81.py:772-801` 从 `demand_kg` 读入，并在 `solver/src/setp_solver/china81.py:472-483` 以 1 demand unit=1 kg 保存。Problem-HGS runner 在 `solver/scripts/run_problem_hgs_private_technical.py:2484-2485,2737-2766,2836-2844` 写 `demand_served/demand_total` 和“完成需求量”，不写 kg；同类字段还见 `solver/scripts/run_private_ablation.py:147-163,318-340`、`solver/scripts/run_component_interaction.py:78-101,640-662`、`solver/scripts/run_mixed_fleet_experiment.py:744-768,1072-1092`。动态报告也写“单位需求”（`solver/scripts/run_problem_hgs_dynamic_disclosure_scout.py:1378,1539`）。
- **错在哪**：主类 A。数值本身是 kg，但落盘字段和人读报告没有单位，容易被下游当订单量、吨或缩放需求。
- **正确写法应是什么**：字段命名为 `demand_served_kg/demand_total_kg`，或在 metadata 明确 `demand_unit=kg`；中文报告写“kg”。
- **是否进入评价器/保存结果（FACT）**：不影响评价器数值，已经进入活动技术包。例：`solver/reports/metro_rebuild_20260812/cn-cy-50c-01_1cycle_probe/raw_runs.csv:1-2` 保存 13266/13266 而表头没有 kg。`solver/scripts/finalize_metro_rebuild_20260812.py:156-159,201` 又直接沿用这些字段。
- **若改动，影响哪些产物**：私有实验 raw runs、report、汇总器和论文服务量表头；不改 demand 数值本身。

### 11. METRO 报告用 80 kWh 推续航，活动电池权威是 77.28 kWh

- **路径与现写法（FACT）**：报告构造器 `solver/scripts/build_china81_metro_suite_20260812.py:1629-1636` 和保存报告 `solver/reports/metro_rebuild_20260812/report.md:137-141` 写“80 kWh、0.605–0.736 kWh/km，满电约 109–132 km”。活动车型与兼容字段分别在 `solver/src/setp_solver/china81.py:831-843,1081` 使用 77.28 kWh；参数修正报告也明确 77.28 kWh（`docs/handoff/param_fix_20260812/report.md:41-48`）。
- **错在哪**：主类 D。报告默认值与实际取数不一致。
- **正确写法应是什么**：若沿用相同单位电耗，77.28/0.736–77.28/0.605 对应约 **105–128 km**，不是 109–132 km。
- **是否进入评价器/保存结果（FACT）**：评价器使用 77.28 kWh，未被 80 kWh 污染；错误已进入 METRO 保存报告和健康解释。
- **若改动，影响哪些产物**：METRO `report.md` 及引用该续航区间的文字；不改已保存路线、SOC 或成本。

### 12. 旧动态合成入口把经纬度角度直接除以 m/s

- **路径与现写法（FACT）**：China81 loader 在 `solver/src/setp_solver/china81.py:714-730` 把 `x=longitude`、`y=latitude`。旧合成事件 helper `solver/src/setp_solver/search/dynamic.py:2180-2203` 却计算经纬度欧氏差，再除以 `DEFAULT_PRICES.v_speed_ms`；默认速度是 25 m/s（`solver/src/setp_solver/prices.py:29`）。唯一调用在 `solver/src/setp_solver/search/dynamic.py:196-205`，属于缺少 `dynamic_events.tsv` 时的旧合成路径（`solver/src/setp_solver/search/dynamic.py:136-151`）。
- **错在哪**：主类 A，兼 D、G。角度不是米，不能除以 m/s 得秒；同时还硬绑共享默认速度而非活动路网。
- **正确写法应是什么**：China 事件窗必须读取对应 CV/EV 冻结 `road_duration_s` 或预计算 direct travel seconds；经纬度欧氏差不得作为米制距离。
- **是否进入评价器/保存结果（FACT）**：以 C026 为静态见证：源坐标在 `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/instances/cn-prd-150c-01-V2-LOCATIONS/nodes.csv:4,35`，角距离约 0.321823757；除 25 得 0.01287295 秒，而当前真实动态流 `data/ChinaInstances/china81_dynamic_stream_v1_20260811/private/true_dynamic_events.csv:1-2` 保存 direct travel 2162.2 秒，相差约 **167,965 倍**。当前 P34 构造器直接读 `road_duration_s.csv`（`solver/scripts/generate_potential_pool_dynamic_streams.py:563-600`），Problem-HGS 子实例复制既有路网；没有找到 China81 保存结果走这条旧 helper。若误用于 profiled China，新 N 节点还会在 `dynamic.py:2110-2122` 因缺矩阵提前失败，通常进不了评价器。
- **若改动，影响哪些产物**：未来误复用旧合成入口时的事件 ready/due、触发与可行性；当前 P34 真值流、现有 China 动态技术包不受影响。

### 13. SISR 把五个不同规模算例的绝对成本差直接相加，并让和的正负参与停止条件

- **路径与现写法（FACT）**：`solver/scripts/run_sisr_incremental_rebuild.py:102-119,162-195` 先算逐题差，再用 `sum(b_minus_a_scaled)>0` 触发条件 2；旧聚合器 `solver/scripts/run_sisr_public_ablation.py:326-351` 同样保存绝对差的 sum/mean。保存产物见 `solver/reports/sisr_public_ablation_20260811/decision.json:138-148`、`report.md:5-9`，以及增量版 `decision.json:1-40`、`report.md:23-48`；`docs/handoff/CURRENT_PROJECT_CONTEXT.md:234-242,305-313` 复述了该判定。
- **错在哪**：主类 F。五题是不同规模、不同成本基数的独立 benchmark；绝对 CNY/缩放成本差求和会让大成本题获得更高权重，不能代表“典型一题”。
- **正确写法应是什么**：先逐题计算 `(B-A)/A`，再报等权宏平均/中位数和逐题胜负。若另报 ratio-of-sums，必须明确它是按 A 成本加权的组合量，不能冒充典型题，也不能未经依据进入停止门。
- **是否进入评价器/保存结果（FACT）**：不影响逐题 evaluator 或 raw runs，已经进入两个 SISR 技术包的 summary、decision、report 及当前上下文。按保存逐题数复算：旧版 ratio-of-sums 为 **0.735951747%**，逐题相对差宏平均为 **0.591958872%**；增量版分别为 **0.106834246%** 和 **0.025105437%**，幅度相差约 4.26 倍。本样本两个口径方向碰巧都为正，不能据此断言停止结论一定反转。
- **若改动，影响哪些产物**：两个 SISR 技术包的汇总数字和条件 2 输入、`CURRENT_PROJECT_CONTEXT.md` 的相关数字；不改逐题保存成本与可行性。两包均标 `formal_paper_result=false`。

### 14. MAIN-2 报告会跨实例池化绝对成本、排放、车辆数与“全局 Best”

- **路径与现写法（FACT）**：`solver/scripts/run_mixed_fleet_experiment.py:1221-1235,1341-1368` 接受多个实例并逐实例运行；但 `render_report()` 在 `solver/scripts/run_mixed_fleet_experiment.py:1114-1159` 对每个臂的全部成功实例×种子直接取全局最小成本、绝对成本/排放/车辆/客户均值，在 `solver/scripts/run_mixed_fleet_experiment.py:1172-1200` 又跨实例平均绝对成本差和排放差。每臂的成功行由 `solver/scripts/run_mixed_fleet_experiment.py:1114-1115` 独立筛选，失败时各臂还可能用不同子集。
- **错在哪**：主类 F。不同规模实例的绝对成本 Best/均值没有共同分母；独立成功子集会进一步破坏可比性。
- **正确写法应是什么**：先在每个实例内聚合种子，再在相同配对键上报告逐实例相对变化和宏平均/中位数；取消跨实例“全局 Best”，失败臂使用共同配对集。
- **是否进入评价器/保存结果（FACT）**：不进 evaluator。仓库未找到完成的正式 MAIN-2 包；`solver/reports/mixed_fleet_harness_20260811/report.md:1-10` 明确只有 dry-run/测试，正式实验未启动。因此这是正式开跑前风险，尚未污染正式结果，未来 per-run raw rows仍可复核。
- **若改动，影响哪些产物**：未来 MAIN-2 `report.md` 的 Best/Avg、配对差和失败分母；不影响单次完整评价结果。

### 15. `convergence.csv.wall_seconds` 可能混入两种起钟点

- **路径与现写法（FACT）**：正常改进记录在 `solver/scripts/run_problem_hgs_private_technical.py:2351-2363` 写 `state.elapsed_seconds`；该值在 `solver/src/setp_solver/algorithms/problem_hgs/runner.py:377-389` 明确等于 initialization wall + search wall。若正常回调没写行，最终 fallback 在 `solver/scripts/run_problem_hgs_private_technical.py:2428-2445` 却把 `result.accounting.run_wall_seconds` 写进同名 `wall_seconds`；`solver/src/setp_solver/algorithms/problem_hgs/contracts.py:366-373` 明确 `run_wall_seconds` 不含初始化。下游 `solver/scripts/finalize_metro_rebuild_20260812.py:115-153` 直接把最后一行当 last-improvement time。
- **错在哪**：主类 G。相同列名有“初始化+搜索”和“仅搜索”两种墙钟基准。
- **正确写法应是什么**：同一列统一为 total algorithm wall；或分成 `total_algorithm_wall_seconds` 与 `search_wall_seconds`，下游明确选择。
- **是否进入评价器/保存结果（FACT）**：不影响停止条件或 evaluator。当前检查的 `solver/reports/metro_rebuild_20260812/cn-cy-50c-01_1cycle_probe/convergence.csv:1-2` 只有正常回调行，未发现已经混写的保存文件；这是确定的代码路径风险，不编造成现有结果污染。
- **若改动，影响哪些产物**：收敛曲线、last-improvement time、预算校准与汇总表；不改最终成本。

### 16. 增量 SISR 报告的“净值为负”与实际公式、数值相反

- **路径与现写法（FACT）**：`solver/scripts/run_sisr_incremental_rebuild.py:102-119,201-208` 明确负的 `B-A` 才是改善；条件代码在 `solver/scripts/run_sisr_incremental_rebuild.py:168-175` 实际要求 sum>0；报告模板 `solver/scripts/run_sisr_incremental_rebuild.py:299-302` 却写“净值为负”。保存报告 `solver/reports/sisr_incremental_rebuild_20260811/report.md:45-50` 同时出现“净值为负”和 `B-A=+44086`。
- **错在哪**：主类 C。正负方向标签反了。
- **正确写法应是什么**：若“净值”指 `B-A`，应写“净值为正/成本净增加”；若想表达 SISR 效果为负，应明确写“净效应为负”，不能与 `B-A` 符号混写。
- **是否进入评价器/保存结果（FACT）**：不进 evaluator；decision JSON 的数值和布尔与代码一致，错误已进入保存 `report.md` 的条件文字。
- **若改动，影响哪些产物**：增量 SISR 技术报告与引用该句的说明，不改逐题成本。

### 17. 300 秒运行的 metadata 被硬写成“20 分钟上限”

- **路径与现写法（FACT）**：runner 参数和真实停止判断分别在 `solver/scripts/run_problem_hgs_private_technical.py:1863-1865,2367-2370` 使用 `args.max_runtime_seconds`；metadata 模板却在 `solver/scripts/run_problem_hgs_private_technical.py:2574-2579` 固定写“user-set 20-minute hard ceiling”。保存例 `solver/reports/convergence_calibration_20260812/probe5_seed1_1cycle/metadata.json:117-122` 同时写 `max_runtime_seconds=300.0` 和“20-minute”。
- **错在哪**：主类 G。300 秒是 5 分钟，不是 20 分钟。
- **正确写法应是什么**：文字由实际秒数生成，或只写参数化墙钟上限，不硬编码 20 分钟。
- **是否进入评价器/保存结果（FACT）**：真实停止行为按 300 秒执行，评价器和运行预算本身没错；错误已进入保存 metadata，可能误导预算审计。
- **若改动，影响哪些产物**：相关技术包 metadata 与引用其预算说明的报告；不改结果数值。

### 18. 一份交接稿把“代理高估”写成“低估 21.6%”

- **路径与现写法（FACT）**：`docs/handoff/root_design_audit_20260812.md:97-103` 写“实付 0.620 vs 代理 0.790，低估 21.6%”。同一数字的更新事实源 `docs/handoff/CURRENT_PROJECT_CONTEXT.md:516-524` 和 `solver/reports/combat_v2_20260812/report.md:91-93` 正确写成新值比旧均值降低 21.5541%。
- **错在哪**：主类 C。0.790 大于 0.620，主语若是“代理”，应为高估；21.6% 的分母是代理值。
- **正确写法应是什么**：“实际/窗口值比旧代理低 21.5541%”；若以实际值作分母，则“旧代理比实际/窗口值高 27.4763%”。
- **是否进入评价器/保存结果（FACT）**：不进 evaluator；已进入一份 handoff 文字，更新的当前上下文和 combat 报告已正确。
- **若改动，影响哪些产物**：仅该旧交接稿及从它复制的叙述，不改任何数值产物。

## 三、按 A—G 分类的逐条台账

本节按主类列账；完整路径、现写法、正确口径、评价器/保存状态和影响产物均见第二节对应编号。

### A. 量纲

| 编号 | 现写法 | 正确口径 | 评价器/保存状态 |
|---|---|---|---|
| 10 | China81 `demand_kg` 落盘为无单位 `demand_served/demand_total` | 字段或 metadata 明确 kg | 不进 evaluator；已进私有 raw/report |
| 12 | 经纬度角度欧氏差 ÷ 25 m/s | China 用冻结 `road_duration_s` | 当前 China 链未调用；未发现保存结果污染 |

### B. 计价与计量基准

| 编号 | 现写法 | 正确口径 | 评价器/保存状态 |
|---|---|---|---|
| 1 | EV 50 元车日溢价只进系统总账 | 同一实体 EV、同一 home depot 只扣一次 | 进利润/公平评价；保存 margin 已错，总成本正确 |
| 2 | 车场利润用算例城市柴油均价 | 按 route home-depot city 价 | 进利润/公平评价；多城市技术包已受影响 |
| 4 | 路线时间成本只进总账 | 非零时按同一定义分摊到车场利润 | 进评价链；当前费率 0，保存数值影响 0 |

### C. 比例与小数

| 编号 | 现写法 | 正确口径 | 评价器/保存状态 |
|---|---|---|---|
| 9 | `round(1000×demand)` 仍叫普通 delivery | raw 值，或 `_scaled`+scale | 求解正确；59 份候选包和顶层汇总标签受影响 |
| 16 | `B-A=+44086` 同时写“净值为负” | 区分 `B-A` 符号和“净效应”措辞 | 不进 evaluator；已进技术报告 |
| 18 | 0.790 对 0.620 写“代理低估 21.6%” | 实际比代理低 21.5541%，或代理比实际高 27.4763% | 不进 evaluator；一份 handoff 受影响 |

### D. 默认值与实际取数

| 编号 | 现写法 | 正确口径 | 评价器/保存状态 |
|---|---|---|---|
| 3 | PRDFIX/METRO 固定读 endogenous 列，却接受并保存任意类别标签 | 值和标签由同一 selector 产生，或拒绝不支持类别 | 属 evaluator 输入；当前列值相同，未见数值污染 |
| 8 | 构造/shift contract 通用写 1735 kg | 明确 CV-only，或分车型 1735/1700 | 已进 V3 数据契约；精确检查仍按车型 |
| 11 | METRO 报告用 80 kWh 推续航 | 活动值 77.28 kWh，约 105–128 km | 不进 evaluator；已进保存报告 |

### E. 代理值与精确值

| 编号 | 现写法 | 正确口径 | 评价器/保存状态 |
|---|---|---|---|
| 5 | 路线代理 EV fixed cost=170 | EV=220、CV=170，均按物理车一次 | 不进终评；进入保存 incumbent 的搜索路径 |
| 6 | 默认/动态插入用全日均值，combat 用可达窗 | 同一链 proposal 使用一致的可达窗代理 | 不进终评；当前动态插入保存解全 CV，未证 EV 数值污染 |
| 7 | 推进代理固定半载 | 候选逐弧载重，或明确仅是半载梯度 | 不进终评；进入 combat 保存 incumbent 的搜索路径 |

### F. 聚合口径

| 编号 | 现写法 | 正确口径 | 评价器/保存状态 |
|---|---|---|---|
| 13 | 五题绝对成本差相加并进入停止条件 | 逐题相对差后宏平均/中位数，保留胜负 | 不进 evaluator；已进 SISR 技术判定和上下文 |
| 14 | MAIN-2 跨实例全局 Best、绝对均值、独立成功子集 | 实例内聚合后用共同配对集报相对变化 | 尚无正式保存包；开跑前风险 |

### G. 时间基准

| 编号 | 现写法 | 正确口径 | 评价器/保存状态 |
|---|---|---|---|
| 15 | 同一 `wall_seconds` 混 total wall 与 search-only wall | 统一起钟点或拆列 | 不进 evaluator；当前抽查文件未见混写 |
| 17 | 300 秒 metadata 写 20 分钟 | 从实际秒数生成文字 | 停止行为正确；保存 metadata 错 |

## 四、存疑待人工确认清单

以下项目有真实口径分叉，但现有证据不足以判错；不计入前述 18 条。

### U1. 7.2 m³ 与 0.1 h/m³ 的情景权威仍不清楚

- **路径/现写法（FACT）**：`solver/scripts/build_china81_suite_rebuild_20260812.py:101-103` 登记 7.2 m³ 和 0.1 h/m³；打包/时序使用见 `solver/scripts/build_china81_suite_rebuild_20260812.py:1156-1174`，保存 shift contract 见 `data/ChinaInstances/china81_suite_prd_fix_v1_20260812/instances/cn-prd-50c-01-V3-TWO-SHIFT-PRDFIX/shift_contract.json:26-34`。7.2 m³ 还进入完整 V3 volume constraint（`solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:895-908`）。
- **为什么存疑**：两者量纲自洽，但本轮材料没有找到可核的车型/企业来源或用户最终情景裁决。不能因为数值“看着合理”就认定正确，也不能因缺来源就臆断为错。
- **需人工确认的正确口径**：确认它们是已批准的构造情景还是现实参数；若是构造情景，应明确标注，不改写成车辆事实。
- **评价器/产物影响**：7.2 m³ 影响正式可行域；0.1 h/m³ 影响装载、午休和健康见证。若数值改变，V3 health/witness/shift contract 及未来正式结果都需重新核账。

### U2. CMEM 的 `psi_conv=737 g/L` 是否需要中国化，当前不能从 0.84 kg/L 机械替换

- **路径/现写法（FACT）**：`solver/src/setp_solver/prices.py:30-35,79-87` 把 737 g/L 登记为 Goeke/Demir CMEM 油耗模型参数；`solver/src/setp_solver/cost.py:889-900,995-1021` 用它把模型燃油率换成 L。柴油排放因子另按中国指南 0.84 t/m³ 生成；`docs/handoff/param_fix_20260812/report.md:18-26,130-136` 明确两套公式不能机械共用密度。
- **为什么存疑**：当前分离在数学上正确，但 737 这一国外 CMEM 转移参数是否应针对中国柴油/车型重新标定，现有材料没有给出批准结论。
- **需人工确认的正确口径**：保留公式边界，单独决定 CMEM 参数是否沿用文献或中国化；不得直接把 0.84 kg/L 抄过去。
- **评价器/产物影响**：若改，会改变所有 CV 弧油耗、燃油成本、排放和搜索代理；当前不判为错误。

### U3. 动态 `maximum_wait` 是固定时钟还是每批首单重新计时

- **路径/现写法（FACT）**：`solver/src/setp_solver/potential_pool_dynamic.py:642-665` 初始 deadline 是 reception start+interval；需求阈值触发后，`solver/src/setp_solver/potential_pool_dynamic.py:677-694` 把 deadline 重置为 appearance+interval。
- **为什么存疑**：如果协议定义固定接单时钟或“需求触发后重开一窗”，现代码正确；如果定义每个 pending batch 从首个未处理订单开始计最大等待，则当前重置点可能不对。任务材料没有给出唯一语义。
- **需人工确认的正确口径**：只需确认上述两种协议哪一种是用户批准版本，不由本报告替用户选。
- **评价器/产物影响**：影响触发秒、批次划分、在线候选和动态结果；不是静态成本单位错误。

### U4. 路线代理 identity 没绑定默认均值电价、共同固定成本和 EV 溢价

- **路径/现写法（FACT）**：`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:227-269` 的 identity 包含实例、车队、算子、scale；只有启用班次代理时才额外写 shift proxy，默认均值所用价格、共同 fixed cost 和 EV 溢价不在 payload。该 identity 进入 search configuration（`solver/src/setp_solver/algorithms/problem_hgs/runner.py:1448-1471`）与 education cache key（`solver/src/setp_solver/algorithms/problem_hgs/integrated_private.py:637-643`）。
- **为什么存疑**：cache 在同一不可变 engine 内存活，未发现运行时跨参数串值；但跨运行 metadata/provenance 可能出现不同价格却同 proposal identity。
- **需人工确认的正确口径**：确认该 hash 只作单进程内 cache identity，还是还承担跨运行科研身份；前者当前可接受，后者字段不足。
- **评价器/产物影响**：潜在影响 metadata、search identity 和缓存可追溯性；没有证据证明完整评分已串值。

## 五、“看着奇怪但正确”清单

### 5.1 170 元固定成本当前确实按实体车·日计一次，不再按趟重复

`FACT`：`solver/src/setp_solver/solution.py:11-25` 用 `#Tn` 还原物理车；`solver/src/setp_solver/cost.py:164-170` 对唯一 physical ID 计固定成本；`solver/src/setp_solver/profit.py:91-110` 也按物理车只扣一次。多趟 route 数多于物理车数是正确结构。当前问题 1 只针对 EV 额外 50 元漏出利润账，不代表基础 170 元仍按趟算错。

### 5.2 公开 exact 的 `×1000` 内部尺本身正确

`FACT`：`third_party/setp_hgs_kernel/setp_hgs_kernel/read.py:30-35,198-204,256-267` 同时缩放 demand 和 capacity；`solver/src/setp_solver/algorithms/problem_hgs/public_search.py:48-60` 明确活动公开尺为 `exact=round(1000×value)`。约束两边同尺度，问题 9 仅是落盘字段没有标 scaled。

### 5.3 当前 China81 的 60 kW 是功率，且与非线性 SOC 曲线成对使用

`FACT`：`solver/src/setp_solver/china81.py:1090-1126` 同时登记 `depot_charge_power_kw=60` 和 60 kW 曲线的 SOC 断点/相对功率；rebuild 默认也选 60 kW 配对（`solver/src/setp_solver/private_instance_rebuild_20260811.py:59-72,103-109`）。22 kW 是显式可选情景，不是当前默认。精确充电结算通过分段曲线时长与时槽积分（`solver/src/setp_solver/cost.py:431-596`），没有再用 `charge_hours×power` 无上限线性外推。

### 5.4 `prices.py` 的 90 km/h 是历史无路网 fallback，活动 China81 不用它推真实弧时间

`FACT`：`solver/src/setp_solver/instance_loader.py:171-210` 在存在 CV/EV road profiles 时直接返回冻结 `distance_m/duration_s/sum_v2d`，仅无 profile 的历史实例才用 `distance/fallback_speed`；`solver/src/setp_solver/cost.py:309-315` 走该接口。因此不能再用 90 km/h 默认值倒推 China81 日里程或续航。问题 12 是另一个旧 helper 绕过了该接口。

### 5.5 活动 China81 的分钟、秒和 kgCO2、gCO2 换算当前闭合

`FACT`：`solver/src/setp_solver/china81.py:781-784` 把订单分钟乘 60 变成秒；`solver/src/setp_solver/china81.py:976-989` 把 `kgCO2e/kWh` 乘 1000 写成 `gCO2/kWh`；`solver/src/setp_solver/cost.py:735-765` 再除 1000 返回 kgCO2。没有发现活动链在这些位置漏乘或多乘 60/1000。

### 5.6 “5805 单”和“120 站”在最新稿里是清楚标注的套件记账，不是单个算例

`FACT`：`docs/paper_gci_dmm_vrp_20260804/table_shells_20260812/convention_screening.md:25-36` 明确 5805 是 81 例的实例—订单记录合计，不是某一例或求解完成量；`docs/paper_gci_dmm_vrp_20260804/table_shells_20260812/convention_screening.md:69-75` 把 120 个实例内 station 节点降为内部记账。`solver/reports/station_restore_20260812/report.md:23-38` 明确 120=54×1+21×2+6×4，不是 120 个互异现实站。旧表壳曾有歧义，但最新稿已纠正，不再报成当前错误。

### 5.7 公开 A3 的服务量汇总和 gap 平均口径当前正确

`FACT`：`docs/paper_gci_dmm_vrp_20260804/table_shells_20260812/table_shells.md:74-95` 标题和表注明确范围是公开 28 题，需求取 `raw_precision_audit.*_demand_raw`；gap 是先逐题相对 BKS，再对 28 题算术平均。它不是把 28 个实例的绝对成本直接相加，也没有使用问题 9 的 1000 倍字段。

### 5.8 私有路线代理的 100000 尺与公开 exact 的 1000 尺是两套独立内部尺度

`FACT`：私有路线代理在 `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:38,849-854` 用 100000 将人民币代理量化到 1e-5 元；公开 reader 在 `third_party/setp_hgs_kernel/setp_hgs_kernel/read.py:30-35` 用 1000 保存公开实例小数。私有最终完整评价仍是浮点精确账，未发现两种 scale 交叉相加。

### 5.9 完整评价 cache 未发现跨对象串值

`FACT`：完整 context hash 绑定所有评价输入（`solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:323-332`）；增量缓存核对实际 changed-duty 集，并可用 full-truth sentinel（`solver/src/setp_solver/algorithms/problem_hgs/evaluation.py:611-731`）；候选 fingerprint 包含 Duty、充电与排班（`solver/src/setp_solver/algorithms/problem_hgs/model.py:467-490`）。问题 U4 是 proposal identity 的可追溯性疑问，不等于已证完整评价 cache 串值。

### 5.10 油耗模型与排放因子使用不同“密度/转换参数”不是自动错误

`FACT`：`psi_conv=737 g/L` 属于 CMEM 油耗率公式；中国指南 0.84 t/m³ 属于柴油燃烧 CO2 排放因子生成链。`docs/handoff/param_fix_20260812/report.md:18-26,130-136` 已明确二者公式角色不同。正确做法是分别核源，而不是为了“统一”把一个数机械抄到两个公式。

## 审计停止边界

本轮已覆盖用户指定的 A—G、必读文件、活动评价/搜索入口和已保存关键结果。没有运行任何求解器、实验或测试；没有因发现问题而新增门禁、合同或重构方案。所有无法由当前文件直接确定的语义均留在第四节，没有为凑数量判错。
