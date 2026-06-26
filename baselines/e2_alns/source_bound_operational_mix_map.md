# 09q Source-Bound Battery x Operational-Constraint Mix Map

Commit: `09f59dbd`.
Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.
Frozen defaults: `B_battery_kwh=280.0`, `v_speed_ms=25.0`, `carbon_price=0.05034`.
This runner does not change `prices.py`, generated bundles, `cost.py`, `check.py`, `evaluation.py`, or algorithm semantics.
Command: `/opt/anaconda3/bin/python3.13 baselines/e2_alns/source_bound_operational_mix_map.py --stage-a --resume --retry-timeouts --workers 3 --runtime-large 1200 --task-timeout-buffer 180`.

## Verdict

`BATTERY_OPERATION_COMBINATION_INSUFFICIENT`.

No tested battery x operational-constraint combination kept the required 10-200 full-gradient screen inside the practical mixed band.

Plain reading: 09o was a useful but narrow 280kWh clue. This report treats it as one row in a broader map; the decision unit is now a battery value plus an operational mechanism across the available 10-200 full-gradient stability instances.

## Phase 0/1 Checks

- Override audit: `OK`.
- Battery candidates selected: `60.0, 81.0, 82.6, 89.0, 100.0, 113.0, 123.9, 140.0, 141.0, 150.0, 176.0, 180.0, 194.0, 200.0, 210.0, 240.0, 280.0, 282.0, 291.0`.
- Constraint scenarios selected: `unbounded_reference, goeke_ev_cap_only, goeke_total_cap, depot_chargers_manifest_ev_diagnostic, depot_chargers_manifest_total_diagnostic, public_charging_disabled_diagnostic, depot_manifest_ev_no_public_diagnostic`.
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
| 60.000 | True | False | IsuzuNRREV;Qiu2024 |
| 80.000 | False | False | Chen2023;Goeke2015 |
| 81.000 | True | False | MercedesESprinter |
| 82.600 | True | True | FusoECanter |
| 89.000 | True | False | FordETransit2025 |
| 100.000 | True | False | IsuzuNRREV |
| 113.000 | True | False | MercedesESprinter |
| 123.900 | True | True | FusoECanter |
| 140.000 | True | False | IsuzuNRREV |
| 141.000 | True | False | DAFXBElectric |
| 150.000 | True | False | MackMDElectric |
| 176.000 | True | False | RenaultTrucksETechD |
| 180.000 | True | False | IsuzuNRREV |
| 194.000 | True | False | FreightlinerEM2 |
| 200.000 | True | False | RenaultTrucksETechD |
| 210.000 | True | False | DAFXBElectric;InternationalEMV |
| 240.000 | True | False | MackMDElectric |
| 280.000 | True | False | VolvoFLFE2023 |
| 282.000 | True | False | DAFXBElectric |
| 291.000 | True | False | FreightlinerEM2 |

## Operational Constraint Scenarios

| scenario | mechanism | source class | promotable | max/charger rule |
|---|---|---|---|---|
| depot_chargers_manifest_ev_diagnostic | depot_charging_capacity | diagnostic_only | False | max_cv=1000000, max_ev=1000000, depot_chargers=7, public_chargers= |
| depot_chargers_manifest_total_diagnostic | depot_charging_capacity | diagnostic_only | False | max_cv=1000000, max_ev=1000000, depot_chargers=14, public_chargers= |
| depot_manifest_ev_no_public_diagnostic | charging_capacity_combo | diagnostic_only | False | max_cv=1000000, max_ev=1000000, depot_chargers=7, public_chargers=0 |
| goeke_ev_cap_only | ev_fleet_capital | source_backed_diagnostic | False | max_cv=1000000, max_ev=7, depot_chargers=, public_chargers= |
| goeke_total_cap | fleet_capital | source_backed_diagnostic | False | max_cv=7, max_ev=7, depot_chargers=, public_chargers= |
| public_charging_disabled_diagnostic | public_charging_availability | diagnostic_only | False | max_cv=1000000, max_ev=1000000, depot_chargers=, public_chargers=0 |
| unbounded_reference | none | reference_only | False | max_cv=1000000, max_ev=1000000, depot_chargers=, public_chargers= |

