# Genuine HGS--RR development package

This directory is an isolated development area for the contract in
`docs/handoff/e2_genuine_hybrid_hgs_rr_contract_20260724.md`.

Current contents implement the isolated A/B/A+B execution bridge without
authorising any formal search:

- exact complete-candidate budget accounting, including infeasible and
  duplicate candidates;
- bidirectional HGS-to-RR and RR-to-HGS lineage proof;
- fail-closed decoder cache identity across instance, city/depot, date,
  vehicle type, parameter authority, fleet authority, and dynamic state;
- six model-specific destroy plans corresponding to cross-depot assignment,
  cross-depot string exchange, CV/EV type change, charge/departure retiming,
  time-window pressure, and dynamic unexecuted-tail rebuilding.
- a non-dominated state frontier for the planned
  depot--vehicle--charge--time decoder;
- an isolated budget-visible copy of the frozen monotone China81 completion
  sequence, so its internal whole-solution checks cannot be hidden behind one
  outer call;
- result-blind registration of one small, one medium, and one large
  development instance across the three regions.
- a reference depot--vehicle--charge decoder, finite-fleet assignment DP,
  route-local cache whose identity includes city/date/tariff/carbon/diesel
  and dynamic state, and an independent regret reconstruction;
- five static China81 RR operations with semantic effect checks, plus the
  frozen-prefix structural contract for the dynamic operation;
- a proxy-only PyVRP 0.12.2 HGS archive generator that excludes unchanged
  initial solutions from descendant evidence;
- an A/B/A+B orchestrator with one shared complete-evaluation ledger per arm,
  a frozen 60/40 A+B evaluation allocation, and a hard bidirectional
  post-injection-gain gate.

The current zero-search gate in `g0_static_semantics_gate_v5/` is deliberately labelled
`REAL_BUNDLE_PREFLIGHT_PENDING`: it does not prove real China81 feasibility,
algorithm quality, or 1+1>2.  Nineteen lightweight tests currently pass.
The next mandatory step is a no-search real-bundle decode/replay gate after
the existing E2 v7 campaign releases memory, followed by preregistered G1.
G1 search is forbidden while that campaign is running.
