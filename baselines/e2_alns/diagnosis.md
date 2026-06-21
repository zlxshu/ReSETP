# E2 ALNS Phase 0 Diagnosis

Status: `DIAGNOSIS_COMPLETE`

Environment:

- Commit before ALNS code changes: `b1ffa756`
- Python: `/opt/anaconda3/bin/python3.13`
- NumPy: `2.3.5`
- `PYTHONHASHSEED=0`

Scope: this is a short, pre-change engineering probe. It is not a formal T3
comparison and does not support any dominance claim.

## Probe Command

```bash
PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 /opt/anaconda3/bin/python3.13 - <<'PY'
from pathlib import Path
from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel, run_winner_kernel_plus_route_elimination
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES

instances = {
    "L-main": Path("models/data_bundle/generated_instances/E-UK24h-三班-01"),
    "e2-vanilla-100c-01": Path("models/data_bundle/generated_instances/e2_benchmark/vanilla/e2-vanilla-100c-01"),
    "e2-multidepot-100c-01": Path("models/data_bundle/generated_instances/e2_benchmark/multidepot/e2-multidepot-100c-01"),
    "e2-threeshift-150c-01": Path("models/data_bundle/generated_instances/e2_benchmark/threeshift/e2-threeshift-150c-01"),
}
for name, path in instances.items():
    bundle = load_search_bundle(path)
    warm = make_shared_initial_solution(bundle)
    ctx = EvaluationContext(bundle.instance, bundle.carbon_profile)
    print("INSTANCE", name)
    print("warm", model_cost(warm, ctx), len(warm.routes), sum(r.vehicle_type.lower() == "cv" for r in warm.routes), sum(r.vehicle_type.lower() == "ev" for r in warm.routes), len(check_solution(warm, bundle.instance, DEFAULT_PRICES)))
    for label, func in [("legacy", run_winner_kernel), ("route_elim", run_winner_kernel_plus_route_elimination)]:
        result = func(path, config=WinnerKernelConfig(seed=1, eval_budget=128, max_runtime_seconds=60.0), initial_solution=warm)
        sol = result["best_solution"]
        print(label, result["best_cost"], result["evaluations"], result["elapsed_seconds"], len(sol.routes), sum(r.vehicle_type.lower() == "cv" for r in sol.routes), sum(r.vehicle_type.lower() == "ev" for r in sol.routes), result["violation_count"])
PY
```

LNS spot check used the same environment and `eval_budget=128` on `L-main` and
`e2-vanilla-100c-01`.

## Short Probe Results

| instance | algorithm | cost | evals | seconds | routes | CV | EV | violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| L-main | warm | 9666.358832 | 0 | - | 65 | 64 | 1 | 0 |
| L-main | legacy winner | 8828.376422 | 128 | 7.346 | 65 | 13 | 52 | 0 |
| L-main | route elimination only | 8828.376422 | 128 | 4.427 | 65 | 13 | 52 | 0 |
| L-main | LNS baseline | 8281.354949 | 128 | 13.067 | 67 | 67 | 0 | 0 |
| e2-vanilla-100c-01 | warm | 7550.193904 | 0 | - | 33 | 32 | 1 | 0 |
| e2-vanilla-100c-01 | legacy winner | 7063.684065 | 128 | 1.118 | 32 | 31 | 1 | 0 |
| e2-vanilla-100c-01 | route elimination only | 7063.684065 | 128 | 1.113 | 32 | 31 | 1 | 0 |
| e2-vanilla-100c-01 | LNS baseline | 6120.866053 | 128 | 3.942 | 34 | 34 | 0 | 0 |
| e2-multidepot-100c-01 | warm | 6657.994082 | 0 | - | 35 | 34 | 1 | 0 |
| e2-multidepot-100c-01 | legacy winner | 5348.647179 | 128 | 3.485 | 34 | 34 | 0 | 0 |
| e2-multidepot-100c-01 | route elimination only | 5348.647179 | 128 | 3.471 | 34 | 34 | 0 | 0 |
| e2-threeshift-150c-01 | warm | 9641.119825 | 0 | - | 50 | 49 | 1 | 0 |
| e2-threeshift-150c-01 | legacy winner | 9096.401203 | 128 | 1.645 | 50 | 29 | 21 | 0 |
| e2-threeshift-150c-01 | route elimination only | 9320.028926 | 128 | 2.644 | 50 | 30 | 20 | 0 |

## Diagnosis

The bottleneck is still consistent with the prompt: on all-CV-favorable
landscapes, the current winner can stay in a mixed or EV-heavy basin while LNS
rebuilds into all-CV solutions. `L-main` and `e2-vanilla-100c-01` both show this
in a small-budget probe: LNS returns all-CV solutions and lower cost, while the
legacy winner remains EV-heavy or keeps an EV route.

Route elimination by itself is not a safe default. At 128 eval it is neutral on
`L-main`, `e2-vanilla-100c-01`, and `e2-multidepot-100c-01`, and worse on
`e2-threeshift-150c-01`. This matches the historical warning in
`alns-crush-root-cause.md`: the literature components should be exposed as
flags and selected by E2 ablation, not silently promoted.

The safe Stage 2 implementation is therefore:

- keep `run_winner_kernel()` as a legacy anchor path with Prompt-1 add-ons off;
- add an explicit E2 ALNS final/experimental entry point with literature flags
  visible in the result manifest;
- run E2 ablation before treating any component set as the formal primary;
- rerun the legacy 100-01 anchor if any shared winner path changes.

## Literature Mapping

- True route-cost repair: Ropke-Pisinger style regret/greedy repair scored by
  the common ReSETP evaluator, implemented through the existing
  `SETP_ALNS_CRUSH_TRUE_REPAIR` flag.
- Route elimination and large-q destroy: Gao-style LNS/GLNS neighborhood and
  Ropke-Pisinger/Wu adaptive large neighborhood behavior, implemented through
  `SETP_ALNS_CRUSH_ROUTE_ELIMINATION` and `SETP_ALNS_CRUSH_ADAPTIVE_Q`.
- Non-hillclimbing acceptance: Wu/Ropke-Pisinger ALNS acceptance family, exposed
  through the existing `SETP_ALNS_CRUSH_TRUE_ACCEPTANCE` flag.
- Embedded bounded local search: VNS/RVND-style route polishing, exposed through
  `SETP_ALNS_CRUSH_LOCAL_SEARCH`.

