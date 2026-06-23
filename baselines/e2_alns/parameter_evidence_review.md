# 09h Evidence-Bound Parameter Review

Conclusion: `HIGHWAY_BATTERY_UPDATE_SUPPORTED`.

An evidence-bound highway/regional modern-battery scenario remained competitive through staged true reoptimization.

## Environment

- repo_head: `e3140e5b534a4a53dc6c13b476f17be970721497`
- diagnostic_artifact_commit: `PENDING_COMMIT`
- branch: `codex/reporting-pipeline`
- python: `/opt/anaconda3/bin/python3.13`
- python_version: `3.13.9`
- numpy: `2.3.5`
- PYTHONHASHSEED: `0`
- carbon_price: `0.05034`
- reopt_policy: `auto`
- elapsed_seconds: `8321.272`

## Command

```bash
baselines/e2_alns/parameter_evidence_review.py
```

Stdout summary:

```json
{
  "fixed_replay_rows": 48,
  "output_dir": "baselines/e2_alns/parameter_evidence_review_data",
  "phase0_only": false,
  "provisional_candidates": 6,
  "reference_rows": 30,
  "reopt_policy": "auto",
  "reopt_rows": 30,
  "reopt_trigger_rows": 23,
  "report": "baselines/e2_alns/parameter_evidence_review.md",
  "route_regime_rows": 6,
  "schema_version": "setp-09h-stdout-summary.v1",
  "verdict": "HIGHWAY_BATTERY_UPDATE_SUPPORTED"
}
```

## Evidence Matrix

| source | year | type | scale | speed | battery | vehicle class | regime | support |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Goeke2015 | 2015 | local_pdf | 10-200 customers | 90.0 | 80.0 | Goeke E-VRPTWMF benchmark truck | benchmark_regional | baseline_lineage_only |
| Qiu2024 | 2024 | local_pdf | 5/10/15/100 customers with 2/3/4/20 stations | 60.0 | 60.0 | mixed ICEV/EV benchmark fleet | urban_regional_benchmark | urban_or_regional_convention |
| Chen2023 | 2023 | local_pdf | 48/4 to 288/6 benchmark; 71-store case study | 30-60 | 80.0 | urban medium distribution trucks | urban_multidepot | urban_speed_only |
| Li2020 | 2020 | local_pdf | r101-21, 100 customers and 20 charging facilities |  |  | EV/CV mixed fleet | benchmark_mixed | mechanism_support |
| MercedesESprinter | 2026 | official_web | large electric van product |  | 81/113 usable | large van | van_delivery | conditional_large_van |
| FordETransit2025 | 2025 | official_pdf | large electric van product |  | 89 usable | large van | van_delivery | conditional_large_van |
| VolvoFLFE2023 | 2023 | official_web | electric distribution trucks |  | 280-565 FL; 280-375 FE | medium distribution truck | regional_distribution | strong_distribution_truck_280 |
| VolvoFH_Electric | 2026 | official_web | heavy electric truck product |  | 360-540 | heavy truck | heavy_highway | future_vehicle_class_fork |
| DaimlerEActros600 | 2026 | official_web | heavy long-haul electric truck product |  | 621 installed, >95% usable | heavy long-haul truck | heavy_highway | future_vehicle_class_fork |
| UK_DfT_SRN_2025 | 2025 | government_web | UK Strategic Road Network | 91.1 |  | all traffic | highway_cross_city | supports_90kmh_cross_city |
| UK_DfT_LocalA_2025 | 2025 | government_web | UK local A roads | urban 27.5; rural 55.2 |  | all traffic | urban_local | supports_urban_fork_only |

## Reference Audit And 09f Dominance

| instance | classifier | best all-CV | seed | best mixed | seed | best gap % | mean all-CV | mean mixed | mean gap % | paired all-CV wins | paired mixed wins |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | 4918.752360 | 5 | 4874.971895 | 1 | -0.890073 | 4944.487761 | 5010.187518 | 1.328747 | 3 | 2 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | 7439.741687 | 2 | 7256.330133 | 2 | -2.465295 | 7451.731179 | 7554.986667 | 1.385658 | 4 | 1 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | 8979.132838 | 1 | 9093.841324 | 5 | 1.277501 | 8991.802112 | 9301.859822 | 3.448227 | 5 | 0 |

Checkpoint audit status:

