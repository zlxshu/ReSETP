# T16 两处越界改动撤销报告

**FACT**：本轮只修改 `solver/src/setp_solver/search/multitrip_schedule.py` 两处：第 757 行把零碳权重比较从 `_TOL` 恢复为 `1e-12`；第 1838 行把已准备车辆 ID 判定恢复为 `physical_vehicle_id(route.vehicle_id).startswith(("CV_", "EV_"))`。`_TOL` 常量未改。

**FACT**：没有删除、弱化或搬移任何 `raise`、`assert` 或校验分支。窗口倒挂保护仍位于 `multitrip_schedule.py:719`，分日后无候选保护仍位于 `multitrip_schedule.py:785`；本轮未修改二者。

**FACT**：T15 的 7 项定向测试为 `7 passed`。三个阳性样本均被判 `CHARGING_TRIP_OVERLAP`，重叠秒数分别为：`C_seed2_budget1000 = 6563.0712245500035`、`C_seed1_budget100 = 6365.9078330282355`、`C_seed3_budget1000 = 6239.742124296223`。T10 的 18 个保存解在默认参数下为 `18/18` 合法。

**FACT**：全量命令退出码为 `1`，真实汇总为 `906 passed / 1 skipped / 6 failed`，与 T15 数量及失败节点一致。失败节点为：

- `test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit`
- `test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables`
- `test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts`
- `test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps`
- `test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact`
- `test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately`

**FACT**：三个受保护文件本轮开工/收工 SHA-256 逐位一致：`cost.py = e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`、`check.py = 1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`、`search/evaluation.py = c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

**FACT**：未改变碳感知择时打分器是否落进主代码、三种车场充电窗口模式取舍、公共站充电候选地位或首趟充电跨日核算口径；未修改两个论文目录。

**INFERENCE**：无。本轮仅恢复 T15 之前的两处既有语义。

**DECISION**：两处撤销及全部规定回归门完成；`paper_claim_allowed=false`。

**HALT_NONE**：没有触发本任务的停止条件。
