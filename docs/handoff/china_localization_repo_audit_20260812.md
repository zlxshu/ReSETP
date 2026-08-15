CHINA_REPO_AUDIT_DONE

# ReSETP 全仓库中国化只读审计（2026-08-12）

## 审计口径

- 本次只读检查 `solver/`、`data/` 以及被项目调用的 `baselines/`、`third_party/`。除本报告外，没有写入任何文件；没有运行求解器、测试或实验。
- “须改”是审计判定，不代表本次已经获准改参数。参数数值、模型含义和重跑范围仍须用户批准。
- 计数单位是“去重后的参数或调用链问题族”，不是同一字符串在多少文件出现。一个问题可同时属于“须改”和“未找到中国可核来源”，所以两个数字不能相加。
- “正式实验”分两种身份：仓库中 E3–E6、XA、XA2、XB、XC 等历史目录自称 `formal`；但当前项目事实源 `docs/handoff/CURRENT_PROJECT_CONTEXT.md:341-350` 明确记载“尚未进入当前正式实验，尚无可回填论文的正式结果”。本报告因此把前者称为“历史正式包”，不把它们恢复为当前论文证据。

# 一、结论摘要

## 1. 数量结论

| 结论 | 数量 | 口径 |
|---|---:|---|
| 须改或须在新一轮正式实验前处理 | **17 项** | 包括数值/调用链硬错误，以及必须改正来源身份或情景标签的问题 |
| 可以保留 | **13 项** | 中国可核字段、明确的中国构造数据、国际通行模型结构、公开基准和国际求解器 |
| 仍未找到对应中国可核来源 | **10 项** | 是上述 17 项的子集；未以相似资料冒充直接依据 |
| 会影响已经保存的中国实验或技术产物 | **14/17 项** | 改值后至少有一组成本、排放、可行性、充电时长、车型选择、装载排程或路线结果须重算 |
| 历史 `formal` 结果家族受影响 | **8 组** | E3、E4、E5、E6、XA、XA2、XB、XC；另有 E2 v7 是 held formal-candidate |
| 当前可直接用于论文的正式实验受影响 | **0 组** | 原因不是问题轻微，而是当前事实源已经明确：当前正式实验尚未启动 |

## 2. 最危险的六项

1. **基础 China81 加载器仍是 22 kW。** `solver/src/setp_solver/china81.py:1015,1030-1035` 仍返回 22 kW 和 Montoya 22 kW 曲线。只有新的私有重建和 2026-08-12 套件在外层覆盖成 60 kW。
2. **出现“文件写 60 kW、内部仍按 22 kW 算”的实质错误。** `solver/scripts/build_private_instance_rebuild_20260811.py:68,367-370,1205-1215` 已把错误数字写进 `solver/reports/instance_rebuild_20260811/health_summary.json:20-60` 和 `solver/reports/instance_rebuild_20260811/report.md:83-90`：148.50 kWh、79.46 元、22.79 kgCO2e 均是 22 kW 口径。这组机制天花板已经作废。
3. **60 kW 只是功率中国化，曲线形状没有中国化。** `solver/src/setp_solver/charging_curve.py:86-106` 明说 60 kW 曲线来自 Montoya 构造算例的 44 kW 曲线形状缩放，不是福田 77.28 kWh 车辆或中国场站实测曲线。
4. **中国车型档案并不等于中国能耗参数。** JAC/Foton 的质量、载重、电池可追到中国厂商，但 Cd、滚阻、CMEM 发动机参数、EV 放电系数仍来自美国 EPA、Demir、Goeke，或没有直接来源；这些值已经进入评价器。
5. **车型档案中的 EV 效率字段没有接进评价器。** `solver/src/setp_solver/china81.py:789,795` 登记 `traction_energy_multiplier`，`solver/src/setp_solver/instance_loader.py:502-529` 只校验它；实际能耗由 `solver/src/setp_solver/cost.py:1109-1119` 读取 `prices.alpha_e`。两者当前碰巧同值，今后若只改车型档案，实验会“看似换源、实际不变”。
6. **燃油体系同时存在两套互相冲突的国外/倒推密度。** `solver/src/setp_solver/prices.py:34-35` 的油耗模型仍用 Goeke 的 44 kJ/g、737 g/L；`baselines/e4_e5/build_china_policy_price_gate_20260717.py:259-266` 的排放因子又用价格倒推 `6.88/(8000/1000)=0.86 kg/L`。中国陆上交通指南印刷页 15 明确给柴油密度 **0.84 t/m³**，印刷页 60 给低位热值 **43.330 GJ/t**；按该页完整排放参数计算应为 **2.6419028944 kgCO2/L**，不是当前 **2.70480534**。油耗模型与排放因子必须分别按公式口径核定，不能直接把一个密度机械抄到两个公式。

## 3. 17 项须处理问题的索引

| 编号 | 问题族 | 是否已经进入保存结果 |
|---|---|---|
| A01 | UK `DEFAULT_PRICES`、NESO 18 槽回退与英镑展示层仍可被 China 路径误用 | 未证明进入当前 China 数值；会污染复用后的默认调用或图表 |
| A02 | 九城分时电价的一手原始链接和命名场站实际价档未闭合 | 已进入 E2–E7 成本链 |
| A03 | 公共充电服务费统一 0.4 CNY/kWh 只是情景代理 | 已进入使用公共站的结果 |
| A04 | 170、0.78/0.67、0.5、1.5、跨场 0 及路线时间 0/75 等成本/收入是代理或无来源默认 | 已进入成本、车型选择与利润链；75 仅见测试、未进入保存结果 |
| A05 | 中国车型继续使用 EPA/Goeke/Demir 或无来源物理参数 | 已进入所有 China81 油耗、电耗、排放评价 |
| A06 | `traction_energy_multiplier` 与评价器 `alpha_e` 权威断线 | 当前数值相同，但国外 `alpha_e` 已进入全部含 EV 结果 |
| A07 | 0.2445 CNY/km 为“中国电池价 ÷ 国外寿命里程” | 已进入私有重建及后续含 EV 技术结果 |
| A08 | 旧参数锁 140.41 kWh 车型与活动 77.28 kWh 车型分叉 | 旧锁不能再证明活动车型；仅车队上限比对恰好不变 |
| A09 | 柴油 EF 使用价格倒推 0.86 密度，冲突中国指南 0.84 | 已进入所有 CV 排放与含碳价成本 |
| A10 | 基础 China81 加载器、旧静态权威和有限车队权威仍为 22 kW | 已进入旧 E2–E7、XA/XA2/XB/XC 的参数时代；直接失效范围是其中实际发生车场充电的保存解 |
| A11 | 当前 60 kW 仍使用 Montoya 44 kW 构造曲线形状 | 已进入 60 kW 技术包和新套件健康计算 |
| A12 | 历史正式包广泛使用无文献依据的 `NL90_mild` | 已进入 E2–E6、XA、XA2、XB、XC |
| A13 | 模型没有桩端到电池充电效率，等价于购电量=入电池量 | 已进入所有含充电动作的成本与排放 |
| A14 | 私有重建午休天花板内部仍用 22 kW | 已产生错误的技术天花板报告数字 |
| A15 | 公共站 60 kW/1 枪多为统一代理，设备身份被误读成参数证据 | 已进入使用公共站的历史结果；新 metro 仅结构构建 |
| A16 | 90 km/h Goeke 回退常量与真实逐弧矩阵不一致 | 活动有 profile 的 China81 不受它控制；旧无 profile/dynamic 回退受影响 |
| A17 | 私有/新套件用统一 7.2 m³、1735 kg 和 0.1 h/m³ 构造装载；与 EV 1700 kg 分车型权威不一致，体积和装货率无直接来源 | 已进入私有重建与新套件的装载可行性、出车时刻和健康见证；尚无当前正式搜索 |