| instance | role | seed | status | total | CV | EV | viol | csv diff | ckpt diff |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-100c-01 | allcv | 1 | OK | 4945.037699 | 29 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | allcv | 2 | OK | 4941.366750 | 29 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | allcv | 3 | OK | 4958.344723 | 30 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | allcv | 4 | OK | 4958.937271 | 30 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | allcv | 5 | OK | 4918.752360 | 29 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | mixed | 1 | OK | 4874.971895 | 10 | 22 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | mixed | 2 | OK | 5186.520656 | 10 | 24 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | mixed | 3 | OK | 4962.492327 | 12 | 20 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | mixed | 4 | OK | 4939.258835 | 11 | 21 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | mixed | 5 | OK | 5087.693874 | 10 | 24 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | allcv | 1 | OK | 7464.210179 | 48 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | allcv | 2 | OK | 7439.741687 | 48 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | allcv | 3 | OK | 7459.639441 | 48 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | allcv | 4 | OK | 7449.754118 | 48 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | allcv | 5 | OK | 7445.310471 | 48 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | mixed | 1 | OK | 7636.937667 | 14 | 39 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | mixed | 2 | OK | 7256.330133 | 15 | 35 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | mixed | 3 | OK | 7711.283492 | 14 | 40 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | mixed | 4 | OK | 7589.467151 | 15 | 37 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | mixed | 5 | OK | 7580.914893 | 13 | 41 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | allcv | 1 | OK | 8979.132838 | 62 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | allcv | 2 | OK | 8982.893041 | 62 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | allcv | 3 | OK | 9023.865534 | 63 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | allcv | 4 | OK | 8987.128891 | 62 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | allcv | 5 | OK | 8985.990256 | 62 | 0 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | mixed | 1 | OK | 9164.523153 | 12 | 58 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | mixed | 2 | OK | 9317.960097 | 13 | 58 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | mixed | 3 | OK | 9478.381063 | 12 | 61 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | mixed | 4 | OK | 9454.593470 | 10 | 62 | 0 | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | mixed | 5 | OK | 9093.841324 | 13 | 55 | 0 | 0.000000 | 0.000000 |

## Route-Regime Audit

| instance | role | seed | regime | routes | dist mean | dist p75 | dist p90 | dist max | max kWh | >80 | >113 | >160 | >280 | dur90 max | dur40 max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-100c-01 | allcv | 5 | regional_cross_city_like | 29 | 139.060265 | 156.458296 | 220.910719 | 248.067540 | 157.534504 | 17 | 7 | 0 | 0 | 3.629084 | 7.074466 |
| e2-threeshift-100c-01 | mixed | 1 | regional_cross_city_like | 32 | 128.284379 | 154.142836 | 222.194921 | 285.094127 | 181.499666 | 13 | 7 | 1 | 0 | 4.046046 | 8.005687 |
| e2-threeshift-150c-01 | allcv | 2 | regional_cross_city_like | 48 | 116.356004 | 157.079692 | 216.861195 | 261.184550 | 164.367500 | 21 | 9 | 1 | 0 | 3.784828 | 7.412392 |
| e2-threeshift-150c-01 | mixed | 2 | regional_cross_city_like | 50 | 114.450240 | 149.359361 | 209.743029 | 250.272808 | 158.209360 | 21 | 9 | 0 | 0 | 3.626080 | 7.097569 |
| e2-threeshift-200c-01 | allcv | 1 | regional_cross_city_like | 62 | 100.579006 | 138.425371 | 184.495607 | 237.452255 | 149.749507 | 18 | 7 | 0 | 0 | 3.516136 | 6.814084 |
| e2-threeshift-200c-01 | mixed | 5 | regional_cross_city_like | 68 | 98.809798 | 130.326146 | 185.442451 | 237.389618 | 149.627968 | 18 | 8 | 0 | 0 | 3.479329 | 6.776407 |

Regime labels are descriptive gates, not proof by themselves: `urban_like` means p90 route distance <=30km and max <=50km; `regional_cross_city_like` means p75 >=50km or max >=100km; otherwise `mixed_regime`.

## Evidence-Bound Fixed Replay

