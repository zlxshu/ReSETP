SLOTDATE_DONE

# China81 时段语义与日期锚点对齐审计

审计日期：2026-08-12  
工作目录：`/Volumes/移动硬盘（512G）/ReSETP`  
任务边界：本轮只做全仓检索、语义判定、现行文字/图表标注修正、加载器防再犯断言和定向单测；没有运行求解器或实验，没有重建 81 例，没有改写 v3/v4 运行参数日历，也没有改动三个受保护文件。

本报告使用四种标签：`FACT` 为当前文件或已保存结果直接支持；`CORRECTION` 为对旧说法的更正；`DECISION` 为本报告建议、不是新的用户决定；`UNKNOWN` 为本轮证据不足。

## 一、时段语义逐处台账与已做的标注修正

### 1.1 结论

`CORRECTION`：China81 的“48 槽”不是全假，也不能整体删成 24 槽。准确拆分如下：

1. **碳强度的信息分辨率是逐小时**：每天只有 24 个省级投影值；每个小时值原样复制到两个相邻的 30 分钟行。48 行没有制造出 48 个独立碳强度观测。
2. **电价的信息分辨率是分时类别**：八城为谷/平/峰三类，石家庄另有尖峰，共四类；类别值按政策时段铺到 48 个 30 分钟行。它既不是 48 个独立观测，也不宜笼统称作“逐小时电价”。石家庄尖峰见 `data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723/tariff_carbon_hourly_calendar.csv:2722-2729`，上游规则见 `baselines/china_instances/build_china_stage2_static_inputs_20260718.py:35-50,150-188`。
3. **公共服务费、柴油价和碳价没有日内分辨率**：服务费是日内恒定的 0.4 元/kWh 代理；柴油价是城市—日期参数；碳价是场景标量。它们只为联合结算方便而重复出现在半小时行中。
4. **30 分钟计算网格是真实模型语义**：充电量按实际会话跨 1800 秒边界分摊，公共/车场价格和碳强度按槽积分，充电桩共享容量也按半小时检查。因此正确名称是“48 个 30 分钟存储、积分与容量槽”，不是“48 个独立外生信号值”。受保护评价器的现行积分入口见 `solver/src/setp_solver/cost.py:1151-1217`；容量检查和充电时序还分布在 `check.py`、`charge_timing.py`、`search/charging.py`、`charging_curve.py`、`algorithms/problem_hgs/schedule_oracle.py` 与 `search/dynamic_multitrip_schedule.py`。

本轮对包含 `48slot`、`48槽/48时段`、`半小时槽/时段/碳/电价` 的文本做了全仓扫描。扫描时命中 821 份文本文件；其中绝大部分是封存实验包、历史合同、报告副本或相同字段的重复保存，不能把每个副本误计成一个独立语义问题。以下按“活动入口—生成链—历史封存—同词异义”归并，覆盖所有命中家族。

### 1.2 逐处语义台账

