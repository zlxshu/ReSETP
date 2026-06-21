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

