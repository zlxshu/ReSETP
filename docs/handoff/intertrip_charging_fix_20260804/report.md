# T10 充电时段与同一实体车外行程重叠修复验证

## 回归验证（最前）

FACT：三个已知阳性样本通过新检查器，3/3 命中 `CHARGING_TRIP_OVERLAP`。
FACT：T9 判定为无重叠且当时合法的解直接调用新 `check_solution`，20/20 仍合法；误报数为 0。
FACT：单元回归 `test_multitrip_schedule.py` 为 23 passed。
DECISION：回归门槛通过，未触发 `HALT_REGRESSION_FAILED`。

## 保护文件与范围

FACT：开工前 SHA-256：`cost.py` `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`；`check.py` `86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b`；`search/evaluation.py` `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。
FACT：收工后 SHA-256：`cost.py` `e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`；`check.py` `886e91108f666c4c4dcb379020b5ec4e055e9a6150fdb42d69bd1ffc9e5ad38c`；`search/evaluation.py` `c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。cost/evaluation 逐位不变，check 按批准事项变化。
FACT：生成器修复重排实体车时间线；检查器新增同一实体车充电区间与任一外行程区间的半开区间相交硬约束。未改碳价、碳数据、电价、算例、车队合同、目标函数、`cost.py`、`search/evaluation.py` 或论文目录。

## T5 冻结矩阵重跑

FACT：T10 raw_runs.csv 观察到 18/18 次；缺失键：无。
FACT：服务量红线通过 18/18；每次要求 50/50 客户与 13264/13264 需求。
FACT：12:00—15:00 充电量归零 18/18 次。

### 逐次结果（修复前→修复后）

| run | 服务量 | 槽位 | 中午 kWh | 实体车数变化 | 系统排放 kg 前→后 | 运营成本 CNY 前→后 | 充电 kWh 前→后 |
|---|---:|---|---:|---:|---:|---:|---:|
| C_seed1_budget100 | 50/50; 13264.000/13264.000 | 09(04:30-05:00), 10(05:00-05:30), 11(05:30-06:00), 12(06:00-06:30), 13(06:30-07:00), 14(07:00-07:30) | 0.000000 | +0 | 173.442594→200.411147 | 2103.706846→2149.591734 | 92.847852→51.845721 |
| C_seed1_budget1000 | 50/50; 13264.000/13264.000 | 09(04:30-05:00), 10(05:00-05:30), 11(05:30-06:00), 12(06:00-06:30), 13(06:30-07:00), 14(07:00-07:30) | 0.000000 | +0 | 189.431446→204.290045 | 2074.478057→2164.645959 | 87.548679→53.572182 |
| C_seed2_budget100 | 50/50; 13264.000/13264.000 | 09(04:30-05:00), 10(05:00-05:30), 11(05:30-06:00), 12(06:00-06:30), 13(06:30-07:00), 14(07:00-07:30) | 0.000000 | +0 | 200.686710→200.686710 | 2152.946018→2152.946018 | 52.612627→52.612627 |
| C_seed2_budget1000 | 50/50; 13264.000/13264.000 | 09(04:30-05:00), 10(05:00-05:30), 12(06:00-06:30), 13(06:30-07:00), 14(07:00-07:30) | 0.000000 | +0 | 172.233638→206.112280 | 2096.219180→2178.418761 | 98.681013→48.257046 |
| C_seed3_budget100 | 50/50; 13264.000/13264.000 | 09(04:30-05:00), 10(05:00-05:30), 11(05:30-06:00), 12(06:00-06:30), 13(06:30-07:00), 14(07:00-07:30) | 0.000000 | +0 | 202.193175→202.193175 | 2156.301386→2156.301386 | 54.136666→54.136666 |
| C_seed3_budget1000 | 50/50; 13264.000/13264.000 | 09(04:30-05:00), 10(05:00-05:30), 11(05:30-06:00), 12(06:00-06:30), 13(06:30-07:00), 14(07:00-07:30) | 0.000000 | +0 | 171.229364→205.894879 | 2090.658834→2177.013384 | 92.081429→53.949672 |
| O_seed1_budget100 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00), 04(02:00-02:30) | 0.000000 | +0 | 175.420163→202.361381 | 2103.706846→2149.591734 | 92.847852→51.845721 |
| O_seed1_budget1000 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00), 04(02:00-02:30) | 0.000000 | +0 | 175.191868→206.248893 | 2090.526218→2164.645959 | 87.548679→53.572182 |
| O_seed2_budget100 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00), 04(02:00-02:30) | 0.000000 | +0 | 202.675442→202.675442 | 2152.946018→2152.946018 | 52.612627→52.612627 |
| O_seed2_budget1000 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00) | 0.000000 | +0 | 207.804309→207.804309 | 2178.418761→2178.418761 | 48.257046→48.257046 |
| O_seed3_budget100 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00), 04(02:00-02:30) | 0.000000 | +0 | 177.691602→204.180360 | 2107.329973→2156.301386 | 89.481844→54.136666 |
| O_seed3_budget1000 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00), 04(02:00-02:30) | 0.000000 | +0 | 174.125076→208.653223 | 2093.742699→2178.475155 | 89.211423→53.572182 |
| P_seed1_budget100 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00), 04(02:00-02:30) | 0.000000 | +0 | 202.361381→202.361381 | 2149.591734→2149.591734 | 51.845721→51.845721 |
| P_seed1_budget1000 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00), 09(04:30-05:00), 10(05:00-05:30) | 0.000000 | +0 | 174.958704→208.046136 | 2077.918907→2179.202259 | 94.165846→49.741055 |
| P_seed2_budget100 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00), 04(02:00-02:30) | 0.000000 | +0 | 202.675442→202.675442 | 2152.946018→2152.946018 | 52.612627→52.612627 |
| P_seed2_budget1000 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00) | 0.000000 | +0 | 173.009736→206.532375 | 2081.785100→2170.813548 | 88.196311→52.922989 |
| P_seed3_budget100 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00) | 0.000000 | +0 | 209.672418→209.672418 | 2183.815200→2183.815200 | 52.060042→52.060042 |
| P_seed3_budget1000 | 50/50; 13264.000/13264.000 | 01(00:30-01:00), 02(01:00-01:30), 03(01:30-02:00) | 0.000000 | +0 | 208.396366→208.396366 | 2179.463282→2179.463282 | 52.604632→52.604632 |

