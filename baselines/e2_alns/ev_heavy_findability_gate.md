# 09z ALNS EV-heavy Findability Gate

Evidence level: **PROBE / 非正式 T3**. This is a diagnostic gate, not formal T3.

Verdict: `HALT_SEARCH_CANNOT_USE_EV_PATH`

## 人话结论

审计能找到可行且不劣的 EV 转换，但搜索没有用上；下一步应设计专门 EV-conversion operator，而不是加时间。

这一步只回答：不给 EV-heavy 答案，搜索能不能自己找到。它不证明正式算法胜负。

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- Diagnostic battery override: `280.0` kWh
- HEAD: `628799742fa50877329c8d042537c4425eb11c1e`

## Search Rows

| algorithm | seed | initial | best | closed gap | EV gain | evals | returned initial | improvements |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| GA | 1 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 9229 | True | 0 |
| LNS | 1 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 11146 | True | 0 |
| PSO | 1 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 16000 | True | 0 |
| VNS | 1 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 13297 | True | 0 |
| alns_e2_carbon | 1 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 2667 | True | 0 |
| alns_e2_carbon_ablation | 1 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 9617 | True | 0 |
| alns_e2_throughput | 1 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 15006 | True | 0 |
| GA | 2 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 9229 | True | 0 |
| LNS | 2 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 11479 | True | 0 |
| PSO | 2 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 16000 | True | 0 |
| VNS | 2 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 13026 | True | 0 |
| alns_e2_carbon | 2 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 2789 | True | 0 |
| alns_e2_carbon_ablation | 2 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 10631 | True | 0 |
| alns_e2_throughput | 2 | 5803.553350 | 5803.553350 | 0.0000 | 0.0000 | 16000 | True | 0 |

## EV Swap Audit

- Audit rows: `21`
- Accepted non-worse CV→EV conversions: `14`

| failure_reason | count |
|---|---:|
| ACCEPTED | 14 |
| CHARGING_TIME_WINDOW_DETOUR | 7 |

## Artifacts

- Data dir: `baselines/e2_alns/ev_heavy_findability_gate_data`
- Report: `baselines/e2_alns/ev_heavy_findability_gate.md`
- Raw rows: `baselines/e2_alns/ev_heavy_findability_gate_data/raw_runs.csv`
- Swap audit rows: `baselines/e2_alns/ev_heavy_findability_gate_data/ev_swap_audit_rows.csv`
- Protected referee files unchanged: `cost.py`, `check.py`, `evaluation.py`, `prices.py`.
