# 09z ALNS EV-heavy Findability Gate

Evidence level: **PROBE / 非正式 T3**. This is a diagnostic gate, not formal T3.

Verdict: `PASS_ALNS_FIND_SIGNAL`

## 人话结论

至少一个 ALNS 变体从中性起点出现找到 EV-heavy 的信号；允许进入单实例长跑复核。

这一步只回答：不给 EV-heavy 答案，搜索能不能自己找到。它不证明正式算法胜负。

## Phase 0

- Phase0 OK: `True`
- Defaults probe: `{"B": 80.0, "Q": 3650.0, "carbon": 0.05034, "numpy": "2.3.5", "python": "/opt/anaconda3/bin/python3.13", "v": 25.0}`
- Diagnostic battery override: `280.0` kWh
- HEAD: `628799742fa50877329c8d042537c4425eb11c1e`

## Search Rows

| algorithm | seed | initial | best | closed gap | EV gain | evals | returned initial | improvements |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| alns_e2_carbon_ablation | 1 | 5803.553350 | 3639.825274 | 5.5182 | 0.7727 | 3000 | False | 73 |
| alns_e2_throughput | 1 | 5803.553350 | 3701.578910 | 5.3607 | 0.7806 | 3000 | False | 68 |
| alns_e2_carbon_ablation | 2 | 5803.553350 | 3364.771719 | 6.2196 | 0.8117 | 3000 | False | 65 |
| alns_e2_throughput | 2 | 5803.553350 | 3364.829838 | 6.2195 | 0.8117 | 2647 | False | 64 |

## EV Swap Audit

- Audit rows: `0`
- Accepted non-worse CV→EV conversions: `0`

| failure_reason | count |
|---|---:|

## Artifacts

- Data dir: `baselines/e2_alns/ev_heavy_findability_gate_policy_fix_probe_data`
- Report: `baselines/e2_alns/ev_heavy_findability_gate_policy_fix_probe.md`
- Raw rows: `baselines/e2_alns/ev_heavy_findability_gate_policy_fix_probe_data/raw_runs.csv`
- Swap audit rows: `baselines/e2_alns/ev_heavy_findability_gate_policy_fix_probe_data/ev_swap_audit_rows.csv`
- Protected referee files unchanged: `cost.py`, `check.py`, `evaluation.py`, `prices.py`.