| 位置或文件家族 | 现在真实分辨率 | 正确表述 | 本轮处理 |
|---|---|---|---|
| `data/Carbon/中国情景/cef_dataset_full_20260731/CEF_data_Scenario_S1.xlsx`；来源身份见同目录 `download_manifest.json:15-17,29-37` | 省级逐小时情景投影；不是官方实时实测 | “2025 年省级逐小时投影的平均用电碳强度” | 数据未改；当前正文和表注已按此披露 |
| `baselines/e4_e5/audit_china_tvci_source_gate_20260717.py:319-340`；`solver/tests/test_china_tvci_source_gate_20260717.py:70-85`；`tvci_2025_48slot_wide.csv` 等 | 24 小时值经零阶保持成为 48 行；每日积分保持 | “逐小时值复制到两个相邻 30 分钟存储行” | 生成器/测试本来已表达复制合同，保留；历史文件名不改 |
| v3、v4 的 `tariff_carbon_hourly_calendar.csv`；字段 `hourly_calendar_row`、`minute_of_day`、`time_index` | 联合存储、积分和容量定位键为 48 行；碳只有 24 个独立小时值 | “48 行存储表示；碳每小时内恒定” | 正式数据、字段名、文件名和哈希未改；由加载器注释与断言消歧 |
| `solver/src/setp_solver/china81.py:933-1074` | 强制每城每天 1…48 完整网格；相邻碳槽必须相等 | “48 是计算网格合同，不是源分辨率” | 在 `:1045-1074` 新增注释和失败关闭断言；任一相邻槽被写成独立碳值即拒绝加载 |
| `solver/tests/test_china81_bundle_20260720.py:569-657` | 负例故意只改变第 2 槽 | 防止后来者把半小时行当独立碳值 | 新增定向回归测试；原 48 行完整性测试继续保留，因为它检查网格完整性 |
| `data/ChinaPrices/china_2025_02_tariff_register_v2.json:2-7,71-114`；`build_china_stage2_static_inputs_20260718.py:35-50,150-188` | 分时类别；八城三类、石家庄四类 | “分时类别价铺入 48 个 30 分钟积分行” | 当前论文、参数表壳、中国化审计和事实源中的“48 槽电价/均值”已修正 |
| `public_service_fee_cny_per_kwh`、`diesel_price_cny_per_l`、`CHINA81_CARBON_PRICE_CNY_PER_KG` | 服务费日内常数；柴油为城市—日期值；碳价为场景标量 | 不称“半小时时变值”；只说为结算随行保存 | 数据未改；K4 的实际评价链见第四节 |
| `cost.py`、`check.py`、`charge_timing.py`、`search/charging.py`、`charging_curve.py`、`schedule_oracle.py`、`dynamic_multitrip_schedule.py` | 真实 30 分钟能量积分、候选起点和共享容量网格 | “30 分钟积分/容量槽” | 语义本来正确；受保护文件不改，其他位置只登记，不把网格压成 24 小时 |
| `solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py:862-870` | 在 30 分钟候选起点上选逐小时碳值；相邻两个起点通常并列 | “最低逐小时碳强度对应的 30 分钟积分网格起点” | 已改 docstring，不改算法行为 |
| `solver/scripts/run_problem_hgs_private_technical.py:1589-1623` 的 `old_48_slot_mean_cny_per_kwh` | 48 个等时长行的日均；对分时类别价等价于按持续时间加权的日均价 | “全日分时类别价的时长加权均值” | 为兼容已保存 JSON 不改字段名；在代码旁加注释，并同步修正当前事实源表述 |
| `docs/paper_gci_dmm_vrp_20260804/paper_main_foundation_v2_20260812.md:253,303` | 中国碳逐小时，价为类别阶梯，充电量按 30 分钟汇总 | 图横轴可用 30 分钟，但图注必须分别披露三种分辨率 | 已修正文和图 4 占位文字 |
| `figure_shell_spec_20260812.md:43`、`table_shells_20260812/table_shells.md:56-68` | 当前 China 图表壳 | “24 个逐小时碳强度阶梯值显示在 48 个积分槽上” | 已修正图壳、表行、表注和数据定位 |
| `solver/src/setp_solver/reporting/figures.py:238-295,688-710` 及 `design_templates.py`、`runner.py`、`STYLE_NOTES.md` | 通用渲染器可能接中国逐小时源，也可能接原生半小时的非中国历史源 | 通用面板标题用中性的“电网碳强度”；China 图注另写逐小时。按碳强度三分位的组名叫“低/中/高碳”，不能冒充真实电价的谷/平/峰 | 已修正标题、阶梯画法、分组名、样例生成器、数据合同、预览标题和相关测试 |
| `docs/paper_submission_final/design_templates/mock_data/f4_48slot_charging.csv` 及对应 F4 PDF/PNG | 样例数据；碳值现按小时成对恒等，充电柱仍为 30 分钟 | “样例数据/非实验结果；逐小时碳阶梯＋30 分钟负荷” | 只重绘这一张样例图；没有读取正式结果或运行实验 |
| `solver/src/setp_solver/search/formal_runner.py:622-633,880-890,1050-1055`、`reporting/samples.py:538-560`、`models/tests/test_carbon.py:62-63` | 旧 UK/NESO 链可能是原生半小时观测 | 不套用 China81 的“24 小时复制”结论 | 登记为非中国例外，不改历史代码/测试 |
| `formal_dynamic_dispatch` 的 `fixed_30_minutes`、看门狗 30 分钟、1800 秒时限、客户服务时长等 | 动态触发间隔、运行时限或服务时间 | 与电价/碳强度分辨率无关 | 从时段问题清单排除 |

