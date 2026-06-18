# Reward Signal Probe

| split | algorithm | steps | nonzero reward rate | improved best | improved current | accepted | terminal | final evals |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| formal_10001 | alpha_ucb_env | 128 | 0.109375 | 14 | 14 | 52 | 0 | 128 |
| formal_10001 | ppo_full | 128 | 0.531250 | 11 | 68 | 128 | 0 | 128 |
| formal_10001 | random_full | 128 | 0.304688 | 30 | 39 | 68 | 0 | 128 |
| train_first | alpha_ucb_env | 128 | 0.078125 | 10 | 10 | 10 | 0 | 128 |
| train_first | ppo_full | 128 | 0.578125 | 21 | 74 | 128 | 0 | 128 |
| train_first | random_full | 128 | 0.273438 | 31 | 35 | 56 | 0 | 128 |

Interpretation: this probe samples short traces only. It tests reward observability, not algorithm quality.
