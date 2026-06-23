# 280kWh Fleet-Composition Gate

Commit: `b6930603`.
Artifact commit: `2086d24b`.
Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.
Prices: `B_battery_kwh=280.0`, `v_speed_ms=25.0`, `carbon_price=0.05034`.
Command: `/opt/anaconda3/bin/python3.13 baselines/e2_alns/fleet_composition_gate_280.py --instance-set representative --seeds 1 2 3 --eval-budget 3000 --runtime-cap-small 180 --runtime-cap-medium 300 --runtime-cap-large 900 --task-timeout-buffer 60 --workers 3`.

## Verdict

`HALT_EV_DOMINANT` (`staged_probe`).

280kWh fixes all-CV pressure but the current winner set is EV-dominant; report composition before broad reruns.

This gate is about route-type composition after the 280kWh update. It does not change model parameters or solver semantics.

## Scope

- Stage: manual.
- Instances audited: 17.
- Raw optimization rows: 153 / expected 153.
- Missing raw rows: 0.
- Winner rows: 51 / expected 51.
- Missing winner rows: 0.
- Seeds: 1, 2, 3.
- Eval budget per run: 3000.
- Workers: 3.

Variant labels are search-shell settings only. The composition columns below are based on actual returned `cv_route_count` and `ev_route_count` after independent `evaluate/check` replay.

## Instance Summary

| instance | ok seeds | all-EV | EV-heavy | balanced | CV-heavy | all-CV | mean CV | mean EV | mean EV share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| multidepot/e2-multidepot-100c-01 | 3 | 0 | 3 | 0 | 0 | 0 | 2.7 | 32.0 | 0.923 |
| multidepot/e2-multidepot-150c-01 | 3 | 3 | 0 | 0 | 0 | 0 | 0.0 | 53.0 | 1.000 |
| multidepot/e2-multidepot-200c-01 | 3 | 0 | 3 | 0 | 0 | 0 | 1.7 | 70.0 | 0.977 |
| multidepot/e2-multidepot-25c-01 | 3 | 1 | 2 | 0 | 0 | 0 | 0.7 | 7.0 | 0.911 |
| multidepot/e2-multidepot-50c-01 | 3 | 1 | 2 | 0 | 0 | 0 | 0.7 | 16.0 | 0.960 |
| multidepot/e2-multidepot-75c-01 | 3 | 0 | 3 | 0 | 0 | 0 | 2.3 | 24.0 | 0.911 |
| threeshift/e2-threeshift-100c-01 | 3 | 2 | 1 | 0 | 0 | 0 | 0.3 | 32.3 | 0.990 |
| threeshift/e2-threeshift-150c-01 | 3 | 0 | 3 | 0 | 0 | 0 | 1.7 | 51.7 | 0.969 |
| threeshift/e2-threeshift-200c-01 | 3 | 2 | 1 | 0 | 0 | 0 | 0.3 | 69.7 | 0.995 |
| threeshift/e2-threeshift-50c-01 | 3 | 3 | 0 | 0 | 0 | 0 | 0.0 | 15.7 | 1.000 |
| threeshift/e2-threeshift-75c-01 | 3 | 1 | 2 | 0 | 0 | 0 | 0.7 | 25.0 | 0.974 |
| vanilla/e2-vanilla-100c-01 | 3 | 0 | 3 | 0 | 0 | 0 | 2.3 | 32.0 | 0.932 |
| vanilla/e2-vanilla-150c-01 | 3 | 1 | 1 | 0 | 0 | 1 | 16.3 | 34.3 | 0.653 |
| vanilla/e2-vanilla-200c-01 | 3 | 0 | 3 | 0 | 0 | 0 | 2.3 | 71.0 | 0.968 |
| vanilla/e2-vanilla-25c-01 | 3 | 2 | 1 | 0 | 0 | 0 | 0.3 | 7.0 | 0.952 |
| vanilla/e2-vanilla-50c-01 | 3 | 0 | 3 | 0 | 0 | 0 | 1.7 | 14.7 | 0.898 |
| vanilla/e2-vanilla-75c-01 | 3 | 0 | 3 | 0 | 0 | 0 | 3.7 | 23.0 | 0.862 |

