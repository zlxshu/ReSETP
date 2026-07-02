# C1-R1b Bridge-Side Repair Validation

本步目标：让 baseline 的 destroy/repair 桥在 5174 平台解上能产出可行邻居，同时不改变 ALNS 主算法任何行为。

Evidence level: **PROBE / baseline health整改**。这不是正式 T3，不得写算法胜负。

边界：只允许修 `candidates.py` 桥侧调用约定；不改 `feasible_repair.py`、独立 ALNS 后端、成本、约束、价格默认值或 TeX。

Verdict: `BRIDGE_FIXED`

## Plain Reading

baseline destroy/repair 桥已能产出 20-40 路线级可行邻居；本结论只说明 baseline health。

## Phase A None Exit

| policy | none exit | count |
|---|---|---:|
| alns_real_fleet_caps | FALLBACK_FEASIBLE | 3 |
| alns_real_fleet_caps | INSERT_LOOP_EXHAUSTED | 140 |
| alns_real_fleet_caps | REPAIRED_FEASIBLE | 57 |
| bridge_thin_current | FINAL_CHECK_FAILED | 200 |

## Call Convention Diff

| field | baseline bridge | main ALNS | risk |
|---|---|---|---|
| policy.max_cv/max_ev | _ThinPolicy(max_cv=1e9, max_ev=1e9) | SearchPolicy(max_cv=instance.num_cv, max_ev=instance.num_ev) | bridge may enumerate routes that can only fail at final fleet-cap check |
| partial solution | _routes_without_customers + _actions_for_routes | _remove_customers removes empty routes and keeps actions for kept vehicles/stations | mostly equivalent; Phase A records partial route/action counts |
| allow_new_route | always True | True except route_elimination_removal forces False | not a direct mismatch for the five bridge destroy operators |
| None handling | returns infeasible _OperatorOutcome detail=strong_repair_failed | returns source_solution/current state and continues | baseline LNS falls back to decoder path after bridge failure |
| shared repair function | repair_removed_customers from feasible_repair.py | same function | fix must be bridge-side call convention, not shared repair semantics |

## Selected Regression Case

```json
{
  "destroy": "shaw_related_removal",
  "fix_path": "bridge_policy_real_fleet_caps",
  "none_exit": "REPAIRED_FEASIBLE",
  "policy_name": "alns_real_fleet_caps",
  "reason": "first real-fleet policy trace that already produces a feasible changed repair",
  "repair": "greedy_insert_repair",
  "seed": 1,
  "trial": 4
}
```

## D1 LNS Probe

- status: `OK`
- evals: `2000`
- best cost: `3820.476792624678`
- feasible native 20-40 route candidates: `1314`
- native best updates: `19`

## D2 Anchors

- goeke80_100_01_seed2_current_q3650: cost `2677.7953638343815`, expected `2677.7953638343815`, parity `True`.
- threeshift_150c_01_seed1_B280_eval2000: cost `3561.080964207054`, expected `3561.080964207054`, parity `True`.

## D4 Legacy Anchor

```json
{
  "anchor": "goeke80_100_01_seed2_Q1600_in_memory_override",
  "best_cost": 5480.399324501256,
  "elapsed_seconds": 57.04410475000077,
  "failure_reason": "Q_capacity=1600.0 rerun did not reproduce the 4878 legacy scale",
  "note": "D4 is explanatory and does not block BRIDGE_FIXED.",
  "schema": "setp-c1-r1b-legacy-q1600-anchor.v1",
  "status": "LEGACY_ANCHOR_UNEXPLAINED",
  "target_legacy_scale": 4878.331796187524,
  "within_legacy_scale": false
}
```

## Artifacts

- Data dir: `baselines/e2_alns/bridge_fix_validation_data`
- `phase_a_bridge_exit_autopsy.csv`
- `call_convention_diff.csv`
- `selected_regression_case.json`
- `lns_b1_raw_runs.csv`
- `anchor_parity.json`
- `legacy_q1600_anchor.json`
- `decision.json`
- `artifact_hashes.json`
