# C1-R2 Native Channel Autopsy Probe

本步目标：证实或证伪两个代码级假设，回答“四基线原生搜索为何 15958 eval 零改进”。

Evidence level: **PROBE / 非正式 T3**. 本报告不得写成算法胜负或正式 T3 证据。

Verdict: `PARTIAL_OR_WEAK_SUPPORT`

## Plain Reading

H1/H2 没有同时达到预注册确认门槛；只按分项事实报告，不推进正式 T3。

## Gate

- H1 decision: `H1_WEAK_OR_UNRESOLVED`
- H2 decision: `H2_CONFIRMED`
- Collection failures: `0`
- HEAD: `b30c9f2eb9972b13e86a31a2d26000f26e7f23a8`
- Python/numpy: `/opt/anaconda3/bin/python3.13` / `2.3.5`
- Battery override only in memory: `dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)`.

## Static Facts

| check | pass | evidence |
|---|---:|---|
| A1_baseline_forces_true_repair_zero | True | metaheuristic_baselines._baseline_fast_repair_flags sets SETP_ALNS_CRUSH_TRUE_REPAIR to 0 |
| A2_route_scoring_downgrades_to_distance | True | repair_scoring.route_model_cost_delta returns _route_distance_delta when TRUE_REPAIR is disabled |
| A3_e2_alns_uses_true_repair_one | True | winner_operators.e2_alns_variant_flags sets TRUE_REPAIR to 1 |
| A4_decode_fallback_to_all_cv_on_violations | True | check_solution returns violation list; _decode_order_like_random_key falls back to all-CV when violations are present |
| A5_route_plan_feasible_uses_cv_temp_route | True | _route_customer_plan_feasible_cached checks a temporary CV route schedule |

## Run Summaries

| phase | algorithm | condition | status | evals | best cost | native best updates | feasible rate | decode fallback | decode <5174 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| B1 | LNS | true_repair_forced_0_current | OK | 2000 | 5174.345121253789 | 0 | 1.0000 | 0.0000 | 0.0000 |
| B1 | LNS | true_repair_probe_1_no_downgrade | OK | 2000 | 5174.345121253789 | 0 | 1.0000 | 0.0000 | 0.0000 |
| B2 | GA | decode_probe_current | OK | 2000 | 5174.345121253789 | 0 | 1.0000 | 0.0000 | 0.0000 |
| B2 | PSO | decode_probe_current | OK | 2000 | 5174.345121253789 | 0 | 1.0000 | 0.0000 | 0.0000 |

## Flip Closure

| closure | seed | status | cost | matches 5174 | accepted flips | EV share |
|---|---:|---|---:|---|---:|---:|
| random_seeded_flip | 1 | OK | 5174.345121253789 | True | 14 | 0.6818 |
| random_seeded_flip | 2 | OK | 5174.345121253789 | True | 14 | 0.6818 |
| deterministic_best_improvement_flip | 0 | OK | 5174.345121253789 | True | 14 | 0.6818 |

## Artifacts

- Data dir: `baselines/e2_alns/native_channel_autopsy_data`
- Candidate rows: `baselines/e2_alns/native_channel_autopsy_data/raw_runs.csv`
- Decode rows: `baselines/e2_alns/native_channel_autopsy_data/decode_events.csv`
- Best trajectory: `baselines/e2_alns/native_channel_autopsy_data/best_trajectory.csv`
- Flip closure: `baselines/e2_alns/native_channel_autopsy_data/flip_closure.csv`
- Decision: `baselines/e2_alns/native_channel_autopsy_data/decision.json`
- Report copy: `baselines/e2_alns/native_channel_autopsy_data/report.md`
