# ReSETP ALNS — Provenance & Independence

**Status:** Independent first-party algorithm package (2026-07-09).  
**Location:** `solver/src/setp_solver/algorithms/resetp_alns/`  
**Public API:** `setp_solver.algorithms.resetp_alns` (`run_resetp_alns` / `run_winner_kernel`)

## Not a dependency

This package does **not** import:

- `Reference Algorithm/ALNS-7.0.0@N-Wouda`
- the third-party `alns` PyPI package
- any path injection of open-source ALNS trees

Upstream N-Wouda remains under `Reference Algorithm/` **for literature reference only**.

## Open-source ancestry (MIT — N-Wouda/alns 7.0.0)

Minimal runtime symbols were originally adapted from N-Wouda/alns 7.0.0 and are now **vendored inside** `runtime/`:

| Symbol | Role |
|--------|------|
| `Outcome` | Accept outcome enum |
| `HillClimbing` | Acceptance |
| `RecordToRecordTravel` | Acceptance |
| `SimulatedAnnealing` | Acceptance |
| `AlphaUCB` (+ project extensions) | Operator selection |
| `update()` | Selector weight update helper |

License: MIT (N-Wouda/alns). See upstream LICENSE in `Reference Algorithm/ALNS-7.0.0@N-Wouda/`.

## Literature mechanism lineage (not code copy)

Ropke & Pisinger ALNS / LNS destroy–repair family:

- Destroy: random / Shaw related / worst / route-level variants
- Repair: greedy / regret-2 / regret-3
- Adaptive operator weights + SA-style acceptance

## ReSETP first-party innovations (project code)

- Cost-aware true-repair scoring (`TRUE_REPAIR`)
- Route elimination / adaptive removal size
- Carbon-related destroy & low-carbon charging repair
- Multi-depot + CV/EV + charging feasibility structure for ReSETP
- Winner-kernel flag profiles (`alns_e2_throughput`, local search, balanced selector variants, …)
- Private copies of repair / local search / strong-bridge (not shared with baseline modules)

## Shared problem referee (allowed; not algorithm components)

| Module | Why shared |
|--------|------------|
| `setp_solver.cost` | Single objective truth |
| `setp_solver.check` | Single feasibility truth |
| `setp_solver.search.evaluation` | Shared eval budget / scoring protocol |
| `setp_solver.prices` | Scenario prices |

## Deprecated shims

`setp_solver.search.alns_wouda`, `setp_solver.search.winner_operators`, and `setp_solver.search.resetp_alns` re-export this package only. Do not add logic there.

## Independence gate

- Main algorithm path must not `import alns` or touch `Reference Algorithm/ALNS-7.0*`.
- Formal entry: `algorithms.resetp_alns`.
- Baselines keep their own modules under `search/metaheuristic_baselines.py` and `search/feasible_repair.py` (baseline health); ALNS uses private copies under this package.