| instance | scenario | evidence | all-CV | mixed | gap % | flip | public kWh | occ cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-100c-01 | A_baseline | baseline | 4918.752360 | 4874.971895 | -0.890073 | True | 29.187364 | 14.593682 |
| e2-threeshift-100c-01 | B_modern_large_van_89 | conditional | 4918.752360 | 4853.365277 | -1.329343 | True | 10.502670 | 5.251335 |
| e2-threeshift-100c-01 | C_modern_large_van_113 | conditional | 4918.752360 | 4840.696600 | -1.586902 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | D_bridge_160 | diagnostic | 4918.752360 | 4840.696600 | -1.586902 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | E_distribution_truck_280 | strong | 4918.752360 | 4840.696600 | -1.586902 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | F_urban_40_baseline_battery | urban_only | 4793.415392 | 4657.425793 | -2.837008 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | G_urban_40_modern_van | urban_only | 4793.415392 | 4657.425793 | -2.837008 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | H_highway_60mph_distribution | strong | 4984.497605 | 4896.044146 | -1.774571 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | A_baseline | baseline | 7439.741687 | 7256.330133 | -2.465295 | True | 59.182348 | 29.591174 |
| e2-threeshift-150c-01 | B_modern_large_van_89 | conditional | 7439.741687 | 7197.770860 | -3.252409 | True | 10.579699 | 5.289849 |
| e2-threeshift-150c-01 | C_modern_large_van_113 | conditional | 7439.741687 | 7185.663403 | -3.415149 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | D_bridge_160 | diagnostic | 7439.741687 | 7185.663403 | -3.415149 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | E_distribution_truck_280 | strong | 7439.741687 | 7185.663403 | -3.415149 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | F_urban_40_baseline_battery | urban_only | 7266.158296 | 6932.395325 | -4.593390 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | G_urban_40_modern_van | urban_only | 7266.158296 | 6932.395325 | -4.593390 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | H_highway_60mph_distribution | strong | 7530.794493 | 7262.936933 | -3.556830 | True | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | A_baseline | baseline | 8979.132838 | 9093.841324 | 1.277501 | False | 54.119816 | 27.059908 |
| e2-threeshift-200c-01 | B_modern_large_van_89 | conditional | 8979.132838 | 9047.781147 | 0.764532 | False | 16.021608 | 8.010804 |
| e2-threeshift-200c-01 | C_modern_large_van_113 | conditional | 8979.132838 | 9024.603119 | 0.506399 | False | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | D_bridge_160 | diagnostic | 8979.132838 | 9024.603119 | 0.506399 | False | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | E_distribution_truck_280 | strong | 8979.132838 | 9024.603119 | 0.506399 | False | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | F_urban_40_baseline_battery | urban_only | 8785.322402 | 8704.460431 | -0.920421 | True | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | G_urban_40_modern_van | urban_only | 8785.322402 | 8704.460431 | -0.920421 | True | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | H_highway_60mph_distribution | strong | 9080.795698 | 9110.491382 | 0.327016 | False | 0.000000 | 0.000000 |

Fixed replay strips public station nodes from EV routes, replays charging under the override, and independently evaluates/checks the result. It is mechanism evidence only.

## Reoptimization Triggers

