# Reward Misalignment Probe

| split | algorithm | steps | mean reward | accepted | improved best | observed best |
|---|---|---:|---:|---:|---:|---:|
| formal_10001 | alpha_ucb_env | 6144 | 0.130208 | 0.103 | 0.026 | 4783.609 |
| formal_10001 | ppo_full | 6144 | 0.126450 | 1.000 | 0.006 | 6085.924 |
| formal_10001 | random_full | 6144 | 0.172693 | 0.367 | 0.028 | 4816.193 |
| held_out | alpha_ucb_env | 6144 | 0.111491 | 0.075 | 0.022 | 3941.851 |
| held_out | ppo_full | 6144 | 0.180262 | 1.000 | 0.011 | 4222.785 |
| held_out | random_full | 6144 | 0.193974 | 0.341 | 0.030 | 3615.060 |
| train0 | alpha_ucb_env | 6144 | 0.152181 | 0.053 | 0.030 | 3575.875 |
| train0 | ppo_full | 6144 | 0.163587 | 1.000 | 0.010 | 4467.097 |
| train0 | random_full | 6144 | 0.205231 | 0.361 | 0.033 | 3639.199 |

Interpretation: high accepted/immediate reward with poor final cost is a reward-misalignment warning, not a training success.
