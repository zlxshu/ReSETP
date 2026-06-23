# 09f Large-Scale All-CV Diagnostic

Conclusion: `ALLCV_ECONOMIC_ON_TRUE_LARGESCALE_CASE`.

True best-and-mean all-CV dominance is present on e2-threeshift-200c-01. Cases with best mixed already present: e2-threeshift-100c-01, e2-threeshift-150c-01.

## Environment

- repo_head: `43d423b7c2fd0a1a4eff85774ba7810bef9409c9`
- diagnostic_artifact_commit: `PENDING_COMMIT`
- branch: `codex/reporting-pipeline`
- python: `/opt/anaconda3/bin/python3.13`
- python_version: `3.13.9`
- numpy: `2.3.5`
- PYTHONHASHSEED: `0`
- carbon_price: `0.05034`
- phase2_mode: `fixed_replay`
- enable_reopt_refine: `False`
- reopt_collection_note: `Attempted --enable-reopt-refine twice in this session. The first default direct run was interrupted after >15 min in local_search/check_solution; the second run used 09d throughput flags and was interrupted after >15 min while still CPU-bound in run_alns_wouda. No reopt rows are claimed; fixed-replay triggers are recorded for a resumable future refine.`
- elapsed_seconds: `0.482`

## Command

```bash
PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 baselines/e2_alns/largescale_allcv_diagnostic.py --phase2-mode fixed_replay --reopt-collection-note 'Attempted --enable-reopt-refine twice in this session. The first default direct run was interrupted after >15 min in local_search/check_solution; the second run used 09d throughput flags and was interrupted after >15 min while still CPU-bound in run_alns_wouda. No reopt rows are claimed; fixed-replay triggers are recorded for a resumable future refine.'
```

Stdout summary:

```json
{
  "classifiers": {
    "e2-threeshift-100c-01": "MIXED_EXISTS_MEAN_ALLCV",
    "e2-threeshift-150c-01": "MIXED_EXISTS_MEAN_ALLCV",
    "e2-threeshift-200c-01": "ALLCV_BEST_AND_MEAN"
  },
  "conclusion": "ALLCV_ECONOMIC_ON_TRUE_LARGESCALE_CASE",
  "output_dir": "baselines/e2_alns/largescale_allcv_diagnostic_data",
  "phase0_only": false,
  "phase2_rows": 78,
  "reference_rows": 30,
  "reopt_rows": 0,
  "reopt_trigger_rows": 4,
  "report": "baselines/e2_alns/largescale_allcv_diagnostic.md",
  "schema_version": "setp-09f-stdout-summary.v1"
}
```

## Phase 0 Reference Audit And Dominance

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

## Phase 1 Cost And Charging Mechanism

| instance | role | seed | total | gap % | CV | EV | fix | km | fuel | elec | occ | carbon | E_cv | E_ev | E_total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-100c-01 | LNS/all-CV | 5 | 4918.752360 | 0.000000 | 29 | 0 | 2320.000000 | 1411.461691 | 1088.953496 | 0.000000 | 0.000000 | 98.337173 | 1953.459931 | 0.000000 | 1953.459931 |
| e2-threeshift-100c-01 | ALNS/mixed | 1 | 4874.971895 | -0.890073 | 10 | 22 | 2560.000000 | 1437.700872 | 544.986850 | 262.518938 | 14.593682 | 55.171555 | 977.645030 | 118.333412 | 1095.978442 |
| e2-threeshift-150c-01 | LNS/all-CV | 2 | 7439.741687 | 0.000000 | 48 | 0 | 3840.000000 | 1954.780872 | 1508.717180 | 0.000000 | 0.000000 | 136.243635 | 2706.468706 | 0.000000 | 2706.468706 |
| e2-threeshift-150c-01 | ALNS/mixed | 2 | 7256.330133 | -2.465295 | 15 | 35 | 4000.000000 | 2005.646065 | 772.493288 | 371.802096 | 29.591174 | 76.797511 | 1385.765959 | 139.810340 | 1525.576299 |
| e2-threeshift-200c-01 | LNS/all-CV | 1 | 8979.132838 | 0.000000 | 62 | 0 | 4960.000000 | 2182.564421 | 1684.454911 | 0.000000 | 0.000000 | 152.113506 | 3021.722401 | 0.000000 | 3021.722401 |
| e2-threeshift-200c-01 | ALNS/mixed | 5 | 9093.841324 | 1.277501 | 13 | 55 | 5440.000000 | 2357.609657 | 671.017212 | 527.840475 | 27.059908 | 70.314072 | 1203.729306 | 193.054007 | 1396.783313 |

