# T19 公共站候选 repair_delta 记账修复报告

## FACT

本轮仅修改 `solver/src/setp_solver/algorithms/resetp_alns/support/charging.py` 的候选打分记账通道：删去该处对 `score_reference` 的直接调用，改为每个路线内部候选先调用 `record_repair_delta(context)`，再调用 `route_model_cost_delta(candidate_route, candidate_actions, context)`。外层完整搜索候选的 `candidate` 评价没有改动。

`route_model_cost_delta` 继续通过统一 `evaluate` 评价整条路线及其全部充电动作。本轮没有新建、简化或更换打分式；绕路里程、时间、充电电费、公共站服务费与占用费、充电侧排放仍由原目标函数核算。

静态审计退出码为 `0`，结果为 `PASS_ALNS_BUDGET_G0_STATIC_CLOSURE`。实际扫描 `30` 个调用点，`blockers=0`，`unclassified=0`，`search_evaluations=0`。通道直接分类计数为 `candidate=9`、`reference=4`、`repair_delta=6`，三个必需通道均存在；其余为 `reference_or_cache=7` 和 `route_delta_or_feature=4`。审计器 `baselines/e2_alns/audit_alns_budget_g0_20260718.py` 未修改，SHA-256 为 `c7322d3704d90b9f658fef7dd1644686434dfd482fd093588466c25c53f68a99`。

默认 `fallback` 下的定向回归为 `7 passed in 3.52s`。三个阳性样本均仍只报 `CHARGING_TRIP_OVERLAP`：`C_seed2_budget1000 = 6563.0712245500035 s`、`C_seed1_budget100 = 6365.9078330282355 s`、`C_seed3_budget1000 = 6239.742124296223 s`。T10 的 `18/18` 个解均为零违反。

`parallel` 最小构造仍使用 `cn-jjj-50c-01-V2-LOCATIONS` 的 `D_beijing`、`S_beijing`、`C003` 原始节点、原始道路矩阵、原始电价/碳强度和原始车辆参数，路线为 `D_beijing -> C003 -> D_beijing`。两候选的违反数均为 `0`。

| 候选 | 完整目标值（CNY） | 里程（m） | 充电电费（CNY） | 排放（kgCO2e） | 占用费（CNY） |
|---|---:|---:|---:|---:|---:|
| 车场 `depot_fallback` | `245.8269329581829` | `80371.46081407` | `21.678085995586443` | `3.9985099596052143` | `0.0` |
| 公共站 `public_station_S_beijing` | `267.38322772138827` | `87555.644999438` | `28.602201671528793` | `8.354838499436376` | `9.491963916008359` |

公共站候选的充电电费已含 `7.593571132806687 CNY` 公共站服务费；两候选的时间成本均为 `0.0 CNY`，但路程时间仍由完整评价器核算。公共站候选比车场候选高 `21.556294763205358 CNY`，因此最终选择 `depot_fallback`。

全量回归的实际结果为 `906 passed / 1 skipped / 6 failed in 413.56s`，与规定基线一致。六项失败与 T15/T17b 基线逐条相同：

1. `test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit`：实际 `HALT_FROZEN_PROTECTED_CONTRACT`，期望 `FROZEN_PROTECTED_CONTRACT_OK`。
2. `test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables`：`report["carbon_aware"]["feasible"]` 实际为 `False`，期望为真。
3. `test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts`：至少一行 `root_cause` 实际为 `repair_logic_defect`，断言要求不得等于该值。
4. `test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps`：`candidate_obj = 4954.208671718898`，`initial_obj = 4923.557583344485`，未满足严格小于。
5. `test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact`：E4 全局清单返回 `2` 项哈希漂移，涉及 `solver/src/setp_solver/search/multitrip_schedule.py` 与 `solver/src/setp_solver/check.py`，期望空列表。
6. `test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately`：实际 `HALT_STRONG_BRIDGE_BACKEND_PROFILE_ALIGNMENT`，期望 `A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED`。

三个受保护文件开工与收工 SHA-256 完全一致：`cost.py = e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`，`check.py = 1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`，`search/evaluation.py = c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

按文件修改时间隔离，本轮唯一人工源码改动为 `charging.py`；`china81_completion.py` 本轮未变。静态审计命令生成的临时审计目录在记录结果后已移出仓库，未作为额外产物保留。本轮没有删除或弱化任何既有 `raise`、`assert` 或校验分支，没有搬移任何异常分支，也没有新增未要求的行为改动。

## INFERENCE

静态审计中新调用点被分类为 `repair_delta`，而不再是完整搜索候选的评价面；这消除了 T18 的额外预算闭合失败。最小构造的两臂数值、可行性和选择均未漂移，支持本次改动只更换记账通道，未改变该构造下的经济打分口径。

## DECISION

T19 回归门全部通过，裁决为 `PASS_T19_REPAIR_DELTA_ACCOUNTING`。`public_station_candidate_mode` 仍只有 `fallback` 与 `parallel` 两个取值，默认仍为 `fallback`。未触碰 `charge_timing_policy`、`depot_charge_window_mode`、首趟跨日口径、碳价、`_TOL`、窗口倒挂保护、审计器判据或许可清单。`paper_claim_allowed=false`。

## HALT_NONE

无回归门失败，本轮不触发 `HALT_REGRESSION_FAILED`。
