# 09n Fleet-Cap Operational Gate

Commit: `dcf89960`.
Diagnostic artifact commit: `55cd2b71cf0de23a573ff8e9bb3be86f2cd16381`.
Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.
Frozen defaults: `B_battery_kwh=280.0`, `v_speed_ms=25.0`, `carbon_price=0.05034`.
This is a diagnostic search-shell gate only. It does not edit `prices.py`, `cost.py`, `check.py`, `evaluation.py`, generated bundles, or formal model semantics.
Command: `/opt/anaconda3/bin/python3.13 baselines/e2_alns/fleet_cap_operational_gate.py --stage-a --stage-b --stage-c --workers 4 --stage-a-eval-budget 1000 --stage-b-eval-budget 3000 --stage-c-eval-budget 16000 --runtime-small 240 --runtime-medium 360 --runtime-large 900 --runtime-confirm-small 300 --runtime-confirm-medium 600 --runtime-confirm-large 900 --task-timeout-buffer 90`.

## Verdict

`HALT_COLLECTION_COST`.

At least one required optimization task timed out or errored.

Plain reading: this report tests whether the apparent 280kWh EV dominance is partly an unlimited-EV-availability artifact. A passing diagnostic cap would still need a separate formal-model plan before the paper can claim it.

## Evidence Matrix

| source | type | explicit numeric cap | supports | rule | caveat |
|---|---|---|---|---|---|
| GoekeSchneider2015Raw | benchmark_raw_instance | True | goeke_total_cap;goeke_ev_cap_only | numPetrolVeh/numElectroVeh per raw E-UK instance | May be incompatible with ReSETP one-route-per-vehicle interpretation if route count exceeds numVeh. |
| ReSETPGeneratedMetadata | generated_instance_metadata | True | goeke_total_cap;goeke_ev_cap_only | metadata num_cv/num_ev copied from Goeke donor | Current solver/checker intentionally do not enforce these values. |
| Chen2023SharedCharging | paper_reference | False | multidepot_shared_charging_context |  | Do not generate evidence_ratio_cap from this source without extracting explicit fleet-count data. |
| Wang2024ResourceSharing | paper_reference | False | resource_sharing_context |  | Context source only for this runner. |
| Qiu2024MixedFleet | local_pdf_reference | False | mixed_fleet_literature_context |  | Battery evidence was used in 09h/09k; no fleet cap ratio is promoted here without extraction. |
| Li2020FleetConfiguration | local_pdf_reference | False | fleet_configuration_mechanism |  | No numeric cap is generated unless the source is explicitly extracted later. |
| GOVUKCommercialEVFleets2024 | official_web | False | finite_ev_adoption_and_barriers_context |  | Qualitative/industry context only unless an explicit fleet ratio is extracted. |

## Cap Scenarios

The cap values are instance-specific. `goeke_total_cap` and `goeke_ev_cap_only` use raw/generated `numPetrolVeh/numElectroVeh`; `depot_scaled_cap` is diagnostic only.
Before expensive EV-heavy warm construction, the runner applies a cheap proxy guard: if the deterministic feasible CV seed already needs more routes than the proposed one-route-per-vehicle cap can hold, that task is recorded as `INIT_INFEASIBLE`. This is a diagnostic collection guard, not a mathematical proof of model infeasibility.

| scenario | rows | source class | min/max CV cap | min/max EV cap |
|---|---:|---|---:|---:|
| depot_scaled_cap | 36 | diagnostic_only | 5-28 | 5-28 |
| goeke_ev_cap_only | 36 | source_backed_diagnostic | 1000000-1000000 | 5-14 |
| goeke_total_cap | 36 | source_backed | 5-14 | 5-14 |

## Phase 1: Did We Exceed Recorded Fleet Counts?

