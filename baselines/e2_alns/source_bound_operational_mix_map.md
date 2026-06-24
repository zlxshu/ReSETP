# 09q Source-Bound Battery x Operational-Constraint Mix Map

Commit: `9f650030`.
Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.
Frozen defaults: `B_battery_kwh=280.0`, `v_speed_ms=25.0`, `carbon_price=0.05034`.
This runner does not change `prices.py`, generated bundles, `cost.py`, `check.py`, `evaluation.py`, or algorithm semantics.
Command: `/opt/anaconda3/bin/python3.13 baselines/e2_alns/source_bound_operational_mix_map.py --stage-a --smoke --battery-values 81 280 --constraint-scenarios unbounded_reference --stage-a-eval-budget 300 --runtime-small 60 --runtime-medium 90 --runtime-large 120 --task-timeout-buffer 30 --workers 3 --no-resume`.

## Verdict

`SMOKE_ONLY`.

Smoke optimization rows completed; this validates the runner path but is not a scientific gate conclusion.

Plain reading: 09o was a useful but narrow 280kWh clue. This report treats it as one row in a broader map; the decision unit is now a battery value plus an operational mechanism across the available 10-200 full-gradient stability instances.

## Phase 0/1 Checks

- Override audit: `OK`.
- Battery candidates selected: `81.0, 280.0`.
- Constraint scenarios selected: `unbounded_reference`.
- Full Stage A default task count: `9177` child tasks over `23` `-01` instances.
- Full Stage B/C default instance count: `69` stability instances.
- `80kWh` remains a historical reference only and is not a main candidate in this runner.

## Existing Evidence Recap

| source | category | battery | rows | in-band | fake balance | EV over manifest | mean EV route |
|---|---|---:|---:|---:|---:|---:|---:|
| 09l_stage_a | multidepot | 60.000 | 9 | 8 | 0 | 8 | 0.485 |
| 09l_stage_a | multidepot | 81.000 | 9 | 7 | 0 | 7 | 0.541 |
| 09l_stage_a | multidepot | 82.600 | 9 | 7 | 1 | 7 | 0.494 |
| 09l_stage_a | multidepot | 89.000 | 9 | 5 | 1 | 7 | 0.557 |
| 09l_stage_a | multidepot | 100.000 | 9 | 5 | 0 | 8 | 0.705 |
| 09l_stage_a | multidepot | 113.000 | 9 | 1 | 0 | 9 | 0.899 |
| 09l_stage_a | multidepot | 123.900 | 9 | 1 | 0 | 9 | 0.882 |
| 09l_stage_a | multidepot | 140.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 141.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 150.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 176.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 180.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 194.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 200.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 210.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 240.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 280.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 282.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | multidepot | 291.000 | 9 | 1 | 0 | 8 | 0.804 |
| 09l_stage_a | threeshift | 60.000 | 5 | 3 | 2 | 3 | 0.230 |
| 09l_stage_a | threeshift | 81.000 | 5 | 3 | 0 | 3 | 0.434 |
| 09l_stage_a | threeshift | 82.600 | 5 | 2 | 0 | 2 | 0.236 |
| 09l_stage_a | threeshift | 89.000 | 5 | 2 | 0 | 3 | 0.374 |
| 09l_stage_a | threeshift | 100.000 | 5 | 0 | 0 | 3 | 0.538 |
| 09l_stage_a | threeshift | 113.000 | 5 | 0 | 0 | 4 | 0.735 |
| 09l_stage_a | threeshift | 123.900 | 5 | 1 | 0 | 5 | 0.895 |
| 09l_stage_a | threeshift | 140.000 | 5 | 0 | 0 | 5 | 0.955 |
| 09l_stage_a | threeshift | 141.000 | 5 | 0 | 0 | 5 | 0.955 |
| 09l_stage_a | threeshift | 150.000 | 5 | 0 | 0 | 4 | 0.750 |
| 09l_stage_a | threeshift | 176.000 | 5 | 0 | 0 | 5 | 0.968 |
| 09l_stage_a | threeshift | 180.000 | 5 | 0 | 0 | 5 | 0.956 |
| 09l_stage_a | threeshift | 194.000 | 5 | 0 | 0 | 4 | 0.748 |
| 09l_stage_a | threeshift | 200.000 | 5 | 0 | 0 | 4 | 0.748 |
| 09l_stage_a | threeshift | 210.000 | 5 | 0 | 0 | 4 | 0.748 |
| 09l_stage_a | threeshift | 240.000 | 5 | 0 | 0 | 5 | 0.943 |
| 09l_stage_a | threeshift | 280.000 | 5 | 0 | 0 | 5 | 0.943 |
| 09l_stage_a | threeshift | 282.000 | 5 | 0 | 0 | 5 | 0.943 |
| 09l_stage_a | threeshift | 291.000 | 5 | 0 | 0 | 5 | 0.943 |
| 09l_stage_a | vanilla | 60.000 | 9 | 1 | 1 | 0 | 0.044 |
| 09l_stage_a | vanilla | 81.000 | 9 | 7 | 2 | 6 | 0.316 |
| 09l_stage_a | vanilla | 82.600 | 9 | 7 | 2 | 6 | 0.336 |
| 09l_stage_a | vanilla | 89.000 | 9 | 8 | 1 | 9 | 0.545 |
| 09l_stage_a | vanilla | 100.000 | 9 | 6 | 1 | 8 | 0.566 |
| 09l_stage_a | vanilla | 113.000 | 9 | 5 | 0 | 8 | 0.610 |
| 09l_stage_a | vanilla | 123.900 | 9 | 3 | 0 | 9 | 0.807 |
| 09l_stage_a | vanilla | 140.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 141.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 150.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 176.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 180.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 194.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 200.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 210.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 240.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 280.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 282.000 | 9 | 2 | 0 | 9 | 0.855 |
| 09l_stage_a | vanilla | 291.000 | 9 | 2 | 0 | 9 | 0.855 |

