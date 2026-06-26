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
| wc100 | wallclock | 100.0 | 3 | {"alns": 1, "tie": 2} | -10.2096 | 0.0519 | 0 |
| wc80 | wallclock | 80.0 | 3 | {"alns": 1, "tie": 2} | -9.5949 | 0.0519 | 0 |

## Artifacts

- Data dir: `baselines/e2_alns/wallclock_battery_preflight_smoke_data`
- Raw rows: `baselines/e2_alns/wallclock_battery_preflight_smoke_data/raw_runs.csv`
- Paired summary: `baselines/e2_alns/wallclock_battery_preflight_smoke_data/paired_summary.csv`
- Scale summary: `baselines/e2_alns/wallclock_battery_preflight_smoke_data/scale_summary.csv`
- Scenario summary: `baselines/e2_alns/wallclock_battery_preflight_smoke_data/scenario_summary.csv`
- Report: `baselines/e2_alns/wallclock_battery_preflight_smoke.md`
- HEAD at run start: `c03ef202d3f60b6dee583a9dc1ae5c63025f2886`
- Artifact commit hash: `pending`

## Interpretation Rules

- `wc80/wc100` compare algorithms by equal wall-clock caps; under-eval is acceptable if a zero-violation incumbent is returned.
- `budget8k80/budget8k100` test whether a lower fixed budget can close inside the same caps; under-eval remains a collection failure.
- `100kWh` is an in-memory diagnostic override only. It is not promoted to a default parameter by this report.
- Goeke80 is interpreted as a Goeke baseline scene unless a later evidence-backed scenario is selected for the mixed-fleet story.