Mixed EV charging behavior:

| instance | seed | EV routes | charges | depot kWh | public kWh | depot cost | public cost | occ cost | EV routes public | EV routes >80kWh | avg EV kWh | max EV kWh | max/battery |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-100c-01 | 1 | 22 | 25 | 1287.562329 | 29.187364 | 238.585300 | 23.933638 | 14.593682 | 3 | 3 | 59.852259 | 95.344371 | 1.191805 |
| e2-threeshift-150c-01 | 2 | 35 | 41 | 1744.590236 | 59.182348 | 323.272571 | 48.529525 | 29.591174 | 6 | 6 | 51.536360 | 96.023315 | 1.200291 |
| e2-threeshift-200c-01 | 5 | 55 | 60 | 2609.078394 | 54.119816 | 483.462226 | 44.378249 | 27.059908 | 5 | 5 | 48.421786 | 98.275631 | 1.228445 |

## Phase 2 Fixed-Replay Single-Parameter Scan

| instance | classifier | parameter | value | all-CV | mixed | gap % | mixed <= all-CV | mixed public kWh | mixed occ cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | battery_kwh | 80.0 | 4918.752360 | 4874.971895 | -0.890073 | True | 29.187364 | 14.593682 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | battery_kwh | 160.0 | 4918.752360 | 4840.696600 | -1.586902 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | battery_kwh | 320.0 | 4918.752360 | 4840.696600 | -1.586902 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | battery_kwh | 480.0 | 4918.752360 | 4840.696600 | -1.586902 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | speed_ms | 25.0 | 4918.752360 | 4874.971895 | -0.890073 | True | 29.187364 | 14.593682 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | speed_ms | 16.7 | 4738.235154 | 4667.250346 | -1.498128 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | speed_ms | 11.1 | 4793.415392 | 4657.425793 | -2.837008 | True | 0.000000 | 0.000000 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | public_station_price | 0.82 | 4918.752360 | 4874.971895 | -0.890073 | True | 29.187364 | 14.593682 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | public_station_price | 0.4 | 4918.752360 | 4862.713203 | -1.139296 | True | 29.187364 | 14.593682 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | public_station_price | 0.1853 | 4918.752360 | 4856.446676 | -1.266697 | True | 29.187364 | 14.593682 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | occupancy_fee | 0.5 | 4918.752360 | 4874.971895 | -0.890073 | True | 29.187364 | 14.593682 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | occupancy_fee | 0.1 | 4918.752360 | 4863.296950 | -1.127428 | True | 29.187364 | 2.918736 |
| e2-threeshift-100c-01 | MIXED_EXISTS_MEAN_ALLCV | occupancy_fee | 0.0 | 4918.752360 | 4860.378214 | -1.186767 | True | 29.187364 | 0.000000 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | battery_kwh | 80.0 | 7439.741687 | 7256.330133 | -2.465295 | True | 59.182348 | 29.591174 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | battery_kwh | 160.0 | 7439.741687 | 7185.663403 | -3.415149 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | battery_kwh | 320.0 | 7439.741687 | 7185.663403 | -3.415149 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | battery_kwh | 480.0 | 7439.741687 | 7185.663403 | -3.415149 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | speed_ms | 25.0 | 7439.741687 | 7256.330133 | -2.465295 | True | 59.182348 | 29.591174 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | speed_ms | 16.7 | 7189.737324 | 6943.983760 | -3.418116 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | speed_ms | 11.1 | 7266.158296 | 6932.395325 | -4.593390 | True | 0.000000 | 0.000000 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | public_station_price | 0.82 | 7439.741687 | 7256.330133 | -2.465295 | True | 59.182348 | 29.591174 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | public_station_price | 0.4 | 7439.741687 | 7231.473547 | -2.799400 | True | 59.182348 | 29.591174 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | public_station_price | 0.1853 | 7439.741687 | 7218.767097 | -2.970192 | True | 59.182348 | 29.591174 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | occupancy_fee | 0.5 | 7439.741687 | 7256.330133 | -2.465295 | True | 59.182348 | 29.591174 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | occupancy_fee | 0.1 | 7439.741687 | 7232.657194 | -2.783490 | True | 59.182348 | 5.918235 |
| e2-threeshift-150c-01 | MIXED_EXISTS_MEAN_ALLCV | occupancy_fee | 0.0 | 7439.741687 | 7226.738959 | -2.863039 | True | 59.182348 | 0.000000 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | battery_kwh | 80.0 | 8979.132838 | 9093.841324 | 1.277501 | False | 54.119816 | 27.059908 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | battery_kwh | 160.0 | 8979.132838 | 9024.603119 | 0.506399 | False | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | battery_kwh | 320.0 | 8979.132838 | 9024.603119 | 0.506399 | False | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | battery_kwh | 480.0 | 8979.132838 | 9024.603119 | 0.506399 | False | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | speed_ms | 25.0 | 8979.132838 | 9093.841324 | 1.277501 | False | 54.119816 | 27.059908 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | speed_ms | 16.7 | 8699.996370 | 8745.550642 | 0.523613 | False | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | speed_ms | 11.1 | 8785.322402 | 8704.460431 | -0.920421 | True | 0.000000 | 0.000000 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | public_station_price | 0.82 | 8979.132838 | 9093.841324 | 1.277501 | False | 54.119816 | 27.059908 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | public_station_price | 0.4 | 8979.132838 | 9071.111002 | 1.024355 | False | 54.119816 | 27.059908 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | public_station_price | 0.1853 | 8979.132838 | 9059.491477 | 0.894949 | False | 54.119816 | 27.059908 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | occupancy_fee | 0.5 | 8979.132838 | 9093.841324 | 1.277501 | False | 54.119816 | 27.059908 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | occupancy_fee | 0.1 | 8979.132838 | 9072.193398 | 1.036409 | False | 54.119816 | 5.411982 |
| e2-threeshift-200c-01 | ALLCV_BEST_AND_MEAN | occupancy_fee | 0.0 | 8979.132838 | 9066.781416 | 0.976136 | False | 54.119816 | 0.000000 |

