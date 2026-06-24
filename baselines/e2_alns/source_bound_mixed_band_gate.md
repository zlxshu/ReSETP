# 09l Source-Bound Practical Mixed-Band Gate

Commit: `d7eea173`.
Python: `/opt/anaconda3/bin/python3.13`; NumPy: `2.3.5`.
Frozen defaults: `B_battery_kwh=280.0`, `v_speed_ms=25.0`, `carbon_price=0.05034`.
Battery values in this report are in-memory overrides only; `prices.py`, `cost.py`, `check.py`, `evaluation.py`, bundle data, and algorithm semantics are not changed.
Command: `/opt/anaconda3/bin/python3.13 baselines/e2_alns/source_bound_mixed_band_gate.py --screen-only --stage-a-eval-budget 1000 --workers 6 --runtime-small 180 --runtime-medium 300 --runtime-large 900 --task-timeout-buffer 90 --retry-timeouts`.

## Verdict

`BATTERY_ONLY_INSUFFICIENT`.

Stage A source-bound screen found no pass or near-pass non-80kWh candidate across the full gradient of -01 instances, so Stage B/C were not triggered. Treat this as a screen-gated insufficiency result, not as a Stage C confirmation.

Important reading rule: `80kWh` is treated only as a historical/literature reference. It is not eligible to rescue the main scenario, because earlier large-scale diagnosis showed that the 80kWh setting makes EVs too weak in the cross-city regime.

## Candidate Sources

| battery kWh | scan | eligible | reference | secondary-only | promotion without extra source | sources | tiers |
|---:|---|---|---|---|---|---|---|
| 60.0 | True | True | False | False | True | IsuzuNRREV;Qiu2024 | literature_benchmark;strong_current_vehicle_class |
| 80.0 | False | False | True | False | False | Chen2023;Goeke2015 | literature_benchmark |
| 81.0 | True | True | False | False | True | MercedesESprinter | conditional_van |
| 82.6 | True | True | False | True | False | FusoECanter | strong_current_vehicle_class |
| 89.0 | True | True | False | False | True | FordETransit2025 | conditional_van |
| 100.0 | True | True | False | False | True | IsuzuNRREV | strong_current_vehicle_class |
| 113.0 | True | True | False | False | True | MercedesESprinter | conditional_van |
| 123.9 | True | True | False | True | False | FusoECanter | strong_current_vehicle_class |
| 140.0 | True | True | False | False | True | IsuzuNRREV | strong_current_vehicle_class |
| 141.0 | True | True | False | False | True | DAFXBElectric | strong_current_vehicle_class |
| 150.0 | True | True | False | False | True | MackMDElectric | strong_current_vehicle_class |
| 176.0 | True | True | False | False | True | RenaultTrucksETechD | strong_current_vehicle_class |
| 180.0 | True | True | False | False | True | IsuzuNRREV | strong_current_vehicle_class |
| 194.0 | True | True | False | False | True | FreightlinerEM2 | strong_current_vehicle_class |
| 200.0 | True | True | False | False | True | RenaultTrucksETechD | strong_current_vehicle_class |
| 210.0 | True | True | False | False | True | DAFXBElectric;InternationalEMV | strong_current_vehicle_class |
| 240.0 | True | True | False | False | True | MackMDElectric | strong_current_vehicle_class |
| 280.0 | True | True | False | False | True | VolvoFLFE2023 | strong_current_vehicle_class |
| 282.0 | True | True | False | False | True | DAFXBElectric | strong_current_vehicle_class |
| 291.0 | True | True | False | False | True | FreightlinerEM2 | strong_current_vehicle_class |

## Override Audit

Phase 0 status: `OK`. The runner uses explicit override warm starts and independently replays every winner through `evaluate/check(..., override)`.

## Stage A Screen

