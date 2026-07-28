# Track22 Stage1 Instrument Health Gate

Verdict: `PASS_INSTRUMENT`

Worker: `C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe`; Python `3.13.12`; NumPy `2.3.5`.

Bundle: `models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113`
Seed: `901`; eval budget: `300`; max runtime seconds: `900`.

| Metric | Value | Gate |
|---|---:|---|
| warm_start_cost | 4079.030056 | reference |
| best_cost | 2627.730354 | 2500-2700 |
| actual_evals | 300 | >0 |
| unique_solution_count | 11 | >1 |
| best_update_count | 10 | >0 |
| violation_count | 0 | 0 |
| improvement_vs_warm_pct | 35.579529% | informative |

Checks:
- `worker_py313`: True
- `worker_numpy_235`: True
- `best_cost_2500_2700`: True
- `unique_solution_count_gt_1`: True
- `best_update_count_gt_0`: True
- `zero_violations`: True
- `evals_positive`: True