| battery | family | rows | EV routes > manifest EV | CV routes > manifest CV | total routes > manifest sum | mean EV share | max EV routes / max manifest EV |
|---:|---|---:|---:|---:|---:|---:|---|
| 60.0 | multidepot | 4 | 3 | 4 | 4 | 0.418 | 48/14 |
| 60.0 | threeshift | 4 | 3 | 4 | 4 | 0.287 | 35/14 |
| 60.0 | vanilla | 4 | 0 | 4 | 4 | 0.000 | 0/14 |
| 81.0 | multidepot | 4 | 3 | 4 | 4 | 0.555 | 39/14 |
| 81.0 | threeshift | 4 | 2 | 4 | 4 | 0.367 | 40/14 |
| 81.0 | vanilla | 4 | 2 | 4 | 4 | 0.298 | 40/14 |
| 82.6 | multidepot | 4 | 2 | 4 | 4 | 0.352 | 24/14 |
| 82.6 | threeshift | 4 | 2 | 4 | 4 | 0.295 | 40/14 |
| 82.6 | vanilla | 4 | 2 | 4 | 4 | 0.301 | 42/14 |
| 89.0 | multidepot | 4 | 2 | 2 | 4 | 0.402 | 27/14 |
| 89.0 | threeshift | 4 | 2 | 4 | 4 | 0.264 | 41/14 |
| 89.0 | vanilla | 4 | 4 | 3 | 4 | 0.625 | 51/14 |
| 100.0 | multidepot | 4 | 3 | 2 | 4 | 0.611 | 46/14 |
| 100.0 | threeshift | 4 | 2 | 2 | 4 | 0.438 | 61/14 |
| 100.0 | vanilla | 4 | 3 | 3 | 4 | 0.526 | 44/14 |
| 113.0 | multidepot | 4 | 4 | 0 | 4 | 0.940 | 71/14 |
| 113.0 | threeshift | 4 | 3 | 1 | 4 | 0.684 | 68/14 |
| 113.0 | vanilla | 4 | 4 | 3 | 4 | 0.709 | 57/14 |
| 123.9 | multidepot | 4 | 4 | 0 | 4 | 0.933 | 73/14 |
| 123.9 | threeshift | 4 | 4 | 1 | 4 | 0.884 | 52/14 |
| 123.9 | vanilla | 4 | 4 | 1 | 4 | 0.862 | 72/14 |
| 140.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 140.0 | threeshift | 4 | 4 | 0 | 4 | 0.960 | 73/14 |
| 140.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 141.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 141.0 | threeshift | 4 | 4 | 0 | 4 | 0.959 | 73/14 |
| 141.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 150.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 150.0 | threeshift | 4 | 3 | 1 | 4 | 0.687 | 51/14 |
| 150.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 176.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 176.0 | threeshift | 4 | 4 | 0 | 4 | 0.960 | 73/14 |
| 176.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 180.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 180.0 | threeshift | 4 | 4 | 0 | 4 | 0.960 | 73/14 |
| 180.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 194.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 194.0 | threeshift | 4 | 3 | 1 | 4 | 0.699 | 51/14 |
| 194.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 200.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 200.0 | threeshift | 4 | 3 | 1 | 4 | 0.699 | 51/14 |
| 200.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 210.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 210.0 | threeshift | 4 | 3 | 1 | 4 | 0.699 | 51/14 |
| 210.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 240.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 240.0 | threeshift | 4 | 4 | 0 | 4 | 0.943 | 70/14 |
| 240.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 280.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 280.0 | threeshift | 4 | 4 | 0 | 4 | 0.943 | 70/14 |
| 280.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 282.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 282.0 | threeshift | 4 | 4 | 0 | 4 | 0.943 | 70/14 |
| 282.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |
| 291.0 | multidepot | 4 | 3 | 2 | 4 | 0.683 | 59/14 |
| 291.0 | threeshift | 4 | 4 | 0 | 4 | 0.943 | 70/14 |
| 291.0 | vanilla | 4 | 4 | 1 | 4 | 0.846 | 53/14 |

## Cap Proxy Audit

`OK`: {'status': 'OK', 'probe_instance': 'multidepot/e2-multidepot-100c-01', 'cap_scenario': 'goeke_ev_cap_only', 'warm_cv_route_count': 34, 'warm_ev_route_count': 1, 'max_cv': 1000000, 'max_ev': 7, 'interpretation': 'SearchPolicy cap can be used as a diagnostic only if warm and final rows are audited.'}

## Stage A Screen

