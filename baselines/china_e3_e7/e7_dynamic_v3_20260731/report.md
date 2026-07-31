# E7 动态需求实验

状态：`PASS_WIRING_SELFCHECK_ALL_GREEN`。正式探针尚未启动，完整候选搜索评价数为 0。

## 启动接线自检

| 门 | 结果 | 证据 |
|---|---|---|
| protected_hashes | `PASS` | 6 frozen files matched |
| all_input_files | `PASS` | 42 frozen input paths loaded and hashed |
| china81_source_fields | `PASS` | 8/8 named source fields matched for all three scales |
| event_and_rolling_fields | `PASS` | 15 streams, 375 events, 68 trigger batches |
| e4_dual_day_calendar | `PASS` | offset -1=2025-02-11; offset 0=2025-02-12 |
| explicit_prices | `PASS` | China81 PriceParameters supplied to both initial variants |
| arm_construction | `PASS` | 4/4 arm configurations constructed |
| minimum_complete_model_evaluation | `PASS` | 4/4 finite objectives; 0 hard violations; 0 search evaluations |
| whole_trip_release_state | `PASS` | first trigger cut passed for 50c, 100c, and 150c with certified terminal EV batteries |
| in_progress_route_charging_witness | `PASS` | every locked action at the first trigger has a contemporaneous window witness in all three scales |
| result_field_alignment | `PASS` | actual_evaluations is the canonical task result field |
| alns_current_objective_binding | `PASS` | FULL_ROLLING, NO_COOPERATION, and CARBON_BLIND first-stage search states have finite reference objectives with zero candidate evaluations |
| spawn_worker_serialization | `PASS` | v3 worker pickled under module resetp_e7_dynamic_preregistered_runner (71 bytes) |
| legal_infeasible_classification | `PASS` | 50c STATIC_FIXED_RECOURSE stage 1 retained as LEGAL_INFEASIBLE with null objective and 0 evaluations |
| trace_mode_guard | `PASS` | formal trace_mode=false dispatches directly without convergence-trace row assertions |
| no_executable_continuation_classification | `PASS` | the rolling gate dedicated NoExecutableContinuation class is included in the LEGAL_INFEASIBLE terminal predicate |

本轮系统审计登记并修复 11 项接线问题：China81 八源文件字段、显式 China81 prices、offset −1 前一日电网曲线，以及`actual_evaluations` 结果字段对齐与整趟路线终态电量释放。运行日为 2025-02-12，首趟预充按 E4 权威口径使用 2025-02-11；v3 与批准 v4 的共享时变字段已逐行闭合。

四臂零搜索最小模型评价均已返回有限目标值：

| 臂 | 路线搜索 | 目标值 | 硬违反 |
|---|---:|---:|---:|
| STATIC_FIXED_RECOURSE | false | 2418.475408 | 0 |
| FULL_ROLLING | true | 2418.475408 | 0 |
| NO_COOPERATION | true | 2418.475408 | 0 |
| CARBON_BLIND | true | 2305.468523 | 0 |

## 待运行阶段

收敛探针、50c、100c、150c、独立复算与正式统计表将在后续阶段逐项写入本报告。