## Stage A

| battery | constraint | status | winners | pass inst | pass buckets | fake buckets | mean route/customer/demand/distance | composition counts |
|---:|---|---|---:|---:|---:|---:|---|---|
| 60.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 10 | 10/23 | 2 | 0.180/0.157/0.171/0.110 | allCV=12, bal=10, evH=0, allEV=0 |
| 60.000 | depot_chargers_manifest_total_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 3 | 0.265/0.230/0.250/0.157 | allCV=10, bal=13, evH=0, allEV=0 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 12 | 12/23 | 5 | 0.208/0.183/0.199/0.115 | allCV=10, bal=12, evH=0, allEV=0 |
| 60.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 9 | 9/23 | 9 | 0.131/0.117/0.127/0.078 | allCV=8, bal=8, evH=0, allEV=0 |
| 60.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 60.000 | public_charging_disabled_diagnostic | fail_fake_balance | 23/23 | 14 | 14/23 | 6 | 0.257/0.225/0.246/0.140 | allCV=9, bal=14, evH=0, allEV=0 |
| 60.000 | unbounded_reference | fail_fake_balance | 23/23 | 14 | 14/23 | 3 | 0.304/0.266/0.288/0.181 | allCV=9, bal=14, evH=0, allEV=0 |
| 81.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 14 | 14/23 | 4 | 0.277/0.242/0.274/0.209 | allCV=7, bal=12, evH=0, allEV=0 |
| 81.000 | depot_chargers_manifest_total_diagnostic | fail_fake_balance | 23/23 | 15 | 15/23 | 2 | 0.353/0.315/0.342/0.263 | allCV=8, bal=14, evH=0, allEV=0 |
| 81.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 4 | 0.232/0.203/0.229/0.163 | allCV=8, bal=11, evH=0, allEV=0 |
| 81.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 10 | 10/23 | 8 | 0.139/0.126/0.134/0.109 | allCV=7, bal=8, evH=0, allEV=0 |
| 81.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 81.000 | public_charging_disabled_diagnostic | fail_fake_balance | 23/23 | 15 | 15/23 | 3 | 0.339/0.304/0.327/0.227 | allCV=7, bal=14, evH=0, allEV=0 |
| 81.000 | unbounded_reference | fail_fake_balance | 23/23 | 18 | 18/23 | 2 | 0.448/0.396/0.432/0.322 | allCV=5, bal=17, evH=0, allEV=0 |
| 82.600 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 4 | 0.245/0.221/0.242/0.185 | allCV=9, bal=11, evH=0, allEV=0 |
| 82.600 | depot_chargers_manifest_total_diagnostic | fail_fake_balance | 23/23 | 16 | 16/23 | 1 | 0.389/0.342/0.376/0.290 | allCV=7, bal=15, evH=0, allEV=0 |
| 82.600 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 12 | 12/23 | 2 | 0.236/0.206/0.235/0.170 | allCV=8, bal=11, evH=0, allEV=0 |
| 82.600 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 11 | 11/23 | 7 | 0.127/0.111/0.124/0.103 | allCV=9, bal=9, evH=0, allEV=0 |
| 82.600 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 82.600 | public_charging_disabled_diagnostic | fail_fake_balance | 23/23 | 15 | 15/23 | 2 | 0.368/0.329/0.358/0.254 | allCV=6, bal=14, evH=0, allEV=0 |
| 82.600 | unbounded_reference | fail_fake_balance | 23/23 | 17 | 17/23 | 1 | 0.427/0.375/0.414/0.310 | allCV=6, bal=16, evH=0, allEV=0 |
| 89.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 12 | 12/23 | 3 | 0.242/0.229/0.242/0.191 | allCV=10, bal=10, evH=0, allEV=0 |
| 89.000 | depot_chargers_manifest_total_diagnostic | fail_fake_balance | 23/23 | 18 | 18/23 | 1 | 0.482/0.431/0.469/0.389 | allCV=4, bal=17, evH=1, allEV=0 |
| 89.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 11 | 11/23 | 2 | 0.229/0.208/0.227/0.175 | allCV=9, bal=10, evH=0, allEV=0 |
| 89.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 11 | 11/23 | 9 | 0.119/0.107/0.119/0.096 | allCV=10, bal=8, evH=0, allEV=0 |
| 89.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 89.000 | public_charging_disabled_diagnostic | fail_fake_balance | 23/23 | 17 | 17/23 | 2 | 0.454/0.413/0.438/0.330 | allCV=5, bal=16, evH=1, allEV=0 |
| 89.000 | unbounded_reference | fail_fake_balance | 23/23 | 17 | 17/23 | 1 | 0.570/0.514/0.556/0.447 | allCV=3, bal=16, evH=2, allEV=1 |
| 100.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 10 | 10/23 | 4 | 0.343/0.320/0.341/0.294 | allCV=5, bal=8, evH=5, allEV=0 |
| 100.000 | depot_chargers_manifest_total_diagnostic | fail_fake_balance | 23/23 | 10 | 10/23 | 1 | 0.468/0.442/0.466/0.392 | allCV=7, bal=8, evH=7, allEV=0 |
| 100.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 12 | 12/23 | 4 | 0.259/0.235/0.256/0.208 | allCV=8, bal=9, evH=0, allEV=0 |
| 100.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 11 | 11/23 | 9 | 0.126/0.118/0.127/0.108 | allCV=9, bal=8, evH=0, allEV=0 |
| 100.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 100.000 | public_charging_disabled_diagnostic | fail_fake_balance | 23/23 | 15 | 15/23 | 1 | 0.597/0.559/0.587/0.479 | allCV=3, bal=14, evH=4, allEV=1 |
| 100.000 | unbounded_reference | fail_fake_balance | 23/23 | 9 | 9/23 | 1 | 0.620/0.581/0.613/0.523 | allCV=4, bal=8, evH=9, allEV=1 |
| 113.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 4 | 0.362/0.338/0.362/0.327 | allCV=4, bal=11, evH=4, allEV=0 |
| 113.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 13 | 13/23 | 0 | 0.589/0.543/0.582/0.521 | allCV=3, bal=12, evH=7, allEV=1 |
| 113.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 12 | 12/23 | 4 | 0.293/0.272/0.296/0.253 | allCV=6, bal=10, evH=3, allEV=0 |
| 113.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 13 | 13/23 | 8 | 0.159/0.154/0.160/0.141 | allCV=5, bal=11, evH=0, allEV=0 |
| 113.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 113.000 | public_charging_disabled_diagnostic | fail_fake_balance | 23/23 | 8 | 8/23 | 1 | 0.641/0.600/0.632/0.546 | allCV=3, bal=7, evH=10, allEV=2 |
| 113.000 | unbounded_reference | fail | 23/23 | 9 | 9/23 | 0 | 0.777/0.738/0.769/0.699 | allCV=1, bal=8, evH=12, allEV=2 |
| 123.900 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 9 | 9/23 | 2 | 0.368/0.347/0.367/0.347 | allCV=4, bal=8, evH=5, allEV=0 |
| 123.900 | depot_chargers_manifest_total_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 1 | 0.596/0.556/0.586/0.553 | allCV=3, bal=12, evH=6, allEV=2 |
| 123.900 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 10 | 10/23 | 3 | 0.325/0.300/0.323/0.290 | allCV=5, bal=9, evH=4, allEV=0 |
| 123.900 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 11 | 11/23 | 8 | 0.141/0.133/0.141/0.137 | allCV=7, bal=10, evH=0, allEV=0 |
| 123.900 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 123.900 | public_charging_disabled_diagnostic | fail_fake_balance | 23/23 | 7 | 7/23 | 1 | 0.768/0.732/0.760/0.682 | allCV=1, bal=6, evH=13, allEV=2 |
| 123.900 | unbounded_reference | fail | 23/23 | 5 | 5/23 | 0 | 0.839/0.812/0.831/0.763 | allCV=1, bal=5, evH=10, allEV=7 |
| 140.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 14 | 14/23 | 5 | 0.366/0.336/0.361/0.350 | allCV=3, bal=12, evH=3, allEV=0 |
| 140.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 13 | 13/23 | 0 | 0.550/0.516/0.540/0.515 | allCV=4, bal=13, evH=5, allEV=1 |
| 140.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.345/0.369/0.354 | allCV=3, bal=11, evH=4, allEV=0 |
| 140.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 8 | 0.159/0.150/0.157/0.150 | allCV=5, bal=11, evH=0, allEV=0 |
| 140.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 140.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.789/0.762/0.781/0.725 | allCV=2, bal=4, evH=12, allEV=5 |
| 140.000 | unbounded_reference | fail | 23/23 | 5 | 5/23 | 0 | 0.780/0.753/0.771/0.721 | allCV=2, bal=5, evH=10, allEV=6 |
| 141.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 14 | 14/23 | 5 | 0.363/0.332/0.358/0.350 | allCV=3, bal=12, evH=3, allEV=0 |
| 141.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 13 | 13/23 | 0 | 0.552/0.518/0.542/0.518 | allCV=4, bal=13, evH=4, allEV=2 |
| 141.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.344/0.370/0.358 | allCV=3, bal=11, evH=4, allEV=0 |
| 141.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 7 | 0.159/0.151/0.158/0.151 | allCV=5, bal=11, evH=0, allEV=0 |
| 141.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 141.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.791/0.765/0.783/0.729 | allCV=2, bal=4, evH=11, allEV=6 |
| 141.000 | unbounded_reference | fail | 23/23 | 5 | 5/23 | 0 | 0.780/0.753/0.771/0.721 | allCV=2, bal=5, evH=10, allEV=6 |
| 150.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.378/0.351/0.375/0.365 | allCV=3, bal=11, evH=4, allEV=0 |
| 150.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 12 | 12/23 | 0 | 0.567/0.536/0.558/0.534 | allCV=4, bal=12, evH=5, allEV=2 |
| 150.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.375/0.348/0.372/0.359 | allCV=3, bal=11, evH=4, allEV=0 |
| 150.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 8 | 0.159/0.149/0.157/0.152 | allCV=5, bal=10, evH=0, allEV=0 |
| 150.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 150.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.791/0.766/0.783/0.729 | allCV=2, bal=4, evH=11, allEV=6 |
| 150.000 | unbounded_reference | fail | 23/23 | 4 | 4/23 | 0 | 0.795/0.770/0.787/0.737 | allCV=2, bal=4, evH=11, allEV=6 |
| 176.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 176.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 12 | 12/23 | 0 | 0.566/0.534/0.557/0.533 | allCV=4, bal=12, evH=5, allEV=2 |
| 176.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.378/0.351/0.374/0.365 | allCV=3, bal=11, evH=4, allEV=0 |
| 176.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 7 | 0.159/0.153/0.158/0.153 | allCV=5, bal=10, evH=0, allEV=0 |
| 176.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 176.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.770/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 176.000 | unbounded_reference | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 180.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 180.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 12 | 12/23 | 0 | 0.566/0.534/0.557/0.533 | allCV=4, bal=12, evH=5, allEV=2 |
| 180.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.377/0.350/0.373/0.364 | allCV=3, bal=11, evH=4, allEV=0 |
| 180.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 7 | 0.159/0.153/0.158/0.153 | allCV=5, bal=10, evH=0, allEV=0 |
| 180.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 180.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 180.000 | unbounded_reference | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 194.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 194.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 12 | 12/23 | 0 | 0.566/0.534/0.557/0.533 | allCV=4, bal=12, evH=5, allEV=2 |
| 194.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 194.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 7 | 0.159/0.153/0.158/0.153 | allCV=5, bal=10, evH=0, allEV=0 |
| 194.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 194.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 194.000 | unbounded_reference | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 200.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 200.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 12 | 12/23 | 0 | 0.566/0.534/0.557/0.533 | allCV=4, bal=12, evH=5, allEV=2 |
| 200.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 200.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 7 | 0.159/0.153/0.158/0.153 | allCV=5, bal=10, evH=0, allEV=0 |
| 200.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 200.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 200.000 | unbounded_reference | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 210.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 210.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 12 | 12/23 | 0 | 0.566/0.534/0.557/0.533 | allCV=4, bal=12, evH=5, allEV=2 |
| 210.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 210.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 7 | 0.159/0.153/0.158/0.153 | allCV=5, bal=10, evH=0, allEV=0 |
| 210.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 210.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 210.000 | unbounded_reference | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 240.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 240.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 12 | 12/23 | 0 | 0.566/0.534/0.557/0.533 | allCV=4, bal=12, evH=5, allEV=2 |
| 240.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 240.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 7 | 0.159/0.153/0.158/0.153 | allCV=5, bal=10, evH=0, allEV=0 |
| 240.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 240.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 240.000 | unbounded_reference | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 280.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 280.000 | depot_chargers_manifest_total_diagnostic | fail | 23/23 | 12 | 12/23 | 0 | 0.566/0.534/0.557/0.533 | allCV=4, bal=12, evH=5, allEV=2 |
| 280.000 | depot_manifest_ev_no_public_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |
| 280.000 | goeke_ev_cap_only | fail_fake_balance | 23/23 | 12 | 12/23 | 7 | 0.159/0.153/0.158/0.153 | allCV=5, bal=10, evH=0, allEV=0 |
| 280.000 | goeke_total_cap | incomplete | 0/23 | 0 | 0/23 | 0 | /// | allCV=0, bal=0, evH=0, allEV=0 |
| 280.000 | public_charging_disabled_diagnostic | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 280.000 | unbounded_reference | fail | 23/23 | 4 | 4/23 | 0 | 0.794/0.769/0.786/0.736 | allCV=2, bal=4, evH=11, allEV=6 |
| 282.000 | depot_chargers_manifest_ev_diagnostic | fail_fake_balance | 23/23 | 13 | 13/23 | 5 | 0.374/0.346/0.369/0.362 | allCV=3, bal=11, evH=4, allEV=0 |

