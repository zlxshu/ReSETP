# DR-ALNS Track24-R dynamic legality source diagnosis

Date: 2026-07-06

Context: Track24-R reportedly fixed the final pending/final-repair deletion bug in unit tests, but the failure-only Stage3 rerun is still blocked by one `HALT_E7_COMMIT_CHUNK_CHECK` row: `E-UK50_01__curric_d2_s3_seed1_24h`, seed `907`, action `stage_budget_event_density`, first violation `TIME_WINDOW` for `C32`, late by `228.326s`.

Source-grounded diagnosis from committed dr-x86 code:

1. Track24 Stage3 policies are not training-ready while any rolling legality gate fails. `track24_decision.json` status is `TRACK24_HALT_DYNAMIC_ORACLE_HEALTH`; Stage4 imitation is skipped until Stage3 oracle is healthy and >=2pp.
2. `dynamic.py` commits executed customers before each new rolling stage by extracting a chunk from the previous plan and checking it against a subinstance. Any chunk violation returns `HALT_E7_COMMIT_CHUNK_CHECK` before the next stage plan is accepted.
3. A remaining commit-chunk `TIME_WINDOW` violation means the final pending deletion issue is not the only problem. The likely source class is replay/extraction semantics: committed chunks are rebuilt as depot-customer-depot routes in `_solution_for_customer_subset`, then re-scheduled and checked in isolation. This may alter timing versus the original route segment that actually served the customer, especially for customers whose planned service depended on predecessor sequence, waiting, charging, or route start timing.
4. Fix direction: do not mask the health gate. Build a red test reproducing seed907/stage_budget_event_density C32; inspect the original previous-plan route schedule and extracted commit chunk schedule. If extraction changes service timing, commit chunk must preserve executed route prefix/segment timing or use a dynamic-specific committed-segment checker instead of rebuilding an artificial depot-customer-depot route.
5. Parallel investigation branches allowed: A) schedule-preserving commit extraction, B) dynamic commit checker that validates frozen executed segments against original route schedule, C) event-window/frozen-node audit for C32, D) budget-policy interaction audit for `stage_budget_event_density`. Stop only if all branches show no source-level defect.

Hard rules:
- Do not run Stage4/PPO until Stage3 health is all clear.
- Do not change `cost.py`, `check.py`, or `evaluation.py` semantics.
- Do not declare Track24 breakthrough from the healthy subset while any commit/final chunk HALT remains.
- Resume only failed Stage3 rows after the fix, then recompute oracle headroom.