| instance | scenario | route regime | evidence | gap % | run? | reason |
| --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-150c-01 | H_highway_60mph_distribution | regional_cross_city_like | strong | -3.556830 | True | evidence applies and fixed replay gap <= 1%; true reoptimization scheduled |
| e2-threeshift-150c-01 | E_distribution_truck_280 | regional_cross_city_like | strong | -3.415149 | True | evidence applies and fixed replay gap <= 1%; true reoptimization scheduled |
| e2-threeshift-100c-01 | H_highway_60mph_distribution | regional_cross_city_like | strong | -1.774571 | True | evidence applies and fixed replay gap <= 1%; true reoptimization scheduled |
| e2-threeshift-100c-01 | E_distribution_truck_280 | regional_cross_city_like | strong | -1.586902 | True | evidence applies and fixed replay gap <= 1%; true reoptimization scheduled |
| e2-threeshift-200c-01 | H_highway_60mph_distribution | regional_cross_city_like | strong | 0.327016 | True | evidence applies and fixed replay gap <= 1%; true reoptimization scheduled |
| e2-threeshift-200c-01 | E_distribution_truck_280 | regional_cross_city_like | strong | 0.506399 | True | evidence applies and fixed replay gap <= 1%; true reoptimization scheduled |
| e2-threeshift-150c-01 | F_urban_40_baseline_battery | regional_cross_city_like | urban_only | -4.593390 | False | scenario regime urban_local does not match route regime regional_cross_city_like |
| e2-threeshift-150c-01 | G_urban_40_modern_van | regional_cross_city_like | urban_only | -4.593390 | False | scenario regime urban_local does not match route regime regional_cross_city_like |
| e2-threeshift-150c-01 | C_modern_large_van_113 | regional_cross_city_like | conditional | -3.415149 | False | scenario regime van_delivery does not match route regime regional_cross_city_like |
| e2-threeshift-150c-01 | D_bridge_160 | regional_cross_city_like | diagnostic | -3.415149 | False | scenario regime diagnostic_bridge does not match route regime regional_cross_city_like |
| e2-threeshift-150c-01 | B_modern_large_van_89 | regional_cross_city_like | conditional | -3.252409 | False | scenario regime van_delivery does not match route regime regional_cross_city_like |
| e2-threeshift-100c-01 | F_urban_40_baseline_battery | regional_cross_city_like | urban_only | -2.837008 | False | scenario regime urban_local does not match route regime regional_cross_city_like |
| e2-threeshift-100c-01 | G_urban_40_modern_van | regional_cross_city_like | urban_only | -2.837008 | False | scenario regime urban_local does not match route regime regional_cross_city_like |
| e2-threeshift-150c-01 | A_baseline | regional_cross_city_like | baseline | -2.465295 | False | scenario regime current does not match route regime regional_cross_city_like |
| e2-threeshift-100c-01 | C_modern_large_van_113 | regional_cross_city_like | conditional | -1.586902 | False | scenario regime van_delivery does not match route regime regional_cross_city_like |
| e2-threeshift-100c-01 | D_bridge_160 | regional_cross_city_like | diagnostic | -1.586902 | False | scenario regime diagnostic_bridge does not match route regime regional_cross_city_like |
| e2-threeshift-100c-01 | B_modern_large_van_89 | regional_cross_city_like | conditional | -1.329343 | False | scenario regime van_delivery does not match route regime regional_cross_city_like |
| e2-threeshift-200c-01 | F_urban_40_baseline_battery | regional_cross_city_like | urban_only | -0.920421 | False | scenario regime urban_local does not match route regime regional_cross_city_like |
| e2-threeshift-200c-01 | G_urban_40_modern_van | regional_cross_city_like | urban_only | -0.920421 | False | scenario regime urban_local does not match route regime regional_cross_city_like |
| e2-threeshift-100c-01 | A_baseline | regional_cross_city_like | baseline | -0.890073 | False | scenario regime current does not match route regime regional_cross_city_like |
| e2-threeshift-200c-01 | C_modern_large_van_113 | regional_cross_city_like | conditional | 0.506399 | False | scenario regime van_delivery does not match route regime regional_cross_city_like |
| e2-threeshift-200c-01 | D_bridge_160 | regional_cross_city_like | diagnostic | 0.506399 | False | scenario regime diagnostic_bridge does not match route regime regional_cross_city_like |
| e2-threeshift-200c-01 | B_modern_large_van_89 | regional_cross_city_like | conditional | 0.764532 | False | scenario regime van_delivery does not match route regime regional_cross_city_like |

## True Reoptimization

