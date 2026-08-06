# T18 公共充电站并列候选实施与回归记录

## FACT

本轮只改动两个源文件：`solver/src/setp_solver/algorithms/resetp_alns/support/charging.py` 与 `solver/src/setp_solver/china81_completion.py`。新增显式开关 `public_station_candidate_mode`，合法值为 `fallback` 与 `parallel`，默认值为 `fallback`。默认模式只生成既有车场优先路径；并列模式同时保留车场完成全部补电的路径，以及“车场只补到可达公共站的启动电量、公共站完成余量”的路径。

两类路径没有新建打分式。`repair_route_charging` 的局部选择调用既有 `search/evaluation.py::score_reference`，即完整 `evaluate + check_solution`；China81 补全器则把两类路径都保留为 `RouteCompletionVariant`，继续通过既有 `_single_route_cost` 排序与 `exact_china81_score` 完整检查/评价后选择。因此绕路里程、绕路时间、充电电费（公共电价已含服务费）、公共站占用费和充电排放均来自现有目标函数与检查器。站点窗口、容量、SOC、非线性充电曲线和实体车时钟检查均未放宽。

最小构造采用 `cn-jjj-50c-01-V2-LOCATIONS` 的 `D_beijing`、`S_beijing`、`C003` 原始节点、原始道路矩阵、原始电价/碳强度和原始车辆参数，构造单客户路线 `D_beijing -> C003 -> D_beijing`。为排除其余 49 个客户带来的共同覆盖罚项，实例节点仅裁成上述三个节点；没有修改源算例。两候选均通过 `check_solution`，违反数均为 0。

| 候选 | 路线与充电动作 | 完整目标值（CNY） | 里程（m） | 充电电费（CNY） | 排放（kgCO2e） | 占用费（CNY） | 时间成本（CNY） |
|---|---|---:|---:|---:|---:|---:|---:|
| 车场 | `D_beijing -> C003 -> D_beijing`；车场充 `25.916999095976912 kWh` | `245.8269329581829` | `80371.46081407` | `21.678085995586443` | `3.9985099596052143` | `0.0` | `0.0` |
| 公共站 | `D_beijing -> S_beijing -> C003 -> D_beijing`；车场启动充 `9.106677626956689 kWh`，公共站充 `18.983927832016718 kWh` | `267.38322772138827` | `87555.644999438` | `28.602201671528793` | `8.354838499436376` | `9.491963916008359` | `0.0` |

公共站动作按原公共总电价计费，其中服务费部分为 `18.983927832016718 * 0.4 = 7.593571132806687 CNY`；该数已包含在表中公共路径的充电电费。当前臂的时间成本系数使两条路径的 `cost_time` 都为 `0.0`，但两条路径仍由现有完整评价器读取并核算路程时间，没有另造或跳过时间项。公共路径比车场路径高 `21.556294763205358 CNY`，最终选择 `depot_fallback`。

第一次最小探针曾失败：当时把公共路径定义为完全不在车场启动充电，而 bundle 的实际初始电量为 `0.0 kWh`，公共候选数为 `1`，精确异常为 `ValueError: No feasible charging insert between D_beijing and C003`，进程退出码为 `1`。该失败未被解释为正确拒绝；实现随后限定为只在 `parallel` 模式下生成满足可达性的车场启动充电，再重新执行全部定向门。

默认模式定向 7 项最终结果为 `7 passed in 3.49s`。三个阳性样本均仍报告唯一 `CHARGING_TRIP_OVERLAP`：`C_seed2_budget1000 = 6563.0712245500035 s`、`C_seed1_budget100 = 6365.9078330282355 s`、`C_seed3_budget1000 = 6239.742124296223 s`。T10 归档为 `18/18` 个解零违反。

