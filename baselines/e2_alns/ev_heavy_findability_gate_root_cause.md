# 09z Root Cause: EV Path Was Killed by Fleet Policy Drift

## Verdict

The previous `HALT_SEARCH_CANNOT_USE_EV_PATH` result was real for the code as run, but it was not an algorithmic dead end. It was caused by a search-shell bug: the winner-kernel loop did not pass the instance CV/EV fleet caps into `SearchPolicy`, so EV-swap candidates were normalized with an unbounded fleet while `check_solution` still enforced the instance hard caps.

Plain English: the search generated useful EV moves, but then mislabelled the remaining CV trips as too many physical CV vehicles. The checker rejected those candidates before acceptance could use them.

## Evidence

Pre-fix 09z gate:

- `14/14` search rows returned the neutral initial signature.
- `vehicle_type_swap` was called hundreds to thousands of times in ALNS rows, but all outcomes were in the rejected bucket.
- `ev-swap-audit` found `14/21` individually feasible and non-worse CV to EV conversions, with cost deltas from about `-23.32` to `-70.50`.

Minimal root-cause reproduction before the fix:

- Direct `vehicle_type_swap_destroy` on `e2-threeshift-150c-01`, B=280, returned `changed=False` for tested seeds.
- `_try_cv_to_ev_candidates` did generate changed EV candidates, but `check_solution` rejected them with:
  `FLEET_SIZE: CV physical vehicles 20 exceed available fuel vehicles 10`.
- The instance caps are `num_cv=10`, `num_ev=10`.
- `alns_wouda.run_alns_wouda` already used inferred fleet limits, but `winner_operators._run_winner_kernel_loop` used `SearchPolicy(require_charging_signal=...)` without `max_cv/max_ev`.

Minimal root-cause reproduction after the fix:

- The same direct `vehicle_type_swap` tests produced feasible changed candidates for tested seeds.
- Candidate cost deltas were negative, about `-47` to `-70`, and `check_solution` returned zero violations.

Short post-fix gate:

- Runner: `neutral-search-gate`, `e2-threeshift-150c-01`, B=280, algorithms `alns_e2_throughput` and `alns_e2_carbon_ablation`, seeds `1-2`, `3000` eval budget, `180s`.
- Verdict: `PASS_ALNS_FIND_SIGNAL`.
- `4/4` ALNS rows moved away from the initial solution.
- Best costs: `3639.825274`, `3701.578910`, `3364.771719`, `3364.829838`.
- EV share gains: about `77pp` to `81pp`.
- First improvement appeared at eval `3`.

## What Was Fixed

The winner-kernel search shell now builds its default `SearchPolicy` from `instance.num_cv` and `instance.num_ev`. This aligns candidate normalization with the same fleet caps later enforced by `check_solution`.

Protected model semantics were not changed: `cost.py`, `check.py`, `evaluation.py`, and `prices.py` remain untouched.

## What This Proves

It is now safe to say:

- The old 09z no-movement result was caused by a fleet-policy implementation bug in the search shell.
- The existing ALNS search can find EV-heavy solutions from a neutral start once that bug is fixed.
- The original EV-maximal reference solution at cost `5411.442347477969` was not a ceiling for the search; repaired ALNS found much lower checked-feasible solutions on this probe.

It is not yet safe to say:

- ALNS formally beats GA/PSO/LNS/VNS.
- The `3364` to `3702` costs are paper-ready formal results.
- The result generalizes to the full Stage A instance set.

## Next Gate

Do not go straight to an 8-instance campaign. First rerun single-instance Phase 1 with all algorithms from neutral start after this fix, including GA/PSO/LNS/VNS, with the same reporting fields. If ALNS remains the only family with strong find signal, then move to the planned longer single-instance Phase 2.
