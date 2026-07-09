# ReSETP ALNS Full Independence

Updated: 2026-07-09

## Location

`solver/src/setp_solver/algorithms/resetp_alns/`

Public API: `from setp_solver.algorithms.resetp_alns import run_resetp_alns, run_winner_kernel`

## Rule

**Fully independent algorithm package.** No runtime dependency on:

- `Reference Algorithm/ALNS-7.0.0@N-Wouda`
- third-party `alns` package
- shared algorithm implementation files with baselines (private copies under `operators/` / `support/` / `kernel/` / `runtime/`)

Allowed shared **problem referee** only: `cost.py`, `check.py`, `search/evaluation.py`, `prices.py`.

## Provenance

See package `PROVENANCE.md`. Runtime subset adapted from N-Wouda/alns 7.0.0 (MIT). Destroy/repair family follows Ropke–Pisinger ALNS literature. ReSETP innovations: true-repair, route elimination, carbon operators, multi-depot/EV structure, winner-kernel profiles.

## Shims (deprecated)

| Old path | Role |
|----------|------|
| `search/alns_wouda.py` | re-export kernel |
| `search/winner_operators.py` | re-export winner |
| `search/resetp_alns/` | re-export runtime |

Do not add logic to shims.

## Tests

- `solver/tests/test_resetp_alns_full_independence.py`
- `solver/tests/test_resetp_alns_independence.py`

## Follow-on (not done in independence commit)

E2 performance work (beat 2nd place ~5%) must run on **L-main 9 threeshift** after this package; see project-prd-execution-v2 and prior A13/A14 notes. Do not claim wins from pre-independence / mixed-instance T3 CSVs as formal.