| battery | status | winners | instance pass/fail | scale pass/fail | mean route/customer/demand/distance EV share | composition counts | sources |
|---:|---|---:|---|---|---|---|---|
| 60.0 | fail | 23/23 | 12/11 | 12/11 | 0.257/0.216/0.243/0.153 | allEV=0, EVheavy=0, balanced=12, CVheavy=1, allCV=10 | IsuzuNRREV;Qiu2024 |
| 81.0 | fail | 23/23 | 17/6 | 17/6 | 0.430/0.387/0.422/0.320 | allEV=0, EVheavy=0, balanced=17, CVheavy=0, allCV=6 | MercedesESprinter |
| 82.6 | fail | 23/23 | 16/7 | 16/7 | 0.376/0.328/0.362/0.269 | allEV=0, EVheavy=0, balanced=16, CVheavy=0, allCV=7 | FusoECanter |
| 89.0 | fail | 23/23 | 15/8 | 15/8 | 0.512/0.460/0.499/0.400 | allEV=0, EVheavy=4, balanced=15, CVheavy=0, allCV=4 | FordETransit2025 |
| 100.0 | fail | 23/23 | 11/12 | 11/12 | 0.614/0.575/0.606/0.516 | allEV=1, EVheavy=7, balanced=11, CVheavy=0, allCV=4 | IsuzuNRREV |
| 113.0 | fail | 23/23 | 6/17 | 6/17 | 0.750/0.713/0.744/0.681 | allEV=4, EVheavy=11, balanced=6, CVheavy=0, allCV=2 | MercedesESprinter |
| 123.9 | fail | 23/23 | 5/18 | 5/18 | 0.856/0.822/0.849/0.798 | allEV=2, EVheavy=16, balanced=5, CVheavy=0, allCV=0 | FusoECanter |
| 140.0 | fail | 23/23 | 3/20 | 3/20 | 0.857/0.830/0.846/0.804 | allEV=3, EVheavy=16, balanced=3, CVheavy=0, allCV=1 | IsuzuNRREV |
| 141.0 | fail | 23/23 | 3/20 | 3/20 | 0.857/0.831/0.846/0.804 | allEV=3, EVheavy=16, balanced=3, CVheavy=0, allCV=1 | DAFXBElectric |
| 150.0 | fail | 23/23 | 3/20 | 3/20 | 0.812/0.783/0.801/0.761 | allEV=3, EVheavy=15, balanced=3, CVheavy=0, allCV=2 | MackMDElectric |
| 176.0 | fail | 23/23 | 3/20 | 3/20 | 0.860/0.834/0.849/0.811 | allEV=4, EVheavy=15, balanced=3, CVheavy=0, allCV=1 | RenaultTrucksETechD |
| 180.0 | fail | 23/23 | 3/20 | 3/20 | 0.857/0.831/0.847/0.805 | allEV=3, EVheavy=16, balanced=3, CVheavy=0, allCV=1 | IsuzuNRREV |
| 194.0 | fail | 23/23 | 3/20 | 3/20 | 0.812/0.785/0.801/0.759 | allEV=2, EVheavy=16, balanced=3, CVheavy=0, allCV=2 | FreightlinerEM2 |
| 200.0 | fail | 23/23 | 3/20 | 3/20 | 0.812/0.785/0.801/0.759 | allEV=2, EVheavy=16, balanced=3, CVheavy=0, allCV=2 | RenaultTrucksETechD |
| 210.0 | fail | 23/23 | 3/20 | 3/20 | 0.812/0.785/0.801/0.759 | allEV=2, EVheavy=16, balanced=3, CVheavy=0, allCV=2 | DAFXBElectric;InternationalEMV |
| 240.0 | fail | 23/23 | 3/20 | 3/20 | 0.854/0.827/0.844/0.801 | allEV=3, EVheavy=16, balanced=3, CVheavy=0, allCV=1 | MackMDElectric |
| 280.0 | fail | 23/23 | 3/20 | 3/20 | 0.854/0.827/0.844/0.801 | allEV=3, EVheavy=16, balanced=3, CVheavy=0, allCV=1 | VolvoFLFE2023 |
| 282.0 | fail | 23/23 | 3/20 | 3/20 | 0.854/0.827/0.844/0.801 | allEV=3, EVheavy=16, balanced=3, CVheavy=0, allCV=1 | DAFXBElectric |
| 291.0 | fail | 23/23 | 3/20 | 3/20 | 0.854/0.827/0.844/0.801 | allEV=3, EVheavy=16, balanced=3, CVheavy=0, allCV=1 | FreightlinerEM2 |

By-scale detail is in the CSV. Rows outside the 20%-80% route-share band are shown below.

