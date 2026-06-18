# PPO Episode-Safe Parallel Repair Report

## Verdict

- verdict: `WEAK_AFTER_VALID_TRAINING`
- reason: Episode-safe training completed, but PPO did not show the required reward trend plus 100-01 AlphaUCB proximity.
- interpretation: episode fragmentation is fixed, but PPO still underperforms after valid training.

## Training Integrity

- schedule: `episode_bucketed`
- timesteps: `1032192`
- eval_budget: `16000`
- n_envs: `9`
- phase_count: `8`
- episode_safe: `True`
- episode_count: `72`
- monitor_lengths: `[16000]`
- env_eval_rows: `72`
- actual_evals: `[16000]`
- feasible_values: `[1]`

## Evaluation Summary

| split | algorithm | mean | median | best | std | notes |
|---|---:|---:|---:|---:|---:|---|
| formal_10001 | alpha_ucb_env | 4878.331796 | 4848.619848 | 4779.053444 | 90.390117 | evals=16000; viol=0 |
| formal_10001 | ppo_full | 6085.923811 | 6085.923811 | 6085.923811 | 0.000000 | gap_vs_alpha_mean=24.75%; gap_vs_random_mean=27.29%; evals=16000; viol=0 |
| formal_10001 | random_full | 4781.121851 | 4788.890407 | 4739.860025 | 23.251876 | evals=16000; viol=0 |
| held_out | alpha_ucb_env | 3902.509680 | 3951.963415 | 3471.164732 | 147.532304 | evals=16000; viol=0 |
| held_out | ppo_full | 4222.785492 | 4222.785492 | 4222.785492 | 0.000000 | gap_vs_alpha_mean=8.21%; gap_vs_random_mean=19.34%; evals=16000; viol=0 |
| held_out | random_full | 3538.481527 | 3543.015348 | 3454.642943 | 32.909463 | evals=16000; viol=0 |

## Notes

- The originally requested mixed schedule was measured but rejected for the pilot because synchronous heterogeneous bundles produced severe long-tail waiting and no completed episode after the early probe window.
- The pilot used `episode_bucketed` with homogeneous phases and 9 parallel envs, preserving complete 16000-eval episodes while keeping worker parallelism.
- Train split evaluation was not run in this task; the empty train comparison file is an explicit placeholder, not evidence.
- Training `env_eval_counts.csv` does not include worker fingerprint columns; scheduled `ps` probes during the run showed `/opt/anaconda3/bin/python3.13` workers, and both evaluation comparison files record that same system worker in every row.
