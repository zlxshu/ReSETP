# 09u Wall-Clock Battery Preflight

Verdict: `PREFLIGHT_COMPLETE`

## Plain Reading

测试数据收齐，可以比较同等时间、降预算和100kWh对车队构成的影响。

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- 09s warm start rows OK: `True` with `69` rows

## Scenario Summary

| scenario | mode | battery kWh | pairs | paired winners | mean gap % ALNS-LNS | mean EV route share 75-200 | failures |
|---|---|---:|---:|---|---:|---:|---:|
| wc100 | wallclock | 100.0 | 23 | {"alns": 2, "lns": 1, "tie": 20} | 0.5926 | 0.0573 | 0 |
| wc80 | wallclock | 80.0 | 23 | {"alns": 2, "lns": 1, "tie": 20} | -2.0424 | 0.0573 | 0 |

## Artifacts

- Data dir: `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data`
- Raw rows: `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data/raw_runs.csv`
- Paired summary: `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data/paired_summary.csv`
- Scale summary: `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data/scale_summary.csv`
- Scenario summary: `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry_data/scenario_summary.csv`
- Report: `baselines/e2_alns/wallclock_battery_preflight_wallclock_retry.md`
- HEAD at run start: `f72c31cc8a2f3321050580cbab2c3c18e58b4ec7`
- Artifact commit hash: `pending`

## Interpretation Rules

- `wc80/wc100` compare algorithms by equal wall-clock caps; under-eval is acceptable if a zero-violation incumbent is returned.
- `budget8k80/budget8k100` test whether a lower fixed budget can close inside the same caps; under-eval remains a collection failure.
- `100kWh` is an in-memory diagnostic override only. It is not promoted to a default parameter by this report.
- Goeke80 is interpreted as a Goeke baseline scene unless a later evidence-backed scenario is selected for the mixed-fleet story.