| battery | family | size | route/customer/demand/distance EV share | source |
|---:|---|---:|---|---|
| 60.0 | multidepot | 150 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | threeshift | 50 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | threeshift | 75 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | vanilla | 15 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | vanilla | 20 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | vanilla | 25 | 0.143/0.080/0.118/0.052 | IsuzuNRREV;Qiu2024 |
| 60.0 | vanilla | 50 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | vanilla | 75 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | vanilla | 100 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | vanilla | 150 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 60.0 | vanilla | 200 | 0.000/0.000/0.000/0.000 | IsuzuNRREV;Qiu2024 |
| 81.0 | multidepot | 20 | 0.000/0.000/0.000/0.000 | MercedesESprinter |
| 81.0 | multidepot | 200 | 0.000/0.000/0.000/0.000 | MercedesESprinter |
| 81.0 | threeshift | 75 | 0.000/0.000/0.000/0.000 | MercedesESprinter |
| 81.0 | threeshift | 200 | 0.000/0.000/0.000/0.000 | MercedesESprinter |
| 81.0 | vanilla | 75 | 0.000/0.000/0.000/0.000 | MercedesESprinter |
| 81.0 | vanilla | 200 | 0.000/0.000/0.000/0.000 | MercedesESprinter |
| 82.6 | multidepot | 150 | 0.000/0.000/0.000/0.000 | FusoECanter |
| 82.6 | multidepot | 200 | 0.000/0.000/0.000/0.000 | FusoECanter |
| 82.6 | threeshift | 50 | 0.000/0.000/0.000/0.000 | FusoECanter |
| 82.6 | threeshift | 75 | 0.000/0.000/0.000/0.000 | FusoECanter |
| 82.6 | threeshift | 200 | 0.000/0.000/0.000/0.000 | FusoECanter |
| 82.6 | vanilla | 75 | 0.000/0.000/0.000/0.000 | FusoECanter |
| 82.6 | vanilla | 200 | 0.000/0.000/0.000/0.000 | FusoECanter |
| 89.0 | multidepot | 25 | 0.857/0.800/0.853/0.631 | FordETransit2025 |
| 89.0 | multidepot | 75 | 0.815/0.760/0.796/0.692 | FordETransit2025 |
| 89.0 | multidepot | 150 | 0.000/0.000/0.000/0.000 | FordETransit2025 |
| 89.0 | multidepot | 200 | 0.000/0.000/0.000/0.000 | FordETransit2025 |
| 89.0 | threeshift | 50 | 0.812/0.720/0.794/0.718 | FordETransit2025 |
| 89.0 | threeshift | 75 | 0.000/0.000/0.000/0.000 | FordETransit2025 |
| 89.0 | threeshift | 200 | 0.000/0.000/0.000/0.000 | FordETransit2025 |
| 89.0 | vanilla | 150 | 0.846/0.793/0.831/0.724 | FordETransit2025 |
| 100.0 | multidepot | 10 | 1.000/1.000/1.000/1.000 | IsuzuNRREV |
| 100.0 | multidepot | 50 | 0.875/0.860/0.862/0.809 | IsuzuNRREV |
| 100.0 | multidepot | 150 | 0.902/0.860/0.896/0.827 | IsuzuNRREV |
| 100.0 | multidepot | 200 | 0.000/0.000/0.000/0.000 | IsuzuNRREV |
| 100.0 | threeshift | 50 | 0.938/0.940/0.931/0.915 | IsuzuNRREV |
| 100.0 | threeshift | 75 | 0.000/0.000/0.000/0.000 | IsuzuNRREV |
| 100.0 | threeshift | 100 | 0.000/0.000/0.000/0.000 | IsuzuNRREV |
| 100.0 | threeshift | 150 | 0.840/0.800/0.832/0.685 | IsuzuNRREV |
| 100.0 | threeshift | 200 | 0.910/0.870/0.899/0.828 | IsuzuNRREV |
| 100.0 | vanilla | 50 | 0.824/0.760/0.793/0.753 | IsuzuNRREV |
| 100.0 | vanilla | 150 | 0.863/0.853/0.861/0.759 | IsuzuNRREV |
| 100.0 | vanilla | 200 | 0.000/0.000/0.000/0.000 | IsuzuNRREV |
| 113.0 | multidepot | 10 | 1.000/1.000/1.000/1.000 | MercedesESprinter |
| 113.0 | multidepot | 20 | 0.857/0.850/0.851/0.734 | MercedesESprinter |
| 113.0 | multidepot | 25 | 0.875/0.800/0.854/0.672 | MercedesESprinter |
| 113.0 | multidepot | 50 | 1.000/1.000/1.000/1.000 | MercedesESprinter |
| 113.0 | multidepot | 75 | 0.923/0.880/0.914/0.850 | MercedesESprinter |
| 113.0 | multidepot | 100 | 0.879/0.840/0.874/0.761 | MercedesESprinter |
| 113.0 | multidepot | 150 | 1.000/1.000/1.000/1.000 | MercedesESprinter |
| 113.0 | multidepot | 200 | 0.959/0.945/0.954/0.907 | MercedesESprinter |
| 113.0 | threeshift | 50 | 0.938/0.920/0.935/0.895 | MercedesESprinter |
| 113.0 | threeshift | 75 | 0.000/0.000/0.000/0.000 | MercedesESprinter |
| 113.0 | threeshift | 100 | 0.882/0.820/0.864/0.825 | MercedesESprinter |
| 113.0 | threeshift | 150 | 0.882/0.847/0.869/0.745 | MercedesESprinter |
| 113.0 | threeshift | 200 | 0.971/0.945/0.966/0.942 | MercedesESprinter |
| 113.0 | vanilla | 10 | 0.000/0.000/0.000/0.000 | MercedesESprinter |
| 113.0 | vanilla | 25 | 0.875/0.760/0.860/0.815 | MercedesESprinter |
| 113.0 | vanilla | 50 | 0.875/0.840/0.862/0.830 | MercedesESprinter |
| 113.0 | vanilla | 150 | 1.000/1.000/1.000/1.000 | MercedesESprinter |
| 123.9 | multidepot | 10 | 1.000/1.000/1.000/1.000 | FusoECanter |
| 123.9 | multidepot | 20 | 0.857/0.850/0.851/0.734 | FusoECanter |
| 123.9 | multidepot | 25 | 0.875/0.800/0.854/0.672 | FusoECanter |
| 123.9 | multidepot | 50 | 0.875/0.860/0.872/0.781 | FusoECanter |
| 123.9 | multidepot | 75 | 1.000/1.000/1.000/1.000 | FusoECanter |
| 123.9 | multidepot | 100 | 0.909/0.880/0.916/0.821 | FusoECanter |
| 123.9 | multidepot | 150 | 0.836/0.793/0.811/0.840 | FusoECanter |
| 123.9 | multidepot | 200 | 0.986/0.975/0.984/0.971 | FusoECanter |
| 123.9 | threeshift | 50 | 0.938/0.940/0.931/0.895 | FusoECanter |
| 123.9 | threeshift | 75 | 0.962/0.960/0.956/0.922 | FusoECanter |
| 123.9 | threeshift | 100 | 0.939/0.920/0.939/0.923 | FusoECanter |
| 123.9 | threeshift | 150 | 0.904/0.887/0.891/0.790 | FusoECanter |
| 123.9 | vanilla | 20 | 0.857/0.850/0.851/0.784 | FusoECanter |
| 123.9 | vanilla | 25 | 0.875/0.760/0.866/0.815 | FusoECanter |
| 123.9 | vanilla | 50 | 0.938/0.900/0.931/0.913 | FusoECanter |
| 123.9 | vanilla | 75 | 0.815/0.800/0.798/0.751 | FusoECanter |
| 123.9 | vanilla | 100 | 0.853/0.800/0.842/0.787 | FusoECanter |
| 123.9 | vanilla | 200 | 0.986/0.980/0.984/0.978 | FusoECanter |
| 140.0 | multidepot | 10 | 1.000/1.000/1.000/1.000 | IsuzuNRREV |
| ... | ... | ... | 239 more rows in CSV | ... |

