# E2 ALNS Short Ablation

Status: `HALT_ALNS_NOT_PROMOTED`

This file records the Stage 2 short ablation used to decide whether a
literature-component ALNS variant can be promoted into the E2 formal protocol.
It is intentionally small and conservative: the goal was to find obvious
regressions before launching the expensive 69-instance protocol.

Environment:

- Base commit before this stage: `b1ffa756`
- Working tree included the new `run_e2_alns_final()` wrapper during the smoke
  rows below.
- Python: `/opt/anaconda3/bin/python3.13`
- NumPy: `2.3.5`
- `PYTHONHASHSEED=0`
- Probe budget: `128` evals, `60s` cap per run, seed `1`

## Variants

| variant | true repair | route elimination | RRT acceptance | local search | adaptive q |
|---|---:|---:|---:|---:|---:|
| legacy | 0 | 0 | 0 | 0 | 0 |
| route_elim_only | 0 | 1 | 0 | 0 | 0 |
| all_flags | 1 | 1 | 1 | 1 | 1 |
| true_repair | 1 | 0 | 0 | 0 | 0 |
| repair_adaptive_q | 1 | 0 | 0 | 0 | 1 |
| repair_q_rrt | 1 | 0 | 1 | 0 | 1 |
| route_repair_q | 1 | 1 | 0 | 0 | 1 |
| route_repair_q_rrt | 1 | 1 | 1 | 0 | 1 |

`run_e2_alns_final()` was narrowed after this ablation to
`TRUE_REPAIR=1`, `ADAPTIVE_Q=1`, and the other three component flags off.

## Results

| instance | variant | cost | evals | seconds | routes | CV | EV | violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| L-main | legacy | 8828.376422 | 128 | 6.285 | 65 | 13 | 52 | 0 |
| L-main | route_elim_only | 8828.376422 | 128 | 4.374 | 65 | 13 | 52 | 0 |
| L-main | all_flags | 9666.358832 | 128 | 55.272 | 65 | 64 | 1 | 0 |
| L-main | true_repair | 9282.393717 | 128 | 4.346 | 65 | 44 | 21 | 0 |
| L-main | repair_adaptive_q | 8828.376422 | 128 | 15.839 | 65 | 13 | 52 | 0 |
| L-main | repair_q_rrt | 9666.358832 | 128 | 14.809 | 65 | 64 | 1 | 0 |
| L-main | route_repair_q | 8828.376422 | 128 | 15.791 | 65 | 13 | 52 | 0 |
| L-main | route_repair_q_rrt | 9666.358832 | 128 | 14.845 | 65 | 64 | 1 | 0 |
| L-main | LNS spot check | 8281.354949 | 128 | 13.067 | 67 | 67 | 0 | 0 |
| e2-vanilla-100c-01 | legacy | 7063.684065 | 128 | 1.121 | 32 | 31 | 1 | 0 |
| e2-vanilla-100c-01 | route_elim_only | 7063.684065 | 128 | 1.107 | 32 | 31 | 1 | 0 |
| e2-vanilla-100c-01 | all_flags | 6253.483468 | 128 | 22.185 | 35 | 27 | 8 | 0 |
| e2-vanilla-100c-01 | true_repair | 6889.121992 | 128 | 0.786 | 33 | 29 | 4 | 0 |
| e2-vanilla-100c-01 | repair_adaptive_q | 6023.219521 | 128 | 15.446 | 34 | 28 | 6 | 0 |
| e2-vanilla-100c-01 | repair_q_rrt | 6117.740191 | 128 | 15.719 | 34 | 31 | 3 | 0 |
| e2-vanilla-100c-01 | route_repair_q | 6023.219521 | 128 | 15.347 | 34 | 28 | 6 | 0 |
| e2-vanilla-100c-01 | route_repair_q_rrt | 6117.740191 | 128 | 15.746 | 34 | 31 | 3 | 0 |
| e2-vanilla-100c-01 | LNS spot check | 6120.866053 | 128 | 3.942 | 34 | 34 | 0 | 0 |
| e2-multidepot-100c-01 | legacy | 5348.647179 | 128 | 3.422 | 34 | 34 | 0 | 0 |
| e2-multidepot-100c-01 | route_elim_only | 5348.647179 | 128 | 3.456 | 34 | 34 | 0 | 0 |
| e2-multidepot-100c-01 | all_flags | 5270.587168 | 128 | 25.031 | 36 | 17 | 19 | 0 |
| e2-multidepot-100c-01 | true_repair | 5314.448235 | 128 | 5.815 | 34 | 27 | 7 | 0 |
| e2-multidepot-100c-01 | repair_adaptive_q | 5295.543324 | 128 | 17.017 | 35 | 20 | 15 | 0 |
| e2-multidepot-100c-01 | repair_q_rrt | 5251.419869 | 128 | 17.727 | 36 | 17 | 19 | 0 |
| e2-multidepot-100c-01 | route_repair_q | 5295.543324 | 128 | 17.061 | 35 | 20 | 15 | 0 |
| e2-multidepot-100c-01 | route_repair_q_rrt | 5251.419869 | 128 | 20.254 | 36 | 17 | 19 | 0 |
| e2-threeshift-150c-01 | legacy | 9096.401203 | 128 | 1.615 | 50 | 29 | 21 | 0 |
| e2-threeshift-150c-01 | route_elim_only | 9320.028926 | 128 | 2.621 | 50 | 30 | 20 | 0 |
| e2-threeshift-150c-01 | all_flags | interrupted | - | >240 | - | - | - | - |

## Interpretation