Fixed replay strips public station nodes from EV routes, replays charging under the override, and re-evaluates/checks independently. It isolates economics, but it is not a full re-optimization proof. Re-optimization refinement, when enabled, uses the strongest fixed-replay trigger per parameter lever on true all-CV instances to avoid rerunning duplicate grid points with identical fixed-route economics.

## Phase 2 Re-Optimization Refinement

Reopt trigger candidates:

| instance | parameter | field | value | fixed replay gap % |
| --- | --- | --- | --- | --- |
| e2-threeshift-200c-01 | speed_ms | v_speed_ms | 11.1 | -0.920421 |
| e2-threeshift-200c-01 | battery_kwh | B_battery_kwh | 160.0 | 0.506399 |
| e2-threeshift-200c-01 | public_station_price | station_electricity_price | 0.1853 | 0.894949 |
| e2-threeshift-200c-01 | occupancy_fee | occupancy_fee | 0.0 | 0.976136 |

Status: `HALT_REOPT_COLLECTION_COST`. Attempted --enable-reopt-refine twice in this session. The first default direct run was interrupted after >15 min in local_search/check_solution; the second run used 09d throughput flags and was interrupted after >15 min while still CPU-bound in run_alns_wouda. No reopt rows are claimed; fixed-replay triggers are recorded for a resumable future refine.

## One-Line Root Cause

固定真实碳价下，100/150c 的问题是 mixed 好解存在但搜索均值不稳；e2-threeshift-200c-01 的 all-CV 真实占优可由单参数 `speed_ms=11.1` 在 fixed replay 中翻成 mixed <= all-CV，需要后续重优化确认。

## Artifacts

- `baselines/e2_alns/largescale_allcv_diagnostic.py`
- `baselines/e2_alns/largescale_allcv_diagnostic_data/reference_solution_audit.csv`
- `baselines/e2_alns/largescale_allcv_diagnostic_data/phase0_dominance.csv`
- `baselines/e2_alns/largescale_allcv_diagnostic_data/phase1_cost_breakdown.csv`
- `baselines/e2_alns/largescale_allcv_diagnostic_data/phase2_fixed_replay.csv`
- `baselines/e2_alns/largescale_allcv_diagnostic_data/phase2_reopt_triggers.csv`
- `baselines/e2_alns/largescale_allcv_diagnostic_data/metadata.json`