| instance | scenario | seed | status | total | gap vs fixed allCV | elapsed | evals | CV | EV |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-150c-01 | H_highway_60mph_distribution | 1 | OK | 6862.768845 |  | 262.041227 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | H_highway_60mph_distribution | 2 | OK | 6866.092125 |  | 266.812594 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | H_highway_60mph_distribution | 3 | OK | 6862.768845 |  | 262.107626 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | H_highway_60mph_distribution | 4 | OK | 6862.768845 |  | 258.153759 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | H_highway_60mph_distribution | 5 | OK | 6866.092125 |  | 255.075172 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | E_distribution_truck_280 | 1 | OK | 6797.831448 |  | 256.528932 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | E_distribution_truck_280 | 2 | OK | 6801.080019 |  | 266.469915 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | E_distribution_truck_280 | 3 | OK | 6797.831448 |  | 254.482181 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | E_distribution_truck_280 | 4 | OK | 6797.831448 |  | 252.402819 | 16000 | 3 | 47 |
| e2-threeshift-150c-01 | E_distribution_truck_280 | 5 | OK | 6797.831448 |  | 261.995404 | 16000 | 3 | 47 |
| e2-threeshift-100c-01 | H_highway_60mph_distribution | 1 | OK | 4536.208344 |  | 155.707352 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | H_highway_60mph_distribution | 2 | OK | 4536.208344 |  | 157.138665 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | H_highway_60mph_distribution | 3 | OK | 4536.208344 |  | 157.961982 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | H_highway_60mph_distribution | 4 | OK | 4536.208344 |  | 155.578094 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | H_highway_60mph_distribution | 5 | OK | 4536.208344 |  | 158.590924 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | E_distribution_truck_280 | 1 | OK | 4491.771010 |  | 158.032141 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | E_distribution_truck_280 | 2 | OK | 4491.771010 |  | 156.744102 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | E_distribution_truck_280 | 3 | OK | 4491.771010 |  | 154.500477 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | E_distribution_truck_280 | 4 | OK | 4491.771010 |  | 155.083467 | 16000 | 0 | 32 |
| e2-threeshift-100c-01 | E_distribution_truck_280 | 5 | OK | 4491.771010 |  | 155.464881 | 16000 | 0 | 32 |
| e2-threeshift-200c-01 | H_highway_60mph_distribution | 1 | OK | 8703.142424 |  | 409.841006 | 16000 | 1 | 67 |
| e2-threeshift-200c-01 | H_highway_60mph_distribution | 2 | OK | 8703.142424 |  | 408.268757 | 16000 | 1 | 67 |
| e2-threeshift-200c-01 | H_highway_60mph_distribution | 3 | OK | 8703.142424 |  | 406.785972 | 16000 | 1 | 67 |
| e2-threeshift-200c-01 | H_highway_60mph_distribution | 4 | OK | 8703.142424 |  | 407.840318 | 16000 | 1 | 67 |
| e2-threeshift-200c-01 | H_highway_60mph_distribution | 5 | OK | 8634.653988 |  | 419.256200 | 16000 | 0 | 68 |
| e2-threeshift-200c-01 | E_distribution_truck_280 | 1 | OK | 8629.766225 |  | 417.913451 | 16000 | 1 | 67 |
| e2-threeshift-200c-01 | E_distribution_truck_280 | 2 | OK | 8629.766225 |  | 421.459752 | 16000 | 1 | 67 |
| e2-threeshift-200c-01 | E_distribution_truck_280 | 3 | OK | 8629.766225 |  | 399.107014 | 16000 | 1 | 67 |
| e2-threeshift-200c-01 | E_distribution_truck_280 | 4 | OK | 8629.766225 |  | 413.451545 | 16000 | 1 | 67 |
| e2-threeshift-200c-01 | E_distribution_truck_280 | 5 | OK | 8563.206193 |  | 430.580570 | 16000 | 0 | 68 |

## Provisional Candidates

| instance | scenario | status | seeds | mean cost | best cost | mean gap % | best gap % | mean EV routes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-150c-01 | H_highway_60mph_distribution | stage1_and_stage2_completed | 1,2,3,4,5 | 6864.098157 | 6862.768845 | -8.852935 | -8.870587 | 47.000000 |
| e2-threeshift-150c-01 | E_distribution_truck_280 | stage1_and_stage2_completed | 1,2,3,4,5 | 6798.481162 | 6797.831448 | -8.619392 | -8.628125 | 47.000000 |
| e2-threeshift-100c-01 | H_highway_60mph_distribution | stage1_and_stage2_completed | 1,2,3,4,5 | 4536.208344 | 4536.208344 | -8.993670 | -8.993670 | 32.000000 |
| e2-threeshift-100c-01 | E_distribution_truck_280 | stage1_and_stage2_completed | 1,2,3,4,5 | 4491.771010 | 4491.771010 | -8.680684 | -8.680684 | 32.000000 |
| e2-threeshift-200c-01 | H_highway_60mph_distribution | stage1_and_stage2_completed | 1,2,3,4,5 | 8689.444737 | 8634.653988 | -4.309655 | -4.913024 | 67.200000 |
| e2-threeshift-200c-01 | E_distribution_truck_280 | stage1_and_stage2_completed | 1,2,3,4,5 | 8616.454218 | 8563.206193 | -4.039127 | -4.632147 | 67.200000 |

## Do Not Do This

- Do not set 40km/h as the cross-city default just because fixed replay flips.
- Do not treat `D_bridge_160` as strong modern-truck evidence without an additional source.
- Do not report fixed replay as true reoptimization.
- Do not scan carbon price in this lane; it stayed fixed at 0.05034.

## Artifacts

- `baselines/e2_alns/parameter_evidence_review.py`
- `baselines/e2_alns/parameter_evidence_review.md`
- `baselines/e2_alns/parameter_evidence_review_data/evidence_matrix.csv`
- `baselines/e2_alns/parameter_evidence_review_data/reference_audit.csv`
- `baselines/e2_alns/parameter_evidence_review_data/route_regime.csv`
- `baselines/e2_alns/parameter_evidence_review_data/fixed_replay.csv`
- `baselines/e2_alns/parameter_evidence_review_data/reopt_triggers.csv`
- `baselines/e2_alns/parameter_evidence_review_data/reopt_refine.csv`
- `baselines/e2_alns/parameter_evidence_review_data/metadata.json`
