# ReSETP repo-wide source audit protocol (2026-07-06)

Purpose: stop local patch loops. The next engineering push must combine source audit, defect fixing, and targeted validation in parallel. This protocol is for Codex/agents working on `dr-x86` and M1 integration.

## 0. Hard answer to user questions

- Is only rerunning fixed-code Stage3 fast enough? No. It is necessary but not sufficient.
- Is only fixing the current `HALT_E7_*` strong enough? No. It fixes a symptom, not the full source risk surface.
- Is the root cause fully determined? Partly. Track24-R/R2 proved two real dynamic legality defects: pending customers could be dropped, and committed chunks could be replayed with changed route context. But the broader root cause is incomplete rolling-state semantics: active/pending/mandatory/committed/served/cancelled are not first-class throughout the dynamic runner.
- Can this solve the problem? It can solve the legality blocker. It does not by itself guarantee DR-ALNS breakthrough; full fixed-code oracle evidence is still required.

## 1. Execution mode

Do not run a long test-only job and stop. Every task must include:

1. source inspection;
2. invariant statement;
3. red/targeted test if missing;
4. code fix if source defect is found;
5. targeted validation;
6. decision: continue, switch route, or halt.

Parallelize independent branches. Do not serialize everything behind one 260-row run.

## 2. Repo-wide audit slices

### Slice A — Dynamic E7 state machine

Files:
- `solver/src/setp_solver/search/dynamic.py`
- `solver/rl/dr_alns_ppo/track24_breakthrough_audit.py`
- `solver/rl/tests/test_track24_breakthrough_audit.py`
- `solver/tests/test_formal_runner.py`

Invariants:
- Every non-cancelled customer is always in exactly one lifecycle state: unrevealed / revealed_unserved / pending_deferred / mandatory_this_stage / committed_locked / served.
- A policy may not make a customer disappear by removing it from `active_ids` without pending or mandatory accounting.
- Committed segments must preserve planned route context and cannot be revalidated under a different artificial schedule.
- Final repair must serve all legal remaining customers or halt with explicit reason.
- Budget/runtime changes must survive through `RollingPolicyDecision` coercion.

Immediate actions:
- Full fixed-code Stage3 confirmation is required, but run in parallel with lifecycle source audit.
- If fixed-code mean reduction <2pp or selected action is only budget allocation, stop dynamic DR as main rescue.

### Slice B — E2 main algorithm strength and innovation

Files:
- `solver/src/setp_solver/search/winner_operators.py`
- `solver/src/setp_solver/search/alns_wouda.py`
- `solver/src/setp_solver/search/candidates.py`
- `solver/src/setp_solver/search/local_search.py`
- `solver/src/setp_solver/search/metaheuristic_baselines.py`
- `baselines/e2_alns/e2_final_closure_20260703/**`

Invariants:
- E2 main algorithm cannot be a thin open-source ALNS wrapper.
- Any claimed innovation must come from a source-identified failure and a verified repair path.
- Documented exceptions must drive the next algorithm change: 100c threeshift cases suggest route-count / route-compression weakness, not carbon first.
- Baseline health must distinguish invalid-not-run, valid-but-weak, natural convergence, and artificial homogenization.

Immediate actions:
- Audit `e2-threeshift-100c-01/02` ALNS vs LNS route counts, fixed cost, best trajectories, route diversity, and route compression opportunity.
- Do not invent a named operator until a minimal route-compression or stability fix improves these exceptions without hurting 150/200c.

### Slice C — Carbon / charging mechanism

Files:
- `solver/src/setp_solver/search/charging.py`
- `solver/src/setp_solver/cost.py` (read-only semantics)
- `solver/src/setp_solver/check.py` (read-only semantics)
- `solver/reports/dr_alns_ppo_v3/final_track23/stage_b_carbon_scenario_knobs*`
- E2 Phase E carbon artifacts on M1 branch

Invariants:
- Carbon-aware logic may enter E2 only if it improves or at least does not harm total E2 objective under fair budget.
- If carbon only changes timing/emissions under scenario knobs, it belongs in E4/E5 mechanism, not E2 main algorithm.
- Station insertion sorting must be checked: if it prioritizes gamma before total-cost delta, it may be mechanism-correct but E2-cost harmful.

Immediate actions:
- Keep carbon as secondary until main E2 weakness is resolved.
- Run only small leverage/ablation checks unless E2 total objective benefit appears.

### Slice D — Fairness E6

Files:
- `solver/src/setp_solver/search/fairness.py`
- fairness reports and E6 runners

Invariants:
- `Pi_d0`, `Pi_d`, min ratio, fairness slack, and violations must be exported stably before fairness-safe repair or DR fairness head.
- Fairness repair innovation must reduce violations or penalty under controlled cost increase.

Immediate actions:
- Expose min-ratio and fairness slack fields before training or claiming fairness action-space headroom.

### Slice E — Evaluator/checker/budget integrity

Files:
- `solver/src/setp_solver/cost.py`
- `solver/src/setp_solver/check.py`
- `solver/src/setp_solver/search/evaluation.py`
- all runners that call `evaluate`, `check_solution`, `EvalBudget`

Invariants:
- Protected semantics are read-only unless user explicitly approves.
- All algorithm comparisons must use the same objective/checker and record budget health.
- No result with under-eval, artificial homogenization, AppleDouble hash pollution, stale worker, or mixed-code reference can become paper evidence.

Immediate actions:
- Static grep for direct `evaluate()`/`check_solution()` bypasses, missing prices, missing worker integrity, missing budget ratio, and stale absolute x86/M1 mixing.

## 3. Codex batch plan

Run four workers if possible:

1. Worker DYN: full fixed-code Track24 Stage3 + lifecycle audit + defer feasibility guards.
2. Worker E2: documented exception root cause audit + route-compression/stability probe design.
3. Worker CARBON: carbon operator source audit limited to E2 relevance, no large run.
4. Worker HEALTH: repo-wide evidence hygiene / budget / hash / worker integrity audit.

Each worker must output:
- `metadata.json`
- `raw_runs.csv` or `audit_rows.csv`
- `decision.json`
- `artifact_hashes.json`
- `report.md`
- list of source files read and exact invariants checked.

## 4. Stop / switch rules

- If DYN full fixed-code oracle <2pp or only budget allocation works: switch dynamic DR from main rescue to secondary/future mechanism; do not PPO.
- If E2 route-compression probe improves 100c exceptions and does not harm 150/200c: prioritize E2 main algorithm innovation.
- If carbon is weak for E2 total objective: move carbon to E4/E5 mechanism only.
- If fairness slack is exposed and oracle reduces fairness violations: promote E6 fairness-safe repair as mechanism innovation.

## 5. Naming discipline

No module is an innovation until it passes:
1. source-identified failure;
2. minimal repair;
3. targeted improvement;
4. ablation;
5. multi-instance sanity.

Before that, call it a hypothesis or repair path, not an innovation.