Failure instances are also retained in CSV; this table shows the first 80.

| battery | family | instance | reason | mean route/customer/demand/distance EV share |
|---:|---|---|---|---|
| 60.0 | multidepot | e2-multidepot-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | threeshift | e2-threeshift-50c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | threeshift | e2-threeshift-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | vanilla | e2-vanilla-100c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | vanilla | e2-vanilla-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | vanilla | e2-vanilla-15c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | vanilla | e2-vanilla-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | vanilla | e2-vanilla-20c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | vanilla | e2-vanilla-25c-01 | route_share_outside_practical_band | 0.143/0.080/0.118/0.052 |
| 60.0 | vanilla | e2-vanilla-50c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 60.0 | vanilla | e2-vanilla-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 81.0 | multidepot | e2-multidepot-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 81.0 | multidepot | e2-multidepot-20c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 81.0 | threeshift | e2-threeshift-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 81.0 | threeshift | e2-threeshift-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 81.0 | vanilla | e2-vanilla-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 81.0 | vanilla | e2-vanilla-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 82.6 | multidepot | e2-multidepot-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 82.6 | multidepot | e2-multidepot-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 82.6 | threeshift | e2-threeshift-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 82.6 | threeshift | e2-threeshift-50c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 82.6 | threeshift | e2-threeshift-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 82.6 | vanilla | e2-vanilla-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 82.6 | vanilla | e2-vanilla-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 89.0 | multidepot | e2-multidepot-150c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 89.0 | multidepot | e2-multidepot-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 89.0 | multidepot | e2-multidepot-25c-01 | route_share_outside_practical_band | 0.857/0.800/0.853/0.631 |
| 89.0 | multidepot | e2-multidepot-75c-01 | route_share_outside_practical_band | 0.815/0.760/0.796/0.692 |
| 89.0 | threeshift | e2-threeshift-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 89.0 | threeshift | e2-threeshift-50c-01 | route_share_outside_practical_band | 0.812/0.720/0.794/0.718 |
| 89.0 | threeshift | e2-threeshift-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 89.0 | vanilla | e2-vanilla-150c-01 | route_share_outside_practical_band | 0.846/0.793/0.831/0.724 |
| 100.0 | multidepot | e2-multidepot-10c-01 | route_share_outside_practical_band | 1.000/1.000/1.000/1.000 |
| 100.0 | multidepot | e2-multidepot-150c-01 | route_share_outside_practical_band | 0.902/0.860/0.896/0.827 |
| 100.0 | multidepot | e2-multidepot-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 100.0 | multidepot | e2-multidepot-50c-01 | route_share_outside_practical_band | 0.875/0.860/0.862/0.809 |
| 100.0 | threeshift | e2-threeshift-100c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 100.0 | threeshift | e2-threeshift-150c-01 | route_share_outside_practical_band | 0.840/0.800/0.832/0.685 |
| 100.0 | threeshift | e2-threeshift-200c-01 | route_share_outside_practical_band | 0.910/0.870/0.899/0.828 |
| 100.0 | threeshift | e2-threeshift-50c-01 | route_share_outside_practical_band | 0.938/0.940/0.931/0.915 |
| 100.0 | threeshift | e2-threeshift-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 100.0 | vanilla | e2-vanilla-150c-01 | route_share_outside_practical_band | 0.863/0.853/0.861/0.759 |
| 100.0 | vanilla | e2-vanilla-200c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 100.0 | vanilla | e2-vanilla-50c-01 | route_share_outside_practical_band | 0.824/0.760/0.793/0.753 |
| 113.0 | multidepot | e2-multidepot-100c-01 | route_share_outside_practical_band | 0.879/0.840/0.874/0.761 |
| 113.0 | multidepot | e2-multidepot-10c-01 | route_share_outside_practical_band | 1.000/1.000/1.000/1.000 |
| 113.0 | multidepot | e2-multidepot-150c-01 | route_share_outside_practical_band | 1.000/1.000/1.000/1.000 |
| 113.0 | multidepot | e2-multidepot-200c-01 | route_share_outside_practical_band | 0.959/0.945/0.954/0.907 |
| 113.0 | multidepot | e2-multidepot-20c-01 | route_share_outside_practical_band | 0.857/0.850/0.851/0.734 |
| 113.0 | multidepot | e2-multidepot-25c-01 | route_share_outside_practical_band | 0.875/0.800/0.854/0.672 |
| 113.0 | multidepot | e2-multidepot-50c-01 | route_share_outside_practical_band | 1.000/1.000/1.000/1.000 |
| 113.0 | multidepot | e2-multidepot-75c-01 | route_share_outside_practical_band | 0.923/0.880/0.914/0.850 |
| 113.0 | threeshift | e2-threeshift-100c-01 | route_share_outside_practical_band | 0.882/0.820/0.864/0.825 |
| 113.0 | threeshift | e2-threeshift-150c-01 | route_share_outside_practical_band | 0.882/0.847/0.869/0.745 |
| 113.0 | threeshift | e2-threeshift-200c-01 | route_share_outside_practical_band | 0.971/0.945/0.966/0.942 |
| 113.0 | threeshift | e2-threeshift-50c-01 | route_share_outside_practical_band | 0.938/0.920/0.935/0.895 |
| 113.0 | threeshift | e2-threeshift-75c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 113.0 | vanilla | e2-vanilla-10c-01 | route_share_outside_practical_band | 0.000/0.000/0.000/0.000 |
| 113.0 | vanilla | e2-vanilla-150c-01 | route_share_outside_practical_band | 1.000/1.000/1.000/1.000 |
| 113.0 | vanilla | e2-vanilla-25c-01 | route_share_outside_practical_band | 0.875/0.760/0.860/0.815 |
| 113.0 | vanilla | e2-vanilla-50c-01 | route_share_outside_practical_band | 0.875/0.840/0.862/0.830 |
| 123.9 | multidepot | e2-multidepot-100c-01 | route_share_outside_practical_band | 0.909/0.880/0.916/0.821 |
| 123.9 | multidepot | e2-multidepot-10c-01 | route_share_outside_practical_band | 1.000/1.000/1.000/1.000 |
| 123.9 | multidepot | e2-multidepot-150c-01 | route_share_outside_practical_band | 0.836/0.793/0.811/0.840 |
| 123.9 | multidepot | e2-multidepot-200c-01 | route_share_outside_practical_band | 0.986/0.975/0.984/0.971 |
| 123.9 | multidepot | e2-multidepot-20c-01 | route_share_outside_practical_band | 0.857/0.850/0.851/0.734 |
| 123.9 | multidepot | e2-multidepot-25c-01 | route_share_outside_practical_band | 0.875/0.800/0.854/0.672 |
| 123.9 | multidepot | e2-multidepot-50c-01 | route_share_outside_practical_band | 0.875/0.860/0.872/0.781 |
| 123.9 | multidepot | e2-multidepot-75c-01 | route_share_outside_practical_band | 1.000/1.000/1.000/1.000 |
| 123.9 | threeshift | e2-threeshift-100c-01 | route_share_outside_practical_band | 0.939/0.920/0.939/0.923 |
| 123.9 | threeshift | e2-threeshift-150c-01 | route_share_outside_practical_band | 0.904/0.887/0.891/0.790 |
| 123.9 | threeshift | e2-threeshift-50c-01 | route_share_outside_practical_band | 0.938/0.940/0.931/0.895 |
| 123.9 | threeshift | e2-threeshift-75c-01 | route_share_outside_practical_band | 0.962/0.960/0.956/0.922 |
| 123.9 | vanilla | e2-vanilla-100c-01 | route_share_outside_practical_band | 0.853/0.800/0.842/0.787 |
| 123.9 | vanilla | e2-vanilla-200c-01 | route_share_outside_practical_band | 0.986/0.980/0.984/0.978 |
| 123.9 | vanilla | e2-vanilla-20c-01 | route_share_outside_practical_band | 0.857/0.850/0.851/0.784 |
| 123.9 | vanilla | e2-vanilla-25c-01 | route_share_outside_practical_band | 0.875/0.760/0.866/0.815 |
| 123.9 | vanilla | e2-vanilla-50c-01 | route_share_outside_practical_band | 0.938/0.900/0.931/0.913 |
| 123.9 | vanilla | e2-vanilla-75c-01 | route_share_outside_practical_band | 0.815/0.800/0.798/0.751 |
| 140.0 | multidepot | e2-multidepot-100c-01 | route_share_outside_practical_band | 0.971/0.960/0.970/0.921 |
| ... | ... | ... | 239 more rows in CSV | ... |

## Stage B Full 69-Instance Gate

Not collected.

## Stage C Confirmation

Not collected.

## Output Files

- `baselines/e2_alns/source_bound_mixed_band_gate_data/metadata.json`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/candidate_sources.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/phase0_override_audit.json`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_a_raw_runs.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_a_winners.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_a_candidate_summary.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_a_by_scale.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_a_failure_instances.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_b_raw_runs.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_b_winners.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_b_candidate_summary.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_b_by_scale.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_b_failure_instances.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_c_raw_runs.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_c_winners.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_c_candidate_summary.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_c_by_scale.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/stage_c_failure_instances.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/raw_runs.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/winners.csv`
- `baselines/e2_alns/source_bound_mixed_band_gate_data/conclusion.json`

## Decision Boundary

If no non-80kWh source-backed candidate passes across all scales and stability instances, do not keep tuning battery capacity. The next honest route is an operational-constraint fork, such as charging-capacity limits, EV capital/fleet-count limits, public charger scarcity, or long-route eligibility constraints.