| scenario | status | winners | instance pass/fail | scale pass/fail | fake-balance buckets | mean route/customer/demand/distance EV share | composition counts | raw statuses |
|---|---|---:|---|---|---:|---|---|---|
| depot_scaled_cap | incomplete | 0/12 | 0/12 | 0/12 | 0 | /// | allEV=0, EVheavy=0, balanced=0, CVheavy=0, allCV=0 | OK=0, init=33, cap=0, timeout/error=3 |
| goeke_ev_cap_only | fail | 12/12 | 4/8 | 10/2 | 6 | 0.193/0.189/0.191/0.190 | allEV=0, EVheavy=0, balanced=10, CVheavy=1, allCV=1 | OK=24, init=11, cap=0, timeout/error=1 |
| goeke_total_cap | incomplete | 0/12 | 0/12 | 0/12 | 0 | /// | allEV=0, EVheavy=0, balanced=0, CVheavy=0, allCV=0 | OK=0, init=33, cap=0, timeout/error=3 |

By-scale failures or fake-balance buckets:

| scenario | family | size | route/customer/demand/distance EV share | reason |
|---|---|---:|---|---|
| depot_scaled_cap | multidepot | 75 | /// | route_share_outside_band |
| depot_scaled_cap | multidepot | 100 | /// | route_share_outside_band |
| depot_scaled_cap | multidepot | 150 | /// | route_share_outside_band |
| depot_scaled_cap | multidepot | 200 | /// | route_share_outside_band |
| depot_scaled_cap | threeshift | 75 | /// | route_share_outside_band |
| depot_scaled_cap | threeshift | 100 | /// | route_share_outside_band |
| depot_scaled_cap | threeshift | 150 | /// | route_share_outside_band |
| depot_scaled_cap | threeshift | 200 | /// | route_share_outside_band |
| depot_scaled_cap | vanilla | 75 | /// | route_share_outside_band |
| depot_scaled_cap | vanilla | 100 | /// | route_share_outside_band |
| depot_scaled_cap | vanilla | 150 | /// | route_share_outside_band |
| depot_scaled_cap | vanilla | 200 | /// | route_share_outside_band |
| goeke_ev_cap_only | multidepot | 75 | 0.192/0.200/0.200/0.187 | route_share_outside_band |
| goeke_ev_cap_only | multidepot | 100 | 0.212/0.200/0.202/0.192 | fake_balance |
| goeke_ev_cap_only | multidepot | 200 | 0.000/0.000/0.000/0.000 | route_share_outside_band |
| goeke_ev_cap_only | threeshift | 150 | 0.200/0.200/0.208/0.196 | fake_balance |
| goeke_ev_cap_only | threeshift | 200 | 0.219/0.195/0.211/0.120 | fake_balance |
| goeke_ev_cap_only | vanilla | 100 | 0.219/0.180/0.200/0.184 | fake_balance |
| goeke_ev_cap_only | vanilla | 150 | 0.208/0.207/0.205/0.172 | fake_balance |
| goeke_ev_cap_only | vanilla | 200 | 0.209/0.225/0.217/0.152 | fake_balance |
| goeke_total_cap | multidepot | 75 | /// | route_share_outside_band |
| goeke_total_cap | multidepot | 100 | /// | route_share_outside_band |
| goeke_total_cap | multidepot | 150 | /// | route_share_outside_band |
| goeke_total_cap | multidepot | 200 | /// | route_share_outside_band |
| goeke_total_cap | threeshift | 75 | /// | route_share_outside_band |
| goeke_total_cap | threeshift | 100 | /// | route_share_outside_band |
| goeke_total_cap | threeshift | 150 | /// | route_share_outside_band |
| goeke_total_cap | threeshift | 200 | /// | route_share_outside_band |
| goeke_total_cap | vanilla | 75 | /// | route_share_outside_band |
| goeke_total_cap | vanilla | 100 | /// | route_share_outside_band |
| goeke_total_cap | vanilla | 150 | /// | route_share_outside_band |
| goeke_total_cap | vanilla | 200 | /// | route_share_outside_band |

Failure instances:

| scenario | family | instance | reason | route/customer/demand/distance EV share |
|---|---|---|---|---|
| depot_scaled_cap | multidepot | e2-multidepot-100c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | multidepot | e2-multidepot-150c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | multidepot | e2-multidepot-200c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | multidepot | e2-multidepot-75c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | threeshift | e2-threeshift-100c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | threeshift | e2-threeshift-150c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | threeshift | e2-threeshift-200c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | threeshift | e2-threeshift-75c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | vanilla | e2-vanilla-100c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | vanilla | e2-vanilla-150c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | vanilla | e2-vanilla-200c-01 | missing_or_infeasible | /// |
| depot_scaled_cap | vanilla | e2-vanilla-75c-01 | missing_or_infeasible | /// |
| goeke_ev_cap_only | multidepot | e2-multidepot-100c-01 | fake_balance | 0.212/0.200/0.202/0.192 |
| goeke_ev_cap_only | multidepot | e2-multidepot-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| goeke_ev_cap_only | multidepot | e2-multidepot-75c-01 | route_share_outside_practical_band | 0.192/0.200/0.200/0.187 |
| goeke_ev_cap_only | threeshift | e2-threeshift-150c-01 | fake_balance | 0.200/0.200/0.208/0.196 |
| goeke_ev_cap_only | threeshift | e2-threeshift-200c-01 | fake_balance | 0.219/0.195/0.211/0.120 |
| goeke_ev_cap_only | vanilla | e2-vanilla-100c-01 | fake_balance | 0.219/0.180/0.200/0.184 |
| goeke_ev_cap_only | vanilla | e2-vanilla-150c-01 | fake_balance | 0.208/0.207/0.205/0.172 |
| goeke_ev_cap_only | vanilla | e2-vanilla-200c-01 | fake_balance | 0.209/0.225/0.217/0.152 |
| goeke_total_cap | multidepot | e2-multidepot-100c-01 | missing_or_infeasible | /// |
| goeke_total_cap | multidepot | e2-multidepot-150c-01 | missing_or_infeasible | /// |
| goeke_total_cap | multidepot | e2-multidepot-200c-01 | missing_or_infeasible | /// |
| goeke_total_cap | multidepot | e2-multidepot-75c-01 | missing_or_infeasible | /// |
| goeke_total_cap | threeshift | e2-threeshift-100c-01 | missing_or_infeasible | /// |
| goeke_total_cap | threeshift | e2-threeshift-150c-01 | missing_or_infeasible | /// |
| goeke_total_cap | threeshift | e2-threeshift-200c-01 | missing_or_infeasible | /// |
| goeke_total_cap | threeshift | e2-threeshift-75c-01 | missing_or_infeasible | /// |
| goeke_total_cap | vanilla | e2-vanilla-100c-01 | missing_or_infeasible | /// |
| goeke_total_cap | vanilla | e2-vanilla-150c-01 | missing_or_infeasible | /// |
| goeke_total_cap | vanilla | e2-vanilla-200c-01 | missing_or_infeasible | /// |
| goeke_total_cap | vanilla | e2-vanilla-75c-01 | missing_or_infeasible | /// |

## Stage B Stability Gate

Not collected.

## Stage C Confirmation

Not collected.

## Verification

- `PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m py_compile baselines/e2_alns/fleet_cap_operational_gate.py`: passed.
- `PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m pytest solver/tests/test_cost.py solver/tests/test_check.py solver/tests/test_search.py -q`: 65 passed in 74.00s.

## Output Files

- `baselines/e2_alns/fleet_cap_operational_gate_data/metadata.json`
- `baselines/e2_alns/fleet_cap_operational_gate_data/evidence_matrix.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/raw_goeke_fleet_counts.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/generated_fleet_metadata.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/cap_scenarios.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/existing_unbounded_winner_audit.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/phase1_unbounded_summary.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/cap_proxy_audit.json`
- `baselines/e2_alns/fleet_cap_operational_gate_data/stage_a_task_queue.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/stage_a_raw_runs.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/stage_a_winners.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/stage_a_scenario_summary.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/stage_a_by_scale.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/stage_a_failure_instances.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/raw_runs.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/winners.csv`
- `baselines/e2_alns/fleet_cap_operational_gate_data/conclusion.json`

## Decision Boundary

If this gate cannot produce a source-backed practical mixed band, do not tune battery values further. Move to charger capacity, public-station scarcity, route eligibility, or explicit EV capital-budget mechanisms, with the same evidence-first rule.
