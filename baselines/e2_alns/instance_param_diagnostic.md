# 09e Instance Parameter Diagnostic

Conclusion: `BASELINE_MIXED_ALREADY_BEATS_CV_ON_SELECTED_CASES`.

Baseline selected small cases did not reproduce all-CV optimality: mixed best-found beat cv_only on 3/3 checked instances.

## Environment

- repo_head: `39879b4b768935f45f69b61474ef840befdfc5be`
- diagnostic_artifact_commit: `9f145998d5b99c9f36839b0b9fc648280a22ab53`
- branch: `codex/reporting-pipeline`
- python: `/opt/anaconda3/bin/python3.13`
- numpy: `2.3.5`
- PYTHONHASHSEED: `0`
- eval_budget: `80`
- max_runtime_seconds: `10.0`
- phase2_mode: `fixed_replay`
- elapsed_seconds: `46.131`

## Phase 0 Override Audit

| check | value |
| --- | --- |
| carbon price pinned | 0.05034 |
| evaluate speed override changes EV kWh | True |
| evaluate public price override changes cost | True |
| check battery override changes feasibility | True |
| big battery violation count | 0 |
| tiny battery violation count | 1 |
| solver objective probe | OK |
| solver objective changed | True |

Audit note: main scans avoid existing LNS/winner runner override paths and use explicit warm starts plus independent `evaluate/check(..., prices)` verification.

## Phase 1 Mechanism

| instance | variant | total | CV | EV | fix | fuel | elec | occ | carbon | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vanilla/e2-vanilla-25c-01 | cv_only | 1253.397191 | 7 | 0 | 560.000000 | 289.910042 | 0.000000 | 0.000000 | 26.180121 | OK |
| vanilla/e2-vanilla-25c-01 | mixed | 1175.268947 | 4 | 3 | 560.000000 | 192.032485 | 41.827568 | 4.155036 | 17.892540 | OK |
| vanilla/e2-vanilla-50c-01 | cv_only | 2900.831228 | 17 | 0 | 1360.000000 | 644.926036 | 0.000000 | 0.000000 | 58.239588 | OK |
| vanilla/e2-vanilla-50c-01 | mixed | 2832.657155 | 11 | 6 | 1360.000000 | 460.936707 | 106.814519 | 20.159435 | 42.845843 | OK |
| threeshift/e2-threeshift-50c-01 | cv_only | 2581.522512 | 16 | 0 | 1280.000000 | 544.800610 | 0.000000 | 0.000000 | 49.197833 | OK |
| threeshift/e2-threeshift-50c-01 | mixed | 2433.458968 | 8 | 9 | 1360.000000 | 277.001357 | 104.440123 | 3.360134 | 27.457042 | OK |

Best-row charging behavior:

| instance | variant | actions | depot kWh | public kWh | depot GBP | public GBP | occ GBP | EV>B | EV public | detour m |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vanilla/e2-vanilla-25c-01 | cv_only | 0 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0.000000 |
| vanilla/e2-vanilla-25c-01 | mixed | 4 | 188.954716 | 8.310073 | 35.013309 | 6.814260 | 4.155036 | 1 | 1 | 0.000000 |
| vanilla/e2-vanilla-50c-01 | cv_only | 0 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0.000000 |
| vanilla/e2-vanilla-50c-01 | mixed | 8 | 398.019674 | 40.318870 | 73.753046 | 33.061473 | 20.159435 | 2 | 2 | 3718.416178 |
| threeshift/e2-threeshift-50c-01 | cv_only | 0 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0.000000 |
| threeshift/e2-threeshift-50c-01 | mixed | 10 | 533.888303 | 6.720269 | 98.929502 | 5.510621 | 3.360134 | 1 | 1 | 7011.636636 |

## Phase 2 Single-Parameter Scan

