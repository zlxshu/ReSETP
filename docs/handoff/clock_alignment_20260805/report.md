# T15 时钟对齐与车场充电窗口模式

## 回归门结果（最前）

**FACT**：T10 破掉的 7 项全部恢复通过：公共站严格时钟/SOC 2 项、refined charging 2 项、搜索 h2/h3/m0_evheavy 3 项；T15 定向回归为 `7 passed`。

**FACT**：三个已知阳性 witness 仍被 `CHARGING_TRIP_OVERLAP` 判为违反，重叠秒数为：`C_seed2_budget1000 = 6563.071224550004`、`C_seed1_budget100 = 6365.9078330282355`、`C_seed3_budget1000 = 6239.742124296223`。

**FACT**：T10 目录中的 18 个解在默认生成/检查口径下全部合法，`18/18` 通过，无新违反。

**FACT**：全量套件使用仓库既有 3.13 环境执行，结果为 `906 passed / 1 skipped / 6 failed`；T10 基线为 `898 passed / 1 skipped / 14 failed`。T10 基线中的 7 项回归门失败全部恢复，另有 China81 共享补全的首趟日偏移旧断言随默认模式修复恢复，因此总计恢复 8 项；剩余 6 项均属于 T10 基线残留，无新失败：

- `test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit`
- `test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables`
- `test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts`
- `test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps`
- `test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact`
- `test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately`

**FACT**：受保护文件开工/收工 SHA-256 均未变化：`cost.py e7ea406d...42b00d`、`search/evaluation.py c7215263...06fc3`、`check.py 1cdb6236...0b1072`。`cost.py`、`search/evaluation.py`、`check.py` 均未编辑。

## 三种窗口模式的公式与取表规则

**FACT**：三种取值统一由显式参数 `depot_charge_window_mode` 校验，合法值只有 `prev_night`、`same_day_predeparture`、`full_gap`。China81 补全入口 `complete_china81_route_skeleton` 和 `exact_china81_score` 的默认值是 `same_day_predeparture`。

**FACT**：`prev_night` 的窗口为前一日收车后至当日首趟出发，动作使用 `charge_day_offset=-1`，本地窗口为 `[0, 86400 - occupancy]`；China81 日历按 `date - 1 day` 读取，未生成或插补数据。

**FACT**：`same_day_predeparture` 的窗口为当日车场开门至证书出发时刻减充电占用，即 `[0, route_timing.earliest_departure_second - occupancy]`，动作偏移为 0，只读取 bundle 当前日期表。

**FACT**：`full_gap` 的窗口为证书计入公共站占用后的返场时刻至下一次证书出发边界减占用，即 `[route_timing.return_second, next_departure - occupancy]`；选择时按充电动作实际落入的日偏移取 profile。China81 该模式预加载 `-1/0/+1` 三个真实日期键，使用仓库现有 28 天日历，不插补。

**FACT**：模式 smoke probe 的实际日历键为：`prev_night -> [-1,0]`、`same_day_predeparture -> [0]`、`full_gap -> [-1,0,1]`；三个 profile 均由日历读取，每个城市对应 48 个半小时槽。

**FACT**：在 `cn-jjj-10c-01-V2-LOCATIONS` 有限车队 smoke fixture 上，`same_day_predeparture` 和 `full_gap` 通过，`prev_night` 返回 `overage=(1, 0, 0)`，即本次注册车队下求解器未找到满足车队上限的组合。

**INFERENCE**：上述 `prev_night` 结果只能归类为“求解器未找到/配置未找到可行解”；没有独立证明，不能写成模型硬不可行，也没有据此选择或淘汰模式。

## 实现事实

**FACT**：`search/multitrip_schedule.py` 新增共享模式校验、证书窗口计算和按实际日偏移选择 profile 的接口；`route_timing` 可在生成阶段只提取权威时钟而不把生成前的电量不足误判成另一套时钟。

**FACT**：`search/charging.py` 和 China81 支持路径均从 `route_timing` 初始化路线时钟；最终路线包含公共站充电动作后，车场动作再次按证书返场时刻重锚，因此不再使用不含公共站占用的 `route_return_arrival_without_charging` 作为最终车场锚点。

**FACT**：China81 补全从 `tariff_carbon_48slot_calendar.csv` 按日期键加载所需 profile，并把显式模式传入动作生成及物理化证书；直接调用 `prepare_multitrip_solution` 的旧接口默认保留 `prev_night`，以不改写其既有归档证书行为。

**FACT**：没有修改碳价、碳数据源、电价、算例、车队合同、目标函数经济含义，也没有放宽既有约束；未修改 `docs/paper_gci_dmm_vrp_20260804/` 或 `docs/paper_v2/`。

**DECISION**：本任务不在三种模式之间择优，不作效应比较，不把任何模式写成论文结论；模式保留给后续预注册试算和用户决定。

**DECISION**：`decision.json` 的 `paper_claim_allowed` 固定为 `false`。
