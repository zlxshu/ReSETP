# T17 充电择时策略显式开关

状态：`PASS_REGRESSION_GATE`

## FACT：实现

1. 新增显式参数 `charge_timing_policy`，合法值为 `carbon_min`、`asap`、`cost_min`、`cost_plus_carbon`；默认值是 `carbon_min`。非法值会触发 `ValueError`。
2. `carbon_min` 默认分支复用受保护的原有 `cost.py::best_charging_action_start`，不改动该函数。`asap` 直接取可行窗口的 `earliest_start_second`。
3. `cost_min` 与 `cost_plus_carbon` 的候选断点枚举照搬 `carbon_objective_probe_20260804/probe_driver.py::_timing_candidates`。`cost_plus_carbon` 的打分式照搬为 `electricity_cost + carbon_price * charging_emissions`，同分时仍取更早时刻。
4. `carbon_price == 0.0` 时，`cost_plus_carbon` 在候选打分前直接切换为 `cost_min`，因此两者走同一段电费打分代码。
5. 参数已接入车场认证窗口选时、公共站插入选时、共享 China81 补全入口，以及两条现存充电生成路径。China81 既有零碳权重的 `ev_immediate` 候选在默认运行中显式映射为 `asap`，保留原有“零权重即最早”的臂语义。
6. 没有删除、弱化或搬移任何既有 `raise` / `assert` / 校验分支；搬移清单为空。`_select_charge_start` 中的 `aware` / `naive` 分支原文未改。
7. 未将公共站充电从兜底改为并列候选；未选择或改写三种车场窗口模式；未改首趟跨日口径、碳价、碳数据源、电价、算例、车队合同、目标函数经济含义或 `_TOL`。

## FACT：四个最小构造用例

构造使用同一辆车、同一 `10.0 kWh`充电量、`30 min`占用、窗口 `[0, 5400] s`，碳价为 `5.0`。前四个半小时槽的电价为 `[1.0, 0.1, 2.0, 0.5]`，碳强度为 `[500, 1000, 100, 200] gCO2e/kWh`。车场 `D0` 与公共站 `F0` 分别使用各自的时变电价字段，得到相同的可核结果：

| 策略 | D0/F0 起始时刻 (s) | 电费 | 充电排放 (kgCO2e) | 选择依据 |
|---|---:|---:|---:|---|
| `asap` | `0.0` | `10.0` | `5.0` | 最早可行 |
| `cost_min` | `1800.0` | `1.0` | `10.0` | 电费最小 |
| `cost_plus_carbon` | `5400.0` | `5.0` | `2.0` | `5.0 + 5.0×2.0 = 15.0` 最小 |
| `carbon_min` | `3600.0` | `20.0` | `1.0` | 充电排放最小 |

`carbon_price=0.0` 的独立验证中，`cost_min` 与 `cost_plus_carbon` 都返回 `1800.0 s`；两者的动作电费均为 `1.0`，排放均为 `10.0 kgCO2e`。

## FACT：定向回归门

1. 首次手工命令把 `test_search.py` 的类名误写为 `SearchTests`，pytest 原样返回三个 `not found` 且 `no tests ran`。更正为实际类名 `SearchGateTests` 后，正式定向 7 项为 `7 passed in 3.40s`（Python 3.13 证据脚本重跑值）。
2. 三个阳性 witness 均被判为 `CHARGING_TRIP_OVERLAP`：`C_seed2_budget1000 = 6563.0712245500035 s`、`C_seed1_budget100 = 6365.9078330282355 s`、`C_seed3_budget1000 = 6239.742124296223 s`。
3. T10 的 18 个解全部合法：`18/18`，每个解的违反类型列表均为空。
4. T15 验证脚本还原样输出了非 T17 门禁的窗口 smoke：`prev_night` 为 `overage=(1, 0, 0)`，`same_day_predeparture` 为 `PASS`，`full_gap` 返回 `CHARGING_START` 违反，其值为 `start=39059.606`、`completion=44177.626`、`departure=40831.871`、`return=63606.704`、`next_departure=127231.871`。本报告不将该输出解释为“正确拒绝”，也不据此选择或淘汰任何窗口模式。

## FACT：全量回归

定向门全过后，使用 `/opt/anaconda3/bin/python3.13` 运行一次全量：`906 passed / 1 skipped / 6 failed in 426.53s`，与 T15 对照数完全相同。失败仍为同一六项，本轮不对其合理性作任何判定：

1. `test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit`：实际 `HALT_FROZEN_PROTECTED_CONTRACT`，期望 `FROZEN_PROTECTED_CONTRACT_OK`。
2. `test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables`：`report["carbon_aware"]["feasible"] = False`。
3. `test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts`：实际 `root_cause = "repair_logic_defect"`。
4. `test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps`：`candidate_obj = 4954.208671718898`，`initial_obj = 4923.557583344485`。
5. `test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact`：E4 global manifest 报 `solver/src/setp_solver/search/multitrip_schedule.py` 与 `solver/src/setp_solver/check.py` hash drift。
6. `test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately`：实际 `HALT_STRONG_BRIDGE_BACKEND_PROFILE_ALIGNMENT`，期望 `A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED`。

## FACT：环境与受保护文件

运行环境为 Python `3.13.9`、numpy `2.3.5`、scipy `1.16.3`、pytest `8.4.2`；`pyvrp` 可导入但模块未提供 `__version__`。所有正式命令都设置 `PYTHONHASHSEED=0` 与 `PYTHONPATH=solver/src:models/src`。

受保护文件开工／收工 SHA-256 一致：

- `cost.py`: `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`
- `check.py`: `1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`
- `search/evaluation.py`: `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`

## INFERENCE

`cost_plus_carbon` 在碳价为零时与 `cost_min` 的代码分支、起始时刻、电费和排放均一致，因而本次构造验证支持“逐字退化”要求。这只是实现与回归结论，不是论文效应结论。

## DECISION

`PASS_REGRESSION_GATE`：T17 规定的定向 7 项、3 个阳性 witness、T10 的 18 个解与全量对照数均满足任务书的显式门禁。

`paper_claim_allowed=false`。

## HALT_*

`NONE`。
