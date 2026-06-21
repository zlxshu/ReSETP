# E2 ALNS SA Acceptance Validation

Status: `PASS_CODE_AND_LEGACY_ANCHOR`

Code commit: `3cfd4035`

Environment:

- Python: `/opt/anaconda3/bin/python3.13`
- NumPy: `2.3.5`
- `PYTHONHASHSEED=0`
- Branch: `codex/reporting-pipeline`

## Regression Tests

Command:

```bash
PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m unittest solver.tests.test_alns_crush_v2
```

Stdout:

```text
...........
----------------------------------------------------------------------
Ran 11 tests in 2.432s

OK
```

Command:

```bash
PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m unittest solver.tests.test_metaheuristic_baselines
```

Stdout:

```text
.s..
----------------------------------------------------------------------
Ran 4 tests in 8.215s

OK (skipped=1)
```

## Runner Smoke

Command:

```bash
PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m setp_solver.search.e2_alns_sa_acceptance --instances e2-threeshift-50c-01 --seeds 1 --eval-budget 32 --runtime-override 30 --workers 1 --output-dir baselines/e2_alns/sa_acceptance_smoke
```

Stdout:

```text
GATE E2_ALNS_SA_ACCEPTANCE {"gate": "HALT_SA_ACCEPTANCE_INCONCLUSIVE", "manifest": "baselines/e2_alns/sa_acceptance_smoke/sa_manifest.json", "elapsed_seconds": 4.614047583992942}
```

The smoke directory was removed after confirming the runner wrote raw rows,
summary rows, verdict JSON, markdown, and convergence CSVs. It is not a formal
gate result.

## Legacy Anchor Guard

Command:

```bash
SETP_ALNS_PARALLEL_WORKERS=4 PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 -m setp_solver.search.winner_restoration run-current --output-dir baselines/e2_alns/sa_acceptance_legacy_anchor --seeds 1-10 --eval-budget 16000 --max-runtime-seconds 900
```

Stdout:

```text
GATE WINNER_RESTORATION run-current {"gate": "PASS_CURRENT_RUN_CLASSIFIED", "summary": {"seed_count": 10, "mean_current_total_cost": 4878.331796187524, "median_current_total_cost": 4848.619847811227, "best_current_total_cost": 4779.053444002934, "std_current_total_cost": 95.27954961466529, "mean_gold_total_cost": 4878.331796187524, "mean_total_delta": 0.0, "median_total_delta": 0.0, "mean_route_count": 32.3, "mean_gold_route_count": 32.3, "mean_route_count_delta": 0.0, "zero_violation_count": 10}, "classification": {"classification": "not_regressed", "mean_total_delta": 0.0, "mean_route_count_delta": 0.0, "route_high_count": 0, "mean_cost_fix_delta": 0.0, "mean_cost_km_delta": 0.0, "cost_fix_explained_share": 0.0, "cost_km_explained_share": 0.0, "vehicle_changed_count": 0, "charging_changed_count": 0, "static_mismatch_count": 0, "static_mismatches": [], "conclusion": "Current winner is not worse than gold on mean; restoration should not change search logic without more evidence."}}
```

Anchor result:

- Mean current/gold total cost: `4878.331796187524` / `4878.331796187524`
- Seed 2 / best current total cost: `4779.053444002934`
- Mean delta: `0.0`
- Zero violations: `10/10`
- Classification: `not_regressed`

Conclusion: 09c SA-acceptance code does not move the legacy `run_winner_kernel()`
anchor. Stage 3-5 remain blocked until the full 09c SA-vs-LNS gate is run and
passes.
