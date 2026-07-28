# DR-ALNS literature-grounded corrective plan (2026-07-06)

Purpose: correct the Track24/Track24-R direction using source logic plus high-value literature patterns. This is not a victory claim and not a PPO instruction.

## 1. Literature lessons to import

### L1. Dynamic VRP needs accepted/committed request semantics
Recent dynamic VRP with prompt confirmation literature stresses that a practical dynamic routing system must both confirm accepted requests and continue optimizing without losing service guarantees. For ReSETP this means E7 cannot express defer/reserve by merely removing customers from `active_ids`; it needs an explicit customer lifecycle.

Required lifecycle:
`unrevealed -> revealed -> pending/deferred -> mandatory/committed -> served/cancelled`.

### L2. Learning-enhanced LNS learns legal subproblem selection, then delegates to repair/subsolver
Neural LNS and Learning-to-Delegate do not let the learning policy create illegal partial problems. The learned component chooses a subproblem / destroy region / repair target, then the solver repairs it. For ReSETP this means DR should choose legal action classes such as budget allocation, mandatory cluster, route segment/subproblem, fairness-safe repair target, or charging-timing candidate; it should not be allowed to make a customer disappear.

### L3. Dynamic stochastic VRP uses reward-to-go / capacity-to-serve proxies
Large-scale dynamic VRP with stochastic requests approximates reward-to-go using remaining service capacity. For ReSETP this suggests replacing ad-hoc defer proxies with explicit feasibility guards: remaining time slack, direct-depot reachability, route/SOC/charging slack, and depot/fleet capacity proxy.

### L4. DR-ALNS value is online control of ALNS parameters/operators, but only after legal oracle headroom exists
DR-ALNS literature supports learning operator/parameter/acceptance control, but Track23/24 show old operator/meta PPO is closed. ReSETP should only train after a fixed-code oracle produces healthy >=2pp information-cost reduction.

## 2. Source diagnosis to act on

Current `dynamic.py` on `dr-x86` has improved legality:
- `pending_deferred_ids` exists.
- pending customers re-enter future active sets.
- final repair runs `_run_stage_plan` on remaining customers.
- `_policy_decision_for_stage` preserves budget/runtime.
- `_solution_for_committed_customers` preserves route prefix through last committed customer.

Remaining abstraction gap:
- `RollingPolicyDecision` still has only `active_ids` as the main customer-control surface.
- There is no first-class `mandatory_ids`, `defer_ids`, `plan_now_ids`, confirmation state, or latest-service guard.
- Current Track24 actions are partly proxies: `depot_capacity_reserve` is not real depot-capacity control; `ev_charging_slack_reserve` is not real SOC/charging slack.

## 3. Next execution package

Run these branches in parallel, not sequentially:

### Branch A: full fixed-code Stage3 confirmation
- Rerun all 260 Stage3 rows under one fixed code version.
- No carried rows, no mixed-code reference.
- Required fields: `mixed_code=false`, `carried=0`, `rerun=260`, health fail = 0.
- Report action-class distribution and selected-action distribution.
- If mean reduction <2pp, stop dynamic DR and do not run Stage4.

### Branch B: dynamic state-machine source audit and minimal patch
- Build explicit lifecycle fields: unrevealed/revealed/pending/mandatory/committed/served/cancelled.
- Extend decision semantics if needed: `mandatory_ids`, `defer_ids`, `plan_now_ids`.
- Ensure pending customers have deadlines and cannot be repeatedly deferred into infeasibility.

### Branch C: feasibility guard for defer/reserve actions
- Before defer, check due-time reachability, direct depot feasibility, demand/capacity slack, and EV/charging proxy.
- If a customer cannot be safely deferred, it must be mandatory for this stage.

### Branch D: source-accurate action naming
- Rename or reimplement proxy actions.
- If an action uses due-time slack, call it slack/defer proxy.
- Only call it depot capacity / EV charging slack if the code actually uses depot capacity or SOC/charging slack.

## 4. Stage4 gate

Stage4 imitation/bandit is allowed only if all are true:
- full fixed-code Stage3 health = 100%;
- mean information-cost reduction >=2pp;
- selected action classes are legal and interpretable;
- no customer is lost, duplicated, or repeatedly deferred past feasibility.

PPO is still not allowed at this gate. Use imitation/contextual bandit first.

## 5. If dynamic line fails

If fixed-code Stage3 is flat or still unstable, stop E7 dynamic DR as the immediate rescue path and switch to:
1. E2 route-compression / stability controller from documented exceptions;
2. E6 fairness-safe repair once fairness slack fields are exposed;
3. E4/E5 carbon/charging only as scenario/mechanism material, not E2 main algorithm.

Hard rules:
- Do not use mixed-code evidence for breakthrough claims.
- Do not train PPO before legal oracle headroom.
- Do not modify `cost.py`, `check.py`, or `evaluation.py` semantics.
- Do not call proxy actions innovation until source code and ablation prove the mechanism.