### 1.3 已做的标注修正

本轮实际修改的活动位置如下；未改任何正式算例 CSV/JSON：

- 加载与防再犯：`solver/src/setp_solver/china81.py`、`solver/tests/test_china81_bundle_20260720.py`。
- 算法/技术输出注释：`solver/src/setp_solver/algorithms/problem_hgs/kernel_proposals.py`、`solver/scripts/run_problem_hgs_private_technical.py`。
- 当前事实与审计：`docs/handoff/CURRENT_PROJECT_CONTEXT.md`、`china_localization_repo_audit_20260812.md`、`root_design_audit_20260812.md`、`experiment_master_map_20260811.md`、`instance_defect_ledger_and_serial_algorithm_20260811.md`。
- 当前正文、实验设计与图表壳：`paper_main_foundation_v2_20260812.md`、`experiment_design_package.md`、`figure_shell_spec_20260812.md`、`table_shells_20260812/table_shells.md`。
- 图表代码与样例：`reporting/figures.py`、`reporting/design_templates.py`、`reporting/runner.py`、`reporting/STYLE_NOTES.md`、`solver/tests/test_reporting.py`、`design_templates/DATA_CONTRACT.md`、`design_preview.tex`、F4 mock CSV 及对应 PDF/PNG。

历史生成器、冻结合同、`solver/reports/**`、`baselines/**/tasks/**`、`tmp/**`、旧论文快照和已保存 JSON 中的兼容字段没有批量回写。它们是证据现场；以后引用时统一按本节台账改述，不把历史包伪装成重新生成的结果。

### 1.4 验证

定向单测结果为 `8 passed in 1.87s`：包括真实 China81 三地区加载、槽—分钟一致性、独立半小时碳值拒绝、图表说明、低/中/高碳分组和 F4 渲染。测试没有调用求解器。重绘后的 F4 已人工查看：碳曲线为逐小时阶梯，充电柱仍在 30 分钟网格，右面板不再与电价谷/平/峰混名。

## 二、日期锚点对照表与冲突清单

### 2.1 日期锚点对照表