## Winner Rows

| instance | seed | winner | composition | CV | EV | cost |
|---|---:|---|---|---:|---:|---:|
| multidepot/e2-multidepot-100c-01 | 1 | ev_shell | ev_heavy_mixed | 2 | 32 | 4670.563 |
| multidepot/e2-multidepot-100c-01 | 2 | ev_shell | ev_heavy_mixed | 2 | 33 | 4761.679 |
| multidepot/e2-multidepot-100c-01 | 3 | free_mixed | ev_heavy_mixed | 4 | 31 | 4844.389 |
| multidepot/e2-multidepot-150c-01 | 1 | ev_shell | all_ev | 0 | 51 | 6668.788 |
| multidepot/e2-multidepot-150c-01 | 2 | free_mixed | all_ev | 0 | 53 | 6875.596 |
| multidepot/e2-multidepot-150c-01 | 3 | ev_shell | all_ev | 0 | 55 | 7093.296 |
| multidepot/e2-multidepot-200c-01 | 1 | ev_shell | ev_heavy_mixed | 2 | 70 | 9184.930 |
| multidepot/e2-multidepot-200c-01 | 2 | ev_shell | ev_heavy_mixed | 2 | 70 | 9139.850 |
| multidepot/e2-multidepot-200c-01 | 3 | free_mixed | ev_heavy_mixed | 1 | 70 | 9025.213 |
| multidepot/e2-multidepot-25c-01 | 1 | free_mixed | ev_heavy_mixed | 1 | 7 | 1004.425 |
| multidepot/e2-multidepot-25c-01 | 2 | free_mixed | ev_heavy_mixed | 1 | 6 | 929.939 |
| multidepot/e2-multidepot-25c-01 | 3 | ev_shell | all_ev | 0 | 8 | 977.122 |
| multidepot/e2-multidepot-50c-01 | 1 | ev_shell | ev_heavy_mixed | 1 | 16 | 2262.471 |
| multidepot/e2-multidepot-50c-01 | 2 | ev_shell | ev_heavy_mixed | 1 | 15 | 2217.306 |
| multidepot/e2-multidepot-50c-01 | 3 | free_mixed | all_ev | 0 | 17 | 2207.100 |
| multidepot/e2-multidepot-75c-01 | 1 | ev_shell | ev_heavy_mixed | 1 | 25 | 3682.666 |
| multidepot/e2-multidepot-75c-01 | 2 | ev_shell | ev_heavy_mixed | 4 | 22 | 3836.580 |
| multidepot/e2-multidepot-75c-01 | 3 | ev_shell | ev_heavy_mixed | 2 | 25 | 3852.430 |
| threeshift/e2-threeshift-100c-01 | 1 | free_mixed | ev_heavy_mixed | 1 | 33 | 4757.717 |
| threeshift/e2-threeshift-100c-01 | 2 | ev_shell | all_ev | 0 | 33 | 4596.893 |
| threeshift/e2-threeshift-100c-01 | 3 | free_mixed | all_ev | 0 | 31 | 4394.117 |
| threeshift/e2-threeshift-150c-01 | 1 | ev_shell | ev_heavy_mixed | 1 | 51 | 6981.465 |
| threeshift/e2-threeshift-150c-01 | 2 | free_mixed | ev_heavy_mixed | 2 | 52 | 7240.016 |
| threeshift/e2-threeshift-150c-01 | 3 | ev_shell | ev_heavy_mixed | 2 | 52 | 7378.179 |
| threeshift/e2-threeshift-200c-01 | 1 | ev_shell | all_ev | 0 | 70 | 8848.608 |
| threeshift/e2-threeshift-200c-01 | 2 | free_mixed | ev_heavy_mixed | 1 | 69 | 8894.849 |
| threeshift/e2-threeshift-200c-01 | 3 | ev_shell | all_ev | 0 | 70 | 8866.207 |
| threeshift/e2-threeshift-50c-01 | 1 | ev_shell | all_ev | 0 | 16 | 2186.094 |
| threeshift/e2-threeshift-50c-01 | 2 | ev_shell | all_ev | 0 | 15 | 2147.093 |
| threeshift/e2-threeshift-50c-01 | 3 | free_mixed | all_ev | 0 | 16 | 2142.317 |
| threeshift/e2-threeshift-75c-01 | 1 | free_mixed | ev_heavy_mixed | 1 | 24 | 3554.695 |
| threeshift/e2-threeshift-75c-01 | 2 | free_mixed | ev_heavy_mixed | 1 | 25 | 3491.494 |
| threeshift/e2-threeshift-75c-01 | 3 | free_mixed | all_ev | 0 | 26 | 3482.939 |
| vanilla/e2-vanilla-100c-01 | 1 | free_mixed | ev_heavy_mixed | 2 | 31 | 5173.281 |
| vanilla/e2-vanilla-100c-01 | 2 | free_mixed | ev_heavy_mixed | 3 | 32 | 5419.412 |
| vanilla/e2-vanilla-100c-01 | 3 | free_mixed | ev_heavy_mixed | 2 | 33 | 5386.207 |
| vanilla/e2-vanilla-150c-01 | 1 | ev_shell | ev_heavy_mixed | 2 | 48 | 6712.249 |
| vanilla/e2-vanilla-150c-01 | 2 | cv_shell | all_cv | 47 | 0 | 7362.084 |
| vanilla/e2-vanilla-150c-01 | 3 | free_mixed | all_ev | 0 | 55 | 7257.092 |
| vanilla/e2-vanilla-200c-01 | 1 | free_mixed | ev_heavy_mixed | 2 | 70 | 10342.389 |
| vanilla/e2-vanilla-200c-01 | 2 | free_mixed | ev_heavy_mixed | 4 | 69 | 10377.838 |
| vanilla/e2-vanilla-200c-01 | 3 | free_mixed | ev_heavy_mixed | 1 | 74 | 10600.331 |
| vanilla/e2-vanilla-25c-01 | 1 | ev_shell | ev_heavy_mixed | 1 | 6 | 1076.841 |
| vanilla/e2-vanilla-25c-01 | 2 | free_mixed | all_ev | 0 | 7 | 1032.204 |
| vanilla/e2-vanilla-25c-01 | 3 | ev_shell | all_ev | 0 | 8 | 1135.439 |
| vanilla/e2-vanilla-50c-01 | 1 | free_mixed | ev_heavy_mixed | 2 | 14 | 2453.213 |
| vanilla/e2-vanilla-50c-01 | 2 | free_mixed | ev_heavy_mixed | 2 | 15 | 2563.366 |
| vanilla/e2-vanilla-50c-01 | 3 | free_mixed | ev_heavy_mixed | 1 | 15 | 2443.660 |
| vanilla/e2-vanilla-75c-01 | 1 | ev_shell | ev_heavy_mixed | 4 | 23 | 4362.899 |
| vanilla/e2-vanilla-75c-01 | 2 | ev_shell | ev_heavy_mixed | 3 | 24 | 4281.107 |
| vanilla/e2-vanilla-75c-01 | 3 | ev_shell | ev_heavy_mixed | 4 | 22 | 4354.836 |

## Output Files

- `baselines/e2_alns/280kwh_fleet_composition_gate_data/metadata.json`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/phase0_instance_audit.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/task_queue.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/raw_runs.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/winners.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/composition_summary.csv`
- `baselines/e2_alns/280kwh_fleet_composition_gate_data/conclusion.json`

## Next Decision Rule

If this gate remains `HALT_ALL_EV` or `HALT_EV_DOMINANT` under stronger budgets, the paper should not frame 280kWh as universally producing a balanced mixed fleet. The honest fallback is to report that modern-battery regional instances become EV-dominant, then decide whether a smaller evidence-bound battery scenario is needed for a balanced-mix narrative.
