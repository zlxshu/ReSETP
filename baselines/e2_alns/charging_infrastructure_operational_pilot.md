# 09o Charging-Infrastructure Operational Pilot

Run commit: `3806df34`.
Artifact commit: `a2e021e678a1f5c8576ac760be207f7bc55dbf4e`.
Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.
Prices used by in-memory override: `B_battery_kwh=280.0`, `v_speed_ms=25.0`, `carbon_price=0.05034`.
Command: `/opt/anaconda3/bin/python3.13 baselines/e2_alns/charging_infrastructure_operational_pilot.py --eval-budget 300 --runtime-cap-large 90 --task-timeout-buffer 30 --resume`.

## Verdict

`HALT_COLLECTION_COST`.

The pilot did not collect a complete auditable set; do not infer charging-infrastructure causality. Under the HALT, the 3 completed OK row(s) are still useful as a clue: mean depot charging energy share=1.000, mean public charging energy share=0.000, max one-depot concurrent charging=62, EV routes using public charging=0. That points to depot charging capacity as the next hypothesis to evidence-check, not to public fast-charger scarcity.

This is a pilot after 09n, not a formal parameter/model change. It freezes generated bundles and solver semantics.

## Plain-Language Reading

The full mini-batch did not pass because every `ev_shell` row timed out. So the honest status is still HALT, not proof. But the successful `free_mixed` rows all say the same thing: at 280kWh, the solver can build many-EV solutions without using public charging at all; it charges EVs at depots, and the generated depot charger counts are very large compared with observed peak concurrency. This makes depot charging capacity or depot charging capital the next cleaner hypothesis. Public fast-charger scarcity is lower priority for this specific mechanism, because the completed rows used zero public charging.

## Why This Was Tested

09n showed that directly capping vehicle route counts through `SearchPolicy` is too blunt: original Goeke/ReSETP fleet counts make many runs infeasible or too CV-light, while unbounded 280kWh winners can use many EV routes. The next plausible operational mechanism is charging infrastructure. Existing code already checks station capacity: public stations normally have one charger, while depots are generated with `customer_count_route_upper_bound` chargers. This pilot asks whether EV-heavy solutions are mostly leaning on that generous depot-charging assumption.

## Instance Charger Structure

| instance | depots | public stations | depot chargers | public chargers | metadata policy |
|---|---:|---:|---:|---:|---|
| vanilla/e2-vanilla-200c-01 | 1 | 21 | 200-200 | 1-1 | customer_count_route_upper_bound |
| multidepot/e2-multidepot-200c-01 | 2 | 21 | 200-200 | 1-1 | customer_count_route_upper_bound |
| threeshift/e2-threeshift-200c-01 | 2 | 21 | 91-91 | 1-1 | customer_count_route_upper_bound |

## Raw Optimization Rows

| instance | variant | status | CV | EV | EV share | cost | depot kWh share | public kWh share | peak depot concurrent | public routes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| multidepot/e2-multidepot-200c-01 | free_mixed | OK | 28 | 47 | 0.627 | 9768.431 | 1.000 | 0.000 | 24 | 0 |
| multidepot/e2-multidepot-200c-01 | ev_shell | TIMEOUT | 0 | 0 | 0.000 | inf |  |  |  |  |
| threeshift/e2-threeshift-200c-01 | free_mixed | OK | 22 | 47 | 0.681 | 9237.063 | 1.000 | 0.000 | 15 | 0 |
| threeshift/e2-threeshift-200c-01 | ev_shell | TIMEOUT | 0 | 0 | 0.000 | inf |  |  |  |  |
| vanilla/e2-vanilla-200c-01 | free_mixed | OK | 12 | 63 | 0.840 | 10845.718 | 1.000 | 0.000 | 62 | 0 |
| vanilla/e2-vanilla-200c-01 | ev_shell | TIMEOUT | 0 | 0 | 0.000 | inf |  |  |  |  |

## Winners

| instance | winner | composition | EV share | depot kWh share | public kWh share | peak depot concurrent | depot peak cap | public routes |
|---|---|---|---:|---:|---:|---:|---:|---:|
| multidepot/e2-multidepot-200c-01 | free_mixed | balanced_mixed | 0.627 | 1.000 | 0.000 | 24 | 200 | 0 |
| threeshift/e2-threeshift-200c-01 | free_mixed | balanced_mixed | 0.681 | 1.000 | 0.000 | 15 | 91 | 0 |
| vanilla/e2-vanilla-200c-01 | free_mixed | ev_heavy_mixed | 0.840 | 1.000 | 0.000 | 62 | 200 | 0 |

## Output Files

- `baselines/e2_alns/charging_infrastructure_operational_pilot_data/metadata.json`
- `baselines/e2_alns/charging_infrastructure_operational_pilot_data/pilot_instance_structure.csv`
- `baselines/e2_alns/charging_infrastructure_operational_pilot_data/all_focus_instance_structure.csv`
- `baselines/e2_alns/charging_infrastructure_operational_pilot_data/raw_runs.csv`
- `baselines/e2_alns/charging_infrastructure_operational_pilot_data/winners.csv`
- `baselines/e2_alns/charging_infrastructure_operational_pilot_data/solutions/*.json`
- `baselines/e2_alns/charging_infrastructure_operational_pilot_data/conclusion.json`

## Next Rule

If this pilot points to depot charging capacity, the next step should not be another ad hoc cap. It should first collect source evidence for depot charger counts or charging-capital budgets, then run a formal 75-200 stability gate with an explicit, switchable operational constraint. If this pilot times out or stays ambiguous, keep the result as a clue only and do not update TeX or defaults.