| 锚点 | 当前日期或范围 | 出处 | 角色与证据强度 | 是否冲突 |
|---|---|---|---|---|
| 碳数据覆盖期 | 2025—2060；本项目取 2025 年 2 月，单日解释取 `2025-02-12` | `cef_dataset_full_20260731/download_manifest.json:15-17,29-37`；运行日历 | 学术数据集的逐小时投影，全年可取；不是实测 | 与 02-12 不冲突，也支持 02-01…28 月面板 |
| 电价适用期 | `formal_month=2025-02` | `data/ChinaPrices/china_2025_02_tariff_register_v2.json:2-7,19-69` | 只支持“2025 年 2 月适用”，未给某一天独立价格；来源为保留原扫描的第三方数字档案 | 02-12 在适用月内；命名车场具体适用行仍未闭合，但不是日期冲突 |
| 柴油来源发布/生效日 | 北京等主要源为 `2025-01-16`，北京从 01-16 24:00 起 0 号柴油 7.48 | `.../evidence/diesel_2025_02_12/beijing_2025_01_16.html:412-413`；其他城市登记见 v4 city register | 官方地方表或官方推导；`01-16` 是来源/生效日，不是配送作业日 | 与 02-12 不冲突；01-16 价格当时仍有效 |
| 柴油证据目录名 | `diesel_2025_02_12` | `baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/evidence/` | 目录名表示审计目标/作业锚，不表示所有源文件都发布于 02-12 | 与源文件 01-16 的角色不同，不应写成同一日期字段 |
| 当前单日作业/共同展示锚 | `2025-02-12` | `china_2025_default_date_decision_v2_20260718.json:3-10,62-67`；`model_change_approval_register_20260718.md:321-330` | 已批准的结果盲共同解释日 | 无冲突；是本报告建议继续保留的唯一单日锚 |
| 活动加载器默认日 | `2025-02-12` | `solver/src/setp_solver/china81.py:36,310-315,512-527,631-656` | 默认参数并按日过滤；bundle 保存该日 | 与获批日一致 |
| 活动柴油参数日 | `scenario_date=2025-02-12` | v4 `city_runtime_parameter_register.csv:1-10` | 九城活动参数登记；状态为已批准 | 与加载器一致 |
| 运行日历首行/覆盖范围 | 首行 `2025-02-01`；全表 `2025-02-01…28` | v4 calendar `:1-2`；正式月份合同 | 02-01 只是全月面板第一天，不是默认作业日 | 旧文若据首行把作业日写成 02-01，属于角色错置 |
| E4/E7 正式逐日重放 | `replay_date ∈ 2025-02-01…28`；02-12 为共同解释日 | `docs/handoff/china_e3_e7_foundation_adapter_contract_20260723.md:12-16`；`baselines/china_e3_e7/foundation_20260723/metadata.json:10-27` | 后续正式合同，明确保留完整自然月 | 与“所有正式任务只用 02-12”的旧笼统措辞有表面冲突，须按字段角色拆开 |
| 私有重建构造日/运行日 | `created_date=2026-08-11`；`runtime_profile_date=2025-02-12` | `china81_private_rebuild_v1_20260811/metadata.json:2,17-23` | 一个是产物创建日，一个是作业日，已显式区分 | 无冲突 |
| suite_v3、PRDFIX、depotpair、metro 构造日 | 多数为 `2026-08-12`，但 metadata 没有显式 `operation_date` | 各套件 `metadata.json:1-16`；builders 省略 `date=` 调用 loader | 创建日有据；作业日只是隐式继承 02-12，证据中等且脆弱 | 字段缺口；不能把 2026-08-12 写成作业日 |
| 新 P34 动态事件流 | 只有相对秒数和 `HH:MM:SS`；日历日 `UNKNOWN` | `china81_dynamic_stream_v1_20260811/metadata.json:1-5,36-66,113-130`；`private/true_dynamic_events.csv:1-3` | 明确是构造模拟日，不是观察订单日；未保存 calendar date | 新生产 runner 尚未接该流，不能声称已经绑定 02-12 |
| 旧技术动态 runner | 隐式继承 loader 默认 `2025-02-12` | `_build_context -> load_china81_bundle` 且省略 `date` | 只说明旧技术链的实际默认行为 | 不能外推到尚未接线的新 P34 生产链 |
| `2025-02-11` 前夜剖面 | day offset `-1` 的前夜 | `solver/reports/charge_window_fix_20260811/gate0_v2_on/metadata.json:169-194` | 为 02-12 作业日跨午夜充电提供前夜剖面 | 不是第二个作业日 |
| `2025-01-01` | 草案日期 | `data/ChinaInstances/china_parameter_lock_v2_20260718.json:186-210` | 明确为 DRAFT 历史项 | 已被 02-12 批准项覆盖，不是活动冲突 |

### 2.2 冲突清单