全量命令为 `PYTHONHASHSEED=0 PYTHONPATH=solver/src:models/src PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/bin/python3.13 -m pytest -q -p no:cacheprovider solver/tests`。精确结果为 `905 passed / 1 skipped / 7 failed in 425.13s`，不等于验收要求的 `906 passed / 1 skipped / 6 failed`。七个失败及精确断言值如下：

1. `test_alns_budget_accounting_g0_20260718.py::test_g0_static_audit_has_zero_blockers_and_five_surfaces`：实际 `HALT_ALNS_BUDGET_CLOSURE_REQUIRED`，期望 `PASS_ALNS_BUDGET_G0_STATIC_CLOSURE`。
2. `test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit`：实际 `HALT_FROZEN_PROTECTED_CONTRACT`，期望 `FROZEN_PROTECTED_CONTRACT_OK`。
3. `test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables`：`report["carbon_aware"]["feasible"]` 实际为 `False`，期望为真。
4. `test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts`：至少一行 `root_cause` 实际为 `repair_logic_defect`，断言要求不得等于该值。
5. `test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps`：`candidate_obj = 4954.208671718898`，`initial_obj = 4923.557583344485`，未满足严格小于。
6. `test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact`：E4 全局清单返回 2 项哈希漂移，涉及 `solver/src/setp_solver/search/multitrip_schedule.py` 与 `solver/src/setp_solver/check.py`，期望空列表。
7. `test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately`：实际 `HALT_STRONG_BRIDGE_BACKEND_PROFILE_ALIGNMENT`，期望 `A3_BACKEND_LOCAL_SEARCH_NOT_SUPPORTED`。

受保护文件开工与收工 SHA-256 完全一致：`cost.py = e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d`，`check.py = 1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072`，`search/evaluation.py = c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3`。

按文件修改时间隔离，本轮人工源代码改动只有上述两个文件。全量测试另刷新了 `.e7_stage_bundles` 测试夹具、`test_tmp_nondeterminism/phase1_env_fingerprints.json` 与 `__pycache__`；后台 watchdog 同期刷新其日志。这些均未作为 T18 源代码改动，`._*`、`__pycache__`、`.pytest_cache` 不进入产物哈希。

## INFERENCE

最小构造已经证明 `parallel` 模式会生成公共站路径、把它送入既有完整目标函数并据值选择；在该构造中公共站没有胜出，数值原因是里程、公共总电价/服务费、占用费与排放共同使目标值高出 `21.556294763205358 CNY`。

全量比规定基线多 1 个失败。依据本轮停止条件，不能在本轮继续归因、修复或把任何失败认定为合理拒绝；因此本轮实现不能通过验收，也不能用于论文主张。

## DECISION

默认值保持 `fallback`；`parallel` 只在调用者显式开启时生效。未改变 `charge_timing_policy` 的四个取值或默认 `carbon_min`，未改变 `depot_charge_window_mode` 的三个取值，未改变首趟跨日核算口径、碳价、碳数据源、电价、算例、车队合同、目标函数经济含义、`_TOL`、窗口倒挂保护及三个受保护文件。

没有删除或弱化任何既有 `raise`、`assert` 或校验分支。原 `repair_route_charging` 的主体被放入 `_repair_route_charging_candidate` 后，三个直接异常分支的去向为：未知策略异常现位于 `charging.py:505`；无可用公共站异常现位于 `charging.py:584`；无法插站异常现位于 `charging.py:607`。三者条件与消息不变，默认 `fallback` 路径仍逐级传播。`parallel` 中捕获 `ValueError` 只用于淘汰新增的某个公共候选，发生在默认路径成功生成之后，不截获默认路径异常。其余既有验证器调用与异常分支未移动、未删除；新增了模式值验证与启动电量边界验证。

`paper_claim_allowed=false`。

## HALT_REGRESSION_FAILED

全量回归门实际为 `905 passed / 1 skipped / 7 failed`，不满足规定值。已停止，不再运行测试、不改测试、不放宽约束、不调阈值、不继续修补。
