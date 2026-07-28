# DR-ALNS Track24-R dynamic legality source diagnosis

Date: 2026-07-06

Update after push: `dynamic.py` on `dr-x86` is now visibly changed in GitHub. It adds `pending_deferred_ids`, carries pending customers into future active sets, routes final remaining customers through a final repair stage, preserves `stage_eval_budget` / `stage_max_runtime_seconds` in `_policy_decision_for_stage`, and replaces commit extraction with `_solution_for_committed_customers` that keeps the route prefix through the last committed customer.

Current user-reported Track24-R2 result: commit-chunk HALT is cleared in failure-only resume, 260/260 rows are written, but the result is `TRACK24R_FAILURE_ONLY_HEALTHY_MIXED_REFERENCE` with `mixed_code=true`, `carried=136`, `rerun=124`, `mean_reduction_pp=12.6924`. This is legality evidence only, not breakthrough evidence; a full fixed-code 260-row rerun is still required before any Stage4 imitation/bandit.

Source-grounded diagnosis from committed dr-x86 code:

1. The fix is materially better than the previous final-pending deletion patch: rolling state now has `pending_deferred_ids`, pending customers re-enter active sets, and final repair runs `_run_stage_plan` on remaining customers instead of extracting them from `previous_plan`.
2. However the dynamic abstraction is still not a full committed-request state machine. `RollingPolicyDecision` still exposes only `active_ids`, `initial_plan`, and budget/runtime; it has no explicit `mandatory_ids`, `defer_ids`, acceptance/confirmation state, or latest-service/deadline metadata. Pending is inferred as `active_ids - stage_active_ids`, not typed as a first-class decision.
3. `_solution_for_committed_customers` now keeps route prefix through the last committed customer, avoiding the old depot-customer-depot replay bug. But it still materializes a synthetic route ending at the depot and filters non-committed intermediate customers. This is a pragmatic legality patch, not a full executed-segment cost/schedule ledger.
4. The correct next step is not Stage4/PPO. It is a full fixed-code Stage3 confirmation plus a parallel source-level state-machine audit. If full fixed-code mean reduction remains >=2pp and all rows are healthy, only then may imitation/contextual bandit be planned; PPO remains later.
5. If fixed-code signal disappears or is mostly budget allocation, stop dynamic-DR as the main rescue path and move to E2 route-compression/stability or E6 fairness-safe repair.

Next execution package should run in parallel:
- A) full fixed-code 260-row Stage3 confirmation (`mixed_code=false`, no carried rows), with action-class distribution and selected action distribution;
- B) source audit of dynamic customer lifecycle: unrevealed/revealed/pending/mandatory/committed/served/cancelled;
- C) typed decision extension proposal: `mandatory_ids`, `defer_ids`, `plan_now_ids`, deadline/feasibility guards;
- D) cheap feasibility guard for defer actions: due-time reachability, direct depot feasibility, EV/charging proxy;
- E) only after A-D pass, plan Stage4 imitation/bandit, not PPO.

Hard rules:
- Do not run Stage4/PPO from mixed-code evidence.
- Do not declare Track24 breakthrough from carried/rerun mixed references.
- Do not change `cost.py`, `check.py`, or `evaluation.py` semantics.
- Resume/full rerun evidence must write metadata/raw rows/decision/report/hash and worker integrity.