1. `CORRECTION`：一行里的 `date=2025-02-01`、目录 `diesel_2025_02_12` 和源文件 `beijing_2025_01_16.html` 不是三个互相竞争的作业日。它们分别是**逐日重放键、审计目标/默认作业锚、来源发布/生效日**。旧记录没有字段角色，才显得互相打架。
2. `FACT`：`docs/handoff/china_e3_formal_release_contract_20260723.md:9-19` 说所有正式任务共同使用 02-12；后续 `china_e3_e7_foundation_adapter_contract_20260723.md:12-16` 又要求 E4/E7 保留 28 天。正确消歧是“共同解释/默认作业日 = 02-12；正式稳健性重放日 = 02-01…28”，不能任选一份合同覆盖另一份。
3. `FACT`：当前 suite_v3、PRDFIX、depotpair 和 metro metadata 缺 `operation_date`；其 builders 在 `build_china81_suite_rebuild_20260812.py:211`、`build_suite_prd_fix_20260812.py:379,770-805`、`build_suite_depotpair_rebuild_20260812.py:1091`、`build_china81_metro_suite_20260812.py:1204,1679` 省略日期，实际靠 loader 默认值。现在数值链对齐，但身份记录不够牢。
4. `FACT`：新 P34 动态 CSV/metadata 没有日历日；`solver/scripts/run_dynamic_experiment.py:1-12,1031-1072` 的生产路径尚未接 China81/P34，也没有日期参数。因此其 calendar date 是 `UNKNOWN`，不能在报告里补写 02-12 冒充已接线事实。
5. `FACT`：v4 构建器把 02-12 获批柴油值复制到 28 天全部行，见 `baselines/china_instances/build_china81_runtime_parameter_authority_v4_20260723.py:95-129`。仓库同时保存国家发改委 02-19 24:00 降柴油 160 元/吨的证据（`ndrc_2025_02_19.html:67-68`）和重庆自 02-20 00:00 起 0 号柴油 7.36 元/L 的地方表（`chongqing_2025_02_19.html:31-37,339-347`），而活动日历重庆 02-20 仍为 7.50（calendar `:11666-11669`）。所以**至少重庆 02-20…28 的柴油列与仓库现有官方证据冲突**。
6. `UNKNOWN`：另八城在 02-20 以后各自精确的每升价格，本轮没有逐城闭合，不能照重庆数值推算。该缺口不影响 02-12 单日锚，但正式 28 日重放若使用逐日柴油成本，就必须先补齐。

## 三、统一方案与代价（含“要不要真改成 24 槽”）

### 3.1 建议的统一日期方案

`DECISION`（建议，不新增用户决定）：保留已批准的 `2025-02-12`，但把不同日期角色写成不同字段。

| 统一字段 | 建议值 | 用途 |
|---|---|---|
| `operation_date` / `default_exhibit_day` | `2025-02-12` | 单日算例加载、共同解释和论文展示 |
| `replay_date` | `2025-02-01…2025-02-28` 中的具体一天 | E4/E7 正式逐日重放；必须进入任务键、结果键 |
| `tariff_effective_month` | `2025-02` | 电价证据实际支持的粒度，不伪造逐日适用证据 |
| `source_publication_date` / `source_effective_from` | 按各柴油原文登记，例如北京 `2025-01-16 24:00` | 说明参数来源何时发布/生效，不冒充作业日 |
| `artifact_created_date` | `2026-08-11` 或 `2026-08-12` | 说明文件何时构造，不参与运行结算 |
| `event_second` / `event_clock` | 保留现值，并在获批重建时另加 `operation_date` | 动态事件流的日内时刻与日历日分开 |

选择 02-12 的依据不是随便挑一天：它已经过批准；活动 loader、v4 城市登记和 private metadata 都一致；逐小时碳数据在该日可取；电价证据覆盖整个 2025 年 2 月；01-16 起的柴油价格在 02-12 仍有效。与此同时，后续合同明确要求 28 日面板，所以不能把“唯一单日锚”扩写成“唯一允许的重放日”。

### 3.2 日期显式化的改动面与代价

