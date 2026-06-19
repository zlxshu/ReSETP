# Metaheuristic Baseline Audit

Commit at audit start: `a5ed83b`

## Environment

- Repository root: `/Volumes/移动硬盘（512G）/ReSETP`
- Branch: `codex/reporting-pipeline`
- Required interpreter: `/opt/anaconda3/bin/python3.13`
- Verified Python: `3.13.9`
- Verified numpy: `2.3.5`
- Verified scipy: `1.16.3`

The working tree was already dirty before this baseline task started. Existing modified and untracked files are treated as user-owned state and are not part of this implementation unless explicitly staged by this task.

## Protected Truth Sources

The protected model/check/evaluation files exist and have no task-start diff:

- `solver/src/setp_solver/cost.py`
- `solver/src/setp_solver/check.py`
- `solver/src/setp_solver/search/evaluation.py`

This task must not change their objective or constraint semantics.

## Verified Core Interfaces

- `solver/src/setp_solver/search/candidates.py`
  - `make_shared_initial_solution(bundle)` exists and builds the shared feasible warm start via existing construction, charging repair, and `check_solution`.
  - `run_candidate(...)` exists, but its legacy GA/VNS/SA paths are W1 smoke adapters and are not paper-grade baselines for this task.
- `solver/src/setp_solver/search/evaluation.py`
  - `EvalBudget.record()` increments full candidate evaluations.
  - `penalized_obj()` records budgeted complete-candidate evaluations.
  - `model_cost()` does not consume the search budget and is only suitable for final unpenalized reporting.
- `solver/src/setp_solver/search/winner_operators.py`
  - `run_winner_kernel(...)` exists and is the official ALNS winner-kernel entry point.
- `solver/src/setp_solver/search/alns_crush.py`
  - `INSTANCE_DIRS` contains `100-01-24h`, `L-main`, `Scale-150`, and `Scale-200`.
- `solver/src/setp_solver/search/alns_crush_v2.py`
  - The existing V2 fairness runner defaults to `100-01-24h` and `L-main` only.

## Instances

The following generated instances are present and should be included by the new runner when `--instances all` is requested:

- `100-01-24h`: `models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113`
- `L-main`: `models/data_bundle/generated_instances/E-UK24h-三班-01`
- `Scale-150`: `models/data_bundle/generated_instances/E-UK24h-三班-150`
- `Scale-200`: `models/data_bundle/generated_instances/E-UK24h-三班-200`

Reports must separate core instances (`100-01-24h`, `L-main`) from scale instances (`Scale-150`, `Scale-200`).

## Existing Reference Material

Local `Reference Algorithm/` contains:

- GA framework material: `GeneticAlgorithmPython-3.6.0@ahmedfgad`
- TSP/VNS reference material: `VNS@Valdecy`
- scikit-opt GA/PSO/ACO/SA framework material: `scikit-opt-0.6.5@guofei9987`
- ALNS framework material: `ALNS-7.0.0@N-Wouda`, `ALNS@wangqianlongucas`
- DR-ALNS reference material: `DR-ALNS@RobbertReijnen`

No directly adaptable TS implementation was found in the repository or `Reference Algorithm/`. Per task boundary, TS is skipped and no substitute baseline is introduced.

## Baseline Provenance Classification

- `GA`: implement from Narayanan et al. arXiv:2204.05545 / provided §2.3 transcription.
- `PSO`: implement the provided discrete VRPTW-PSO transcription; scikit-opt PSO is continuous and only a formula reference.
- `VNS`: implement Woller et al. arXiv:2511.09570 style VNS; Valdecy TSP-VNS is not directly adapted.
- `ACO`: implement transcript-backed IACO design from He Meiling et al. 2023.
- `GA-VNS`: implement memetic composition of this task's GA and VNS.
- `LNS`: implement transcript-backed GLNS design from Gao Jiaojiao et al. 2024.
- `GWO`: implement transcript-backed HGWO design from Ma Xiangli et al. 2025.
- `IWD`: implement transcript-backed IIWD design from Zhang Jingwen et al. 2025.

## Fairness Requirements

All formal baseline rows must:

- Use the shared warm start from `make_shared_initial_solution`.
- Decode/search through existing ReSETP construction, insertion, EV charging repair, and feasibility utilities.
- Score complete candidate solutions via `EvaluationContext` + `EvalBudget` + `score_candidate`/`penalized_obj`.
- Stop only after `actual_evals == 16000` unless the 900-second runtime cap is hit; runtime-under-budget rows are marked `HALT_RUNTIME_UNDER_EVAL` and excluded from win/loss verdicts.
- Require `check_solution(...)` zero violations for comparable results.
- Bind every reported number to the current git commit hash.