# 二、按七类分节的逐条台账

## （一）货币与计量

| 文件路径与行号 | 当前取值或写法 | 来源判定 | 中国侧候选来源 | 是否进入正式实验、改动影响 |
|---|---|---|---|---|
| `solver/src/setp_solver/prices.py:44-76,94-150` | `DEFAULT_PRICES` 保留柴油 £1.4331/L、电价 £0.82/£0.1853、碳价 £0.05034/kg、固定成本 £80、收入 £0.18936/kg、里程成本 £0.35/km | **国外来源**；英国 2025 情景 | China81 已有 CNY 城市油价、铺在 48 行积分网格上的分时类别电价和中国成本情景。中国正式入口必须显式传 `bundle.prices` | 历史 UK/公开基准可留；未证明当前 China runner 使用英镑数值，但多个函数默认接收 `DEFAULT_PRICES`，误用会使数值完全失效。A01 |
| `solver/src/setp_solver/reporting/samples.py:127-142`；`solver/src/setp_solver/reporting/tables.py:48-49,65,75,84,88,98,107-108,121-122`；`solver/src/setp_solver/reporting/figures.py:11,357-423,478,602`；`solver/src/setp_solver/reporting/design_templates.py:236-243,395-403`；`solver/src/setp_solver/reporting/runner.py:261-265,323` | 参数表、表头、图轴、样板数据和字段名硬编码 `£`、`GBP/tCO2e`、`price_gbp_per_tonne` | **国外来源** | 中国报告应取运行元数据中的 `CNY`；不需要另找参数来源 | 不改变已保存求解值；若复用会把人民币错标为英镑。须改展示身份，旧 UK 展品原样保留。A01 |
| `solver/src/setp_solver/search/submission_contract.py:75,117-118`；`solver/src/setp_solver/search/evaluation.py:22`；`solver/src/setp_solver/search/alns_crush_v3.py:570-600`；`solver/src/setp_solver/search/winner_restoration.py:547-599`；`solver/rl/dr_alns_ppo/offline_bandit.py:1017` | 冻结合同字段、注释及旧公开轨诊断文本仍写 `gbp_per_customer`、GBP/`£` | **国外来源，但多数属于旧 UK/公开轨语义** | China81 新入口应使用带币种元数据的中性字段；历史合同和旧报告不静默改写 | 旧公开结果可留。未发现这些旧诊断脚本生成当前 China81 正式结果；复活到 China 路径会造成币种身份错误。归入 A01/K12 |
| `data/ChinaInstances/china_parameter_lock_v2_20260718.json:17-28` | CNY；m/km、kg、L、kWh、kW、s、kgCO2e、CNY/min | **中国可核来源／法定公制** | 无须替换 | 可留。活动 China81 数据未发现英里、磅、加仑等模型单位。K01 |
| `baselines/contract_audit/e1_e7_submission_contract_20260711/report.md:7`；`data/Carbon/时变碳强度/regional_carbon_intensity_2025-11-01_to_2025-11-30.csv:1-15`；`data/Carbon/电网平均排放因子或地区排放因子（US）/egrid2023_technical_guide.pdf`（PDF 第 1–2 页） | GBP、UK NESO、美国 EPA eGRID 等 | **国外来源，但身份明确的历史/国际档案** | 不应静默改写历史证据 | 未检出活动 China81 加载引用。可留作历史或对照，不得再作为 China81 参数证据。K12 |

## （二）价格体系

