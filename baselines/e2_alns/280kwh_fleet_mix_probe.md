# 280kWh Fleet-Mix Degeneration Probe

Date: 2026-06-23.

Commit context: `48484b41` after `8500fd9c` promoted `B_battery_kwh=280`.

## Verdict

`PROVISIONAL_HALT_FULL_TRUE_MIXED_CLAIM`.

The 280kWh update fixes the old all-CV pressure, but the first cross-scale probe shows a strong EV-heavy pull. Some representative free `mixed` runs already return zero CV routes. Therefore the paper cannot honestly claim, yet, that 280kWh gives a true mixed-fleet optimum across 25-200 customer scales.

This is not a rejection of the 280kWh update. It is a scope warning: the next formal E1 rerun must report vehicle-type composition explicitly and distinguish all-EV, EV-heavy mixed, and balanced mixed cases.

## Probe Scope

This was a diagnostic probe only, not formal E1 evidence.

- Python: `/opt/anaconda3/bin/python3.13`
- Paths: `PYTHONPATH=solver/src:models/src`
- Prices: current `DEFAULT_PRICES` with `carbon_price=0.05034`, so `B_battery_kwh=280`, `v_speed_ms=25.0`
- Algorithm shell: `run_alns_wouda`
- Policy: free `SearchPolicy(require_charging_signal=False)`, recorded as `mixed`
- E2 flags: `e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)`
- Seed: `1`
- Budget: `1000` evals
- Runtime cap requested: `60` seconds per instance; the 200c cases can return later because the solver checks time at loop boundaries

The purpose was only to check whether free mixed search immediately collapses toward all-EV under the new battery default.

## Probe Rows

| instance | total cost | CV routes | EV routes | evals | violations |
|---|---:|---:|---:|---:|---:|
| vanilla/e2-vanilla-25c-01 | 1146.070 | 0 | 8 | 1000 | 0 |
| vanilla/e2-vanilla-50c-01 | 2532.420 | 1 | 16 | 1000 | 0 |
| vanilla/e2-vanilla-75c-01 | 4558.534 | 4 | 24 | 1000 | 0 |
| vanilla/e2-vanilla-100c-01 | 5268.954 | 6 | 27 | 1000 | 0 |
| vanilla/e2-vanilla-150c-01 | 7102.549 | 0 | 53 | 1000 | 0 |
| vanilla/e2-vanilla-200c-01 | 10342.408 | 2 | 70 | 1000 | 0 |
| threeshift/e2-threeshift-100c-01 | 4559.864 | 2 | 29 | 1000 | 0 |
| threeshift/e2-threeshift-150c-01 | 7188.956 | 2 | 51 | 1000 | 0 |
| threeshift/e2-threeshift-200c-01 | 9745.310 | 37 | 36 | 220 | 0 |

CSV: `baselines/e2_alns/280kwh_fleet_mix_probe_data/mixed_probe_seed1.csv`.

## Existing Full-Budget 09h Cross-Check

The previous 09h `E_distribution_truck_280` true re-optimization rows are stronger than this light probe for the three-shift large cases:

| instance | ok seeds | mean route count | mean EV routes | mean CV routes | mean cost |
|---|---:|---:|---:|---:|---:|
| e2-threeshift-100c-01 | 5 | 32.0 | 32.0 | 0.0 | 4491.771 |
| e2-threeshift-150c-01 | 5 | 50.0 | 47.0 | 3.0 | 6798.481 |
| e2-threeshift-200c-01 | 5 | 68.0 | 67.2 | 0.8 | 8616.454 |

That means 200c remains technically mixed on average, but 100c is all-EV and 150/200c are heavily EV-dominant.

## Important Caveat

Do not use the old formal E1 `ev_only` label as hard all-EV evidence. `SearchPolicy.max_cv/max_ev` is a search-shell preference, not a model constraint; old `ev_only` rows can still contain CV routes. The robust check is the actual `cv_route_count` and `ev_route_count` in the returned solution.

## Next Step

Run a proper 280kWh E1 fleet-composition gate before the broader E1-E7 rerun:

1. Use full budget or an explicitly staged budget ladder.
2. Cover 25, 50, 75, 100, 150, and 200 customer scales, with representative vanilla/multidepot/threeshift cases.
3. Report both cost winner and route-type composition.
4. Classify each case as `all_ev`, `ev_heavy_mixed`, `balanced_mixed`, or `all_cv`.

Until that gate is complete, the honest story is: `280kWh solves all-CV degeneration but may overcorrect toward EV dominance at some scales`.