Top failure rows:

| battery | constraint | instance | reason | mean EV route/customer/demand/distance |
|---:|---|---|---|---|
| 60.000 | depot_chargers_manifest_ev_diagnostic | multidepot/e2-multidepot-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | multidepot/e2-multidepot-15c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | multidepot/e2-multidepot-20c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | multidepot/e2-multidepot-25c-01 | fake_balance | 0.286/0.240/0.276/0.191 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | threeshift/e2-threeshift-100c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | threeshift/e2-threeshift-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-100c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-10c-01 | fake_balance | 0.250/0.200/0.262/0.135 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-15c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-20c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-25c-01 | route_share_outside_practical_band | 0.143/0.080/0.126/0.057 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-50c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_ev_diagnostic | vanilla/e2-vanilla-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | multidepot/e2-multidepot-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | multidepot/e2-multidepot-25c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | threeshift/e2-threeshift-100c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | threeshift/e2-threeshift-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-100c-01 | fake_balance | 0.212/0.190/0.196/0.110 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-10c-01 | fake_balance | 0.250/0.200/0.262/0.135 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-15c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-20c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-25c-01 | fake_balance | 0.286/0.200/0.257/0.148 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-50c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_chargers_manifest_total_diagnostic | vanilla/e2-vanilla-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | multidepot/e2-multidepot-150c-01 | fake_balance | 0.367/0.327/0.358/0.169 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | multidepot/e2-multidepot-15c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | multidepot/e2-multidepot-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | multidepot/e2-multidepot-20c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | multidepot/e2-multidepot-25c-01 | fake_balance | 0.286/0.240/0.276/0.191 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | multidepot/e2-multidepot-50c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | threeshift/e2-threeshift-100c-01 | fake_balance | 0.300/0.290/0.288/0.163 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | vanilla/e2-vanilla-100c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | vanilla/e2-vanilla-10c-01 | fake_balance | 0.250/0.200/0.262/0.135 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | vanilla/e2-vanilla-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | vanilla/e2-vanilla-15c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.000 | depot_manifest_ev_no_public_diagnostic | vanilla/e2-vanilla-200c-01 | fake_balance | 0.206/0.155/0.182/0.095 |

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
