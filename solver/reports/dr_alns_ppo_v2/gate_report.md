# DR-ALNS-PPO v2 Gate Report

## Gate

`HALT_BASELINE_WIRING`

PPO training was not started. The RL lane now imports the winner operator module,
but the current official winner entry point does not reproduce the Phase1/TaskA
winner-kernel reference before training.

## What Passed

- `worker.py` no longer executes local `operator_manual` destroy/repair paths.
- `env.py` action space is winner-backed: `MultiDiscrete([6, 3, 10, 100])`
  for `ppo_full`, and `MultiDiscrete([6, 3])` for operator-only/kernel-default
  controls.
- Step traces include `operator_base_id=winner_kernel_v1`,
  `winner_operator_module=setp_solver.search.winner_operators`, winner
  destroy/repair names, threshold, q data, and actual eval deltas.
- Tiny-budget preflight showed `alpha_ucb_env` and `official_winner_kernel`
  agree exactly at 20 evals on E-UK100_01 seed1.

## Blocking Evidence

Expected reference from `solver/reports/alns_crush_v3/taskA_step_api_audit.json`:

- bundle: E-UK100_01
- seed: 2
- eval_budget: 16000
- official `run_winner_kernel` best_cost: 4779.053444002934
- operator_base_id: winner_kernel_v1
- violation_count: 0

Observed with fixed hash seed:

```text
PYTHONHASHSEED=0 PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m dr_alns_ppo.evaluate_policy --manifest solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json --split formal_eval --bundle-filter E-UK100_01 --algorithms official_winner_kernel,alpha_ucb_env --eval-budget 16000 --seeds 2 --output-dir solver/reports/dr_alns_ppo_v2/self_check_100_01_hashseed0_seed2 --jobs 1
```

`solver/reports/dr_alns_ppo_v2/self_check_100_01_hashseed0_seed2/comparison.partial.csv`:

| algorithm | seed | best_obj | actual_evals | candidate_scores | operator_base_id | violation_count |
|---|---:|---:|---:|---:|---|---:|
| official_winner_kernel | 2 | 4909.530249672552 | 16000 | 16000 | winner_kernel_v1 | 0 |

This is zero-violation and budget-complete, but it is not the Phase1/TaskA
reference value. That blocks PPO self-check and training.

## Aborted Batch

The first 100-01 10-seed batch was stopped after completed official rows showed
the same problem. Completed rows are preserved in
`solver/reports/dr_alns_ppo_v2/self_check_100_01/comparison.partial.csv`.

Completed official rows:

| seed | official_winner_kernel best_obj |
|---:|---:|
| 1 | 5954.73383353001 |
| 2 | 4909.530249672552 |
| 3 | 5773.3819464782055 |
| 4 | 6024.488077952977 |
| 5 | 6062.672019121483 |

For each completed seed, `alpha_ucb_env` matched the official kernel value,
which suggests the PPO environment is calling the same current winner module.
The blocker is the current winner baseline itself versus the recorded Phase1
winner reference.

## Verification

```text
PYTHONPATH=solver/rl:solver/src:models/src solver/rl/.venv/bin/python -m pytest solver/rl/tests -q
```

Result: `43 passed in 5.96s`.

```text
PYTHONPATH=solver/src:models/src python -m unittest discover -s solver/tests -p 'test_*.py'
```

Result: `Ran 141 tests in 325.243s - OK`.

## Next Required Action

Before PPO smoke or pilot training, reconcile the current importable
`setp_solver.search.winner_operators.run_winner_kernel` with the Phase1/TaskA
winner reference. Until that gate passes, DR-ALNS-PPO v2 must remain untrained.
