# 09y Stage A Three-Shift 280kWh Construction Generalization

Evidence level: **PROBE / 非正式 T3**. This is a construction diagnostic, not formal T3.

Verdict: `THREESHIFT_MIXED_GENERALIZES`

## Plain Reading

280kWh 下至少两个三班实例构造出零违约、EV≥30%、成本和总碳都不劣于全-CV 的非退化混合解。

## Gate

- Pass rule: `EV route share >= 0.30`, `violation_count = 0`, `cost gap % <= 0`, and `E_total gap % <= 0` versus the all-CV/near-CV baseline.
- Passing instances: `8/9`
- Pass list: `e2-threeshift-100c-02, e2-threeshift-100c-03, e2-threeshift-150c-01, e2-threeshift-150c-02, e2-threeshift-150c-03, e2-threeshift-200c-01, e2-threeshift-200c-02, e2-threeshift-200c-03`

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- Diagnostic battery override: `280.0` kWh
- HEAD: `e1a90b08c1dcd7877943245ad444e57cd8855872`

## Construction Rows

| instance | EV route share | violation_count | cost gap % | E_total gap % | low-carbon charging share | charging actions | pass | verdict |
|---|---:|---:|---:|---:|---:|---:|---|---|
| e2-threeshift-100c-01 | 0.2667 | 0 | -3.0411 | -12.8058 | 0.0055 | 4 | no | X_SEARCH_MISSED_FEASIBLE_EV |
| e2-threeshift-100c-02 | 0.4286 | 0 | -4.9878 | -21.3974 | 0.0888 | 6 | yes | X_SEARCH_MISSED_FEASIBLE_EV |
| e2-threeshift-100c-03 | 0.4667 | 0 | -8.3323 | -38.5444 | 0.1080 | 7 | yes | X_SEARCH_MISSED_FEASIBLE_EV |
| e2-threeshift-150c-01 | 0.4545 | 0 | -6.7564 | -28.4787 | 0.0400 | 10 | yes | X_SEARCH_MISSED_FEASIBLE_EV |
| e2-threeshift-150c-02 | 0.5238 | 0 | -8.8627 | -39.9245 | 0.1040 | 11 | yes | X_SEARCH_MISSED_FEASIBLE_EV |
| e2-threeshift-150c-03 | 0.4500 | 0 | -6.5615 | -28.1597 | 0.0330 | 9 | yes | X_SEARCH_MISSED_FEASIBLE_EV |
| e2-threeshift-200c-01 | 0.4074 | 0 | -5.5628 | -24.5370 | 0.0219 | 11 | yes | X_SEARCH_MISSED_FEASIBLE_EV |
| e2-threeshift-200c-02 | 0.4286 | 0 | -6.6863 | -30.5307 | 0.0324 | 12 | yes | X_SEARCH_MISSED_FEASIBLE_EV |
| e2-threeshift-200c-03 | 0.4828 | 0 | -7.3580 | -32.9987 | 0.0479 | 14 | yes | X_SEARCH_MISSED_FEASIBLE_EV |

## Failure Reasons

| instance | failure_reason | count |
|---|---|---:|
| e2-threeshift-100c-01 | ACCEPTED | 3 |
| e2-threeshift-100c-01 | CHARGING_TIME_WINDOW_DETOUR | 9 |
| e2-threeshift-100c-02 | ACCEPTED | 5 |
| e2-threeshift-100c-02 | CHARGING_TIME_WINDOW_DETOUR | 6 |
| e2-threeshift-100c-03 | ACCEPTED | 6 |
| e2-threeshift-100c-03 | CHARGING_TIME_WINDOW_DETOUR | 5 |
| e2-threeshift-150c-01 | ACCEPTED | 9 |
| e2-threeshift-150c-01 | CHARGING_TIME_WINDOW_DETOUR | 7 |
| e2-threeshift-150c-02 | ACCEPTED | 10 |
| e2-threeshift-150c-02 | CHARGING_TIME_WINDOW_DETOUR | 3 |
| e2-threeshift-150c-03 | ACCEPTED | 8 |
| e2-threeshift-150c-03 | CHARGING_TIME_WINDOW_DETOUR | 6 |
| e2-threeshift-200c-01 | ACCEPTED | 10 |
| e2-threeshift-200c-01 | CHARGING_TIME_WINDOW_DETOUR | 12 |
| e2-threeshift-200c-02 | ACCEPTED | 11 |
| e2-threeshift-200c-02 | CHARGING_TIME_WINDOW_DETOUR | 11 |
| e2-threeshift-200c-03 | ACCEPTED | 13 |
| e2-threeshift-200c-03 | CHARGING_TIME_WINDOW_DETOUR | 8 |

## Artifacts

- Data dir: `baselines/e2_alns/threeshift_280_stageA_generalization_data`
- Report: `baselines/e2_alns/threeshift_280_stageA_generalization.md`
- HEAD at run start: `e1a90b08c1dcd7877943245ad444e57cd8855872`
- Carbon price fixed at `0.05034`; protected solver semantics unchanged.
- Battery capacity was applied only with in-memory `dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)`.