| 文件路径与行号 | 当前取值或写法 | 来源判定 | 中国侧候选来源 | 是否进入正式实验、改动影响 |
|---|---|---|---|---|
| `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/city_runtime_parameter_register.csv:2-10`；`solver/src/setp_solver/china81.py:130-140` | 2025-02-12 柴油 7.43–7.50 CNY/L，按城市绑定 | **中国可核来源**；北京、天津、河北、广东政府镜像、四川价格公报、重庆官方推导均登记 URL/哈希 | 可继续用相应地方发改委/政府价格资料 | 已进入 China CV 油费。只补来源不改数值不作废；数值变动会重算 CV 成本。K02 |
| `data/ChinaPrices/china_2025_02_tariff_register_v2.json:2-7,19-69,71-114`；`data/ChinaPrices/china_2025_02_tariff_register_v3.json:2-7,8-28,30-52,61-69` | 九城 1–10 kV 分时类别电价，铺在 48 行 30 分钟积分网格上；六价区主要是 `energydc.cn` 留存的电网扫描；命名场站的电压、容量、计量、利用小时、账单未知 | **中国资料内容可核，但第一手溯源与场站适用行来源不明** | 国家电网 95598、南方电网或省级发改委 2025-02 原表；命名园区报装资料/电费账单 | 分时类别价格进入 E2–E7 和私有技术结果。只补一手链接且数字不变不作废；改变价档/数值会使充电时机、成本和路线选择重算。A02/U01 |
| `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv:1-5`（全表同口径） | 公共服务费固定 0.4 CNY/kWh，字段明写 `UNIFORM_SCENARIO_PROXY_NOT_MARKET_OBSERVATION` | **来源不明／构造情景** | 各具体站点、运营商在 2025-02 的价目或订单/账单；**未找到支持九城统一 0.4 的中国可核来源** | 已进入使用公共站的货币目标。改值后这些成本结果须重算；未使用公共站的解可逐解核后保留。A03/U02 |
| `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/parameter_lock.json:21-29`；`solver/src/setp_solver/china81.py:1019,1024`；`solver/src/setp_solver/cost.py:164-179` | 固定成本 170 CNY/已使用物理车辆·规划日（跨多趟只收一次）；CV 非能源成本 0.78 CNY/km | **来源不明／情景代理** | `data/ChinaPrices/cost_proxy_snapshots_20260718/vehicle_fixed_cost_wri_light_logistics_202104.md:3-21` 的 WRI 案例只能给约 162.96 元/日资本代理；`data/ChinaPrices/cost_proxy_snapshots_20260718/vehicle_fixed_cost_yunneng_4p2_monthly_20241128.md:3-21` 的 4.2 m 新能源车 4,800–5,980 元/月只能给 160–199 元/日近邻区间；均非精确 4.5 t 账本 | 已进入车数、跨趟复用和总成本。改值可能改变路线和车数，相关历史包/技术包须重跑。A04/U03 |
| `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/parameter_lock.json:23-28`；`solver/src/setp_solver/china81.py:758,785` | CV/EV 非能源成本 0.78/0.67 CNY/km | **来源不明／复合代理** | `data/ChinaPrices/cost_proxy_snapshots_20260718/c_km_icct_tco_maintenance_202102.md:3-15` 的 ICCT 中国重卡维护 0.325/0.218 CNY/km（不是 4.5 t）；轮胎、通行费只能分项构造，不足以证明 0.78/0.67 | 已进入所有车型成本比较。改变会使混合车队、临界里程和成本结果失效。A04/U03 |
| `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/parameter_lock.json:25`；`solver/src/setp_solver/china81.py:1020` | 占位费 0.5 CNY/min | **来源不明，不能视为全国统一值** | `data/ChinaPrices/cost_proxy_snapshots_20260718/occupancy_fee_nbd_operator_observation_20250313.md:3-11` 的北京站点观察有 0.25、0.5、3.2、6.4 CNY/min；`data/ChinaPrices/cost_proxy_snapshots_20260718/occupancy_fee_xiaojukeji_official_rule_20260717.md:3-14` 只证明可配置，不能证明 0.5 通用 | 仅使用公共站且发生超时占用的结果受影响。A04/U03 |
| `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/parameter_lock.json:26`；`solver/src/setp_solver/china81.py:1022`；`solver/scripts/run_dynamic_experiment.py:1038-1071` | 收入/外包代理 1.5 CNY/kg；动态正式入口在缺批准来源时拒绝运行 | **1.5 为场景代理；正式外包单价来源不明但当前 fail-closed** | `data/ChinaPrices/cost_proxy_snapshots_20260718/revenue_per_kg_zhongkuaiyun_quote_20260717.md:3-14` 给四川 1.30–1.50、广东 1.65–1.80 CNY/kg，但只是站到站报价且 >50 kg 可议价；德邦规则等可作敏感性，不是统一成交价 | 收入进入 E6 利润/参与约束；公平关闭的技术包不受。改变会使 E6/外包比较重算。A04/U03 |
| `solver/src/setp_solver/prices.py:69-71,149`；`solver/src/setp_solver/china81.py:1021`；`solver/src/setp_solver/cost.py:200` | 跨场服务成本 `cross_site_cost=0.0`，即完全共享、无摩擦基线 | **来源不明／明确的模型基线，不是中国现实零成本观测** | 目标企业跨场调度、装卸、回空或结算账本；**未找到支持现实跨场成本恒为 0 的中国来源** | 0 已进入所有发生跨场服务的协同成本。只改披露不作废；改为非零会使 E3/E6 及其他跨场解的成本、利润、路线选择重算。A04/U03 |
| `solver/src/setp_solver/prices.py:146-147`；`solver/src/setp_solver/cost.py:194-200`；`solver/tests/test_e5_route_time_cost.py:11-30` | 路线时间价值默认 0；注释称 E5-P1 敏感性为 75 CNY/h，但活动生产入口未检出 75，仅测试使用 | **默认关闭；75 CNY/h 的中国来源不明** | 中国 4.5 t 城配车辆人工、机会成本或运营账本；**未找到 75 的直接来源** | 未证明 75 进入保存的 China 结果，默认 0 已进入总账。若正式启用非零值，会改变路线总成本和搜索排序。A04/U03 |
| `solver/scripts/run_private_rebuild_assignment_probe_pyvrp.py:2-8,29-30,93-103` | 技术探针用 1.7542 CNY/km 和 170 CNY/车的代理目标生成候选，再由精确评价器重放 | **来源不明／技术代理，不是正式价格** | 若继续使用，只能由当期已冻结的中国车型成本分解导出并记录；未找到 1.7542 的独立中国来源 | 不直接进入最终精确成本，但会改变探针产生的候选路线；相关重建健康见证不可当现实价格或正式效果。归入 A04/U03 |
| `solver/src/setp_solver/china81.py:1016-1017`；`baselines/e4_e5/china_policy_price_gate_20260717/price_scenarios.csv:2-4` | 0.07502/0.05632 CNY/kgCO2e | **中国可核来源，但只是全国碳市场成交价映射成内部影子价；不是道路物流当前法定履约成本** | 全国碳市场/上海环境能源交易所对应实验日期成交数据 | 可作为已声明的碳价情景保留。只改措辞不作废；改数值会改变含碳价总账排序。K06 |

## （三）车辆参数

