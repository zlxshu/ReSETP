# 280kWh Fleet-Composition Gate

Commit: `48484b41`.
Artifact commit: `a8234035`.
Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.
Prices: `B_battery_kwh=280.0`, `v_speed_ms=25.0`, `carbon_price=0.05034`.
Command: `/opt/anaconda3/bin/python3.13 baselines/e2_alns/fleet_composition_gate_280.py --instance-set smoke --eval-budget 300 --runtime-cap-small 30 --runtime-cap-medium 45 --runtime-cap-large 60 --task-timeout-buffer 10`.

## Verdict

`HALT_COLLECTION_COST` (`staged_probe`).

The gate did not collect a complete auditable optimization set.

This gate is about route-type composition after the 280kWh update. It does not change model parameters or solver semantics.

## Scope

- Instances audited: 3.
- Raw optimization rows: 9.
- Winner rows: 3.
- Seeds: 1.
- Eval budget per run: 300.

Variant labels are search-shell settings only. The composition columns below are based on actual returned `cv_route_count` and `ev_route_count` after independent `evaluate/check` replay.

## Instance Summary

| instance | ok seeds | all-EV | EV-heavy | balanced | CV-heavy | all-CV | mean EV share |
|---|---:|---:|---:|---:|---:|---:|---:|
| multidepot/e2-multidepot-100c-01 | 1 | 0 | 0 | 1 | 0 | 0 | 0.686 |
| threeshift/e2-threeshift-200c-01 | 1 | 0 | 0 | 1 | 0 | 0 | 0.681 |
| vanilla/e2-vanilla-25c-01 | 1 | 0 | 0 | 1 | 0 | 0 | 0.429 |

## Winner Rows

| instance | seed | winner | composition | CV | EV | cost |
|---|---:|---|---|---:|---:|---:|
| multidepot/e2-multidepot-100c-01 | 1 | free_mixed | balanced_mixed | 11 | 24 | 4913.698 |
| threeshift/e2-threeshift-200c-01 | 1 | free_mixed | balanced_mixed | 22 | 47 | 9237.063 |
| vanilla/e2-vanilla-25c-01 | 1 | ev_shell | balanced_mixed | 4 | 3 | 1197.055 |

## Output Files

- `baselines/e2_alns/280kwh_fleet_composition_gate_data/metadata.json`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/phase0_instance_audit.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/raw_runs.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/winners.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/composition_summary.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/conclusion.json`

## Next Decision Rule

If this gate remains `HALT_ALL_EV` or `HALT_EV_DOMINANT` under stronger budgets, the paper should not frame 280kWh as universally producing a balanced mixed fleet. The honest fallback is to report that modern-battery regional instances become EV-dominant, then decide whether a smaller evidence-bound battery scenario is needed for a balanced-mix narrative.