| 改动 | 影响文件 | 代价与边界 |
|---|---|---|
| 给现有套件显式写 `operation_date=2025-02-12` | private、suite_v3、PRDFIX、depotpair、metro builders 与 metadata | 代码改动低至中；但会改变封存包和 artifact hash，仍属正式产物重建，须用户批准 |
| 给 P34 动态流和生产 runner 加 `operation_date` | 动态 metadata/CSV schema、生成器、`run_dynamic_experiment.py` 和输出主键 | 中等；须先完成尚未接线的生产链，不能只改一行文字冒充已绑定 |
| E4/E7 显式加入逐日 `replay_date` | 任务 manifest、结果主键、汇总表/图 | 中至高；避免 28 天结果被同名覆盖，需要重建相关结果索引 |
| 修复 02-20 后逐城柴油序列 | 九城官方证据、runtime authority、时空结算权威、依赖哈希 | 高；至少涉及正式数据重建，使用逐日油费的 28 日结果还须重算 |
| 把单日锚改成别的日期 | loader/构建器、碳剖面、成本/排放、保存结果 | 高；现有证据没有显示 02-10、02-16 或 02-01 比已批准的 02-12 更强，不建议重开 |

### 3.3 要不要真改成 24 槽

| 选项 | 怎么做 | 数值/结果影响 | 代价 | 建议 |
|---|---|---|---|---|
| A. 保留 48 个 30 分钟积分/容量槽 | 只把碳称为 24 小时信号、电价称为分时类别信号；保留当前联合键 | 数值不变；真实的充电分摊和容量近似不变 | 低；本轮已完成标注、断言、测试和图表修正 | **推荐** |
| B. 仅把碳权威表压成 24 行，加载时再展开为 48 行 | 新建 24 行碳源权威；loader 显式零阶保持到计算网格 | 理论上可保持评价数值，但正式数据、文件名、哈希、builder、联合键和复现链都会改变 | 中至高；仍属于重建正式算例数据，须用户批准 | 只有为清理数据架构而非改变模型时才考虑 |
| C. 整个模型改成 24 个一小时槽 | 电价、碳、充电积分、候选起点和桩容量全部改为一小时 | 会改变跨时段电费/排放、部分充电分槽量、共享桩可行性和搜索结果 | 很高；触及受保护 `cost.py`、`check.py`，以及 `charge_timing.py`、`search/charging.py`、`schedule_oracle.py`、动态排程、图表和大量测试；必须重跑结果 | 不建议在没有单独科学目的时做 |

本轮严格执行选项 A，没有替用户启动 B/C。v3、v4 日历 SHA-256 在任务前后保持：v3 `54acbdc757c8a3a3b097d1e39cd35294e795ca2c1711bd56b12bc3b9af9b1c0b`；v4 `e714b05b2e44635204681fe213dfd454e9f9009c647bad7318ce6b0ccad2004b`。

## 四、K4 两处存疑标记的现状

### 4.1 柴油 `PENDING_EXPLICIT_PARAMETER_APPROVAL`

`CORRECTION`：当前 v4 中“候选栏”和“活动参数栏”同时存在，不能只看候选状态就说“7.48 仍待批”。

- v4 同一行保留遗留候选 `diesel_price_candidate_cny_per_l=7.48`、`diesel_candidate_status=PENDING_EXPLICIT_PARAMETER_APPROVAL`，同时另有活动值 `diesel_price_cny_per_l=7.48`、`diesel_parameter_status=APPROVED_CHINA_E3_FORMAL_RELEASE_001`，见 `city_runtime_parameter_register.csv:1-4` 和 calendar `:1-3`。
- 当前默认运行权威明确指向 v4，见 `solver/src/setp_solver/china81.py:117-120`。loader 只把候选值/标签复制进 time profile（`:1109-1116`）；全源码未发现候选字段控制数值评价。
- 活动油价映射只读取 `diesel_price_cny_per_l`，且只接受已批准状态，见 `china81.py:1291-1327`；随后进入 `PriceParameters` 和按路线起点城市结算的燃油成本。候选 `PENDING` 不会阻断或替代活动值。
- 已保存 metadata 确实会同时保存两套字段，例如 `solver/reports/charge_window_fix_20260811/gate0_v2_on/metadata.json:169-194`；这只证明标签被加载/留档，不等于 `PENDING` 控制评价。
- 已保存的历史成都—重庆技术包使用了活动城市油价：`best_solution.json:240-266,276-360` 保存总油耗 58.220006 L、燃油成本 436.340081 元，路线同时从成都和重庆出发；结合 v4 成都 7.48、重庆 7.50 可闭合出成都约 15.4983 L，7.48 元/L 对该保存成本的贡献约 115.927 元。该包是历史技术结果，不是当前论文正式结果。

