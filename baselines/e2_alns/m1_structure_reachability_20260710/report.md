# M1 structure reachability diagnostic

Verdict: `ALNS_SCHEDULER_OR_MULTI_STEP_BARRIER`.

This is a one-step mechanism test, not an algorithm ranking and not a formal T3 result. It keeps the shared evaluator and checker unchanged and uses the same frozen starts for ALNS and SA.

Instance: `L-main-threeshift-25c-01`; actual customers: `55`; battery: `280.0` kWh.

## Start states

- CV_ONLY: cost 1730.390718, routes 8, EV routes 0, charging actions 0.
- SHARED_ONE_EV: cost 1811.837477, routes 9, EV routes 1, charging actions 1.

## One-step summary

- ALNS / CURRENT_T3_LOCAL_SEARCH / CV_ONLY: 48 structural candidates, 32 immediately improving, 0 route drops, 48 EV changes.
- ALNS / CURRENT_T3_LOCAL_SEARCH / SHARED_ONE_EV: 21 structural candidates, 21 immediately improving, 6 route drops, 20 EV changes.
- ALNS / CURRENT_THROUGHPUT / CV_ONLY: 42 structural candidates, 28 immediately improving, 0 route drops, 42 EV changes.
- ALNS / CURRENT_THROUGHPUT / SHARED_ONE_EV: 24 structural candidates, 24 immediately improving, 9 route drops, 20 EV changes.
- ALNS / LEAN_PUBLIC / CV_ONLY: 48 structural candidates, 29 immediately improving, 0 route drops, 48 EV changes.
- ALNS / LEAN_PUBLIC / SHARED_ONE_EV: 22 structural candidates, 22 immediately improving, 7 route drops, 19 EV changes.
- ALNS / ROUTE_ELIMINATION_DIAGNOSTIC / CV_ONLY: 57 structural candidates, 30 immediately improving, 0 route drops, 57 EV changes.
- ALNS / ROUTE_ELIMINATION_DIAGNOSTIC / SHARED_ONE_EV: 31 structural candidates, 31 immediately improving, 16 route drops, 28 EV changes.
- SA / DIRECT_PATH_OPERATORS / CV_ONLY: 0 structural candidates, 0 immediately improving, 0 route drops, 0 EV changes.
- SA / DIRECT_PATH_OPERATORS / SHARED_ONE_EV: 4 structural candidates, 3 immediately improving, 0 route drops, 4 EV changes.

## Boundary

A missing one-step change is strong evidence that the present move set cannot directly cross that boundary. It does not prove that a long sequence can never reach it. An improving one-step change only proves that the move exists; it does not prove the scheduler will choose it often enough in a full run.
