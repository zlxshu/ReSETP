# Literature-based algorithm decision for ReSETP ALNS / DR-ALNS (2026-07-07)

This document is a decision memo, not a broad literature survey. It translates the first confirmed literature principles and current source findings into an execution plan.

## 1. Core decision

Primary algorithm rescue should move to E2 route-count compression / stability, while E7 dynamic DR remains gated by full fixed-code Stage3 and proxy-semantics audit.

Reason:
- E2 has a source-confirmed failure mode: local search cannot reduce route count, while documented 100c threeshift exceptions point to route compression.
- Latest `ab3f8dc3` changes improve E7 dynamic lifecycle and guards, but Track24 fixed-code evidence must still be fully rerun, and proxy-dominant selected actions cannot justify PPO or a mechanism claim.

## 2. Literature principles used

1. Learning-enhanced LNS learns legal subproblem selection and delegates to a solver/repair operator. It should not create illegal subproblems or remove customers from the problem.
2. Dynamic VRP with confirmation requires accepted/committed requests to be served while routes continue to be optimized. This requires explicit lifecycle state: unrevealed, active, pending, mandatory, committed, served, cancelled.
3. EVRP charging algorithms integrate station insertion and charging feasibility into neighborhoods; carbon or charging logic is not an E2 rescue unless it improves total objective under fair budget.
4. ALNS/LNS improvements in routing usually come from problem-specific neighborhoods and repair mechanisms. Innovation must come from a verified repair of a source-identified failure.

## 3. Source findings after `ab3f8dc3`

### Dynamic / Track24

Positive:
- `RollingPolicyDecision` now has `plan_now_ids`, `defer_ids`, and `mandatory_ids`.
- `RollingPolicyContext` now exposes `pending_customer_ids`, `mandatory_customer_ids`, and `committed_customer_ids`.
- `_normalize_policy_decision` rejects unknown IDs, committed IDs, plan/defer overlap, and deferred mandatory customers.
- `_classify_defer_eligibility` adds a conservative guard using due time, direct depot feasibility, demand capacity, and pending age.
- Track24 now records proxy semantics and blocks PPO when selected actions are proxy-dominant.

Remaining risk:
- Full fixed-code Track24 Stage3 evidence is still required. Mixed or carried rows cannot be used.
- Defer guard is still coarse; EV/SOC remains explicitly proxy.
- If selected actions are mainly `capacity_reserve_*` or `ev_charging_slack_reserve_*`, report as proxy / state-control evidence only, not real depot-capacity or SOC mechanism.

### E2 main algorithm

Positive:
- `route_elimination_removal` now removes one weak route and sets `allow_new_route_repair=False`, which is a source-level compression move.

Remaining risk:
- The E2 compression probe evidence is not in the remote repository at this review time, so the reported 12/12 probe cannot yet be audited remotely.
- A single route-elimination patch is only a repair hypothesis until documented exceptions improve and 150/200c sanity is not harmed.

### Carbon / charging

Current role:
- Mechanism-side E4/E5 only unless targeted E2 total-objective ablation proves benefit.

### Fairness

Current role:
- High-potential E6 mechanism path once min-ratio and fairness slack are stably exported.

## 4. Execution order

### Step 1 — Audit and reproduce E2 compression evidence

Required before declaring algorithm progress:
- Push/report `solver/reports/e2_route_compression_probe_20260707/**` or regenerate it in a tracked report directory.
- Compare old vs new profile on `e2-threeshift-100c-01`, `e2-threeshift-100c-02`, and at least one 200c sanity instance.
- Required metrics: route count, fixed cost, total cost, EV/CV share, best update count, unique solution count, zero violations, evals/runtime.
- If compression improves 100c exceptions and does not harm 200c sanity, expand to 9 threeshift instances.

### Step 2 — Run full fixed-code Track24 Stage3 gate

Required before any Stage4:
- New report dir.
- 260/260 all fixed-code rerun.
- `mixed_code=false`, `carried=0`, health failures = 0.
- Report selected action distribution and proxy-selected share.

Decision:
- If mean reduction <2pp: stop dynamic DR as main rescue.
- If mean reduction >=2pp but proxy-dominant: no PPO; either implement true mechanism semantics or downgrade to budget/proxy control.
- If mean reduction >=2pp and non-proxy mechanisms dominate: proceed only to imitation/contextual bandit, not PPO.

### Step 3 — If E2 compression passes, make it the main algorithm innovation path

Only after evidence:
- Name the mechanism after the verified failure and fix, e.g. controlled route-compression repair.
- Add ablation: base ALNS, +local search, +route compression, +compression+stability.
- Use it as the E2 algorithm contribution, with dynamic/fairness/carbon as mechanism extensions.

### Step 4 — If E2 compression fails, switch to E6 fairness-safe repair

Prerequisite:
- Export min profit ratio and fairness slack.
- Build fairness-safe repair only after slack fields exist.

### Step 5 — Carbon remains E4/E5 unless proven otherwise

Do not spend main-algorithm cycles on carbon unless E2 total objective improves.

## 5. Stop rules

- Do not train PPO from Track24 unless full fixed-code Stage3 is healthy, mean >=2pp, and selected mechanisms are not proxy-dominant.
- Do not claim E2 innovation from route compression until remote-auditable evidence proves it fixes documented exceptions.
- Do not rename repair hypotheses as innovations before ablation.
- Do not use untracked local evidence for paper claims.
