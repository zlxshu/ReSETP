# Source-literature audit findings (2026-07-06)

This file records concrete findings from direct source inspection plus first-tranche high-value literature mapping. It is not a claim that 300 papers or every repository line have already been read. It is a checkpoint of actionable findings.

## 1. Immediate source findings

### F1. E7 dynamic control still uses legacy active-set subtraction

Files read:
- `solver/src/setp_solver/search/dynamic.py`
- `solver/rl/dr_alns_ppo/track24_breakthrough_audit.py`

Evidence:
- `RollingPolicyDecision` still exposes `active_ids` as the main customer-control surface; it has no first-class `plan_now_ids`, `defer_ids`, or `mandatory_ids`.
- Track24 policy computes `deferred`, then returns `RollingPolicyDecision(active_ids=context.active_ids - deferred)`.
- `capacity_reserve_*` and `ev_charging_slack_reserve_*` are explicitly marked as proxy semantics in `build_stage3_action_specs`.

Implication:
- Fixed-code Stage3 being healthy is necessary but not enough. If selected rows are dominated by proxy semantics, no mechanism claim or PPO should follow.

Required correction:
- Promote dynamic decision semantics from legacy active-set subtraction to explicit lifecycle control: `plan_now_ids`, `defer_ids`, `mandatory_ids`, `pending_customer_ids`, `committed_customer_ids`.

### F2. E2 main profile cannot solve documented route-count exceptions by local search alone

Files read:
- `solver/src/setp_solver/search/local_search.py`
- `solver/src/setp_solver/search/feasible_repair.py`
- `solver/src/setp_solver/search/alns_wouda.py`

Evidence:
- `local_search.py` only enumerates 2-opt, Or-opt, and single-customer relocate. It has no route merge, route-count compression, or route-elimination local search.
- Relocate source route requires at least two customers, so it will not clear single-customer routes.
- `feasible_repair.py` limits candidate breadth: `MAX_ROUTE_CANDIDATES=4`, `MAX_POSITIONS_PER_ROUTE=2`, `MAX_EXISTING_EV_ROUTE_CANDIDATES=1`.
- `repair_removed_customers` defaults to `allow_new_route=True`, and `_new_route_options` opens new CV/EV routes.

Implication:
- E2 documented exceptions where LOCAL_SEARCH is worse than LNS and route compression is suspected are source-consistent. The next real main-algorithm repair path is a compression-mode repair or route-count-sensitive search phase, not carbon or PPO.

Required correction:
- Build a minimal compression probe on `e2-threeshift-100c-01/02` and one 200c sanity instance: route-elimination/removal with `allow_new_route=False` first, fallback allowed only after compression fails, and full feasibility check.

### F3. Carbon/charging is currently mechanism-side, not E2 rescue

Files read:
- `solver/src/setp_solver/search/charging.py`
- `solver/src/setp_solver/cost.py`

Evidence:
- `evaluate()` correctly includes CV direct emissions, EV indirect emissions from charging slots, total emissions, and carbon trading cost.
- `charging.py` selects low-gamma charging starts for aware charging and station insertion.
- Existing Stage6 evidence is scenario-only / weak for E2: timing delta is tiny even when carbon cost share is high.

Implication:
- Carbon-aware repair should not be the immediate E2 main-algorithm rescue unless a small E2 total-objective ablation proves it helps.

Required correction:
- Keep carbon as E4/E5 mechanism unless E2 total objective improves in a targeted small ablation.

## 2. Literature-to-source mapping, first tranche

| Literature pattern | Source implication | ReSETP action |
|---|---|---|
| Learning-enhanced LNS learns legal subproblem selection, then delegates to repair/subsolver. | DR should select legal subproblems/repair targets, not delete customers from `active_ids`. | Replace active-set subtraction with typed lifecycle decisions. |
| Neural LNS integrates learned heuristics inside an LNS repair framework. | Learning must operate inside feasible destroy/repair semantics. | Use imitation/bandit only after legal oracle headroom. |
| Dynamic VRP with prompt confirmation requires accepted requests to be served while routes continue optimizing. | E7 needs committed/mandatory request state, not only served/pending. | Add `mandatory_ids`, `committed_customer_ids`, defer guards. |
| Dynamic/stochastic VRP uses remaining service capacity / reward-to-go logic. | Defer actions require forward feasibility guards. | Add due-time/direct-depot/capacity/EV proxy guard before defer. |
| EVRP nonlinear/partial charging algorithms couple routing and charging decisions. | Carbon/charging action must be judged by total cost and feasibility, not only gamma. | Keep carbon/charging as mechanism until E2 objective gain is proven. |
| Route decomposition / LNS for large VRP improves by selecting routes/subproblems. | E2 exceptions should be attacked through route compression and subproblem repair. | Build compression-mode repair probe. |

## 3. Immediate execution priority

1. E2 compression probe from source-confirmed weakness.
2. DYN full fixed-code confirmation plus explicit lifecycle patch.
3. HEALTH repo-wide evidence hygiene.
4. Carbon only as small E2 relevance audit and E4/E5 mechanism.

## 4. Stop rules

- No Stage4/PPO unless full fixed-code Stage3 is all healthy, not mixed-code, and mean reduction >=2pp.
- No dynamic mechanism claim if selected actions are proxy-dominant.
- No E2 innovation claim until a repair path fixes a source-identified failure and survives ablation.
- No paper evidence from mixed-code, under-eval, health-HALT, or x86/M1 absolute-value mixing.