FACT：逐次原始字段、48 槽明细和最终解见证分别保存在 `raw_runs.csv`、`slot_distribution.csv`、`solution_witnesses.json`；本表的前值来自 T5 同键原始记录。
FACT：因修复而增加实体车辆的次数为 0；因修复导致搜索未找到可行解的次数以 `raw_runs.csv` 的缺失键计，本次为 0。
INFERENCE：若修复后实体车数上升，含义是原先路线池依赖了不允许的重叠充电安排；这不等同于证明模型硬不可行。
DECISION：本目录只作为技术缺陷修复验证；`decision.json.paper_claim_allowed=false`。
DECISION：本次未触发 `HALT_REGRESSION_FAILED`、`HALT_REQUIRES_PROTECTED_FILE_CHANGE` 或 `HALT_AWAITING_USER_APPROVAL`。

## 测试套件逐条结果

FACT：全量结果为 898 passed、1 skipped、14 failed。失败逐条原因见 `metadata.json.test_suite.failures`；其中与本次新增硬约束直接相关的旧 in-trip charging fixture 失败均保留，未通过放宽约束消除。
- FAIL：tests/test_china81_shared_completion_20260720.py::test_shared_completion_is_feasible_monotone_and_complete — old test requires charge_day_offset=0; repaired generator emits pre-horizon first-trip charging at -1
- FAIL：tests/test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit — pre-existing protected-contract verdict HALT_FROZEN_PROTECTED_CONTRACT
- FAIL：tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables — pre-existing E5 carbon-aware replay is infeasible
- FAIL：tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts — pre-existing diagnostic labels one case repair_logic_defect
- FAIL：tests/test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps — pre-existing candidate objective is not below initial objective
- FAIL：tests/test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact — pre-existing E4 manifest reports multitrip_schedule.py and check.py drift
- FAIL：tests/test_public_station_multitrip_20260723.py::test_public_station_route_closes_strict_clock_soc_and_certificate — new approved hard constraint correctly rejects in-trip public charging overlap
- FAIL：tests/test_public_station_multitrip_20260723.py::test_public_station_route_passes_mandatory_strict_runtime — same new hard constraint makes the old in-trip public-charge fixture infeasible
- FAIL：tests/test_refined_carbon_charging.py::test_integrated_route_repair_inserts_station_and_remains_fully_feasible — new approved hard constraint correctly rejects in-trip charging overlap
- FAIL：tests/test_refined_carbon_charging.py::test_refined_reset_and_reconstruction_consumes_one_candidate_evaluation — same new hard constraint rejects the old in-trip charging fixture
- FAIL：tests/test_search.py::SearchGateTests::test_h2_initial_solution_contains_deterministic_ev_charging_witness — new hard constraint removes the old in-trip charging witness
- FAIL：tests/test_search.py::SearchGateTests::test_h3_short_alns_has_nonzero_charging_signal — same new hard constraint removes the old in-trip charging witness
- FAIL：tests/test_search.py::SearchGateTests::test_m0_evheavy_initial_solution_respects_fleet_limits_and_charges — same new hard constraint removes the old in-trip charging witness
- FAIL：tests/test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately — pre-existing strong-bridge verdict differs from fixture expectation
