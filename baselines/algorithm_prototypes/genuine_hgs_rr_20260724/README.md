# Genuine HGS--RR development package

This directory is an isolated development area for the contract in
`docs/handoff/e2_genuine_hybrid_hgs_rr_contract_20260724.md`.

Current contents implement only the parts that can be verified without
running search:

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

This is not yet a runnable algorithm and must not be cited as one.  Seven
lightweight contract tests currently pass.  The next implementation step is
the model-aware repair/decoder and the epoch bridge.  G1 search is forbidden
while the existing E2 v7 formal campaign is running.
