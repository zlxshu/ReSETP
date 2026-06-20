# Metaheuristic Baselines HALT Report

One-line conclusion: no ALNS-vs-8-baseline win/lose/tie claim is valid yet for `100-01-24h`, `L-main`, `Scale-150`, or `Scale-200`; the 8 baselines are implemented and pass zero-violation small-budget tests, but the current implementation is too slow to guarantee `actual_evals=16000` within 900s, so the formal comparison is halted.

## What Was Implemented

`solver/src/setp_solver/search/metaheuristic_baselines.py` now exposes `run_metaheuristic_baseline(algorithm, bundle_dir, seed, eval_budget, max_runtime_seconds, initial_solution)` for GA, PSO, VNS, ACO, GA-VNS, LNS, GWO, and IWD. All complete candidate scoring goes through `EvaluationContext(..., EvalBudget(limit=target,target=target))` and `score_candidate()`. `model_cost()` is used only for unpenalized reporting, not budget accounting.

`solver/src/setp_solver/search/metaheuristic_baseline_runner.py` now provides the comparison runner with hard environment checks for `/opt/anaconda3/bin/python3.13` and numpy `2.3.5`. The runner can serialize raw runs, comparison rows, Wilcoxon rows, verdicts, reports, manifests, and solutions. A small runner smoke test passed after fixing the fair-SA status normalization.

`solver/tests/test_metaheuristic_baselines.py` verifies the gold environment and confirms all 8 baselines return zero-violation solutions at a small evaluation budget.

## Provenance By Commit

- `6d5446d` records the audit in `baselines/audit.md`.
- `a6a233d` adds the shared baseline harness and runner.
- `3305a10` adds GA.
- `ca36e8a` adds PSO.
- `a199a8b` adds VNS.
- `4835b5a` adds ACO.
- `8fb5c49` adds GA-VNS.
- `e7646d0` adds LNS.
- `bbf5325` adds GWO.
- `f1b8849` adds IWD.
- `b4749bc` adds the unit tests.
- `c02045f` fixes runner status normalization and removes duplicate scoring overhead before the speed probe.

## Verification Commands

Environment and tests:

```text
PYTHONPATH=solver/src /opt/anaconda3/bin/python3.13 -m unittest solver.tests.test_metaheuristic_baselines
```

Stdout:

```text
.s.
----------------------------------------------------------------------
Ran 3 tests in 8.790s

OK (skipped=1)
```

Runner smoke command:

```text
PYTHONPATH=solver/src SETP_META_PARALLEL_WORKERS=1 /opt/anaconda3/bin/python3.13 -m setp_solver.search.metaheuristic_baseline_runner all --repo-root . --output-dir baselines/smoke_runner --instances 100-01-24h --seeds 1 --eval-budget 4 --max-runtime-seconds 120 --algorithms GA,PSO
```

Stdout:

```text
GATE METAHEURISTIC_BASELINES OK {"gate": "OK", "manifest": "baselines/smoke_runner/manifest.json", "elapsed_seconds": 7.0073081250011455}
```

Speed probe command:

```text
PYTHONPATH=solver/src /opt/anaconda3/bin/python3.13 - <<'PY'
import time
from setp_solver.search.metaheuristic_baselines import BASELINE_ALGORITHMS, run_metaheuristic_baseline
p='models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113'
for alg in BASELINE_ALGORITHMS:
    t=time.perf_counter()
    r=run_metaheuristic_baseline(alg, p, seed=1, eval_budget=100, max_runtime_seconds=300)
    dt=time.perf_counter()-t
    print(alg, r.status, r.evals, round(dt,3), round(r.evals/dt,3), r.best_cost)
PY
```

Stdout:

```text
GA OK 100 11.129 8.986 6331.298733608956
PSO OK 100 9.112 10.974 6331.298733608956
VNS OK 100 9.895 10.106 6331.298733608956
ACO OK 100 11.076 9.029 6331.298733608956
GA-VNS OK 100 9.618 10.397 6331.298733608956
LNS OK 100 9.06 11.038 5545.80699995476
GWO OK 100 14.911 6.707 6331.298733608956
IWD OK 100 25.254 3.96 6331.298733608956
```

Anchor speed command:

```text
PYTHONPATH=solver/src /opt/anaconda3/bin/python3.13 - <<'PY'
import time
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, run_candidate
from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel
p='models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113'
b=load_search_bundle(p)
w=make_shared_initial_solution(b)
for name in ['fair-SA','winner']:
    t=time.perf_counter()
    if name=='fair-SA':
        r=run_candidate('scikit-opt-SA', p, seed=1, eval_budget=100, max_runtime_seconds=300, initial_solution=w)
        evals=r.evals; cost=r.best_cost; status=r.status
    else:
        r=run_winner_kernel(p, config=WinnerKernelConfig(seed=1, eval_budget=100, max_runtime_seconds=300), initial_solution=w)
        evals=r['evaluations']; cost=r['best_cost']; status='OK' if r['feasible'] else 'BAD'
    dt=time.perf_counter()-t
    print(name, status, evals, round(dt,3), round(evals/dt,3), cost)
PY
```

Stdout:

```text
fair-SA feasible 100 0.561 178.119 6331.298733608956
winner OK 100 6.386 15.659 5406.294961824951
```

## HALT Reason

The formal requirement is `16000 / 900 = 17.78` complete evaluations per second per run. The current 8 baseline implementations are below that threshold on the 100-eval gate. The slowest is IWD at about 3.96 eval/s, and the best baseline speed observed is about 11.04 eval/s. Running the requested four instances, 10 seeds, and 8 baselines now would produce under-budget runs or require far more than the allowed runtime, so those outputs would be methodologically invalid.

Therefore `comparison_table.csv`, `wilcoxon.csv`, and `verdicts.csv` are explicit HALT artifacts, not dominance evidence. No Wilcoxon p-values, paired wins, or ALNS superiority claims are reported.

## Required Next Fix

The implementation needs a performance pass before the formal run. The likely target is the giant-tour decode path: many algorithms repeatedly call `random_key_to_solution()`, which is much slower than the existing fair-SA adapter and still slower than winner-kernel ALNS. The next revision should move more candidate generation onto route-local destroy/repair and avoid repeated full reconstruction where the paper design permits an equivalent route-set mutation.