| instance | parameter | value | cv_only | mixed | ev_only | best non-CV gap % | flip |
| --- | --- | --- | --- | --- | --- | --- | --- |
| threeshift/e2-threeshift-50c-01 | battery_kwh | 80.0 | 2581.522512 | 2433.458968 | nan | -5.735512 | True |
| threeshift/e2-threeshift-50c-01 | battery_kwh | 160.0 | 2581.522512 | 2422.536259 | nan | -6.158624 | True |
| threeshift/e2-threeshift-50c-01 | battery_kwh | 320.0 | 2581.522512 | 2422.536259 | nan | -6.158624 | True |
| threeshift/e2-threeshift-50c-01 | battery_kwh | 480.0 | 2581.522512 | 2422.536259 | nan | -6.158624 | True |
| threeshift/e2-threeshift-50c-01 | occupancy_fee | 0.0 | 2581.522512 | 2430.098833 | nan | -5.865673 | True |
| threeshift/e2-threeshift-50c-01 | occupancy_fee | 0.1 | 2581.522512 | 2430.770860 | nan | -5.839641 | True |
| threeshift/e2-threeshift-50c-01 | occupancy_fee | 0.5 | 2581.522512 | 2433.458968 | nan | -5.735512 | True |
| threeshift/e2-threeshift-50c-01 | public_station_price | 0.1853 | 2581.522512 | 2429.193613 | nan | -5.900739 | True |
| threeshift/e2-threeshift-50c-01 | public_station_price | 0.4 | 2581.522512 | 2430.636455 | nan | -5.844848 | True |
| threeshift/e2-threeshift-50c-01 | public_station_price | 0.82 | 2581.522512 | 2433.458968 | nan | -5.735512 | True |
| threeshift/e2-threeshift-50c-01 | speed_ms | 11.1 | 2518.694791 | 2341.230381 | nan | -7.045888 | True |
| threeshift/e2-threeshift-50c-01 | speed_ms | 16.7 | 2491.034567 | 2342.514193 | nan | -5.962196 | True |
| threeshift/e2-threeshift-50c-01 | speed_ms | 25.0 | 2581.522512 | 2433.458968 | nan | -5.735512 | True |
| vanilla/e2-vanilla-25c-01 | battery_kwh | 80.0 | 1253.397191 | 1175.268947 | nan | -6.233319 | True |
| vanilla/e2-vanilla-25c-01 | battery_kwh | 160.0 | 1253.397191 | 1165.850742 | nan | -6.984733 | True |
| vanilla/e2-vanilla-25c-01 | battery_kwh | 320.0 | 1253.397191 | 1165.850742 | nan | -6.984733 | True |
| vanilla/e2-vanilla-25c-01 | battery_kwh | 480.0 | 1253.397191 | 1165.850742 | nan | -6.984733 | True |
| vanilla/e2-vanilla-25c-01 | occupancy_fee | 0.0 | 1253.397191 | 1171.113911 | nan | -6.564821 | True |
| vanilla/e2-vanilla-25c-01 | occupancy_fee | 0.1 | 1253.397191 | 1171.944918 | nan | -6.498520 | True |
| vanilla/e2-vanilla-25c-01 | occupancy_fee | 0.5 | 1253.397191 | 1175.268947 | nan | -6.233319 | True |
| vanilla/e2-vanilla-25c-01 | public_station_price | 0.1853 | 1253.397191 | 1169.994544 | nan | -6.654127 | True |
| vanilla/e2-vanilla-25c-01 | public_station_price | 0.4 | 1253.397191 | 1171.778717 | nan | -6.511781 | True |
| vanilla/e2-vanilla-25c-01 | public_station_price | 0.82 | 1253.397191 | 1175.268947 | nan | -6.233319 | True |
| vanilla/e2-vanilla-25c-01 | speed_ms | 11.1 | 1219.892549 | 1125.843296 | nan | -7.709634 | True |
| vanilla/e2-vanilla-25c-01 | speed_ms | 16.7 | 1205.141960 | 1121.568862 | nan | -6.934710 | True |
| vanilla/e2-vanilla-25c-01 | speed_ms | 25.0 | 1253.397191 | 1175.268947 | nan | -6.233319 | True |
| vanilla/e2-vanilla-50c-01 | battery_kwh | 80.0 | 2900.831228 | 2832.657155 | nan | -2.350156 | True |
| vanilla/e2-vanilla-50c-01 | battery_kwh | 160.0 | 2900.831228 | 2785.205494 | nan | -3.985952 | True |
| vanilla/e2-vanilla-50c-01 | battery_kwh | 320.0 | 2900.831228 | 2785.205494 | nan | -3.985952 | True |
| vanilla/e2-vanilla-50c-01 | battery_kwh | 480.0 | 2900.831228 | 2785.205494 | nan | -3.985952 | True |
| vanilla/e2-vanilla-50c-01 | occupancy_fee | 0.0 | 2900.831228 | 2812.497720 | nan | -3.045110 | True |
| vanilla/e2-vanilla-50c-01 | occupancy_fee | 0.1 | 2900.831228 | 2816.529607 | nan | -2.906119 | True |
| vanilla/e2-vanilla-50c-01 | occupancy_fee | 0.5 | 2900.831228 | 2832.657155 | nan | -2.350156 | True |
| vanilla/e2-vanilla-50c-01 | public_station_price | 0.1853 | 2900.831228 | 2807.066768 | nan | -3.232331 | True |
| vanilla/e2-vanilla-50c-01 | public_station_price | 0.4 | 2900.831228 | 2815.723230 | nan | -2.933918 | True |
| vanilla/e2-vanilla-50c-01 | public_station_price | 0.82 | 2900.831228 | 2832.657155 | nan | -2.350156 | True |
| vanilla/e2-vanilla-50c-01 | speed_ms | 11.1 | 2826.447015 | 2692.578643 | nan | -4.736277 | True |
| vanilla/e2-vanilla-50c-01 | speed_ms | 16.7 | 2793.698987 | 2681.423044 | nan | -4.018899 | True |
| vanilla/e2-vanilla-50c-01 | speed_ms | 25.0 | 2900.831228 | 2832.657155 | nan | -2.350156 | True |

Phase 2 uses fixed customer-order and vehicle-type references from Phase 1, then replays EV charging under each in-memory price override. It isolates parameter economics without claiming full re-optimization.

## One-Line Root Cause

固定真实碳价下, 本次 09e 选定小算例没有复现'全油车最优': mixed 已经低于本脚本的 cv_only。因此不能把电池/电价/占用费判为全油退化真凶; 下一步应转到 09d 中 LNS 全油车占优的更大实例或引入 LNS 级全油参考解再诊断。

## Artifacts

- `baselines/e2_alns/instance_param_diagnostic.py`
- `baselines/e2_alns/instance_param_diagnostic_data/phase0_audit.json`
- `baselines/e2_alns/instance_param_diagnostic_data/phase1_cost_breakdown.csv`
- `baselines/e2_alns/instance_param_diagnostic_data/phase2_scan.csv`

## Command

```bash
/opt/anaconda3/bin/python3.13 baselines/e2_alns/instance_param_diagnostic.py --eval-budget 80 --max-runtime-seconds 10
```