The all-flags literature bundle is not safe. It regresses `L-main` to the warm
start and made the three-shift 150c probe spend too long inside local-search
full feasibility checks before it was interrupted. `LOCAL_SEARCH=1` is therefore
kept off for the current E2 wrapper.

RRT acceptance is also not safe in this smoke. It improves
`e2-multidepot-100c-01`, but regresses `L-main` and is worse than
`repair_adaptive_q` on `e2-vanilla-100c-01`. It remains an explicit component,
not a promoted default.

Route elimination did not show independent benefit in this sample. It was
neutral on two 100c cases and worse on the three-shift 150c spot check, so it is
kept off in `run_e2_alns_final()` pending larger evidence.

The only promoted candidate from this short ablation is
`TRUE_REPAIR=1 + ADAPTIVE_Q=1`. It improves the two E2 100c probes against the
legacy winner while staying zero-violation, but it still does not solve
`L-main`.

## Gate

The Stage 2 acceptance gate is not met. LNS still beats the ALNS candidate in
the `L-main` spot check, and the LNS all-CV scan construction is materially
different from the current winner/E2 ALNS warm-start path. Formal E2 T3/F2
should not proceed until this ALNS-vs-LNS gap is either fixed or explicitly
accepted as a limitation by the user.

## 09b Scan Bridge Gate

- Gate: `HALT_SCAN_BRIDGE_BEATEN`
- Reason: LNS is significantly better or ALNS is worse by more than 2% in at least two threeshift groups.
- Commit: `bd57906df953945138c794185941200d3fc5a17b`
- Python: `/opt/anaconda3/bin/python3.13`; NumPy `2.3.5`
- Seeds: [1, 2, 3]; eval budget is a diagnostic backstop `16000`

| instance | algorithm | n | mean | best | std | mean seconds | mean evals | routes | CV | EV | zero violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| e2-multidepot-100c-01 | LNS | 3 | 4984.471933 | 4979.829535 | 7.223051 | 300.018 | 10848.3 | 32.00 | 32.00 | 0.00 | 3 |
| e2-multidepot-100c-01 | alns_scan_bridge | 3 | 4999.970300 | 4959.858338 | 58.560800 | 291.675 | 9592.7 | 34.00 | 10.33 | 23.67 | 3 |
| e2-threeshift-100c-01 | LNS | 3 | 4948.249724 | 4941.366750 | 8.933125 | 300.020 | 10667.7 | 29.33 | 29.33 | 0.00 | 3 |
| e2-threeshift-100c-01 | alns_scan_bridge | 3 | 4933.037208 | 4788.120316 | 209.005341 | 273.862 | 6985.0 | 31.33 | 11.33 | 20.00 | 3 |
| e2-threeshift-150c-01 | LNS | 3 | 7454.530436 | 7439.741687 | 13.009736 | 877.577 | 16000.0 | 48.00 | 48.00 | 0.00 | 3 |
| e2-threeshift-150c-01 | alns_scan_bridge | 3 | 7589.674709 | 7393.172205 | 171.618095 | 587.500 | 14115.7 | 52.00 | 14.67 | 37.33 | 3 |
| e2-threeshift-200c-01 | LNS | 3 | 8991.315571 | 8967.188137 | 29.262367 | 900.035 | 10270.7 | 62.33 | 62.33 | 0.00 | 3 |
| e2-threeshift-200c-01 | alns_scan_bridge | 3 | 10100.635716 | 9416.507124 | 604.321757 | 587.013 | 16000.0 | 64.67 | 25.00 | 39.67 | 3 |
| e2-threeshift-75c-01 | LNS | 3 | 3609.106375 | 3583.386585 | 26.929743 | 287.437 | 16000.0 | 23.67 | 23.67 | 0.00 | 3 |
| e2-threeshift-75c-01 | alns_scan_bridge | 3 | 3665.900339 | 3482.093633 | 171.996445 | 148.713 | 16000.0 | 25.00 | 7.33 | 17.67 | 3 |
| e2-vanilla-100c-01 | LNS | 3 | 5691.460232 | 5680.378556 | 10.924290 | 300.022 | 10096.7 | 31.00 | 31.00 | 0.00 | 3 |
| e2-vanilla-100c-01 | alns_scan_bridge | 3 | 5806.853323 | 5672.729844 | 116.198192 | 286.013 | 11187.3 | 33.00 | 20.00 | 13.00 | 3 |

- Overall threeshift gap ALNS-LNS: `5.143525%`
- Group gaps: `{"e2-threeshift-100c-01": -0.30743227323648614, "e2-threeshift-150c-01": 1.8129146293467506, "e2-threeshift-200c-01": 12.337684468945282, "e2-threeshift-75c-01": 1.573629540496925}`
- Paired wins/ties ALNS: `4/12`
- Wilcoxon p, LNS better: `0.021240234375`

## 09b Legacy Anchor Guard

- Gate: `PASS_CURRENT_RUN_CLASSIFIED`
- Command output directory: `baselines/e2_alns/scan_bridge_legacy_anchor`
- Mean current/gold total cost: `4878.331796187524` / `4878.331796187524`
- Seed 2 current/gold: `4779.053444002934` / `4779.053444002934`
- Mean delta: `0.0`
- Zero violations: `10/10`
- Static recipe audit: `PASS_STATIC_RECIPE_AUDIT`

Conclusion: the scan-bridge code did not move the legacy `run_winner_kernel()`
anchor. Stage 3-5 still remain stopped because the 09b scan bridge gate was
beaten by LNS on the E2 threeshift subset.