| 文件路径与行号 | 当前取值或写法 | 来源判定 | 中国侧候选来源 | 是否进入正式实验、改动影响 |
|---|---|---|---|---|
| `solver/src/setp_solver/china81.py:748-755,770-782` | JAC K7：4495/2565/1735 kg；Foton ES1 快运栏板：4495/2600/1700 kg、77.28 kWh | **中国可核来源**（厂商官方配置） | [江淮威铃 K7 官方页](https://yika.jac.com.cn/wlK7/)；[福田欧马可 ES1 官方产品 PDF](https://aumark.foton.com.cn/profile/upload/2025/08/08/%E6%AC%A7%E9%A9%AC%E5%8F%AF%E6%99%BA%E8%93%8DES1%E5%8D%95%E9%A1%B5-NEW_20250808124334A003.pdf)；工信部对应公告 | 这些同一配置可核字段可留。质量、载重、电池已进入所有 China81 可行性/能耗结果。K03 |
| `solver/src/setp_solver/prices.py:26,28,41,96-117,183`；`solver/src/setp_solver/reporting/samples.py:127-130` | 共享默认车型和旧报告样板仍是 Goeke–Schneider 的 6,350 kg 整备质量、3,650 kg 载重、80 kWh 电池和 22 kW | **国外公开基准参数；在原 Goeke 基准轨可保留，不是中国车型/车场证据** | China81 已有 JAC/Foton 分车型质量、载重、77.28 kWh 电池和 60 kW 新情景；不应为公开基准反向改值 | 活动 China81 的车型档案和实例电池会覆盖这些回退值，未发现其进入当前 profiled China81 数值；绕过实例权威或复用旧样板时会误用。K11 |
| `solver/src/setp_solver/china81.py:754,776-781,792-794` | 迎风面积 `0.85×2.2×2.48`；Foton 缺高度，借用 JAC 2.48 m；投影系数 0.85 | **来源不明／跨车型假设** | 同一 Foton 77.28 kWh、1700 kg 配置的工信部公告/OEM 外廓尺寸；投影系数需 OEM 风洞或可核试验资料。**未找到直接中国来源** | 面积进入 CV/EV 机械能。改值会使全部能耗、排放、成本结果重算。A05/U04 |
| `solver/src/setp_solver/china81.py:756-767,783-795`；`solver/src/setp_solver/prices.py:22-40`；`solver/src/setp_solver/cost.py:949-958,1006-1018,1103-1119` | Cd=.45 来自美国 EPA SmartWay Class 2B；China 档案仍继承 Goeke/Demir 的空气密度 1.2041、Cr=.01、发动机/燃料参数 0.2、1、.9、.4、44 kJ/g、737 g/L、33、5 L，以及 EV 系数 1.184692×1.112434 | **车辆/燃料标定为国外来源；空气密度是国际模型环境条件，可披露保留但不是九城实测** | 精确车型的工信部/交通运输部油耗数据库、OEM 滑行/风洞/台架资料；中国柴油候选为 `data/Carbon/中国情景/raw_20260717/NDRC_land_transport_GHG_guideline.pdf` 印刷页 15 的 0.84 t/m³、印刷页 60 的 43.330 GJ/t，但必须按 CMEM 公式口径整体校准，不能机械替换；测试方法候选为 [GB/T 27840-2021](https://std.samr.gov.cn/gb/search/gbDetailed?id=CE1E6A1DD5B458F6E05397BE0A0A68DF) 和 [GB/T 18386.2-2022](https://std.samr.gov.cn/gb/search/gbDetailedCNF?id=EB58F4DA91C9B2A2E05397BE0A0A7D33) | 这些量直接进入每条弧的机械能、油耗或电耗；尤其 737 g/L 与排放因子所用 0.86 kg/L、官方 0.84 kg/L 三套口径并存。更换会使所有 China81 成本、排放、车型选择和搜索结果失效。A05/U05 |
| `solver/src/setp_solver/china81.py:789,795`；`solver/src/setp_solver/instance_loader.py:502-529`；`solver/src/setp_solver/cost.py:1103-1119` | 车型档案有 `traction_energy_multiplier`，实际评价读取 `prices.alpha_e`；`_china_prices()` 未覆盖 `alpha_e` | **默认值与实际调用不一致；当前两处碰巧都是 Goeke 数值** | 同一车型 GB/T 18386.2-2022 试验或可核能耗数据；落值时必须核对评价器真实权威 | 国外 `alpha_e` 已进入全部含 EV 的 China 结果。只改车型档案不会改变结果；真正换值后所有含 EV 结果须重算。A06/U05 |
| `solver/src/setp_solver/private_instance_rebuild_20260811.py:44,158-167`；`data/ChinaInstances/china81_private_rebuild_v1_20260811/vehicle_costs.csv:1-3`；`solver/scripts/build_private_instance_rebuild_20260811.py:1417` | 电池折旧 0.2445 CNY/km = 长江证券 59,000 CNY ÷ Goeke 241,350 km | **中国价格与国外构造寿命混合；典型旧中国化残留** | 同一中国 4.5 t 车型/电池体系的质保、循环寿命、车队退役里程或中国 TCO 研究；**未找到可核的中国寿命里程** | 已进入私有重建、mechanism validation、search budget diagnosis。改变后 EV 成本、临界里程、车型选择及交互结果须重算。A07/U06 |
| `solver/src/setp_solver/private_instance_rebuild_20260811.py:45,343-346`；`solver/scripts/build_private_instance_rebuild_20260811.py:1418` | EV 固定溢价 50 CNY/车日，取陈婉茹等 2023 第 5 节/表 7 的 550−500 | **中国文献来源；其“实证还是论文情景”须按原文身份披露** | 陈婉茹等（2023）《系统工程理论与实践》43(11):3320–3335，第 5 节、表 7 | 可作为中国文献情景保留；若原文只是构造参数，不得写成实测成本。改数值会使含 EV 结果重算。K05 |
| `data/ChinaInstances/china_parameter_lock_v2_20260718.json:55-101`；`solver/src/setp_solver/china81.py:770-795` | 旧锁是 ES1·140 厢式 140.41 kWh、3300/1000 kg；活动代码是 ES1 快运栏板 77.28 kWh、2600/1700 kg | **默认值与实际权威分叉** | 活动车型同一配置的福田官方页/工信部公告，不得从 140.41 kWh 邻近变体补高度 | 旧锁不能再作为活动车型来源。车队权威 v1/v2 现有容量上限逐位相同，单纯修锁不作废该上限；车型参数改变则全部含 EV 结果重算。A08 |
| `solver/scripts/build_private_instance_rebuild_20260811.py:66-67,423-424,634,727,1205`；`solver/scripts/build_china81_suite_rebuild_20260812.py:101-103,1166-1168,1273,1693,2097-2099`；`solver/src/setp_solver/private_instance_rebuild_20260811.py:287-296`；代表性产物 `data/ChinaInstances/china81_suite_v3_20260812/instances/cn-prd-50c-01-V3-TWO-SHIFT-FS/shift_contract.json:7,30-31` | 统一体积容量 7.2 m³、载重 1735 kg、装货率 0.1 h/m³；1735 是 JAC CV 载重，但 Foton EV 的活动权威是 1700 kg | **默认值与实际不一致；7.2 m³ 和 0.1 h/m³ 来源不明** | 精确所选厢体/栏板车型的 OEM 或工信部货厢尺寸；同类中国配送场站装货作业记录。**未找到能直接证明 7.2 和 0.1 的中国来源** | 私有运行时以 7.2 拒绝超容路线；两个构造器用三项值做装箱、出车时刻、车辆链和午休充电窗口。私有重建及 suite health/witness 须按获批口径重建；新套件正式搜索为 0。A17/U10 |
| `data/ChinaInstances/china81_suite_v3_20260812/vehicle_cost_contract.json:2-13` | 复制 0.78、0.67、0.2445、170、220，但没有 source/provenance 字段 | **来源不明；隐藏了 0.2445 的国外寿命分母** | 直接绑定上游来源和参数身份；数值来源同上 | 新套件 `formal_search_evaluations=0`，目前无正式结果作废；未来直接加载会把旧依据带入。归入 A04/A07/A08 |

## （四）排放体系

| 文件路径与行号 | 当前取值或写法 | 来源判定 | 中国侧候选来源 | 是否进入正式实验、改动影响 |
|---|---|---|---|---|
| `solver/src/setp_solver/china81.py:1018`；`baselines/e4_e5/build_china_policy_price_gate_20260717.py:259-266` | 柴油 EF=2.70480534 kgCO2/L；密度由 6.88 CNY/L ÷ 8000 CNY/t 倒推 0.86 kg/L | **中国公式输入 + 无效的价格倒推密度；当前值依据错误** | `data/Carbon/中国情景/raw_20260717/NDRC_land_transport_GHG_guideline.pdf` 印刷页 15 给柴油 0.84 t/m³，印刷页 60 给 43.330 GJ/t、20.20×10^-3 tC/GJ、98%；同口径结果 2.6419028944 kgCO2/L。现行标准候选为 [GB/T 32151.27-2024](https://std.samr.gov.cn/gb/search/gbDetailed?id=25940C3CEF2D8A9AE06397BE0A0A525A) | 已进入全部 CV 排放和含碳价成本。排放列必重算；若含碳价目标参与搜索，路线/车型结果也可能作废。A09 |
| `solver/src/setp_solver/cost.py:39-45,73-107,431-485,596-663,700-755,1190-1206` | 共享碳槽默认仍写 NESO、2025-11-13 UTC、18 个半小时槽；China81 使用 48 行 30 分钟积分/容量网格，但外生碳只有 24 个逐小时值 | **国外历史回退；默认值与 China 实际取数不一致** | China81 已按中国日历传入真实 profile 长度，不需要另造中国统一槽数 | 当前 China 成本链显式传 `len(profile)=48`，且日期常量除定义外未被使用，所以只改注释/身份不作废既有数值；无 profile 或省略 `n_slots` 的非循环复用路径会退回 18 槽，并可能在第 9 小时后截断或拒绝动作。归入 A01 |
| `data/ChinaInstances/china_parameter_lock_v2_20260718.json:186-210`；`data/Carbon/中国情景/cef_dataset_full_20260731/download_manifest.json:2-17,18-94` | 2025–2060 省级逐时 CEF，Figshare DOI 10.6084/m9.figshare.28953545.v3，论文 DOI 10.1038/s41597-026-07272-6 | **中国可核学术数据；是模型投影/模拟，不是官方实时实测** | 若只需年度官方因子，可用生态环境部购电因子；它没有逐时变化，不能替代时变机制数据 | 可作为明确的中国模拟时变数据保留。改数据会使 E2 排放、E4 碳时序、E7/XC 动态排放重算。K07 |
| `solver/src/setp_solver/prices.py:30-40,80-89`；`solver/src/setp_solver/cost.py:883-900,965-1021` | CMEM/Goeke 机械功率与油耗结构 | **国际通行模型结构，可保留；车辆特定标定值不能冒充中国实测** | 不需把公式结构“中国化”；只应对输入参数另行找中国证据或声明迁移 | 结构本身不要求作废实验；若更换标定参数则所有油耗/排放重算。K09 |
| `baselines/e4_e5/china_policy_price_gate_20260717/price_scenarios.csv:2-4` | CEA 价格用作内部影子价 | **中国可核情景，非道路物流法定履约成本** | 对应日期全国碳市场官方成交数据 | 可留，身份须准确。见价格类 K06。 |

## （五）充电体系

| 文件路径与行号 | 当前取值或写法 | 来源判定 | 中国侧候选来源 | 是否进入正式实验、改动影响 |
|---|---|---|---|---|
| `solver/src/setp_solver/china81.py:1015,1030-1035`；`data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/facilities.csv:2-10`；`data/ChinaInstances/china81_finite_fleet_authority_v3_20260802/fleet_caps.csv:2-20` | 基础 China81、旧静态权威和车队权威仍是 22 kW；来源标签为统一计划容量代理 | **国外来源/错误主值**；不是中国物流园实测 | 咸宁市发改委《新能源汽车充（换）电设施专项规划（2022–2035年）》印刷页 84：60 kW 一机一枪直流桩适用于物流园及小型物流车；规划中实际场站清单可按印刷页 23 复核 | 旧 E2–E7、XA/XA2/XB/XC 属 22 kW 参数时代；其中实际发生车场充电的保存解须重算，其余全 CV、无充电或只用公共站的解不能仅凭功率变化判作废，须逐解核查。基础 loader 继续误用的风险仍在。A10 |
| `data/ChinaInstances/china81_suite_v3_20260812/metadata.json:2-13`；`solver/src/setp_solver/private_instance_rebuild_20260811.py:64-72,103-136` | 新私有/新套件默认 60 kW；22 kW 保留可选 | **60 kW 为中国可核场景；22 kW 只能作为国外历史敏感性** | [咸宁市规划原文](https://fgw.xianning.gov.cn/xxgk/fdzdgknr/ghjh/202301/P020250303636637394908.pdf)，印刷页 84；命名园区实际设备仍需各站证据 | 新套件只有构建健康检查、正式搜索 0；60 kW 可留。可选 22 kW 必须保持“国外/历史对照”身份。K04 |
| `solver/src/setp_solver/prices.py:57,117`；`solver/src/setp_solver/china81.py:1004`；`solver/src/setp_solver/check.py:1014-1060`；`solver/src/setp_solver/search/charging.py:93-136` | EV 在车场预充电前的初始电量 `initial_ev_battery_kwh=0.0`；随后由车场充电动作增加电量 | **中国可核文献中的建模约定，不是中国企业车队班前 SOC 实测值** | 黄志红、黄卫来、郭放（2024）《考虑电池损耗的电动物流汽车充电设施选址与充电策略协同优化研究》，《中国管理科学》32(6):68–78，期刊印刷页 70 式(15)–(16)，DOI `10.16381/j.cnki.issn1003-207x.2021.1636`，[原文 PDF](https://www.zgglkx.com/CN/article/downloadArticleFile.do?attachType=PDF&id=19208) | 已进入全部含 EV 车场充电的 China 结果。若只改正来源身份和披露措辞，旧数值不作废；若把 0 改成其他初始电量，则车场预充时长、电价/碳槽位、成本、可行性及所有含 EV 结果须重算。K13 |
| `solver/src/setp_solver/charging_curve.py:86-106`；`solver/src/setp_solver/china81.py:1025-1042` | 60 kW 使用 `M17_FAST_SHAPE_SCALED_60KW_PWL`，0/85/95/100% SOC，来自 Montoya Fig.8 44 kW 形状缩放 | **国外构造算例曲线，不是中国 77.28 kWh 车实测** | 该 Foton 配置与 60 kW 直流桩组合的 OEM 试验/充电日志；**未找到可核中国 SOC—功率曲线** | 已进入 60 kW 接线、suite health、后续技术运行。改变曲线会改变充电时长、可行性、电价/碳槽位与搜索结果。A11/U07 |
| `solver/src/setp_solver/charging_curve.py:78-83`；`baselines/china_e3_e7/e5_nonlinear_final_20260730/charging_sessions.csv:2-12` | `NL90_mild`：0–90% 额定功率、90–100% 半功率，无文献注释；历史正式会话保存 22/60 kW | **来源不明／人工构造曲线** | **未找到中国可核来源**；如保留只能称预注册构造对照 | 已进入 E2、E3、E4、E5、E6、XA、XA2、XB、XC 历史包。换曲线后相关数值结果均失效。A12/U07 |
| `solver/src/setp_solver/charging_curve.py:24-75`；`solver/src/setp_solver/solution.py:37-46`；`solver/src/setp_solver/cost.py:565-663,1157-1213` | 无“桩端购电→电池入电”效率字段；`action.energy_kwh` 同时用于 SOC、电费和间接排放，等价于 100% | **来源不明／参数缺失** | 精确车型+桩的计量日志、OEM/型式试验；**未找到可直接支持具体中国效率数值的来源**，技术标准名称不能代替效率实测 | 已进入所有含充电动作的结果。引入效率会改变购电量、成本、排放，且可能改变时长/可行性定义，须重算。A13/U08 |
| `solver/scripts/build_private_instance_rebuild_20260811.py:68,367-370,1205-1215,1253-1279`；`solver/reports/instance_rebuild_20260811/health_summary.json:20-60`；`solver/reports/instance_rebuild_20260811/report.md:83-90` | 设施写 60 kW，午休上限却用常量 22 kW；每车 29.7 kWh，总 148.50 kWh，省 79.46 元、少 22.79 kg | **默认值与实际不一致；已产生错误数字** | 同一 60 kW 登记曲线的分段积分；`solver/reports/depot_power_60kw_20260811/report.md:63-82` 已给 76.8 min 从 0 起可达 70.651 kWh 的独立技术读数，但本审计不代替正式重算 | 不是正式搜索结果，但该机制天花板和设计依据作废。A14 |
| `data/ChinaInstances/china81_stage2_static_inputs_corrected_v3_20260723/facilities.csv:2-10`；`data/ChinaInstances/china81_suite_v3_20260812/facilities.csv:2-10`；`data/ChinaInstances/china81_metro_suite_v1_20260812/station_parameter_assignments.csv:1-12`（全表 2,501 条同一证据口径） | 九城公共站统一 60 kW/1 枪；多数 OSM 只证明位置/标签；石家庄 Tesla 实际页列 6 桩、最高 119 kW，模型仍为 60/1；metro 表又把代理赋值写成 `evidence_class=FACT` | **来源不明；部分默认值与已知设备信息不一致；证据身份易被误读** | 各站运营商设备页、政府备案、现场铭牌/账单；**未找到八站的功率/枪数直接证据** | 使用公共站的历史结果须重算；未访问公共站的解可逐解核后保留。新 metro 套件正式搜索 0，当前只需重建来源身份/健康产物。A15/U09 |

## （六）速度与路网

| 文件路径与行号 | 当前取值或写法 | 来源判定 | 中国侧候选来源 | 是否进入正式实验、改动影响 |
|---|---|---|---|---|
| `solver/src/setp_solver/prices.py:29,90`；`data/ChinaInstances/china81_suite_v3_20260812/instances/cn-prd-50c-01-V3-TWO-SHIFT-FS/matrix_reference.json:2-37`；`data/ChinaInstances/china81_suite_v3_20260812/instances/cn-prd-50c-01-V3-TWO-SHIFT-FS/source_mapping.csv:1-55` | 固定 25 m/s = 90 km/h，来自 Goeke PRP 上限 | **默认值与实际不一致** | 活动 China81 直接使用冻结逐弧距离/时长；不应再用一个“全国真实均速”替换另一个常量 | `solver/src/setp_solver/instance_loader.py:186-210` 在有 road profile 时不使用 90。对该 54 节点广佛实例引用的 CV 矩阵做只读复算：2,862 条正弧的弧速简单均值 51.269 km/h、总距离/总时间 57.445 km/h；逐弧速度并不是统一的 54.8，也明显不是 90。只改回退值不会改变活动 profiled 结果。A16 |
| `solver/src/setp_solver/instance_loader.py:180-210`；`solver/src/setp_solver/cost.py:309-330,1041-1055,1103-1119` | 有 profile 时读取同路径 distance、duration、Σ(v²d) | **中国真实路网场景可核** | 无须中国化替换；继续保留冻结矩阵、图和哈希 | 活动 China81 正确路径。重路由会使所有路线可行性、能耗、成本和搜索结果重跑。K08 |
| `data/ChinaInstances/china81_local_directed_matrices_corrected_v10_20260723/metadata.json:2-30` | OSRM 26.7.3、1,578,948 有向点对、无欧氏/对称回填、同路径三矩阵 | **可核的国际工具+中国坐标/路网** | 无须把 OSRM 换成中国软件 | 可留。国际开源路由器不属于该中国化的参数。K08 |
| `solver/src/setp_solver/search/dynamic.py:2180-2203`；`solver/src/setp_solver/instance_loader.py:186-198` | 无 road profile 时用 90 km/h 生成时长/夹时间窗 | **国外回退值** | 中国动态流应继续携带真实逐弧 profile；未找到可作为九城统一默认速度的中国来源 | 当前 `solver/src/setp_solver/potential_pool_dynamic.py:838-843` 使用 profile；旧 E7/无 profile 路径若复活须判旧口径失效。A16 |
| `solver/reports/metro_rebuild_20260812/metadata.json:8-20,28-35` | `clip_sha256`、`osrm_version` 为 `UNKNOWN`，但图 manifest 有哈希 | **复现元数据不完整，不是数值中国化问题** | 冻结图 manifest/OSRM 构建记录 | 正式搜索 0；补元数据且不重路由不作废。若无法证明同图而重路由，未来矩阵不能与旧值混用。 |

## （七）标准引用

| 文件路径与行号 | 当前取值或写法 | 来源判定 | 中国侧候选来源 | 是否进入正式实验、改动影响 |
|---|---|---|---|---|
| `solver/src/setp_solver/china81.py:763-768,790-796` | `CD_0.45_EPA_SMARTWAY_CLASS2B_SCENARIO`；Demir/Goeke transfer | **美国/欧洲学术来源** | 精确车型实测；方法候选 GB/T 27840-2021、GB/T 18386.2-2022 | 这些是数值标定，不是仅补引用；换值会使全部能耗/排放结果重算。A05 |
| `solver/` 活动 China81 参数全量检索 | 未发现 GB/T 27840、GB/T 18386.2、GB/T 32151.27 等国标直接绑定活动数值 | **来源不明；“没有欧美标准”不等于“已有国标依据”** | 车辆油耗/电耗方法：GB/T 27840-2021、GB/T 18386.2-2022；陆上交通温室气体：GB/T 32151.27-2024；充电设施设计可参考 GB/T 50966-2024，但它不规定统一物流园功率 | 只补规范性引用不作废；若按标准换了数值/边界则相应重算。U05/U08 |
| `solver/src/setp_solver/prices.py:7-41`、`solver/src/setp_solver/charging_curve.py:86-106` | Goeke/Demir/CMEM、Montoya | **国际模型/公开基准可以保留；国外标定值不能冒充中国实证** | 不要求把模型公式改成“国产公式” | CMEM 结构与公开基准可留；Montoya 曲线只能作明确的文献迁移/敏感性。K09/K11 |
| `third_party/setp_hgs_kernel/README.md:3-25`；`solver/src/setp_solver/algorithms/problem_hgs/PROVENANCE.md:7-17` | PyVRP 0.12.2/HGS 内核、MIT 许可和适配层分界 | **本就该国际化** | 无须中国化 | 属算法结构，不是场景参数。可留。K10 |
| `third_party/hgs-cvrp/README.md:3-10`；`third_party/harvested_operators/pyvrp_v0.12.2/ORIGIN.md:3-27` | 官方 HGS-CVRP 强控制、PyVRP 操作子原样材料 | **本就该国际化** | 无须中国化 | 公开控制/血统材料可留，不影响 China 参数。K10/K11 |
| `solver/src/setp_solver/algorithms/problem_hgs/frvcpy_adapter.py:177-224,249-252` | FRVCP 上游算法；适配器从项目 bundle 取矩阵、功率、曲线、电池 | **国际算法结构，接入方式正确** | 无须中国化 | `solver/reports/frvcpy_integration_20260811/on_shortest/decision.json:2-17` 仅技术接入，不是正式效果实验。可留。K10 |

# 三、“改了会作废哪些已有实验”的影响清单

## 1. 已经确定需要作废或重算的保存结果

| 结果家族 | 保存证据 | 受影响参数 | 影响结论 |
|---|---|---|---|
| `solver/reports/instance_rebuild_20260811` | `solver/reports/instance_rebuild_20260811/report.md:83-90`；`solver/reports/instance_rebuild_20260811/health_summary.json:20-60` | A14：内部 22 kW | 148.50 kWh、79.46 元、22.79 kgCO2e 天花板作废；结构性的客户、趟次、车数见证不因这一个错误自动作废 |
| 私有重建与 `china81_suite_v3_20260812` 健康见证 | `solver/scripts/build_private_instance_rebuild_20260811.py:634,727,1205`；`solver/scripts/build_china81_suite_rebuild_20260812.py:1166-1168,1273,1693` | A17：7.2 m³、统一 1735 kg、0.1 h/m³ | 装箱、车辆链、出车时刻和午休可充电时间须按获批容量/装货率重建；新套件尚无正式搜索结果 |
| `solver/reports/mechanism_validation_v3_20260811` | `solver/reports/mechanism_validation_v3_20260811/report.md:21-26,32-50` | 22 kW/M17 曲线；Goeke EV 能耗；0.2445 成本 | 四种固定充电策略的时长、电费、排放表不能作为 60 kW 主情景；含 EV 的方向短测若换车辆/成本参数也须重跑 |
| 历史 E5 非线性正式 40 单元 | `baselines/china_e3_e7/e5_nonlinear_final_20260730/report.md:5-15`；`baselines/china_e3_e7/e5_nonlinear_final_20260730/charging_sessions.csv:2-12` | 22 kW、`NL90_mild`、100%效率、车辆能耗 | 充电时长、可行性、成本端点作废 |
| 历史 E4 联合路径/碳面板 | `baselines/china_e3_e7/e4_joint_routing_20260801/formal_panel_20260801/decision.json:24-35`；保存解含 22 kW 充电 | 22 kW、曲线、CEF、柴油 EF、车辆参数 | 排放/含碳价成本以及含充电解的可行性须重算 |
| 历史 XA 算法比较 | `baselines/china_e3_e7/formal_algorithm_20260802/decision.json:1`，80 个运行 | 保存解含 22 kW、`NL90_mild`、77.28 kWh | 旧目标值、可行性和算法比较不能迁移到修正参数 |
| 历史 XA2 200c 消融 | `baselines/china_e3_e7/formal_ablation_200c_20260803/decision.json:1`，30 个运行 | 同上 | 旧三臂相同目标值属于旧参数时代；参数改变后须重跑，不能只换报告数字 |
| 历史 XB 五档车队 | `baselines/china_e3_e7/formal_fleet_levels_20260802/decision.json:23-24` | 22 kW、曲线、车辆能耗、成本 | 含 EV 档位作废；全 CV 档位不受充电功率直接影响，但受柴油 EF/CMEM/成本改变影响 |
| 历史 XC 动态调度 | `baselines/china_e3_e7/formal_dynamic_dispatch_20260802/decision.json:2-24` | 功率、曲线、车辆能耗、固定成本、CEF | 冻结事件状态、充电动作、成本和排放不可继续比较 |

## 2. 需要按参数逐项重算的历史包

| 历史包 | 当前保存身份 | 何时作废 |
|---|---|---|
| E3 正式客户归属面板 | `baselines/china_e3_e7/e3_scattered_ownership_20260801/formal_panel_solomon_i1_20260801/panel_summary/decision.json:64-76`，60 配对/120 行 | 改车辆能耗、固定/里程成本、柴油 EF 或电价后重算；22 kW 只对实际发生充电的保存解有直接影响 |
| E6 承运商参与面板 | `baselines/china_e3_e7/e6_contractor_participation_20260801/formal_e6a_panel_20260801/panel_decision.json:1-32`：60 正式单元、900 联盟记录 | 改收入 1.5、成本代理、车辆参数、充电参数后重算 |
| E2 v7 | `baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/full_witness_replay/decision.json:1-16`：405 任务、1620 完整解；`baselines/e2_final_campaign_20260720/corrected_china81_rerun_v7_small_archive_ledger_20260724/result_strength_gate/decision.json:27-51`：`paper_strength_pass=false`、held formal-candidate | 任一活动价格、CEF、车辆、22 kW/曲线改动后旧数值作废；它本来就不是当前可入文结果 |
| E4 carbon timing 固定解重放 | `baselines/china_e3_e7/e4_carbon_timing_20260729/metadata.json:2-13,39-55`：405 个已有解、零搜索固定方案复算 | CEF 或充电时长改变时，排放与时序窗口须重算；不能只保留旧排放列 |

## 3. 不会因为本次中国化问题自动作废的内容

- 当前 `china81_suite_v3_20260812`、metro、depot-pair、prd-fix 等是算例构建/结构健康包，正式搜索评价为 0。价格或曲线改变不会否定其真实坐标、客户身份和路网哈希，但涉及容量、装货排程、能耗、临界里程和充电天花板的健康列须重算。
- `solver/reports/depot_power_60kw_20260811/minimal_run_endogenous` 保存解为全 CV，只证明 60 kW 接线可以加载；它本来不证明充电效果。
- 使用同一路网矩阵的纯几何距离、时间窗身份、客户覆盖和需求量证据，不因价格变化自动作废。
- 公开 Solomon/Goeke/MDVRPTW 基准和国际算法强控制不因 China81 参数修正作废。

# 四、未找到中国来源因而只能如实披露的清单

1. **命名物流园实际电价合同。** 未找到九个命名场站在 2025-02 的实际电压、报装容量、计量方式、利用小时和账单；现价档只能称预注册场景。
2. **九城统一公共充电服务费 0.4 CNY/kWh。** 未找到统一中国实证；必须称情景代理。
3. **精确 4.5 t 城配车成本。** 未找到能同时证明固定成本 170、CV/EV 非能源成本 0.78/0.67、占位费 0.5、收入/外包 1.5、现实跨场成本恒为 0 或路线时间价值 75 CNY/h 的同口径中国账本。
4. **Foton 77.28 kWh、1700 kg 配置的精确高度和 0.85 迎风投影系数。** 不得用 140.41 kWh 邻近配置或 JAC 高度补齐。
5. **JAC/Foton 精确车型的 Cd、Cr、CMEM 发动机/燃料标定和 EV 放电效率。** 当前 44 kJ/g、737 g/L 也属于 Goeke 口径；国标或官方指南可提供方法与燃料参数，不能替代整车标定。
6. **中国同车型电池寿命里程。** 当前 241,350 km 是 Goeke–Schneider 国外算例依据；未找到可核中国替代值。
7. **Foton 77.28 kWh 车辆配 60 kW 直流桩的 SOC—功率曲线。** 当前曲线是 Montoya 44 kW 构造曲线形状迁移。
8. **桩端到电池的充电效率。** 未找到能直接支持一个具体数值的同车同桩中国实测；当前模型等价于 100%。
9. **八个公共站的实际功率和枪数。** OSM 身份不能证明 60 kW/1 枪；石家庄已有页面信息反而与统一 60/1 不同。
10. **私有/新套件的 7.2 m³ 车辆体积容量和 0.1 h/m³ 装货率。** 未找到同一所选车型和中国配送场站的直接依据；1735 kg 又只对应 CV，不能作为 EV 的统一载重。

# 五、本就该保持国际化、不应中国化的清单

1. **公开基准算例及其原协议。** Solomon、Goeke–Schneider、公开 MDVRPTW/EVRPTW 的坐标、单位、车辆和原始参数应原样保留；只须与 China81 结果分轨。
2. **HGS/PyVRP 搜索内核。** PyVRP 0.12.2、HGS-CVRP 强控制、Vidal 操作子是算法与复现血统，不是中国现实参数。
3. **FRVCP 算法结构。** 适配器已经从 China bundle 读取本项目矩阵、功率、曲线和电池；不应把国际算法本身替换成“中国算法”。
4. **CMEM/机械功率的数学结构。** 国际通行模型可以保留；应中国化或透明披露的是车型特定输入，不是为了形式改公式。
5. **OSRM/OSM 路由工具。** 国际开源工具配中国坐标、冻结中国路网和可复核哈希是合理组合；不需要换成国产工具才算中国化。
6. **历史 UK/US 碳、价格和 GBP 产物。** 它们应保持原始证据身份，不应静默篡改；边界是不得再作为 China81 当前参数来源。
7. **Montoya 曲线作为国际文献迁移/敏感性对照。** 可以保留，但必须明确是国外构造曲线，不能称中国实测主曲线。

## 只读完整性证明

任务开始与报告写完前复核的三个受保护文件 SHA-256 如下；最终交付前再次核对，三者必须与本表一致：

| 文件 | SHA-256 |
|---|---|
| `solver/src/setp_solver/cost.py` | `ad5b360dd255c7c4c975074a6eb3ad5e31354c2eaf7399af288670396140ccd1` |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` |

本审计不提出重构方案；所有候选来源只用于说明“若用户批准替换，应向哪里取证”。