## Battery Sources

| battery | eligible | secondary | source ids |
|---:|---|---|---|
| 80.000 | False | False | Chen2023;Goeke2015 |
| 81.000 | True | False | MercedesESprinter |
| 280.000 | True | False | VolvoFLFE2023 |

## Operational Constraint Scenarios

| scenario | mechanism | source class | promotable | max/charger rule |
|---|---|---|---|---|
| unbounded_reference | none | reference_only | False | max_cv=1000000, max_ev=1000000, depot_chargers=, public_chargers= |

## Stage A

| battery | constraint | status | winners | pass inst | pass buckets | fake buckets | mean route/customer/demand/distance | composition counts |
|---:|---|---|---:|---:|---:|---:|---|---|
| 81.000 | unbounded_reference | fail | 2/2 | 0 | 0/2 | 0 | 0.000/0.000/0.000/0.000 | allCV=2, bal=0, evH=0, allEV=0 |
| 280.000 | unbounded_reference | pass | 2/2 | 2 | 2/2 | 0 | 0.559/0.488/0.542/0.544 | allCV=0, bal=2, evH=0, allEV=0 |

Top failure rows:

| battery | constraint | instance | reason | mean EV route/customer/demand/distance |
|---:|---|---|---|---|
| 81.000 | unbounded_reference | multidepot/e2-multidepot-100c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 81.000 | unbounded_reference | threeshift/e2-threeshift-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |

## Stage B

Not run or no rows collected.

## Stage C

Not run or no rows collected.

## Output Files

- `baselines/e2_alns/source_bound_operational_mix_map_data/metadata.json`
- `baselines/e2_alns/source_bound_operational_mix_map_data/evidence_matrix.csv`
- `baselines/e2_alns/source_bound_operational_mix_map_data/battery_candidate_set.csv`
- `baselines/e2_alns/source_bound_operational_mix_map_data/operational_constraint_matrix.csv`
- `baselines/e2_alns/source_bound_operational_mix_map_data/phase1_existing_failure_map.csv`
- `baselines/e2_alns/source_bound_operational_mix_map_data/stage_a_raw_runs.csv` / `stage_a_winners.csv` / `stage_a_scenario_summary.csv` if Stage A was run
- `baselines/e2_alns/source_bound_operational_mix_map_data/conclusion.json`

## Next Rule

Only a Stage C pass with a source-promotable operational constraint can justify a later formal model/TeX change. Diagnostic-only passes are useful for direction, but they are not a thesis parameter by themselves.
