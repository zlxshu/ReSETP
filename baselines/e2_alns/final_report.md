# E2 ALNS Stage 2 Report

Conclusion: `HALT_ALNS_NOT_PROMOTED`. The legacy winner anchor is unchanged, but
the E2 strengthened ALNS candidate has not yet passed the LNS robustness gate,
so Stage 3-5 formal T3/F2 should not be launched from this state.

## What Changed

Code changes are limited to `winner_operators.py` and the public API test:

- `run_winner_kernel()` remains the legacy anchor path and still forces
  Prompt-1 add-ons off.
- `run_e2_alns_final()` is a separate E2 wrapper.
- `e2_alns_variant_flags()` exposes the currently promoted candidate:
  `TRUE_REPAIR=1`, `ADAPTIVE_Q=1`, `ROUTE_ELIMINATION=0`,
  `TRUE_ACCEPTANCE=0`, `LOCAL_SEARCH=0`.
- The manifest records all literature component sources so future ablation can
  promote or demote them explicitly.

No model semantics files were modified: `cost.py`, `check.py`, and
`evaluation.py` were not edited.

## Legacy Anchor Guard

Command:

```bash
SETP_ALNS_PARALLEL_WORKERS=4 PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m setp_solver.search.winner_restoration run-current --output-dir baselines/e2_alns/legacy_anchor --seeds 1-10 --eval-budget 16000 --max-runtime-seconds 900
```

Result:

- Gate: `PASS_CURRENT_RUN_CLASSIFIED`
- Mean current total cost: `4878.331796187524`
- Mean gold total cost: `4878.331796187524`
- Mean delta: `0.0`
- Best current total cost: `4779.053444002934`
- Seed 2 current/gold: `4779.053444002934` / `4779.053444002934`
- Zero violations: `10/10`
- Classification: `not_regressed`

This satisfies the user guard: the shared winner wrapper changes did not move
the `100-01` legacy anchor.

## E2 Candidate Status

The short ablation in `ablation.md` found:

- `TRUE_REPAIR + ADAPTIVE_Q` improves `e2-vanilla-100c-01` and
  `e2-multidepot-100c-01` in the 128-eval smoke.
- `LOCAL_SEARCH=1` is too slow and regresses `L-main` in the smoke.
- RRT acceptance regresses `L-main` and is not promoted.
- Route elimination is neutral or negative in this sample and is not promoted.

The candidate remains zero-violation in the completed smoke rows.

## Why This Halts Downstream

The prompt's Stage 2 gate requires the final ALNS to avoid being systematically
beaten by LNS on all-CV-favorable cases. That is not true yet:

- `L-main`, 128 eval: E2 candidate `8828.376422`; LNS spot check
  `8281.354949`.
- `e2-vanilla-100c-01`, 128 eval: E2 candidate `6023.219521`; LNS spot check
  `6120.866053`, so the candidate wins this one, but LNS is close and all-CV.
- Existing evidence says the LNS advantage comes from scan/all-CV construction
  plus LNS repair, not from evaluator drift.

Therefore the honest action is to stop before the formal E2 T3/F2 run. Running
69 instances now would produce a table from an ALNS candidate that has not met
the ALNS stage acceptance gate.

## Downstream Impact

The old E1-E7 formal numbers are not invalidated by this commit because the
legacy `run_winner_kernel()` path is still exact. If `run_e2_alns_final()` or a
future strengthened ALNS is promoted as the primary paper algorithm, the old
`9da7f8b` formal numbers and the `£4878.33` table anchors must be rerun in a
separate formal rerun.

## Recommended Next Step

Do not proceed to Stage 3-5 formal T3 from this state. The next engineering
step should be a focused ALNS-vs-LNS bridge, most likely by implementing a
literature-clean scan/multi-start construction option or a GLNS-style whole
route rebuild as an explicit ALNS component, then repeating this short
ablation and the legacy anchor guard.

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
