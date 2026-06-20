---
name: algorithm-pivot-ca-alns
description: "Major algorithm-layer pivot — drop fake DR-ALNS, build Carbon-Aware ALNS on the Wouda library; rerun all main experiments"
metadata: 
  node_type: memory
  type: project
  originSessionId: c7e19b75-f4af-454a-9cdd-0285773bf61c
---

2026-06-14 decision after C1/C2 diagnoses. **The algorithm layer was broken and is being rebuilt.**

**What was wrong:** `PRIMARY_ALGORITHM="ALNS-Wouda"` (candidates.py:36) generated ALL main results (T4/T5/T7/T8/T9 via E1/E3/E4/E6/E7) but it ranked 倒数第2 in T3 (15.3% gap). Diagnosis: NOT a real algorithm weakness — an integration/benchmark-fairness bug. (a) Eval-budget unfair: 16000 eval = ~300 Wouda library iterations vs ~16000 hand-written moves. (b) `vehicle_type_swap` only swaps CV→EV (single direction) → forces expensive EV structure. (c) operators too narrow (single-customer removal, CV-only insertion). The "DR-ALNS win" (1.8%) is an artifact — it collapses to all-CV (0 EV), which is genuinely cheaper at realistic carbon price (consistent with the carbon-insensitivity finding). Also the repo "DR-ALNS" is a fake — no PPO/RL, just reactive adaptive-weight ALNS; naming is indefensible.

**The pivot (user-approved):**
1. **CA-ALNS = Carbon-Aware ALNS, built ON the Wouda `alns` library.** Fix budget+operators (P2a, running) → fair vanilla baseline; add carbon-aware/charging-timing-aware destroy-repair operators (P2b = the real algorithm contribution, tied to time-varying grid carbon); optional lightweight online-learning operator selector with a state/action interface matching DR-ALNS schema (P2c, also the PPO-upgrade bridge).
2. **PPO-DR-ALNS: NOT abandoned, deferred to future work.** Keep reference repo + the C2 state/action design for a later paper upgrade. C2 verdict: feasible but high-risk (must retrain, dependency hell sb3/torch/gym, millions of env steps, weak "application novelty").
3. **Drop the "DR-ALNS" name from the main paper** (rename to CA-ALNS / Reactive-ALNS as honest).

**Accepted consequence (P3):** switch PRIMARY to the strong ALNS → **rerun E1–E7**, regenerate all tables/figures, **all carbon numbers change**. Story gets CLEANER not weaker: low carbon price → near all-CV, EVs emerge only at ~30× price. The §4.6 carbon text already written (1935 kg two-layer, ~50 EV at 1×, etc.) is **provisional** and must be renumbered after the rerun. See [[deferred-instance-robustness]].

**2026-06-15 UPDATE — direction sharpened.** The "fix budget/operators" attempts (P2a/P2a-Iter/A/B) all FAILED to make ALNS beat SA: even budget-fair, the strengthened ALNS-Wouda stayed ~18-19% while DR-ALNS(regret) and SA tie at ~2%. User demands ALNS **CRUSH** SA (huge gap), and **rejected** an SP/set-partitioning "global recombination" idea as off-target ("牛头不对马嘴") — the fix must be **ALNS-internal**. New root-cause thesis in [[alns-crush-root-cause]]: dominant cost is route-count (£80×routes ≈63% of cost); crush = route minimization via large destroy-repair (which SA structurally can't do), blocked by 4 ALNS-internal defects (distance-not-cost repair scoring, q too small to empty a route, no route-elimination operator, acceptance is literally SA, plus no embedded local search). Carbon-aware operators (P2b) come AFTER ALNS is strong. Lesson learned: do NOT trust half-finished/unverified workflow outputs.