结论：**候选状态字段本身没有进入数值评价；活动的 7.48 已进入评价链和已保存技术结果。** v3 没有活动批准两列，按当前 loader 合同不能形成活动 bundle。

### 4.2 服务费 `UNIFORM_SCENARIO_PROXY_NOT_MARKET_OBSERVATION`

`FACT`：`service_fee_class` 是披露标签，源码只在 loader 中保存它（`china81.py:1105`），未发现评价器按该标签分支；但数值 0.4 已进入评价链。

- loader 读取 `public_energy`、`public_service_fee`、`public_total`，并强制 `energy + service = total`（`china81.py:1021-1043`）；公共总价进入兼容价格和逐槽 profile（`:1094-1105,1154-1202`）。
- 精确充电成本对车场读取 `depot_energy_cny_per_kwh`，对公共站读取 `public_total_cny_per_kwh`（受保护 `cost.py:1168-1224`）；利润账复用同一函数（`profit.py:143-169`）；公共站择时/排程也读取总价（`schedule_oracle.py:160-195` 等）。因此只有实际使用公共站时 0.4 才产生金额；全在车场充电时贡献为 0。占用费 `cost_occ` 是另一笔费用，不能与服务费混算。
- 可核的已保存例：历史 E4 panel 的 `cn-prd-50c-02.../solutions/seed10_cost_only.json:1-29,421-432` 在广州公共站充 2.032385031649 kWh，开始于 23498.9 秒；对应 v4 广州 02-12 行的 `public_total=0.31816875+0.4=0.71816875`（calendar `:4574-4578`）。保存电费闭合为 `20.839971139757 - 19.380375722059 = 1.459595417698` 元，其中服务费贡献 `2.032385031649 × 0.4 = 0.812954012659` 元。
- 对历史 E4 panel 全部 solution JSON 的只读清点，6 份 `station_charging_kwh>0`，单份服务费贡献约 0.812954—1.667534 元。全仓不同历史副本和嵌套候选的语义去重总数本轮没有闭合，记为 `UNKNOWN`。
- 反例同样存在：`solver/reports/combat_v2_20260812/combat_v2_5cycles_final/best_solution.json:554-581` 保存 `station_charging_kwh=0`，所以该包服务费实际贡献为 0。

结论：**标签不控制评价，但 0.4 这个统一代理数值已进入公共站充电的评价链，并已在历史保存结果中实际产生金额。** 本轮按 K4 要求只核实，没有修改标签或数值。

## 五、受保护文件哈希

| 受保护文件 | 任务开始 SHA-256 | 交付前 SHA-256 | 本任务处理 |
|---|---|---|---|
| `solver/src/setp_solver/cost.py` | `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989` | `525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989` | 未修改 |
| `solver/src/setp_solver/check.py` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072` | 未修改 |
| `solver/src/setp_solver/search/evaluation.py` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3` | 未修改 |

说明：任务开始时 `cost.py` 已与 2026-08-12 早先审计记录的旧哈希不同；本任务按用户说明把它视为获授权并行任务的现场，只记录、不干预。就本任务的“开始—交付前”窗口而言，三个受保护文件逐位一致。

本任务不产生实验包；没有 `metadata.json/raw_runs.csv/decision.json/artifact_hashes.json` 四件套要求。唯一新增交付为本报告，其他改动均为上述现行标注、断言、测试和非实验图表样例。
